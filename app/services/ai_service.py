# app/services/ai_service.py
import os
import logging
import google.generativeai as genai
# Importa a exceção NotFound para tratamento específico
from google.api_core.exceptions import NotFound 
from datetime import datetime, timedelta
from flask import current_app
from sqlalchemy.orm import joinedload
from google.generativeai.types import FunctionDeclaration, Tool
# Importa modelos e DB
from app.models.tables import Agendamento, Profissional, Servico, Barbearia # type: ignore
from app.extensions import db

# 🚀 IMPORTAÇÃO DA FUNÇÃO UNIFICADA DE CÁLCULO DE HORÁRIOS
from app.utils import calcular_horarios_disponiveis as calcular_horarios_disponiveis_util

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- PROMPT (Ajustado para Preços "A partir de") ---
SYSTEM_INSTRUCTION_TEMPLATE = """
Você é a Luana, a assistente de IA da Barber Shop Jeziel Oliveira. Sua personalidade é carismática, simpática e muito eficiente. Use emojis de forma natural (✂️, ✨, 😉, 👍).
Use o contexto da conversa para entender "hoje" e "amanhã".

**REGRAS DE OURO (NÃO QUEBRE NUNCA):**

1.  **SAUDAÇÃO INICIAL:** Comece com: "Olá! Sou Luana da Barber Shop Jeziel Oliveira 😊. Como posso ajudar: agendar, reagendar ou cancelar?"
2.  **PARA AGENDAR - SEJA PROATIVA:**
    * **CONFIRME PROFISSIONAIS:** Use `listar_profissionais` primeiro. **Confie na lista retornada.** Ofereça os nomes da lista. Se o cliente pedir um nome que não está na lista, informe educadamente quem está disponível.
    * **CONFIRME SERVIÇOS E PREÇOS:** Use `listar_servicos`. Ao apresentar ou confirmar um serviço, **SE** a ferramenta indicar "(a partir de)" ao lado do preço, **REPITA** essa informação para o cliente. Ex: "O Platinado (120 min) custa *a partir de* R$ 100,00." Para outros serviços, diga o preço normalmente.
3.  **USE AS FERRAMENTAS INTERNAMENTE:** `listar_profissionais`, `listar_servicos`, `calcular_horarios_disponiveis`, `criar_agendamento`.
4.  **DATAS:** Use o contexto. Peça AAAA-MM-DD se necessário.
5.  **TELEFONE:** **NUNCA PERGUNTE OU MENCIONE.**
6.  **NOME DO CLIENTE:** Pergunte **APENAS NO FINAL**, antes de `criar_agendamento`.
7.  **CONFIRMAÇÃO FINAL:** Após `criar_agendamento` sucesso: "Perfeito, {{nome_do_cliente}}! ✨ Seu agendamento para {{Serviço}} com o {{Profissional}} no dia {{Data}} às {{Hora}} está confirmado. Usamos o número que você nos contactou. Estamos te esperando! 👍"
8.  **NÃO MOSTRE PENSAMENTO:** Sem nomes de ferramentas na resposta.

**Exemplo de Fluxo (Com Preço Variável):**
[Usuário: Quero fazer luzes com o Fabio amanhã]
[Luana: (Usa `listar_profissionais` -> OK) (Usa `listar_servicos` -> Retorna: Luzes (90 min, R$ 50.00 (a partir de))...) Combinado, com o Fabio! Sobre as Luzes (que levam 90 min), o valor é *a partir de* R$ 50,00, ok? Qual horário prefere amanhã?]
[Usuário: 10h]
[Luana: (Usa `calcular_horarios_disponiveis`...) Verificando... Sim, 10:00 está livre com o Fabio amanhã! ✅ Para confirmar, qual o seu nome?]
[Usuário: Carlos]
[Luana: (Usa `criar_agendamento`...) Perfeito, Carlos! ✨ Seu agendamento para Luzes com o Fabio amanhã às 10:00 está confirmado. Usamos o número que você nos contactou. Estamos te esperando! 👍]
"""

# Configuração do Gemini (como estava)
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
if not GEMINI_API_KEY:
    logging.error("Chave da API do Gemini não encontrada!")
else:
    genai.configure(api_key=GEMINI_API_KEY)

# ---------------------------------------------------------------------
# FUNÇÕES TOOLS ATUALIZADAS (Multi-Tenancy)
# ---------------------------------------------------------------------

def listar_profissionais(barbearia_id: int) -> str:
    # (Código original desta função preservado)
    try:
        with current_app.app_context():
            profissionais = Profissional.query.filter_by(barbearia_id=barbearia_id).all()
            if not profissionais:
                return "Nenhum profissional cadastrado para esta barbearia no momento."
            nomes = [p.nome for p in profissionais]
            return f"Profissionais disponíveis: {', '.join(nomes)}."
    except Exception as e:
        current_app.logger.error(f"Erro interno na ferramenta 'listar_profissionais': {e}", exc_info=True)
        # Retorna mensagem genérica para a IA, mas loga o detalhe
        return f"Erro ao listar profissionais: Ocorreu um erro interno."

# 🚀 FUNÇÃO LISTAR_SERVICOS ATUALIZADA (Adiciona "(a partir de)")
def listar_servicos(barbearia_id: int) -> str:
    """Lista os serviços, adicionando '(a partir de)' para preços variáveis."""
    try:
        with current_app.app_context():
            servicos = Servico.query.filter_by(barbearia_id=barbearia_id).order_by(Servico.nome).all()
            if not servicos:
                return "Nenhum serviço cadastrado para esta barbearia."
            
            lista_formatada = []
            # Lista de nomes de serviços com preço variável (BASEADO NA SUA IMAGEM)
            servicos_a_partir_de = [
                "Platinado", "Luzes", "Coloração", "Pigmentação", 
                "Selagem", "Escova Progressiva", "Relaxamento", 
                "Alisamento", "Hidratação", "Reconstrução"
            ]
            
            for s in servicos:
                preco_str = f"R$ {s.preco:.2f}"
                # Adiciona a indicação se o nome do serviço estiver na lista
                if s.nome in servicos_a_partir_de:
                    preco_str += " (a partir de)"
                lista_formatada.append(f"{s.nome} ({s.duracao} min, {preco_str})")
                
            return f"Serviços disponíveis: {'; '.join(lista_formatada)}."
    except Exception as e:
        current_app.logger.error(f"Erro interno na ferramenta 'listar_servicos': {e}", exc_info=True)
        return f"Erro ao listar serviços: Ocorreu um erro interno."

# 🚀 FUNÇÃO WRAPPER: Chama a função unificada do utils.py
def calcular_horarios_disponiveis(barbearia_id: int, profissional_nome: str, dia: str) -> str:
    """
    Wrapper para a função utilitária. Busca o profissional e chama a lógica unificada.
    Retorna uma string formatada para a IA.
    """
    try:
        with current_app.app_context():
            profissional = Profissional.query.filter_by(
                barbearia_id=barbearia_id, 
                nome=profissional_nome
            ).first()
            
            if not profissional:
                return "Profissional não encontrado. Por favor, verifique o nome."
            
            # Determina o objeto datetime para o dia
            agora = datetime.now() # Naive por enquanto, a função util lida com timezone
            if dia.lower() == 'hoje':
                dia_dt = agora
            elif dia.lower() == 'amanhã':
                dia_dt = agora + timedelta(days=1)
            else:
                try:
                    # Tenta converter YYYY-MM-DD para datetime (naive)
                    dia_dt = datetime.strptime(dia, '%Y-%m-%d')
                except ValueError:
                    return "Formato de data inválido. Use 'hoje', 'amanhã' ou 'AAAA-MM-DD'."

            # Chama a função unificada de utils.py
            horarios_dt_list = calcular_horarios_disponiveis_util(profissional, dia_dt)
            
            # Formata a lista de datetimes (com timezone) para string H:M
            horarios_str_list = [h.strftime('%H:%M') for h in horarios_dt_list]
            
            # Usa strftime para formatar a data consistentemente (DD/MM/YYYY)
            dia_formatado = dia_dt.strftime('%d/%m/%Y') 
            
            return f"Horários disponíveis para {profissional_nome} em {dia_formatado}: {', '.join(horarios_str_list) or 'Nenhum horário encontrado.'}"
            
    except Exception as e:
        current_app.logger.error(f"Erro no wrapper 'calcular_horarios_disponiveis': {e}", exc_info=True)
        return "Desculpe, ocorreu um erro ao verificar os horários."

def criar_agendamento(barbearia_id: int, nome_cliente: str, telefone_cliente: str, data_hora: str, profissional_nome: str, servico_nome: str) -> str:
    # (Código original desta função preservado)
    try:
        with current_app.app_context():
            profissional = Profissional.query.filter_by(barbearia_id=barbearia_id, nome=profissional_nome).first()
            if not profissional:
                return "Profissional não encontrado."
                
            servico = Servico.query.filter_by(barbearia_id=barbearia_id, nome=servico_nome).first()
            if not servico:
                return "Serviço não encontrado."

            # Converte para datetime e torna naive para salvar no DB
            data_hora_dt = datetime.strptime(data_hora, '%Y-%m-%d %H:%M').replace(tzinfo=None) 
            
            novo_fim = data_hora_dt + timedelta(minutes=servico.duracao)
            inicio_dia = data_hora_dt.replace(hour=0, minute=0, second=0, microsecond=0)
            fim_dia = inicio_dia + timedelta(days=1) # Corrigido para pegar até o fim do dia

            ags = (
                Agendamento.query
                .options(joinedload(Agendamento.servico))
                .filter(
                    Agendamento.barbearia_id == barbearia_id,
                    Agendamento.profissional_id == profissional.id,
                    Agendamento.data_hora >= inicio_dia,
                    Agendamento.data_hora < fim_dia
                )
                .all()
            )
            # Compara naive com naive
            conflito = any(
                max(data_hora_dt, ag.data_hora) < min(novo_fim, ag.data_hora + timedelta(minutes=ag.servico.duracao))
                for ag in ags
            )
            if conflito:
                return "Conflito de horário. Por favor, escolha outro."

            novo_agendamento = Agendamento(
                nome_cliente=nome_cliente,
                telefone_cliente=telefone_cliente, # Recebido do webhook
                data_hora=data_hora_dt, # Salva naive
                profissional_id=profissional.id,
                servico_id=servico.id,
                barbearia_id=barbearia_id 
            )
            db.session.add(novo_agendamento)
            db.session.commit()
            # Formata data/hora para a mensagem de confirmação
            data_hora_formatada = data_hora_dt.strftime('%d/%m/%Y às %H:%M')
            return f"Agendamento criado com sucesso para {nome_cliente} em {data_hora_formatada} com {profissional_nome} para {servico_nome}." # Removido 'Confirmação enviada!'
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Erro na ferramenta 'criar_agendamento': {e}", exc_info=True)
        return f"Erro ao criar agendamento: {str(e)}" # Pode expor detalhes, talvez simplificar

# ---------------------------------------------------------------------
# DEFINIÇÃO DAS TOOLS (Atualizada)
# ---------------------------------------------------------------------

listar_profissionais_func = FunctionDeclaration(
    name="listar_profissionais",
    description="Lista todos os profissionais disponíveis no sistema.",
    parameters={ "type": "object", "properties": {}, "required": [] }
)
listar_servicos_func = FunctionDeclaration(
    name="listar_servicos",
    description="Lista todos os serviços disponíveis, incluindo duração e preço.",
    parameters={ "type": "object", "properties": {}, "required": [] }
)
calcular_horarios_disponiveis_func = FunctionDeclaration(
    name="calcular_horarios_disponiveis",
    description="Consulta horários disponíveis (slots de 30 min) para um profissional em um dia específico.",
    parameters={
        "type": "object",
        "properties": {
            "profissional_nome": {
                "type": "string",
                "description": "Nome exato do profissional (confirmado pela ferramenta listar_profissionais)"
            },
            "dia": {
                "type": "string",
                "description": "Dia no formato YYYY-MM-DD, ou as palavras 'hoje' ou 'amanhã'"
            }
        },
        "required": ["profissional_nome", "dia"]
    }
)

# 🚀 FERRAMENTA 'criar_agendamento' SEM o parâmetro 'telefone_cliente'
criar_agendamento_func = FunctionDeclaration(
    name="criar_agendamento",
    description="Cria um novo agendamento no sistema. O telefone do cliente é obtido automaticamente pelo sistema.",
    parameters={
        "type": "object",
        "properties": {
            "nome_cliente": {
                "type": "string",
                "description": "Nome do cliente (obtido na conversa)"
            },
            # "telefone_cliente": Removido da definição!
            "data_hora": {
                "type": "string",
                "description": "Data e hora exata do início do agendamento no formato YYYY-MM-DD HH:MM (ex: 2025-10-28 15:00)"
            },
            "profissional_nome": {
                "type": "string",
                "description": "Nome exato do profissional escolhido (confirmado pela ferramenta listar_profissionais)"
            },
            "servico_nome": {
                "type": "string",
                "description": "Nome exato do serviço escolhido (confirmado pela ferramenta listar_servicos)"
            }
        },
        # 'telefone_cliente' removido dos requeridos
        "required": ["nome_cliente", "data_hora", "profissional_nome", "servico_nome"] 
    }
)

# Agrupa as ferramentas
tools = Tool(
    function_declarations=[
        listar_profissionais_func,
        listar_servicos_func,
        calcular_horarios_disponiveis_func,
        criar_agendamento_func 
    ]
)

# --- Inicialização do Modelo Gemini (Mantida com 'gemini-pro-latest') ---
model = None 
try:
    model_name_to_use = 'models/gemini-pro-latest' 
    model = genai.GenerativeModel( model_name=model_name_to_use, tools=[tools], system_instruction=SYSTEM_INSTRUCTION_TEMPLATE )
    logging.info(f"Modelo Gemini ('{model_name_to_use}') inicializado com SUCESSO!")
except NotFound as nf_error:
    logging.error(f"ERRO CRÍTICO: Modelo Gemini '{model_name_to_use}' não encontrado: {nf_error}", exc_info=True)
except Exception as e:
    logging.error(f"ERRO CRÍTICO GERAL ao inicializar o modelo Gemini: {e}", exc_info=True)
