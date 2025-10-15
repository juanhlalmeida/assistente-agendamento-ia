# app/services/ai_service.py
import os
import logging
import google.generativeai as genai
from datetime import datetime, date, timedelta
from sqlalchemy.orm import joinedload

# Importamos as ferramentas do nosso banco de dados
from app.models.tables import Agendamento, Profissional, Servico
from app.extensions import db

# Configuração do logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- FERRAMENTAS (FUNÇÕES) QUE A IA PODE USAR ---

def calcular_horarios_disponiveis(profissional_nome: str, dia: str) -> str:
    """Calcula e retorna uma string com os horários disponíveis para um profissional em um dia específico."""
    logging.info(f"Executando ferramenta: calcular_horarios_disponiveis para {profissional_nome} no dia {dia}")
    try:
        profissional = Profissional.query.filter(Profissional.nome.ilike(f"%{profissional_nome}%")).first()
        if not profissional:
            return "Profissional não encontrado. Por favor, verifique o nome. Os profissionais disponíveis são [Liste os nomes aqui se necessário]."

        if dia.lower() == 'hoje':
            dia_dt = datetime.now()
        elif dia.lower() == 'amanhã':
            dia_dt = datetime.now() + timedelta(days=1)
        else:
            dia_dt = datetime.strptime(dia, '%Y-%m-%d')

        HORA_INICIO_TRABALHO = 9
        HORA_FIM_TRABALHO = 20
        INTERVALO_MINUTOS = 30
        horarios_disponiveis = []
        horario_iteracao = dia_dt.replace(hour=HORA_INICIO_TRABALHO, minute=0, second=0, microsecond=0)
        fim_do_dia = dia_dt.replace(hour=HORA_FIM_TRABALHO, minute=0, second=0, microsecond=0)
        inicio_dia, fim_dia_query = (dia_dt.replace(hour=0, minute=0), dia_dt.replace(hour=23, minute=59))
        
        agendamentos_do_dia = Agendamento.query.options(joinedload(Agendamento.servico)).filter(
            Agendamento.profissional_id == profissional.id,
            Agendamento.data_hora >= inicio_dia, Agendamento.data_hora < fim_dia_query
        ).all()
        
        intervalos_ocupados = [(ag.data_hora, ag.data_hora + timedelta(minutes=ag.servico.duracao)) for ag in agendamentos_do_dia]
        
        agora = datetime.now()
        while horario_iteracao < fim_do_dia:
            esta_ocupado = any(i <= horario_iteracao < f for i, f in intervalos_ocupados)
            if not esta_ocupado and horario_iteracao > agora:
                horarios_disponiveis.append(horario_iteracao.strftime('%H:%M'))
            horario_iteracao += timedelta(minutes=INTERVALO_MINUTOS)

        resultado = f"Resultado da consulta de horários: Os horários disponíveis para {profissional_nome} no dia {dia_dt.strftime('%d/%m/%Y')} são: {', '.join(horarios_disponiveis) if horarios_disponiveis else 'Nenhum horário disponível.'}"
        logging.info(resultado)
        return resultado
    except Exception as e:
        logging.error(f"Erro na ferramenta calcular_horarios_disponiveis: {e}")
        return f"Ocorreu um erro interno ao calcular os horários: {str(e)}"

def criar_agendamento(nome_cliente: str, telefone_cliente: str, data_hora: str, profissional_nome: str, servico_nome: str) -> str:
    """Cria um novo agendamento no sistema após verificar conflitos."""
    logging.info(f"Executando ferramenta: criar_agendamento para {nome_cliente} em {data_hora}")
    # ... (O código completo da função criar_agendamento que o seu dev sugeriu)
    return "Função criar_agendamento executada." # Placeholder

# --- CONFIGURAÇÃO DO MODELO DE IA ---

GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
if not GEMINI_API_KEY:
    logging.error("Chave da API do Gemini não encontrada!")
else:
    genai.configure(api_key=GEMINI_API_KEY)

# Descrevemos nossas ferramentas para a IA
tools_definitions = {
    "calcular_horarios_disponiveis": calcular_horarios_disponiveis,
    "criar_agendamento": criar_agendamento
}

try:
    model = genai.GenerativeModel(
        model_name='models/gemini-2.5-flash',
        tools=[calcular_horarios_disponiveis, criar_agendamento], # Habilita o Function Calling
        system_instruction="""
        Você é o assistente de agendamento premium da BinahTech, uma barbearia/salão de elite. Sua missão é fornecer um serviço excepcional: ágil, personalizado e impecável, maximizando a satisfação do cliente para fidelização e upsell sutil (ex.: sugerir serviços complementares como barba após corte).

        Regras de Alto Nível para Excelência:
        - Seja empático e proativo: Sempre pergunte por preferências (ex.: 'Prefere manhã ou tarde?') e confirme detalhes para evitar erros.
        - Foque exclusivamente em agendamentos: Ignore ou redirecione tópicos irrelevantes com 'Desculpe, sou especializado em agendamentos. Como posso ajudar com isso?'.
        - Use ferramentas inteligentemente: Chame 'calcular_horarios_disponiveis' ANTES de sugerir horários; chame 'criar_agendamento' SOMENTE após confirmação explícita do cliente.
        - Valide tudo: Verifique nomes de profissionais/serviços disponíveis. Trate erros graciosamente (ex.: 'Horário indisponível, sugiro alternativas.').
        - Otimização: Mantenha respostas concisas, use linguagem natural em português, e inclua chamadas para ação (ex.: 'Confirma?').
        """
    )
except Exception as e:
    logging.error(f"Erro ao inicializar o modelo Gemini: {e}")
    model = None