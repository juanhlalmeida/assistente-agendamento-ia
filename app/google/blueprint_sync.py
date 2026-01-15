# app/google/blueprint_sync.py

import logging
from flask import Blueprint
from sqlalchemy import event
from app.models.tables import Agendamento, Profissional # <--- Adicionado Profissional
from app.google.google_calendar_service import GoogleCalendarService
from app.extensions import db # <--- Adicionado db para fazer consulta

# Define o Blueprint
bp = Blueprint('google_sync_worker', __name__)

logger = logging.getLogger(__name__)

def enviar_para_google(mapper, connection, target):
    """
    Roda automaticamente após salvar um Agendamento.
    target = O agendamento que acabou de ser salvo.
    """
    try:
        logger.info(f"🔄 [SYNC] Novo agendamento detectado (ID: {target.id}). Buscando dados...")
        
        # --- CORREÇÃO: BUSCA MANUAL DO PROFISSIONAL ---
        # Não confiamos no target.profissional direto, pois pode estar vazio na memória.
        # Usamos o ID para buscar no banco com certeza.
        
        profissional = None
        if target.profissional_id:
            # Importação local para evitar ciclos, se necessário, ou usar a query direta
            session = db.session
            profissional = session.get(Profissional, target.profissional_id)
        
        if profissional and profissional.barbearia:
            barbearia = profissional.barbearia
            logger.info(f"📍 [SYNC] Barbearia encontrada: {barbearia.nome_fantasia}")
        else:
            logger.warning(f"⚠️ [SYNC] Não foi possível achar a barbearia para o Profissional ID {target.profissional_id}.")
            return
        # ---------------------------------------------

        # 2. Conectar e Enviar
        service = GoogleCalendarService(barbearia)
        google_id = service.create_event(target)
        
        if google_id:
            logger.info(f"✅ [SYNC] Sucesso! Evento Google criado ID: {google_id}")
        
    except Exception as e:
        logger.error(f"❌ [SYNC] Erro ao sincronizar (Site continua funcionando): {str(e)}")

# Liga o ouvido do SQLAlchemy
event.listen(Agendamento, 'after_insert', enviar_para_google)
