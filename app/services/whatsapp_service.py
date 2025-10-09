# app/services/whatsapp_service.py
import os
import requests
import json
import logging

# Configura um sistema de logs profissional que aparecerá no console da Render
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Lê as credenciais salvas no ambiente da Render
ACCESS_TOKEN = os.getenv('WHATSAPP_ACCESS_TOKEN')
PHONE_NUMBER_ID = os.getenv('WHATSAPP_PHONE_NUMBER_ID')

# Verificação inicial para garantir que as variáveis foram carregadas
if not all([ACCESS_TOKEN, PHONE_NUMBER_ID]):
    logging.error("ERRO CRÍTICO: Variáveis de ambiente WHATSAPP_ACCESS_TOKEN ou WHATSAPP_PHONE_NUMBER_ID não estão configuradas!")

API_URL = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages"

def send_whatsapp_message(to, text):
    """Envia uma mensagem de texto para um número de WhatsApp com logs detalhados."""
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "text": {"body": text}
    }
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    
    logging.info(f"Preparando para enviar a mensagem '{text}' para {to} usando o ID {PHONE_NUMBER_ID}")
    try:
        # Adicionamos um timeout para evitar que a requisição fique presa
        response = requests.post(API_URL, headers=headers, data=json.dumps(payload), timeout=10)
        
        # Esta é a "caixa-preta": logamos a resposta completa da Meta
        logging.info(f"Resposta recebida da Meta: Status {response.status_code}, Conteúdo: {response.text}")

        # Lança um erro se a requisição falhou (ex: 400, 401, 403)
        response.raise_for_status()
            
        logging.info(f"Mensagem enviada com sucesso para {to}!")
        return response.json()
        
    except requests.exceptions.RequestException as e:
        # Se ocorrer um erro de rede ou um erro da API (4xx, 5xx), ele será logado aqui
        logging.error(f"Erro CRÍTICO ao tentar enviar mensagem via API: {e}")
        if e.response is not None:
            logging.error(f"Detalhes do erro da Meta: {e.response.text}")
        return None