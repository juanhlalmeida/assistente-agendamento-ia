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
        # 1. Salva o áudio temporariamente em formato .ogg
        with tempfile.NamedTemporaryFile(delete=False, suffix=".ogg") as temp_audio:
            temp_audio.write(audio_bytes)
            temp_file_path = temp_audio.name

        # 2. Faz o upload seguro para o Gemini
        audio_file = genai.upload_file(path=temp_file_path, mime_type="audio/ogg")
        
        # 3. Pede para o Gemini transcrever com prompt rigoroso
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content([
            "Você é um transcritor de áudio. Transcreva exatamente o que está sendo dito neste áudio. Retorne APENAS o texto da transcrição, sem explicações adicionais e sem aspas.",
            audio_file
        ])
        
        transcricao = response.text.strip()
        
        # 4. Faxina: Limpa os arquivos para não estourar o disco da Render
        try:
            genai.delete_file(audio_file.name)
            os.remove(temp_file_path)
        except Exception as e:
            logging.warning(f"Aviso ao limpar cache de áudio: {e}")
            
        return transcricao
    except Exception as e:
        logging.error(f"Erro na transcrição do áudio com Gemini: {e}")
        return "[Áudio recebido, mas não foi possível compreender a voz do cliente]"


def extrair_e_filtrar_mensagem_waha(payload, session_id=None):
    """
    Processa o payload do WAHA, extrai o texto de forma universal
    e aplica os escudos de segurança contra grupos e mensagens vazias.
    AGORA COM DETECTOR E TRANSCRITOR DE ÁUDIO (PTT) EMBUTIDO!
    
    Retorna: (bool_sucesso, resultado_ou_mensagem_erro)
    """
    if not payload:
        return False, "Sem payload"

    from_number = payload.get('from')
    body_raw = payload.get('body')
    msg_type = payload.get('type', '')

    # 1. 🛡️ ESCUDO ANTI-GRUPOS
    if from_number and '@g.us' in str(from_number):
        logging.info(f"🚫 [ESCUDO-UTILS] Mensagem de grupo ignorada: {from_number}")
        return False, "mensagem_de_grupo"

    # 2. 🎙️ INTERCEPTADOR E TRANSCRITOR DE ÁUDIO (PTT)
    if msg_type in ['ptt', 'audio']:
        message_id = payload.get('id')
        if session_id and message_id:
            logging.info(f"🔊 Áudio detectado de {from_number}! Baixando do motor WAHA...")
            try:
                # Formata o ID da mensagem para não quebrar a URL
                safe_message_id = urllib.parse.quote(message_id, safe='')
                url_download = f"{WAHA_BASE_URL}/api/{session_id}/messages/{safe_message_id}/download"
                
                # Faz o download do arquivo criptografado do WhatsApp
                response = requests.get(url_download, headers=get_waha_headers(), timeout=30)
                
                if response.status_code == 200:
                    logging.info("🔊 Áudio baixado! Iniciando transcrição avançada com Gemini...")
                    transcricao = transcrever_audio_gemini(response.content)
                    logging.info(f"📝 Transcrição concluída com sucesso: '{transcricao}'")
                    
                    # Devolve a transcrição como se fosse um texto digitado
                    return True, transcricao
                else:
                    logging.error(f"❌ Erro ao baixar áudio do WAHA. Status: {response.status_code}")
                    return False, "erro_download_audio"
            except Exception as e:
                logging.error(f"❌ Falha grave ao processar áudio: {e}")
                return False, "erro_processamento_audio"
        else:
            logging.warning("⚠️ Áudio ignorado porque 'session_id' não foi passado para o Utils.")
            return False, "falta_session_id"

    # 3. 🛠️ EXTRATOR UNIVERSAL DE TEXTO (Evita o erro de dicionário/NoneType)
    if isinstance(body_raw, dict):
        body = str(body_raw.get('text', body_raw.get('caption', '')))
    else:
        body = str(body_raw) if body_raw is not None else ""

    body = body.strip()

    # 4. 🛡️ ESCUDO MENSAGENS VAZIAS / FIGURINHAS SEM TEXTO
    if not body or body == "" or body.lower() == "none":
        # Bloqueia também envio de imagens, figurinhas e documentos sem legenda
        if msg_type in ['image', 'video', 'document', 'sticker']:
             return False, "Mensagem de mídia sem texto ignorada"
        return False, "mensagem_vazia"

    return True, body