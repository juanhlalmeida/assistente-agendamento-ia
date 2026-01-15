# app/google/blueprint_sync.py

import logging
from flask import Blueprint
from sqlalchemy import event
from app.models.tables import Agendamento
from app.google.google_calendar_service import GoogleCalendarService

# Define um Blueprint (como se fosse uma 'rota', mas serve só para carregar o código)
bp = Blueprint('google_sync_worker', __name__)

logger = logging.getLogger(__name__)

def enviar_para_google(mapper, connection, target):
    """
    Esta função roda automaticamente toda vez que um Agendamento é salvo no banco.
    'target' é o agendamento que acabou de ser criado.
    """
    try:
        logger.info(f"🔄 [SYNC] Novo agendamento detectado (ID: {target.id}). Preparando envio Google...")
        
        # 1. Descobrir qual a barbearia responsável
        # O target.profissional pode não estar carregado ainda, então usamos o relacionamento
        if target.profissional and target.profissional.barbearia:
            barbearia = target.profissional.barbearia
        else:
            logger.warning("⚠️ [SYNC] Não foi possível achar a barbearia do profissional.")
            return

        # 2. Conectar e Enviar
        service = GoogleCalendarService(barbearia)
        google_id = service.create_event(target)
        
        if google_id:
            logger.info(f"✅ [SYNC] Sucesso! Evento Google criado ID: {google_id}")
        
    except Exception as e:
        # Importante: Se der erro AQUI, a gente só loga. NÃO travamos o site.
        logger.error(f"❌ [SYNC] Erro ao sincronizar (Site continua funcionando): {str(e)}")

# Aqui ligamos o "ouvido" do SQLAlchemy
# Sempre que a tabela Agendamento tiver um 'after_insert' (inserção), roda a função acima.
event.listen(Agendamento, 'after_insert', enviar_para_google)
