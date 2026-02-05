from app.plugins.base_plugin import BaseBusinessPlugin
from app.models.tables import Profissional, Agendamento, Servico
from datetime import datetime, time, timedelta
import pytz
from sqlalchemy.orm import joinedload

class BarbershopPlugin(BaseBusinessPlugin):
    """
    Plugin responsável pela lógica de Barbearias e Studios (Agendamento por Slots/Minutos).
    Contém as regras da Carol Lash (Horários mistos e Almoço).
    """

    def gerar_system_prompt(self) -> str:
        # Retornaremos o prompt específico no próximo passo (integrando com ai_service)
        return "PROMPT_BARBEARIA"

    def buscar_recursos(self):
        """Retorna os Profissionais da loja"""
        return Profissional.query.filter_by(barbearia_id=self.business.id).all()

    def buscar_servicos(self):
        """Retorna os Serviços da loja"""
        return Servico.query.filter_by(barbearia_id=self.business.id).all()

    def calcular_disponibilidade(self, data_ref: datetime, **kwargs):
        """
        Lógica de cálculo de horários (Migrada do utils.py).
        Esperamos kwargs: 'profissional_id' e 'duracao'
        """
        profissional_id = kwargs.get('profissional_id')
        duracao = kwargs.get('duracao', 30)

        # Se não passar o profissional (ex: busca geral), pegamos o primeiro (fallback)
        if isinstance(profissional_id, Profissional):
            profissional = profissional_id
        else:
            profissional = Profissional.query.get(profissional_id)
            
        if not profissional:
            return []

        # --- AQUI COMEÇA A LÓGICA QUE CONSERTAMOS HOJE ---
        sao_paulo_tz = pytz.timezone('America/Sao_Paulo')
        agora = datetime.now(sao_paulo_tz)
        
        # 🛑 TRAVA DE PASSADO
        if data_ref.date() < agora.date():
            return [] 

        barbearia = self.business
        
        # Configurações
        h_abre_str = getattr(barbearia, 'horario_abertura', '09:00') or '09:00'
        h_fecha_padrao = getattr(barbearia, 'horario_fechamento', '19:00') or '19:00'
        h_fecha_sabado = getattr(barbearia, 'horario_fechamento_sabado', '14:00') or '14:00'
        dias_func_str = getattr(barbearia, 'dias_funcionamento', 'Terça a Sábado')

        dia_semana_int = data_ref.weekday()
        dia_aberto = False
        h_fecha_str = h_fecha_padrao 

        # --- LÓGICA ESPECIAL CAROL LASH ---
        eh_carol = 'Carol' in dias_func_str

        # CENÁRIO 1: CAROL MISTO
        if dias_func_str == 'Carol: Terça a Sábado (Misto)':
            if dia_semana_int in [1, 2, 3, 4, 5]: 
                dia_aberto = True
                if dia_semana_int == 5: h_fecha_str = h_fecha_sabado
                elif dia_semana_int in [1, 3]: h_fecha_str = '22:00' # Ter/Qui até 22h (pra caber 20:30)
                elif dia_semana_int in [2, 4]: h_fecha_str = '19:00' # Qua/Sex até 19h (pra caber 17:30)

        # CENÁRIO 2: CAROL SEMANA CURSO
        elif dias_func_str == 'Carol: Segunda a Sexta (Misto)':
            if dia_semana_int in [0, 1, 2, 3, 4]:
                dia_aberto = True
                if dia_semana_int in [1, 3]: h_fecha_str = '22:00'
                else: h_fecha_str = '19:00'

        # CENÁRIO 3: PADRÃO
        else:
            dias_lower = dias_func_str.lower()
            if 'segunda a sexta' in dias_lower and dia_semana_int < 5: dia_aberto = True
            elif 'segunda a sábado' in dias_lower and dia_semana_int < 6:
                dia_aberto = True
                if dia_semana_int == 5: h_fecha_str = h_fecha_sabado
            elif 'terça a sábado' in dias_lower and 0 < dia_semana_int < 6:
                dia_aberto = True
                if dia_semana_int == 5: h_fecha_str = h_fecha_sabado
            elif 'terça a sexta' in dias_lower and 0 < dia_semana_int < 5: dia_aberto = True
            
            # Travas extras
            if dia_semana_int == 5 and 'sábado' not in dias_lower and 'sabado' not in dias_lower: dia_aberto = False
            if dia_semana_int == 6 and 'domingo' not in dias_lower: dia_aberto = False
            if dia_semana_int == 0 and 'segunda' not in dias_lower: dia_aberto = False

        if not dia_aberto:
            return []

        # Cálculo Matemático
        try:
            h_inicio, m_inicio = map(int, h_abre_str.split(':'))
            h_fim, m_fim = map(int, h_fecha_str.split(':'))
        except:
            h_inicio, m_inicio = 9, 0
            h_fim, m_fim = 19, 0

        INTERVALO_MINUTOS = 30 
        horarios_disponiveis = []

        dia_base = datetime.combine(data_ref.date(), time.min) 
        
        try:
            horario_iteracao = sao_paulo_tz.localize(dia_base.replace(hour=h_inicio, minute=m_inicio), is_dst=None)
            fim_do_dia = sao_paulo_tz.localize(dia_base.replace(hour=h_fim, minute=m_fim), is_dst=None)
            
            # BLOQUEIO DE ALMOÇO (CAROL)
            almoco_inicio = None
            almoco_fim = None
            if eh_carol:
                almoco_inicio = sao_paulo_tz.localize(dia_base.replace(hour=12, minute=0), is_dst=None)
                almoco_fim = sao_paulo_tz.localize(dia_base.replace(hour=13, minute=0), is_dst=None)

            # Busca no Banco
            inicio_query = dia_base.replace(hour=0, minute=0, second=0, microsecond=0)
            fim_query = inicio_query + timedelta(days=1)
            
            agendamentos_do_dia = (
                Agendamento.query
                .options(joinedload(Agendamento.servico))
                .filter(
                    Agendamento.barbearia_id == barbearia.id,
                    Agendamento.profissional_id == profissional.id,
                    Agendamento.data_hora >= inicio_query, 
                    Agendamento.data_hora < fim_query 
                )
                .all()
            )
            
            intervalos_ocupados = []
            for ag in agendamentos_do_dia:
                duracao_ag = ag.servico.duracao if ag.servico else 30
                inicio_ocupado = sao_paulo_tz.localize(ag.data_hora, is_dst=None)
                fim_ocupado = inicio_ocupado + timedelta(minutes=duracao_ag)
                intervalos_ocupados.append((inicio_ocupado, fim_ocupado))
                
            # Loop de Slots
            while horario_iteracao + timedelta(minutes=duracao) <= fim_do_dia:
                fim_slot_candidato = horario_iteracao + timedelta(minutes=duracao)
                esta_ocupado = False

                # 1. Colisão com Agendamentos
                for inicio_oc, fim_oc in intervalos_ocupados:
                    if (horario_iteracao < fim_oc) and (fim_slot_candidato > inicio_oc):
                        esta_ocupado = True
                        break
                
                # 2. Colisão com Almoço
                if not esta_ocupado and eh_carol and almoco_inicio:
                    if (horario_iteracao < almoco_fim) and (fim_slot_candidato > almoco_inicio):
                        esta_ocupado = True

                # 3. Passado
                if not esta_ocupado and data_ref.date() == agora.date():
                    if horario_iteracao < (agora + timedelta(minutes=15)):
                        esta_ocupado = True
                
                if not esta_ocupado:
                    horarios_disponiveis.append(horario_iteracao) 
                    
                horario_iteracao += timedelta(minutes=INTERVALO_MINUTOS)
                
            return horarios_disponiveis

        except Exception as e:
            print(f"ERRO Plugin Barbearia: {e}") 
            return []
