# list_models.py
import os
import google.generativeai as genai
from dotenv import load_dotenv

# Carrega as variáveis de ambiente (para rodar localmente)
load_dotenv()

# Configura a API
api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    print("Erro: A variável de ambiente GEMINI_API_KEY não foi encontrada.")
else:
    genai.configure(api_key=api_key)
    print("Modelos Gemini disponíveis para a sua chave de API:\n")
    for m in genai.list_models():
        # Imprime apenas os modelos que podem ser usados para gerar conteúdo
        if 'generateContent' in m.supported_generation_methods:
            print(m.name)