# app/integrations/google_calendar_service.py

import os
import logging
import datetime
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from app.integrations.calendar_events import CALENDAR_CONFIG

# Configura logger específico
logger = logging.getLogger(__name__)

class GoogleCalendarService:
    def __init__(self, barbearia):
        self.barbearia = barbearia
        self.service = None
        self._authenticate()

    def _authenticate(self):
        """Autentica usando os tokens salvos no banco da barbearia"""
        if not self.barbearia.google_refresh_token:
            return None
            
        try:
            creds = Credentials(
                token=self.barbearia.google_access_token,
                refresh_token=self.barbearia.google_refresh_token,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=os.getenv('GOOGLE_CLIENT_ID'),
                client_secret=os.getenv('GOOGLE_CLIENT_SECRET'),
                scopes=CALENDAR_CONFIG['SCOPES']
            )
            self.service = build('calendar', 'v3', credentials=creds)
        except Exception as e:
            logger.error(f"❌ Erro de autenticação Google para Barbearia {self.barbearia.id}: {str(e)}")
            self.service = None

    def create_event(self, agendamento):
        """Cria um evento no Google Agenda"""
        if not self.service: return False

        try:
            inicio = agendamento.data_hora.isoformat()
            fim = (agendamento.data_hora + datetime.timedelta(minutes=agendamento.servico.duracao)).isoformat()

            evento_body = {
                'summary': f"✂️ {agendamento.nome_cliente} - {agendamento.servico.nome}",
                'location': self.barbearia.nome_fantasia,
                'description': f"Agendado via IA.\nProfissional: {agendamento.profissional.nome}\nTelefone: {agendamento.telefone_cliente}",
                'start': {'dateTime': inicio, 'timeZone': CALENDAR_CONFIG['TIMEZONE']},
                'end': {'dateTime': fim, 'timeZone': CALENDAR_CONFIG['TIMEZONE']},
                'reminders': {
                    'useDefault': False,
                    'overrides': [{'method': 'popup', 'minutes': CALENDAR_CONFIG['REMINDER_MINUTES']}],
                },
            }

            event = self.service.events().insert(
                calendarId=CALENDAR_CONFIG['DEFAULT_CALENDAR_ID'], 
                body=evento_body
            ).execute()
            
            logger.info(f"✅ Evento Google Criado: {event.get('htmlLink')}")
            return event.get('id')

        except Exception as e:
            logger.error(f"❌ Erro ao criar evento Google: {str(e)}")
            raise e

    def delete_event(self, google_event_id):
        """Remove um evento do Google Agenda"""
        if not self.service or not google_event_id: return False

        try:
            self.service.events().delete(
                calendarId=CALENDAR_CONFIG['DEFAULT_CALENDAR_ID'],
                eventId=google_event_id
            ).execute()
            logger.info(f"🗑️ Evento Google Removido: {google_event_id}")
            return True
        except Exception as e:
            logger.error(f"❌ Erro ao deletar evento Google: {str(e)}")
            return False
