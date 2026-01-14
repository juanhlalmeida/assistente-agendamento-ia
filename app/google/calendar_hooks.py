# app/integrations/calendar_hooks.py

import logging
from app.extensions import db
from app.models.tables import Agendamento, Barbearia
from app.google.google_calendar_service import GoogleCalendarService
from app.google.google_calendar_service import CalendarAction

logger = logging.getLogger(__name__)

def trigger_google_calendar_sync(agendamento_id, action):
    """
    Função Gatilho: Chamada pelo ai_service.py após salvar no banco.
    Não trava o sistema se der erro.
    """
    try:
        # 1. Busca dados frescos do banco
        agendamento = Agendamento.query.get(agendamento_id)
        if not agendamento:
            return
            
        barbearia = agendamento.barbearia
        
        # 2. Verifica se a barbearia tem Google conectado
        if not barbearia.google_refresh_token:
            logger.info(f"ℹ️ Google Agenda não conectado para {barbearia.nome_fantasia}. Pulando.")
            return

        # 3. Inicializa serviço
        service = GoogleCalendarService(barbearia)
        
        # 4. Executa a ação
        if action == CalendarAction.CREATE:
            google_id = service.create_event(agendamento)
            # Aqui poderíamos salvar o google_id no banco futuro
            
        elif action == CalendarAction.DELETE:
            # Lógica futura para deletar usando o ID salvo
            pass
            
    except Exception as e:
        # BLINDAGEM: Se der erro aqui, o WhatsApp continua funcionando normal
        logger.error(f"⚠️ Erro silencioso na Sincronização Google: {str(e)}")
