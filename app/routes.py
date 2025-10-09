# app/routes.py
import os
from flask import Blueprint, render_template, request, redirect, url_for, flash
from .models.tables import Agendamento, Profissional, Servico
from .extensions import db
from datetime import datetime, date, timedelta

bp = Blueprint('main', __name__)

def calcular_horarios_disponiveis(profissional, dia_selecionado):
    """
    Calcula os horários disponíveis para um profissional em um dia específico.
    """
    HORA_INICIO_TRABALHO = 9
    HORA_FIM_TRABALHO = 20
    INTERVALO_MINUTOS = 30
    
    horarios_disponiveis = []
    horario_iteracao = dia_selecionado.replace(hour=HORA_INICIO_TRABALHO, minute=0, second=0, microsecond=0)
    fim_do_dia = dia_selecionado.replace(hour=HORA_FIM_TRABALHO, minute=0, second=0, microsecond=0)

    agendamentos_do_dia = Agendamento.query.filter(
        Agendamento.profissional_id == profissional.id,
        db.func.date(Agendamento.data_hora) == dia_selecionado.date()
    ).all()

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
        # Lógica para CRIAR um novo agendamento
        # ... (código de criação que já está funcionando) ...
        return redirect(url_for('main.agenda'))

    # Lógica para EXIBIR a página de agenda
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

# --- ROTA PARA EXCLUIR UM AGENDAMENTO ---
@bp.route('/agendamento/excluir/<int:agendamento_id>', methods=['POST'])
def excluir_agendamento(agendamento_id):
    agendamento = Agendamento.query.get_or_404(agendamento_id)
    data_redirect = agendamento.data_hora.strftime('%Y-%m-%d')
    profissional_redirect = agendamento.profissional_id
    db.session.delete(agendamento)
    db.session.commit()
    flash('Agendamento excluído com sucesso!', 'warning')
    return redirect(url_for('main.agenda', data=data_redirect, profissional_id=profissional_redirect))

# --- ROTA PARA EDITAR UM AGENDAMENTO ---
@bp.route('/agendamento/editar/<int:agendamento_id>', methods=['GET', 'POST'])
def editar_agendamento(agendamento_id):
    # ... (código de edição que já está funcionando) ...
    return "Edit page" # Placeholder

# --- ✅ NOVA ROTA DO WEBHOOK DO WHATSAPP ---
@bp.route('/webhook', methods=['GET', 'POST'])
def webhook():
    # Esta parte lida com a verificação de segurança da Meta (Fase 1)
    if request.method == 'GET':
        VERIFY_TOKEN = os.getenv('WHATSAPP_VERIFY_TOKEN')
        
        mode = request.args.get('hub.mode', '')
        token = request.args.get('hub.verify_token', '')
        challenge = request.args.get('hub.challenge', '')
        
        if mode == 'subscribe' and token == VERIFY_TOKEN:
            print('WEBHOOK VERIFICADO COM SUCESSO!')
            return challenge, 200
        else:
            print('FALHA NA VERIFICAÇÃO DO WEBHOOK')
            return 'Forbidden', 403

    # Esta parte receberá as mensagens dos usuários (Fase 2)
    if request.method == 'POST':
        data = request.get_json()
        print("MENSAGEM DO WHATSAPP RECEBIDA:", data)
        # Futuramente, aqui chamaremos a IA
        return 'OK', 200

def init_app(app):
    app.register_blueprint(bp)
