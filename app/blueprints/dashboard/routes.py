# app/blueprints/dashboard/routes.py
import logging
from flask import Blueprint, render_template, redirect, url_for, flash, current_app
from sqlalchemy import func, distinct
from app.models.tables import Agendamento, User # Importa modelos necessários
from app.extensions import db
from flask_login import login_required, current_user # Para proteger e filtrar
from datetime import datetime, date, time, timedelta
import pytz # Para formatar a data/hora local

# Cria o Blueprint 'dashboard' com prefixo /dashboard
bp = Blueprint('dashboard', __name__, url_prefix='/dashboard')

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Helper para obter o início e fim do dia (UTC ou naive, como no DB)
def _range_do_dia_utc(dia_dt: date):
    inicio = datetime.combine(dia_dt, time.min)
    fim = inicio + timedelta(days=1)
    return inicio, fim

@bp.route('/')
@login_required
def index():
    """Exibe o dashboard com informações do dia para a barbearia logada."""
    if not hasattr(current_user, 'barbearia_id') or not current_user.barbearia_id:
        flash('Erro: Usuário inválido ou não associado a uma barbearia.', 'danger')
        # Ajuste 'main.login' se seu login estiver em outro blueprint (ex: 'auth.login')
        return redirect(url_for('main.login')) 
        
    barbearia_id_logada = current_user.barbearia_id
    
    # Define o fuso horário de São Paulo para exibição
    sao_paulo_tz = pytz.timezone('America/Sao_Paulo')
    hoje_local = datetime.now(sao_paulo_tz).date() # Pega a data de hoje local
    
    # Calcula início e fim do dia para queries no DB (naive/UTC)
    inicio_hoje_db, fim_hoje_db = _range_do_dia_utc(hoje_local)

    try:
        # 1. Contar Agendamentos de Hoje
        agendamentos_hoje_count = db.session.query(func.count(Agendamento.id)).filter(
            Agendamento.barbearia_id == barbearia_id_logada,
            Agendamento.data_hora >= inicio_hoje_db,
            Agendamento.data_hora < fim_hoje_db
        ).scalar() or 0 # .scalar() retorna o valor ou None, usamos 'or 0'

        # 2. Contar Clientes Únicos (Total da Barbearia)
        total_clientes_count = db.session.query(func.count(distinct(Agendamento.telefone_cliente))).filter(
            Agendamento.barbearia_id == barbearia_id_logada
        ).scalar() or 0

        # 3. Listar Próximos Agendamentos de Hoje
        proximos_agendamentos = Agendamento.query.options(
            db.joinedload(Agendamento.servico), 
            db.joinedload(Agendamento.profissional)
        ).filter(
            Agendamento.barbearia_id == barbearia_id_logada,
            Agendamento.data_hora >= inicio_hoje_db,
            Agendamento.data_hora < fim_hoje_db
        ).order_by(Agendamento.data_hora.asc()).all()

        # Formata a data atual para exibição (ex: "terça-feira, 28 de outubro de 2025")
        # Definindo locale para português do Brasil
        import locale
        try:
            # Tenta definir o locale para pt_BR. UTF-8 é comum em Linux/Render
            locale.setlocale(locale.LC_TIME, 'pt_BR.UTF-8') 
        except locale.Error:
            try:
                # Fallback para Windows (pode não funcionar na Render)
                locale.setlocale(locale.LC_TIME, 'Portuguese_Brazil.1252')
            except locale.Error:
                # Fallback final se nenhum funcionar
                logging.warning("Locale 'pt_BR.UTF-8' ou 'Portuguese_Brazil.1252' não encontrado. Usando formato padrão.")
                locale.setlocale(locale.LC_TIME, '') # Usa o padrão do sistema

        data_hoje_formatada = hoje_local.strftime('%A, %d de %B de %Y').capitalize()

    except Exception as e:
        current_app.logger.error(f"Erro ao buscar dados do dashboard para barbearia {barbearia_id_logada}: {e}", exc_info=True)
        flash('Ocorreu um erro ao carregar os dados do dashboard.', 'danger')
        # Define valores padrão em caso de erro
        agendamentos_hoje_count = 'Erro'
        total_clientes_count = 'Erro'
        proximos_agendamentos = []
        data_hoje_formatada = hoje_local.strftime('%d/%m/%Y') # Formato simples

    return render_template(
        'dashboard.html', 
        agendamentos_hoje=agendamentos_hoje_count,
        total_clientes=total_clientes_count,
        proximos_agendamentos=proximos_agendamentos,
        data_hoje=data_hoje_formatada,
        sao_paulo_tz=sao_paulo_tz # Passa o timezone para o template formatar horas
    )