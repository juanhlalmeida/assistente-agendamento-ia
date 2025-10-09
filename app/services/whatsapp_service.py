# app/services/whatsapp_service.py
import os
import requests
import json
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

ACCESS_TOKEN = os.getenv('WHATSAPP_ACCESS_TOKEN')

# ✅ A CORREÇÃO ESTÁ AQUI. Usamos a variável correta.
PHONE_NUMBER_ID = os.getenv('WHATSAPP_PHONE_NUMBER_ID')

if not all([ACCESS_TOKEN, PHONE_NUMBER_ID]):
    logging.error("ERRO CRÍTICO: Variáveis de ambiente WHATSAPP_ACCESS_TOKEN ou WHATSAPP_PHONE_NUMBER_ID não estão configuradas!")

# Agora a URL será montada com o ID correto (o que começa com 856...)
API_URL = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages"

def send_whatsapp_message(to, text):
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "text": {"body": text}
    }
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    
    logging.info(f"Preparando para enviar a mensagem '{text}' para {to} usando o Phone Number ID correto: {PHONE_NUMBER_ID}")
    try:
        response = requests.post(API_URL, headers=headers, data=json.dumps(payload), timeout=10)
        logging.info(f"Resposta recebida da Meta: Status {response.status_code}, Conteúdo: {response.text}")
        response.raise_for_status()
        logging.info(f"Mensagem enviada com sucesso para {to}!")
        return response.json()
    except requests.exceptions.RequestException as e:
        logging.error(f"Erro CRÍTICO ao tentar enviar mensagem via API: {e}")
        if e.response is not None:
            logging.error(f"Detalhes do erro da Meta: {e.response.text}")
        return None