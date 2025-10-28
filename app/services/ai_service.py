# app/services/ai_service.py
import os
import logging
import google.generativeai as genai
from datetime import datetime, timedelta
from flask import current_app
from sqlalchemy.orm import joinedload
from google.generativeai.types import FunctionDeclaration, Tool
# Importa modelos e DB
from app.models.tables import Agendamento, Profissional, Servico, Barbearia # type: ignore
from app.extensions import db

# 🚀 IMPORTAÇÃO DA FUNÇÃO UNIFICADA DE CÁLCULO DE HORÁRIOS
from app.utils import calcular_horarios_disponiveis as calcular_horarios_disponiveis_util

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 🚀 PROMPT REVISADO (SEM TELEFONE e datas dinâmicas removidas temporariamente do template)
SYSTEM_INSTRUCTION_TEMPLATE = """
Você é a Luana, a assistente de IA da Barber Shop Jeziel Oliveira. Sua personalidade é carismática, simpática e muito eficiente. Use emojis de forma natural (✂️, ✨, 😉, 👍).
Use o contexto da conversa para entender "hoje" e "amanhã".

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
    * `criar_agendamento`: Crie o agendamento (args: nome_cliente, data_hora 'YYYY-MM-DD HH:MM', profissional_nome, servico_nome). **NÃO INCLUA TELEFONE AQUI.**
4.  **DATAS:** Use o contexto da conversa para datas. Peça no formato AAAA-MM-DD se necessário.
5.  **TELEFONE:** **NUNCA PERGUNTE OU MENCIONE O TELEFONE DO CLIENTE!** O sistema trata disso automaticamente. Foque em nome, serviço, profissional e data/hora.
6.  **NOME DO CLIENTE:** Pergunte o nome do cliente **APENAS NO FINAL**, antes de chamar `criar_agendamento`.
7.  **CONFIRMAÇÃO FINAL:** Após usar `criar_agendamento` com sucesso, confirme: "Perfeito, {{nome_do_cliente}}! ✨ Seu agendamento para {{Serviço}} com o {{Profissional}} no dia {{Data}} às {{Hora}} está confirmado. Usamos o número que você nos contactou. Estamos te esperando! 👍"
8.  **NÃO MOSTRE SEU PENSAMENTO:** Nunca inclua nomes de ferramentas na resposta para o cliente.

**REGRAS DE OURO PARA UM ATENDIMENTO PERFEITO (NÃO QUEBRE NUNCA):**
1. **INFORME O CONTEXTO TEMPORAL:** A data de hoje é {current_date}. Use esta informação para entender "hoje" e "amanhã".
2. **NUNCA ALUCINE:** Você é proibido de inventar nomes. Para saber os profissionais ou serviços, sua PRIMEIRA ação DEVE ser usar as ferramentas `listar_profissionais` ou `listar_servicos`.
3. **SEJA PROATIVA E RÁPIDA:**
   - Inicie a conversa de forma proativa. Ex: "Olá! Sou a Luana, da Vila Chic Barber Shop. Para quem gostaria de agendar, com o Romario ou o Guilherme? 😉"
   - Se o cliente já deu informações, não pergunte de novo. Se ele disse "corte com Romario amanhã", sua próxima pergunta deve ser "Ótimo! Qual horário prefere amanhã?".
   - Agrupe perguntas sempre que possível.
4. **NÃO MOSTRE SEU PENSAMENTO:** A sua resposta final para o cliente NUNCA deve conter o nome de uma ferramenta (como 'tools.calcular_horarios...'). Apenas devolva o texto da conversa.
5. **CONFIRME TUDO:** Após a ferramenta `criar_agendamento` confirmar o sucesso, envie uma mensagem final clara: "Perfeito, {{nome_do_cliente}}! ✨ Seu agendamento para {{Serviço}} com o {{Profissional}} no dia {{Data}} às {{Hora}} está confirmado. O número {{telefone_do_cliente}} foi salvo para este agendamento. Estamos te esperando! 👍"

**Exemplo de Fluxo (Adaptável aos Profissionais Reais):**
[Usuário: Oi]
[Luana: Olá! Sou Luana da Barber Shop Jeziel Oliveira 😊. Como posso ajudar: agendar, reagendar ou cancelar?]
[Usuário: Quero agendar com Fabio]
[Luana: (Usa `listar_profissionais` -> Retorna: Fabio, Romario, Guilherme) Perfeito! Com o Fabio. Qual serviço você gostaria e para qual dia/hora prefere?]
[Usuário: Corte hoje 15h]
[Luana: (Usa `calcular_horarios_disponiveis` para Fabio, hoje) Um momento... Verificando para Corte com Fabio hoje às 15:00... Disponível! ✅ Para confirmar, qual o seu nome?]
[Usuário: Juan]
[Luana: (Usa `criar_agendamento` com nome_cliente=Juan, data_hora=..., profissional=Fabio, servico=Corte) Perfeito, Juan! ✨ Seu agendamento para Corte de Cabelo com o Fabio hoje às 15:00 está confirmado. Usamos o número que você nos contactou. Estamos te esperando! 👍]
"""

# Configuração do Gemini (como estava)
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
if not GEMINI_API_KEY:
    logging.error("Chave da API do Gemini não encontrada!")
else:
    genai.configure(api_key=GEMINI_API_KEY)

# ---------------------------------------------------------------------
# FUNÇÕES TOOLS ATUALIZADAS (Multi-Tenancy)
# ---------------------------------------------------------------------

def listar_profissionais(barbearia_id: int) -> str:
    # (Código original desta função preservado)
    try:
        with current_app.app_context():
            profissionais = Profissional.query.filter_by(barbearia_id=barbearia_id).all()
            if not profissionais:
                return "Nenhum profissional cadastrado para esta barbearia no momento."
            nomes = [p.nome for p in profissionais]
            return f"Profissionais disponíveis: {', '.join(nomes)}."
    except Exception as e:
        current_app.logger.error(f"Erro interno na ferramenta 'listar_profissionais': {e}", exc_info=True)
        # Retorna mensagem genérica para a IA, mas loga o detalhe
        return f"Erro ao listar profissionais: Ocorreu um erro interno."

def listar_servicos(barbearia_id: int) -> str:
    # (Código original desta função preservado)
    try:
        with current_app.app_context():
            servicos = Servico.query.filter_by(barbearia_id=barbearia_id).all()
            if not servicos:
                return "Nenhum serviço cadastrado para esta barbearia."
            lista_formatada = [
                f"{s.nome} ({s.duracao} min, R$ {s.preco:.2f})"
                for s in servicos
            ]
            return f"Serviços disponíveis: {'; '.join(lista_formatada)}."
    except Exception as e:
        current_app.logger.error(f"Erro interno na ferramenta 'listar_servicos': {e}", exc_info=True)
        return f"Erro ao listar serviços: {str(e)}" # Pode expor detalhes, talvez simplificar

# 🚀 FUNÇÃO WRAPPER: Chama a função unificada do utils.py
def calcular_horarios_disponiveis(barbearia_id: int, profissional_nome: str, dia: str) -> str:
    """
    Wrapper para a função utilitária. Busca o profissional e chama a lógica unificada.
    Retorna uma string formatada para a IA.
    """
    try:
        with current_app.app_context():
            profissional = Profissional.query.filter_by(
                barbearia_id=barbearia_id, 
                nome=profissional_nome
            ).first()
            
            if not profissional:
                return "Profissional não encontrado. Por favor, verifique o nome."
            
            # Determina o objeto datetime para o dia
            agora = datetime.now() # Naive por enquanto, a função util lida com timezone
            if dia.lower() == 'hoje':
                dia_dt = agora
            elif dia.lower() == 'amanhã':
                dia_dt = agora + timedelta(days=1)
            else:
                try:
                    # Tenta converter YYYY-MM-DD para datetime (naive)
                    dia_dt = datetime.strptime(dia, '%Y-%m-%d')
                except ValueError:
                    return "Formato de data inválido. Use 'hoje', 'amanhã' ou 'AAAA-MM-DD'."

            # Chama a função unificada de utils.py
            horarios_dt_list = calcular_horarios_disponiveis_util(profissional, dia_dt)
            
            # Formata a lista de datetimes (com timezone) para string H:M
            horarios_str_list = [h.strftime('%H:%M') for h in horarios_dt_list]
            
            # Usa strftime para formatar a data consistentemente (DD/MM/YYYY)
            dia_formatado = dia_dt.strftime('%d/%m/%Y') 
            
            return f"Horários disponíveis para {profissional_nome} em {dia_formatado}: {', '.join(horarios_str_list) or 'Nenhum horário encontrado.'}"
            
    except Exception as e:
        current_app.logger.error(f"Erro no wrapper 'calcular_horarios_disponiveis': {e}", exc_info=True)
        return "Desculpe, ocorreu um erro ao verificar os horários."


def criar_agendamento(barbearia_id: int, nome_cliente: str, telefone_cliente: str, data_hora: str, profissional_nome: str, servico_nome: str) -> str:
    # (Código original desta função preservado)
    try:
        with current_app.app_context():
            profissional = Profissional.query.filter_by(barbearia_id=barbearia_id, nome=profissional_nome).first()
            if not profissional:
                return "Profissional não encontrado."
                
            servico = Servico.query.filter_by(barbearia_id=barbearia_id, nome=servico_nome).first()
            if not servico:
                return "Serviço não encontrado."

            # Converte para datetime e torna naive para salvar no DB
            data_hora_dt = datetime.strptime(data_hora, '%Y-%m-%d %H:%M').replace(tzinfo=None) 
            
            novo_fim = data_hora_dt + timedelta(minutes=servico.duracao)
            inicio_dia = data_hora_dt.replace(hour=0, minute=0, second=0, microsecond=0)
            fim_dia = inicio_dia + timedelta(days=1) # Corrigido para pegar até o fim do dia

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
            # Compara naive com naive
            conflito = any(
                max(data_hora_dt, ag.data_hora) < min(novo_fim, ag.data_hora + timedelta(minutes=ag.servico.duracao))
                for ag in ags
            )
            if conflito:
                return "Conflito de horário. Por favor, escolha outro."

            novo_agendamento = Agendamento(
                nome_cliente=nome_cliente,
                telefone_cliente=telefone_cliente, # Recebido do webhook
                data_hora=data_hora_dt, # Salva naive
                profissional_id=profissional.id,
                servico_id=servico.id,
                barbearia_id=barbearia_id 
            )
            db.session.add(novo_agendamento)
            db.session.commit()
            # Formata data/hora para a mensagem de confirmação
            data_hora_formatada = data_hora_dt.strftime('%d/%m/%Y às %H:%M')
            return f"Agendamento criado com sucesso para {nome_cliente} em {data_hora_formatada} com {profissional_nome} para {servico_nome}." # Removido 'Confirmação enviada!'
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Erro na ferramenta 'criar_agendamento': {e}", exc_info=True)
        return f"Erro ao criar agendamento: {str(e)}" # Pode expor detalhes, talvez simplificar

# ---------------------------------------------------------------------
# DEFINIÇÃO DAS TOOLS (Atualizada)
# ---------------------------------------------------------------------

listar_profissionais_func = FunctionDeclaration(
    name="listar_profissionais",
    description="Lista todos os profissionais disponíveis no sistema.",
    parameters={ "type": "object", "properties": {}, "required": [] }
)
listar_servicos_func = FunctionDeclaration(
    name="listar_servicos",
    description="Lista todos os serviços disponíveis, incluindo duração e preço.",
    parameters={ "type": "object", "properties": {}, "required": [] }
)
calcular_horarios_disponiveis_func = FunctionDeclaration(
    name="calcular_horarios_disponiveis",
    description="Consulta horários disponíveis (slots de 30 min) para um profissional em um dia específico.",
    parameters={
        "type": "object",
        "properties": {
            "profissional_nome": {
                "type": "string",
                "description": "Nome exato do profissional (confirmado pela ferramenta listar_profissionais)"
            },
            "dia": {
                "type": "string",
                "description": "Dia no formato YYYY-MM-DD, ou as palavras 'hoje' ou 'amanhã'"
            }
        },
        "required": ["profissional_nome", "dia"]
    }
)

# 🚀 FERRAMENTA 'criar_agendamento' SEM o parâmetro 'telefone_cliente'
criar_agendamento_func = FunctionDeclaration(
    name="criar_agendamento",
    description="Cria um novo agendamento no sistema. O telefone do cliente é obtido automaticamente pelo sistema.",
    parameters={
        "type": "object",
        "properties": {
            "nome_cliente": {
                "type": "string",
                "description": "Nome do cliente (obtido na conversa)"
            },
            # "telefone_cliente": Removido da definição!
            "data_hora": {
                "type": "string",
                "description": "Data e hora exata do início do agendamento no formato YYYY-MM-DD HH:MM (ex: 2025-10-28 15:00)"
            },
            "profissional_nome": {
                "type": "string",
                "description": "Nome exato do profissional escolhido (confirmado pela ferramenta listar_profissionais)"
            },
            "servico_nome": {
                "type": "string",
                "description": "Nome exato do serviço escolhido (confirmado pela ferramenta listar_servicos)"
            }
        },
        # 'telefone_cliente' removido dos requeridos
        "required": ["nome_cliente", "data_hora", "profissional_nome", "servico_nome"] 
    }
)

# Agrupa as ferramentas
tools = Tool(
    function_declarations=[
        listar_profissionais_func,
        listar_servicos_func,
        calcular_horarios_disponiveis_func,
        criar_agendamento_func 
    ]
)

# Inicialização do Modelo Gemini (Usa o prompt e tools atualizados)
model = None # Inicializa como None por segurança
try:
    # TODO: Idealmente, o system_instruction deveria ser formatado com a data atual
    #       antes de inicializar o modelo, ou passado dinamicamente ao gerar conteúdo.
    #       Por agora, a IA usará a data do prompt estático.
    model = genai.GenerativeModel(
        model_name='gemini-1.5-flash', # Usando 1.5 Flash
        tools=[tools],
        system_instruction=SYSTEM_INSTRUCTION_TEMPLATE 
    )
    logging.info("Modelo Gemini inicializado com SUCESSO com utils e tools atualizadas!")
except Exception as e:
    logging.error(f"ERRO CRÍTICO ao inicializar o modelo Gemini: {e}", exc_info=True)
    # Mantém model como None se a inicialização falhar