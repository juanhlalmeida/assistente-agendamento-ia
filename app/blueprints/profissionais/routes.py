# app/blueprints/profissionais/routes.py
import logging
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, abort
from app.models.tables import Profissional, Agendamento # Importa modelos necessários
from app.extensions import db
from flask_login import login_required, current_user # Para proteger e filtrar

# Cria o Blueprint 'profissionais' com prefixo /profissionais
bp = Blueprint('profissionais', __name__, url_prefix='/profissionais')

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# --- ROTA PRINCIPAL: LISTAR PROFISSIONAIS ---
@bp.route('/')
@login_required
def index():
    """Exibe a lista de profissionais da barbearia logada."""
    if not hasattr(current_user, 'barbearia_id') or not current_user.barbearia_id:
        flash('Erro: Usuário inválido ou não associado a uma barbearia.', 'danger')
        return redirect(url_for('auth.login')) # Ajuste 'auth.login' se necessário
        
    barbearia_id_logada = current_user.barbearia_id
    
    try:
        lista_profissionais = Profissional.query.filter_by(barbearia_id=barbearia_id_logada).order_by(Profissional.nome).all()
    except Exception as e:
        current_app.logger.error(f"Erro ao buscar profissionais para barbearia {barbearia_id_logada}: {e}", exc_info=True)
        flash('Ocorreu um erro ao carregar os profissionais.', 'danger')
        lista_profissionais = [] 

    return render_template('profissionais.html', profissionais=lista_profissionais)

# --- ROTA PARA ADICIONAR NOVO PROFISSIONAL ---
@bp.route('/novo', methods=['GET', 'POST'])
@login_required
def novo_profissional():
    """Exibe o formulário (GET) e processa a criação (POST)."""
    if not hasattr(current_user, 'barbearia_id') or not current_user.barbearia_id:
        flash('Erro: Usuário inválido ou não associado a uma barbearia.', 'danger')
        return redirect(url_for('auth.login'))
        
    barbearia_id_logada = current_user.barbearia_id

    if request.method == 'POST':
        nome = request.form.get('nome')

        if not nome:
            flash("O nome do profissional é obrigatório.", 'danger')
            return render_template('novo_profissional.html', form_data=request.form)
        else:
            try:
                # Verifica se já existe um profissional com este nome nesta barbearia
                existente = Profissional.query.filter_by(nome=nome, barbearia_id=barbearia_id_logada).first()
                if existente:
                    flash(f'Erro: Já existe um profissional chamado "{nome}".', 'danger')
                    return render_template('novo_profissional.html', form_data=request.form)

                novo = Profissional(
                    nome=nome,
                    barbearia_id=barbearia_id_logada 
                )
                db.session.add(novo)
                db.session.commit()
                flash(f'Profissional "{nome}" adicionado com sucesso!', 'success')
                return redirect(url_for('profissionais.index')) 
            except Exception as e:
                db.session.rollback()
                flash(f'Erro ao adicionar profissional: {str(e)}', 'danger')
                current_app.logger.error(f"Erro ao adicionar profissional: {e}", exc_info=True)
                return render_template('novo_profissional.html', form_data=request.form)

    # Método GET: exibe formulário vazio
    return render_template('novo_profissional.html', form_data={})

# --- ROTA PARA EDITAR PROFISSIONAL ---
@bp.route('/editar/<int:profissional_id>', methods=['GET', 'POST'])
@login_required
def editar_profissional(profissional_id):
    """Exibe o formulário preenchido (GET) e processa a atualização (POST)."""
    if not hasattr(current_user, 'barbearia_id') or not current_user.barbearia_id:
        flash('Erro: Usuário inválido ou não associado a uma barbearia.', 'danger')
        return redirect(url_for('auth.login'))

    barbearia_id_logada = current_user.barbearia_id

    profissional = Profissional.query.filter_by(id=profissional_id, barbearia_id=barbearia_id_logada).first()
    if not profissional:
        abort(404, description="Profissional não encontrado ou não pertence à sua barbearia.")

    if request.method == 'POST':
        nome = request.form.get('nome')

        if not nome:
            flash("O nome do profissional é obrigatório.", 'danger')
            return render_template('editar_profissional.html', profissional=profissional, form_data=request.form)
        else:
            try:
                 # Verifica se já existe OUTRO profissional com este nome nesta barbearia
                existente = Profissional.query.filter(
                    Profissional.nome == nome, 
                    Profissional.barbearia_id == barbearia_id_logada,
                    Profissional.id != profissional_id # Exclui o próprio profissional da verificação
                ).first()
                if existente:
                    flash(f'Erro: Já existe outro profissional chamado "{nome}".', 'danger')
                    return render_template('editar_profissional.html', profissional=profissional, form_data=request.form)

                profissional.nome = nome
                db.session.commit() 
                flash(f'Profissional "{nome}" atualizado com sucesso!', 'success')
                return redirect(url_for('profissionais.index')) 
            except Exception as e:
                db.session.rollback()
                flash(f'Erro ao atualizar profissional: {str(e)}', 'danger')
                current_app.logger.error(f"Erro ao atualizar profissional ID {profissional_id}: {e}", exc_info=True)
                return render_template('editar_profissional.html', profissional=profissional, form_data=request.form)

    # Método GET: exibe formulário preenchido
    form_data_preenchido = {'nome': profissional.nome}
    return render_template('editar_profissional.html', profissional=profissional, form_data=form_data_preenchido)

# --- ROTA PARA APAGAR PROFISSIONAL ---
@bp.route('/apagar/<int:profissional_id>', methods=['POST'])
@login_required
def apagar_profissional(profissional_id):
    """Apaga um profissional, SE não houver agendamentos associados."""
    if not hasattr(current_user, 'barbearia_id') or not current_user.barbearia_id:
        flash('Erro: Usuário inválido ou não associado a uma barbearia.', 'danger')
        return redirect(url_for('auth.login')) 
        
    barbearia_id_logada = current_user.barbearia_id

    profissional = Profissional.query.filter_by(id=profissional_id, barbearia_id=barbearia_id_logada).first()

    if not profissional:
        flash('Profissional não encontrado ou não pertence à sua barbearia.', 'danger')
        return redirect(url_for('profissionais.index'))

    # Verifica se existem agendamentos (passados ou futuros) para este profissional
    agendamentos_existentes = Agendamento.query.filter_by(
        profissional_id=profissional.id, 
        barbearia_id=barbearia_id_logada 
    ).count()

    if agendamentos_existentes > 0:
        flash(f'Erro: Não é possível apagar o profissional "{profissional.nome}", pois ele já foi utilizado em {agendamentos_existentes} agendamento(s). Considere editar o nome se ele não trabalha mais aqui.', 'danger')
        return redirect(url_for('profissionais.index'))
        
    # Se chegou aqui, é seguro apagar
    try:
        nome_profissional_apagado = profissional.nome 
        db.session.delete(profissional)
        db.session.commit()
        flash(f'Profissional "{nome_profissional_apagado}" apagado com sucesso!', 'warning')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao apagar profissional: {str(e)}', 'danger')
        current_app.logger.error(f"Erro ao apagar profissional ID {profissional_id}: {e}", exc_info=True)

    return redirect(url_for('profissionais.index'))