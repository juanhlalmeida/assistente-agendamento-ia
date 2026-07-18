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
    """Extrator Universal (ESTILO META API - Baseado em Headers Reais)"""
    if not payload:
        return False, "Sem payload"

    from_number = payload.get('from')
    body_raw = payload.get('body')
    msg_type = str(payload.get('type', '')).lower()
    has_media = payload.get('hasMedia', False)

    # 1. 🛡️ ESCUDO ANTI-GRUPOS
    if from_number and '@g.us' in str(from_number):
        return False, "mensagem_de_grupo"

    # 2. 🎙️ INTERCEPTADOR ESTILO META API (Não confia no 'type' do WAHA)
    message_id = payload.get('id')
    
    if (has_media or msg_type in ['ptt', 'audio', 'voice']) and session_id and message_id:
        logging.info(f"📦 Mídia detectada de {from_number}! Fazendo download para descobrir o formato real...")
        try:
            safe_message_id = urllib.parse.quote(message_id, safe='')
            url_download = f"{WAHA_BASE_URL}/api/{session_id}/messages/{safe_message_id}/download"
            
            # Baixa a mídia diretamente
            response = requests.get(url_download, headers=get_waha_headers(), timeout=45)
            
            if response.status_code == 200:
                # O CÉREBRO: Lê o tipo de arquivo verdadeiro devolvido pelo servidor
                content_type = response.headers.get('Content-Type', '').lower()
                logging.info(f"📊 Formato real do arquivo: {content_type}")
                
                # Se for qualquer tipo de áudio, ele transcreve!
                if 'audio' in content_type or 'ogg' in content_type:
                    logging.info("🔊 Áudio confirmado! Iniciando transcrição avançada...")
                    transcricao = transcrever_audio_gemini(response.content)
                    logging.info(f"📝 Transcrição perfeita: '{transcricao}'")
                    return True, transcricao
                else:
                    logging.info("🖼️ É uma imagem/documento. Seguindo para ver se há legenda...")
            else:
                logging.error(f"❌ Erro ao baixar arquivo. Status: {response.status_code}")
        except Exception as e:
            logging.error(f"❌ Falha grave ao processar mídia: {e}")

    # 3. 🛠️ EXTRATOR UNIVERSAL DE TEXTO (Legendas e Texto Normal)
    if isinstance(body_raw, dict):
        body = str(body_raw.get('text', body_raw.get('caption', '')))
    else:
        body = str(body_raw) if body_raw is not None else ""

    body = body.strip()

    # 4. 🛡️ ESCUDO MENSAGENS VAZIAS
    if not body or body == "" or body.lower() == "none":
        return False, "mensagem_vazia_ou_midia_sem_legenda"

    return True, body