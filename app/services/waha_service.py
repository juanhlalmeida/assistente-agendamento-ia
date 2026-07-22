import os
import requests
import time
import logging
import base64
import re

# Configurações do WAHA (Puxamos do ambiente, se não houver, usa a porta 10000 confirmada na Render)
WAHA_BASE_URL = os.environ.get('WAHA_BASE_URL', 'http://waha-agendamento-ia:10000')
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


def status_sessao_waha(session_id):
    """Verifica o status no WAHA antes de tomar qualquer atitude destrutiva."""
    try:
        response = requests.get(f"{WAHA_BASE_URL}/api/sessions", headers=get_waha_headers(), timeout=5)
        if response.status_code == 200:
            sessoes = response.json()
            for s in sessoes:
                if s.get('name') == session_id:
                    return s.get('status', 'UNKNOWN')
        return "NOT_FOUND"
    except:
        return "ERROR"


def criar_sessao_waha(session_id):
    """Inicia a sessão COM INTELIGÊNCIA DE ESTADO (Evita corromper o motor Chromium)"""
    status_atual = status_sessao_waha(session_id)
    logging.info(f"🔍 [WAHA] Status atual da sessão '{session_id}': {status_atual}")

    # =====================================================================
    # 🧠 REGRA DE OURO: Se já está a ligar ou a funcionar, NÃO FAZEMOS NADA!
    # Isso impede o erro fatal "Navigating frame was detached" no WAHA.
    # =====================================================================
    if status_atual in ['STARTING', 'SCAN_QR_CODE', 'WORKING']:
        logging.info(f"✅ [WAHA] A sessão já está operando ({status_atual}). Ignorando comando de recriação.")
        return True, {"status": status_atual}

    # Se a sessão existe mas está parada, manda apenas um comando de arranque suave
    if status_atual == 'STOPPED':
        logging.info(f"🚀 [WAHA] Sessão estava pausada. A dar a ignição...")
        try:
            requests.post(f"{WAHA_BASE_URL}/api/sessions/{session_id}/start", headers=get_waha_headers(), timeout=5)
        except:
            pass
        return True, {"status": "starting"}

    # =====================================================================
    # 🧹 SÓ APAGA se falhou ('FAILED') ou não existe ('NOT_FOUND')
    # =====================================================================
    logging.info(f"🧹 [WAHA] Sessão morta ou inexistente. Limpando e recriando...")
    try:
        requests.post(f"{WAHA_BASE_URL}/api/sessions/{session_id}/stop", headers=get_waha_headers(), timeout=3)
        requests.delete(f"{WAHA_BASE_URL}/api/sessions/{session_id}", headers=get_waha_headers(), timeout=3)
    except:
        pass # Ignora erros de limpeza se não havia nada para limpar

    meu_webhook = "https://assistente-agendamento-ia.onrender.com/api/webhooks/waha"
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
        # 1. Cria a sessão e avisa para onde mandar as mensagens
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
        
        return True, {"status": "starting"}
    except Exception as e:
        logging.error(f"[WAHA] Falha ao criar/iniciar sessão {session_id}: {e}")
        return False, str(e)


def obter_qr_code_waha(session_id):
    """Puxa a imagem do QR Code APÓS garantir que o status é SCAN_QR_CODE (Solução Definitiva)."""
    
    # 1. LOOP DE ESPERA INTELIGENTE (Polling)
    # Vamos checar o status a cada 3 segundos, no máximo 5 vezes (Total 15s, seguro para a Render)
    status_pronto = False
    for tentativa in range(5):
        status_atual = status_sessao_waha(session_id)
        logging.info(f"⏳ [WAHA] Aguardando motor iniciar... Status atual: {status_atual} (Tentativa {tentativa+1}/5)")
        
        if status_atual == 'SCAN_QR_CODE':
            status_pronto = True
            break
        elif status_atual == 'WORKING':
            return False, "O WhatsApp já está conectado! Atualize a página e pronto."
        elif status_atual == 'FAILED':
            return False, "O motor do WhatsApp falhou ao iniciar. Clique em 'Atualizar QR Code' novamente."
            
        time.sleep(3) # Pausa rápida antes de perguntar de novo
        
    if not status_pronto:
        # Se após 15s ainda estiver STARTING, devolvemos a tela pra Carol não travar o servidor
        return False, "O sistema está ligando. Clique em 'Atualizar QR Code' em alguns segundos para ver a imagem!"

    # 2. O BOTE CERTEIRO (O status já é SCAN_QR_CODE, o WAHA não vai mais dar Erro 422)
    try:
        logging.info(f"📸 [WAHA] Motor pronto! Baixando a imagem do QR Code...")
        response = requests.get(
            f"{WAHA_BASE_URL}/api/{session_id}/auth/qr",
            headers=get_waha_headers(),
            timeout=10
        )
        
        if response.status_code == 200:
            # Transforma a imagem e entrega pra tela da Carol
            encoded_img = base64.b64encode(response.content).decode('utf-8')
            return True, f"data:image/png;base64,{encoded_img}"
        else:
            logging.error(f"[WAHA] WAHA retornou status {response.status_code} ao pedir a imagem.")
            return False, "O QR Code ainda está sendo gerado. Tente novamente."
            
    except Exception as e:
        logging.error(f"[WAHA] Erro de rede ao baixar QR Code: {e}")
        return False, "Falha ao carregar a imagem. Tente de novo!"