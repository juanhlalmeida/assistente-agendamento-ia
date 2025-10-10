# app/routes.py
import os
import json
import logging
from datetime import datetime, date, time, timedelta

import requests
from flask import Blueprint, render_template, request, redirect, url_for, flash
from sqlalchemy.orm import joinedload

from .models.tables import Agendamento, Profissional, Servico
from .extensions import db
from whatsapp_client import WhatsAppClient, sanitize_msisdn

# Logging básico (pode mover para a app factory depois)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
bp = Blueprint('main', __name__)

# ----------------- Helpers -----------------
def _range_do_dia(dia_dt: datetime) -> tuple[datetime, datetime]:
    """Retorna (início_do_dia, início_dia_seguinte) para usar em filtros >= e < (melhor uso de índice)."""
    inicio = datetime.combine(dia_dt.date(), time.min)
    fim = inicio + timedelta(days=1)
    return inicio, fim


# ----------------- Regras de agenda (painel web) -----------------
def calcular_horarios_disponiveis(profissional: Profissional, dia_selecionado: datetime):
    HORA_INICIO_TRABALHO = 9
    HORA_FIM_TRABALHO = 20
    INTERVALO_MINUTOS = 30

    horarios_disponiveis = []
    horario_iteracao = dia_selecionado.replace(hour=HORA_INICIO_TRABALHO, minute=0, second=0, microsecond=0)
    fim_do_dia = dia_selecionado.replace(hour=HORA_FIM_TRABALHO, minute=0, second=0, microsecond=0)

    # Busca apenas os agendamentos do profissional no dia, com join para evitar N+1
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
        inicio_ocupado = ag.data_hora
        fim_ocupado = inicio_ocupado + timedelta(minutes=ag.servico.duracao)
        intervalos_ocupados.append((inicio_ocupado, fim_ocupado))

    agora = datetime.now()
    while horario_iteracao < fim_do_dia:
        esta_ocupado = False
        for inicio_o, fim_o in intervalos_ocupados:
            if inicio_o <= horario_iteracao < fim_o:
                esta_ocupado = True
                break
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
            servico_selecionado = Servico.query.get(servico_id)
            if not servico_selecionado:
                raise ValueError("Serviço inválido.")

            novo_fim = novo_inicio + timedelta(minutes=servico_selecionado.duracao)

            # Busca do dia para o profissional, com join para pegar duração
            inicio_dia, fim_dia = _range_do_dia(novo_inicio)
            ags = (
                Agendamento.query
                .options(joinedload(Agendamento.servico))
                .filter(Agendamento.profissional_id == int(profissional_id))
                .filter(Agendamento.data_hora >= inicio_dia, Agendamento.data_hora < fim_dia)
                .all()
            )

            conflito = False
            for ag in ags:
                existente_inicio = ag.data_hora
                existente_fim = existente_inicio + timedelta(minutes=ag.servico.duracao)
                if max(novo_inicio, existente_inicio) < min(novo_fim, existente_fim):
                    conflito = True
                    break

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

    # GET
    data_selecionada_str = request.args.get('data', date.today().strftime('%Y-%m-%d'))
    profissional_selecionado_id = request.args.get('profissional_id')
    data_selecionada = datetime.strptime(data_selecionada_str, '%Y-%m-%d')

    profissionais = Profissional.query.all()
    servicos = Servico.query.all()
    horarios_disponiveis = []
    profissional_selecionado = None

    if profissional_selecionado_id:
        profissional_selecionado = Profissional.query.get(profissional_selecionado_id)
    elif profissionais:
        profissional_selecionado = profissionais[0]
        profissional_selecionado_id = profissional_selecionado.id

    if profissional_selecionado:
        horarios_disponiveis = calcular_horarios_disponiveis(profissional_selecionado, data_selecionada)

    # Lista do dia (todos os profissionais), ordenada
    inicio, fim = _range_do_dia(data_selecionada)
    agendamentos_do_dia = (
        Agendamento.query
        .options(joinedload(Agendamento.servico), joinedload(Agendamento.profissional))
        .filter(Agendamento.data_hora >= inicio, Agendamento.data_hora < fim)
        .order_by(Agendamento.data_hora.asc())
        .all()
    )

    return render_template(
        'agenda.html',
        agendamentos=agendamentos_do_dia,
        profissionais=profissionais,
        servicos=servicos,
        horarios_disponiveis=horarios_disponiveis,
        data_selecionada=data_selecionada,
        profissional_selecionado=profissional_selecionado
    )


@bp.route('/agendamento/excluir/<int:agendamento_id>', methods=['POST'])
def excluir_agendamento(agendamento_id):
    agendamento = Agendamento.query.get_or_404(agendamento_id)
    data_redirect = agendamento.data_hora.strftime('%Y-%m-%d')
    profissional_redirect = agendamento.profissional_id
    db.session.delete(agendamento)
    db.session.commit()
    flash('Agendamento excluído com sucesso!', 'warning')
    return redirect(url_for('main.agenda', data=data_redirect, profissional_id=profissional_redirect))


@bp.route('/agendamento/editar/<int:agendamento_id>', methods=['GET', 'POST'])
def editar_agendamento(agendamento_id):
    agendamento = Agendamento.query.get_or_404(agendamento_id)

    if request.method == 'POST':
        agendamento.nome_cliente = request.form.get('nome_cliente')
        agendamento.telefone_cliente = request.form.get('telefone_cliente')
        agendamento.data_hora = datetime.strptime(request.form.get('data_hora'), '%Y-%m-%dT%H:%M')
        agendamento.profissional_id = int(request.form.get('profissional_id'))
        agendamento.servico_id = int(request.form.get('servico_id'))
        db.session.commit()
        flash('Agendamento atualizado com sucesso!', 'success')
        return redirect(url_for('main.agenda',
                                data=agendamento.data_hora.strftime('%Y-%m-%d'),
                                profissional_id=agendamento.profissional_id))

    profissionais = Profissional.query.all()
    servicos = Servico.query.all()
    return render_template('editar_agendamento.html',
                           agendamento=agendamento,
                           profissionais=profissionais,
                           servicos=servicos)


# ----------------- Webhook WhatsApp (corrigido) -----------------
@bp.route('/webhook', methods=['GET', 'POST'])
def webhook():
    # Verificação (GET)
    if request.method == 'GET':
        VERIFY_TOKEN = os.getenv('WHATSAPP_VERIFY_TOKEN')
        mode = request.args.get('hub.mode', '')
        token = request.args.get('hub.verify_token', '')
        challenge = request.args.get('hub.challenge', '')
        if mode == 'subscribe' and token == VERIFY_TOKEN:
            logging.info('WEBHOOK VERIFICADO COM SUCESSO!')
            return challenge, 200
        logging.warning('FALHA NA VERIFICAÇÃO DO WEBHOOK')
        return 'Forbidden', 403

    # Recebimento e resposta (POST)
    data = request.get_json(silent=True) or {}
    logging.info("PAYLOAD COMPLETO RECEBIDO: %s", data)

    try:
        entry = (data.get('entry') or [{}])[0]
        changes = (entry.get('changes') or [{}])[0]
        value = changes.get('value') or {}
        message = (value.get('messages') or [{}])[0]

        if not message:
            return 'OK', 200

        from_number_raw = message.get('from')
        from_number = sanitize_msisdn(from_number_raw)
        msg_text = (message.get('text') or {}).get('body') or ''
        profile_name = (value.get('contacts') or [{}])[0].get('profile', {}).get('name', 'Cliente')

        if from_number and msg_text:
            client = WhatsAppClient()  # usa envs: WHATSAPP_ACCESS_TOKEN / WHATSAPP_PHONE_NUMBER_ID
            response_text = f"Olá, {profile_name}! Recebi sua mensagem: '{msg_text}'"
            api_res = client.send_text(from_number, response_text)

            if api_res.get("status") != "sent":
                logging.error("Falha no envio WhatsApp: %s", api_res)

    except Exception as e:
        logging.error("Erro ao processar webhook ou enviar resposta: %s", e, exc_info=True)

    return 'OK', 200


def init_app(app):
