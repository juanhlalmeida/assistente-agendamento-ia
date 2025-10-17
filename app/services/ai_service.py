# app/services/ai_service.py
import os
import logging
import google.generativeai as genai
from datetime import datetime, timedelta
from flask import current_app
from sqlalchemy.orm import joinedload
from app.models.tables import Agendamento, Profissional, Servico
from app.extensions import db

# --- Configuração do cliente Gemini (Mantido) ---
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
if not GEMINI_API_KEY:
    logging.error("Chave da API do Gemini não encontrada!")
else:
    genai.configure(api_key=GEMINI_API_KEY)

# --- Funções (Tools) que a IA pode chamar (Sua lógica, 100% preservada) ---

def listar_profissionais() -> str:
    """Lista todos os profissionais disponíveis no sistema."""
    try:
        with current_app.app_context():
            profissionais = Profissional.query.all()
            if not profissionais:
                return "Nenhum profissional cadastrado no momento."
            nomes = [p.nome for p in profissionais]
            return f"Profissionais disponíveis: {', '.join(nomes)}."
    except Exception as e:
        return f"Erro ao listar profissionais: {str(e)}"

def listar_servicos() -> str:
    """Lista todos os serviços disponíveis no sistema."""
    try:
        with current_app.app_context():
            servicos = Servico.query.all()
            if not servicos:
                return "Nenhum serviço cadastrado no momento."
            # ✅ AJUSTE: Retornando mais detalhes para o modelo, como você pediu no prompt.
            # O modelo agora pode informar ao cliente o preço e a duração.
            detalhes = [f"{s.nome} ({s.duracao} min, R${s.preco:.2f})" for s in servicos]
            return f"Serviços disponíveis: {', '.join(detalhes)}."
    except Exception as e:
        return f"Erro ao listar serviços: {str(e)}"

def calcular_horarios_disponiveis(profissional_nome: str, dia: str) -> str:
    """Calcula horários disponíveis para um profissional em um dia específico."""
    try:
        with current_app.app_context():
            profissional = Profissional.query.filter_by(nome=profissional_nome).first()
            if not profissional:
                return "Profissional não encontrado. Por favor, verifique o nome."

            agora = datetime.now()
            if dia.lower() == 'hoje':
                dia_dt = agora.replace(hour=0, minute=0, second=0, microsecond=0)
            elif dia.lower() == 'amanhã':
                dia_dt = (agora + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            else:
                dia_dt = datetime.strptime(dia, '%Y-%m-%d')

            HORA_INICIO_TRABALHO = 9
            HORA_FIM_TRABALHO = 20
            INTERVALO_MINUTOS = 30

            horarios_disponiveis = []
            horario_iteracao = dia_dt.replace(hour=HORA_INICIO_TRABALHO, minute=0)
            fim_do_dia = dia_dt.replace(hour=HORA_FIM_TRABALHO, minute=0)

            # Busca agendamentos apenas para o dia relevante
            inicio_busca = dia_dt
            fim_busca = dia_dt.replace(hour=23, minute=59, second=59)
            agendamentos_do_dia = (
                Agendamento.query
                .options(joinedload(Agendamento.servico))
                .filter(Agendamento.profissional_id == profissional.id)
                .filter(Agendamento.data_hora.between(inicio_busca, fim_busca))
                .all()
            )

            intervalos_ocupados = [(ag.data_hora, ag.data_hora + timedelta(minutes=ag.servico.duracao)) for ag in agendamentos_do_dia]

            while horario_iteracao < fim_do_dia:
                # Verifica se o *início* do horário está livre e se ele já não passou
                esta_ocupado = any(inicio <= horario_iteracao < fim for inicio, fim in intervalos_ocupados)
                if not esta_ocupado and horario_iteracao > agora:
                    horarios_disponiveis.append(horario_iteracao.strftime('%H:%M'))
                
                horario_iteracao += timedelta(minutes=INTERVALO_MINUTOS)

            if not horarios_disponiveis:
                return f"Nenhum horário disponível para {profissional_nome} em {dia_dt.strftime('%Y-%m-%d')}."
            
            return f"Horários disponíveis para {profissional_nome} em {dia_dt.strftime('%Y-%m-%d')}: {', '.join(horarios_disponiveis)}."
    except Exception as e:
        return f"Erro ao calcular horários: {str(e)}"

def criar_agendamento(nome_cliente: str, telefone_cliente: str, data_hora: str, profissional_nome: str, servico_nome: str) -> str:
    """Cria um novo agendamento no banco de dados."""
    try:
        with current_app.app_context():
            profissional = Profissional.query.filter_by(nome=profissional_nome).first()
            if not profissional: return "Profissional não encontrado."

            servico = Servico.query.filter_by(nome=servico_nome).first()
            if not servico: return "Serviço não encontrado."

            data_hora_dt = datetime.strptime(data_hora, '%Y-%m-%d %H:%M')

            # Verifica se o horário já passou
            if data_hora_dt <= datetime.now():
                return "Este horário já passou. Por favor, escolha um horário futuro."

            # Lógica de conflito (mantida, mas com busca mais otimizada)
            novo_fim = data_hora_dt + timedelta(minutes=servico.duracao)
            inicio_dia = data_hora_dt.replace(hour=0, minute=0)
            fim_dia = data_hora_dt.replace(hour=23, minute=59)

            agendamentos_existentes = (
                Agendamento.query
                .options(joinedload(Agendamento.servico))
                .filter(Agendamento.profissional_id == profissional.id)
                .filter(Agendamento.data_hora.between(inicio_dia, fim_dia))
                .all()
            )
            
            conflito = any(
                max(data_hora_dt, ag.data_hora) < min(novo_fim, ag.data_hora + timedelta(minutes=ag.servico.duracao))
                for ag in agendamentos_existentes
            )

            if conflito:
                return "Conflito de horário. Este horário já está ocupado. Por favor, escolha outro."

            novo_agendamento = Agendamento(
                nome_cliente=nome_cliente,
                telefone_cliente=telefone_cliente,
                data_hora=data_hora_dt,
                profissional_id=profissional.id,
                servico_id=servico.id,
            )
            db.session.add(novo_agendamento)
            db.session.commit()
            return f"Agendamento criado com sucesso para {nome_cliente} em {data_hora} com {profissional_nome} para o serviço {servico_nome}."
    except Exception as e:
        db.session.rollback()
        return f"Erro ao criar agendamento: {str(e)}"

# ✅ AJUSTE: Simplificação da declaração das tools.
# O SDK do Gemini agora lê as descrições (docstrings) e os tipos (type hints)
# das suas funções para criar as declarações automaticamente.
tools_list = [
    listar_profissionais,
    listar_servicos,
    calcular_horarios_disponiveis,
    criar_agendamento,
]

# (Opcional) Dicionário para chamar as funções por nome, pode ser útil em outras partes do seu app.
tools_definitions = {
    func.__name__: func for func in tools_list
}

# --- Modelo de IA (Combinação do melhor dos dois mundos) ---
model = None
try:
    model = genai.GenerativeModel(
        # ✅ Usando o modelo Pro, que é mais robusto para seguir instruções complexas.
        model_name='gemini-1.5-pro-latest',
        
        # ✅ USANDO A FORMA MODERNA E SIMPLES DE PASSAR AS TOOLS
        tools=tools_list,
        
        # ✅ MANTENDO A SUA EXCELENTE E DETALHADA SYSTEM INSTRUCTION
        system_instruction=f"""
        Você é Luana, concierge breve e eficiente da Vila Chique. Responda sempre de forma concisa (máx. 2-3 frases), amigável e direta. Não use desculpas longas; corrija erros rapidamente. Use emojis de forma natural (😊, ✅, ✂️).

        Fluxo de agendamento:
        1. Saudação inicial breve: "Olá! Sou Luana da Vila Chique 😊. Como posso ajudar: agendar, reagendar ou cancelar?"
        2. Para agendar: Mencione profissionais disponíveis logo no início (use listar_profissionais se necessário). Pergunte só o essencial: serviço, profissional, data/hora preferida.
        3. Use tools INTERNAMENTE (nunca mostre código ou "tools." na resposta):
           - listar_profissionais: Para listar profissionais.
           - listar_servicos: Para listar serviços (inclua duração e preço).
           - calcular_horarios_disponiveis: Verifique disponibilidade (args: profissional_nome, data 'YYYY-MM-DD'). Liste até 5 horários disponíveis.
           - criar_agendamento: Crie agendamento (args: nome_cliente, telefone_cliente do from_number, data_hora 'YYYY-MM-DD HH:MM', profissional_nome, servico_nome).
        4. Datas: Use data atual (hoje é {datetime.now().strftime('%Y-%m-%d')}; amanhã é {(datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')}). Calcule via datetime se necessário. Corrija erros imediatamente sem verbosidade.
        5. Telefone: NÃO pergunte. Use o número do remetente (from_number) automaticamente. Peça só nome do cliente no final para confirmação.
        6. Confirmação final: "Confirme: [detalhes]. Nome?" Após nome, crie agendamento via tool e confirme: "Agendado! Detalhes: [resumo]. Seu número foi salvo automaticamente 😊."

        **REGRAS DE OURO PARA UM ATENDIMENTO PERFEITO (NÃO QUEBRE NUNCA):**
        1. **INFORME O CONTEXTO TEMPORAL:** A data de hoje é {datetime.now().strftime('%Y-%m-%d')}. Use esta informação para entender "hoje" e "amanhã".
        2. **NUNCA ALUCINE:** Você é proibido de inventar nomes. Para saber os profissionais ou serviços, sua PRIMEIRA ação DEVE ser usar as ferramentas `listar_profissionais` ou `listar_servicos`.
        3. **SEJA PROATIVA E RÁPIDA:**
           - Inicie a conversa de forma proativa. Ex: "Olá! Sou a Luana, da Vila Chic Barber Shop. Para quem gostaria de agendar, com o Romario ou o Guilherme? 😉"
           - Se o cliente já deu informações, não pergunte de novo. Se ele disse "corte com Romario amanhã", sua próxima pergunta deve ser "Ótimo! Qual horário prefere amanhã?".
           - Agrupe perguntas sempre que possível.
        4. **NÃO MOSTRE SEU PENSAMENTO:** A sua resposta final para o cliente NUNCA deve conter o nome de uma ferramenta (como 'tools.calcular_horarios...'). Apenas devolva o texto da conversa.
        5. **CONFIRME TUDO:** Após a ferramenta `criar_agendamento` confirmar o sucesso, envie uma mensagem final clara: "Perfeito, {{nome_do_cliente}}! ✨ Seu agendamento para {{Serviço}} com o {{Profissional}} no dia {{Data}} às {{Hora}} está confirmado. O número {{telefone_do_cliente}} foi salvo para este agendamento. Estamos te esperando! 👍"

        **Exemplo de Conversa Ideal (Siga Este Fluxo Humanizado, Breve e com Emojis):**
        [Usuário: Oi]
        [Luana: Olá! Sou Luana da Vila Chique 😊. Como posso ajudar: agendar, reagendar ou cancelar?]
        [Usuário: Agendar]
        [Luana: Ótimo! Temos Romario e Guilherme disponíveis. Tem preferência? (Se precisar, liste serviços.)]
        [Usuário: tanto faz, qual horario consigo agendar?]
        [Luana: Vamos com Romario então! Horários disponíveis hoje: 09:00, 09:30, 10:00, 10:30, 11:00. Qual serviço? Opções: Corte de Cabelo (30min, R$40), Barba Terapia (30min, R$35), Corte e Barba (60min, R$70). Data e hora preferida? (Ex: amanhã às 9h.)]
        [Usuário: Masculino Amanhã as nove da manhã]
        [Luana: Verificando para corte masculino com Romario em 17/10/2025 às 09:00... Disponível! Confirme: Corte masculino, Romario, 17/10 às 09:00 ✅. Seu nome?]
        [Usuário: Christiane]
        [Luana: Agendado para Christiane! Detalhes: Corte masculino com Romario em 17/10/2025 às 09:00 😊. Seu número foi salvo automaticamente. Qualquer dúvida, é só falar!]
        """
    )
except Exception as e:
    logging.error(f"Erro ao inicializar o modelo Gemini: {str(e)}", exc_info=True)