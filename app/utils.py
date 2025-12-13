# app/utils.py
import pytz
from datetime import datetime, time, timedelta
from sqlalchemy.orm import joinedload
from app.models.tables import Profissional, Agendamento, Servico, Barbearia

# --- FUNÇÃO UNIFICADA PARA CÁLCULO DE HORÁRIOS (DINÂMICA & BLINDADA) ---
def calcular_horarios_disponiveis(profissional: Profissional, dia_selecionado: datetime):
    """
    Calcula horários disponíveis respeitando RIGOROSAMENTE as configurações da Barbearia.
    """
    sao_paulo_tz = pytz.timezone('America/Sao_Paulo')
    
    # 1. Recupera as Configurações
    barbearia = profissional.barbearia
    
    # Configurações com fallback seguro
    h_abre_str = getattr(barbearia, 'horario_abertura', '09:00') or '09:00'
    h_fecha_padrao = getattr(barbearia, 'horario_fechamento', '19:00') or '19:00'
    h_fecha_sabado = getattr(barbearia, 'horario_fechamento_sabado', '14:00') or '14:00'
    
    # Texto dos dias (ex: "Terça a Sexta")
    dias_func_str = getattr(barbearia, 'dias_funcionamento', 'Terça a Sábado').lower()

    # 2. Definição do dia da semana (0=Seg, 5=Sáb, 6=Dom)
    dia_semana_int = dia_selecionado.weekday()

    # ==============================================================================
    # 🔒 TRAVAS DE SEGURANÇA ABSOLUTAS (HARD LOCKS)
    # Se o dia não estiver escrito explicitamente no texto, bloqueia antes de tudo.
    # ==============================================================================
    
    # TRAVA DE SÁBADO: Se é sábado e não tem "sábado" no texto -> BLOQUEIA
    if dia_semana_int == 5:
        if 'sábado' not in dias_func_str and 'sabado' not in dias_func_str:
            return [] # Retorna vazio = Dia Fechado
            
    # TRAVA DE DOMINGO: Se é domingo e não tem "domingo" no texto -> BLOQUEIA
    if dia_semana_int == 6:
        if 'domingo' not in dias_func_str:
            return []

    # TRAVA DE SEGUNDA: Se é segunda e não tem "segunda" no texto -> BLOQUEIA
    if dia_semana_int == 0:
        if 'segunda' not in dias_func_str:
            return []

    # ==============================================================================

    # 3. Lógica de Intervalos (Para preencher os dias do meio, ex: Quarta/Quinta)
    dias_permitidos = []
    
    if 'segunda' in dias_func_str and 'sábado' in dias_func_str: # "Segunda a Sábado"
        dias_permitidos = [0, 1, 2, 3, 4, 5]
    elif 'terça' in dias_func_str and 'sábado' in dias_func_str: # "Terça a Sábado"
        dias_permitidos = [1, 2, 3, 4, 5]
    elif 'segunda' in dias_func_str and 'sexta' in dias_func_str: # "Segunda a Sexta"
        dias_permitidos = [0, 1, 2, 3, 4]
    elif 'terça' in dias_func_str and 'sexta' in dias_func_str: # "Terça a Sexta" (SEU CASO)
        dias_permitidos = [1, 2, 3, 4]
    else:
        # Padrão genérico (caso a IA não entenda o intervalo)
        # Nota: As travas acima (Seg/Sab/Dom) JÁ filtraram os extremos perigosos.
        # Então aqui podemos ser um pouco mais permissivos com o "miolo" da semana.
        dias_permitidos = [1, 2, 3, 4, 5]

    # Se o dia passou pelas travas mas não está na lista permitida do intervalo
    if dia_semana_int not in dias_permitidos:
        return []

    # 4. Define horário de fechamento correto (Sábado vs Dia de Semana)
    if dia_semana_int == 5: # Sábado
        h_fecha_str = h_fecha_sabado
    else: # Outros dias
        h_fecha_str = h_fecha_padrao

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
            if ag.servico is None: continue
            inicio_ocupado = sao_paulo_tz.localize(ag.data_hora, is_dst=None)
            fim_ocupado = inicio_ocupado + timedelta(minutes=ag.servico.duracao)
            intervalos_ocupados.append((inicio_ocupado, fim_ocupado))
            
        agora = datetime.now(sao_paulo_tz)
        
        while horario_iteracao < fim_do_dia:
            esta_ocupado = any(inicio <= horario_iteracao < fim for inicio, fim in intervalos_ocupados)
            
            if not esta_ocupado and horario_iteracao > agora:
                horarios_disponiveis.append(horario_iteracao) 
                
            horario_iteracao += timedelta(minutes=INTERVALO_MINUTOS)
            
        return horarios_disponiveis

    except Exception as e:
        print(f"ERRO CRÍTICO ao calcular horários: {e}") 
        return []
