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
        except Exception as e:
            logging.warning(f"Aviso ao limpar cache de áudio: {e}")
            
        return transcricao
    except Exception as e:
        logging.error(f"Erro na transcrição do áudio com Gemini: {e}", exc_info=True)
        return "[Áudio recebido, mas não foi possível compreender a voz do cliente]"

def extrair_e_filtrar_mensagem_waha(payload, session_id=None):
    """Extrator Universal com Suporte a Áudio e Mídia (Com Raio-X)"""
    if not payload:
        return False, "Sem payload"

    from_number = payload.get('from')
    body_raw = payload.get('body')
    msg_type = payload.get('type', '')
    has_media = payload.get('hasMedia', False)

    # 🕵️‍♂️ RAIO-X PARA MÍDIAS (Ver o que está chegando)
    if has_media or msg_type in ['ptt', 'audio', 'voice', 'image', 'video']:
        logging.info(f"📦 [WAHA UTILS] Mídia Recebida: type='{msg_type}', hasMedia={has_media}")

    # 1. 🛡️ ESCUDO ANTI-GRUPOS
    if from_number and '@g.us' in str(from_number):
        logging.info(f"🚫 [ESCUDO-UTILS] Mensagem de grupo ignorada: {from_number}")
        return False, "mensagem_de_grupo"

    # 2. 🎙️ INTERCEPTADOR E TRANSCRITOR DE ÁUDIO (PTT)
    if msg_type in ['ptt', 'audio', 'voice']:
        message_id = payload.get('id')
        if session_id and message_id:
            logging.info(f"🔊 Áudio detectado de {from_number}! Baixando do WAHA...")
            try:
                safe_message_id = urllib.parse.quote(message_id, safe='')
                url_download = f"{WAHA_BASE_URL}/api/{session_id}/messages/{safe_message_id}/download"
                
                logging.info(f"🔗 Fazendo download do áudio em: {url_download}")
                response = requests.get(url_download, headers=get_waha_headers(), timeout=45) # 45s de tolerância
                
                if response.status_code == 200:
                    logging.info("🔊 Áudio baixado! Iniciando transcrição com Gemini...")
                    transcricao = transcrever_audio_gemini(response.content)
                    logging.info(f"📝 Transcrição concluída: '{transcricao}'")
                    return True, transcricao
                else:
                    logging.error(f"❌ Erro ao baixar áudio. Status: {response.status_code} - {response.text}")
                    return False, "erro_download_audio"
            except Exception as e:
                logging.error(f"❌ Falha grave ao processar áudio: {e}", exc_info=True)
                return False, "erro_processamento_audio"
        else:
            logging.warning(f"⚠️ Áudio ignorado: falta 'session_id' ({session_id}) ou 'message_id' ({message_id}).")
            return False, "falta_dados_audio"

    # 3. 🛠️ EXTRATOR UNIVERSAL DE TEXTO
    if isinstance(body_raw, dict):
        body = str(body_raw.get('text', body_raw.get('caption', '')))
    else:
        body = str(body_raw) if body_raw is not None else ""

    body = body.strip()

    # 4. 🛡️ ESCUDO MENSAGENS VAZIAS / FIGURINHAS
    if not body or body == "" or body.lower() == "none":
        if msg_type in ['image', 'video', 'document', 'sticker']:
             return False, f"Mídia ({msg_type}) sem legenda ignorada"
        return False, "mensagem_vazia"

    return True, body