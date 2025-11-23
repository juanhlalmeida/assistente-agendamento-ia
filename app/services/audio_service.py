# app/services/audio_service.py
import os
import requests
import tempfile
import logging
import google.generativeai as genai
from time import sleep

# Configuração de Logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class AudioService:
    def __init__(self):
        # Pega tokens do ambiente (para autenticação do download)
        self.google_api_key = os.getenv('GOOGLE_API_KEY')
        
        if not self.google_api_key:
            logger.error("GOOGLE_API_KEY não configurada!")
            
        genai.configure(api_key=self.google_api_key)

    def processar_audio(self, audio_id, access_token):
        """
        1. Baixa o áudio da Meta usando o access_token da Barbearia.
        2. Envia para o Gemini.
        3. Retorna a resposta em texto.
        """
        caminho_arquivo = None
        arquivo_remoto_gemini = None
        
        try:
            # 1. Recuperar URL de Download da Meta
            url_download = self._obter_url_midia(audio_id, access_token)
            
            # 2. Baixar o binário
            conteudo_audio = self._baixar_binario_midia(url_download, access_token)
            
            # 3. Salvar temporariamente em disco
            # delete=False é obrigatório para compatibilidade
            with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as temp_file:
                temp_file.write(conteudo_audio)
                caminho_arquivo = temp_file.name
            
            logger.info(f"🎤 Áudio salvo temporariamente: {caminho_arquivo}")

            # 4. Upload para o Gemini (File API)
            arquivo_remoto_gemini = genai.upload_file(caminho_arquivo, mime_type="audio/ogg")
            
            # Espera processar (geralmente < 2s para áudios curtos)
            while arquivo_remoto_gemini.state.name == "PROCESSING":
                sleep(1)
                arquivo_remoto_gemini = genai.get_file(arquivo_remoto_gemini.name)

            if arquivo_remoto_gemini.state.name == "FAILED":
                raise ValueError("Gemini falhou ao processar o arquivo de áudio.")

            # 5. Gerar resposta
            # Usamos o Flash pois é rápido e barato para áudio
            model = genai.GenerativeModel("gemini-1.5-flash") 
            
            prompt_sistema = """
            Você é uma assistente de Barbearia eficiente e simpática.
            Ouça o áudio do cliente.
            Se ele quiser agendar: extraia intenção, data, hora, serviço e profissional.
            Se for dúvida: responda sucintamente.
            Responda APENAS em texto, como se fosse uma resposta de WhatsApp.
            NÃO invente horários. Se não tiver certeza, pergunte.
            """
            
            resposta = model.generate_content([prompt_sistema, arquivo_remoto_gemini])
            return resposta.text

        except Exception as e:
            logger.error(f"Erro no processamento de áudio: {e}")
            return "Desculpe, tive um problema técnico para ouvir seu áudio. Pode digitar por favor?"

        finally:
            # 6. Limpeza de Recursos (CRÍTICO)
            if caminho_arquivo and os.path.exists(caminho_arquivo):
                os.remove(caminho_arquivo)
            
            # Opcional: deletar do Google para privacidade
            if arquivo_remoto_gemini:
                try:
                    genai.delete_file(arquivo_remoto_gemini.name)
                except:
                    pass

    def _obter_url_midia(self, audio_id, access_token):
        url = f"https://graph.facebook.com/v19.0/{audio_id}"
        headers = {"Authorization": f"Bearer {access_token}"}
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.json().get('url')

    def _baixar_binario_midia(self, url, access_token):
        headers = {"Authorization": f"Bearer {access_token}"}
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.content
