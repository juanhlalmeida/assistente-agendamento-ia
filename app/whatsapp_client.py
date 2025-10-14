# app/whatsapp_client.py
from __future__ import annotations

import os
import re
import json
import logging
from typing import Any, Dict, Optional

# A biblioteca da Twilio substitui a necessidade do 'requests' para envio
from twilio.rest import Client

logger = logging.getLogger(__name__)

def sanitize_msisdn(value: str) -> str:
    """Para a Twilio, o número vem como 'whatsapp:+5511...'. Esta função remove o prefixo."""
    return (value or "").replace('whatsapp:', '').strip()

class WhatsAppClient:
    def __init__(self) -> None:
        # Usamos as credenciais da Twilio, que guardamos na Render
        self.account_sid = os.getenv("TWILIO_ACCOUNT_SID")
        self.auth_token = os.getenv("TWILIO_AUTH_TOKEN")
        # Este é o número fixo do Sandbox da Twilio
        self.from_number = 'whatsapp:+14155238886'
        
        # Inicializa o cliente da Twilio
        if not all([self.account_sid, self.auth_token]):
            logger.error("ERRO CRÍTICO: Variáveis de ambiente TWILIO_ACCOUNT_SID ou TWILIO_AUTH_TOKEN não configuradas!")
            self.client = None
        else:
            self.client = Client(self.account_sid, self.auth_token)

    def send_text(self, to_number: str, text: str, **kwargs) -> Dict[str, Any]:
        """Envia uma mensagem de texto usando a API da Twilio."""
        if not self.client:
            logger.error("Falha no envio: Cliente Twilio não inicializado por falta de credenciais.")
            return {"status": "error", "message": "Cliente Twilio não inicializado."}
        
        # A API da Twilio espera o número do destinatário no formato 'whatsapp:+55...'
        recipient_number = f"whatsapp:{to_number}"
        
        logger.info(f"Preparando para enviar via Twilio: '{text}' de {self.from_number} para {recipient_number}")
        
        try:
            message = self.client.messages.create(
              from_=self.from_number,
              body=text,
              to=recipient_number
            )
            
            logger.info(f"Mensagem enviada com sucesso pela Twilio! SID: {message.sid}, Status: {message.status}")
            return {"status": message.status, "sid": message.sid}
            
        except Exception as e:
            logger.exception("Erro CRÍTICO ao enviar mensagem via Twilio: %s", e)
            return {"status": "error", "message": str(e)}