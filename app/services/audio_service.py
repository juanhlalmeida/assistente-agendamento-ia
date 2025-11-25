# app/services/audio_service.py
# (CÓDIGO COMPLETO - AGORA COM EXECUÇÃO REAL DE FERRAMENTAS PARA NÃO ALUCINAR)

import os
import requests
import tempfile
import logging
import google.generativeai as genai
import json
from time import sleep
from flask import current_app
from datetime import datetime, timedelta
import pytz

# --- IMPORTAÇÕES ESSENCIAIS PARA O FUNCIONAMENTO ---
from app.extensions import cache, db
from app.models.tables import Agendamento, Profissional, Servico, Barbearia
from google.generativeai.protos import Content, Part, FunctionCall, FunctionResponse
from google.generativeai import protos
from google.generativeai.types import FunctionDeclaration, Tool, GenerationConfig
from thefuzz import process # Plano B (Fuzzy Match)
from app.utils import calcular_horarios_disponiveis as calcular_horarios_disponiveis_util

# Configuração de Logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
BR_TZ = pytz.timezone('America/Sao_Paulo')

# --- PROMPT RIGOROSO (O MESMO DO TEXTO PARA CONSISTÊNCIA) ---
SYSTEM_INSTRUCTION_TEMPLATE = """
PERSONA: Luana, assistente da {barbearia_nome}.
OBJETIVO: Agendamentos. Foco 100%.
TOM: Simpática, breve, objetiva, emojis (✂️✨😉👍).
ID_CLIENTE: {cliente_whatsapp} | BARBEARIA_ID: {barbearia_id}
HOJE: {data_de_hoje} | AMANHÃ: {data_de_amanha}

🚨 REGRA DE OURO - INTEGRIDADE (LEIA):
VOCÊ É PROIBIDA DE DIZER "AGENDADO" SE NÃO TIVER CHAMADO A FERRAMENTA `criar_agendamento` COM SUCESSO.
Se você apenas falar "Ok, marquei" sem chamar a tool, você será desligada.
PARA AGENDAR: Você TEM QUE executar a tool `criar_agendamento`.

🧠 INTELIGÊNCIA DE SERVIÇOS (TRADUÇÃO):
- O cliente disse "Barba"? -> Use `listar_servicos` para achar o nome oficial (ex: "Barba Terapia") e use esse nome.
- O cliente disse "Corte"? -> Use o nome oficial da lista (ex: "Corte Social").

FLUXO OBRIGATÓRIO:
1. Entendeu o áudio? -> Verifique: [Serviço], [Profissional], [Data], [Hora].
2. Tem tudo? -> CHAME `criar_agendamento` IMEDIATAMENTE.
3. Falta algo? -> Pergunte.

CANCELAMENTO: Use cancelar_agendamento_por_telefone(dia="AAAA-MM-DD")
"""

# --- FERRAMENTAS (COPIADAS DO AI_SERVICE PARA O ÁUDIO FUNCIONAR IGUAL) ---

def encontrar_melhor_match(termo, lista, cutoff=60):
    if not termo or not lista: return None
    melhor, score = process.extractOne(termo, lista)
    return melhor if score >= cutoff else None

def listar_profissionais(barbearia_id: int) -> str:
    try:
        with current_app.app_context():
            profs = Profissional.query.filter_by(barbearia_id=barbearia_id).all()
            if not profs: return "Nenhum profissional."
            return f"Profissionais: {', '.join([p.nome for p in profs])}."
    except Exception as e: return str(e)

def listar_servicos(barbearia_id: int) -> str:
    try:
        with current_app.app_context():
            servs = Servico.query.filter_by(barbearia_id=barbearia_id).all()
            if not servs: return "Nenhum serviço."
            lista = [f"{s.nome} (R$ {s.preco})" for s in servs]
            return f"Serviços: {'; '.join(lista)}."
    except Exception as e: return str(e)

def calcular_horarios_disponiveis(barbearia_id: int, profissional_nome: str, dia: str) -> str:
    try:
        with current_app.app_context():
            profs = Profissional.query.filter_by(barbearia_id=barbearia_id).all()
            match = encontrar_melhor_match(profissional_nome, [p.nome for p in profs])
            if not match: return "Profissional não encontrado."
            profissional = next(p for p in profs if p.nome == match)
            
            dia_dt = datetime.now(BR_TZ) if dia == 'hoje' else (datetime.now(BR_TZ) + timedelta(days=1) if dia == 'amanhã' else BR_TZ.localize(datetime.strptime(dia, '%Y-%m-%d')))
            
            horarios = calcular_horarios_disponiveis_util(profissional, dia_dt)
            return f"Vagas para {match} em {dia_dt.strftime('%d/%m')}: {', '.join([h.strftime('%H:%M') for h in horarios])}."
    except Exception: return "Erro ao ver horários."

def criar_agendamento(barbearia_id: int, nome_cliente: str, telefone_cliente: str, data_hora: str, profissional_nome: str, servico_nome: str) -> str:
    try:
        with current_app.app_context():
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
    except Exception as e:
        db.session.rollback()
        return f"Erro técnico: {e}"

def cancelar_agendamento_por_telefone(barbearia_id: int, telefone_cliente: str, dia: str) -> str:
    try:
        with current_app.app_context():
            dt = datetime.strptime(dia, '%Y-%m-%d').date()
            ags = Agendamento.query.filter(Agendamento.barbearia_id==barbearia_id, Agendamento.telefone_cliente==telefone_cliente, Agendamento.data_hora >= datetime.combine(dt, datetime.min.time())).all()
            if not ags: return "Nada agendado."
            for a in ags: db.session.delete(a)
            db.session.commit()
            return "Cancelado com sucesso."
    except: return "Erro ao cancelar."

# Definição das Tools para o Gemini
tools_list = Tool(function_declarations=[
    FunctionDeclaration(name="listar_profissionais", description="Lista equipe", parameters={"type": "object", "properties": {}}),
    FunctionDeclaration(name="listar_servicos", description="Lista serviços", parameters={"type": "object", "properties": {}}),
    FunctionDeclaration(name="calcular_horarios_disponiveis", description="Vê vagas", parameters={"type": "object", "properties": {"profissional_nome": {"type": "string"}, "dia": {"type": "string"}}, "required": ["profissional_nome", "dia"]}),
    FunctionDeclaration(name="criar_agendamento", description="Cria agendamento", parameters={"type": "object", "properties": {"nome_cliente": {"type": "string"}, "data_hora": {"type": "string"}, "profissional_nome": {"type": "string"}, "servico_nome": {"type": "string"}}, "required": ["nome_cliente", "data_hora", "profissional_nome", "servico_nome"]}),
    FunctionDeclaration(name="cancelar_agendamento_por_telefone", description="Cancela", parameters={"type": "object", "properties": {"dia": {"type": "string"}}, "required": ["dia"]})
])

class AudioService:
    def __init__(self):
        self.google_api_key = os.getenv('GOOGLE_API_KEY')
        if not self.google_api_key: logger.error("GOOGLE_API_KEY ausente!")
        genai.configure(api_key=self.google_api_key)

    def processar_audio(self, audio_id, access_token, wa_id, barbearia_id):
        """Processa áudio, mantém memória e EXECUTA TOOLS."""
        caminho_arquivo = None
        arquivo_remoto = None
        cache_key = f"chat_history_{wa_id}:{barbearia_id}"
        
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

            # 3. Inicializar Modelo com Tools (AQUI ESTAVA O ERRO ANTES - FALTAVAM AS TOOLS)
            model = genai.GenerativeModel(
                "gemini-2.5-flash", 
                tools=[tools_list], 
                generation_config=GenerationConfig(temperature=0.0)
            )
            chat = model.start_chat(history=history)
            
            # 4. Enviar Áudio + Instrução de Execução
            response = chat.send_message([
                "Analise este áudio. Se o cliente pediu agendamento e você tem os dados, CHAME A TOOL criar_agendamento AGORA.", 
                arquivo_remoto
            ])
            
            # 5. LOOP DE EXECUÇÃO DE FERRAMENTAS (O GRANDE SEGREDO QUE FALTAVA)
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
                    # Envia o resultado da ferramenta de volta para a IA
                    response = chat.send_message(protos.Part(function_response=protos.FunctionResponse(name=fname, response={"result": res})))
                else:
                    response = chat.send_message(protos.Part(function_response=protos.FunctionResponse(name=fname, response={"error": "Tool not found"})))

            # 6. Salvar Memória e Retornar
            cache.set(cache_key, self._serialize_history(chat.history))
            
            if response.candidates and response.candidates[0].content.parts:
                return response.candidates[0].content.parts[0].text
            return "Agendamento processado."

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
