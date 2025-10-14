# app/services/whatsapp_service.py
import os
import logging
from twilio.rest import Client

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Lê as credenciais da Twilio salvas no ambiente da Render
TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')
TWILIO_WHATSAPP_NUMBER = 'whatsapp:+14155238886' # Número do Sandbox da Twilio

if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN]):
    logging.error("ERRO CRÍTICO: Variáveis de ambiente da Twilio não estão configuradas!")

# Cria o cliente da Twilio
client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

def send_whatsapp_message(to, text):
    """Envia uma mensagem de texto usando a API da Twilio."""
    try:
        # O número 'to' deve estar no formato 'whatsapp:+5511999998888'
        recipient = f"whatsapp:{to}"

        logging.info(f"Preparando para enviar '{text}' de {TWILIO_WHATSAPP_NUMBER} para {recipient}")

        message = client.messages.create(
            from_=TWILIO_WHATSAPP_NUMBER,
            body=text,
            to=recipient
        )

        logging.info(f"Mensagem enviada com sucesso! SID: {message.sid}")
        return message
    except Exception as e:
        logging.error(f"Erro CRÍTICO ao enviar mensagem via Twilio: {e}")
        return None