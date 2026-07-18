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
    
    # 2. 🎙️ INTERCEPTADOR DE ÁUDIO (Busca no disco local do container)
    if (has_media or msg_type in ['ptt', 'audio', 'voice']) and session_id and message_id:
        logging.info(f"🔊 Áudio detectado! ID: {message_id}. Buscando no disco...")
        try:
            # Caminho padrão onde o WAHA salva as mídias
            caminho_sessao = f"/app/.sessions/noweb/{session_id}/media"
            
            # Se a pasta não existir, tentamos uma alternativa
            if not os.path.exists(caminho_sessao):
                caminho_sessao = f"/app/.sessions/noweb/{session_id}"

            audio_encontrado = None
            for arquivo in os.listdir(caminho_sessao):
                # O WAHA geralmente salva o arquivo com o ID da mensagem no nome
                if message_id in arquivo:
                    caminho_completo = os.path.join(caminho_sessao, arquivo)
                    with open(caminho_completo, "rb") as f:
                        audio_encontrado = f.read()
                    break
            
            if audio_encontrado:
                logging.info("🔊 Áudio encontrado no disco! Transcrevendo...")
                transcricao = transcrever_audio_gemini(audio_encontrado)
                return True, transcricao
            else:
                logging.warning(f"⚠️ Áudio não encontrado na pasta {caminho_sessao}")
                return False, "erro_arquivo_nao_encontrado"
        except Exception as e:
            logging.error(f"❌ Falha ao ler áudio do disco: {e}")
            
            return False, "erro_leitura_disco"