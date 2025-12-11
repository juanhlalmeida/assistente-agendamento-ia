# app/services/ai_service.py
# (CÓDIGO COMPLETO E OTIMIZADO - COM FUZZY MATCHING E PROTEÇÃO MALFORMED CALL)

import os
import logging
import json
import google.generativeai as genai
import re
from google.api_core.exceptions import NotFound, ResourceExhausted
# --- IMPORTAÇÃO NECESSÁRIA PARA CAPTURAR O ERRO MALFORMED ---
from google.generativeai.types import generation_types 
# ------------------------------------------------------------
from datetime import datetime, timedelta
from flask import current_app
from sqlalchemy.orm import joinedload
from datetime import time as dt_time

# --- INÍCIO DA IMPLEMENTAÇÃO (Conforme o PDF) ---
# Importa o cache das extensões
from app.extensions import cache 
# Importa os tipos de dados do Gemini para serialização
from google.generativeai.protos import Content 
# (Usamos 'protos' como no seu código original para FunctionCall/Response)
from google.generativeai import protos 
# --- FIM DA IMPLEMENTAÇÃO ---

# --- ALTERAÇÃO 1: Importar GenerationConfig para controlar a temperatura ---
from google.generativeai.types import FunctionDeclaration, Tool, GenerationConfig
import pytz
BR_TZ = pytz.timezone('America/Sao_Paulo') 
from app.models.tables import Agendamento, Profissional, Servico, Barbearia 
from app.extensions import db
import time 

from app.utils import calcular_horarios_disponiveis as calcular_horarios_disponiveis_util

# --- NOVA IMPLEMENTAÇÃO: BIBLIOTECA DE COMPARAÇÃO DE TEXTO (PLANO B) ---
from thefuzz import process 
# -------------------------------------------------------------

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- PROMPT OTIMIZADO (COM INTELIGÊNCIA DE TRADUÇÃO E REGRAS UNIFICADAS) ---
SYSTEM_INSTRUCTION_TEMPLATE = """
PERSONA: Luana, assistente da {barbearia_nome}.
OBJETIVO: Agendamentos. Foco 100%.
TOM: Simpática, breve, objetiva, descontraida, emojis (✂️✨😉👍).
ID_CLIENTE: {cliente_whatsapp} | BARBEARIA_ID: {barbearia_id}
HOJE: {data_de_hoje} | AMANHÃ: {data_de_amanha}

🚨 REGRA DE OURO - INTEGRIDADE DO SISTEMA (LEIA COM ATENÇÃO):
VOCÊ É PROIBIDA DE DIZER "AGENDADO" OU "CONFIRMADO" SE NÃO TIVER CHAMADO A FERRAMENTA `criar_agendamento` COM SUCESSO.
- Se você apenas falar "Ok, marquei", você está MENTINDO para o cliente, pois nada foi salvo no sistema.
- PARA AGENDAR DE VERDADE: Você TEM QUE executar a tool `criar_agendamento`.
- Se a ferramenta der erro, avise o cliente. Se der sucesso, aí sim confirme.

🚨 PROTOCOLO DE SEGURANÇA & ANTI-ALUCINAÇÃO (PRIORIDADE MÁXIMA):
1. RECUSA DE TÓPICOS: Se o usuário pedir QUALQUER COISA que não seja agendamento (ex: hino, piada, receita, política, futebol, tecnologia, letra de música), você DEVE recusar imediatamente:
   "Desculpe, eu sou a Luana da {barbearia_nome} e só cuido dos agendamentos. 😊 Quer marcar um horário?"
   NÃO cante, NÃO explique, NÃO dê opiniões. Apenas recuse.
2. REALIDADE DOS HORÁRIOS: Você está PROIBIDA de inventar horários. Se a ferramenta 'calcular_horarios_disponiveis' retornar vazio ou "Nenhum horário", diga ao cliente que não há vagas. NUNCA suponha que há um horário livre sem confirmação da ferramenta.

🧠 INTELIGÊNCIA DE SERVIÇOS (TRADUÇÃO):
   O banco de dados exige nomes exatos, mas o cliente fala de forma natural.
   SEU DEVER É TRADUZIR O PEDIDO PARA O NOME OFICIAL:
   - O cliente disse "fazer a barba"? -> Chame `listar_servicos`. Se existir "Barba Terapia" ou "Barba Completa", USE ESSE NOME na ferramenta `criar_agendamento`. Não trave por detalhes.
   - O cliente disse "cortar o cabelo"? -> Associe ao "Corte Social" ou similar que estiver na lista.
   - Dúvida real (ex: existe "Corte Social" E "Corte Navalhado")? -> Aí sim, pergunte a preferência.

REGRAS DE EXECUÇÃO (ACTION-ORIENTED):
1. NÃO ENROLE: Se o cliente mandou áudio com [Serviço, Dia, Hora], chame as ferramentas IMEDIATAMENTE.
2. Falta o Profissional? -> Pergunte "Tem preferência por barbeiro?" ou assuma "Qualquer um" se ele disser que tanto faz.
3. CONFIRMAÇÃO: "Agendamento confirmado!" somente após a ferramenta retornar sucesso.

REGRAS:
1. Saudar UMA VEZ (primeira msg)
2. Objetivo: preencher [serviço], [profissional], [data], [hora]
3. Use APENAS nomes exatos das ferramentas (listar_profissionais/listar_servicos)
   3.1. IMPORTANTE: Se for listar ou perguntar sobre profissionais, VOCÊ DEVE CHAMAR A FERRAMENTA `listar_profissionais` ANTES de responder. Não deixe a lista vazia.
4. Pergunte tudo que falta de uma vez
5. Datas: Hoje={data_de_hoje}, Amanhã={data_de_amanha}. Use AAAA-MM-DD
6. NUNCA mencione telefone
7. Nome do cliente: perguntar antes de criar_agendamento
8. Confirmação: "Perfeito, {{nome}}! Agendamento {{Serviço}} com {{Profissional}} dia {{Data}} às {{Hora}} confirmado. Aguardamos você!"
9. Preços variáveis: repetir "(a partir de)" se retornado
CANCELAMENTO: Use cancelar_agendamento_por_telefone(dia="AAAA-MM-DD")
"""
# ---------------------------------------

# ============================================
# 🧠 FUNÇÃO AUXILIAR DO PLANO B (FUZZY MATCH)
# ============================================
def encontrar_melhor_match(termo_busca, lista_opcoes, cutoff=60):
    """
    Procura o item mais parecido na lista.
    Ex: termo="barba" -> lista=["Corte", "Barba Terapia"] -> Retorna "Barba Terapia"
    cutoff=60 significa que precisa ter pelo menos 60% de semelhança.
    """
    if not termo_busca or not lista_opcoes:
        return None
    
    # Retorna (melhor_match, score)
    melhor, score = process.extractOne(termo_busca, lista_opcoes)
    
    if score >= cutoff:
        logging.info(f"🔍 Fuzzy Match: '{termo_busca}' identificado como '{melhor}' (Score: {score})")
        return melhor
    
    logging.warning(f"⚠️ Fuzzy Match falhou para '{termo_busca}'. Melhor: '{melhor}' (Score: {score} < {cutoff})")
    return None

# ==============================================================================
# 2. FILTRO DE SPAM (PRESERVADO)
# ==============================================================================
# ============================================
# 🛡️ FILTRO DE MENSAGENS PROIBIDAS (MELHORADO)
# ============================================
def mensagem_bloqueada(texto: str) -> bool:
    """
    Retorna True se a mensagem for spam ou assunto proibido.
    Usa lógica mais robusta para apanhar variações.
    """
    texto_lower = texto.lower()
    
    # Bloqueia textos muito longos (custo alto de processamento)
    if len(texto) > 300: 
        logging.warning(f"🚫 Mensagem BLOQUEADA (muito longa: {len(texto)} chars)")
        return True

    # Palavras-chave simples (alta precisão)
    proibidas_exatas = [
        'chatgpt', 'openai', 'ignore as instruções', 'mode debug', 
        'sua stack', 'código fonte', 'quem te criou', 'quem te desenvolveu'
    ]
    for p in proibidas_exatas:
        if p in texto_lower:
            return True

    # Padrões Regex (para apanhar "hino naciional", "futebow", etc.)
    # \b = fronteira da palavra, .? = erro de digitação opcional
    padroes_proibidos = [
        r'hino.*nacion',     # Pega "hino nacional", "hino naciional", "hino da nação"
        r'canta.*hino',      # Pega "cantar o hino", "canta hino"
        r'letra.*m[uú]sica', # Pega "letra de musica", "letra da música"
        r'futebo',           # Pega "futebol", "futebool"
        r'pol[íi]tica',      # Pega "política", "politica"
        r'receita.*de',      # Pega "receita de bolo"
        r'piada',
        r'poema',
    ]

    for padrao in padroes_proibidos:
        if re.search(padrao, texto_lower):
            logging.warning(f"🚫 Mensagem BLOQUEADA (padrão proibido: '{padrao}'): {texto[:50]}...")
            return True
            
    return False

# Configuração do Gemini (Preservado)
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
if not GEMINI_API_KEY:
    logging.error("Chave da API do Gemini não encontrada!")
else:
    genai.configure(api_key=GEMINI_API_KEY)

# ---------------------------------------------------------------------
# FUNÇÕES TOOLS (MODIFICADAS COM FUZZY MATCH)
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
    try:
        with current_app.app_context():
            # --- PLANO B: BUSCA INTELIGENTE DE PROFISSIONAL ---
            todos_profs = Profissional.query.filter_by(barbearia_id=barbearia_id).all()
            nomes_profs = [p.nome for p in todos_profs]
            
            nome_correto = encontrar_melhor_match(profissional_nome, nomes_profs)
            
            if not nome_correto:
                return f"Profissional '{profissional_nome}' não encontrado. Opções: {', '.join(nomes_profs)}."
            
            profissional = next((p for p in todos_profs if p.nome == nome_correto), None)
            # --------------------------------------------------
           
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
            return f"Horários disponíveis para {nome_correto} em {dia_formatado}: {', '.join(horarios_str_list) or 'Nenhum horário encontrado.'}"
    except Exception as e:
        current_app.logger.error(f"Erro no wrapper 'calcular_horarios_disponiveis': {e}", exc_info=True)
        return "Desculpe, ocorreu um erro ao verificar os horários."

def criar_agendamento(barbearia_id: int, nome_cliente: str, telefone_cliente: str, data_hora: str, profissional_nome: str, servico_nome: str) -> str:
    try:
        with current_app.app_context():
            # --- PLANO B: BUSCA INTELIGENTE DE PROFISSIONAL ---
            todos_profs = Profissional.query.filter_by(barbearia_id=barbearia_id).all()
            nome_prof_match = encontrar_melhor_match(profissional_nome, [p.nome for p in todos_profs])
            
            if not nome_prof_match:
                return f"Profissional '{profissional_nome}' não encontrado."
            
            profissional = next(p for p in todos_profs if p.nome == nome_prof_match)
            
            # --- PLANO B: BUSCA INTELIGENTE DE SERVIÇO ---
            todos_servicos = Servico.query.filter_by(barbearia_id=barbearia_id).all()
            nome_serv_match = encontrar_melhor_match(servico_nome, [s.nome for s in todos_servicos])
            
            if not nome_serv_match:
                logging.warning(f"Tentativa de agendar serviço inexistente: '{servico_nome}'")
                return f"Serviço '{servico_nome}' não encontrado. Por favor, confirme o nome do serviço na lista: {', '.join([s.nome for s in todos_servicos])}."
            
            servico = next(s for s in todos_servicos if s.nome == nome_serv_match)
            # ---------------------------------------------
               
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
            return f"Agendamento criado com sucesso para {nome_cliente} em {data_hora_formatada} com {profissional.nome} para {servico.nome}."
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Erro na ferramenta 'criar_agendamento': {e}", exc_info=True)
        return f"Erro ao criar agendamento: {str(e)}" 

def cancelar_agendamento_por_telefone(barbearia_id: int, telefone_cliente: str, dia: str) -> str:
    """
    Cancela TODOS os agendamentos de um cliente (telefone) para um dia específico.
    """
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

# --- Inicialização do Modelo Gemini (OTIMIZADO PARA FLASH) ---
model = None 
try:
    # ✅ MUDANÇA 1: Trocado para Flash (94% economia)
    model_name_to_use = 'gemini-2.5-flash'  # Era: 'models/gemini-pro-latest'
    
    # --- ALTERAÇÃO 2: IMPLEMENTAÇÃO DO ESTUDO (Temperature 0 para evitar alucinação) ---
    generation_config = GenerationConfig(
        temperature=0.0,  # Zero criatividade para seguir as tools estritamente
        top_p=0.95,
        top_k=40,
        max_output_tokens=1024,
    )
    
    model = genai.GenerativeModel(
        model_name=model_name_to_use, 
        tools=[tools],
        generation_config=generation_config # Aplicando a config
    )
    
    logging.info(f"✅ Modelo Gemini ('{model_name_to_use}') inicializado com SUCESSO!")
except NotFound as nf_error:
    logging.error(f"ERRO CRÍTICO: Modelo Gemini '{model_name_to_use}' não encontrado: {nf_error}", exc_info=True)
except Exception as e:
    logging.error(f"ERRO CRÍTICO GERAL ao inicializar o modelo Gemini: {e}", exc_info=True)

# --- FUNÇÕES HELPER DE SERIALIZAÇÃO ---
def serialize_history(history: list[Content]) -> str:
    """
    Serializa o histórico de chat (lista de objetos Content) para uma string JSON.
    Lida com texto, FunctionCall (protos) e FunctionResponse (protos).
    """
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
    """
    Deserializa uma string JSON de volta para uma lista de objetos Content.
    Recria texto, FunctionCall (protos) e FunctionResponse (protos).
    """
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

# --- FUNÇÃO PRINCIPAL DE PROCESSAMENTO (Refatorada para Cache) ---
def processar_ia_gemini(user_message: str, barbearia_id: int, cliente_whatsapp: str) -> str:
    """
    Processa a mensagem do usuário usando o Gemini, mantendo o histórico
    da conversa no cache (Redis) associado ao número do cliente.
    """
    if not model:
        logging.error("Modelo Gemini não inicializado. Abortando.")
        return "Desculpe, meu cérebro (IA) está offline no momento. Tente novamente mais tarde."
   
    cache_key = f"chat_history_{cliente_whatsapp}:{barbearia_id}"
   
    try:
        barbearia = Barbearia.query.get(barbearia_id)
        if not barbearia:
            logging.error(f"Barbearia ID {barbearia_id} não encontrada no processar_ia_gemini.")
            return "Desculpe, não consegui identificar para qual barbearia você está ligando."
       
        # Carregar histórico do cache
        logging.info(f"Carregando histórico do cache para a chave: {cache_key}")
        serialized_history = cache.get(cache_key)
        history_to_load = deserialize_history(serialized_history)
       
        # ✅ MUDANÇA 3: Logging para monitorar Redis
        if serialized_history:
            logging.info(f"✅ Histórico recuperado do Redis. Tamanho: {len(serialized_history)} chars")
        else:
            logging.warning("⚠️ Redis vazio - nova sessão iniciada")
       
        agora_br = datetime.now(BR_TZ)
        data_hoje_str = agora_br.strftime('%Y-%m-%d')
        data_amanha_str = (agora_br + timedelta(days=1)).strftime('%Y-%m-%d')
       
        # --- IMPLEMENTAÇÃO DE EMOJIS (Lógica para Personalizar) ---
        # Tenta pegar do banco, se não tiver ou der erro, usa padrão
        emojis = getattr(barbearia, 'emojis_sistema', '✂️✨😉👍') or '✂️✨😉👍'
        # ---------------------------------------------------------

        system_prompt = SYSTEM_INSTRUCTION_TEMPLATE.format(
            barbearia_nome=barbearia.nome_fantasia,
            cliente_whatsapp=cliente_whatsapp,
            barbearia_id=barbearia_id,
            data_de_hoje=data_hoje_str,
            data_de_amanha=data_amanha_str
        )
        
        # --- INJEÇÃO DOS EMOJIS NO PROMPT ---
        system_prompt += f"\n\nIMPORTANTE: USE SEMPRE ESTES EMOJIS: {emojis}"
        # -----------------------------------
       
        is_new_chat = not history_to_load
       
        if is_new_chat:
            logging.info(f"Iniciando NOVO histórico de chat para o cliente {cliente_whatsapp}.")
            history_to_load = [
                {'role': 'user', 'parts': [system_prompt]},
                {'role': 'model', 'parts': [
                    f"Olá! Bem-vindo(a) à {barbearia.nome_fantasia}! Como posso ajudar no seu agendamento?"
                ]}
            ]
       
        chat_session = model.start_chat(history=history_to_load)
       
        if is_new_chat and user_message.lower().strip() in ['oi', 'ola', 'olá', 'bom dia', 'boa tarde', 'boa noite']:
             new_serialized_history = serialize_history(chat_session.history)
             cache.set(cache_key, new_serialized_history)
             logging.info(f"✅ Histórico salvo no Redis. Tamanho: {len(new_serialized_history)} chars")
             return f"Olá! Bem-vindo(a) à {barbearia.nome_fantasia}! Como posso ajudar no seu agendamento?"
      
        logging.info(f"Enviando mensagem para a IA: {user_message}")
       
        # --- PROTEÇÃO CONTRA ERRO MALFORMED (Tente enviar, capture se der erro) ---
        try:
            response = chat_session.send_message(user_message)
        except generation_types.StopCandidateException as e:
            logging.error(f"Erro Malformed Call: {e}")
            # Tenta recuperar pedindo para a IA repetir sem chamar função ou de forma mais simples
            return "Desculpe, tive um problema técnico ao processar seu pedido. Pode repetir por favor?"
        except Exception as e:
            # Outros erros (ex: ResourceExhausted, etc.)
            logging.error(f"Erro ao enviar mensagem para a IA: {e}", exc_info=True)
            return "Desculpe, tive um problema para processar sua solicitação. Vamos tentar de novo do começo. O que você gostaria?"
        # ------------------------------------------------------
      
        # Lógica de Ferramentas
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
                "cancelar_agendamento_por_telefone": cancelar_agendamento_por_telefone,
            }
           
            if function_name in tool_map:
                function_to_call = tool_map[function_name]
                kwargs = dict(function_args)
                kwargs['barbearia_id'] = barbearia_id
               
                if function_name in ['criar_agendamento', 'cancelar_agendamento_por_telefone']:
                     kwargs['telefone_cliente'] = cliente_whatsapp
               
                tool_response = function_to_call(**kwargs)
               
                # --- PROTEÇÃO NO RETORNO DA TOOL TAMBÉM ---
                try:
                    response = chat_session.send_message(
                        protos.Part(
                            function_response=protos.FunctionResponse(
                                name=function_name,
                                response={"result": tool_response}
                            )
                        )
                    )
                except generation_types.StopCandidateException:
                    logging.error("Erro Malformed Call no retorno da tool")
                    return "Tive um erro ao confirmar o agendamento. Por favor, tente novamente."
                # -------------------------------------------
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
       
        # Salvar histórico no cache
        new_serialized_history = serialize_history(chat_session.history)
        cache.set(cache_key, new_serialized_history)
        logging.info(f"✅ Histórico salvo no Redis. Tamanho: {len(new_serialized_history)} chars")
       
        # ✅ MUDANÇA 4: Logging de uso de tokens E CORREÇÃO DO INDEX ERROR
        final_response_text = "Desculpe, não entendi. Pode repetir?"
        
        if response.candidates and response.candidates[0].content.parts:
            # Tenta pegar o texto da primeira parte
            part = response.candidates[0].content.parts[0]
            if part.text:
                final_response_text = part.text
            else:
                # Se não tiver texto (caso raro onde só chamou função e parou),
                # força uma resposta padrão ou tenta pegar da próxima parte
                logging.warning("IA retornou conteúdo sem texto (provavelmente apenas FunctionCall).")
                # Tenta rodar mais uma vez se ficou mudo
                try:
                    response = chat_session.send_message("Responda ao usuário com base no que você acabou de processar.")
                    if response.candidates and response.candidates[0].content.parts:
                         final_response_text = response.candidates[0].content.parts[0].text
                except:
                    final_response_text = "Aqui estão as informações solicitadas."

        # Monitoramento de tokens (se disponível)
        try:
            if hasattr(response, 'usage_metadata'):
                input_tokens = response.usage_metadata.prompt_token_count
                output_tokens = response.usage_metadata.candidates_token_count
                logging.info(f"💰 Tokens usados - Input: {input_tokens}, Output: {output_tokens}")
        except Exception:
            pass  # Ignore se não houver metadata de uso
        
        logging.info(f"Resposta final da IA: {final_response_text}")
        return final_response_text
       
    except Exception as e:
        logging.error(f"Erro GRANDE ao processar com IA: {e}", exc_info=True)
        return "Desculpe, tive um problema para processar sua solicitação. Vamos tentar de novo do começo. O que você gostaria?"
