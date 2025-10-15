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

try:
    # ✅ A CORREÇÃO FINAL: Usamos o nome exato da lista que obtivemos.
    model = genai.GenerativeModel(
        model_name='models/gemini-2.5-flash',
        system_instruction="""
        Você é um assistente de agendamento de uma barbearia/salão chamado BinahTech.
        Sua personalidade é amigável, eficiente e direta.
        Seu único objetivo é agendar, reagendar ou cancelar horários para os clientes.
        Nunca responda a perguntas que não sejam sobre agendamentos.
        Sempre confirme o agendamento no final com todos os detalhes.
        """
    )
except Exception as e:
    logging.error(f"Erro CRÍTICO ao inicializar o modelo Gemini: {e}")
    model = None