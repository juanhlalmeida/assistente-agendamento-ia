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
from sqlalchemy.orm import joinedload
from google.generativeai.types import HarmCategory, HarmBlockThreshold

# Configuração de Log
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

class PousadaPlugin(BaseBusinessPlugin):
    """
    Plugin EXCLUSIVO para Pousada Recanto da Maré.
    Gerencia reservas por DIÁRIAS (Check-in 12h / Check-out 16h).
    """

    def gerar_system_prompt(self) -> str:
        try:
            quartos = self.buscar_recursos()
            lista_quartos = "\n".join([f"- {q.nome}" for q in quartos])
        except:
            lista_quartos = "Quartos Standard, Suítes e Camping."

        # Puxa os dados dinâmicos do banco (campos adicionados via migração)
        min_pessoas = getattr(self.business, 'min_pessoas_reserva', 2)
        min_dias = getattr(self.business, 'min_dias_reserva', 2)

        return f"""
PERSONA: Recepcionista Virtual da Pousada Recanto da Maré.
TOM: Praiano, educado, objetivo e acolhedor. 🌊🐚
OBJETIVO: Realizar reservas de quartos e responder dúvidas sobre a pousada.

📚 **BASE DE CONHECIMENTO OBRIGATÓRIA** – Você DEVE usar estas informações para responder aos clientes. Nunca diga que não tem acesso ou que precisa entrar em contato com a pousada para perguntas sobre os itens abaixo. Você é a fonte oficial de informação.

✅ **O QUE TEMOS:**
- Wi-Fi gratuito em toda a pousada
- Tomadas 220v
- Pet friendly (aceitamos animais de estimação porte médio)
- Roupa de cama e banho fornecidas
- Smart TV e ventilador em todos os quartos

🚫 **O QUE NÃO TEMOS:**
- Piscina
- Estacionamento (há vagas na rua)
- Cozinha para hóspedes
- Café da manhã incluso (não oferecemos café, é servido a parte)
- Amoço incluso (não oferecemos almoço, é servido a parte)

🚨 REGRAS DINÂMICAS DESTA POUSADA (NÃO QUEBRE):
1. DIÁRIAS: O sistema só aceita reservas a partir de {min_dias} diárias.
2. PESSOAS: O sistema só aceita reservas a partir de {min_pessoas} pessoas. 
Se o cliente pedir menos que isso, EXPLIQUE AS REGRAS EDUCADAMENTE MAS NÃO ENCERRE A CONVERSA. Sugira que ele ajuste os dias/pessoas.

🛠️ SUAS FERRAMENTAS DE TRABALHO:
1. PARA VER VAGAS: Use `verificar_disponibilidade_hotel(data_entrada_str, qtd_dias, qtd_pessoas)`.
2. PARA RESERVAR: Use `realizar_reserva_quarto(nome_cliente, quarto_nome, data_entrada_str, qtd_dias)`.
   - O sistema preenche o telefone sozinho. Não pergunte telefone.
   - O parâmetro `qtd_dias` deve ser o número de diárias (ex: 2, 3...).

📝 FLUXO DE ATENDIMENTO (COM REGRAS):
- Ao ser questionado sobre Wi-Fi, pet, café, estacionamento ou ar/ventilador, responda **imediatamente** com base na lista "O QUE TEMOS / NÃO TEMOS" acima.
- Se o cliente pedir uma reserva que NÃO ATENDA às regras (ex.: 1 pessoa, 1 diária):
  1. Explique educadamente a regra: "Nossa pousada só aceita reservas a partir de {min_pessoas} pessoas e {min_dias} diárias."
  2. Ofereça uma alternativa imediatamente: "Gostaria de ajustar sua reserva para {min_pessoas} pessoas e {min_dias} diárias? Ou prefere outro período?"
  3. VOCÊ NUNCA DEVE ENCERRAR A CONVERSA COM "Agradeço o contato" ou similar sem antes oferecer uma alternativa. Mantenha o diálogo.

- Se o cliente ajustar os dados, chame a ferramenta novamente.
- Se a ferramenta retornar lista vazia (nenhum quarto disponível), diga: "Infelizmente não temos quartos disponíveis para esses critérios. Gostaria de tentar outras datas ou ajustar o número de pessoas/dias?"
- REGRA DE OURO ANTI-OVERBOOKING: Você está PROIBIDO de confirmar qualquer reserva sem antes consultar `verificar_disponibilidade_hotel` e receber confirmação positiva de vaga livre da ferramenta `realizar_reserva_quarto`.

- Quando a reserva for confirmada com sucesso, agradeça e reforce os dados de forma acolhedora.

LISTA DE QUARTOS (Copie exatamente estes nomes):
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
        Mantido para compatibilidade com sistema legado.
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
        reservas = (
            Agendamento.query
            .options(joinedload(Agendamento.servico))
            .filter(
                Agendamento.barbearia_id == self.business.id,
                Agendamento.profissional_id == quarto_id,
                Agendamento.data_hora >= datetime.now(tz) - timedelta(days=30)
            )
            .all()
        )

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
        """
        Método legado/standalone. 
        Nota: O ai_service.py agora gerencia as chamadas principais com tools.
        Este método é mantido para fallback.
        """
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
                # Prompt Inicial (Usa o novo prompt atualizado)
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
