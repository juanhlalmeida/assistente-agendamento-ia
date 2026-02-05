from app.plugins.base_plugin import BaseBusinessPlugin
from app.models.tables import Profissional, Agendamento, Servico
from datetime import datetime, timedelta, time
import pytz

class PousadaPlugin(BaseBusinessPlugin):
    """
    Plugin específico para Hotelaria/Pousadas.
    - 'Profissional' vira 'Quarto/Acomodação'.
    - 'Serviço' vira 'Tipo de Diária/Pacote'.
    - Agendamento é por DIAS (Check-in/Check-out), não por minutos.
    """

    def gerar_system_prompt(self) -> str:
        return """
PERSONA: Recepcionista Virtual da Pousada.
TOM: Acolhedor, calmo, sofisticado e prestativo. Use emojis de viagem/natureza: 🌿 🛏️ 🏖️ ☕

OBJETIVO: Vender diárias e tirar dúvidas sobre a estadia.

VOCABULÁRIO OBRIGATÓRIO (Tradução Mental):
- Se o sistema mostrar "Profissional", você lê "QUARTO" ou "SUÍTE".
- Se o sistema mostrar "Serviço", você lê "PACOTE" ou "DIÁRIA".
- Não existe "Horário marcado", existe "RESERVA".

REGRAS DE NEGÓCIO:
1. SEMPRE pergunte a Data de Chegada (Check-in) e Data de Saída (Check-out) ou quantidade de noites.
2. Não agendamos por "hora". A diária começa geralmente às 14h e termina às 12h (padrão hoteleiro).
3. Se o cliente perguntar "Tem vaga?", use a ferramenta de calcular disponibilidade passando as datas.

AO CONFIRMAR:
"Sua reserva na [Nome da Suíte] para os dias X a Y está pré-confirmada! 🌿"
"""

    def buscar_recursos(self):
        """Retorna os Quartos (cadastrados como Profissionais no banco atual)"""
        # Dica: No front-end futuro, mudaremos o label para 'Acomodações'
        return Profissional.query.filter_by(barbearia_id=self.business.id).all()

    def buscar_servicos(self):
        """Retorna os Pacotes/Diárias"""
        return Servico.query.filter_by(barbearia_id=self.business.id).all()

    def calcular_disponibilidade(self, data_ref: datetime, **kwargs):
        """
        Verifica se o QUARTO está livre nas datas solicitadas.
        OBS: Aqui a lógica é verificar colisão de DATAS, não de horas.
        """
        quarto_id = kwargs.get('profissional_id') # Profissional = Quarto
        dias_estadia = kwargs.get('duracao', 1) # No caso de pousada, duração = dias
        
        # Se duracao vier em minutos (padrão do sistema antigo), converte para dias
        if dias_estadia > 30: 
            dias_estadia = 1 # Proteção contra "60 minutos" virar "60 dias"

        if not quarto_id:
            return []

        sao_paulo_tz = pytz.timezone('America/Sao_Paulo')
        checkin_desejado = data_ref.replace(hour=14, minute=0, second=0) # Check-in padrão 14h
        checkout_desejado = checkin_desejado + timedelta(days=dias_estadia)

        # Busca reservas existentes que colidam com esse período
        # Lógica de Colisão: (InicioA < FimB) e (FimA > InicioB)
        
        reservas_existentes = Agendamento.query.filter(
            Agendamento.barbearia_id == self.business.id,
            Agendamento.profissional_id == quarto_id,
            Agendamento.data_hora < checkout_desejado, # Começou antes do meu checkout
            # Precisaríamos da data fim no banco, mas por enquanto usamos a duração do serviço
        ).all()

        # Verificação Simplificada (MVP):
        # Se tiver QUALQUER agendamento no dia do check-in, consideramos o dia ocupado.
        # (No futuro, faremos uma verificação mais robusta com data de saída exata)
        
        for reserva in reservas_existentes:
            # Assume que cada agendamento bloqueia o dia inteiro
            dia_reserva = reserva.data_hora.date()
            
            # Se a reserva cai em qualquer dia do intervalo desejado
            cursor = checkin_desejado.date()
            while cursor < checkout_desejado.date():
                if cursor == dia_reserva:
                    return [] # Ocupado!
                cursor += timedelta(days=1)

        # Se passou limpo, retorna o horário de check-in como "disponível"
        return [checkin_desejado]
