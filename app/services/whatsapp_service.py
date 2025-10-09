# app/services/whatsapp_service.py
import os
import requests
import json

ACCESS_TOKEN = os.getenv('WHATSAPP_ACCESS_TOKEN')
PHONE_NUMBER_ID = os.getenv('WHATSAPP_PHONE_NUMBER_ID')
API_URL = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages"

def send_whatsapp_message(to, text):
    """Envia uma mensagem de texto para um número de WhatsApp."""
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "text": {
            "body": text
        }
    }
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    try:
        response = requests.post(API_URL, headers=headers, data=json.dumps(payload))
        response.raise_for_status()  # Lança um erro se a requisição falhar (status != 2xx)
        print(f"Mensagem enviada com sucesso para {to}!")
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Erro ao enviar mensagem para {to}: {e}")
        print("Resposta do servidor:", e.response.text if e.response else "Nenhuma resposta")
        return None