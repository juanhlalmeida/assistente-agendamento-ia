# app/services/waha_utils.py
import logging
import requests
import tempfile
import os
import urllib.parse
import google.generativeai as genai
from app.services.waha_service import WAHA_BASE_URL, get_waha_headers

def transcrever_audio_gemini(audio_bytes):
    """Usa a IA nativa do Gemini para ouvir e transcrever o áudio"""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".ogg") as temp_audio:
            temp_audio.write(audio_bytes)
            temp_file_path = temp_audio.name

        audio_file = genai.upload_file(path=temp_file_path, mime_type="audio/ogg")
        
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content([
            "Você é um transcritor de áudio. Transcreva exatamente o que está sendo dito neste áudio. Retorne APENAS o texto da transcrição, sem explicações adicionais e sem aspas.",
            audio_file
        ])
        
        transcricao = response.text.strip()
        
        try:
            genai.delete_file(audio_file.name)
            os.remove(temp_file_path)
        except Exception:
            pass
            
        return transcricao
    except Exception as e:
        logging.error(f"Erro na transcrição do áudio com Gemini: {e}", exc_info=True)
        return "[Áudio recebido, mas não foi possível compreender a voz do cliente]"

def extrair_e_filtrar_mensagem_waha(payload, session_id=None):
    if not payload:
        return False, "Sem payload"

    from_number = payload.get('from')
    body_raw = payload.get('body')
    msg_type = str(payload.get('type', '')).lower()
    has_media = payload.get('hasMedia', False)

    # 1. Escudo Anti-Grupo
    if from_number and '@g.us' in str(from_number):
        return False, "mensagem_de_grupo"

    # 2. 🎙️ INTERCEPTADOR VIA URL OFICIAL DO WAHA
    if has_media or msg_type in ['ptt', 'audio', 'voice']:
        message_id = payload.get('id')
        logging.info(f"🔊 Mídia detectada! ID: {message_id}")
        
        try:
            # A BALA DE PRATA: Pega a URL exata que o WAHA gerou e mandou!
            media_info = payload.get('media', {})
            url_original = media_info.get('url')
            
            if not url_original:
                logging.error("❌ O WAHA não enviou o link! A variável WHATSAPP_DOWNLOAD_MEDIA=true foi configurada na Render?")
                return False, "sem_url_no_payload"
                
            # BLINDAGEM DE REDE: O WAHA pode mandar a URL como 'localhost'. Nós trocamos pelo domínio da Render.
            if "localhost" in url_original or "127.0.0.1" in url_original:
                caminho_arquivo = urllib.parse.urlparse(url_original).path
                url_download = f"{WAHA_BASE_URL}{caminho_arquivo}"
            else:
                url_download = url_original
                
            logging.info(f"🔗 Baixando áudio da URL oficial: {url_download}")
            
            # Baixa o áudio com a API Key correta
            response = requests.get(url_download, headers=get_waha_headers(), timeout=45)
            
            if response.status_code == 200:
                logging.info("✅ Áudio baixado com sucesso da API!")
                transcricao = transcrever_audio_gemini(response.content)
                logging.info(f"📝 Transcrição perfeita: '{transcricao}'")
                return True, transcricao
            else:
                logging.error(f"❌ WAHA bloqueou o download. Status: {response.status_code} - {response.text}")
                return False, "erro_download_waha"
                
        except Exception as e:
            logging.error(f"❌ Falha crítica no processamento da API: {e}", exc_info=True)
            return False, "erro_geral_api"

    # 3. Extrator de Texto Normal
    if isinstance(body_raw, dict):
        body = str(body_raw.get('text', body_raw.get('caption', '')))
    else:
        body = str(body_raw) if body_raw is not None else ""

    body = body.strip()

    # 4. Escudo de Mensagem Vazia
    if not body or body == "" or body.lower() == "none":
        return False, "mensagem_vazia_ou_midia_sem_legenda"

    return True, body