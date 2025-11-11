# app/services/ai_service.py
# (CÓDIGO COMPLETO E CORRIGIDO)

import os
import logging
import google.generativeai as genai
# Importa a exceção NotFound para tratamento específico
from google.api_core.exceptions import NotFound 
from datetime import datetime, timedelta
from flask import current_app
from sqlalchemy.orm import joinedload
from google.generativeai.types import FunctionDeclaration, Tool
# Importa modelos e DB
from app.models.tables import Agendamento, Profissional, Servico, Barbearia # type: ignore
from app.extensions import db
import time # Importa time para o retry
from google.api_core.exceptions import ResourceExhausted # Importa a exceção de Quota

# 🚀 IMPORTAÇÃO DA FUNÇÃO UNIFICADA DE CÁLCULO DE HORÁRIOS
from app.utils import calcular_horarios_disponiveis as calcular_horarios_disponiveis_util

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- PROMPT (Preservado 100%) ---
SYSTEM_INSTRUCTION_TEMPLATE = """
Você é 'Luana', uma assistente de IA da {barbearia_nome}.
Seja sempre simpática, direta e 100% focada em agendamentos. Use emojis (✂️, ✨, 😉, 👍) quando apropriado.
O seu ID de cliente é: {cliente_whatsapp}
A sua Barbearia ID é: {barbearia_id}

1.  **SSAUDAÇÃO INICIAL: Sempre comece a primeira conversa com: "Olá! Bem-vindo(a) à {barbearia_nome}! 😊 Como posso ajudar no seu agendamento? Ou quer reagendar ou cancelar um horário?"
2.  **PARA AGENDAR - SEJA PROATIVA:**
    * **CONFIRME PROFISSIONAIS:** Use `listar_profissionais` primeiro. **Confie na lista retornada.** Ofereça os nomes da lista. Se o cliente pedir um nome que não está na lista, informe educadamente quem está disponível.
    * **CONFIRME SERVIÇOS E PREÇOS:** Use `listar_servicos`. Ao apresentar ou confirmar um serviço, **SE** a ferramenta indicar "(a partir de)" ao lado do preço, **REPITA** essa informação para o cliente. Ex: "O Platinado (120 min) custa *a partir de* R$ 100,00." Para outros serviços, diga o preço normalmente.
3.  **USE AS FERRAMENTAS INTERNAMENTE:** `listar_profissionais`, `listar_servicos`, `calcular_horarios_disponiveis`, `criar_agendamento`.
4.  **DATAS:** Use o contexto. Peça AAAA-MM-DD se necessário.
5.  **TELEFONE:** **NUNCA PERGUNTE OU MENCIONE.**
6.  **NOME DO CLIENTE:** Pergunte **APENAS NO FINAL**, antes de `criar_agendamento`.
7.  **CONFIRMAÇÃO FINAL:** Após `criar_agendamento` sucesso: "Perfeito, {{nome_do_cliente}}! ✨ Seu agendamento para {{Serviço}} com o {{Profissional}} no dia {{Data}} às {{Hora}} está confirmado. Usamos o número que você nos contactou. Estamos te esperando! 👍"
8.  **NÃO MOSTRE PENSAMENTO:** Sem nomes de ferramentas na resposta.

**Exemplo de Fluxo (Com Preço Variável):**
[Usuário: Quero fazer luzes com o Fabio amanhã]
[Luana: (Usa `listar_profissionais` -> OK) (Usa `listar_servicos` -> Retorna: Luzes (90 min, R$ 50.00 (a partir de))...) Combinado, com o Fabio! Sobre as Luzes (que levam 90 min), o valor é *a partir de* R$ 50,00, ok? Qual horário prefere amanhã?]
[Usuário: 10h]
[Luana: (Usa `calcular_horarios_disponiveis`...) Verificando... Sim, 10:00 está livre com o Fabio amanhã! ✅ Para confirmar, qual o seu nome?]
[Usuário: Carlos]
[Luana: (Usa `criar_agendamento`...) Perfeito, Carlos! ✨ Seu agendamento para Luzes com o Fabio amanhã às 10:00 está confirmado. Usamos o número que você nos contactou. Estamos te esperando! 👍]
"""

# Configuração do Gemini (como estava)
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
if not GEMINI_API_KEY:
    logging.error("Chave da API do Gemini não encontrada!")
else:
    genai.configure(api_key=GEMINI_API_KEY)

# ---------------------------------------------------------------------
# FUNÇÕES TOOLS ATUALIZADAS (Multi-Tenancy)
# (Seu código original 100% preservado)
# ---------------------------------------------------------------------

def listar_profissionais(barbearia_id: int) -> str:
    try:
        with current_app.app_context():
            profissionais = Profissional.query.filter_by(barbearia_id=barbearia_id).all()
            if not profissionais:
                logging.warning(f"Ferramenta 'listar_profissionais' (barbearia_id: {barbearia_id}): Nenhum profissional cadastrado.")
                return "Nenhum profissional cadastrado para esta barbearia no momento."
            nomes = [p.nome for p in profissionais]
            return f"Profissionais disponíveis: {', '.join(nomes)}."
    except Exception as e:
        current_app.logger.error(f"Erro interno na ferramenta 'listar_profissionais': {e}", exc_info=True)
        return f"Erro ao listar profissionais: Ocorreu um erro interno."

def listar_servicos(barbearia_id: int) -> str:
    """Lista os serviços, adicionando '(a partir de)' para preços variáveis."""
    try:
        with current_app.app_context():
            servicos = Servico.query.filter_by(barbearia_id=barbearia_id).order_by(Servico.nome).all()
            if not servicos:
                logging.warning(f"Ferramenta 'listar_servicos' (barbearia_id: {barbearia_id}): Nenhum serviço cadastrado.")
                return "Nenhum serviço cadastrado para esta barbearia."
            
            lista_formatada = []
            servicos_a_partir_de = [
                "Platinado", "Luzes", "Coloração", "Pigmentação", 
                "Selagem", "Escova Progressiva", "Relaxamento", 
                "Alisamento", "Hidratação", "Reconstrução"
            ]
            
            for s in servicos:
                preco_str = f"R$ {s.preco:.2f}"
                if s.nome in servicos_a_partir_de:
                    preco_str += " (a partir de)"
                lista_formatada.append(f"{s.nome} ({s.duracao} min, {preco_str})")
                
            return f"Serviços disponíveis: {'; '.join(lista_formatada)}."
    except Exception as e:
        current_app.logger.error(f"Erro interno na ferramenta 'listar_servicos': {e}", exc_info=True)
        return f"Erro ao listar serviços: Ocorreu um erro interno."

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
            
            agora = datetime.now() 
            if dia.lower() == 'hoje':
                dia_dt = agora
            elif dia.lower() == 'amanhã':
                dia_dt = agora + timedelta(days=1)
            else:
                try:
                    dia_dt = datetime.strptime(dia, '%Y-%m-%d')
                except ValueError:
                    return "Formato de data inválido. Use 'hoje', 'amanhã' ou 'AAAA-MM-DD'."

            horarios_dt_list = calcular_horarios_disponiveis_util(profissional, dia_dt)
            horarios_str_list = [h.strftime('%H:%M') for h in horarios_dt_list]
            dia_formatado = dia_dt.strftime('%d/%m/%Y') 
            
            return f"Horários disponíveis para {profissional_nome} em {dia_formatado}: {', '.join(horarios_str_list) or 'Nenhum horário encontrado.'}"
            
    except Exception as e:
        current_app.logger.error(f"Erro no wrapper 'calcular_horarios_disponiveis': {e}", exc_info=True)
        return "Desculpe, ocorreu um erro ao verificar os horários."

def criar_agendamento(barbearia_id: int, nome_cliente: str, telefone_cliente: str, data_hora: str, profissional_nome: str, servico_nome: str) -> str:
    # (Seu código original 100% preservado)
    try:
        with current_app.app_context():
            profissional = Profissional.query.filter_by(barbearia_id=barbearia_id, nome=profissional_nome).first()
            if not profissional:
                return "Profissional não encontrado."
            servico = Servico.query.filter_by(barbearia_id=barbearia_id, nome=servico_nome).first()
            if not servico:
                return "Serviço não encontrado."
            data_hora_dt = datetime.strptime(data_hora, '%Y-%m-%d %H:%M').replace(tzinfo=None) 
            novo_fim = data_hora_dt + timedelta(minutes=servico.duracao)
            inicio_dia = data_hora_dt.replace(hour=0, minute=0, second=0, microsecond=0)
            fim_dia = inicio_dia + timedelta(days=1)
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
                barbearia_id=barbearia_id 
            )
            db.session.add(novo_agendamento)
            db.session.commit()
            data_hora_formatada = data_hora_dt.strftime('%d/%m/%Y às %H:%M')
            return f"Agendamento criado com sucesso para {nome_cliente} em {data_hora_formatada} com {profissional_nome} para {servico_nome}."
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Erro na ferramenta 'criar_agendamento': {e}", exc_info=True)
        return f"Erro ao criar agendamento: {str(e)}" 

# ---------------------------------------------------------------------
# DEFINIÇÃO DAS TOOLS (Preservada)
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
            "profissional_nome": { "type": "string", "description": "Nome exato do profissional (confirmado pela ferramenta listar_profissionais)" },
            "dia": { "type": "string", "description": "Dia no formato YYYY-MM-DD, ou as palavras 'hoje' ou 'amanhã'" }
        },
        "required": ["profissional_nome", "dia"]
    }
)
criar_agendamento_func = FunctionDeclaration(
    name="criar_agendamento",
    description="Cria um novo agendamento no sistema. O telefone do cliente é obtido automaticamente pelo sistema.",
    parameters={
        "type": "object",
        "properties": {
            "nome_cliente": { "type": "string", "description": "Nome do cliente (obtido na conversa)" },
            "data_hora": { "type": "string", "description": "Data e hora exata do início do agendamento no formato YYYY-MM-DD HH:MM (ex: 2025-10-28 15:00)" },
            "profissional_nome": { "type": "string", "description": "Nome exato do profissional escolhido (confirmado pela ferramenta listar_profissionais)" },
            "servico_nome": { "type": "string", "description": "Nome exato do serviço escolhido (confirmado pela ferramenta listar_servicos)" }
        },
        "required": ["nome_cliente", "data_hora", "profissional_nome", "servico_nome"] 
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

# --- Inicialização do Modelo Gemini (Corrigida) ---
model = None 
try:
    model_name_to_use = 'models/gemini-pro-latest' # Mantendo o seu modelo
    
    # --- CORREÇÃO CRÍTICA ---
    # Removemos o 'system_instruction' ESTÁTICO daqui.
    # O prompt agora é 100% dinâmico e definido em 'processar_ia_gemini'
    model = genai.GenerativeModel( model_name=model_name_to_use, tools=[tools] )
    # ------------------------
    
    logging.info(f"Modelo Gemini ('{model_name_to_use}') inicializado com SUCESSO!")
except NotFound as nf_error:
    logging.error(f"ERRO CRÍTICO: Modelo Gemini '{model_name_to_use}' não encontrado: {nf_error}", exc_info=True)
except Exception as e:
    logging.error(f"ERRO CRÍTICO GERAL ao inicializar o modelo Gemini: {e}", exc_info=True)


# --- ADIÇÃO: O HISTÓRICO DA CONVERSA ---
convo_history = {}

# --- FUNÇÃO PRINCIPAL DE PROCESSAMENTO (O cérebro) ---
# (Seu código original 100% preservado, com a correção do loop de retry)
def processar_ia_gemini(user_message: str, barbearia_id: int, cliente_whatsapp: str) -> str:
    """
    Processa a mensagem do usuário usando o Gemini, com histórico e ferramentas.
    Otimizado para usar MENOS requisições.
    """
    if not model:
        logging.error("Modelo Gemini não inicializado. Abortando.")
        return "Desculpe, meu cérebro (IA) está offline no momento. Tente novamente mais tarde."
    try:
        barbearia = Barbearia.query.get(barbearia_id)
        if not barbearia:
            logging.error(f"Barbearia ID {barbearia_id} não encontrada no processar_ia_gemini.")
            return "Desculpe, não consegui identificar para qual barbearia você está ligando."
        
        # Formata o prompt do sistema com os dados da barbearia
        system_prompt = SYSTEM_INSTRUCTION_TEMPLATE.format(
            barbearia_nome=barbearia.nome_fantasia,
            cliente_whatsapp=cliente_whatsapp,
            barbearia_id=barbearia_id
        )
        
        # Inicia (ou recupera) o histórico
        if cliente_whatsapp not in convo_history:
            logging.info(f"Iniciando novo histórico de chat para o cliente {cliente_whatsapp}.")
            # Cria o histórico de chat com o prompt do sistema
            convo_history[cliente_whatsapp] = model.start_chat(history=[
                {'role': 'user', 'parts': [system_prompt]},
                {'role': 'model', 'parts': [
                    f"Olá! Bem-vindo(a) à {barbearia.nome_fantasia}! 😊 Como posso ajudar no seu agendamento?"
                ]}
            ])
            # Retorna a saudação inicial na primeira mensagem
            return f"Olá! Bem-vindo(a) à {barbearia.nome_fantasia}! 😊 Como posso ajudar no seu agendamento?"
       
        chat_session = convo_history[cliente_whatsapp]
        logging.info(f"Enviando mensagem para a IA: {user_message}")
        
        # --- CORREÇÃO: LÓGICA DE RETRY (Preservada do seu código, mas corrigida) ---
        response = None # Define response como None
        retries = 3
        for attempt in range(retries):
            try:
                # A mensagem é enviada AQUI
                response = chat_session.send_message(user_message)
                break # Sai do loop se for um sucesso
            except ResourceExhausted as e:
                # Se a quota esgotar, espera e tenta de novo
                wait_time = 60
                logging.warning(f"Quota excedida (Gemini). Tentando novamente em {wait_time}s... (Tentativa {attempt+1}/{retries})")
                time.sleep(wait_time)
            except Exception as e:
                # Outros erros
                logging.error(f"Erro ao enviar mensagem para a IA na tentativa {attempt+1}: {e}", exc_info=True)
                if attempt == retries - 1: # Se for a última tentativa
                    logging.error("Erro persistente na IA após todas as tentativas.")
                    return "Desculpe, estou com um problema de comunicação com meu cérebro (IA). Tente novamente mais tarde."
        
        if response is None:
             logging.error("Falha ao obter resposta da IA após todas as retries.")
             return "Desculpe, não consegui processar sua solicitação agora (limite de quota). Por favor, tente novamente em alguns minutos."
        # ----------------------------------------------------------------
       
        # --- LÓGICA DE FERRAMENTAS (Preservada) ---
        while response.candidates[0].content.parts and response.candidates[0].content.parts[0].function_call:
           
            function_call = response.candidates[0].content.parts[0].function_call
            function_name = function_call.name
            function_args = function_call.args
           
            logging.info(f"IA solicitou a ferramenta '{function_name}' com os argumentos: {dict(function_args)}")
            
            tool_map = {
                "listar_profissionais": listar_profissionais,
                "listar_servicos": listar_servicos,
                "calcular_horarios_disponiveis": calcular_horarios_disponiveis,
                "criar_agendamento": criar_agendamento,
            }
            
            if function_name in tool_map:
                function_to_call = tool_map[function_name]
                kwargs = dict(function_args)
                kwargs['barbearia_id'] = barbearia_id
                
                if function_name == 'criar_agendamento':
                     kwargs['telefone_cliente'] = cliente_whatsapp 
                
                tool_response = function_to_call(**kwargs)
                
                response = chat_session.send_message(
                    genai.Part(function_response={"name": function_name, "response": tool_response}),
                )
            else:
                logging.error(f"Erro: IA tentou chamar uma ferramenta desconhecida: {function_name}")
                response = chat_session.send_message(
                    genai.Part(function_response={"name": function_name, "response": {"error": "Ferramenta não encontrada."}}),
                )
        
        # --- Resposta Final ---
        final_response_text = response.candidates[0].content.parts[0].text
        logging.info(f"Resposta final da IA: {final_response_text}")
        return final_response_text
        
    except Exception as e:
        logging.error(f"Erro GRANDE ao processar com IA: {e}", exc_info=True)
        if cliente_whatsapp in convo_history:
            del convo_history[cliente_whatsapp] # Limpa o histórico se der erro
        return "Desculpe, tive um problema para processar sua solicitação. Vamos tentar de novo do começo. O que você gostaria?"