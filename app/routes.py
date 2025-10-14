# app/routes.py
import os
import logging
from datetime import datetime, date, time, timedelta

from flask import Blueprint, render_template, request, redirect, url_for, flash
from sqlalchemy.orm import joinedload

from .models.tables import Agendamento, Profissional, Servico
from .extensions import db
# Mantemos a sua abstração, mas precisaremos ajustar o whatsapp_client.py depois
from .whatsapp_client import WhatsAppClient, sanitize_msisdn 

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
bp = Blueprint('main', __name__)

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
    ag = Agendamento.query.get_or_404(agendamento_id)
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

# --- WEBHOOK ATUALIZADO PARA O "DIALETO" DA TWILIO ---
@bp.route('/webhook', methods=['POST'])
def webhook():
    # A verificação GET da Meta não é usada pela Twilio, então removemos essa parte.
    
    # 1. Lemos os dados como Formulário Web
    data = request.values
    logging.info("PAYLOAD RECEBIDO DA TWILIO: %s", data)

    try:
        # 2. Usamos os nomes de campo da Twilio ('From', 'Body')
        from_number_raw = data.get('From')
        msg_text = data.get('Body')
        
        if not from_number_raw or not msg_text:
            logging.warning("Webhook da Twilio recebido sem 'From' ou 'Body'.")
            return 'OK', 200

        # 3. Usamos a sua função para limpar o número
        from_number = sanitize_msisdn(from_number_raw)
        
        # 4. Usamos o seu WhatsAppClient (que precisará ser ajustado para a Twilio)
        client = WhatsAppClient()
        
        # Por agora, uma resposta de eco simples
        response_text = f"Olá! Recebi sua mensagem via Twilio: '{msg_text}'"
        
        api_res = client.send_text(from_number, response_text)
        
        if not api_res or api_res.get("status") not in ('queued', 'sent', 'delivered'):
             logging.error("Falha no envio via Twilio: %s", api_res)

    except Exception as e:
        logging.error("Erro no webhook da Twilio: %s", e, exc_info=True)

    return 'OK', 200

def init_app(app):
    app.register_blueprint(bp)