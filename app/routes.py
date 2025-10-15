# app/routes.py
import os
import logging
import google.generativeai as genai

from datetime import datetime, date, time, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app



from flask import Blueprint, render_template, request, redirect, url_for, flash
from sqlalchemy.orm import joinedload
from .services.ai_service import model as ai_model, tools_definitions



from .models.tables import Agendamento, Profissional, Servico
from .extensions import db
from .whatsapp_client import WhatsAppClient, sanitize_msisdn
from .services import ai_service  # Importamos o nosso novo cérebro de IA

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
bp = Blueprint('main', __name__)

# --- Armazenamento em memória para o histórico das conversas ---
# A chave será o número do usuário, e o valor será o objeto de chat do Gemini
conversation_history = {}

# --- FUNÇÕES DO PAINEL WEB (SEU CÓDIGO ORIGINAL, 100% PRESERVADO) ---

def _range_do_dia(dia_dt: datetime):
    inicio = datetime.combine(dia_dt.date(), time.min)
    fim = inicio + timedelta(days=1)
    return inicio, fim

def calcular_horarios_disponiveis(profissional: Profissional, dia_selecionado: datetime):
    HORA_INICIO_TRABALHO = 9
    HORA_FIM_TRABALHO = 20
    INTERVALO_MINUTOS = 30

    horarios_disponiveis = []
    horario_iteracao = dia_selecionado.replace(hour=HORA_INICIO_TRABALHO, minute=0, second=0, microsecond=0)
    fim_do_dia = dia_selecionado.replace(hour=HORA_FIM_TRABALHO, minute=0, second=0, microsecond=0)

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
        i = ag.data_hora
        f = i + timedelta(minutes=ag.servico.duracao)
        intervalos_ocupados.append((i, f))

    agora = datetime.now()
    while horario_iteracao < fim_do_dia:
        esta_ocupado = any(i <= horario_iteracao < f for i, f in intervalos_ocupados)
        if not esta_ocupado and horario_iteracao > agora:
            horarios_disponiveis.append(horario_iteracao)
        horario_iteracao += timedelta(minutes=INTERVALO_MINUTOS)

    return horarios_disponiveis

@bp.route('/agenda', methods=['GET', 'POST'])
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
        horarios_disponiveis = calcular_horarios_disponiveis(profissional_sel, data_sel)

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
def excluir_agendamento(agendamento_id):
    ag = Agendamento.query.get_or_44(agendamento_id)
    data_redirect = ag.data_hora.strftime('%Y-%m-%d')
    prof_redirect = ag.profissional_id
    db.session.delete(ag)
    db.session.commit()
    flash('Agendamento excluído com sucesso!', 'warning')
    return redirect(url_for('main.agenda', data=data_redirect, profissional_id=prof_redirect))

@bp.route('/agendamento/editar/<int:agendamento_id>', methods=['GET', 'POST'])
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

    profissionais = Profissional.query.all()
    servicos = Servico.query.all()
    return render_template('editar_agendamento.html',
                           agendamento=ag, profissionais=profissionais, servicos=servicos)

# --- WEBHOOK ATUALIZADO PARA ORQUESTRAR A CONVERSA COM A IA (FASE 4) ---
# app/routes.py

# ... (todo o seu código anterior, imports, funções do painel, etc.) ...

@bp.route('/webhook', methods=['POST'])
def webhook():
    if not ai_model:
        logging.error("MODELO DE IA NÃO INICIALIZADO.")
        return "OK", 200

    data = request.values
    logging.info("PAYLOAD RECEBIDO DA TWILIO: %s", data)

    try:
        msg_text = data.get('Body')
        from_number_raw = data.get('From')

        if not from_number_raw or not msg_text:
            return 'OK', 200

        from_number = sanitize_msisdn(from_number_raw)

        chat_session = ai_model.start_chat(history=conversation_history.get(from_number, []))

        response = chat_session.send_message(msg_text)

        # --- LÓGICA DE FUNCTION CALLING CORRIGIDA ---
        try:
            function_call = response.candidates[0].content.parts[0].function_call
        except (IndexError, AttributeError):
            function_call = None # A IA respondeu com texto normal

        if function_call and function_call.name:
            func_name = function_call.name
            args = {key: value for key, value in function_call.args.items()}

            logging.info(f"IA solicitou a ferramenta '{func_name}' com os argumentos: {args}")

            tool_function = tools_definitions.get(func_name)
            if tool_function:
                # ✅ CORREÇÃO: Usamos o 'current_app.app_context()' para aceder à base de dados
                with current_app.app_context():
                    result = tool_function(**args)

                response = chat_session.send_message(
                    part=genai.Part(function_response={'name': func_name, 'response': {'result': result}})
                )
            else:
                # ... (lógica de ferramenta desconhecida)
                pass

        reply_text = response.text

        client = WhatsAppClient()
        api_res = client.send_text(from_number, reply_text)

        if not api_res or api_res.get("status") not in ('queued', 'sent', 'delivered'):
             logging.error("Falha no envio da resposta da IA via Twilio: %s", api_res)

        conversation_history[from_number] = chat_session.history

    except Exception as e:
        logging.error("Erro no webhook da IA: %s", e, exc_info=True)

    return 'OK', 200