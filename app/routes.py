# app/routes.py
import os
import logging
import pytz
import google.generativeai as genai
from datetime import datetime, date, time, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, abort
from sqlalchemy.orm import joinedload
# 🚀 CORREÇÃO: Importa 'User' mas não o usaremos para login no momento
from app.models.tables import Agendamento, Profissional, Servico, User 
# 🚀 ADICIONADO: Import de Barbearia
from app.models.tables import Barbearia
from app.extensions import db
from app.whatsapp_client import WhatsAppClient, sanitize_msisdn    
from app.services import ai_service 
from app.commands import reset_database_logic

# 🚀 CORREÇÃO: Removidas todas as importações do flask_login
# from flask_login import login_user, logout_user, login_required, current_user 

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
bp = Blueprint('main', __name__)

# --- Armazenamento em memória para o histórico das conversas ---
conversation_history = {}

# --- FUNÇÕES DE AUTENTICAÇÃO (DESABILITADAS) ---

@bp.route('/', methods=['GET', 'POST'])
def login():
    # 🚀 CORREÇÃO: Redireciona direto para a agenda, como era antes.
    return redirect(url_for('main.agenda'))


@bp.route('/logout')
def logout():
    # 🚀 CORREÇÃO: Rota de logout apenas redireciona para a agenda
    return redirect(url_for('main.agenda'))

# --- FUNÇÕES DO PAINEL WEB (CORRIGIDAS) ---
def _range_do_dia(dia_dt: datetime):
    inicio = datetime.combine(dia_dt.date(), time.min)
    fim = inicio + timedelta(days=1)
    return inicio, fim

def calcular_horarios_disponiveis_web(profissional: Profissional, dia_selecionado: datetime):
    # (Esta função está OK, sem mudanças)
    sao_paulo_tz = pytz.timezone('America/Sao_Paulo')
    HORA_INICIO_TRABALHO = 9
    HORA_FIM_TRABALHO = 20
    INTERVALO_MINUTOS = 30
    horarios_disponiveis = []
    horario_iteracao = sao_paulo_tz.localize(dia_selecionado.replace(hour=HORA_INICIO_TRABALHO, minute=0, second=0, microsecond=0))
    fim_do_dia = sao_paulo_tz.localize(dia_selecionado.replace(hour=HORA_FIM_TRABALHO, minute=0, second=0, microsecond=0))
    inicio, fim = _range_do_dia(dia_selecionado)
    agendamentos_do_dia = (
        Agendamento.query
        .options(joinedload(Agendamento.servico))
        .filter(Agendamento.profissional_id == profissional.id)
        .filter(Agendamento.data_hora >= inicio, Agendamento.data_hora < fim)
        .all()
    )
    intervalos_ocupados = []
    for ag in agendamentos_do_dia:
        inicio_ocupado = sao_paulo_tz.localize(ag.data_hora)
        fim_ocupado = inicio_ocupado + timedelta(minutes=ag.servico.duracao)
        intervalos_ocupados.append((inicio_ocupado, fim_ocupado))
    agora = datetime.now(sao_paulo_tz)
    while horario_iteracao < fim_do_dia:
        esta_ocupado = any(i <= horario_iteracao < f for i, f in intervalos_ocupados)
        if not esta_ocupado and horario_iteracao > agora:
            horarios_disponiveis.append(horario_iteracao)
        horario_iteracao += timedelta(minutes=INTERVALO_MINUTOS)
    return horarios_disponiveis


@bp.route('/agenda', methods=['GET', 'POST'])
# 🚀 CORREÇÃO: O decorador @login_required foi REMOVIDO daqui
def agenda():
    if request.method == 'POST':
        nome_cliente = request.form.get('nome_cliente')
        telefone_cliente = request.form.get('telefone_cliente')
        data_hora_str = request.form.get('data_hora')
        profissional_id = request.form.get('profissional_id')
        servico_id = request.form.get('servico_id')
        if not all([nome_cliente, telefone_cliente, data_hora_str, profissional_id, servico_id]):
            flash('Erro: Todos os campos são obrigatórios.', 'danger')
            return redirect(url_for('main.agenda'))
        try:
            novo_inicio = datetime.strptime(data_hora_str, '%Y-%m-%dT%H:%M')
            servico = Servico.query.get(servico_id)
            if not servico:
                raise ValueError("Serviço inválido.")
            novo_fim = novo_inicio + timedelta(minutes=servico.duracao)
            inicio_dia, fim_dia = _range_do_dia(novo_inicio)
            ags = (
                Agendamento.query
                .options(joinedload(Agendamento.servico))
                .filter(Agendamento.profissional_id == int(profissional_id))
                .filter(Agendamento.data_hora >= inicio_dia, Agendamento.data_hora < fim_dia)
                .all()
            )
            conflito = any(
                max(novo_inicio, ag.data_hora) < min(novo_fim, ag.data_hora + timedelta(minutes=ag.servico.duracao))
                for ag in ags
            )
            if conflito:
                flash('Erro: O profissional já está ocupado neste horário.', 'danger')
            else:
                novo_agendamento = Agendamento(
                    nome_cliente=nome_cliente,
                    telefone_cliente=telefone_cliente,
                    data_hora=novo_inicio,
                    profissional_id=int(profissional_id),
                    servico_id=int(servico_id),
                )
                db.session.add(novo_agendamento)
                db.session.commit()
                flash('Agendamento criado com sucesso!', 'success')
        except Exception as e:
            flash(f'Ocorreu um erro ao processar o agendamento: {str(e)}', 'danger')
        redirect_date = (novo_inicio if 'novo_inicio' in locals() else datetime.now()).strftime('%Y-%m-%d')
        return redirect(url_for('main.agenda', data=redirect_date, profissional_id=profissional_id))
    
    # Lógica GET
    data_sel_str = request.args.get('data', date.today().strftime('%Y-%m-%d'))
    profissional_sel_id = request.args.get('profissional_id')
    data_sel = datetime.strptime(data_sel_str, '%Y-%m-%d')
    profissionais = Profissional.query.all()
    servicos = Servico.query.all()
    horarios_disponiveis = []
    profissional_sel = None
    if profissional_sel_id:
        profissional_sel = Profissional.query.get(profissional_sel_id)
    elif profissionais:
        profissional_sel = profissionais[0]
        profissional_sel_id = profissional_sel.id
    if profissional_sel:
        horarios_disponiveis = calcular_horarios_disponiveis_web(profissional_sel, data_sel) 
    inicio, fim = _range_do_dia(data_sel)
    ags_dia = (
        Agendamento.query
        .options(joinedload(Agendamento.servico), joinedload(Agendamento.profissional))
        .filter(Agendamento.data_hora >= inicio, Agendamento.data_hora < fim)
        .order_by(Agendamento.data_hora.asc())
        .all()
    )
    return render_template(
        'agenda.html',
        agendamentos=ags_dia,
        profissionais=profissionais,
        servicos=servicos,
        horarios_disponiveis=horarios_disponiveis,
        data_selecionada=data_sel,
        profissional_selecionado=profissional_sel
    )

@bp.route('/agendamento/excluir/<int:agendamento_id>', methods=['POST'])
# 🚀 CORREÇÃO: O decorador @login_required foi REMOVIDO daqui
def excluir_agendamento(agendamento_id):
    ag = Agendamento.query.get_or_404(agendamento_id)
    data_redirect = ag.data_hora.strftime('%Y-%m-%d')
    prof_redirect = ag.profissional_id
    db.session.delete(ag)
    db.session.commit()
    flash('Agendamento excluído com sucesso!', 'warning')
    return redirect(url_for('main.agenda', data=redirect_date, profissional_id=prof_redirect))

@bp.route('/agendamento/editar/<int:agendamento_id>', methods=['GET', 'POST'])
# 🚀 CORREÇÃO: O decorador @login_required foi REMOVIDO daqui
def editar_agendamento(agendamento_id):
    ag = Agendamento.query.get_or_404(agendamento_id)
    if request.method == 'POST':
        ag.nome_cliente = request.form.get('nome_cliente')
        ag.telefone_cliente = request.form.get('telefone_cliente')
        ag.data_hora = datetime.strptime(request.form.get('data_hora'), '%Y-%m-%dT%H:%M')
        ag.profissional_id = int(request.form.get('profissional_id'))
        ag.servico_id = int(request.form.get('servico_id'))
        db.session.commit()
        flash('Agendamento atualizado com sucesso!', 'success')
        return redirect(url_for('main.agenda',
                                data=ag.data_hora.strftime('%Y-%m-%d'),
                                profissional_id=ag.profissional_id))
    
    # Lógica GET
    profissionais = Profissional.query.all()
    servicos = Servico.query.all()
    return render_template('editar_agendamento.html',
                           agendamento=ag, profissionais=profissionais, servicos=servicos)

# --- WEBHOOK (ATUALIZADO PARA MULTI-TENANCY) ---
@bp.route('/webhook', methods=['POST'])
def webhook():
    data = request.values
    logging.info("PAYLOAD RECEBIDO DA TWILIO: %s", data)
    
    try:
        msg_text = data.get('Body')
        from_number_raw = data.get('From')
        
        # 🚀 ALTERAÇÃO: Precisamos do número 'To' (Destinatário)
        # É este número que identifica a barbearia!
        to_number_raw = data.get('To') 
        
        if not from_number_raw or not msg_text or not to_number_raw:
            logging.warning("Webhook da Twilio recebido sem 'From', 'Body' ou 'To'.")
            return 'OK', 200
        
        from_number = sanitize_msisdn(from_number_raw)
        
        # 🚀 ALTERAÇÃO: Sanitiza o número da barbearia
        barbearia_phone = sanitize_msisdn(to_number_raw)

        # --- LÓGICA MULTI-TENANCY ---
        # 1. Encontrar a barbearia pelo número de telefone
        barbearia = Barbearia.query.filter_by(telefone_whatsapp=barbearia_phone).first()

        if not barbearia:
            logging.error(f"CRÍTICO: Nenhuma barbearia encontrada para o número {barbearia_phone}. Ignorando mensagem.")
            return 'OK', 200 # Respondemos OK para a Twilio não tentar de novo
        
        if barbearia.status_assinatura != 'ativa':
             logging.warning(f"Mensagem recebida para barbearia '{barbearia.nome_fantasia}' com assinatura '{barbearia.status_assinatura}'. Ignorando.")
             # (Opcional: enviar msg de "serviço suspenso" para o cliente)
             return 'OK', 200
             
        barbearia_id = barbearia.id
        logging.info(f"Mensagem roteada para Barbearia ID: {barbearia_id} ({barbearia.nome_fantasia})")
        # --- FIM DA LÓGICA ---
        
        if ai_service.model is None:
            logging.error("Modelo da IA não inicializado. Usando fallback.")
            reply_text = "Olá! Estamos com um problema técnico. Tente novamente em breve."
            client = WhatsAppClient()
            client.send_text(from_number, reply_text)
            return 'OK', 200
        
        # O histórico agora é por barbearia E por cliente
        history_key = f"{barbearia_id}:{from_number}"
        historico_atual = conversation_history.get(history_key, [])
        
        if not historico_atual:
            current_date_str = datetime.now().strftime('%d de %B de %Y')
            historico_atual = [
                {"role": "user", "parts": [f"[CONTEXTO DO SISTEMA: Hoje é {current_date_str}]"]},
                {"role": "model", "parts": ["Entendido. Como posso ajudá-lo?"]}
            ]
        
        chat_session = ai_service.model.start_chat(history=historico_atual)
        response = chat_session.send_message(msg_text)
        
        while response.parts and any(part.function_call for part in response.parts):
            for part in response.parts:
                if part.function_call:
                    func_name = part.function_call.name
                    args = dict(part.function_call.args)
                    
                    logging.info(f"IA solicitou a ferramenta '{func_name}' com os argumentos: {args}")
                    
                    # 🚀 ALTERAÇÃO: Passamos o 'barbearia_id' para TODAS as funções
                    
                    if func_name == 'criar_agendamento':
                        args['telefone_cliente'] = from_number
                        result = ai_service.criar_agendamento(barbearia_id=barbearia_id, **args)
                    elif func_name == 'listar_profissionais':
                        result = ai_service.listar_profissionais(barbearia_id=barbearia_id)
                    elif func_name == 'listar_servicos':
                        result = ai_service.listar_servicos(barbearia_id=barbearia_id)
                    elif func_name == 'calcular_horarios_disponiveis':
                        result = ai_service.calcular_horarios_disponiveis(barbearia_id=barbearia_id, **args)
                    else:
                        result = "Ferramenta desconhecida."
                    
                    function_response = genai.protos.Part(
                        function_response=genai.protos.FunctionResponse(
                            name=func_name,
                            response={"result": result}
                        )
                    )
                    response = chat_session.send_message([function_response])
        
        reply_text = response.text
        client = WhatsAppClient()
        api_res = client.send_text(from_number, reply_text)
        
        if api_res.get("status") not in ('queued', 'sent', 'delivered'):
            logging.error("Falha no envio da resposta da IA via Twilio: %s", api_res)
        
        conversation_history[history_key] = chat_session.history
        
    except Exception as e:
        logging.error("Erro no webhook da IA: %s", e, exc_info=True)
    
    return 'OK', 200

# --- ROTA SECRETA (Nenhuma mudança necessária) ---
@bp.route('/admin/reset-database/<string:secret_key>')
def reset_database(secret_key):
    expected_key = os.getenv('RESET_DB_KEY')
    
    if not expected_key or secret_key != expected_key:
        abort(404)
    
    try:
        logging.info("Iniciando o reset do banco de dados via rota segura...")
        reset_database_logic()
        logging.info("Banco de dados recriado com sucesso.")
        return "<h1>Banco de dados recriado com sucesso!</h1><p>Pode voltar para a <a href='/agenda'>página da agenda</a>.</p>"
    except Exception as e:
        logging.error("Erro ao recriar o banco de dados: %s", e, exc_info=True)
        return f"<h1>Ocorreu um erro ao recriar o banco de dados:</h1><p>{str(e)}</p>"


@bp.route('/admin/criar-primeiro-usuario/<secret_key>')
def criar_primeiro_usuario(secret_key):
    """
    Esta rota secreta tentará criar um usuário, mas está desabilitada
    porque o login foi desabilitado.
    """
    # 🚀 CORREÇÃO: Rota desabilitada pois o login está desabilitado.
    return "O sistema de login está temporariamente desabilitado. Esta rota não fará nada.", 200