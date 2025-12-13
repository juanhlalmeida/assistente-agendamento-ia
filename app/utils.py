# app/utils.py
import pytz
from datetime import datetime, time, timedelta
from sqlalchemy.orm import joinedload
from app.models.tables import Profissional, Agendamento, Servico, Barbearia

# --- FUNÇÃO UNIFICADA PARA CÁLCULO DE HORÁRIOS (DINÂMICA) ---
def calcular_horarios_disponiveis(profissional: Profissional, dia_selecionado: datetime):
    """
    Calcula horários disponíveis respeitando as configurações da Barbearia (Horários e Dias).
    """
    sao_paulo_tz = pytz.timezone('America/Sao_Paulo')
    
    # 1. Recupera as Configurações da Barbearia
    barbearia = profissional.barbearia
    
    # Defaults de segurança caso não tenha configurado
    h_abre_str = getattr(barbearia, 'horario_abertura', '09:00') or '09:00'
    h_fecha_str = getattr(barbearia, 'horario_fechamento', '19:00') or '19:00'
    dias_func_str = getattr(barbearia, 'dias_funcionamento', 'Terça a Sábado').lower()

    # 2. Converte strings "09:00" para inteiros (Hora e Minuto)
    try:
        h_inicio, m_inicio = map(int, h_abre_str.split(':'))
        h_fim, m_fim = map(int, h_fecha_str.split(':'))
    except ValueError:
        # Fallback se formato estiver errado no banco
        h_inicio, m_inicio = 9, 0
        h_fim, m_fim = 19, 0

    INTERVALO_MINUTOS = 30 

    horarios_disponiveis = []
    
    # 3. Lógica de Bloqueio por Dia da Semana
    # 0=Segunda, 1=Terça, ... 5=Sábado, 6=Domingo
    dia_semana_int = dia_selecionado.weekday()
    
    # Mapeamento simples de texto para números permitidos
    # Ex: "Terça a Sábado" -> Bloqueia Segunda (0) e Domingo (6)
    dias_permitidos = []
    
    if 'segunda' in dias_func_str and 'sábado' in dias_func_str: # "Segunda a Sábado"
        dias_permitidos = [0, 1, 2, 3, 4, 5]
    elif 'terça' in dias_func_str and 'sábado' in dias_func_str: # "Terça a Sábado"
        dias_permitidos = [1, 2, 3, 4, 5]
    elif 'segunda' in dias_func_str and 'sexta' in dias_func_str: # "Segunda a Sexta"
        dias_permitidos = [0, 1, 2, 3, 4]
    else:
        # Padrão seguro se a IA não entender o texto customizado: 
        # Assume Terça(1) a Sábado(5)
        dias_permitidos = [1, 2, 3, 4, 5]

    # SE O DIA PEDIDO NÃO FOR PERMITIDO, RETORNA VAZIO
    if dia_semana_int not in dias_permitidos:
        return []

    # 4. Cálculo Matemático (Agora com variáveis dinâmicas)
    dia_base = datetime.combine(dia_selecionado.date(), time.min) 
    
    try:
        # Início e Fim baseados na configuração
        horario_iteracao = sao_paulo_tz.localize(dia_base.replace(hour=h_inicio, minute=m_inicio), is_dst=None)
        fim_do_dia = sao_paulo_tz.localize(dia_base.replace(hour=h_fim, minute=m_fim), is_dst=None)
        
        # Intervalo de query no banco (naive)
        inicio_query = dia_base.replace(hour=0, minute=0, second=0, microsecond=0)
        fim_query = inicio_query + timedelta(days=1)
        
        agendamentos_do_dia = (
            Agendamento.query
            .options(joinedload(Agendamento.servico))
            .filter(
                Agendamento.barbearia_id == barbearia.id, # Garante que é da mesma loja
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
