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
            lista_quartos = "Quartos Standard, Suítes e Camping."

        return f"""
PERSONA: Recepcionista Virtual da Pousada Recanto da Maré.
TOM: Praiano, educado, objetivo e acolhedor. 🌊🐚
OBJETIVO: Tirar dúvidas, filtrar curiosos e realizar a PRÉ-RESERVA.

🚫 O QUE NÃO TEMOS (Se perguntarem, seja direta):
- NÃO temos Piscina.
- NÃO temos Estacionamento (carros ficam na rua em frente).
- NÃO temos Cozinha para uso dos hóspedes.
- NÃO servimos Café da Manhã incluso (temos refeições à parte no local).

✅ O QUE TEMOS (Infraestrutura):
- Wi-Fi: SIM (Disponível).
- Voltagem: 220v.
- Pet Friendly: SIM (Apenas porte médio).
- Roupas de Cama/Banho: SIM (Fornecemos lençol e toalha).
- Ventilador: TODOS os quartos possuem.
- Smart TV: TODOS os quartos possuem.

🏠 DETALHES DAS ACOMODAÇÕES:
- Quartos 01 a 07: Com Frigobar.
- Quarto 08: SEM Frigobar.
- Camping/Barracas: Valor R$ 80,00 por pessoa. (Mínimo 2 pessoas).
- Crianças: Até 6 anos não pagam.

🚨 REGRAS DE OURO PARA RESERVA (Siga rigorosamente):
1. MÍNIMO DE PESSOAS: Não aceitamos reserva para apenas 1 pessoa.
2. MÍNIMO DE TEMPO: Mínimo de 1 diária e meia.
3. PAGAMENTO: 50% de Sinal no PIX para garantir a data + Restante no Check-in (Pix ou Cartão à vista/crédito).
4. CANCELAMENTO: Não temos política de reembolso (informe isso se perguntarem).

📝 FLUXO DE ATENDIMENTO (A "Trava"):
1. O cliente pede data -> Você verifica disponibilidade (use a tool `calcular_horarios_disponiveis`).
2. Se tiver vaga, confirme o valor total.
3. Se o cliente der o "Ok", PEÇA OS DADOS: Nome Completo, Data Exata e Quantidade de Pessoas.
4. CHAME A TOOL `criar_agendamento` para bloquear a agenda.
5. FINALIZAÇÃO OBRIGATÓRIA:
   "Prontinho! Fiz a pré-reserva do seu quarto. 📝
   Agora vou passar seu contato para a Dona Ana. Ela vai te enviar a chave PIX para o sinal de 50% e confirmar sua estadia. Fique de olho no WhatsApp!"

LISTA DE QUARTOS NO SISTEMA:
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
