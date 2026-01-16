# app/google/blueprint_sync.py
# (CÓDIGO CORRIGIDO E BLINDADO)

import logging
from flask import Blueprint
from sqlalchemy import event
# IMPORTANTE: Importamos Profissional e Servico para buscar manualmente
from app.models.tables import Agendamento, Profissional, Servico
from app.google.google_calendar_service import GoogleCalendarService
from app.extensions import db

# Define o Blueprint para ser carregado no __init__.py
bp = Blueprint('google_sync_worker', __name__)

logger = logging.getLogger(__name__)

def enviar_para_google(mapper, connection, target):
    """
    Esta função roda AUTOMATICAMENTE (Hook) assim que um agendamento é inserido no banco.
    'target' é o objeto Agendamento que acabou de ser criado.
    """
    try:
        logger.info(f"🔄 [SYNC] Novo agendamento detectado (ID: {target.id}). Iniciando carga de dados...")

        # O SQLAlchemy session pode não estar disponível diretamente no 'connection', 
        # então usamos a session global do Flask-SQLAlchemy
        session = db.session

        # ---------------------------------------------------------
        # 1. FORÇAR CARREGAMENTO DO PROFISSIONAL
        # ---------------------------------------------------------
        if target.profissional_id and not target.profissional:
            profissional = session.get(Profissional, target.profissional_id)
            target.profissional = profissional # Reconecta manualmente
        
        if not target.profissional:
            logger.warning(f"⚠️ [SYNC] Abortando: Profissional não encontrado para Agendamento {target.id}")
            return

        # ---------------------------------------------------------
        # 2. FORÇAR CARREGAMENTO DO SERVIÇO (Aqui estava o erro da duração)
        # ---------------------------------------------------------
        if target.servico_id and not target.servico:
            servico = session.get(Servico, target.servico_id)
            target.servico = servico # Reconecta manualmente
            
        if not target.servico:
            logger.warning(f"⚠️ [SYNC] Abortando: Serviço não encontrado para Agendamento {target.id}")
            return

        # ---------------------------------------------------------
        # 3. VERIFICAR BARBEARIA E TOKENS
        # ---------------------------------------------------------
        barbearia = target.profissional.barbearia
        if not barbearia:
            logger.warning("⚠️ [SYNC] Abortando: Profissional sem barbearia vinculada.")
            return

        if not barbearia.google_refresh_token:
            logger.info(f"ℹ️ [SYNC] Google Agenda não conectado para a barbearia '{barbearia.nome_fantasia}'.")
            return

        logger.info(f"📍 [SYNC] Dados OK: {barbearia.nome_fantasia} | Serviço: {target.servico.nome} ({target.servico.duracao} min)")

        # ---------------------------------------------------------
        # 4. ENVIAR PARA O GOOGLE
        # ---------------------------------------------------------
        service = GoogleCalendarService(barbearia)
        google_id = service.create_event(target)
        
        if google_id:
            logger.info(f"✅ [SYNC] SUCESSO! Evento criado no Google. ID: {google_id}")
        else:
            logger.warning("⚠️ [SYNC] O serviço do Google não retornou ID (falha silenciosa).")

    except Exception as e:
        # Loga o erro mas NÃO trava o sistema de agendamento do cliente
        logger.error(f"❌ [SYNC] ERRO FATAL na sincronização: {str(e)}", exc_info=True)

# Liga o "escutador" do banco de dados
event.listen(Agendamento, 'after_insert', enviar_para_google)
