# app/blueprints/main/routes.py
import logging
import pytz
from datetime import datetime, date, time, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, abort
from sqlalchemy.orm import joinedload

# Imports necessários para estas rotas
from app.models.tables import Agendamento, Profissional, Servico, User 
from app.extensions import db
from flask_login import login_required, current_user 

# Cria o Blueprint chamado 'main'
bp = Blueprint('main', __name__)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# --- FUNÇÕES AUXILIARES ---
# (Movidas do routes.py original para cá)
def _range_do_dia(dia_dt: datetime):
    inicio = datetime.combine(dia_dt.date(), time.min)
    fim = inicio + timedelta(days=1)
    return inicio, fim

def calcular_horarios_disponiveis_web(profissional: Profissional, dia_selecionado: datetime):
    sao_paulo_tz = pytz.timezone('America/Sao_Paulo')
    HORA_INICIO_TRABALHO = 9
    HORA_FIM_TRABALHO = 20
    INTERVALO_MINUTOS = 30
    horarios_disponiveis = []
    # Garante que estamos a trabalhar com a data sem hora antes de localizar
    dia_base = datetime.combine(dia_selecionado.date(), time.min) 
    horario_iteracao = sao_paulo_tz.localize(dia_base.replace(hour=HORA_INICIO_TRABALHO))
    fim_do_dia = sao_paulo_tz.localize(dia_base.replace(hour=HORA_FIM_TRABALHO))
    
    inicio_query, fim_query = _range_do_dia(dia_selecionado)
    
    agendamentos_do_dia = (
        Agendamento.query
        .options(joinedload(Agendamento.servico))
        .filter(Agendamento.profissional_id == profissional.id) 
        .filter(Agendamento.data_hora >= inicio_query, Agendamento.data_hora < fim_query)
        .all()
    )
    intervalos_ocupados = []
    for ag in agendamentos_do_dia:
        # Garante que a data/hora do agendamento é comparada com timezone
        inicio_ocupado = sao_paulo_tz.localize(ag.data_hora) if ag.data_hora.tzinfo is None else ag.data_hora.astimezone(sao_paulo_tz)
        fim_ocupado = inicio_ocupado + timedelta(minutes=ag.servico.duracao)
        intervalos_ocupados.append((inicio_ocupado, fim_ocupado))
        
    agora = datetime.now(sao_paulo_tz)
    
    while horario_iteracao < fim_do_dia:
        esta_ocupado = any(i <= horario_iteracao < f for i, f in intervalos_ocupados)
        # Compara horários com timezone
        if not esta_ocupado and horario_iteracao > agora:
            horarios_disponiveis.append(horario_iteracao) 
        horario_iteracao += timedelta(minutes=INTERVALO_MINUTOS)
    return horarios_disponiveis

# --- ROTAS PRINCIPAIS DO PAINEL ---

@bp.route('/agenda', methods=['GET', 'POST'])
@login_required 
def agenda():
    # --- LÓGICA MULTI-TENANCY ---
    if not hasattr(current_user, 'role'):
         flash('Erro de configuração da conta de usuário.', 'danger')
         logout_user() # Importar logout_user se necessário aqui
         return redirect(url_for('auth.login')) # Corrigido para auth.login

    if current_user.role == 'super_admin':
         flash('Área restrita para administradores de barbearia.', 'warning')
         return redirect(url_for('auth.login')) 

    barbearia_id_logada = current_user.barbearia_id
    if not barbearia_id_logada:
        flash('Erro: Usuário não associado a uma barbearia.', 'danger')
        logout_user() 
        return redirect(url_for('auth.login'))
    # --- FIM DA LÓGICA ---

    if request.method == 'POST':
        nome_cliente = request.form.get('nome_cliente')
        telefone_cliente = request.form.get('telefone_cliente')
        data_hora_str = request.form.get('data_hora')
        profissional_id = request.form.get('profissional_id')
        servico_id = request.form.get('servico_id')
        
        if not all([nome_cliente, telefone_cliente, data_hora_str, profissional_id, servico_id]):
            flash('Erro: Todos os campos são obrigatórios.', 'danger')
            return redirect(url_for('main.agenda')) # Mantém main.agenda aqui
            
        try:
            profissional = Profissional.query.filter_by(id=profissional_id, barbearia_id=barbearia_id_logada).first()
            if not profissional:
                flash('Profissional inválido ou não pertence à sua barbearia.', 'danger')
                raise ValueError("Profissional inválido.")

            servico = Servico.query.filter_by(id=servico_id, barbearia_id=barbearia_id_logada).first()
            if not servico:
                 flash('Serviço inválido ou não pertence à sua barbearia.', 'danger')
                 raise ValueError("Serviço inválido.")
            
            novo_inicio = datetime.strptime(data_hora_str, '%Y-%m-%dT%H:%M')
            # Torna o datetime 'naive' (sem timezone) para guardar no DB consistentemente
            novo_inicio = novo_inicio.replace(tzinfo=None) 
            
            novo_fim = novo_inicio + timedelta(minutes=servico.duracao)
            inicio_dia, fim_dia = _range_do_dia(novo_inicio)

            ags = (
                Agendamento.query
                .options(joinedload(Agendamento.servico))
                .filter(
                    Agendamento.barbearia_id == barbearia_id_logada, 
                    Agendamento.profissional_id == profissional.id,
                    Agendamento.data_hora >= inicio_dia, 
                    Agendamento.data_hora < fim_dia
                )
                .all()
            )
            conflito = any(
                # Compara datetimes 'naive'
                max(novo_inicio, ag.data_hora) < min(novo_fim, ag.data_hora + timedelta(minutes=ag.servico.duracao))
                for ag in ags
            )

            if conflito:
                flash('Erro: O profissional já está ocupado neste horário.', 'danger')
            else:
                novo_agendamento = Agendamento(
                    nome_cliente=nome_cliente,
                    telefone_cliente=telefone_cliente,
                    data_hora=novo_inicio, # Salva como 'naive'
                    profissional_id=profissional.id,
                    servico_id=servico.id,
                    barbearia_id=barbearia_id_logada 
                )
                db.session.add(novo_agendamento)
                db.session.commit()
                flash('Agendamento criado com sucesso!', 'success')
        except ValueError as ve: 
             pass 
        except Exception as e:
            db.session.rollback() 
            flash(f'Ocorreu um erro ao processar o agendamento: {str(e)}', 'danger')
            
        redirect_date_str = (novo_inicio if 'novo_inicio' in locals() else datetime.now()).strftime('%Y-%m-%d')
        prof_id_redirect = profissional_id if 'profissional_id' in locals() and profissional_id else None 
        
        if prof_id_redirect:
             prof_check = Profissional.query.filter_by(id=prof_id_redirect, barbearia_id=barbearia_id_logada).first()
             if not prof_check:
                  prof_id_redirect = None 

        return redirect(url_for('main.agenda', data=redirect_date_str, profissional_id=prof_id_redirect))
    
    # --- Lógica GET (Filtros Multi-Tenancy) ---
    data_sel_str = request.args.get('data', date.today().strftime('%Y-%m-%d'))
    profissional_sel_id = request.args.get('profissional_id')
    try:
        data_sel = datetime.strptime(data_sel_str, '%Y-%m-%d')
    except ValueError:
        flash('Data inválida fornecida.', 'warning')
        data_sel = datetime.combine(date.today(), time.min) 
        data_sel_str = data_sel.strftime('%Y-%m-%d')

    profissionais = Profissional.query.filter_by(barbearia_id=barbearia_id_logada).order_by(Profissional.nome).all()
    servicos = Servico.query.filter_by(barbearia_id=barbearia_id_logada).order_by(Servico.nome).all()
    
    horarios_disponiveis = []
    profissional_sel = None

    if profissional_sel_id:
        profissional_sel = Profissional.query.filter_by(id=profissional_sel_id, barbearia_id=barbearia_id_logada).first()
        if not profissional_sel and profissionais:
             profissional_sel = profissionais[0]
    elif profissionais: 
        profissional_sel = profissionais[0]

    if profissional_sel:
        horarios_disponiveis = calcular_horarios_disponiveis_web(profissional_sel, data_sel) 
        
    inicio_query, fim_query = _range_do_dia(data_sel)
    ags_dia = (
        Agendamento.query
        .options(joinedload(Agendamento.servico), joinedload(Agendamento.profissional))
        .filter(
            Agendamento.barbearia_id == barbearia_id_logada, 
            Agendamento.data_hora >= inicio_query, 
            Agendamento.data_hora < fim_query
        )
        .filter(Agendamento.profissional_id == profissional_sel.id if profissional_sel else True) 
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
@login_required 
def excluir_agendamento(agendamento_id):
    barbearia_id_logada = current_user.barbearia_id
    ag = Agendamento.query.filter_by(id=agendamento_id, barbearia_id=barbearia_id_logada).first_or_404("Agendamento não encontrado ou não pertence à sua barbearia.")
    
    data_redirect = ag.data_hora.strftime('%Y-%m-%d')
    prof_redirect = ag.profissional_id
    try:
        db.session.delete(ag)
        db.session.commit()
        flash('Agendamento excluído com sucesso!', 'warning')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao excluir agendamento: {str(e)}', 'danger')
        
    return redirect(url_for('main.agenda', data=data_redirect, profissional_id=prof_redirect))

@bp.route('/agendamento/editar/<int:agendamento_id>', methods=['GET', 'POST'])
@login_required 
def editar_agendamento(agendamento_id):
    barbearia_id_logada = current_user.barbearia_id
    ag = Agendamento.query.filter_by(id=agendamento_id, barbearia_id=barbearia_id_logada).first_or_404("Agendamento não encontrado ou não pertence à sua barbearia.")
   
    if request.method == 'POST':
        try:
            novo_profissional_id = int(request.form.get('profissional_id'))
            novo_servico_id = int(request.form.get('servico_id'))
            
            prof = Profissional.query.filter_by(id=novo_profissional_id, barbearia_id=barbearia_id_logada).first()
            serv = Servico.query.filter_by(id=novo_servico_id, barbearia_id=barbearia_id_logada).first()
            
            if not prof or not serv:
                 flash('Profissional ou Serviço inválido para esta barbearia.', 'danger')
                 raise ValueError("Profissional ou Serviço inválido.")

            ag.nome_cliente = request.form.get('nome_cliente')
            ag.telefone_cliente = request.form.get('telefone_cliente')
            
            data_hora_naive = datetime.strptime(request.form.get('data_hora'), '%Y-%m-%dT%H:%M').replace(tzinfo=None)
            ag.data_hora = data_hora_naive
            
            ag.profissional_id = novo_profissional_id
            ag.servico_id = novo_servico_id
            
            db.session.commit()
            flash('Agendamento atualizado com sucesso!', 'success')
            return redirect(url_for('main.agenda',
                                    data=ag.data_hora.strftime('%Y-%m-%d'),
                                    profissional_id=ag.profissional_id))
        except ValueError as ve:
             pass
        except Exception as e:
             db.session.rollback()
             flash(f'Erro ao atualizar agendamento: {str(e)}', 'danger')
             return redirect(url_for('main.editar_agendamento', agendamento_id=agendamento_id))

    profissionais = Profissional.query.filter_by(barbearia_id=barbearia_id_logada).order_by(Profissional.nome).all()
    servicos = Servico.query.filter_by(barbearia_id=barbearia_id_logada).order_by(Servico.nome).all()
    
    return render_template('editar_agendamento.html',
                           agendamento=ag, profissionais=profissionais, servicos=servicos)