# app/integrations/calendar_events.py

class CalendarAction:
    CREATE = 'create'
    DELETE = 'delete'
    UPDATE = 'update'

class GoogleSyncStatus:
    PENDING = 'pending'
    SUCCESS = 'success'
    FAILED = 'failed'
    SKIPPED = 'skipped'

# Configurações Gerais
CALENDAR_CONFIG = {
    'SCOPES': ['https://www.googleapis.com/auth/calendar'],
    'DEFAULT_CALENDAR_ID': 'primary',
    'TIMEZONE': 'America/Sao_Paulo',
    'REMINDER_MINUTES': 30,
    'ENABLE_LOGGING': True
}
