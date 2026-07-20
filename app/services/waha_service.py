import os
import requests
import time
import logging
import base64
import re

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
    """Mantém a extensão original do WAHA (@lid, @g.us, @c.us) para não enviar para números fantasmas"""
    numero_str = str(numero).strip()
    
    # Se o número já veio do WAHA com a extensão correta (@), devolve intacto!
    if '@' in numero_str:
        return numero_str
        
    # Se for um número puro vindo do banco de dados, limpa e coloca @c.us
    numero_limpo = re.sub(r'\D', '', numero_str)
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
    """Aciona a criação de uma nova sessão, DESTRUINDO fantasmas antes, e AVISA O WEBHOOK."""
    
    # --- NOVIDADE: O CAÇADOR DE FANTASMAS ---
    # Tenta parar e deletar qualquer resquício da sessão antiga para destravar a Render
    try:
        logging.info(f"🧹 Limpando possível sessão travada: {session_id}")
        requests.post(f"{WAHA_BASE_URL}/api/sessions/{session_id}/stop", headers=get_waha_headers(), timeout=3)
        time.sleep(1)
        requests.delete(f"{WAHA_BASE_URL}/api/sessions/{session_id}", headers=get_waha_headers(), timeout=3)
    except:
        pass # Se não existir, segue o jogo sem dar erro

    # O link exato do "ouvido" do seu sistema na Render
    meu_webhook = "https://assistente-agendamento-ia.onrender.com/api/webhooks/waha"
    
    # Payload completo: Nome + Chave de Ignição + Webhook
    payload = {
        "name": session_id,
        "start": True,
        "config": {
            "webhooks": [
                {
                    "url": meu_webhook,
                    "events": ["message", "session.status"]
                }
            ]
        }
    }
    
    try:
        # 1. Cria a sessão avisando para onde mandar as mensagens
        response = requests.post(
            f"{WAHA_BASE_URL}/api/sessions/",
            json=payload,
            headers=get_waha_headers(),
            timeout=15
        )
        
        # 2. Gira a Chave de Ignição
        requests.post(
            f"{WAHA_BASE_URL}/api/sessions/{session_id}/start",
            headers=get_waha_headers(),
            timeout=10
        )
        
        if response.status_code == 422:
            logging.info(f"[WAHA] Sessão já existe: {session_id}")
            return True, {"status": "already_exists"}
            
        response.raise_for_status()
        return True, response.json()
    except Exception as e:
        logging.error(f"[WAHA] Falha ao criar/iniciar sessão {session_id}: {e}")
        return False, str(e)    


def obter_qr_code_waha(session_id):
    """Puxa a imagem do QR Code RÁPIDO para não causar Timeout no Gunicorn/Render."""
    
    # NOVIDADE: Sem o sleep de 10s que derrubava o servidor! 
    # Tentamos apenas 4 vezes, com 3 segundos (Total 12s, bem abaixo do limite de 30s da Render).
    for tentativa in range(4):
        try:
            response = requests.get(
                f"{WAHA_BASE_URL}/api/{session_id}/auth/qr",
                headers=get_waha_headers(),
                timeout=5
            )
            
            if response.status_code == 200:
                # Transforma a imagem e entrega pra tela
                encoded_img = base64.b64encode(response.content).decode('utf-8')
                return True, f"data:image/png;base64,{encoded_img}"
                
            elif response.status_code == 422:
                # Ainda não está pronto. Espera e tenta de novo.
                logging.warning(f"[WAHA] Servidor desenhando QR Code. Tentativa {tentativa+1} de 4...")
                time.sleep(3)
            else:
                response.raise_for_status()
                
        except Exception as e:
            logging.warning(f"[WAHA] Aguardando o motor iniciar... Erro: {e}")
            time.sleep(3)
            
    # Devolve o controle rápido para a tela da Carol sem deixar o servidor travar
    return False, "O sistema está ligando. Clique em 'Atualizar QR Code' novamente para ver a imagem!"
    

def enviar_midia_waha(session_id, to_number, url_arquivo, caption=""):
    """Envia imagem/mídia via WAHA forçando o formato de Imagem (Foto nativa)"""
    chat_id = formatar_numero_waha(to_number)
    payload = {
        "session": session_id,
        "chatId": chat_id,
        "file": {"url": url_arquivo},
        "caption": caption
    }
    try:
        response = requests.post(
            f"{WAHA_BASE_URL}/api/sendImage", 
            json=payload,
            headers=get_waha_headers(),
            timeout=30
        )
        response.raise_for_status()
        logging.info(f"[WAHA] Imagem enviada com sucesso para {chat_id}")
        return True
    except Exception as e:
        logging.error(f"[WAHA] Erro ao enviar mídia: {e}")
        return False