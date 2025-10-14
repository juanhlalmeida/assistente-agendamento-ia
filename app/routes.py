# app/routes.py
import os
import logging
from flask import Blueprint, render_template, request, redirect, url_for, flash
from .models.tables import Agendamento, Profissional, Servico
from .extensions import db
from datetime import datetime, date, timedelta
from .services.whatsapp_service import send_whatsapp_message

# Configura o logging para vermos tudo na Render
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

bp = Blueprint('main', __name__)

# --- FUNÇÕES DO PAINEL WEB (SEM MUDANÇAS) ---

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

# --- WEBHOOK ATUALIZADO PARA O "DIALETO" DA TWILIO ---
@bp.route('/webhook', methods=['POST'])
def webhook():
    # A Twilio envia os dados como um formulário, não como JSON.
    data = request.values
    logging.info(f"PAYLOAD RECEBIDO DA TWILIO: {data}")

    # Os nomes dos campos da Twilio são 'Body' e 'From' (com letra maiúscula)
    received_text = data.get('Body', None)
    from_number_raw = data.get('From', None)
    
    # O número da Twilio vem como "whatsapp:+5513...", precisamos limpar o prefixo.
    if from_number_raw:
        from_number_cleaned = from_number_raw.replace('whatsapp:', '')
    else:
        from_number_cleaned = None

    if received_text and from_number_cleaned:
        logging.info(f"Extraído: De={from_number_cleaned}, Mensagem='{received_text}'")
        
        # Prepara a resposta (o "eco")
        response_text = f"Recebi sua mensagem via Twilio: '{received_text}'"
        
        # Usa nosso serviço para enviar a resposta de volta
        send_whatsapp_message(from_number_cleaned, response_text)
    else:
        logging.warning("Webhook da Twilio recebido, mas sem os campos 'Body' ou 'From'.")

    return 'OK', 200

def init_app(app):
    app.register_blueprint(bp)