# app/services/ai_service.py
# (CÓDIGO COMPLETO E OTIMIZADO - VERSÃO SENIOR COM CONTEXTO DE SERVIÇO)
# ✅ IMPLEMENTAÇÃO DO DETECTOR DE GHOST CALL (Baseado em Paper Acadêmico 2026)
# ✅ AJUSTADO: CORREÇÃO DE ORDEM DE DECLARAÇÃO E DETECÇÃO DE BLOQUEIO

import os
import logging
import json
import google.generativeai as genai
import re
import urllib.parse
from app.utils.plugin_loader import carregar_plugin_negocio
from flask import url_for
from google.generativeai.types import HarmCategory, HarmBlockThreshold

from google.api_core.exceptions import NotFound, ResourceExhausted
from google.generativeai.types import generation_types
from datetime import datetime, timedelta
from flask import current_app
from sqlalchemy.orm import joinedload
from datetime import time as dt_time
from app.extensions import cache
from google.generativeai.protos import Content
from google.generativeai import protos
from google.generativeai.types import FunctionDeclaration, Tool, GenerationConfig
import pytz

BR_TZ = pytz.timezone('America/Sao_Paulo')

from app.models.tables import Agendamento, Profissional, Servico, Barbearia
from app.extensions import db
import time
from app.utils import calcular_horarios_disponiveis as calcular_horarios_disponiveis_util
from thefuzz import process
# Importando da pasta 'google'
from app.google.calendar_hooks import trigger_google_calendar_sync, CalendarAction


logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def gerar_link_google_calendar(inicio: datetime, fim: datetime, titulo: str, descricao: str, local: str):
    """
    Gera um link clicável que abre a agenda do Google do cliente já preenchida.
    """
    fmt = '%Y%m%dT%H%M%S'
    datas = f"{inicio.strftime(fmt)}/{fim.strftime(fmt)}"
    
    base_url = "https://www.google.com/calendar/render?action=TEMPLATE"
    params = {
        'text': titulo,
        'dates': datas,
        'details': descricao,
        'location': local,
        'sf': 'true',
        'output': 'xml'
    }
    return f"{base_url}&{urllib.parse.urlencode(params)}"

# ==============================================================================
# ⭐ FUNÇÃO DE DETECÇÃO DE GHOST CALL (PAPER ACADÊMICO 2026 - SEÇÃO 5.3.1)
# ==============================================================================

def detectar_ghost_call(resposta_final: str, historico_chat) -> tuple:
    """
    Detecta se IA confirmou agendamento OU bloqueio SEM executar a ferramenta.
    
    Baseado em: "Análise de Falhas de Orquestração e Alucinação de Execução 
    em Agentes de IA" (2026) - Seção 3.4 e 5.3.1
    
    O problema: Modelos geram confirmações falsas ANTES do sistema executar
    a função real, causando "Ghost Tool Calling".
    
    Returns: (é_ghost: bool, resposta_corrigida: str)
    """
    import re
    
    # Padrões que IA usa para confirmar (mas pode ser falso)
    confirmacoes = [
        r'agendamento\s+confirmado',
        r'agendado\s+com\s+sucesso',
        r'marcado\s+para',
        r'está\s+agendado',
        r'confirmei\s+(?:o|seu)\s+agendamento',
        r'✅.*agendamento',
        r'perfeito.*agendamento',
        r'agendamento\s+realizado',
        # Padrões de bloqueio (Novos)
        r'agenda\s+bloqueada',
        r'bloqueio\s+realizado',
        r'horário.*fechado',
        r'bloqueei\s+a\s+agenda'
    ]
    
    # Verificar se IA disse que agendou ou bloqueou
    ia_confirmou = any(re.search(p, resposta_final.lower()) for p in confirmacoes)
    
    if not ia_confirmou:
        return False, resposta_final
    
    # ✅ VERIFICAR SE TOOL 'criar_agendamento' OU 'bloquear_agenda_dono' FOI CHAMADA
    tool_executada = False
    
    try:
        for content in historico_chat:
            for part in content.parts:
                if hasattr(part, 'function_response') and part.function_response:
                    # Verifica se foi agendamento OU bloqueio
                    if part.function_response.name in ['criar_agendamento', 'bloquear_agenda_dono']:
                        response_dict = dict(part.function_response.response)
                        result = response_dict.get('result', '')
                        # Verifica sucesso na resposta da tool (ambas retornam 'sucesso' ou texto positivo)
                        if any(x in str(result).lower() for x in ['sucesso', 'criado', 'bloqueada', 'concluído']):
                            tool_executada = True
                            logging.info(f"✅ Ferramenta '{part.function_response.name}' foi executada com SUCESSO")
                        else:
                            logging.warning(f"⚠️ Ferramenta '{part.function_response.name}' retornou erro/aviso: {result[:100]}")
    except Exception as e:
        logging.error(f"Erro ao verificar histórico de ghost call: {e}")
    
    # 🚨 GHOST CALL DETECTADO
    if ia_confirmou and not tool_executada:
        logging.error(f"🚨 GHOST CALL DETECTADO: IA disse 'confirmado/bloqueado' mas ferramenta NÃO foi executada!")
        
        resposta_segura = (
            "⚠️ Ops! Detectei um problema de sincronização. "
            "Por favor, verifique se a ação foi concluída ou me envie os dados novamente "
            "(data, horário e ação) para eu confirmar no sistema."
        )
        
        return True, resposta_segura
    
    return False, resposta_final

# ==============================================================================
# 🧠 PROMPT 1: MODO CLIENTE (Versão Otimizada - Sem Alucinação de Serviços)
# ==============================================================================

SYSTEM_INSTRUCTION_CLIENTE = """

{header_persona}

OBJETIVO: Agendamentos. Foco 100%.
ID_CLIENTE: {cliente_whatsapp} | ID_LOJA: {barbearia_id}
HOJE: {data_de_hoje} | AMANHÃ: {data_de_amanha}

🚨 REGRA DO PROFISSIONAL (IMPORTANTE):
{regra_profissional_dinamica}

🚨 PROTOCOLO DE EXECUÇÃO IMEDIATA (REGRA SUPREMA):
ASSIM QUE O CLIENTE DER O "OK" OU CONFIRMAR O HORÁRIO E VOCÊ TIVER OS 5 DADOS (Serviço, Profissional, Data, Hora, Nome):

1. 🛑 PARE DE FALAR.
2. 🤐 NÃO DIGA "Vou agendar" ou "Estou confirmando".
3. ⚡ CHAME A FERRAMENTA `criar_agendamento` IMEDIATAMENTE.
- O agendamento SÓ EXISTE se a ferramenta for chamada. Se você apenas digitar texto confirmando, VOCÊ ESTÁ MENTINDO e falhando na tarefa.

🚨 REGRA DE OURO - INTEGRIDADE DO SISTEMA (LEIA COM ATENÇÃO):
VOCÊ É PROIBIDA DE DIZER "AGENDADO" OU "CONFIRMADO" SE NÃO TIVER CHAMADO A FERRAMENTA `criar_agendamento` COM SUCESSO.

- EXTREMAMANTE IMPORTANTE - PARA AGENDAR DE VERDADE: Você TEM QUE executar a tool `criar_agendamento`.
- Se você apenas falar "Ok, marquei", você está MENTINDO para o cliente, pois nada foi salvo no sistema.
- PARA AGENDAR DE VERDADE: Você TEM QUE executar a tool `criar_agendamento`.
- Se a ferramenta der erro, avise o cliente. Se der sucesso, aí sim confirme.

🚨 REGRA DE DISPONIBILIDADE & PROATIVIDADE (NOVO):

Se a ferramenta `calcular_horarios_disponiveis` retornar que NÃO há vagas no horário que o cliente pediu:

1. NÃO PERGUNTE "Quer ver outro horário?" (Isso irrita o cliente).
2. SEJA PROATIVA: Diga "Não tenho às Xh, mas tenho livre às Yh e Zh. Algum desses serve?".
3. Liste imediatamente as opções que a ferramenta retornou.
4. Se a ferramenta disser "Sem horários hoje", ofereça horários de AMANHÃ.

🚨 PROTOCOLO DE SEGURANÇA & ANTI-ALUCINAÇÃO (PRIORIDADE MÁXIMA):

1. RECUSA DE TÓPICOS: Se o usuário pedir QUALQUER COISA que não seja agendamento (ex: hino, piada, receita, política, futebol, tecnologia, letra de música), você DEVE recusar imediatamente:

"Desculpe, eu sou a assistente virtual e só cuido dos agendamentos. 😊 Quer marcar um horário?"
NÃO cante, NÃO explique, NÃO dê opiniões. Apenas recuse.
2. REALIDADE DOS HORÁRIOS: Você está PROIBIDA de inventar horários. Se a ferramenta 'calcular_horarios_disponiveis' retornar vazio ou "Nenhum horário", diga ao cliente que não há vagas. NUNCA suponha que há um horário livre sem confirmação da ferramenta.

🎁 TABELA DE PREÇOS / FOTOS (REGRA ABSOLUTA):

Se o cliente perguntar sobre "preços", "valores", "tabela", "quanto custa", "serviços", "cardápio", "foto" ou "imagem":
VOCÊ ESTÁ PROIBIDA DE DIGITAR A LISTA DE PREÇOS EM TEXTO.
Ao invés disso, envie a tag [ENVIAR_TABELA] no final da sua resposta.
Adapte a frase anterior à sua persona (seja educada ou brother), mas OBRIGATORIAMENTE use a tag.

Exemplos de resposta correta:
- Lash: "Com certeza amiga! Aqui está a tabela: [ENVIAR_TABELA]"
- Barbearia: "Tá na mão campeão, confira os valores: [ENVIAR_TABELA]"

Gostaria de agendar algum desses serviços?

🧠 INTELIGÊNCIA DE SERVIÇOS (TRADUÇÃO E VERIFICAÇÃO):
O banco de dados exige nomes exatos, mas o cliente fala de forma natural.

SEU DEVER É TRADUZIR O PEDIDO PARA O NOME OFICIAL, MAS APENAS SE ELE EXISTIR NA FERRAMENTA `listar_servicos`.

- Cliente pediu "barba"? -> Associe a "Barba Terapia" ou "Barba Simples" (SE HOUVER).
- Cliente pediu "cílios"? -> Associe a "Volume Brasileiro" ou "Fio a Fio" (SE HOUVER).
- Cliente pediu "sobrancelha"? -> VERIFIQUE SE EXISTE O SERVIÇO NA LISTA.
  -> SE EXISTIR: Associe ao nome correto (ex: Design).
  -> SE NÃO EXISTIR: DIGA QUE A LOJA NÃO OFERECE ESSE SERVIÇO. NÃO INVENTE.

REGRAS DE EXECUÇÃO (ACTION-ORIENTED):

1. NÃO ENROLE: Se o cliente mandou áudio com [Serviço, Dia, Hora], chame as ferramentas IMEDIATAMENTE.
2. Falta o Profissional? -> Pergunte a preferência ou assuma "Qualquer um" se ele disser que tanto faz.
3. CONFIRMAÇÃO: "Agendamento confirmado!" somente após a ferramenta retornar sucesso.

REGRAS GERAIS:
1. Saudar UMA VEZ (primeira msg)
2. Objetivo: preencher [serviço], [profissional], [data], [hora]
3. Use APENAS nomes exatos das ferramentas (listar_profissionais/listar_servicos)
3.1. IMPORTANTE: Se for listar ou perguntar sobre profissionais, VOCÊ DEVE CHAMAR A FERRAMENTA `listar_profissionais` ANTES de responder. Não deixe a lista vazia.
4. Pergunte tudo que falta de uma vez
IMPORTANTE: Ao verificar horários, SE O CLIENTE JÁ FALOU O NOME DO SERVIÇO, envie o parametro 'servico_nome' na ferramenta para garantir a duração correta.
5. Datas: Hoje={data_de_hoje}, Amanhã={data_de_amanha}. Use AAAA-MM-DD
6. NUNCA mencione telefone
7. Nome do cliente: perguntar antes de criar_agendamento
8. Confirmação: Use quebras de linha e negrito para destacar os dados. Siga EXATAMENTE este formato visual:

"Perfeito, *{{nome}}*! ✅
*Agendamento Confirmado:*
🗓 *Data:* {{Data}}
⏰ *Horário:* {{Hora}}
👤 *Profissional:* {{Profissional}}
✨ *Serviço:* {{Serviço}}
Aguardamos você!"

9. Preços variáveis: repetir "(a partir de)" se retornado
CANCELAMENTO: Use cancelar_agendamento_por_telefone(dia="AAAA-MM-DD")

"""
# ==============================================================================
# 👩💼 PROMPT 2: MODO SECRETÁRIA (ATUALIZADO PARA FINANCEIRO SOB DEMANDA)
# ==============================================================================

SYSTEM_INSTRUCTION_SECRETARIA = """

VOCÊ É A SECRETÁRIA PESSOAL DO(A) DONO(A) DA LOJA.
Quem está falando com você AGORA é o(a) PROPRIETÁRIO(A) (Boss).
SEU OBJETIVO: Gerenciar a agenda e bloquear horários.

HOJE: {data_de_hoje}
COMO AGIR (REGRA DE AÇÃO IMEDIATA):

1. SE O CHEFE PEDIR "AGENDA", "RESUMO" OU "QUEM VEM HOJE":
   - ⚡ NÃO FALE "Vou verificar".
   - ⚡ CHAME A TOOL `consultar_agenda_dono` IMEDIATAMENTE.
   - Mostre a lista retornada pela ferramenta.

2. SE O CHEFE PEDIR "BLOQUEAR", "FECHAR", "VOU AO MÉDICO":
   - Pergunte data e hora (se faltar).
   - ⚡ CHAME A TOOL `bloquear_agenda_dono` IMEDIATAMENTE.
   - Use 'hoje' ou 'amanhã' no parametro data se o chefe falar assim.

💰 SOBRE FINANCEIRO:
- A ferramenta calcula tudo. Mostre valores (R$) APENAS se o chefe perguntar explicitamente sobre "dinheiro" ou "faturamento".
- Se ele perguntar "agenda", mostre apenas horários e nomes.

RESUMO: Fale pouco e EXECUTE as ferramentas. Você tem acesso total ao banco de dados.
VOCÊ É A SECRETÁRIA PESSOAL DO(A) DONO(A) DA LOJA.
Quem está falando com você AGORA é o(a) PROPRIETÁRIO(A) (Boss).

SEU OBJETIVO:

Ajudar o dono a gerenciar o dia.

1. BLOQUEAR AGENDA: Se o dono disser "Vou sair", "Fecha a agenda", "Bloqueia a tarde":
2. FERRAMENTA PRINCIPAL: `consultar_agenda_dono`
3. "bloquear_agenda_dono"

- Para ver o dia de hoje: use data_inicio='hoje', data_fim='mesmo_dia'
- Para ver a SEMANA inteira: use data_inicio='hoje', data_fim='semana'

COMO AGIR:

TOM DE VOZ E PERSONALIDADE:
- Seja extremamente educada, gentil e prestativa.
- NÃO USE termos como "Chefe", "Patroa", "Líder" ou "Boss".
- Trate-a com carinho e profissionalismo. Use emojis delicados (✨, 🌷, 😊).
- Seja breve e eficiente.

💰 SOBRE FINANCEIRO (IMPORTANTE):
- A ferramenta vai te entregar os valores de cada serviço e o total previsto.
- PORÉM, você só deve mostrar valores (R$) se o chefe perguntar explicitamente sobre "faturamento", "dinheiro", "quanto deu", "valores" ou "resumo financeiro".
- Se ele perguntar apenas "como está a agenda" ou "quem vem hoje", mostre apenas os horários e nomes, OMITINDO OS VALORES.

"""
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

    if len(texto) > 300:
        logging.warning(f"🚫 Mensagem BLOQUEADA (muito longa: {len(texto)} chars)")
        return True

    proibidas_exatas = [
        'chatgpt', 'openai', 'ignore as instruções', 'mode debug',
        'sua stack', 'código fonte', 'quem te criou', 'quem te desenvolveu'
    ]

    for p in proibidas_exatas:
        if p in texto_lower:
            return True

    padroes_proibidos = [
        r'hino.*nacion',
        r'canta.*hino',
        r'letra.*m[uú]sica',
        r'futebo',
        r'pol[íi]tica',
        r'receita.*de',
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

# =====================================================================
# FUNÇÕES TOOLS (MODIFICADAS COM FUZZY MATCH)
# =====================================================================

def listar_profissionais(barbearia_id: int) -> str:
    try:
        with current_app.app_context():
            profissionais = Profissional.query.filter_by(barbearia_id=barbearia_id).all()
            if not profissionais:
                logging.warning(f"Ferramenta 'listar_profissionais' (barbearia_id: {barbearia_id}): Nenhum profissional cadastrado.")
                return "Nenhum profissional cadastrado para esta loja no momento."
            nomes = [p.nome for p in profissionais]
            return f"Profissionais disponíveis: {', '.join(nomes)}."
    except Exception as e:
        current_app.logger.error(f"Erro interno na ferramenta 'listar_profissionais': {e}", exc_info=True)
        return f"Erro ao listar profissionais: Ocorreu um erro interno."

def listar_servicos(barbearia_id: int) -> str:
    """Lista os serviços, excluindo serviços internos de bloqueio."""
    try:
        with current_app.app_context():
            # ✅ ALTERAÇÃO: Filtra para NÃO mostrar o Bloqueio Administrativo
            servicos = Servico.query.filter(
                Servico.barbearia_id == barbearia_id,
                Servico.nome != "Bloqueio Administrativo"
            ).order_by(Servico.nome).all()

            if not servicos:
                logging.warning(f"Ferramenta 'listar_servicos' (barbearia_id: {barbearia_id}): Nenhum serviço cadastrado.")
                return "Nenhum serviço cadastrado para esta loja."

            lista_formatada = []
            servicos_a_partir_de = [
                "Platinado", "Luzes", "Coloração", "Pigmentação",
                "Selagem", "Escova Progressiva", "Relaxamento",
                "Alisamento", "Hidratação", "Reconstrução",
                "Volume Brasileiro", "Volume Russo", "Mega Volume", "Remoção", "Remoção de Cílios"
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

def calcular_horarios_disponiveis(barbearia_id: int, profissional_nome: str, dia: str, servico_nome: str = None) -> str:
    try:
        with current_app.app_context():
            # 1. Recupera a Barbearia
            barbearia = Barbearia.query.get(barbearia_id)
            if not barbearia:
                return "Erro: Barbearia não encontrada."

            # 2. CARREGA O PLUGIN (O Cérebro Correto: Barbearia ou Pousada) 🧠
            plugin = carregar_plugin_negocio(barbearia)

            # 3. Busca Profissionais (Usando o Plugin)
            todos_profs = plugin.buscar_recursos() # Retorna profissionais ou quartos
            # Extrai os nomes para o Fuzzy Match
            lista_nomes = [p.nome for p in todos_profs]
            
            nome_correto = encontrar_melhor_match(profissional_nome, lista_nomes)

            if not nome_correto:
                return f"Profissional '{profissional_nome}' não encontrado."

            # Pega o objeto profissional correto
            profissional = next(p for p in todos_profs if p.nome == nome_correto)

            # 4. Tratamento de Data (Mantido)
            agora_br = datetime.now(BR_TZ)
            if dia.lower() == 'hoje': dia_dt = agora_br
            elif dia.lower() == 'amanhã': dia_dt = agora_br + timedelta(days=1)
            else:
                try: dia_dt = BR_TZ.localize(datetime.strptime(dia, '%Y-%m-%d'))
                except: return "Data inválida. Use 'hoje', 'amanhã' ou AAAA-MM-DD."

            # 5. Tratamento de Serviço/Duração
            duracao_calculo = 60
            msg_extra = ""
            
            if servico_nome:
                # Busca serviços usando o Plugin também (pra manter padrão)
                todos_servicos = plugin.buscar_servicos()
                nome_serv_match = encontrar_melhor_match(servico_nome, [s.nome for s in todos_servicos])

                if nome_serv_match:
                    servico = next(s for s in todos_servicos if s.nome == nome_serv_match)
                    duracao_calculo = servico.duracao
                    logging.info(f"⏱️ Calculando para '{servico.nome}' ({duracao_calculo} min)")
                else:
                    msg_extra = " (Obs: Não achei o serviço exato, usando 1h)."
            else:
                msg_extra = " (Obs: Calculado com base em 60min)."

            # =========================================================
            # 🔥 O GRANDE MOMENTO: CÁLCULO VIA PLUGIN
            # =========================================================
            # O plugin sabe se tem que bloquear almoço, se é pousada, etc.
            horarios = plugin.calcular_disponibilidade(
                data_ref=dia_dt,
                profissional_id=profissional.id, # Passamos o ID
                duracao=duracao_calculo
            )

            # Formatação da Resposta
            if not horarios:
                # 👇 IMPLEMENTAÇÃO DA BUSCA PROATIVA DE VAGAS 👇
                sugestoes = []
                # Procura nos próximos 2 dias
                for i in range(1, 3):
                    prox_dia = dia_dt + timedelta(days=i)
                    
                    # Chama o plugin novamente para o próximo dia
                    h_prox = plugin.calcular_disponibilidade(
                        data_ref=prox_dia,
                        profissional_id=profissional.id,
                        duracao=duracao_calculo
                    )
                    
                    if h_prox:
                        # Pega até 4 horários para não poluir
                        lista_p = [h.strftime('%H:%M') for h in h_prox[:4]] 
                        sugestoes.append(f"Dia {prox_dia.strftime('%d/%m')}: {', '.join(lista_p)}")
                
                msg_retorno = f"❌ Sem horários livres para {nome_correto} em {dia_dt.strftime('%d/%m')}."
                
                if sugestoes:
                    msg_retorno += f" Mas encontrei estas vagas próximas: {'; '.join(sugestoes)}."
                
                return msg_retorno
                
            lista_h = [h.strftime('%H:%M') for h in horarios]
            return f"Horários livres para {nome_correto} em {dia_dt.strftime('%d/%m')}: {', '.join(lista_h)}{msg_extra}"

    except Exception as e:
        current_app.logger.error(f"Erro Plugin Cálculo: {e}", exc_info=True)
        return f"Erro ao calcular horários: {str(e)}"

def consultar_agenda_dono(barbearia_id: int, data_inicio: str, data_fim: str) -> str:
    """
    Retorna os agendamentos E O FATURAMENTO PREVISTO.
    Ignora visualmente os bloqueios no cálculo financeiro explícito.
    """
    try:
        with current_app.app_context():
            agora = datetime.now(BR_TZ)

            if data_inicio.lower() in ['hoje', 'agora']:
                dt_ini = agora.replace(hour=0, minute=0, second=0)
            else:
                try: dt_ini = datetime.strptime(data_inicio, '%Y-%m-%d')
                except: dt_ini = agora

            if data_fim.lower() == 'hoje':
                dt_fim = agora.replace(hour=23, minute=59)
            elif data_fim == 'mesmo_dia':
                dt_fim = dt_ini.replace(hour=23, minute=59)
            elif data_fim == 'semana':
                dt_fim = dt_ini + timedelta(days=7)
                dt_fim = dt_fim.replace(hour=23, minute=59)
            else:
                try: dt_fim = datetime.strptime(data_fim, '%Y-%m-%d')
                except: dt_fim = dt_ini.replace(hour=23, minute=59)

            agendamentos = Agendamento.query.options(joinedload(Agendamento.servico), joinedload(Agendamento.profissional)).filter(
                Agendamento.barbearia_id == barbearia_id,
                Agendamento.data_hora >= dt_ini,
                Agendamento.data_hora <= dt_fim
            ).order_by(Agendamento.data_hora).all()

            if not agendamentos:
                return f"🏖️ Nada marcado entre {dt_ini.strftime('%d/%m')} e {dt_fim.strftime('%d/%m')}."

            relatorio = [f"📅 RELATÓRIO DE {dt_ini.strftime('%d/%m')} A {dt_fim.strftime('%d/%m')}\n"]
            faturamento_total = 0.0
            qtd_clientes_reais = 0
            dia_atual = ""

            for ag in agendamentos:
                data_ag_str = ag.data_hora.strftime('%d/%m (%A)')
                if data_ag_str != dia_atual:
                    relatorio.append(f"\n🔹 {data_ag_str}")
                    dia_atual = data_ag_str

                valor = ag.servico.preco if ag.servico else 0.0
                nome_cliente = ag.nome_cliente
                nome_servico = ag.servico.nome if ag.servico else "Serviço"
                
                # Tratamento visual para bloqueios
                if "bloqueio" in nome_cliente.lower() or "bloqueio" in nome_servico.lower() or valor == 0:
                    linha = f" ⛔ {ag.data_hora.strftime('%H:%M')} - BLOQUEADO / INDISPONÍVEL"
                else:
                    faturamento_total += valor
                    qtd_clientes_reais += 1
                    linha = f" ⏰ {ag.data_hora.strftime('%H:%M')} - {nome_cliente.split()[0]} ({nome_servico}) [R$ {valor:.2f}]"
                
                relatorio.append(linha)

            relatorio.append("\n" + "="*20)
            relatorio.append(f"📊 RESUMO FINANCEIRO:")
            relatorio.append(f"✅ Clientes Agendados: {qtd_clientes_reais}")
            relatorio.append(f"💰 Faturamento Previsto: R$ {faturamento_total:.2f}")
            relatorio.append("="*20)

            return "\n".join(relatorio)

    except Exception as e:
        return f"Erro ao consultar agenda: {e}"

def criar_agendamento(barbearia_id: int, nome_cliente: str, telefone_cliente: str, data_hora: str, profissional_nome: str, servico_nome: str) -> str:
    try:
        with current_app.app_context():
            todos_profs = Profissional.query.filter_by(barbearia_id=barbearia_id).all()
            nome_prof_match = encontrar_melhor_match(profissional_nome, [p.nome for p in todos_profs])

            if not nome_prof_match:
                return f"Profissional '{profissional_nome}' não encontrado."

            profissional = next(p for p in todos_profs if p.nome == nome_prof_match)

            todos_servicos = Servico.query.filter_by(barbearia_id=barbearia_id).all()
            nome_serv_match = encontrar_melhor_match(servico_nome, [s.nome for s in todos_servicos])

            if not nome_serv_match:
                logging.warning(f"Tentativa de agendar serviço inexistente: '{servico_nome}'")
                return f"Serviço '{servico_nome}' não encontrado. Por favor, confirme o nome do serviço na lista: {', '.join([s.nome for s in todos_servicos])}."

            servico = next(s for s in todos_servicos if s.nome == nome_serv_match)

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
                try:
                    sugestao = calcular_horarios_disponiveis(barbearia_id, profissional.nome, data_hora_dt.strftime('%Y-%m-%d'), servico.nome)
                except:
                    sugestao = "Verifique outros horários."

                return f"❌ Conflito! O horário {data_hora_dt.strftime('%H:%M')} não é suficiente para '{servico.nome}' ({servico.duracao} min) ou já está ocupado. {sugestao}"

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

          # =================================================================
            # 📢 NOTIFICAÇÃO 1: PARA O CLIENTE (LINK CURTO E DISCRETO 🤫)
            # =================================================================
            try:
                from app.routes import enviar_mensagem_whatsapp_meta 
                
                barbearia_atual = profissional.barbearia
                if barbearia_atual.assinatura_ativa:
                    
                    # Gera Link Curto
                    link_curto = url_for('main.redirect_gcal', agendamento_id=novo_agendamento.id, _external=True)
                    
                    # MENSAGEM MINIMALISTA (Para não brigar com a resposta da IA)
                    msg_cliente = f"📅 *Toque para salvar na agenda:* \n{link_curto}"
                    
                    enviar_mensagem_whatsapp_meta(telefone_cliente, msg_cliente, barbearia_atual)
                    logging.info(f"✅ Link Curto enviado via IA: {telefone_cliente}")

            except Exception as e_client:
                logging.error(f"Erro ao notificar cliente na tool: {e_client}")

            
            # 🔥 GATILHO GOOGLE CALENDAR (Blindado)
            # Rota ajustada para app.google
            try:
                logging.info(f"📅 Disparando sincronização Google para Agendamento {novo_agendamento.id}")
                trigger_google_calendar_sync(novo_agendamento.id, CalendarAction.CREATE)
            except Exception as e:
                logging.error(f"⚠️ Erro ao disparar sync Google: {e}")

            # 🔔 NOTIFICAÇÃO AUTOMÁTICA PRO DONO
            try:
                from app.routes import enviar_mensagem_whatsapp_meta
                barbearia_dono = profissional.barbearia

                if barbearia_dono.telefone_admin and barbearia_dono.assinatura_ativa:
                    nome_loja = barbearia_dono.nome_fantasia.lower()
                    is_lash = any(x in nome_loja for x in ['lash', 'studio', 'cílios', 'sobrancelha', 'beleza'])

                    if is_lash:
                        emoji_titulo = "🦋✨"
                        emoji_servico = "💅"
                    else:
                        emoji_titulo = "💈✂️"
                        emoji_servico = "🪒"

                    msg_dono = (
                        f"🔔 *Novo Agendamento (Via IA)* {emoji_titulo}\n\n"
                        f"👤 {nome_cliente}\n"
                        f"📅 {data_hora_dt.strftime('%d/%m às %H:%M')}\n"
                        f"{emoji_servico} {servico.nome}\n"
                        f"👋 Prof: {profissional.nome}"
                    )

                    enviar_mensagem_whatsapp_meta(barbearia_dono.telefone_admin, msg_dono, barbearia_dono)
                    logging.info(f"🔔 Notificação enviada para o dono {barbearia_dono.telefone_admin}")

            except Exception as e:
                logging.error(f"Erro ao notificar dono: {e}")

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

    # --- NOVA FUNÇÃO: BLOQUEAR AGENDA ---
def bloquear_agenda_dono(barbearia_id: int, data: str, hora_inicio: str, hora_fim: str, motivo: str = "Bloqueio Admin") -> str:
    """
    Bloqueia a agenda criando agendamentos com valor R$ 0,00.
    ACEITA: 'hoje', 'amanhã' ou data 'YYYY-MM-DD'.
    """
    try:
        with current_app.app_context():
            # 1. Tratamento Inteligente da Data
            agora = datetime.now(BR_TZ)
            if data.lower() == 'hoje':
                data_dt = agora.date()
            elif data.lower() == 'amanhã' or data.lower() == 'amanha':
                data_dt = (agora + timedelta(days=1)).date()
            else:
                try:
                    data_dt = datetime.strptime(data, '%Y-%m-%d').date()
                except ValueError:
                    return f"Erro: Data inválida ('{data}'). Use 'hoje', 'amanhã' ou o formato AAAA-MM-DD."

            # Converter horas
            try:
                h_ini = datetime.strptime(hora_inicio, '%H:%M').time()
                h_fim = datetime.strptime(hora_fim, '%H:%M').time()
            except ValueError:
                return "Erro de hora: Use o formato HH:MM (ex: 14:00)."
            
            inicio_dt = datetime.combine(data_dt, h_ini)
            fim_dt = datetime.combine(data_dt, h_fim)
            
            # 2. Identificar Profissional (Pega o primeiro/dono)
            profissional = Profissional.query.filter_by(barbearia_id=barbearia_id).first()
            if not profissional: return "Erro: Profissional não encontrado."
            
            # 3. LÓGICA INTELIGENTE: Busca ou Cria Serviço de Bloqueio (R$ 0.00)
            nome_servico_bloqueio = "Bloqueio Administrativo"
            servico = Servico.query.filter_by(barbearia_id=barbearia_id, nome=nome_servico_bloqueio).first()
            
            # --- CORREÇÃO DE LEGADO: Se já existe mas o preço está errado, corrige agora ---
            if servico and servico.preco > 0:
                servico.preco = 0.0
                db.session.commit()
                logging.info(f"💰 Serviço '{nome_servico_bloqueio}' teve o preço corrigido para R$ 0.00.")

            if not servico:
                # REMOVIDO O CAMPO 'descricao' QUE CAUSAVA O ERRO
                servico = Servico(
                    nome=nome_servico_bloqueio,
                    preco=0.0,
                    duracao=30,
                    barbearia_id=barbearia_id
                )
                db.session.add(servico)
                db.session.commit()
                logging.info(f"✅ Serviço '{nome_servico_bloqueio}' criado automaticamente.")

            # 4. Loop para preencher os horários
            intervalo = servico.duracao if servico.duracao > 0 else 30
            cursor = inicio_dt
            bloqueios = 0
            
            while cursor < fim_dt:
                ocupado = Agendamento.query.filter_by(
                    barbearia_id=barbearia_id, 
                    profissional_id=profissional.id, 
                    data_hora=cursor
                ).first()
                
                if not ocupado:
                    bloqueio = Agendamento(
                        nome_cliente=f"⛔ {motivo}",
                        telefone_cliente="00000000000",
                        data_hora=cursor,
                        profissional_id=profissional.id,
                        servico_id=servico.id,
                        barbearia_id=barbearia_id
                    )
                    db.session.add(bloqueio)
                    bloqueios += 1
                
                cursor += timedelta(minutes=intervalo)
            
            db.session.commit()
            
            # Formata resposta para confirmar a data exata usada
            data_formatada = data_dt.strftime('%d/%m/%Y')
            return f"SUCESSO: Agenda bloqueada dia {data_formatada} das {hora_inicio} às {hora_fim}. ({bloqueios} horários fechados)."
            
    except Exception as e:
        db.session.rollback()
        logging.error(f"❌ Erro crítico ao bloquear: {e}") # Adicionado log melhor
        return f"Erro ao bloquear: {str(e)}"
        
# =====================================================================
# DEFINIÇÃO DAS TOOLS
# =====================================================================

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
    description="Consulta horários disponíveis. TENTE SEMPRE INFORMAR O SERVIÇO ('servico_nome') se o cliente já tiver dito, para garantir que o tempo calculado seja suficiente.",
    parameters={
        "type": "object",
        "properties": {
            "profissional_nome": {"type": "string", "description": "Nome exato do profissional"},
            "dia": {"type": "string", "description": "Dia no formato YYYY-MM-DD, ou as palavras 'hoje' ou 'amanhã'"},
            "servico_nome": {"type": "string", "description": "Nome do serviço desejado (Opcional, mas RECOMENDADO para evitar conflitos de horário)"}
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

consultar_agenda_func = FunctionDeclaration(
    name="consultar_agenda_dono",
    description="Exclusivo para o dono. Consulta os agendamentos e previsão financeira. Aceita 'semana'.",
    parameters={
        "type": "object",
        "properties": {
            "data_inicio": {"type": "string", "description": "Data inicial YYYY-MM-DD ou 'hoje'"},
            "data_fim": {"type": "string", "description": "Data final YYYY-MM-DD, 'mesmo_dia' (só hoje) ou 'semana' (7 dias)"}
        },
        "required": ["data_inicio", "data_fim"]
    }
)

# --- ✅ MOVIDO: DEFINIÇÃO DE BLOQUEIO ANTES DA LISTA TOOLS ---
bloquear_agenda_func = FunctionDeclaration(
    name="bloquear_agenda_dono",
    description="Bloqueia um período da agenda (ex: médico, folga). Use APENAS se o dono pedir para fechar/bloquear a agenda.",
    parameters={
        "type": "object",
        "properties": {
            "data": {"type": "string", "description": "YYYY-MM-DD"},
            "hora_inicio": {"type": "string", "description": "HH:MM"},
            "hora_fim": {"type": "string", "description": "HH:MM"},
            "motivo": {"type": "string", "description": "Motivo do bloqueio (ex: Médico)"}
        },
        "required": ["data", "hora_inicio", "hora_fim"]
    }
)

tools = Tool(
    function_declarations=[
        listar_profissionais_func,
        listar_servicos_func,
        calcular_horarios_disponiveis_func,
        criar_agendamento_func,
        cancelar_agendamento_func,
        consultar_agenda_func,
        bloquear_agenda_func # ✅ Agora definido corretamente antes
    ]
)

# --- Inicialização do Modelo Gemini (OTIMIZADO PARA FLASH) ---

model = None

try:
    model_name_to_use = 'gemini-2.5-flash'
    
    generation_config = GenerationConfig(
        temperature=0.0,
        top_p=0.95,
        top_k=40,
        max_output_tokens=1024,
    )

    # 👇 ADIÇÃO DE SEGURANÇA: Configurações para evitar bloqueio falso (Output: 0)
    from google.generativeai.types import HarmCategory, HarmBlockThreshold

    safety_settings = {
        HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
    }

    model = genai.GenerativeModel(
        model_name=model_name_to_use,
        tools=[tools],
        generation_config=generation_config,
        safety_settings=safety_settings  # ✅ APLICANDO A LIBERAÇÃO AQUI
    )

    logging.info(f"✅ Modelo Gemini ('{model_name_to_use}') inicializado com SUCESSO e SEM FILTROS!")

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

# --- FUNÇÃO PRINCIPAL DE PROCESSAMENTO ---

def processar_ia_gemini(user_message: str, barbearia_id: int, cliente_whatsapp: str) -> str:
    """
    Processa a mensagem do usuário usando o Gemini, mantendo o histórico
    da conversa no cache (Redis) associado ao número do cliente.

    ⭐ AGORA COM DETECTOR DE GHOST CALL (Paper Acadêmico 2026)
    ✅ COMANDO RESET E AUTO-RECUPERAÇÃO IMPLEMENTADOS
    🚨 MODO RESGATE SILENCIOSO: Assume o controle se a IA travar (Output 0)
    """

    if not model:
        logging.error("Modelo Gemini não inicializado. Abortando.")
        return "O sistema está reiniciando rapidinho. Tente em 1 minuto! ⏳"

    cache_key = f"chat_history_{cliente_whatsapp}:{barbearia_id}"

    # 1. 🛑 COMANDO DE RESET MANUAL (IMPLEMENTAÇÃO SEGURA)
    # Se o usuário pedir reset, limpamos o cache antes de qualquer processamento pesado.
    comandos_reset = ['reset', 'reiniciar', 'começar de novo', 'limpar', 'resetar']
    if user_message.lower().strip() in comandos_reset:
        try:
            cache.delete(cache_key)
            logging.info(f"🧹 Histórico resetado manualmente para {cliente_whatsapp}")
            return "Conexão reiniciada! 🔄 Como posso ajudar você agora?"
        except Exception as e:
            logging.error(f"Erro ao tentar resetar cache: {e}")
            return "Erro ao tentar reiniciar. Tente novamente."

    try:
        barbearia = Barbearia.query.get(barbearia_id)

        if not barbearia:
            logging.error(f"Barbearia ID {barbearia_id} não encontrada no processar_ia_gemini.")
            return "Desculpe, não consegui identificar para qual loja você está ligando."

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

        # --- VERIFICAÇÃO DE IDENTIDADE: É A PATROA/PATRÃO? 🕵️♀️ ---

        tel_cliente_limpo = ''.join(filter(str.isdigit, cliente_whatsapp))
        tel_admin_limpo = ''.join(filter(str.isdigit, barbearia.telefone_admin or ''))

        eh_o_dono = (tel_admin_limpo and tel_admin_limpo in tel_cliente_limpo) or (tel_cliente_limpo in tel_admin_limpo)

        if eh_o_dono:
            logging.info(f"👑 MODO SECRETÁRIA ATIVADO para {cliente_whatsapp}")

            system_prompt = SYSTEM_INSTRUCTION_SECRETARIA.format(
                data_de_hoje=agora_br.strftime('%d/%m/%Y')
            )

        # 👇 [NOVO] VERIFICAÇÃO DE POUSADA (ANTES DE CAIR NO PADRÃO) 👇
        elif barbearia.business_type == 'pousada':
            logging.info(f"🏨 MODO POUSADA ATIVADO para {cliente_whatsapp}")
            
            # Carrega o Plugin da Pousada
            plugin = carregar_plugin_negocio(barbearia)
            
            # Pega o Prompt especializado (Quartos, Check-in, Regras)
            base_prompt = plugin.gerar_system_prompt()
            
            # Adiciona o contexto temporal que a IA precisa
            system_prompt = f"{base_prompt}\n\nHOJE: {data_hoje_str} | AMANHÃ: {data_amanha_str}\nID_CLIENTE: {cliente_whatsapp}"

        else:
            # --- LÓGICA MULTI-TENANCY (BARBEARIA VS LASH) - MODO CLIENTE ---

            nome_lower = barbearia.nome_fantasia.lower()
            eh_lash = any(x in nome_lower for x in ['lash', 'cílios', 'sobrancelha', 'estética', 'beauty', 'studio'])

            if eh_lash:
                # 👇 AQUI ESTÁ O AJUSTE DE PERSONA (SEM 'QUERIDA') 👇
                header_persona = f"""
PERSONA: Assistente Virtual do {barbearia.nome_fantasia} (Studio de Beleza/Lash).
TOM: Educada, gentil e prática.
- TRATAMENTO: Chame de "Amiga" ou pelo Nome. 🚫 NUNCA use "Querida" ou "Amor".
- EMOJIS: Use com moderação (1 ou 2 por mensagem). Ex: ✨ 🦋
- INÍCIO: Se não souber o nome, pergunte gentilmente logo no início.
"""
            else:
                header_persona = f"""

PERSONA: Assistente da {barbearia.nome_fantasia} (Barbearia).
TOM: Brother, prático, gente boa. Use: 'Cara', 'Mano', 'Campeão'.
EMOJIS OBRIGATÓRIOS: ✂️ 💈 👊 🔥

"""

            # 4. 🔥 LÓGICA DE PROFISSIONAL ÚNICO 🔥

            profs_db = Profissional.query.filter_by(barbearia_id=barbearia_id).all()
            qtd_profs = len(profs_db)

            if qtd_profs == 1:
                nome_unico = profs_db[0].nome
                regra_profissional = f"""

ATENÇÃO: Só existe 1 profissional neste estabelecimento: {nome_unico}.
NÃO pergunte 'com quem prefere fazer'.
Se o cliente não especificar, ASSUMA IMEDIATAMENTE que é com {nome_unico} e prossiga para verificar horários.

"""

            else:
                regra_profissional = "Pergunte ao cliente a preferência de profissional caso ele não diga."

            # 5. Monta o Prompt Final (CLIENTE)

            system_prompt = SYSTEM_INSTRUCTION_CLIENTE.format(
                header_persona=header_persona,
                cliente_whatsapp=cliente_whatsapp,
                barbearia_id=barbearia_id,
                data_de_hoje=data_hoje_str,
                data_de_amanha=data_amanha_str,
                regra_profissional_dinamica=regra_profissional

            )

        is_new_chat = not history_to_load

        # ==============================================================================
        # 🛡️ INTERCEPTADOR DE PRIMEIRO CONTATO (SOLUÇÃO PROFISSIONAL ANTI-LOOP)
        # ==============================================================================
        # Se for um novo chat, nós NÃO chamamos a IA agora.
        # Nós enviamos as boas-vindas + foto manualmente, salvamos o estado e encerramos.
        # Isso garante que a foto chegue 100% das vezes e evita loops.
        
        if is_new_chat:
            logging.info(f"🆕 Iniciando nova conversa com {cliente_whatsapp}. Aplicando Protocolo de Boas-Vindas.")

            # 1. Mensagem Gentil, Padronizada e com a direção correta (ABAIXO)
            msg_boas_vindas = (
                f"Olá! Seja muito bem-vinda ao *{barbearia.nome_fantasia}*! ✨\n\n"
                f"É um prazer receber você por aqui. Para facilitar, estou enviando logo abaixo "
                f"nossa tabela completa de serviços e valores atualizados. 💖\n\n"
                f"Qual desses procedimentos você gostaria de agendar hoje? 😊"
            )

            try:
                from app.routes import enviar_midia_whatsapp_meta, enviar_mensagem_whatsapp_meta
                
                # 2. Envia TEXTO
                enviar_mensagem_whatsapp_meta(cliente_whatsapp, msg_boas_vindas, barbearia)
                
                # 3. Envia FOTO (Se houver)
                if barbearia.url_tabela_precos:
                    logging.info(f"📸 Enviando Tabela de Preços inicial para {cliente_whatsapp}")
                    enviar_midia_whatsapp_meta(cliente_whatsapp, barbearia.url_tabela_precos, barbearia)

            except Exception as e:
                logging.error(f"Erro ao enviar boas-vindas manuais: {e}")
                # Segue o baile se der erro no envio, para não travar o salvamento do histórico

            # 4. 💾 CONSTRUÇÃO MANUAL DO HISTÓRICO (O SEGREDO PARA NÃO DAR LOOP)
            # Precisamos salvar: [Instrução do Sistema] + [O que o cliente disse] + [O que respondemos]
            
            history_manual = [
                # Turno 1: Instrução do Sistema (User) -> OK (Model)
                Content(role='user', parts=[protos.Part(text=system_prompt)]),
                Content(role='model', parts=[protos.Part(text="Entendido. Vou agir conforme suas instruções.")]),
                
                # Turno 2: O que o cliente acabou de mandar (User) -> Nossa resposta de boas-vindas (Model)
                Content(role='user', parts=[protos.Part(text=user_message)]), 
                Content(role='model', parts=[protos.Part(text=msg_boas_vindas)])
            ]
            
            # 5. Salva no Redis e RETORNA VAZIO (Fim da execução deste turno)
            new_serialized_history = serialize_history(history_manual)
            cache.set(cache_key, new_serialized_history)
            logging.info(f"✅ Histórico inicial criado e salvo manualmente. Loop evitado.")
            
            return "" # Retorna vazio para a rota principal não enviar nada duplicado.

        # ==============================================================================
        # FIM DO INTERCEPTADOR - Se não for new_chat, vida normal abaixo:
        # ==============================================================================

        chat_session = model.start_chat(history=history_to_load)

        # =========================================================================
        # 👇 ATUALIZAÇÃO FINAL: ENVIO DE TABELA FORÇADO NO PRIMEIRO CONTATO 👇
        # =========================================================================
        
        # Se for um novo chat (apenas system prompt e saudação inicial da IA no histórico),
        # assumimos que é o primeiro contato real do cliente.
        # Não importa se ele disse "oi", "preço" ou "agendar", vamos mandar a tabela.
        
        eh_inicio_conversa = len(history_to_load) <= 2

        if eh_inicio_conversa:
            
            # Mensagem gentil padrão para TODOS os casos
            msg_texto = f"Olá! Seja muito bem-vindo(a) ao *{barbearia.nome_fantasia}*! ✨\n\nJá separei nossa tabela de valores para você dar uma olhadinha aqui abaixo! 👇💖\n\nQual desses serviços você gostaria de agendar? 😊"
            
            # ATUALIZA O HISTÓRICO MANUALMENTE
            # Verifica se o último item é um objeto Content e tem role 'model'
            # (Agora vai funcionar porque inicializamos history_to_load corretamente acima)
            if len(history_to_load) > 1 and getattr(history_to_load[-1], 'role', '') == 'model':
                history_to_load.pop()
                
            history_to_load.append(Content(role='model', parts=[protos.Part(text=msg_texto)]))
            
            # Salva o novo estado no Redis
            # serialize_history espera uma lista de Content, que agora está correta
            new_serialized_history = serialize_history(history_to_load)
            cache.set(cache_key, new_serialized_history)
            logging.info(f"✅ Boas-vindas automáticas (FORÇADO) para: {user_message}")

            # ENVIA A MENSAGEM E A FOTO
            if barbearia.url_tabela_precos:
                try:
                    from app.routes import enviar_midia_whatsapp_meta, enviar_mensagem_whatsapp_meta
                    
                    # 1. Envia Texto
                    enviar_mensagem_whatsapp_meta(cliente_whatsapp, msg_texto, barbearia)
                    
                    # 2. Envia Foto
                    logging.info(f"📸 Enviando Tabela automática para {cliente_whatsapp}")
                    enviar_midia_whatsapp_meta(cliente_whatsapp, barbearia.url_tabela_precos, barbearia)
                    
                    return "" # Retorna vazio para encerrar aqui
                    
                except Exception as e:
                    logging.error(f"Erro no envio forçado: {e}")
                    return msg_texto
            
            return msg_texto

        logging.info(f"Enviando mensagem para a IA: {user_message}")
        
        # --- TENTATIVA DE COMUNICAÇÃO COM DETECÇÃO DE TRAVAMENTO ---
        travou = False
        response = None

        try:
            response = chat_session.send_message(user_message)
            
            # Verifica se a IA respondeu VAZIO (O problema do Output 0 - Bloqueio de Segurança)
            if not response.candidates or not response.candidates[0].content.parts:
                travou = True
                logging.warning("⚠️ ALERTA: IA retornou Output 0 (Bloqueio de Segurança). Iniciando Resgate.")

        except generation_types.StopCandidateException as e:
            logging.error(f"Erro Malformed Call: {e}")
            travou = True
        except Exception as e:
            logging.error(f"Erro ao enviar mensagem para a IA: {e}")
            travou = True

        # ======================================================================
        # 🚨 MODO RESGATE INTELIGENTE (SEM APAGAR A MEMÓRIA)
        # Se a IA travar, o Python assume e entrega o que o cliente quer.
        # ======================================================================
        if travou:
            # NÃO DELETAMOS O CACHE AQUI! (Isso corrige o problema da "Amnésia")
            msg_lower = user_message.lower()

            # CASO 1: Cliente pediu PREÇO, VALOR, TABELA
            if any(x in msg_lower for x in ['preço', 'preco', 'valor', 'quanto', 'tabela', 'custo']):
                logging.info("🚨 RESGATE ATIVADO: Enviando tabela/preços.")
                
                if barbearia.url_tabela_precos:
                    from app.routes import enviar_midia_whatsapp_meta
                    enviar_midia_whatsapp_meta(cliente_whatsapp, barbearia.url_tabela_precos, barbearia)
                    return "Enviei nossa tabela abaixo! 👇 Se já souber o que quer, é só me falar o serviço e horário."
                
                lista = listar_servicos(barbearia_id)
                return f"Aqui estão nossos valores: 👇\n\n{lista}\n\nQual deles você prefere?"

            # CASO 2: Cliente pediu SERVIÇOS, OPÇÕES, QUAIS, LISTA
            elif any(x in msg_lower for x in ['serviço', 'servico', 'opções', 'opcoes', 'quais', 'lista', 'fazem', 'trabalham']):
                logging.info("🚨 RESGATE ATIVADO: Enviando lista de serviços.")
                lista = listar_servicos(barbearia_id)
                return f"Temos estas opções maravilhosas! ✨\n\n{lista}\n\nGostaria de agendar algum?"

            # CASO 3: Agendamento (Hora/Data) - CRUCIAL PARA NÃO DAR ERRO
            elif any(x in msg_lower for x in ['agendar', 'marcar', 'horário', 'dia', 'amanhã', 'hoje', 'as ', 'às ']):
                # Resposta que mantém o fluxo sem perder a paciência do cliente
                return "Entendi! ✨ Tive uma pequena oscilação no sistema, mas já anotei o horário. Para eu confirmar de vez: **Qual é o serviço exato e seu nome completo?**"

            # CASO 4: Genérico
            else:
                return "Oiê! ✨ O sinal oscilou um pouquinho aqui. Pode repetir a última parte? Quero garantir que entendi certinho para agendar pra você!"

        # --- SE NÃO TRAVOU, SEGUE O FLUXO NORMAL DA IA ---

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
                "consultar_agenda_dono": consultar_agenda_dono,
                "bloquear_agenda_dono": bloquear_agenda_dono

            }
            
            # 🔥 O PULO DO GATO: SE FOR POUSADA, TROCA A FERRAMENTA 🔥
            if barbearia.business_type == 'pousada':
                logging.info("🏨 Substituindo tool 'listar_servicos' pela versão POUSADA.")
                tool_map["listar_servicos"] = listar_servicos_pousada

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
                    return "Tive um probleminha técnico rápido ao confirmar. Tenta me pedir de novo? 🙏"

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
        try:
            cache.set(cache_key, serialize_history(chat_session.history))
        except Exception:
            pass

        logging.info(f"✅ Histórico salvo no Redis (se sucesso).")
        final_response_text = "Desculpe, não entendi. Pode repetir?"
        if response.candidates and response.candidates[0].content.parts:
            part = response.candidates[0].content.parts[0]

            if part.text:

                final_response_text = part.text

            else:

                logging.warning("IA retornou conteúdo sem texto (provavelmente apenas FunctionCall).")

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

            pass

        # ==========================================================================
        # 🚨 ⭐ DETECTOR DE GHOST CALL (IMPLEMENTAÇÃO DO PAPER ACADÊMICO) ⭐ 🚨
        # ==========================================================================

        eh_ghost, resposta_corrigida = detectar_ghost_call(final_response_text, chat_session.history)

        if eh_ghost:

            logging.error(f"🚨 Ghost call bloqueado para cliente {cliente_whatsapp}")

            final_response_text = resposta_corrigida

        # ==========================================================================

        # 🕵️ INTERCEPTADOR DE COMANDOS (TABELA DE PREÇOS / FOTOS)

        if "[ENVIAR_TABELA]" in final_response_text:

            final_response_text = final_response_text.replace("[ENVIAR_TABELA]", "").strip()

            link_foto = getattr(barbearia, 'url_tabela_precos', None)

            if link_foto:

                logging.info(f"📸 Enviando Tabela de Preços para {cliente_whatsapp}")

                from app.routes import enviar_midia_whatsapp_meta

                enviar_midia_whatsapp_meta(cliente_whatsapp, link_foto, barbearia)

            if not final_response_text:

                final_response_text = "Aqui está a nossa tabela! ✨"

            else:
                # Ajuste visual se ficar vazio
                if len(final_response_text) < 3:
                    final_response_text = "Enviei a tabela acima! 👆💖"

        logging.info(f"Resposta final da IA: {final_response_text}")

        return final_response_text

    except Exception as e:

        # 3. 🛡️ SEGURANÇA FINAL: Se explodir tudo, reseta o cache para não travar na próxima
        logging.error(f"Erro GRANDE ao processar com IA: {e}", exc_info=True)
        try:
            cache.delete(cache_key)
        except:
            pass
        return "Tive um problema para processar sua solicitação. Vamos tentar de novo do começo. O que você gostaria?"

def listar_servicos_pousada(barbearia_id: int) -> str:
    """
    Versão exclusiva para Pousada: Converte minutos em Diárias.
    """
    from app.models.tables import Servico # Garante importação
    try:
        servicos = Servico.query.filter_by(barbearia_id=barbearia_id).all()
        if not servicos:
            return "No momento não temos quartos cadastrados no sistema."
        
        texto = "🏨 **NOSSAS ACOMODAÇÕES E TARIFAS:**\n\n"
        
        for s in servicos:
            nome = s.nome
            preco = s.preco
            duracao_min = s.duracao
            
            # Lógica de Tradução
            if "day use" in nome.lower() or "barraca" in nome.lower():
                tipo = "🏕️ Day Use / Camping"
                detalhe = "(Uso da área externa das 08h às 18h)"
            elif duracao_min >= 1380: # 23h ou 24h
                tipo = "🛌 Diária Completa"
                detalhe = "(Check-in 12h / Check-out 16h do dia seguinte)"
            else:
                tipo = "⏳ Período Curto"
                detalhe = f"({int(duracao_min/60)} horas)"
                
            texto += f"- **{nome}**: R$ {preco:.2f}\n  _{tipo} {detalhe}_\n\n"
            
        texto += "⚠️ **Importante:**\n- Mínimo de 1 diária e meia.\n- Não aceitamos reserva para 1 pessoa só.\n- Café da manhã não incluso."
        return texto

    except Exception as e:
        return f"Erro ao listar acomodações: {str(e)}"
