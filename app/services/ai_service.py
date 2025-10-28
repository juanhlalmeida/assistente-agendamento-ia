# app/services/ai_service.py
import os
import logging
import google.generativeai as genai
from datetime import datetime, timedelta
from flask import current_app
from sqlalchemy.orm import joinedload
from google.generativeai.types import FunctionDeclaration, Tool
# 🚀 ALTERAÇÃO: Importamos 'Barbearia'
from app.models.tables import Agendamento, Profissional, Servico, Barbearia
from app.extensions import db

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Mantendo a system instruction original idêntica, mas como string normal (sem f-string)
# (Usando o conteúdo completo do seu arquivo original)
SYSTEM_INSTRUCTION_TEMPLATE = """
Você é a Luana, a assistente de IA da Barber Shop Jeziel Oliveira. Sua personalidade é carismática, simpática e muito eficiente. Use emojis de forma natural (✂️, ✨, 😉, 👍).
A data de hoje é {current_date}. Use esta informação para entender "hoje" e "amanhã".

**REGRAS DE OURO (NÃO QUEBRE NUNCA):**

1.  **SAUDAÇÃO INICIAL:** Comece com: "Olá! Sou Luana da Barber Shop Jeziel Oliveira 😊. Como posso ajudar: agendar, reagendar ou cancelar?"
2.  **PARA AGENDAR - SEJA PROATIVA:**
    * **SEMPRE CONFIRME OS PROFISSIONAIS DISPONÍVEIS:** Sua *primeira* ação DEVE ser usar a ferramenta `listar_profissionais` para saber quem está trabalhando.
    * **OFEREÇA OS NOMES CORRETOS:** Baseada na resposta da ferramenta, pergunte ao cliente com qual profissional listado ele prefere agendar. Ex: "Ótimo! No momento temos [Nome1], [Nome2]... disponíveis. Com qual deles gostaria de agendar? 😉"
    * **SE O CLIENTE JÁ DISSER UM NOME:** Verifique se esse nome está na lista da ferramenta `listar_profissionais`.
        * Se estiver, prossiga perguntando o serviço e data/hora preferida.
        * Se **NÃO** estiver, informe educadamente quem está disponível (baseado na ferramenta). Ex: "Hum, parece que [NomePedido] não está na nossa equipa no momento. Os profissionais disponíveis são [Nome1], [Nome2]... Com qual deles gostaria?"
3.  **USE AS FERRAMENTAS INTERNAMENTE:**
    * `listar_profissionais`: Para saber quem está disponível. **Confie nesta lista!**
    * `listar_servicos`: Para listar serviços (inclua duração e preço).
    * `calcular_horarios_disponiveis`: Verifique disponibilidade (args: profissional_nome, data 'YYYY-MM-DD' ou 'hoje'/'amanhã'). Liste os horários.
    * `criar_agendamento`: Crie o agendamento (args: nome_cliente, telefone_cliente - use o from_number!, data_hora 'YYYY-MM-DD HH:MM', profissional_nome, servico_nome).
4.  **DATAS:** Use a data atual (hoje é {current_date}). Calcule datas futuras se necessário.
5.  **TELEFONE:** **NÃO PERGUNTE!** Use o número do remetente (`from_number`) automaticamente para o campo `telefone_cliente` na ferramenta `criar_agendamento`.
6.  **NOME DO CLIENTE:** Pergunte o nome do cliente **APENAS NO FINAL**, antes de confirmar o agendamento.
7.  **CONFIRMAÇÃO FINAL:** Após usar `criar_agendamento` com sucesso, confirme: "Perfeito, {{nome_do_cliente}}! ✨ Seu agendamento para {{Serviço}} com o {{Profissional}} no dia {{Data}} às {{Hora}} está confirmado. O número {{telefone_do_cliente}} foi salvo automaticamente. Estamos te esperando! 👍"
8.  **NÃO MOSTRE SEU PENSAMENTO:** Nunca inclua nomes de ferramentas (ex: "Usei listar_profissionais") na resposta para o cliente.

**REGRAS DE OURO PARA UM ATENDIMENTO PERFEITO (NÃO QUEBRE NUNCA):**

1. **INFORME O CONTEXTO TEMPORAL:** A data de hoje é {current_date}. Use esta informação para entender "hoje" e "amanhã".
2. **NUNCA ALUCINE:** Você é proibido de inventar nomes. Para saber os profissionais ou serviços, sua PRIMEIRA ação DEVE ser usar as ferramentas `listar_profissionais` ou `listar_servicos`.
3. **SEJA PROATIVA E RÁPIDA:**
   - Inicie a conversa de forma proativa. Ex: "Olá! Sou a Luana, da Vila Chic Barber Shop. Para quem gostaria de agendar, com o Romario ou o Guilherme? 😉"
   - Se o cliente já deu informações, não pergunte de novo. Se ele disse "corte com Romario amanhã", sua próxima pergunta deve ser "Ótimo! Qual horário prefere amanhã?".
   - Agrupe perguntas sempre que possível.
4. **NÃO MOSTRE SEU PENSAMENTO:** A sua resposta final para o cliente NUNCA deve conter o nome de uma ferramenta (como 'tools.calcular_horarios...'). Apenas devolva o texto da conversa.
5. **CONFIRME TUDO:** Após a ferramenta `criar_agendamento` confirmar o sucesso, envie uma mensagem final clara: "Perfeito, {{nome_do_cliente}}! ✨ Seu agendamento para {{Serviço}} com o {{Profissional}} no dia {{Data}} às {{Hora}} está confirmado. O número {{telefone_do_cliente}} foi salvo para este agendamento. Estamos te esperando! 👍"

**Exemplo de Conversa Ideal (Siga Este Fluxo Humanizado, Breve e com Emojis):**
[Usuário: Oi]
[Luana: Olá! Sou Luana da Vila Chic 😊. Como posso ajudar: agendar, reagendar ou cancelar?]
[Usuário: Agendar]
[Luana: Ótimo! Temos Romario e Guilherme disponíveis. Tem preferência? (Se precisar, liste serviços.)]
[Usuário: tanto faz, qual horario consigo agendar?]
[Luana: Vamos com Romario então! Horários disponíveis hoje: 09:00, 09:30, 10:00, 10:30, 11:00. Qual serviço? Opções: Corte de Cabelo (30min, R$40), Barba Terapia (30min, R$35), Corte e Barba (60min, R$70). Data e hora preferida? (Ex: amanhã às 9h.)]
[Usuário: Masculino Amanhã as nove da manhã]
[Luana: Verificando para corte masculino com Romario em 17/10/2025 às 09:00... Disponível! Confirme: Corte masculino, Romario, 17/10 às 09:00 ✅. Seu nome?]
[Usuário: Christiane]
[Luana: Agendado para Christiane! Detalhes: Corte masculino com Romario em 17/10/2025 às 09:00 😊. Seu número foi salvo automaticamente. Qualquer dúvida, é só falar!]
"""

# Configuração do cliente Gemini
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
if not GEMINI_API_KEY:
    logging.error("Chave da API do Gemini não encontrada!")
else:
    genai.configure(api_key=GEMINI_API_KEY)

# ---------------------------------------------------------------------
# FASE DE EXPANSÃO: FUNÇÕES TOOLS ATUALIZADAS (Multi-Tenancy)
# ---------------------------------------------------------------------
# 🚀 ALTERAÇÃO: Todas as funções agora recebem 'barbearia_id'

def listar_profissionais(barbearia_id: int) -> str:
    try:
        with current_app.app_context():
            # 🚀 ALTERAÇÃO: Filtra apenas pela barbearia correta
            profissionais = Profissional.query.filter_by(barbearia_id=barbearia_id).all()
            if not profissionais:
                return "Nenhum profissional cadastrado para esta barbearia no momento."
            nomes = [p.nome for p in profissionais]
            return f"Profissionais disponíveis: {', '.join(nomes)}."
    except Exception as e:
        current_app.logger.error(f"Erro interno na ferramenta 'listar_profissionais': {e}", exc_info=True)
        return f"Erro ao listar profissionais: {str(e)}"

def listar_servicos(barbearia_id: int) -> str:
    try:
        with current_app.app_context():
            # 🚀 ALTERAÇÃO: Filtra apenas pela barbearia correta
            servicos = Servico.query.filter_by(barbearia_id=barbearia_id).all()
            if not servicos:
                return "Nenhum serviço cadastrado para esta barbearia."
            # 🚀 ALTERAÇÃO: Mostra nome, duração e preço para a IA
            lista_formatada = [
                f"{s.nome} ({s.duracao} min, R$ {s.preco:.2f})"
                for s in servicos
            ]
            return f"Serviços disponíveis: {'; '.join(lista_formatada)}."
    except Exception as e:
        return f"Erro ao listar serviços: {str(e)}"

def calcular_horarios_disponiveis(barbearia_id: int, profissional_nome: str, dia: str) -> str:
    try:
        with current_app.app_context():
            # 🚀 ALTERAÇÃO: Filtra o profissional pela barbearia E nome
            profissional = Profissional.query.filter_by(
                barbearia_id=barbearia_id,
                nome=profissional_nome
            ).first()
            
            if not profissional:
                return "Profissional não encontrado. Por favor, verifique o nome."
            
            # O resto da lógica de cálculo de horário continua igual...
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
            
            # 🚀 ALTERAÇÃO: A query de agendamentos agora também filtra pela barbearia_id
            agendamentos_do_dia = (
                Agendamento.query
                .options(joinedload(Agendamento.servico))
                .filter(
                    Agendamento.barbearia_id == barbearia_id, # Garante a barbearia
                    Agendamento.profissional_id == profissional.id,
                    Agendamento.data_hora >= inicio,
                    Agendamento.data_hora < fim
                )
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

def criar_agendamento(barbearia_id: int, nome_cliente: str, telefone_cliente: str, data_hora: str, profissional_nome: str, servico_nome: str) -> str:
    try:
        with current_app.app_context():
            # 🚀 ALTERAÇÃO: Filtra profissional e serviço pela barbearia_id
            profissional = Profissional.query.filter_by(barbearia_id=barbearia_id, nome=profissional_nome).first()
            if not profissional:
                return "Profissional não encontrado."
                
            servico = Servico.query.filter_by(barbearia_id=barbearia_id, nome=servico_nome).first()
            if not servico:
                return "Serviço não encontrado."

            data_hora_dt = datetime.strptime(data_hora, '%Y-%m-%d %H:%M')
            novo_fim = data_hora_dt + timedelta(minutes=servico.duracao)
            inicio_dia = data_hora_dt.replace(hour=0, minute=0)
            fim_dia = data_hora_dt.replace(hour=23, minute=59)

            # 🚀 ALTERAÇÃO: Filtra agendamentos de conflito pela barbearia_id
            ags = (
                Agendamento.query
                .options(joinedload(Agendamento.servico))
                .filter(
                    Agendamento.barbearia_id == barbearia_id,
                    Agendamento.profissional_id == profissional.id,
                    Agendamento.data_hora >= inicio_dia,
                    Agendamento.data_hora < fim_dia
                )
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
                barbearia_id=barbearia_id  # 🚀 ALTERAÇÃO: A "etiqueta" é adicionada!
            )
            db.session.add(novo_agendamento)
            db.session.commit()
            return f"Agendamento criado com sucesso para {nome_cliente} em {data_hora} com {profissional_nome} para {servico_nome}. Confirmação enviada!"
    except Exception as e:
        db.session.rollback()
        return f"Erro ao criar agendamento: {str(e)}"

# ---------------------------------------------------------------------
# FASE DE EXPANSÃO: DEFINIÇÃO DAS TOOLS
# ---------------------------------------------------------------------
# NENHUMA MUDANÇA AQUI, como solicitado.
# Estas são as definições originais (sem barbearia_id) que a IA vai usar.

listar_profissionais_func = FunctionDeclaration(
    name="listar_profissionais",
    description="Lista todos os profissionais disponíveis no sistema.",
    parameters={
        "type": "object",
        "properties": {},
        "required": []
    }
)
listar_servicos_func = FunctionDeclaration(
    name="listar_servicos",
    description="Lista todos os serviços disponíveis no sistema.",
    parameters={
        "type": "object",
        "properties": {},
        "required": []
    }
)
calcular_horarios_disponiveis_func = FunctionDeclaration(
    name="calcular_horarios_disponiveis",
    description="Consulta horários disponíveis para um profissional em um dia específico.",
    parameters={
        "type": "object",
        "properties": {
            "profissional_nome": {
                "type": "string",
                "description": "Nome do profissional (ex.: Bruno)"
            },
            "dia": {
                "type": "string",
                "description": "Dia no formato YYYY-MM-DD, 'hoje' ou 'amanhã'"
            }
        },
        "required": ["profissional_nome", "dia"]
    }
)
criar_agendamento_func = FunctionDeclaration(
    name="criar_agendamento",
    description="Cria um novo agendamento no sistema.",
    parameters={
        "type": "object",
        "properties": {
            "nome_cliente": {
                "type": "string",
                "description": "Nome do cliente"
            },
            "telefone_cliente": {
                "type": "string",
                "description": "Telefone do cliente (ex.: +5513988057145)"
            },
            "data_hora": {
                "type": "string",
                "description": "Data e hora no formato YYYY-MM-DD HH:MM"
            },
            "profissional_nome": {
                "type": "string",
                "description": "Nome do profissional"
            },
            "servico_nome": {
                "type": "string",
                "description": "Nome do serviço (ex.: Corte de Cabelo)"
            }
        },
        "required": ["nome_cliente", "telefone_cliente", "data_hora", "profissional_nome", "servico_nome"]
    }
)
tools = Tool(
    function_declarations=[
        listar_profissionais_func,
        listar_servicos_func,
        calcular_horarios_disponiveis_func,
        criar_agendamento_func
    ]
)

# Inicializa o modelo Gemini (continua igual)
try:
    model = genai.GenerativeModel(
        model_name='models/gemini-2.5-flash',
        tools=[tools],
        system_instruction=SYSTEM_INSTRUCTION_TEMPLATE
    )
    logging.info("Modelo Gemini inicializado com sucesso!")
except Exception as e:
    logging.error(f"Erro ao inicializar o modelo Gemini: {e}")
    model = None