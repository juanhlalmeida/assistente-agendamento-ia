# app/utils.py

import pytz
from datetime import datetime, time, timedelta
from sqlalchemy.orm import joinedload
from app.models.tables import Profissional, Agendamento, Servico, Barbearia

# --- FUNÇÃO UNIFICADA PARA CÁLCULO DE HORÁRIOS (DINÂMICA & BLINDADA) ---
def calcular_horarios_disponiveis(profissional: Profissional, dia_selecionado: datetime, duracao=90):
    """
    Calcula horários disponíveis respeitando RIGOROSAMENTE as configurações.
    ATUALIZAÇÃO FINAL: Ajuste de 30min no fim do dia e Bloqueio de Almoço (12h-13h).
    """
    sao_paulo_tz = pytz.timezone('America/Sao_Paulo')
    agora = datetime.now(sao_paulo_tz)
    
    # 🛑 TRAVA DE PASSADO
    if dia_selecionado.date() < agora.date():
        return [] 

    # 1. Recupera as Configurações
    barbearia = profissional.barbearia
    
    # Configurações com fallback seguro
    h_abre_str = getattr(barbearia, 'horario_abertura', '09:00') or '09:00'
    h_fecha_padrao = getattr(barbearia, 'horario_fechamento', '19:00') or '19:00'
    h_fecha_sabado = getattr(barbearia, 'horario_fechamento_sabado', '14:00') or '14:00'
    
    dias_func_str = getattr(barbearia, 'dias_funcionamento', 'Terça a Sábado')

    # 2. Definição do dia da semana (0=Seg, 5=Sáb, 6=Dom)
    dia_semana_int = dia_selecionado.weekday()

    dia_aberto = False
    h_fecha_str = h_fecha_padrao 

    # ==============================================================================
    # 🧠 LÓGICA DE DECISÃO DE HORÁRIOS (CAROL LASH)
    # ==============================================================================
    
    eh_carol = 'Carol' in dias_func_str # Flag para ativar o almoço depois

    # CENÁRIO 1: CAROL MISTO (Terça a Sábado)
    if dias_func_str == 'Carol: Terça a Sábado (Misto)':
        if dia_semana_int in [1, 2, 3, 4, 5]: # Ter a Sab
            dia_aberto = True
            
            if dia_semana_int == 5: # Sábado
                h_fecha_str = h_fecha_sabado
            elif dia_semana_int in [1, 3]: # Terça (1) e Quinta (3)
                # AJUSTE FINO: 22:00 fecha a conta para o último ser 20:30 (com 1h30 de serviço)
                h_fecha_str = '22:00'
            elif dia_semana_int in [2, 4]: # Quarta (2) e Sexta (4)
                # AJUSTE FINO: 19:00 fecha a conta para o último ser 17:30
                h_fecha_str = '19:00'

    # CENÁRIO 2: CAROL SEMANA DE CURSO (Segunda a Sexta)
    elif dias_func_str == 'Carol: Segunda a Sexta (Misto)':
        if dia_semana_int in [0, 1, 2, 3, 4]: # Seg a Sex
            dia_aberto = True
            
            if dia_semana_int in [1, 3]: # Terça (1) e Quinta (3)
                h_fecha_str = '22:00' # Ajustado para terminar 20:30
            else: # Seg(0), Qua(2), Sex(4)
                h_fecha_str = '19:00' # Ajustado para terminar 17:30

    # CENÁRIO 3: PADRÃO (Outras Lojas)
    else:
        dias_lower = dias_func_str.lower()
        if 'segunda a sexta' in dias_lower and dia_semana_int < 5:
            dia_aberto = True
        elif 'segunda a sábado' in dias_lower and dia_semana_int < 6:
            dia_aberto = True
            if dia_semana_int == 5: h_fecha_str = h_fecha_sabado
        elif 'terça a sábado' in dias_lower and 0 < dia_semana_int < 6:
            dia_aberto = True
            if dia_semana_int == 5: h_fecha_str = h_fecha_sabado
        elif 'terça a sexta' in dias_lower and 0 < dia_semana_int < 5:
            dia_aberto = True
        
        # Travas Extras
        if dia_semana_int == 5 and 'sábado' not in dias_lower and 'sabado' not in dias_lower:
            dia_aberto = False
        if dia_semana_int == 6 and 'domingo' not in dias_lower:
            dia_aberto = False
        if dia_semana_int == 0 and 'segunda' not in dias_lower:
            dia_aberto = False

    if not dia_aberto:
        return []

    # ==============================================================================
    # ⚙️ CÁLCULO MATEMÁTICO
    # ==============================================================================
    
    try:
        h_inicio, m_inicio = map(int, h_abre_str.split(':'))
        h_fim, m_fim = map(int, h_fecha_str.split(':'))
    except ValueError:
        h_inicio, m_inicio = 9, 0
        h_fim, m_fim = 19, 0

    INTERVALO_MINUTOS = 30 
    horarios_disponiveis = []

    dia_base = datetime.combine(dia_selecionado.date(), time.min) 
    
    try:
        horario_iteracao = sao_paulo_tz.localize(dia_base.replace(hour=h_inicio, minute=m_inicio), is_dst=None)
        fim_do_dia = sao_paulo_tz.localize(dia_base.replace(hour=h_fim, minute=m_fim), is_dst=None)
        
        # --- DEFINIÇÃO DO ALMOÇO (12:00 as 13:00) ---
        # Só aplicamos se for configuração da Carol para não quebrar outras lojas
        almoco_inicio = None
        almoco_fim = None
        if eh_carol:
            almoco_inicio = sao_paulo_tz.localize(dia_base.replace(hour=12, minute=0), is_dst=None)
            almoco_fim = sao_paulo_tz.localize(dia_base.replace(hour=13, minute=0), is_dst=None)

        # Busca agendamentos do banco
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
            
        # --- LOOP DE VERIFICAÇÃO ---
        while horario_iteracao + timedelta(minutes=duracao) <= fim_do_dia:
            
            fim_slot_candidato = horario_iteracao + timedelta(minutes=duracao)
            esta_ocupado = False

            # 1. Verifica colisão com Agendamentos Reais
            for inicio_oc, fim_oc in intervalos_ocupados:
                if (horario_iteracao < fim_oc) and (fim_slot_candidato > inicio_oc):
                    esta_ocupado = True
                    break
            
            # 2. Verifica colisão com o ALMOÇO (12h-13h) - Se for Carol
            if not esta_ocupado and eh_carol and almoco_inicio:
                # Se o horário começa dentro do almoço OU termina dentro do almoço
                # Lógica: (Inicio < FimAlmoco) E (Fim > InicioAlmoco)
                if (horario_iteracao < almoco_fim) and (fim_slot_candidato > almoco_inicio):
                    esta_ocupado = True

            # 3. Verifica passado (apenas se for hoje)
            if not esta_ocupado and dia_selecionado.date() == agora.date():
                if horario_iteracao < (agora + timedelta(minutes=15)):
                    esta_ocupado = True
            
            if not esta_ocupado:
                horarios_disponiveis.append(horario_iteracao) 
                
            horario_iteracao += timedelta(minutes=INTERVALO_MINUTOS)
            
        return horarios_disponiveis

    except Exception as e:
        print(f"ERRO CRÍTICO ao calcular horários: {e}") 
        return []
