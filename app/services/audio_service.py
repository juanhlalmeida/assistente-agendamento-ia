# app/services/audio_service.py
# (CÓDIGO CORRIGIDO PARA ACEITAR OS NOVOS ARGUMENTOS + MEMÓRIA)

import os
import requests
import tempfile
import logging
import google.generativeai as genai
import json
from time import sleep
from app.extensions import cache 
from google.generativeai.protos import Content, Part

# Configuração de Logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class AudioService:
    def __init__(self):
        self.google_api_key = os.getenv('GOOGLE_API_KEY')
        if not self.google_api_key:
            logger.error("GOOGLE_API_KEY não configurada!")
        genai.configure(api_key=self.google_api_key)

    def processar_audio(self, audio_id, access_token, wa_id=None, barbearia_id=None):
        """
        Processa áudio mantendo o contexto da conversa no Redis.
        Aceita wa_id e barbearia_id para acessar o histórico.
        """
        caminho_arquivo = None
        arquivo_remoto_gemini = None
        cache_key = f"chat_history_{wa_id}:{barbearia_id}" if wa_id and barbearia_id else None
        
        try:
            # 1. Baixar Áudio
            url_download = self._obter_url_midia(audio_id, access_token)
            conteudo_audio = self._baixar_binario_midia(url_download, access_token)
            
            with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as temp_file:
                temp_file.write(conteudo_audio)
                caminho_arquivo = temp_file.name
            
            # 2. Upload para Gemini
            arquivo_remoto_gemini = genai.upload_file(caminho_arquivo, mime_type="audio/ogg")
            while arquivo_remoto_gemini.state.name == "PROCESSING":
                sleep(1)
                arquivo_remoto_gemini = genai.get_file(arquivo_remoto_gemini.name)

            # 3. RECUPERAR MEMÓRIA (REDIS)
            history = []
            if cache_key:
                serialized_history = cache.get(cache_key)
                if serialized_history:
                    history = self._deserialize_history(serialized_history)
            
            # 4. Instanciar Modelo com Memória
            # Usando gemini-2.5-flash conforme seu padrão
            model = genai.GenerativeModel("gemini-2.5-flash") 
            chat = model.start_chat(history=history)
            
            prompt_sistema = """
            [CONTEXTO: ÁUDIO RECEBIDO]
            Ouça este áudio como parte da conversa anterior.
            Se o cliente confirmou dados que faltavam (ex: horário, profissional), junte com o que já sabemos.
            Se ele pedir agendamento, verifique se temos: Serviço, Profissional, Data e Hora.
            Responda em texto curto e natural.
            """
            
            # Envia o áudio para o chat (mantendo histórico)
            response = chat.send_message([prompt_sistema, arquivo_remoto_gemini])
            
            # 5. SALVAR MEMÓRIA ATUALIZADA
            if cache_key:
                new_history = self._serialize_history(chat.history)
                cache.set(cache_key, new_history)
            
            return response.text

        except Exception as e:
            logger.error(f"Erro audio: {e}")
            return "Tive um problema técnico no áudio. Pode digitar?"

        finally:
            if caminho_arquivo and os.path.exists(caminho_arquivo): os.remove(caminho_arquivo)
            if arquivo_remoto_gemini: 
                try: genai.delete_file(arquivo_remoto_gemini.name)
                except: pass

    def _obter_url_midia(self, audio_id, access_token):
        url = f"https://graph.facebook.com/v19.0/{audio_id}"
        headers = {"Authorization": f"Bearer {access_token}"}
        res = requests.get(url, headers=headers)
        res.raise_for_status()
        return res.json().get('url')

    def _baixar_binario_midia(self, url, access_token):
        headers = {"Authorization": f"Bearer {access_token}"}
        res = requests.get(url, headers=headers)
        res.raise_for_status()
        return res.content

    # --- Helpers de Serialização ---
    def _serialize_history(self, history):
        serializable = []
        for content in history:
            parts = []
            for part in content.parts:
                if part.text: parts.append({'text': part.text})
            serializable.append({'role': content.role, 'parts': parts})
        return json.dumps(serializable)

    def _deserialize_history(self, json_str):
        history = []
        try:
            data = json.loads(json_str)
            for item in data:
                parts = [Part(text=p['text']) for p in item.get('parts', []) if 'text' in p]
                if parts: history.append(Content(role=item['role'], parts=parts))
        except: pass
        return history
