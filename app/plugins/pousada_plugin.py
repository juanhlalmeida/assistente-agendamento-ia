from app.plugins.base_plugin import BaseBusinessPlugin
from app.models.tables import Profissional, Agendamento, Servico
from datetime import datetime, timedelta
import pytz

class PousadaPlugin(BaseBusinessPlugin):
    """
    Plugin EXCLUSIVO para Pousada Recanto da Maré.
    - Lógica de Agendamento: DIÁRIAS (Check-in 12h / Check-out 16h).
    - 'Profissional' no banco = 'Quarto'.
    - 'Serviço' no banco = 'Pacote de Diária'.
    """

    def gerar_system_prompt(self) -> str:
        # Recupera dados básicos para injetar no prompt
        try:
            quartos = self.buscar_recursos()
            lista_quartos = "\n".join([f"- {q.nome}" for q in quartos])
        except:
            lista_quartos = "Quartos 1 a 8 e Barracas de Camping."

        return f"""
PERSONA: Recepcionista Virtual da Pousada Recanto da Maré.
TOM: Acolhedor, praiano, educado e eficiente. 🌊🐚🛌
OBJETIVO: Realizar triagem de reservas e tirar dúvidas.

🚨 REGRAS DE OURO (Check-in/Check-out):
1. Check-in: 12:00 | Check-out: 16:00.
2. NÃO fazemos reservas de apenas 1 dia. (Mínimo recomendado: Diária e meia ou Pacote Fim de Semana).
3. NÃO aceitamos reservas para 1 pessoa apenas.

💰 TABELA DE PREÇOS (Mental):
- Segunda a Quinta: R$ 300,00 a diária.
- Sexta, Sábado e Domingo: R$ 350,00 a diária.
- Aceitamos PIX e Cartão.

🏠 CONHECIMENTO DOS QUARTOS:
- Todos têm: Banheiro, Smart TV e Wi-Fi.
- Quarto 01 e 04: Têm AR CONDICIONADO ❄️ (Destaque isso!).
- Quartos 02, 03, 05, 06, 07, 08: Ventilador.
- Capacidade Padrão: 3 pessoas (exceto Quarto 4 que é beliche/4 pessoas).
- Camping: 10 Barracas disponíveis (área externa).

SUA MISSÃO (TRIAGEM):
1. O cliente pergunta.
2. Você verifica disponibilidade (use a tool `calcular_horarios_disponiveis`).
3. Se tiver vaga, você confirma os dados e diz:
   "Perfeito! Fiz a pré-reserva aqui. Vou passar para a confirmação final da gerência e já te chamo para fechar o sinal."

LISTA DE ACOMODAÇÕES NO SISTEMA:
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
        Calcula se o Quarto está livre na data solicitada.
        Regra Pousada: Bloqueia o dia inteiro (das 12h de um dia às 12h do outro).
        """
        quarto_id = kwargs.get('profissional_id') 
        duracao_minutos = kwargs.get('duracao', 1440) # Padrão 1 dia (1440 min)
        
        # Converte duração de minutos para dias (aproximado) para cálculo de range
        dias_estadia = max(1, int(duracao_minutos / 1440))

        if not quarto_id:
            return []

        # Define o horário de Check-in oficial da regra de negócio
        tz = pytz.timezone('America/Sao_Paulo')
        
        # Se a data_ref vier sem timezone, localiza
        if data_ref.tzinfo is None:
            data_ref = tz.localize(data_ref)
            
        # O cliente quer entrar neste dia às 12:00
        checkin_desejado = data_ref.replace(hour=12, minute=0, second=0)
        
        # O cliente vai sair X dias depois, às 16:00
        checkout_desejado = checkin_desejado + timedelta(days=dias_estadia)
        checkout_desejado = checkout_desejado.replace(hour=16, minute=0, second=0)

        # Busca conflitos no banco
        # Um conflito ocorre se: (NovoInicio < FimExistente) E (NovoFim > InicioExistente)
        
        reservas = Agendamento.query.filter(
            Agendamento.barbearia_id == self.business.id,
            Agendamento.profissional_id == quarto_id,
            Agendamento.data_hora >= datetime.now(tz) - timedelta(days=30) # Otimização: olha só 30 dias atrás pra frente
        ).all()

        conflito = False
        
        for reserva in reservas:
            # Data Inicio da Reserva Existente
            inicio_existente = reserva.data_hora
            if inicio_existente.tzinfo is None:
                inicio_existente = tz.localize(inicio_existente)
            
            # Data Fim da Reserva Existente (Estimada pela duração do serviço)
            duracao_reserva = reserva.servico.duracao if reserva.servico else 1440
            fim_existente = inicio_existente + timedelta(minutes=duracao_reserva)
            
            # Lógica de Colisão de Datas
            if checkin_desejado < fim_existente and checkout_desejado > inicio_existente:
                conflito = True
                break

        if conflito:
            return [] # Retorna lista vazia = Sem disponibilidade
        else:
            return [checkin_desejado] # Retorna o horário de entrada possível

    def processar_message(self, user_message, barbearia, cliente_whatsapp):
        # Este método é chamado pelo ai_service.py se necessário customizar o fluxo
        # Por enquanto, deixamos o ai_service controlar o fluxo e usamos este plugin
        # apenas para fornecer o Prompt e as Regras de Cálculo.
        pass
