# app/utils.py

import pytz
from datetime import datetime, time, timedelta
from sqlalchemy.orm import joinedload
from app.models.tables import Profissional, Agendamento, Servico, Barbearia

# --- FUNÇÃO UNIFICADA PARA CÁLCULO DE HORÁRIOS (DINÂMICA & BLINDADA) ---
def calcular_horarios_disponiveis(profissional: Profissional, dia_selecionado: datetime, duracao=90):
    """
    Calcula horários disponíveis respeitando RIGOROSAMENTE as configurações da Barbearia.
    
    ATUALIZAÇÃO: Inclui lógica Híbrida (Carol Lash) sem remover a lógica padrão.
    """
    sao_paulo_tz = pytz.timezone('America/Sao_Paulo')
    agora = datetime.now(sao_paulo_tz)
    
    # 🛑 TRAVA DE PASSADO: Se o dia for antes de hoje -> BLOQUEIA IMEDIATAMENTE
    if dia_selecionado.date() < agora.date():
        return [] 

    # 1. Recupera as Configurações
    barbearia = profissional.barbearia
    
    # Configurações com fallback seguro
    h_abre_str = getattr(barbearia, 'horario_abertura', '09:00') or '09:00'
    h_fecha_padrao = getattr(barbearia, 'horario_fechamento', '19:00') or '19:00'
    h_fecha_sabado = getattr(barbearia, 'horario_fechamento_sabado', '14:00') or '14:00'
    
    # Texto dos dias (ex: "Terça a Sexta" ou "Carol: Terça a Sábado (Misto)")
    dias_func_str = getattr(barbearia, 'dias_funcionamento', 'Terça a Sábado') # Mantém case original para comparação exata

    # 2. Definição do dia da semana (0=Seg, 5=Sáb, 6=Dom)
    dia_semana_int = dia_selecionado.weekday()

    # Variáveis de Controle (serão definidas abaixo)
    dia_aberto = False
    h_fecha_str = h_fecha_padrao # Começa com o padrão, ajusta se necessário

    # ==============================================================================
    # 🧠 LÓGICA DE DECISÃO DE HORÁRIOS (CAROL LASH + PADRÃO)
    # ==============================================================================
    
    # CENÁRIO 1: CAROL MISTO (Terça a Sábado)
    if dias_func_str == 'Carol: Terça a Sábado (Misto)':
        if dia_semana_int in [1, 2, 3, 4, 5]: # Ter a Sab
            dia_aberto = True
            
            if dia_semana_int == 5: # Sábado
                h_fecha_str = h_fecha_sabado
            elif dia_semana_int in [1, 3]: # Terça (1) e Quinta (3) -> Estendido
                h_fecha_str = '20:30'
            elif dia_semana_int in [2, 4]: # Quarta (2) e Sexta (4) -> Reduzido
                h_fecha_str = '17:30'

    # CENÁRIO 2: CAROL SEMANA DE CURSO (Segunda a Sexta)
    elif dias_func_str == 'Carol: Segunda a Sexta (Misto)':
        if dia_semana_int in [0, 1, 2, 3, 4]: # Seg a Sex (Sáb/Dom FECHADOS)
            dia_aberto = True
            
            if dia_semana_int in [1, 3]: # Terça (1) e Quinta (3) -> Estendido
                h_fecha_str = '20:30'
            else: # Seg(0), Qua(2), Sex(4) -> Reduzido
                h_fecha_str = '17:30'

    # CENÁRIO 3: PADRÃO (Lógica Original Mantida para outras lojas)
    else:
        dias_lower = dias_func_str.lower()
        
        # Lógica de Intervalos Genérica
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
        
        # Travas de Segurança Extras (Do seu código original)
        if dia_semana_int == 5 and 'sábado' not in dias_lower and 'sabado' not in dias_lower:
            dia_aberto = False
        if dia_semana_int == 6 and 'domingo' not in dias_lower:
            dia_aberto = False
        if dia_semana_int == 0 and 'segunda' not in dias_lower:
            dia_aberto = False

    # SE O DIA ESTIVER FECHADO, RETORNA VAZIO IMEDIATAMENTE
    if not dia_aberto:
        return []

    # ==============================================================================
    # ⚙️ CÁLCULO MATEMÁTICO (Mantido Original 100%)
    # ==============================================================================
    
    # 5. Converte horários para inteiros
    try:
        h_inicio, m_inicio = map(int, h_abre_str.split(':'))
        h_fim, m_fim = map(int, h_fecha_str.split(':'))
    except ValueError:
        h_inicio, m_inicio = 9, 0
        h_fim, m_fim = 19, 0

    INTERVALO_MINUTOS = 30 
    horarios_disponiveis = []

    # 6. Cálculo Matemático
    dia_base = datetime.combine(dia_selecionado.date(), time.min) 
    
    try:
        horario_iteracao = sao_paulo_tz.localize(dia_base.replace(hour=h_inicio, minute=m_inicio), is_dst=None)
        fim_do_dia = sao_paulo_tz.localize(dia_base.replace(hour=h_fim, minute=m_fim), is_dst=None)
        
        # Intervalo de query
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
            # Pega duração do agendamento existente (se não tiver serviço, assume 30min)
            duracao_ag = ag.servico.duracao if ag.servico else 30
            
            inicio_ocupado = sao_paulo_tz.localize(ag.data_hora, is_dst=None)
            fim_ocupado = inicio_ocupado + timedelta(minutes=duracao_ag)
            intervalos_ocupados.append((inicio_ocupado, fim_ocupado))
            
        # --- LOOP PRINCIPAL DE VERIFICAÇÃO ---
        # Verifica se o bloco (Inicio + Duração Solicitada) cabe antes do fechamento
        while horario_iteracao + timedelta(minutes=duracao) <= fim_do_dia:
            
            # Define o fim deste slot candidato
            fim_slot_candidato = horario_iteracao + timedelta(minutes=duracao)
            
            esta_ocupado = False
            # Verifica colisão com qualquer agendamento existente
            for inicio_oc, fim_oc in intervalos_ocupados:
                # Lógica de Colisão: (InicioA < FimB) e (FimA > InicioB)
                # Verifica se o slot candidato se sobrepõe a algum agendamento
                if (horario_iteracao < fim_oc) and (fim_slot_candidato > inicio_oc):
                    esta_ocupado = True
                    break
            
            # Verifica se é passado (com margem de 15min) APENAS SE FOR HOJE
            if dia_selecionado.date() == agora.date():
                if horario_iteracao < (agora + timedelta(minutes=15)):
                    esta_ocupado = True
            
            if not esta_ocupado:
                horarios_disponiveis.append(horario_iteracao) 
                
            horario_iteracao += timedelta(minutes=INTERVALO_MINUTOS)
            
        return horarios_disponiveis

    except Exception as e:
        print(f"ERRO CRÍTICO ao calcular horários: {e}") 
        return []
