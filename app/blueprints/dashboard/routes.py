# app/blueprints/dashboard/routes.py
import logging
from flask import Blueprint, render_template, redirect, url_for, flash, current_app
from sqlalchemy import func, distinct
from app.models.tables import Agendamento, User  # type: ignore
from app.extensions import db
from flask_login import login_required, current_user
from datetime import datetime, date, time, timedelta
import pytz
import locale

# Cria o Blueprint 'dashboard' com prefixo /dashboard
bp = Blueprint('dashboard', __name__, url_prefix='/dashboard')

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def _range_do_dia_utc(dia_dt: date):
    inicio = datetime.combine(dia_dt, time.min)
    fim = inicio + timedelta(days=1)
    return inicio, fim


def _eh_agendamento_valido(ag) -> bool:
    nome_cli = (getattr(ag, 'nome_cliente', '') or '').lower()
    nome_srv = (getattr(ag.servico, 'nome', '') or '').lower() if getattr(ag, 'servico', None) else ''
    return 'bloqueio' not in nome_cli and 'bloqueio' not in nome_srv


@bp.route('/')
@login_required
def index():
    """Exibe o dashboard executivo da barbearia/studio para admins,
       ou redireciona Super Admins para o painel deles."""

    if hasattr(current_user, 'role') and current_user.role == 'super_admin':
        return redirect(url_for('superadmin.listar_barbearias'))

    if not hasattr(current_user, 'barbearia_id') or not current_user.barbearia_id:
        flash('Erro: Usuário admin inválido ou não associado a uma barbearia.', 'danger')
        return redirect(url_for('main.login'))

    barbearia_id_logada = current_user.barbearia_id

    sao_paulo_tz = pytz.timezone('America/Sao_Paulo')
    hoje_local = datetime.now(sao_paulo_tz).date()

    inicio_hoje_db, fim_hoje_db = _range_do_dia_utc(hoje_local)

    # Intervalo da semana atual (Segunda-feira 00:00 até Domingo 23:59:59)
    inicio_semana_date = hoje_local - timedelta(days=hoje_local.weekday())
    fim_semana_date = inicio_semana_date + timedelta(days=7)
    inicio_semana_db = datetime.combine(inicio_semana_date, time.min)
    fim_semana_db = datetime.combine(fim_semana_date, time.min)

    try:
        # 1. Buscar agendamentos de hoje (com serviço e profissional carregados)
        proximos_agendamentos_db = (
            Agendamento.query.options(
                db.joinedload(Agendamento.servico),
                db.joinedload(Agendamento.profissional)
            )
            .filter(
                Agendamento.barbearia_id == barbearia_id_logada,
                Agendamento.data_hora >= inicio_hoje_db,
                Agendamento.data_hora < fim_hoje_db
            )
            .order_by(Agendamento.data_hora.asc())
            .all()
        )

        # 2. Buscar agendamentos da semana atual para KPIs executivos
        agendamentos_semana_db = (
            Agendamento.query.options(
                db.joinedload(Agendamento.servico)
            )
            .filter(
                Agendamento.barbearia_id == barbearia_id_logada,
                Agendamento.data_hora >= inicio_semana_db,
                Agendamento.data_hora < fim_semana_db
            )
            .all()
        )

        # 3. Calcular indicadores executivos com segurança (ignorando bloqueios administrativos)
        agendamentos_validos_hoje = [ag for ag in proximos_agendamentos_db if _eh_agendamento_valido(ag)]
        agendamentos_validos_semana = [ag for ag in agendamentos_semana_db if _eh_agendamento_valido(ag)]

        agendamentos_hoje_count = len(agendamentos_validos_hoje)
        agendamentos_semana_count = len(agendamentos_validos_semana)

        receita_hoje_val = sum(
            float(ag.servico.preco)
            for ag in agendamentos_validos_hoje
            if getattr(ag, 'servico', None) and getattr(ag.servico, 'preco', None) and float(ag.servico.preco) > 0
        )

        receita_semana_val = sum(
            float(ag.servico.preco)
            for ag in agendamentos_validos_semana
            if getattr(ag, 'servico', None) and getattr(ag.servico, 'preco', None) and float(ag.servico.preco) > 0
        )

        # 4. Contar Clientes Únicos (Total da Loja)
        total_clientes_count = (
            db.session.query(func.count(distinct(Agendamento.telefone_cliente)))
            .filter(
                Agendamento.barbearia_id == barbearia_id_logada,
                Agendamento.telefone_cliente != '00000000000'
            )
            .scalar()
            or 0
        )

        # 5. Formatar horários para a timeline (preservando todos os itens do dia)
        proximos_agendamentos_formatados = []
        for ag in proximos_agendamentos_db:
            hora_formatada = '--:--'
            if ag.data_hora:
                try:
                    hora_formatada = ag.data_hora.strftime('%H:%M')
                except Exception as fmt_e:
                    current_app.logger.warning(f"Erro ao formatar hora {ag.data_hora} para agendamento {ag.id}: {fmt_e}")
            ag.hora_formatada = hora_formatada
            proximos_agendamentos_formatados.append(ag)

        # 6. Formatar data atual para cabeçalho
        try:
            locale.setlocale(locale.LC_TIME, 'pt_BR.UTF-8')
        except locale.Error:
            try:
                locale.setlocale(locale.LC_TIME, 'Portuguese_Brazil.1252')
            except locale.Error:
                locale.setlocale(locale.LC_TIME, '')

        data_hoje_formatada = hoje_local.strftime('%A, %d de %B de %Y').capitalize()

    except Exception as e:
        current_app.logger.error(f"Erro ao buscar dados do dashboard para barbearia {barbearia_id_logada}: {e}", exc_info=True)
        flash('Ocorreu um erro ao carregar os dados do dashboard.', 'danger')
        agendamentos_hoje_count = 0
        agendamentos_semana_count = 0
        receita_hoje_val = 0.0
        receita_semana_val = 0.0
        total_clientes_count = 0
        proximos_agendamentos_formatados = []
        data_hoje_formatada = hoje_local.strftime('%d/%m/%Y')

    return render_template(
        'dashboard.html',
        agendamentos_hoje=agendamentos_hoje_count,
        agendamentos_semana=agendamentos_semana_count,
        receita_hoje=receita_hoje_val,
        receita_semana=receita_semana_val,
        total_clientes=total_clientes_count,
        proximos_agendamentos=proximos_agendamentos_formatados,
        data_hoje=data_hoje_formatada
    )
