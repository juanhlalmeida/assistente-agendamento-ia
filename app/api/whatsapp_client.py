
"""
Cliente simples para integração com WhatsApp Cloud API (ou similar).
Este módulo está como *stub*: não faz chamadas reais sem as variáveis do .env.
"""
import os
import json
import logging
import requests  # opcional; usado condicionalmente

logger = logging.getLogger(__name__)

class WhatsAppClient:
    def __init__(self, token: str | None = None, phone_id: str | None = None):
        self.token = token or os.getenv('WHATSAPP_TOKEN')
        self.phone_id = phone_id or os.getenv('WHATSAPP_PHONE_ID')
        self.base_url = f"https://graph.facebook.com/v20.0/{self.phone_id}/messages" if self.phone_id else None

    def send_message(self, to_number: str, text: str) -> dict:
        """Envia mensagem de texto. Se faltar configuração, faz um log/print simulando envio.
        Retorna um dicionário com o status.
        """
        if not self.token or not self.phone_id or not self.base_url:
            msg = {
                'status': 'simulated',
                'reason': 'Configuração ausente (WHATSAPP_TOKEN/WHATSAPP_PHONE_ID) — envio simulado.',
                'to': to_number,
                'text': text,
            }
            logger.info("[WhatsApp SIMULADO] %s", json.dumps(msg, ensure_ascii=False))
            return msg

        headers = {
            'Authorization': f'Bearer {self.token}',
            'Content-Type': 'application/json'
        }
        payload = {
            'messaging_product': 'whatsapp',
            'to': to_number,
            'type': 'text',
            'text': {'body': text}
        }
        try:
            resp = requests.post(self.base_url, headers=headers, json=payload, timeout=20)
            data = resp.json() if resp.content else {'status_code': resp.status_code}
            return {'status': 'sent' if resp.ok else 'error', 'response': data}
        except Exception as exc:
            logger.exception('Falha ao enviar mensagem WhatsApp: %s', exc)
            return {'status': 'error', 'error': str(exc)}
