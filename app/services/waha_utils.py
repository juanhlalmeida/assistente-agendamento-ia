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

    # Escudo Anti-Grupo
    if from_number and '@g.us' in str(from_number):
        return False, "mensagem_de_grupo"

    # INTERCEPTADOR DE MÍDIA - ROTA CORRETA DO WAHA
    message_id = payload.get('id')
    
    if (has_media or msg_type in ['ptt', 'audio', 'voice']) and session_id and message_id:
        logging.info(f"🔊 Áudio detectado! ID: {message_id}")
        try:
            # A ROTA PADRÃO DO WAHA PARA DOWNLOAD É ESTA:
            # /api/{session}/messages/{messageId}/download
            url_download = f"{WAHA_BASE_URL}/api/{session_id}/messages/{message_id}/download"
            
            logging.info(f"🔗 Chamando API de download: {url_download}")
            response = requests.get(url_download, headers=get_waha_headers(), timeout=45)
            
            if response.status_code == 200:
                logging.info("🔊 Áudio baixado! Iniciando transcrição com Gemini...")
                transcricao = transcrever_audio_gemini(response.content)
                logging.info(f"📝 Transcrição perfeita: '{transcricao}'")
                return True, transcricao
            else:
                logging.error(f"❌ Erro ao baixar (Status {response.status_code}): {response.text}")
                return False, "erro_download_audio"
        except Exception as e:
            logging.error(f"❌ Falha grave ao processar: {e}", exc_info=True)
            return False, "erro_processamento_audio"

    # Extrator de Texto
    if isinstance(body_raw, dict):
        body = str(body_raw.get('text', body_raw.get('caption', '')))
    else:
        body = str(body_raw) if body_raw is not None else ""

    body = body.strip()
    if not body:
        return False, "mensagem_vazia"

    return True, body