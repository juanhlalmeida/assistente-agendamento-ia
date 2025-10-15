# app/services/ai_service.py
import os
import logging
import google.generativeai as genai
from datetime import datetime, timedelta
from flask import current_app
from sqlalchemy.orm import joinedload
from google.generativeai.types import FunctionDeclaration, Tool  # Import para tools
from app.models.tables import Agendamento, Profissional, Servico
from app.extensions import db

# Configuração do cliente Gemini
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
if not GEMINI_API_KEY:
    logging.error("Chave da API do Gemini não encontrada!")
else:
    genai.configure(api_key=GEMINI_API_KEY)

# Funções reais (tools) que a IA pode chamar (mantidas iguais)
def listar_profissionais() -> str:
    """Lista todos os profissionais disponíveis no sistema."""
    try:
        with current_app.app_context():
            profissionais = Profissional.query.all()
            if not profissionais:
                return "Nenhum profissional cadastrado no momento."
            nomes = [p.nome for p in profissionais]
            return f"Profissionais disponíveis: {', '.join(nomes)}."
    except Exception as e:
        return f"Erro ao listar profissionais: {str(e)}"

def listar_servicos() -> str:
    """Lista todos os serviços disponíveis no sistema."""
    try:
        with current_app.app_context():
            servicos = Servico.query.all()
            if not servicos:
                return "Nenhum serviço cadastrado no momento."
            nomes = [s.nome for s in servicos]
            return f"Serviços disponíveis: {', '.join(nomes)}."
    except Exception as e:
        return f"Erro ao listar serviços: {str(e)}"

def calcular_horarios_disponiveis(profissional_nome: str, dia: str) -> str:
    """Calcula horários disponíveis para um profissional em um dia específico."""
    try:
        with current_app.app_context():
            profissional = Profissional.query.filter_by(nome=profissional_nome).first()
            if not profissional:
                return "Profissional não encontrado. Por favor, verifique o nome."

            agora = datetime.now()
            if dia.lower() == 'hoje':
                dia_dt = agora
            elif dia.lower() == 'amanhã':
                dia_dt = agora + timedelta(days=1)
            else:
                dia_dt = datetime.strptime(dia, '%Y-%m-%d')

            HORA_INICIO_TRABALHO = 9
            HORA_FIM_TRABALHO = 20
            INTERVALO_MINUTOS = 30

            horarios_disponiveis = []
            horario_iteracao = dia_dt.replace(hour=HORA_INICIO_TRABALHO, minute=0, second=0, microsecond=0)
            fim_do_dia = dia_dt.replace(hour=HORA_FIM_TRABALHO, minute=0, second=0, microsecond=0)

            inicio, fim = (dia_dt.replace(hour=0, minute=0), dia_dt.replace(hour=23, minute=59))
            agendamentos_do_dia = (
                Agendamento.query
                .options(joinedload(Agendamento.servico))
                .filter(Agendamento.profissional_id == profissional.id)
                .filter(Agendamento.data_hora >= inicio, Agendamento.data_hora < fim)
                .all()
            )

            intervalos_ocupados = [(ag.data_hora, ag.data_hora + timedelta(minutes=ag.servico.duracao)) for ag in agendamentos_do_dia]

            while horario_iteracao < fim_do_dia:
                esta_ocupado = any(i <= horario_iteracao < f for i, f in intervalos_ocupados)
                if not esta_ocupado and horario_iteracao > agora:
                    horarios_disponiveis.append(horario_iteracao.strftime('%H:%M'))
                horario_iteracao += timedelta(minutes=INTERVALO_MINUTOS)

            return f"Horários disponíveis para {profissional_nome} em {dia_dt.strftime('%Y-%m-%d')}: {', '.join(horarios_disponiveis) or 'Nenhum disponível.'}"
    except Exception as e:
        return f"Erro ao calcular horários: {str(e)}"

def criar_agendamento(nome_cliente: str, telefone_cliente: str, data_hora: str, profissional_nome: str, servico_nome: str) -> str:
    """Cria um novo agendamento no banco de dados."""
    try:
        with current_app.app_context():
            profissional = Profissional.query.filter_by(nome=profissional_nome).first()
            if not profissional:
                return "Profissional não encontrado."

            servico = Servico.query.filter_by(nome=servico_nome).first()
            if not servico:
                return "Serviço não encontrado."

            data_hora_dt = datetime.strptime(data_hora, '%Y-%m-%d %H:%M')

            novo_fim = data_hora_dt + timedelta(minutes=servico.duracao)
            inicio_dia = data_hora_dt.replace(hour=0, minute=0)
            fim_dia = data_hora_dt.replace(hour=23, minute=59)
            ags = (
                Agendamento.query
                .options(joinedload(Agendamento.servico))
                .filter(Agendamento.profissional_id == profissional.id)
                .filter(Agendamento.data_hora >= inicio_dia, Agendamento.data_hora < fim_dia)
                .all()
            )
            conflito = any(
                max(data_hora_dt, ag.data_hora) < min(novo_fim, ag.data_hora + timedelta(minutes=ag.servico.duracao))
                for ag in ags
            )
            if conflito:
                return "Conflito de horário. Por favor, escolha outro."

            novo_agendamento = Agendamento(
                nome_cliente=nome_cliente,
                telefone_cliente=telefone_cliente,
                data_hora=data_hora_dt,
                profissional_id=profissional.id,
                servico_id=servico.id,
            )
            db.session.add(novo_agendamento)
            db.session.commit()
            return f"Agendamento criado com sucesso para {nome_cliente} em {data_hora} com {profissional_nome} para {servico_nome}. Confirmação enviada!"
    except Exception as e:
        db.session.rollback()
        return f"Erro ao criar agendamento: {str(e)}"

# Definição das tools no formato CORRETO do Gemini (corrigido: use Type em vez de SchemaType)
listar_profissionais_func = FunctionDeclaration(
    name="listar_profissionais",
    description="Lista todos os profissionais disponíveis no sistema.",
    parameters=genai.protos.Schema(
        type=genai.protos.Type.OBJECT,
        properties={},
        required=[]
    )
)

listar_servicos_func = FunctionDeclaration(
    name="listar_servicos",
    description="Lista todos os serviços disponíveis no sistema.",
    parameters=genai.protos.Schema(
        type=genai.protos.Type.OBJECT,
        properties={},
        required=[]
    )
)

calcular_horarios_disponiveis_func = FunctionDeclaration(
    name="calcular_horarios_disponiveis",
    description="Consulta horários disponíveis para um profissional em um dia específico.",
    parameters=genai.protos.Schema(
        type=genai.protos.Type.OBJECT,
        properties={
            "profissional_nome": genai.protos.Schema(
                type=genai.protos.Type.STRING,
                description="Nome do profissional (ex.: Bruno)"
            ),
            "dia": genai.protos.Schema(
                type=genai.protos.Type.STRING,
                description="Dia no formato YYYY-MM-DD, 'hoje' ou 'amanhã'"
            )
        },
        required=["profissional_nome", "dia"]
    )
)

criar_agendamento_func = FunctionDeclaration(
    name="criar_agendamento",
    description="Cria um novo agendamento no sistema.",
    parameters=genai.protos.Schema(
        type=genai.protos.Type.OBJECT,
        properties={
            "nome_cliente": genai.protos.Schema(
                type=genai.protos.Type.STRING,
                description="Nome do cliente"
            ),
            "telefone_cliente": genai.protos.Schema(
                type=genai.protos.Type.STRING,
                description="Telefone do cliente (ex.: +5513988057145)"
            ),
            "data_hora": genai.protos.Schema(
                type=genai.protos.Type.STRING,
                description="Data e hora no formato YYYY-MM-DD HH:MM"
            ),
            "profissional_nome": genai.protos.Schema(
                type=genai.protos.Type.STRING,
                description="Nome do profissional"
            ),
            "servico_nome": genai.protos.Schema(
                type=genai.protos.Type.STRING,
                description="Nome do serviço (ex.: Corte de Cabelo)"
            )
        },
        required=["nome_cliente", "telefone_cliente", "data_hora", "profissional_nome", "servico_nome"]
    )
)

tools = Tool(
    function_declarations=[
        listar_profissionais_func,
        listar_servicos_func,
        calcular_horarios_disponiveis_func,
        criar_agendamento_func
    ]
)

# Nosso modelo de IA com tools corrigidas
try:
    model = genai.GenerativeModel(
        model_name='gemini-2.5-flash',
        tools=[tools],  # Agora no formato correto
        system_instruction="""
        Você é o assistente de agendamento premium da BinahTech, uma barbearia/salão de elite. Sua missão é fornecer um serviço excepcional: ágil, personalizado e impecável, maximizando a satisfação do cliente para fidelização e upsell sutil.

        Regras de Alto Nível para Excelência:
        - Sempre comece listando profissionais/serviços reais chamando 'listar_profissionais' ou 'listar_servicos' se não souber ou se o usuário perguntar.
        - Nunca invente nomes; use apenas dados reais do sistema via tools.
        - Seja empático e proativo: Pergunte preferências e confirme detalhes. Para "hoje", use data atual.
        - Foque em agendamentos: Ignore irrelevantes.
        - Use tools: Chame 'listar_*' primeiro; 'calcular_horarios_disponiveis' antes de sugerir horários; 'criar_agendamento' SOMENTE após confirmação total (nome, telefone, data_hora exata, profissional, serviço).
        - Valide: Trate erros (ex.: 'Nome inválido, aqui a lista: ...'). Sugira alternativas.
        - Otimização: Respostas concisas, em português. Inclua upsell (ex.: 'Adicionar barba?').
        - Retenção: Ao final, sugira retorno ou avaliação.
        - Edge Cases: Para reagendamentos, adicione tools futuras.

        Sempre confirme final com detalhes completos.
        """
    )
except Exception as e:
    logging.error(f"Erro ao inicializar o modelo Gemini: {str(e)}")  # Logging mais detalhado para depuração
    model = None