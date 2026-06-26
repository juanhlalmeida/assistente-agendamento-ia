import os
import requests
import time
import logging
import base64

# Configurações do WAHA (Puxamos do ambiente, se não houver, usa o padrão local)
WAHA_BASE_URL = os.environ.get('WAHA_BASE_URL', 'http://127.0.0.1:3000')
WAHA_API_KEY = os.environ.get('WAHA_API_KEY', 'sua_chave_secreta_super_segura_aqui_123!')

def get_waha_headers():
    """Constrói os cabeçalhos obrigatórios com a chave de API restritiva."""
    return {
        'Content-Type': 'application/json',
        'X-Api-Key': WAHA_API_KEY
    }

def formatar_numero_waha(numero):
    """Garante que o número seja apenas dígitos e adiciona a flag @c.us (obrigatório no WAHA)"""
    numero_limpo = ''.join(filter(str.isdigit, str(numero)))
    return f"{numero_limpo}@c.us"

def enviar_mensagem_waha(session_id, to_number, text):
    """Envia uma mensagem de texto simulando o comportamento humano (Typing...)"""
    chat_id = formatar_numero_waha(to_number)
    
    # --- ESTRATÉGIA ANTI-BAN: Simular digitação humana ---
    try:
        requests.post(
            f"{WAHA_BASE_URL}/api/startTyping",
            json={"session": session_id, "chatId": chat_id},
            headers=get_waha_headers(),
            timeout=5
        )
        # Calcula um tempo de pausa realista baseado no tamanho da frase (max 3 segundos)
        tempo_pausa = min(len(text) * 0.05, 3) 
        time.sleep(tempo_pausa)
        
        # Para a digitação
        requests.post(
            f"{WAHA_BASE_URL}/api/stopTyping",
            json={"session": session_id, "chatId": chat_id},
            headers=get_waha_headers(),
            timeout=5
        )
    except Exception as e:
        logging.warning(f"Aviso WAHA (Ignorável): Falha ao simular digitação: {e}")

    # --- ENVIO REAL DA MENSAGEM ---
    payload = {
        "session": session_id,
        "chatId": chat_id,
        "text": text
    }
    
    try:
        response = requests.post(
            f"{WAHA_BASE_URL}/api/sendText",
            json=payload,
            headers=get_waha_headers(),
            timeout=10
        )
        response.raise_for_status() # Dispara erro se não for Status 200
        logging.info(f"[WAHA] Mensagem enviada com sucesso para {chat_id}")
        return True, response.json()
    
    except requests.exceptions.RequestException as e:
        logging.error(f"[WAHA] Erro crítico ao enviar mensagem: {e}")
        return False, str(e)

def criar_sessao_waha(session_id):
    """Aciona a criação de uma nova sessão no WAHA (Carga Minimalista)."""
    # Agora o payload só tem o nome. Impossível dar erro 422.
    payload = {
        "name": session_id
    }
    
    try:
        response = requests.post(
            f"{WAHA_BASE_URL}/api/sessions/",
            json=payload,
            headers=get_waha_headers(),
            timeout=15
        )
        if response.status_code == 422:
            logging.info(f"[WAHA] Sessão já existe ou em uso: {session_id}")
            return True, {"status": "already_exists"}
            
        response.raise_for_status()
        return True, response.json()
    except Exception as e:
        logging.error(f"[WAHA] Falha ao criar sessão {session_id}: {e}")
        return False, str(e)
    

def obter_qr_code_waha(session_id):
    """Puxa a imagem do QR Code e converte para Base64 para exibir no HTML de forma segura."""
    try:
        response = requests.get(
            f"{WAHA_BASE_URL}/api/{session_id}/auth/qr",
            headers=get_waha_headers(),
            timeout=15 # Damos um tempo maior caso o WAHA esteja gerando a imagem
        )
        response.raise_for_status()
        
        # Transforma a imagem crua (bytes) em texto Base64 legível para navegadores
        encoded_img = base64.b64encode(response.content).decode('utf-8')
        return True, f"data:image/png;base64,{encoded_img}"
        
    except requests.exceptions.RequestException as e:
        logging.error(f"[WAHA] Erro ao obter QR Code: {e}")
        return False, str(e)
    

def enviar_midia_waha(session_id, to_number, url_arquivo, caption=""):
    """Envia imagem/mídia (Tabela de preços, flyers) via WAHA"""
    chat_id = formatar_numero_waha(to_number)
    payload = {
        "session": session_id,
        "chatId": chat_id,
        "file": {"url": url_arquivo},
        "caption": caption
    }
    try:
        # Usamos sendFile que o WAHA aceita universalmente para imagens e PDFs
        response = requests.post(
            f"{WAHA_BASE_URL}/api/sendFile", 
            json=payload,
            headers=get_waha_headers(),
            timeout=15
        )
        response.raise_for_status()
        logging.info(f"[WAHA] Mídia enviada com sucesso para {chat_id}")
        return True
    except Exception as e:
        logging.error(f"[WAHA] Erro ao enviar mídia: {e}")
        return False

        