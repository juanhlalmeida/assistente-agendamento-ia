# app/routes.py
import os
import requests
import json
import logging
from flask import Blueprint, render_template, request, redirect, url_for, flash
from .models.tables import Agendamento, Profissional, Servico
from .extensions import db
from datetime import datetime, date, timedelta

# Configura o logging para vermos tudo na Render
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

bp = Blueprint('main', __name__)

# --- FUNÇÕES DO PAINEL WEB ---

def calcular_horarios_disponiveis(profissional, dia_selecionado):
    HORA_INICIO_TRABALHO = 9
    HORA_FIM_TRABALHO = 20
    INTERVALO_MINUTOS = 30
    horarios_disponiveis = []
    horario_iteracao = dia_selecionado.replace(hour=HORA_INICIO_TRABALHO, minute=0, second=0, microsecond=0)
    fim_do_dia = dia_selecionado.replace(hour=HORA_FIM_TRABALHO, minute=0, second=0, microsecond=0)
    agendamentos_do_dia = Agendamento.query.filter(Agendamento.profissional_id == profissional.id, db.func.date(Agendamento.data_hora) == dia_selecionado.date()).all()
    intervalos_ocupados = []
    for ag in agendamentos_do_dia:
        inicio_ocupado = ag.data_hora
        fim_ocupado = inicio_ocupado + timedelta(minutes=ag.servico.duracao)
        intervalos_ocupados.append((inicio_ocupado, fim_ocupado))
    while horario_iteracao < fim_do_dia:
        esta_ocupado = False
        for inicio, fim in intervalos_ocupados:
            if horario_iteracao >= inicio and horario_iteracao < fim:
                esta_ocupado = True
                break
        if not esta_ocupado and horario_iteracao > datetime.now():
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
            novo_fim = novo_inicio + timedelta(minutes=servico_selecionado.duracao)
            agendamentos_existentes = Agendamento.query.filter_by(profissional_id=profissional_id).all()
            conflito_encontrado = False
            for ag_existente in agendamentos_existentes:
                existente_inicio = ag_existente.data_hora
                existente_fim = existente_inicio + timedelta(minutes=ag_existente.servico.duracao)
                if max(novo_inicio, existente_inicio) < min(novo_fim, existente_fim):
                    conflito_encontrado = True
                    break
            if conflito_encontrado:
                flash('Erro: O profissional já está ocupado neste horário.', 'danger')
            else:
                novo_agendamento = Agendamento(
                    nome_cliente=nome_cliente, telefone_cliente=telefone_cliente, data_hora=novo_inicio,
                    profissional_id=int(profissional_id), servico_id=int(servico_id)
                )
                db.session.add(novo_agendamento)
                db.session.commit()
                flash('Agendamento criado com sucesso!', 'success')
        except Exception as e:
            flash(f'Ocorreu um erro ao processar o agendamento: {str(e)}', 'danger')
        return redirect(url_for('main.agenda', data=novo_inicio.strftime('%Y-%m-%d'), profissional_id=profissional_id))
    
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
    agendamentos_do_dia = Agendamento.query.filter(db.func.date(Agendamento.data_hora) == data_selecionada.date()).order_by(Agendamento.data_hora.asc()).all()
    return render_template(
        'agenda.html', agendamentos=agendamentos_do_dia, profissionais=profissionais, servicos=servicos,
        horarios_disponiveis=horarios_disponiveis, data_selecionada=data_selecionada, profissional_selecionado=profissional_selecionado
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
        return redirect(url_for('main.agenda', data=agendamento.data_hora.strftime('%Y-%m-%d'), profissional_id=agendamento.profissional_id))
    profissionais = Profissional.query.all()
    servicos = Servico.query.all()
    return render_template('editar_agendamento.html', agendamento=agendamento, profissionais=profissionais, servicos=servicos)

# --- ROTA DO WEBHOOK ATUALIZADA E AUTOCONTIDA ---
@bp.route('/webhook', methods=['GET', 'POST'])
def webhook():
    # Lógica de verificação (GET)
    if request.method == 'GET':
        VERIFY_TOKEN = os.getenv('WHATSAPP_VERIFY_TOKEN')
        mode = request.args.get('hub.mode', '')
        token = request.args.get('hub.verify_token', '')
        challenge = request.args.get('hub.challenge', '')
        if mode == 'subscribe' and token == VERIFY_TOKEN:
            logging.info('WEBHOOK VERIFICADO COM SUCESSO!')
            return challenge, 200
        else:
            logging.warning('FALHA NA VERIFICAÇÃO DO WEBHOOK')
            return 'Forbidden', 403

    # Lógica para receber e RESPONDER mensagens (POST)
    if request.method == 'POST':
        data = request.get_json()
        logging.info(f"PAYLOAD COMPLETO RECEBIDO: {data}")

        try:
            changes = data.get('entry', [{}])[0].get('changes', [{}])[0]
            value = changes.get('value', {})
            message = value.get('messages', [{}])[0]
            
            if message:
                from_number = message.get('from')
                msg_body = message.get('text', {}).get('body')
                profile_name = value.get('contacts', [{}])[0].get('profile', {}).get('name', 'Cliente')

                if from_number and msg_body:
                    logging.info(f"Extraído: De={from_number}, Mensagem='{msg_body}'")
                    
                    ACCESS_TOKEN = os.getenv('WHATSAPP_ACCESS_TOKEN')
                    PHONE_NUMBER_ID = os.getenv('WHATSAPP_PHONE_NUMBER_ID')
                    API_URL = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages"
                    
                    response_text = f"Olá, {profile_name}! Recebi sua mensagem: '{msg_body}'"
                    
                    payload = {"messaging_product": "whatsapp", "to": from_number, "text": {"body": response_text}}
                    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}", "Content-Type": "application/json"}
                    
                    logging.info(f"Enviando resposta para {from_number} com o ID {PHONE_NUMBER_ID}")
                    response = requests.post(API_URL, headers=headers, data=json.dumps(payload), timeout=10)
                    logging.info(f"Resposta da Meta: Status {response.status_code}, Conteúdo: {response.text}")
                    response.raise_for_status()

        except Exception as e:
            logging.error(f"Erro ao processar webhook ou enviar resposta: {e}", exc_info=True)

        return 'OK', 200

def init_app(app):
    app.register_blueprint(bp)