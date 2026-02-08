import logging
import os
import json
import google.generativeai as genai
from datetime import datetime, timedelta
import pytz
from flask import url_for

from app.plugins.base_plugin import BaseBusinessPlugin
from app.models.tables import Profissional, Agendamento, Servico, ChatLog
from app.extensions import db, cache
from google.generativeai.types import HarmCategory, HarmBlockThreshold

# Configuração de Log
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

class PousadaPlugin(BaseBusinessPlugin):
    """
    Plugin EXCLUSIVO para Pousada Recanto da Maré.
    Gerencia reservas por DIÁRIAS (Check-in 12h / Check-out 16h).
    """

    def gerar_system_prompt(self) -> str:
        # Tenta listar os quartos para colocar no prompt
        try:
            quartos = self.buscar_recursos()
            lista_quartos = "\n".join([f"- {q.nome}" for q in quartos])
        except:
            lista_quartos = "Quartos Standard e Suítes."

        return f"""
PERSONA: Recepcionista Virtual da Pousada Recanto da Maré.
TOM: Acolhedor, praiano, educado e eficiente. 🌊🐚🛌
OBJETIVO: Realizar triagem de reservas e tirar dúvidas.

🚨 REGRAS DE OURO (Check-in/Check-out):
1. Check-in: 12:00 | Check-out: 16:00.
2. NÃO fazemos reservas de apenas 1 dia. (Mínimo recomendado: Diária e meia ou Pacote Fim de Semana).
3. NÃO aceitamos reservas para 1 pessoa apenas.

💰 TABELA DE PREÇOS (Base):
- Segunda a Quinta: R$ 300,00 a diária.
- Sexta, Sábado e Domingo: R$ 350,00 a diária.
- Aceitamos PIX e Cartão.

🏠 CONHECIMENTO DOS QUARTOS:
- Todos têm: Banheiro, Smart TV e Wi-Fi.
- Quarto 01 e 04: Têm AR CONDICIONADO ❄️ (Destaque isso!).
- Quartos 02, 03, 05, 06, 07, 08: Ventilador.
- Camping: 10 Barracas disponíveis (área externa).

SUA MISSÃO (TRIAGEM):
1. O cliente pergunta.
2. Você verifica disponibilidade (use a tool `calcular_horarios_disponiveis`).
3. Se tiver vaga, confirme os dados e diga:
   "Perfeito! Fiz a pré-reserva. Vou passar para a gerência confirmar e já te chamo para fechar o sinal."

LISTA DE ACOMODAÇÕES:
{lista_quartos}
"""

    def buscar_recursos(self):
        """Retorna os Quartos."""
        return Profissional.query.filter_by(barbearia_id=self.business.id).all()

    def buscar_servicos(self):
        """Retorna as opções de Diária."""
        return Servico.query.filter_by(barbearia_id=self.business.id).all()

    def calcular_disponibilidade(self, data_ref: datetime, **kwargs):
        """
        Calcula se o Quarto está livre.
        Regra: Bloqueia o dia inteiro (12h às 16h do dia seguinte).
        """
        quarto_id = kwargs.get('profissional_id') 
        duracao_minutos = kwargs.get('duracao', 1440)
        
        dias_estadia = max(1, int(duracao_minutos / 1440))

        if not quarto_id:
            return []

        tz = pytz.timezone('America/Sao_Paulo')
        if data_ref.tzinfo is None:
            data_ref = tz.localize(data_ref)
            
        checkin_desejado = data_ref.replace(hour=12, minute=0, second=0)
        checkout_desejado = (checkin_desejado + timedelta(days=dias_estadia)).replace(hour=16, minute=0, second=0)

        # Busca conflitos (reservas existentes que batem com as datas)
        reservas = Agendamento.query.filter(
            Agendamento.barbearia_id == self.business.id,
            Agendamento.profissional_id == quarto_id,
            Agendamento.data_hora >= datetime.now(tz) - timedelta(days=30)
        ).all()

        for reserva in reservas:
            inicio_existente = reserva.data_hora
            if inicio_existente.tzinfo is None: inicio_existente = tz.localize(inicio_existente)
            
            duracao = reserva.servico.duracao if reserva.servico else 1440
            fim_existente = inicio_existente + timedelta(minutes=duracao)
            
            # Se as datas se cruzam
            if checkin_desejado < fim_existente and checkout_desejado > inicio_existente:
                return [] # Ocupado

        return [checkin_desejado] # Livre

    # ==========================================================
    # 🧠 O CÉREBRO QUE FALA (PROCESS_MESSAGE)
    # ==========================================================
    def process_message(self, user_message, barbearia, cliente_whatsapp):
        try:
            logging.info(f"🏨 Plugin Pousada processando msg: {user_message}")
            self.business = barbearia # Garante que o contexto da loja está setado

            # 1. Configura Gemini
            api_key = os.getenv('GEMINI_API_KEY')
            if not api_key: return "Erro: API Key não configurada."
            genai.configure(api_key=api_key)

            # 2. Histórico (Cache)
            cache_key = f"pousada_chat_{cliente_whatsapp}:{barbearia.id}"
            history = []
            cached_hist = cache.get(cache_key)
            
            if cached_hist:
                try:
                    # Reconstrói histórico simples para o Gemini
                    data = json.loads(cached_hist)
                    for item in data:
                        history.append({"role": item["role"], "parts": [item["text"]]})
                except:
                    pass
            else:
                # Prompt Inicial
                history.append({"role": "user", "parts": [self.gerar_system_prompt()]})
                history.append({"role": "model", "parts": [f"Olá! Bem-vindo(a) à {barbearia.nome_fantasia}. Como posso ajudar sua estadia?"]})

            # 3. Gera Resposta
            model = genai.GenerativeModel('gemini-1.5-flash')
            chat = model.start_chat(history=history)
            
            response = chat.send_message(user_message)
            resposta_texto = response.text

            # 4. Salva Histórico Atualizado
            new_history_data = []
            for content in chat.history:
                # Salva apenas texto simples para economizar e evitar erros de serialização complexa
                role = content.role
                text = content.parts[0].text if content.parts else ""
                new_history_data.append({"role": role, "text": text})
            
            cache.set(cache_key, json.dumps(new_history_data), timeout=3600) # 1 hora de memória

            # 5. Salva Log no Banco (Opcional)
            try:
                log = ChatLog(
                    barbearia_id=barbearia.id,
                    cliente_telefone=cliente_whatsapp,
                    mensagem_usuario=user_message,
                    mensagem_ia=resposta_texto,
                    data_hora=datetime.now()
                )
                db.session.add(log)
                db.session.commit()
            except Exception as e_db:
                logging.error(f"Erro ao salvar log: {e_db}")

            return resposta_texto

        except Exception as e:
            logging.error(f"❌ Erro no Plugin Pousada: {e}", exc_info=True)
            return "Desculpe, nossa recepção está verificando a disponibilidade. Tente novamente em instantes. 🏨"
