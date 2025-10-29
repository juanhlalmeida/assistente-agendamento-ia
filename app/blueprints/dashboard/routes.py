# app/blueprints/dashboard/routes.py
import logging
from flask import Blueprint, render_template, redirect, url_for, flash, current_app
from sqlalchemy import func, distinct
from app.models.tables import Agendamento, User # type: ignore
from app.extensions import db
from flask_login import login_required, current_user 
from datetime import datetime, date, time, timedelta
import pytz # 🚀 ADICIONADO IMPORT PYTZ
import locale # Para formatar a data

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
        # Ajuste 'main.login' se seu login estiver em outro blueprint
        return redirect(url_for('main.login')) 
        
    barbearia_id_logada = current_user.barbearia_id
    
    sao_paulo_tz = pytz.timezone('America/Sao_Paulo')
    # Usar UTC para referência do 'agora' pode ser mais robusto na Render
    # hoje_local = datetime.now(sao_paulo_tz).date() 
    hoje_utc = datetime.now(pytz.utc).date() # Data de hoje em UTC
    
    # Usa a data UTC para queries no DB (assumindo DB guarda naive ou UTC)
    inicio_hoje_db, fim_hoje_db = _range_do_dia_utc(hoje_utc) 

    try:
        # 1. Contar Agendamentos de Hoje
        agendamentos_hoje_count = db.session.query(func.count(Agendamento.id)).filter(
            Agendamento.barbearia_id == barbearia_id_logada,
            Agendamento.data_hora >= inicio_hoje_db,
            Agendamento.data_hora < fim_hoje_db
        ).scalar() or 0 

        # 2. Contar Clientes Únicos (Total da Barbearia)
        total_clientes_count = db.session.query(func.count(distinct(Agendamento.telefone_cliente))).filter(
            Agendamento.barbearia_id == barbearia_id_logada
        ).scalar() or 0

        # 3. Listar Próximos Agendamentos de Hoje
        proximos_agendamentos_db = Agendamento.query.options(
            db.joinedload(Agendamento.servico), 
            db.joinedload(Agendamento.profissional)
        ).filter(
            Agendamento.barbearia_id == barbearia_id_logada,
            Agendamento.data_hora >= inicio_hoje_db,
            Agendamento.data_hora < fim_hoje_db
        ).order_by(Agendamento.data_hora.asc()).all()

        # 🚀 CORREÇÃO: Formata a hora AQUI na rota
        proximos_agendamentos_formatados = []
        for ag in proximos_agendamentos_db:
            hora_formatada = '--:--' # Valor padrão
            if ag.data_hora:
                # Assume que data_hora do DB é naive (representando UTC implicitamente ou local do servidor)
                # Torna 'aware' como UTC, depois converte para São Paulo
                try:
                    hora_local_sp = ag.data_hora.replace(tzinfo=pytz.utc).astimezone(sao_paulo_tz)
                    hora_formatada = hora_local_sp.strftime('%H:%M')
                except Exception as fmt_e:
                     current_app.logger.warning(f"Erro ao formatar hora {ag.data_hora} para agendamento {ag.id}: {fmt_e}")
            # Adiciona o atributo formatado ao objeto (ou cria um dicionário)
            # Vamos adicionar ao objeto para manter a estrutura
            ag.hora_formatada = hora_formatada 
            proximos_agendamentos_formatados.append(ag)
        # -----------------------------------------------

        # Formata a data atual para exibição
        # Usa a data local de SP para exibição
        hoje_local_para_display = datetime.now(sao_paulo_tz).date() 
        try:
            locale.setlocale(locale.LC_TIME, 'pt_BR.UTF-8') 
        except locale.Error:
            try:
                locale.setlocale(locale.LC_TIME, 'Portuguese_Brazil.1252')
            except locale.Error:
                logging.warning("Locale 'pt_BR' não encontrado. Usando formato padrão.")
                locale.setlocale(locale.LC_TIME, '') 

        data_hoje_formatada = hoje_local_para_display.strftime('%A, %d de %B de %Y').capitalize()

    except Exception as e:
        current_app.logger.error(f"Erro ao buscar dados do dashboard para barbearia {barbearia_id_logada}: {e}", exc_info=True)
        flash('Ocorreu um erro ao carregar os dados do dashboard.', 'danger')
        agendamentos_hoje_count = 'Erro'
        total_clientes_count = 'Erro'
        proximos_agendamentos_formatados = [] # Usa a lista formatada vazia
        data_hoje_formatada = datetime.now(sao_paulo_tz).date().strftime('%d/%m/%Y') 

    return render_template(
        'dashboard.html', 
        agendamentos_hoje=agendamentos_hoje_count,
        total_clientes=total_clientes_count,
        # Passa a lista com a hora já formatada
        proximos_agendamentos=proximos_agendamentos_formatados, 
        data_hoje=data_hoje_formatada
        # Não precisamos mais passar sao_paulo_tz
    )