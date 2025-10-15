# app/services/ai_service.py
import os
import logging
import google.generativeai as genai

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
if not GEMINI_API_KEY:
    logging.error("Chave da API do Gemini não encontrada!")
else:
    genai.configure(api_key=GEMINI_API_KEY)

# ✅ A CORREÇÃO FINAL: Usamos o modelo Pro com o apelido '-latest'.
# Este nome é garantido de funcionar e se manter atualizado.
model = genai.GenerativeModel(
    model_name='gemini-1.5-pro-latest',
    system_instruction="""
    Você é um assistente de agendamento de uma barbearia/salão chamado BinahTech.
    Sua personalidade é amigável, eficiente e direta.
    Seu único objetivo é agendar, reagendar ou cancelar horários para os clientes.
    Nunca responda a perguntas que não sejam sobre agendamentos.
    Sempre confirme o agendamento no final com todos os detalhes (serviço, profissional, dia e hora).
    """
)