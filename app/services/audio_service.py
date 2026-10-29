# app/services/audio_service.py
# (CÓDIGO CORRIGIDO: USA A CHAVE 'GEMINI_API_KEY' CORRETA)

import os
import time
import requests
import tempfile
import logging
import google.generativeai as genai
import json
from time import sleep
from flask import current_app
from datetime import datetime, timedelta
import pytz

# --- IMPORTAÇÕES ESSENCIAIS ---
from app.extensions import cache, db
from app.models.tables import Agendamento, Profissional, Servico, Barbearia
from google.generativeai.protos import Content, Part, FunctionCall, FunctionResponse
from google.generativeai import protos
from google.generativeai.types import FunctionDeclaration, Tool, GenerationConfig
from thefuzz import process 
from app.utils import calcular_horarios_disponiveis as calcular_horarios_disponiveis_util
from app.utils.plugin_loader import carregar_plugin_negocio

# Configuração de Logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
BR_TZ = pytz.timezone('America/Sao_Paulo')

# --- PROMPT RIGOROSO ---
SYSTEM_INSTRUCTION_TEMPLATE = """
PERSONA: Luana, assistente da {barbearia_nome}.
OBJETIVO: Agendamentos. Foco 100%.
TOM: Simpática, breve, objetiva, emojis (✂️✨😉👍).
ID_CLIENTE: {cliente_whatsapp} | BARBEARIA_ID: {barbearia_id}
HOJE: {data_de_hoje} | AMANHÃ: {data_de_amanha}

🚨 REGRA DE OURO:
VOCÊ É PROIBIDA DE DIZER "AGENDADO" SE NÃO TIVER CHAMADO A FERRAMENTA `criar_agendamento` COM SUCESSO.
Se você apenas falar "Ok, marquei" sem chamar a tool, o agendamento falha.

🚨 REGRA ESTRITA DE MENSAGENS CURTAS E ATENDIMENTO:
- Responda SEMPRE em no máximo 2 a 3 frases curtas.
- NUNCA envie a lista completa de 12 serviços de uma vez quando a cliente pedir para agendar: pergunte primeiro se é colocação ou manutenção e qual modelo ela prefere.
- Ofereça no máximo 2 a 3 opções de horário por vez.

🚨 REGRA DE OURO ESTRITA: VOCÊ ESTÁ TERMINANTEMENTE PROIBIDO DE INVENTAR OU LISTAR QUALQUER SERVIÇO, PREÇO OU DURAÇÃO QUE NÃO TENHA SIDO EXPRESSAMENTE RETORNADO PELA FERRAMENTA/FUNÇÃO DE CONSULTA AO BANCO DE DADOS. SE A FUNÇÃO FALHAR, DIGA APENAS QUE ESTÁ VERIFICANDO O SISTEMA. NUNCA USE SEU CONHECIMENTO GERAL PARA COMPLETAR LISTAS DE ESTÉTICA OU BARBEARIA.
- Sempre que o cliente mencionar "serviço", "valor" ou enviar continuações de contexto (como "?"), CHAME OBRIGATORIAMENTE a ferramenta `listar_servicos`.

🧠 TRADUÇÃO DE SERVIÇOS:
- Cliente disse "Barba"? -> Use o nome oficial (ex: "Barba Terapia").
- Cliente disse "Corte"? -> Use o nome oficial (ex: "Corte Social").

FLUXO OBRIGATÓRIO:
1. Entendeu o áudio? -> Verifique: [Serviço], [Profissional], [Data], [Hora].
2. Tem tudo? -> CHAME `criar_agendamento` IMEDIATAMENTE.
3. Falta algo? -> Pergunte.

CANCELAMENTO: Use cancelar_agendamento_por_telefone(dia="AAAA-MM-DD")
"""

# --- FERRAMENTAS ---

def encontrar_melhor_match(termo, lista, cutoff=60):
    if not termo or not lista: return None
    melhor, score = process.extractOne(termo, lista)
    return melhor if score >= cutoff else None

def listar_profissionais(barbearia_id: int) -> str:
    profs = Profissional.query.filter_by(barbearia_id=barbearia_id).all()
    if not profs: return "Nenhum profissional."
    return f"Profissionais: {', '.join([p.nome for p in profs])}."

def listar_servicos(barbearia_id: int) -> str:
    servs = Servico.query.filter(
        Servico.barbearia_id == barbearia_id,
        Servico.nome != "Bloqueio Administrativo"
    ).all()
    if not servs: return "Nenhum serviço."
    lista = [f"{s.nome} (R$ {s.preco})" for s in servs]
    return f"Serviços (USE EXCLUSIVAMENTE ESTES DO BANCO DE DADOS - PROIBIDO INVENTAR OUTROS): {'; '.join(lista)}."

def calcular_horarios_disponiveis(barbearia_id: int, profissional_nome: str, dia: str, servico_nome: str = None) -> str:
    barbearia = Barbearia.query.get(barbearia_id)
    try:
        plugin = carregar_plugin_negocio(barbearia) if barbearia else None
        profs = plugin.buscar_recursos() if plugin else Profissional.query.filter_by(barbearia_id=barbearia_id).all()
    except Exception as e_plug:
        logger.warning(f"⚠️ Falha ao carregar plugin (áudio), usando busca direta: {e_plug}")
        plugin = None
        profs = Profissional.query.filter_by(barbearia_id=barbearia_id).all()
    match = encontrar_melhor_match(profissional_nome, [p.nome for p in profs])
    if not match: return "Profissional não encontrado."
    profissional = next(p for p in profs if p.nome == match)
    
    agora_br = datetime.now(BR_TZ)
    if dia.lower() == 'hoje':
        dia_dt = agora_br
    elif dia.lower() == 'amanhã':
        dia_dt = agora_br + timedelta(days=1)
    else:
        try:
            dia_dt = BR_TZ.localize(datetime.strptime(dia, '%Y-%m-%d'))
        except Exception:
            return "Data inválida. Use 'hoje', 'amanhã' ou AAAA-MM-DD."

    duracao_calculo = 60
    if servico_nome:
        servs = plugin.buscar_servicos() if plugin else Servico.query.filter_by(barbearia_id=barbearia_id).all()
        serv_match = encontrar_melhor_match(servico_nome, [s.nome for s in servs])
        if serv_match:
            servico = next(s for s in servs if s.nome == serv_match)
            duracao_calculo = servico.duracao

    horarios = None
    for tentativa in range(2):
        try:
            horarios = plugin.calcular_disponibilidade(
                data_ref=dia_dt,
                profissional_id=profissional.id,
                duracao=duracao_calculo
            )
            break
        except Exception as e_tentativa:
            logger.warning(f"⚠️ Tentativa {tentativa + 1}/2 falhou em plugin.calcular_disponibilidade (áudio): {e_tentativa}")
            if tentativa < 1:
                time.sleep(0.5)
            else:
                logger.warning("🔄 Acionando fallback calcular_horarios_disponiveis de app.utils (áudio)")
                horarios = calcular_horarios_disponiveis_util(
                    profissional=profissional,
                    dia_selecionado=dia_dt,
                    duracao=duracao_calculo
                )

    if not horarios:
        sugestoes = []
        for offset in range(1, 4):
            prox_dia = dia_dt + timedelta(days=offset)
            h_prox = None
            for tentativa in range(2):
                try:
                    h_prox = plugin.calcular_disponibilidade(
                        data_ref=prox_dia,
                        profissional_id=profissional.id,
                        duracao=duracao_calculo
                    )
                    break
                except Exception:
                    if tentativa < 1:
                        time.sleep(0.5)
                    else:
                        h_prox = calcular_horarios_disponiveis_util(
                            profissional=profissional,
                            dia_selecionado=prox_dia,
                            duracao=duracao_calculo
                        )
            if h_prox:
                lista_p = [h.strftime('%H:%M') for h in h_prox[:3]]
                sugestoes.append(f"Dia {prox_dia.strftime('%d/%m')}: {', '.join(lista_p)}")
                if len(sugestoes) >= 2:
                    break

        msg_retorno = f"❌ Sem horários livres para {match} em {dia_dt.strftime('%d/%m')}."
        if sugestoes:
            msg_retorno += f" Mas encontrei estas vagas próximas: {'; '.join(sugestoes)}."
        return msg_retorno

    return f"Vagas para {match} em {dia_dt.strftime('%d/%m')}: {', '.join([h.strftime('%H:%M') for h in horarios])}."

def criar_agendamento(barbearia_id: int, nome_cliente: str, telefone_cliente: str, data_hora: str, profissional_nome: str, servico_nome: str) -> str:
    # Profissional
    profs = Profissional.query.filter_by(barbearia_id=barbearia_id).all()
    prof_match = encontrar_melhor_match(profissional_nome, [p.nome for p in profs])
    if not prof_match: return "Profissional não encontrado."
    profissional = next(p for p in profs if p.nome == prof_match)
    
    # Serviço
    servs = Servico.query.filter_by(barbearia_id=barbearia_id).all()
    serv_match = encontrar_melhor_match(servico_nome, [s.nome for s in servs])
    if not serv_match: return f"Serviço não encontrado. Opções: {', '.join([s.nome for s in servs])}"
    servico = next(s for s in servs if s.nome == serv_match)
    
    dt_obj = datetime.strptime(data_hora, '%Y-%m-%d %H:%M').replace(tzinfo=None)
    
    # Salvar
    novo = Agendamento(nome_cliente=nome_cliente, telefone_cliente=telefone_cliente, data_hora=dt_obj, profissional_id=profissional.id, servico_id=servico.id, barbearia_id=barbearia_id)
    db.session.add(novo)
    db.session.commit()
    return f"SUCESSO: Agendado {servico.nome} com {profissional.nome} dia {data_hora}."

def cancelar_agendamento_por_telefone(barbearia_id: int, telefone_cliente: str, dia: str) -> str:
    dt = datetime.strptime(dia, '%Y-%m-%d').date()
    ags = Agendamento.query.filter(Agendamento.barbearia_id==barbearia_id, Agendamento.telefone_cliente==telefone_cliente, Agendamento.data_hora >= datetime.combine(dt, datetime.min.time())).all()
    if not ags: return "Nada agendado."
    for a in ags: db.session.delete(a)
    db.session.commit()
    return "Cancelado com sucesso."

# Definição das Tools
tools_list = Tool(function_declarations=[
    FunctionDeclaration(name="listar_profissionais", description="Lista equipe", parameters={"type": "object", "properties": {}}),
    FunctionDeclaration(name="listar_servicos", description="Lista todos os serviços e valores reais do banco de dados. OBRIGATÓRIO chamar sempre que o cliente falar 'serviço', 'valor', 'preço' ou enviar continuações de contexto como '?'.", parameters={"type": "object", "properties": {}}),
    FunctionDeclaration(name="calcular_horarios_disponiveis", description="Vê vagas", parameters={"type": "object", "properties": {"profissional_nome": {"type": "string"}, "dia": {"type": "string"}}, "required": ["profissional_nome", "dia"]}),
    FunctionDeclaration(name="criar_agendamento", description="Cria agendamento", parameters={"type": "object", "properties": {"nome_cliente": {"type": "string"}, "data_hora": {"type": "string"}, "profissional_nome": {"type": "string"}, "servico_nome": {"type": "string"}}, "required": ["nome_cliente", "data_hora", "profissional_nome", "servico_nome"]}),
    FunctionDeclaration(name="cancelar_agendamento_por_telefone", description="Cancela", parameters={"type": "object", "properties": {"dia": {"type": "string"}}, "required": ["dia"]})
])

class AudioService:
    def __init__(self):
        # 🔥 CORREÇÃO AQUI: Usar 'GEMINI_API_KEY' que é a que existe no Render
        self.google_api_key = os.getenv('GEMINI_API_KEY') 
        
        if not self.google_api_key: 
            logger.error("GEMINI_API_KEY ausente! Áudio não funcionará.")
        else:
            genai.configure(api_key=self.google_api_key)

    def processar_audio(self, audio_id, access_token, wa_id, barbearia_id, app):
        """
        Processa áudio, mantém memória e EXECUTA TOOLS.
        """
        caminho_arquivo = None
        arquivo_remoto = None
        cache_key = f"chat_history_{wa_id}:{barbearia_id}"
        
        # Contexto para o Banco de Dados
        with app.app_context():
            try:
                # 1. Download e Upload do Áudio
                url = self._get_url(audio_id, access_token)
                binary = self._get_binary(url, access_token)
                
                with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tf:
                    tf.write(binary)
                    caminho_arquivo = tf.name
                
                arquivo_remoto = genai.upload_file(caminho_arquivo, mime_type="audio/ogg")
                while arquivo_remoto.state.name == "PROCESSING":
                    sleep(1)
                    arquivo_remoto = genai.get_file(arquivo_remoto.name)

                # 2. Recuperar Memória
                barbearia = Barbearia.query.get(barbearia_id)
                history = self._deserialize_history(cache.get(cache_key))
                agora = datetime.now(BR_TZ)
                
                if not history:
                    prompt = SYSTEM_INSTRUCTION_TEMPLATE.format(
                        barbearia_nome=barbearia.nome_fantasia, cliente_whatsapp=wa_id, barbearia_id=barbearia_id,
                        data_de_hoje=agora.strftime('%Y-%m-%d'), data_de_amanha=(agora+timedelta(days=1)).strftime('%Y-%m-%d')
                    )
                    history = [Content(role='user', parts=[protos.Part(text=prompt)]), Content(role='model', parts=[protos.Part(text="Olá!")])]

                # 3. Inicializar Modelo
                model = genai.GenerativeModel(
                    "gemini-2.5-flash", 
                    tools=[tools_list], 
                    generation_config=GenerationConfig(temperature=0.0)
                )
                chat = model.start_chat(history=history)
                
                # 4. Enviar Áudio
                response = chat.send_message([
                    "Analise este áudio. Se tiver dados para agendar, CHAME A TOOL criar_agendamento.", 
                    arquivo_remoto
                ])
                
                # 5. Loop de Ferramentas
                while response.candidates and response.candidates[0].content.parts and response.candidates[0].content.parts[0].function_call:
                    fc = response.candidates[0].content.parts[0].function_call
                    fname = fc.name
                    fargs = dict(fc.args)
                    logger.info(f"🎤 Áudio Tool Call: {fname} {fargs}")
                    
                    tool_map = {
                        "listar_profissionais": listar_profissionais, "listar_servicos": listar_servicos,
                        "calcular_horarios_disponiveis": calcular_horarios_disponiveis, "criar_agendamento": criar_agendamento,
                        "cancelar_agendamento_por_telefone": cancelar_agendamento_por_telefone
                    }
                    
                    if fname in tool_map:
                        fargs['barbearia_id'] = barbearia_id
                        if 'telefone_cliente' in fargs or fname in ['criar_agendamento', 'cancelar_agendamento_por_telefone']:
                            fargs['telefone_cliente'] = wa_id
                        
                        res = tool_map[fname](**fargs)
                        response = chat.send_message(protos.Part(function_response=protos.FunctionResponse(name=fname, response={"result": res})))
                    else:
                        response = chat.send_message(protos.Part(function_response=protos.FunctionResponse(name=fname, response={"error": "Tool not found"})))

                # 6. Salvar
                cache.set(cache_key, self._serialize_history(chat.history))
                
                if response.candidates and response.candidates[0].content.parts:
                    return response.candidates[0].content.parts[0].text
                return "Processado."

            except Exception as e:
                logger.error(f"Erro Áudio: {e}")
                return "Desculpe, não entendi o áudio."
            finally:
                if caminho_arquivo and os.path.exists(caminho_arquivo): os.remove(caminho_arquivo)
                if arquivo_remoto: 
                    try: genai.delete_file(arquivo_remoto.name)
                    except: pass

    def _get_url(self, mid, token):
        r = requests.get(f"https://graph.facebook.com/v19.0/{mid}", headers={"Authorization": f"Bearer {token}"})
        r.raise_for_status(); return r.json()['url']
    
    def _get_binary(self, url, token):
        r = requests.get(url, headers={"Authorization": f"Bearer {token}"})
        r.raise_for_status(); return r.content

    def _serialize_history(self, hist):
        res = []
        for c in hist:
            parts = []
            for p in c.parts:
                if p.text: parts.append({'text': p.text})
                elif p.function_call: parts.append({'function_call': protos.FunctionCall.to_dict(p.function_call)})
                elif p.function_response: parts.append({'function_response': protos.FunctionResponse.to_dict(p.function_response)})
            res.append({'role': c.role, 'parts': parts})
        return json.dumps(res)

    def _deserialize_history(self, j):
        if not j: return []
        try:
            h = []
            for i in json.loads(j):
                parts = []
                for p in i.get('parts', []):
                    if 'text' in p: parts.append(protos.Part(text=p['text']))
                    elif 'function_call' in p: parts.append(protos.Part(function_call=protos.FunctionCall(p['function_call'])))
                    elif 'function_response' in p: parts.append(protos.Part(function_response=protos.FunctionResponse(p['function_response'])))
                h.append(Content(role=i['role'], parts=parts))
            return h
        except: return []
