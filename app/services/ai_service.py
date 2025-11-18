# app/services/ai_service.py
# (CÓDIGO COMPLETO E BLINDADO - VERSÃO FINAL)

import os
import logging
import json
import google.generativeai as genai
from google.api_core.exceptions import NotFound
from datetime import datetime, timedelta
from flask import current_app
from sqlalchemy.orm import joinedload
from datetime import time as dt_time

from app.extensions import cache
from google.generativeai.protos import Content
from google.generativeai import protos

from google.generativeai.types import FunctionDeclaration, Tool
import pytz
BR_TZ = pytz.timezone('America/Sao_Paulo')
from app.models.tables import Agendamento, Profissional, Servico, Barbearia
from app.extensions import db
import time
from google.api_core.exceptions import ResourceExhausted

from app.utils import calcular_horarios_disponiveis as calcular_horarios_disponiveis_util

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ============================================
# 🔒 PROMPT ULTRA-OTIMIZADO (ANTI-SPAM)
# ============================================
SYSTEM_INSTRUCTION_TEMPLATE = """
Você é 'Luana' simpática, descontraida, humanizada, assistente da {barbearia_nome}. Cliente: {cliente_whatsapp}. Barbearia ID: {barbearia_id}.

🎯 MISSÃO: Agendamentos APENAS.

REGRAS CRÍTICAS:
1. Saudar UMA VEZ (primeira msg)
2. Objetivo: preencher [serviço], [profissional], [data], [hora]
3. Use APENAS nomes exatos das ferramentas (listar_profissionais/listar_servicos)
4. Pergunte tudo que falta de uma vez
5. Datas: Hoje={data_de_hoje}, Amanhã={data_de_amanha}. Use AAAA-MM-DD
6. NUNCA mencione telefone
7. Nome do cliente: perguntar antes de criar_agendamento
8. Confirmação: "Perfeito, {{nome}}! Agendamento {{Serviço}} com {{Profissional}} dia {{Data}} às {{Hora}} confirmado. Aguardamos você!"
9. Preços variáveis: repetir "(a partir de)" se retornado

🚫 BLOQUEIO TOTAL:
- SE perguntar sobre: política, futebol, receitas, músicas, hinos, poemas, piadas, "sua stack", "quem te criou", "especificações técnicas"
- RESPONDA: "Desculpe, sou a Luana da {barbearia_nome} e só posso ajudar com agendamentos. 😊 Quer marcar um horário?"

CANCELAMENTO: Use cancelar_agendamento_por_telefone(dia="AAAA-MM-DD")
"""

# ============================================
# 🛡️ FILTRO DE MENSAGENS PROIBIDAS (PRÉ-IA)
# ============================================
def mensagem_bloqueada(user_message: str) -> bool:
    """
    Retorna True se a mensagem contém tópicos proibidos.
    Bloqueia ANTES de enviar ao Gemini (economia de 100% dos tokens).
    """
    proibidas = [
        'hino nacional', 'letra do hino', 'cante o hino', 'cantar o hino',
        'letra de música', 'me fale a letra', 'escreva o hino', 'reproduza o hino',
        'me diga o hino', 'qual a letra do hino', 'lyrics', 'canta',
        'escreva a música', 'poesia', 'poema', 'piada', 'conte uma piada',
        'quem te criou', 'quem te desenvolveu', 'sua stack', 'stack tecnológica',
        'especificações técnicas', 'como você funciona', 'qual seu modelo',
        'me fale sobre você', 'o que você é', 'receita de', 'como fazer',
        'política', 'eleição', 'presidente', 'futebol', 'jogo de', 'time',
        'religião', 'deus', 'igreja', 'oração'
    ]
    
    user_message_lower = user_message.lower()
    
    for palavra in proibidas:
        if palavra in user_message_lower:
            logging.warning(f"🚫 Mensagem BLOQUEADA (palavra proibida: '{palavra}'): {user_message[:50]}...")
            return True
    
    # Bloqueia mensagens muito longas (possível spam/ataque)
    if len(user_message) > 500:
        logging.warning(f"🚫 Mensagem BLOQUEADA (muito longa: {len(user_message)} chars)")
        return True
    
    return False

# ============================================
# Configuração do Gemini
# ============================================
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
if not GEMINI_API_KEY:
    logging.error("Chave da API do Gemini não encontrada!")
else:
    genai.configure(api_key=GEMINI_API_KEY)

# ============================================
# FUNÇÕES TOOLS (PRESERVADAS 100%)
# ============================================

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
    try:
        with current_app.app_context():
            profissional = Profissional.query.filter_by(
                barbearia_id=barbearia_id,
                nome=profissional_nome
            ).first()
            if not profissional:
                return "Profissional não encontrado. Por favor, verifique o nome."
           
            agora_br = datetime.now(BR_TZ)
           
            if dia.lower() == 'hoje':
                dia_dt = agora_br
            elif dia.lower() == 'amanhã':
                dia_dt = agora_br + timedelta(days=1)
            else:
                try:
                    dia_dt_naive = datetime.strptime(dia, '%Y-%m-%d')
                    dia_dt = BR_TZ.localize(dia_dt_naive)
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
    try:
        with current_app.app_context():
            profissional = Profissional.query.filter_by(barbearia_id=barbearia_id, nome=profissional_nome).first()
            if not profissional:
                return "Profissional não encontrado."
            servico = Servico.query.filter_by(barbearia_id=barbearia_id, nome=servico_nome).first()
            if not servico:
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

def cancelar_agendamento_por_telefone(barbearia_id: int, telefone_cliente: str, dia: str) -> str:
    logging.info(f"Iniciando cancelamento para cliente {telefone_cliente} no dia {dia} para barbearia {barbearia_id}")
    try:
        with current_app.app_context():
            try:
                dia_dt = datetime.strptime(dia, '%Y-%m-%d').date()
            except ValueError:
                return "Formato de data inválido. Por favor, forneça a data no formato AAAA-MM-DD."
            
            inicio_dia = datetime.combine(dia_dt, dt_time.min)
            fim_dia = datetime.combine(dia_dt, dt_time.max)
            
            agendamentos_para_cancelar = Agendamento.query.filter(
                Agendamento.barbearia_id == barbearia_id,
                Agendamento.telefone_cliente == telefone_cliente,
                Agendamento.data_hora >= inicio_dia,
                Agendamento.data_hora <= fim_dia
            ).all()
            
            if not agendamentos_para_cancelar:
                logging.warning(f"Nenhum agendamento encontrado para {telefone_cliente} no dia {dia}")
                return f"Não encontrei nenhum agendamento no seu nome (telefone: {telefone_cliente}) para o dia {dia_dt.strftime('%d/%m/%Y')}."
            
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

# ============================================
# DEFINIÇÃO DAS TOOLS
# ============================================
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

tools = Tool(
    function_declarations=[
        listar_profissionais_func,
        listar_servicos_func,
        calcular_horarios_disponiveis_func,
        criar_agendamento_func,
        cancelar_agendamento_func
    ]
)

# ============================================
# Inicialização do Modelo Gemini
# ============================================
model = None
try:
    model_name_to_use = 'gemini-2.5-flash'
    model = genai.GenerativeModel(model_name=model_name_to_use, tools=[tools])
    logging.info(f"✅ Modelo Gemini ('{model_name_to_use}') inicializado com SUCESSO!")
except NotFound as nf_error:
    logging.error(f"ERRO CRÍTICO: Modelo Gemini '{model_name_to_use}' não encontrado: {nf_error}", exc_info=True)
except Exception as e:
    logging.error(f"ERRO CRÍTICO GERAL ao inicializar o modelo Gemini: {e}", exc_info=True)

# ============================================
# 🔄 FUNÇÕES HELPER COM JANELA DESLIZANTE
# ============================================

def serialize_history(history: list[Content]) -> str:
    """
    Serializa histórico COM LIMITE DE 10 MENSAGENS (Janela Deslizante).
    Economia: mantém apenas o contexto recente relevante.
    """
    MAX_HISTORY = 10
    
    # ✅ JANELA DESLIZANTE: Mantém apenas últimas 10 mensagens
    if len(history) > MAX_HISTORY:
        history = history[-MAX_HISTORY:]
        logging.info(f"📊 Histórico cortado para {MAX_HISTORY} mensagens (economia de tokens)")
    
    serializable_list = []
    for content in history:
        serial_parts = []
        for part in content.parts:
            part_dict = {}
            if part.text:
                part_dict['text'] = part.text
            elif part.function_call:
                part_dict['function_call'] = protos.FunctionCall.to_dict(part.function_call)
            elif part.function_response:
                part_dict['function_response'] = protos.FunctionResponse.to_dict(part.function_response)
           
            if part_dict:
                serial_parts.append(part_dict)
       
        serializable_list.append({
            'role': content.role,
            'parts': serial_parts
        })
    return json.dumps(serializable_list)

def deserialize_history(json_string: str) -> list[Content]:
    history_list = []
    if not json_string:
        return history_list
    try:
        serializable_list = json.loads(json_string)
    except json.JSONDecodeError:
        logging.warning("Dados de cache de histórico inválidos ou corrompidos.")
        return history_list
    for item in serializable_list:
        deserial_parts = []
        for part_data in item.get('parts', []):
            if 'text' in part_data:
                deserial_parts.append(protos.Part(text=part_data['text']))
            elif 'function_call' in part_data:
                fc = protos.FunctionCall(part_data['function_call'])
                deserial_parts.append(protos.Part(function_call=fc))
            elif 'function_response' in part_data:
                fr = protos.FunctionResponse(part_data['function_response'])
                deserial_parts.append(protos.Part(function_response=fr))
       
        history_list.append(Content(role=item.get('role'), parts=deserial_parts))
    return history_list

# ============================================
# 🚀 FUNÇÃO PRINCIPAL (ULTRA-OTIMIZADA + BLINDADA)
# ============================================

def processar_ia_gemini(user_message: str, barbearia_id: int, cliente_whatsapp: str) -> str:
    """
    Versão ESTÁVEL para demonstração.
    Remove validação agressiva de histórico corrompido.
    """
    if not model:
        logging.error("Modelo Gemini não inicializado. Abortando.")
        return "Desculpe, meu cérebro (IA) está offline no momento. Tente novamente mais tarde."
   
    # ✅ FILTRO PRÉ-IA (MANTIDO)
    if mensagem_bloqueada(user_message):
        barbearia = Barbearia.query.get(barbearia_id)
        nome_barbearia = barbearia.nome_fantasia if barbearia else "nossa barbearia"
        return f"Desculpe, sou a Luana da {nome_barbearia} e só posso ajudar com agendamentos. 😊 Quer marcar um horário?"
    
    cache_key = f"chat_history_{cliente_whatsapp}:{barbearia_id}"
   
    try:
        barbearia = Barbearia.query.get(barbearia_id)
        if not barbearia:
            logging.error(f"Barbearia ID {barbearia_id} não encontrada no processar_ia_gemini.")
            return "Desculpe, não consegui identificar para qual barbearia você está ligando."
       
        logging.info(f"Carregando histórico do cache para a chave: {cache_key}")
        serialized_history = cache.get(cache_key)
        history_to_load = deserialize_history(serialized_history)
        
        if serialized_history:
            logging.info(f"✅ Histórico recuperado do Redis. Tamanho: {len(serialized_history)} chars")
        else:
            logging.warning("⚠️ Redis vazio - nova sessão iniciada")
       
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
       
        is_new_chat = not history_to_load
       
        if is_new_chat:
            logging.info(f"Iniciando NOVO histórico de chat para o cliente {cliente_whatsapp}.")
            history_to_load = [
                {'role': 'user', 'parts': [system_prompt]},
                {'role': 'model', 'parts': [
                    f"Olá! Bem-vindo(a) à {barbearia.nome_fantasia}! Como posso ajudar no seu agendamento?"
                ]}
            ]
        
        # ❌ REMOVIDO: Validação agressiva de histórico corrompido
        # (Estava causando falsos positivos e resetando conversas válidas)
        
        chat_session = model.start_chat(history=history_to_load)
       
        if is_new_chat and user_message.lower().strip() in ['oi', 'ola', 'olá', 'bom dia', 'boa tarde', 'boa noite']:
             new_serialized_history = serialize_history(chat_session.history)
             cache.set(cache_key, new_serialized_history)
             logging.info(f"✅ Histórico salvo no Redis. Tamanho: {len(new_serialized_history)} chars")
             return f"Olá! Bem-vindo(a) à {barbearia.nome_fantasia}! Como posso ajudar no seu agendamento?"
      
        logging.info(f"Enviando mensagem para a IA: {user_message}")
       
        historico_valido = False
        
        try:
            response = chat_session.send_message(user_message)
            historico_valido = True
            
        except ResourceExhausted as e:
            logging.warning(f"Quota do Gemini excedida: {e}")
            return "Puxa, parece que atingi meu limite de processamento por agora. 😕 Por favor, tente novamente em um minuto."
        except Exception as e:
            logging.error(f"Erro ao enviar mensagem para a IA: {e}", exc_info=True)
            # Limpa apenas em caso de erro REAL
            cache.delete(cache_key)
            logging.warning(f"🧹 Histórico limpo devido a erro. Próxima mensagem começará do zero.")
            return "Desculpe, tive um problema para processar sua solicitação. Vamos tentar de novo do começo. O que você gostaria?"
      
        # Loop de Ferramentas
        max_iterations = 10
        iteration = 0
        
        while (iteration < max_iterations and 
               response.candidates and 
               response.candidates[0].content.parts and 
               response.candidates[0].content.parts[0].function_call):
            
            iteration += 1
            function_call = response.candidates[0].content.parts[0].function_call
            function_name = function_call.name
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
               
                if function_name in ['criar_agendamento', 'cancelar_agendamento_por_telefone']:
                     kwargs['telefone_cliente'] = cliente_whatsapp
               
                tool_response = function_to_call(**kwargs)
                
                # ✅ LIMPEZA AUTOMÁTICA APÓS SUCESSO (MANTIDO)
                if "sucesso" in str(tool_response).lower() and function_name in ['criar_agendamento', 'cancelar_agendamento_por_telefone']:
                    logging.info("🧹 Agendamento/Cancelamento concluído. Limpando histórico para próxima conversa.")
                    cache.delete(cache_key)
                    historico_valido = False
               
                try:
                    response = chat_session.send_message(
                        protos.Part(
                            function_response=protos.FunctionResponse(
                                name=function_name,
                                response={"result": tool_response}
                            )
                        )
                    )
                except Exception as e:
                    logging.error(f"Erro ao enviar function_response: {e}", exc_info=True)
                    cache.delete(cache_key)
                    return "Desculpe, tive um problema ao processar a ferramenta. Vamos recomeçar."
            else:
                logging.error(f"Erro: IA tentou chamar uma ferramenta desconhecida: {function_name}")
                response = chat_session.send_message(
                    protos.Part(
                        function_response=protos.FunctionResponse(
                            function_name,
                            response={"error": "Ferramenta não encontrada."}
                        )
                    )
                )
        
        if iteration >= max_iterations:
            logging.error("⚠️ Loop infinito detectado! Abortando.")
            cache.delete(cache_key)
            return "Desculpe, tive um problema. Vamos recomeçar."
       
        # ✅ SALVA HISTÓRICO SE VÁLIDO
        if historico_valido:
            new_serialized_history = serialize_history(chat_session.history)
            cache.set(cache_key, new_serialized_history)
            logging.info(f"✅ Histórico salvo no Redis. Tamanho: {len(new_serialized_history)} chars")
       
        # Logging de tokens
        final_response_text = response.candidates[0].content.parts[0].text
        
        try:
            if hasattr(response, 'usage_metadata'):
                input_tokens = response.usage_metadata.prompt_token_count
                output_tokens = response.usage_metadata.candidates_token_count
                logging.info(f"💰 Tokens usados - Input: {input_tokens}, Output: {output_tokens}")
        except Exception:
            pass
        
        logging.info(f"Resposta final da IA: {final_response_text}")
        return final_response_text
       
    except Exception as e:
        logging.error(f"Erro GRANDE ao processar com IA: {e}", exc_info=True)
        try:
            cache.delete(cache_key)
            logging.info("🧹 Cache limpo após erro crítico")
        except:
            pass
        return "Desculpe, tive um problema para processar sua solicitação. Vamos tentar de novo do começo. O que você gostaria?"
      
        # Loop de Ferramentas
        max_iterations = 10
        iteration = 0
        
        while (iteration < max_iterations and 
               response.candidates and 
               response.candidates[0].content.parts and 
               response.candidates[0].content.parts[0].function_call):
            
            iteration += 1
            function_call = response.candidates[0].content.parts[0].function_call
            function_name = function_call.name
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
               
                if function_name in ['criar_agendamento', 'cancelar_agendamento_por_telefone']:
                     kwargs['telefone_cliente'] = cliente_whatsapp
               
                tool_response = function_to_call(**kwargs)
                
                # ✅ LIMPEZA AUTOMÁTICA APÓS SUCESSO
                if "sucesso" in str(tool_response).lower() and function_name in ['criar_agendamento', 'cancelar_agendamento_por_telefone']:
                    logging.info("🧹 Agendamento/Cancelamento concluído. Limpando histórico para próxima conversa.")
                    cache.delete(cache_key)
                    historico_valido = False
               
                try:
                    response = chat_session.send_message(
                        protos.Part(
                            function_response=protos.FunctionResponse(
                                name=function_name,
                                response={"result": tool_response}
                            )
                        )
                    )
                except Exception as e:
                    logging.error(f"Erro ao enviar function_response: {e}", exc_info=True)
                    cache.delete(cache_key)
                    return "Desculpe, tive um problema ao processar a ferramenta. Vamos recomeçar."
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
        
        if iteration >= max_iterations:
            logging.error("⚠️ Loop infinito detectado! Abortando.")
            cache.delete(cache_key)
            return "Desculpe, tive um problema. Vamos recomeçar."
       
        # ✅ SÓ SALVA HISTÓRICO SE NÃO HOUVE ERRO
        if historico_valido:
            new_serialized_history = serialize_history(chat_session.history)
            cache.set(cache_key, new_serialized_history)
            logging.info(f"✅ Histórico salvo no Redis. Tamanho: {len(new_serialized_history)} chars")
       
        # Logging de tokens
        final_response_text = response.candidates[0].content.parts[0].text
        
        try:
            if hasattr(response, 'usage_metadata'):
                input_tokens = response.usage_metadata.prompt_token_count
                output_tokens = response.usage_metadata.candidates_token_count
                logging.info(f"💰 Tokens usados - Input: {input_tokens}, Output: {output_tokens}")
        except Exception:
            pass
        
        logging.info(f"Resposta final da IA: {final_response_text}")
        return final_response_text
       
    except Exception as e:
        logging.error(f"Erro GRANDE ao processar com IA: {e}", exc_info=True)
        try:
            cache.delete(cache_key)
            logging.info("🧹 Cache limpo após erro crítico")
        except:
            pass
        return "Desculpe, tive um problema para processar sua solicitação. Vamos tentar de novo do começo. O que você gostaria?"

      
        # Loop de Ferramentas com proteção contra loop infinito
        max_iterations = 10  # Previne loop infinito
        iteration = 0
        
        while (iteration < max_iterations and 
               response.candidates and 
               response.candidates[0].content.parts and 
               response.candidates[0].content.parts[0].function_call):
            
            iteration += 1
            function_call = response.candidates[0].content.parts[0].function_call
            function_name = function_call.name
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
               
                if function_name in ['criar_agendamento', 'cancelar_agendamento_por_telefone']:
                     kwargs['telefone_cliente'] = cliente_whatsapp
               
                tool_response = function_to_call(**kwargs)
                
                # ✅ CAMADA 4: LIMPEZA AUTOMÁTICA APÓS SUCESSO
                if "sucesso" in str(tool_response).lower() and function_name in ['criar_agendamento', 'cancelar_agendamento_por_telefone']:
                    logging.info("🧹 Agendamento/Cancelamento concluído. Limpando histórico para próxima conversa.")
                    cache.delete(cache_key)
                    historico_valido = False  # Não salvar (já foi deletado)
               
                try:
                    response = chat_session.send_message(
                        protos.Part(
                            function_response=protos.FunctionResponse(
                                name=function_name,
                                response={"result": tool_response}
                            )
                        )
                    )
                except Exception as e:
                    logging.error(f"Erro ao enviar function_response: {e}", exc_info=True)
                    # ✅ LIMPA HISTÓRICO SE DEU ERRO NO LOOP
                    cache.delete(cache_key)
                    return "Desculpe, tive um problema ao processar a ferramenta. Vamos recomeçar."
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
        
        if iteration >= max_iterations:
            logging.error("⚠️ Loop infinito detectado! Abortando.")
            cache.delete(cache_key)
            return "Desculpe, tive um problema. Vamos recomeçar."
       
        # ✅ CAMADA 3: SÓ SALVA HISTÓRICO SE NÃO HOUVE ERRO
        if historico_valido:
            new_serialized_history = serialize_history(chat_session.history)
            cache.set(cache_key, new_serialized_history)
            logging.info(f"✅ Histórico salvo no Redis. Tamanho: {len(new_serialized_history)} chars")
       
        # Logging de tokens
        final_response_text = response.candidates[0].content.parts[0].text
        
        try:
            if hasattr(response, 'usage_metadata'):
                input_tokens = response.usage_metadata.prompt_token_count
                output_tokens = response.usage_metadata.candidates_token_count
                logging.info(f"💰 Tokens usados - Input: {input_tokens}, Output: {output_tokens}")
        except Exception:
            pass
        
        logging.info(f"Resposta final da IA: {final_response_text}")
        return final_response_text
       
    except Exception as e:
        logging.error(f"Erro GRANDE ao processar com IA: {e}", exc_info=True)
        # ✅ SEMPRE LIMPA CACHE EM CASO DE ERRO CRÍTICO
        try:
            cache.delete(cache_key)
            logging.info("🧹 Cache limpo após erro crítico")
        except:
            pass
        return "Desculpe, tive um problema para processar sua solicitação. Vamos tentar de novo do começo. O que você gostaria?"
