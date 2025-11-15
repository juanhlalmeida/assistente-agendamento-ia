# app/services/ai_service.py
# (CÓDIGO COMPLETO E REATORADO PARA USAR REDIS/CACHE)

import os
import logging
import json  # [cite: 104]
import google.generativeai as genai
from google.api_core.exceptions import NotFound 
from datetime import datetime, timedelta
from flask import current_app
from sqlalchemy.orm import joinedload

# --- INÍCIO DA IMPLEMENTAÇÃO (Conforme o PDF) ---
# Importa o cache das extensões [cite: 165]
from app.extensions import cache 
# Importa os tipos de dados do Gemini para serialização
from google.generativeai.protos import Content  # <-- ESTA É A CORREÇÃO
# (Usamos 'protos' como no seu código original para FunctionCall/Response)
from google.generativeai import protos  #
# --- FIM DA IMPLEMENTAÇÃO ---

from google.generativeai.types import FunctionDeclaration, Tool 
import pytz
BR_TZ = pytz.timezone('America/Sao_Paulo') 
from app.models.tables import Agendamento, Profissional, Servico, Barbearia  # type: ignore
from app.extensions import db
import time 
from google.api_core.exceptions import ResourceExhausted 

from app.utils import calcular_horarios_disponiveis as calcular_horarios_disponiveis_util

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- PROMPT REFINADO (Preservado 100%) ---
SYSTEM_INSTRUCTION_TEMPLATE = """
Voce e 'Luana', uma assistente de IA da {barbearia_nome}.
Seja sempre simpatica, direta e 100% focada em agendamentos. Use emojis (tesoura, brilho, piscada, polegar pra cima) quando apropriado.
O seu ID de cliente e: {cliente_whatsapp}
A sua Barbearia ID e: {barbearia_id}

REGRAS DE OURO (NAO QUEBRE NUNCA):
1. **SAUDACAO:** Voce so deve saudar o cliente UMA VEZ, na primeira mensagem da conversa.
2. **FOCO TOTAL:** O seu unico objetivo e preencher os 4 campos: [servico], [profissional], [data], [hora].
3. **NAO ALUCINE (NAO INVENTE):**
    * **NUNCA** invente nomes de profissionais ou servicos que nao estejam na lista.
    * Use **EXATAMENTE** os nomes retornados pelas ferramentas `listar_profissionais` e `listar_servicos`.
    * Se o cliente disser "corte de cabelo" e a ferramenta retornar "Corte", voce DEVE confirmar: "Entendido, o servico e 'Corte', correto?".
4. **SEJA PROATIVA:** Se faltar mais de uma informacao, pergunte por TUDO o que falta de uma vez.
5. **USE AS FERRAMENTAS:** `listar_profissionais`, `listar_servicos`, `calcular_horarios_disponiveis`, `criar_agendamento`.
   
    # --- ADICIONADO: REGRA DE CANCELAMENTO ---
    * **PARA CANCELAR:** Se o cliente pedir para cancelar, use a ferramenta `cancelar_agendamento_por_telefone`. Você SÓ precisa do dia.
    * Exemplo: "oi, pode cancelar meu corte do dia 16?" -> IA chama `cancelar_agendamento_por_telefone(dia="AAAA-MM-DD")`
    # ----------------------------------------
6. **DATAS:** Use o contexto. Hoje e {data_de_hoje}. "Amanha" e {data_de_amanha}. Use sempre o formato AAAA-MM-DD para as ferramentas.
7. **TELEFONE:** **NUNCA PERGUNTE OU MENCIONE.**
8. **NOME DO CLIENTE:** Pergunte **APENAS NO FINAL**, antes de `criar_agendamento`.
9. **CONFIRMACAO FINAL:** Apos `criar_agendamento` sucesso: "Perfeito, {{nome_do_cliente}}! Seu agendamento para {{Servico}} com o {{Profissional}} no dia {{Data}} as {{Hora}} esta confirmado. Usamos o numero que voce nos contactou. Estamos te esperando!"
10. **PRECOS VARIAVEIS:** Ao confirmar um servico, **SE** a ferramenta `listar_servicos` indicar "(a partir de)" ao lado do preco, **REPITA** essa informacao.

**Exemplo de Fluxo (Com Preço Variável):**
[Usuário: Quero fazer luzes com o Fabio amanhã]
[Luana: (Usa `listar_profissionais` -> OK) (Usa `listar_servicos` -> Retorna: Luzes (90 min, R$ 50.00 (a partir de))...) Combinado, com o Fabio! Sobre as Luzes (que levam 90 min), o valor é *a partir de* R$ 50,00, ok? Qual horário prefere amanhã?]
[Usuário: 10h]
[Luana: (Usa `calcular_horarios_disponiveis`...) Verificando... Sim, 10:00 está livre com o Fabio amanhã! ✅ Para confirmar, qual o seu nome?]
[Usuário: Carlos]
[Luana: (Usa `criar_agendamento`...) Perfeito, Carlos! ✨ Seu agendamento para Luzes com o Fabio amanhã às 10:00 está confirmado. Usamos o número que você nos contactou. Estamos te esperando! 👍]

"""
# ---------------------------------------

# Configuração do Gemini (Preservado)
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
if not GEMINI_API_KEY:
    logging.error("Chave da API do Gemini não encontrada!")
else:
    genai.configure(api_key=GEMINI_API_KEY)

# ---------------------------------------------------------------------
# FUNÇÕES TOOLS (Preservadas 100% + 1 Nova)
# ---------------------------------------------------------------------

def listar_profissionais(barbearia_id: int) -> str:
    try:
        with current_app.app_context():
            profissionais = Profissional.query.filter_by(barbearia_id=barbearia_id).all()
            if not profissionais:
                # Esta é a linha que o seu log mostrou!
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
    # (Seu código original 100% preservado, com a CORREÇÃO DE FUSO HORÁRIO)
    try:
        with current_app.app_context():
            profissional = Profissional.query.filter_by(
                barbearia_id=barbearia_id, 
                nome=profissional_nome
            ).first()
            if not profissional:
                return "Profissional não encontrado. Por favor, verifique o nome."
           
            # --- CORREÇÃO DE FUSO HORÁRIO (Bug 4) ---
            agora_br = datetime.now(BR_TZ) # Usa o fuso do Brasil
           
            if dia.lower() == 'hoje':
                dia_dt = agora_br
            elif dia.lower() == 'amanhã':
                dia_dt = agora_br + timedelta(days=1)
            else:
                try:
                    # Converte AAAA-MM-DD para datetime e *assume* ser do Brasil
                    dia_dt_naive = datetime.strptime(dia, '%Y-%m-%d')
                    dia_dt = BR_TZ.localize(dia_dt_naive)
                except ValueError:
                    return "Formato de data inválido. Use 'hoje', 'amanhã' ou 'AAAA-MM-DD'."
            # ----------------------------------------
            horarios_dt_list = calcular_horarios_disponiveis_util(profissional, dia_dt)
            horarios_str_list = [h.strftime('%H:%M') for h in horarios_dt_list]
            dia_formatado = dia_dt.strftime('%d/%m/%Y') 
            return f"Horários disponíveis para {profissional_nome} em {dia_formatado}: {', '.join(horarios_str_list) or 'Nenhum horário encontrado.'}"
    except Exception as e:
        current_app.logger.error(f"Erro no wrapper 'calcular_horarios_disponiveis': {e}", exc_info=True)
        return "Desculpe, ocorreu um erro ao verificar os horários."

def criar_agendamento(barbearia_id: int, nome_cliente: str, telefone_cliente: str, data_hora: str, profissional_nome: str, servico_nome: str) -> str:
    # (Seu código original 100% preservado, com logging.warning para serviço inexistente)
    try:
        with current_app.app_context():
            profissional = Profissional.query.filter_by(barbearia_id=barbearia_id, nome=profissional_nome).first()
            if not profissional:
                return "Profissional não encontrado."
            servico = Servico.query.filter_by(barbearia_id=barbearia_id, nome=servico_nome).first()
            if not servico:
                # Este foi o Bug 5: A IA tentou agendar "Corte Tradicional", que não existe.
                logging.warning(f"Tentativa de agendar serviço inexistente: '{servico_nome}'")
                return f"Serviço '{servico_nome}' não encontrado. Por favor, confirme o nome do serviço."
               
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

# --- ADICIONADO: A NOVA FERRAMENTA DE CANCELAMENTO ---
def cancelar_agendamento_por_telefone(barbearia_id: int, telefone_cliente: str, dia: str) -> str:
    """
    Cancela TODOS os agendamentos de um cliente (telefone) para um dia específico.
    """
    logging.info(f"Iniciando cancelamento para cliente {telefone_cliente} no dia {dia} para barbearia {barbearia_id}")
    try:
        with current_app.app_context():
            try:
                # Converte o dia (AAAA-MM-DD) para um objeto de data
                dia_dt = datetime.strptime(dia, '%Y-%m-%d').date()
            except ValueError:
                return "Formato de data inválido. Por favor, forneça a data no formato AAAA-MM-DD."
            # Encontra os agendamentos
            inicio_dia = datetime.combine(dia_dt, time.min)
            fim_dia = datetime.combine(dia_dt, time.max)
            agendamentos_para_cancelar = Agendamento.query.filter(
                Agendamento.barbearia_id == barbearia_id,
                Agendamento.telefone_cliente == telefone_cliente,
                Agendamento.data_hora >= inicio_dia,
                Agendamento.data_hora <= fim_dia
            ).all()
            if not agendamentos_para_cancelar:
                logging.warning(f"Nenhum agendamento encontrado para {telefone_cliente} no dia {dia}")
                return f"Não encontrei nenhum agendamento no seu nome (telefone: {telefone_cliente}) para o dia {dia_dt.strftime('%d/%m/%Y')}."
            # Cancela os agendamentos
            nomes_servicos = []
            for ag in agendamentos_para_cancelar:
                nomes_servicos.append(f"{ag.servico.nome} às {ag.data_hora.strftime('%H:%M')}")
                db.session.delete(ag)
           
            db.session.commit()
           
            msg_sucesso = f"Cancelamento concluído! O(s) seu(s) agendamento(s) para {dia_dt.strftime('%d/%m/%Y')} ({', '.join(nomes_servicos)}) foi(ram) cancelado(s)."
            logging.info(msg_sucesso)
            return msg_sucesso
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Erro na ferramenta 'cancelar_agendamento_por_telefone': {e}", exc_info=True)
        return f"Erro ao cancelar agendamento: {str(e)}"
# ----------------------------------------------------

# ---------------------------------------------------------------------
# DEFINIÇÃO DAS TOOLS (Preservada + 1 Nova)
# ---------------------------------------------------------------------
listar_profissionais_func = FunctionDeclaration(
    name="listar_profissionais",
    description="Lista todos os profissionais disponíveis no sistema.",
    parameters={"type": "object", "properties": {}, "required": []}
)
listar_servicos_func = FunctionDeclaration(
    name="listar_servicos",
    description="Lista todos os serviços disponíveis, incluindo duração e preço.",
    parameters={"type": "object", "properties": {}, "required": []}
)
calcular_horarios_disponiveis_func = FunctionDeclaration(
    name="calcular_horarios_disponiveis",
    description="Consulta horários disponíveis (slots de 30 min) para um profissional em um dia específico.",
    parameters={
        "type": "object",
        "properties": {
            "profissional_nome": {"type": "string", "description": "Nome exato do profissional (confirmado pela ferramenta listar_profissionais)"},
            "dia": {"type": "string", "description": "Dia no formato YYYY-MM-DD, ou as palavras 'hoje' ou 'amanhã'"}
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
            "nome_cliente": {"type": "string", "description": "Nome do cliente (obtido na conversa)"},
            "data_hora": {"type": "string", "description": "Data e hora exata do início do agendamento no formato YYYY-MM-DD HH:MM (ex: 2025-10-28 15:00)"},
            "profissional_nome": {"type": "string", "description": "Nome exato do profissional escolhido (confirmado pela ferramenta listar_profissionais)"},
            "servico_nome": {"type": "string", "description": "Nome exato do serviço escolhido (confirmado pela ferramenta listar_servicos)"}
        },
        "required": ["nome_cliente", "data_hora", "profissional_nome", "servico_nome"] 
    }
)

# --- ADICIONADO: Definição da nova ferramenta ---
cancelar_agendamento_func = FunctionDeclaration(
    name="cancelar_agendamento_por_telefone",
    description="Cancela TODOS os agendamentos de um cliente para um dia específico. O telefone do cliente é obtido automaticamente pelo sistema.",
    parameters={
        "type": "object",
        "properties": {
            "dia": {"type": "string", "description": "O dia dos agendamentos a cancelar, no formato YYYY-MM-DD, ou as palavras 'hoje' ou 'amanhã'."}
        },
        "required": ["dia"]
    }
)
# ----------------------------------------------

tools = Tool(
    function_declarations=[
        listar_profissionais_func,
        listar_servicos_func,
        calcular_horarios_disponiveis_func,
        criar_agendamento_func,
        cancelar_agendamento_func  # <-- ADICIONADO
    ]
)

# --- Inicialização do Modelo Gemini (Preservado) ---
model = None 
try:
    model_name_to_use = 'models/gemini-pro-latest'  # Mantendo o seu modelo
    
    # (Removido o system_instruction estático)
    model = genai.GenerativeModel(model_name=model_name_to_use, tools=[tools])
    
    logging.info(f"Modelo Gemini ('{model_name_to_use}') inicializado com SUCESSO!")
except NotFound as nf_error:
    logging.error(f"ERRO CRÍTICO: Modelo Gemini '{model_name_to_use}' não encontrado: {nf_error}", exc_info=True)
except Exception as e:
    logging.error(f"ERRO CRÍTICO GERAL ao inicializar o modelo Gemini: {e}", exc_info=True)

# --- INÍCIO DA IMPLEMENTAÇÃO (Conforme o PDF) ---
# --- REMOVIDO: A VARIÁVEL GLOBAL ---
# convo_history = {} #
# --- ADICIONADO: Funções Helper de Serialização (Adaptadas para 'protos') ---
# [cite: 99, 107]
def serialize_history(history: list[Content]) -> str:
    """
    Serializa o histórico de chat (lista de objetos Content) para uma string JSON.
    Lida com texto, FunctionCall (protos) e FunctionResponse (protos).
    """
    serializable_list = []  # [cite: 109]
    for content in history:  # [cite: 110]
        serial_parts = []  # [cite: 111]
        for part in content.parts:  # [cite: 112]
            part_dict = {}  # [cite: 113]
            if part.text:  # [cite: 114]
                part_dict['text'] = part.text  # [cite: 115]
            # Adaptado para usar 'protos' (que o seu código já usa)
            elif part.function_call:  # [cite: 116]
                part_dict['function_call'] = protos.FunctionCall.to_dict(part.function_call)  # [cite: 118]
            elif part.function_response:  # [cite: 119]
                part_dict['function_response'] = protos.FunctionResponse.to_dict(part.function_response)  # [cite: 120]
           
            if part_dict:  # [cite: 121]
                serial_parts.append(part_dict)  # [cite: 122]
       
        serializable_list.append({
            'role': content.role,  # [cite: 125]
            'parts': serial_parts  # [cite: 126]
        })  # [cite: 123]
    return json.dumps(serializable_list)  # [cite: 127]

def deserialize_history(json_string: str) -> list[Content]:
    """
    Deserializa uma string JSON de volta para uma lista de objetos Content.
    Recria texto, FunctionCall (protos) e FunctionResponse (protos).
    """
    #
    history_list = []  # [cite: 130]
    if not json_string:  # [cite: 131]
        return history_list  # [cite: 132]
    try:
        serializable_list = json.loads(json_string)  # [cite: 134]
    except json.JSONDecodeError:  # [cite: 135]
        logging.warning("Dados de cache de histórico inválidos ou corrompidos.")
        return history_list  # [cite: 136]
    for item in serializable_list:  # [cite: 137]
        deserial_parts = []  # [cite: 138]
        for part_data in item.get('parts', []):  # [cite: 139]
            if 'text' in part_data:  # [cite: 140]
                deserial_parts.append(protos.Part(text=part_data['text']))  # [cite: 141] (Adaptado para protos.Part)
            # Adaptado para usar 'protos'
            elif 'function_call' in part_data:  # [cite: 142]
                fc = protos.FunctionCall(part_data['function_call'])  # [cite: 144]
                deserial_parts.append(protos.Part(function_call=fc))  # [cite: 145]
            elif 'function_response' in part_data:  # [cite: 146]
                fr = protos.FunctionResponse(part_data['function_response'])  # [cite: 147]
                deserial_parts.append(protos.Part(function_response=fr))  # [cite: 147]
       
        history_list.append(Content(role=item.get('role'), parts=deserial_parts))  # [cite: 148]
    return history_list  # [cite: 152]
# --- FIM DAS FUNÇÕES HELPER ---

# --- FUNÇÃO PRINCIPAL DE PROCESSAMENTO (Refatorada para Cache) ---
def processar_ia_gemini(user_message: str, barbearia_id: int, cliente_whatsapp: str) -> str:
    """
    Processa a mensagem do usuário usando o Gemini, mantendo o histórico
    da conversa no cache (Redis) associado ao número do cliente.
    """
    # [cite: 176]
    if not model:
        logging.error("Modelo Gemini não inicializado. Abortando.")
        return "Desculpe, meu cérebro (IA) está offline no momento. Tente novamente mais tarde."
   
    # 1. Definir a Cache Key (Chave do Cache)
    # Usamos o ID do cliente + ID da barbearia para garantir um histórico único
    cache_key = f"chat_history_{cliente_whatsapp}:{barbearia_id}"  # [cite: 183]
   
    try:
        barbearia = Barbearia.query.get(barbearia_id)
        if not barbearia:
            logging.error(f"Barbearia ID {barbearia_id} não encontrada no processar_ia_gemini.")
            return "Desculpe, não consegui identificar para qual barbearia você está ligando."
       
        # 2. Carregar (GET) histórico anterior do cache [cite: 185]
        logging.info(f"Carregando histórico do cache para a chave: {cache_key}")
        serialized_history = cache.get(cache_key)
        history_to_load = deserialize_history(serialized_history)  # [cite: 186]
       
        # (Lógica de Fuso Horário preservada)
        agora_br = datetime.now(BR_TZ)
        data_hoje_str = agora_br.strftime('%Y-%m-%d')
        data_amanha_str = (agora_br + timedelta(days=1)).strftime('%Y-%m-%d')
       
        system_prompt = SYSTEM_INSTRUCTION_TEMPLATE.format(
            barbearia_nome=barbearia.nome_fantasia,
            cliente_whatsapp=cliente_whatsapp,
            barbearia_id=barbearia_id,
            data_de_hoje=data_hoje_str,
            data_de_amanha=data_amanha_str
        )
       
        # 3. Iniciar a sessão de chat (Corrigido o Bug 1 da saudação)
        is_new_chat = not history_to_load  # [cite: 180]
       
        if is_new_chat:
            logging.info(f"Iniciando NOVO histórico de chat para o cliente {cliente_whatsapp}.")
            # Cria o histórico de chat com o prompt do sistema
            history_to_load = [
                {'role': 'user', 'parts': [system_prompt]},
                {'role': 'model', 'parts': [
                    f"Olá! Bem-vindo(a) à {barbearia.nome_fantasia}! Como posso ajudar no seu agendamento?"
                ]}
            ]
       
        chat_session = model.start_chat(history=history_to_load)  # [cite: 197]
       
        # Se for um chat novo E o usuário SÓ disse "oi", retorna a saudação e para
        if is_new_chat and user_message.lower().strip() in ['oi', 'ola', 'olá', 'bom dia', 'boa tarde', 'boa noite']:
             # Salva o histórico inicial (saudação) no cache
             new_serialized_history = serialize_history(chat_session.history)  # [cite: 225]
             cache.set(cache_key, new_serialized_history)  # [cite: 227]
             return f"Olá! Bem-vindo(a) à {barbearia.nome_fantasia}! Como posso ajudar no seu agendamento?"
      
        logging.info(f"Enviando mensagem para a IA: {user_message}")
       
        # 4. Enviar mensagem para a IA (Lógica de retry preservada)
        try:
            response = chat_session.send_message(user_message)  # [cite: 200]
        except ResourceExhausted as e:
            logging.warning(f"Quota do Gemini excedida: {e}")
            return "Puxa, parece que atingi meu limite de processamento por agora. 😕 Por favor, tente novamente em um minuto."
        except Exception as e:
            logging.error(f"Erro ao enviar mensagem para a IA: {e}", exc_info=True)
            return "Desculpe, tive um problema para processar sua solicitação. Vamos tentar de novo do começo. O que você gostaria?"
      
        # 5. Lógica de Ferramentas (Preservada e Corrigida) [cite: 202]
        while response.candidates[0].content.parts and response.candidates[0].content.parts[0].function_call:  # [cite: 204]
          
            function_call = response.candidates[0].content.parts[0].function_call  # [cite: 206]
            function_name = function_call.name  # [cite: 207]
            function_args = function_call.args
          
            logging.info(f"IA solicitou a ferramenta '{function_name}' com os argumentos: {dict(function_args)}")
           
            tool_map = {
                "listar_profissionais": listar_profissionais,
                "listar_servicos": listar_servicos,
                "calcular_horarios_disponiveis": calcular_horarios_disponiveis,
                "criar_agendamento": criar_agendamento,
                "cancelar_agendamento_por_telefone": cancelar_agendamento_por_telefone,
            }
           
            if function_name in tool_map:
                function_to_call = tool_map[function_name]
                kwargs = dict(function_args)
                kwargs['barbearia_id'] = barbearia_id
               
                if function_name == 'criar_agendamento':
                     kwargs['telefone_cliente'] = cliente_whatsapp
               
                tool_response = function_to_call(**kwargs)
               
                # (Sua sintaxe 'protos' preservada, como corrigimos antes)
                response = chat_session.send_message(  # [cite: 218]
                    protos.Part(
                        function_response=protos.FunctionResponse(
                            name=function_name,
                            response={"result": tool_response}
                        )
                    )
                )
            else:
                logging.error(f"Erro: IA tentou chamar uma ferramenta desconhecida: {function_name}")
                response = chat_session.send_message(
                    protos.Part(
                        function_response=protos.FunctionResponse(
                            name=function_name,
                            response={"error": "Ferramenta não encontrada."}
                        )
                    )
                )
       
        # 6. Salvar (SET) o novo histórico no cache [cite: 227]
        new_serialized_history = serialize_history(chat_session.history)  # [cite: 225]
        cache.set(cache_key, new_serialized_history)
       
        # 7. Retornar resposta final [cite: 229]
        final_response_text = response.candidates[0].content.parts[0].text
        logging.info(f"Resposta final da IA: {final_response_text}")
        return final_response_text
       
    except Exception as e:
        logging.error(f"Erro GRANDE ao processar com IA: {e}", exc_info=True)
        # (Não limpamos o histórico do cache aqui, pode ser um erro temporário)
        return "Desculpe, tive um problema para processar sua solicitação. Vamos tentar de novo do começo. O que você gostaria?"
# --- FIM DA IMPLEMENTAÇÃO ---
