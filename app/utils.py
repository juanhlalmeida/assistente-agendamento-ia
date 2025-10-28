# app/utils.py
import pytz
from datetime import datetime, time, timedelta
from sqlalchemy.orm import joinedload
# Importa os modelos necessários DENTRO da função ou globalmente se não houver risco circular
# Vamos importar globalmente por agora, mas atentos a erros de importação
from app.models.tables import Profissional, Agendamento, Servico # type: ignore

# --- FUNÇÃO UNIFICADA PARA CÁLCULO DE HORÁRIOS ---
# Baseada na versão _web que funcionava no painel
def calcular_horarios_disponiveis(profissional: Profissional, dia_selecionado: datetime):
    """
    Calcula os horários disponíveis para um profissional em um dia específico,
    considerando agendamentos existentes e o horário atual (fuso de São Paulo).
    Retorna uma lista de objetos datetime cientes do fuso horário (America/Sao_Paulo).
    """
    sao_paulo_tz = pytz.timezone('America/Sao_Paulo')
    # Horário de funcionamento padrão (pode virar configuração no futuro)
    HORA_INICIO_TRABALHO = 9
    HORA_FIM_TRABALHO = 20 
    INTERVALO_MINUTOS = 30 # Intervalo entre slots oferecidos

    horarios_disponiveis = []
    
    # Garante que estamos a trabalhar com a data base (sem hora/tz)
    dia_base = datetime.combine(dia_selecionado.date(), time.min) 
    
    try:
        # Define o início e fim do dia de trabalho COM timezone
        # Usa is_dst=None para lidar com mudanças de horário de verão, se aplicável
        horario_iteracao = sao_paulo_tz.localize(dia_base.replace(hour=HORA_INICIO_TRABALHO), is_dst=None)
        fim_do_dia = sao_paulo_tz.localize(dia_base.replace(hour=HORA_FIM_TRABALHO), is_dst=None)
        
        # Define o intervalo de query no banco (sem timezone - naive)
        # O banco geralmente guarda em UTC ou local naive. Assumimos naive.
        inicio_query = dia_base.replace(hour=0, minute=0, second=0, microsecond=0)
        fim_query = inicio_query + timedelta(days=1)
        
        # Busca agendamentos do profissional no dia especificado
        agendamentos_do_dia = (
            Agendamento.query
            .options(joinedload(Agendamento.servico)) # Carrega o serviço junto para pegar a duração
            .filter(
                Agendamento.profissional_id == profissional.id,
                Agendamento.data_hora >= inicio_query, 
                Agendamento.data_hora < fim_query 
            )
            .all()
        )
        
        # Cria lista de intervalos ocupados, convertendo para o timezone correto (SP)
        intervalos_ocupados = []
        for ag in agendamentos_do_dia:
            if ag.servico is None: # Segurança: Ignora agendamentos sem serviço associado
                 print(f"Aviso: Agendamento ID {ag.id} sem serviço associado.")
                 continue
                 
            # Converte ag.data_hora (naive do DB) para o fuso de SP
            inicio_ocupado = sao_paulo_tz.localize(ag.data_hora, is_dst=None)
            fim_ocupado = inicio_ocupado + timedelta(minutes=ag.servico.duracao)
            intervalos_ocupados.append((inicio_ocupado, fim_ocupado))
            
        # Obtém a hora atual COM timezone para comparação
        agora = datetime.now(sao_paulo_tz)
        
        # Itera pelos horários possíveis do dia
        while horario_iteracao < fim_do_dia:
            # Verifica se o horário atual está dentro de algum intervalo ocupado
            # A verificação deve considerar a duração do *serviço sendo agendado*? 
            # Não, aqui apenas listamos slots livres no intervalo definido (INTERVALO_MINUTOS).
            # A verificação de conflito *real* (com duração) é feita ao *criar* o agendamento.
            esta_ocupado = any(inicio <= horario_iteracao < fim for inicio, fim in intervalos_ocupados)
            
            # Adiciona à lista se NÃO estiver ocupado E for no futuro
            if not esta_ocupado and horario_iteracao > agora:
                horarios_disponiveis.append(horario_iteracao) 
                
            horario_iteracao += timedelta(minutes=INTERVALO_MINUTOS)
            
        return horarios_disponiveis

    except Exception as e:
        # Usar o logger da aplicação Flask seria melhor aqui, mas print funciona por agora
        print(f"ERRO CRÍTICO ao calcular horários: {e}") 
        # Considerar logar traceback: import traceback; traceback.print_exc()
        return [] # Retorna lista vazia em caso de erro

# --- OUTRAS FUNÇÕES UTILITÁRIAS PODEM SER ADICIONADAS AQUI ---