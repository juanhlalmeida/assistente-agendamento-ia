# app/blueprints/superadmin/routes.py
import logging
from functools import wraps
from flask import Blueprint, render_template, redirect, url_for, flash, current_app, abort, request
from app.models.tables import Barbearia, User # type: ignore
from app.extensions import db
from flask_login import login_required, current_user 
from werkzeug.security import generate_password_hash

# Cria o Blueprint 'superadmin' com prefixo /superadmin
bp = Blueprint('superadmin', __name__, url_prefix='/superadmin')

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# --- DECORATOR PARA PROTEGER ROTAS SUPER ADMIN ---
def super_admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not hasattr(current_user, 'role') or current_user.role != 'super_admin':
            flash('Acesso não autorizado.', 'danger')
            return redirect(url_for('main.login')) 
        return f(*args, **kwargs)
    return decorated_function
# -------------------------------------------------

# --- ROTA: LISTAR BARBEARIAS ---
@bp.route('/barbearias') 
@login_required
@super_admin_required 
def listar_barbearias():
    """Exibe a lista de todas as barbearias cadastradas."""
    try:
        lista_barbearias = Barbearia.query.order_by(Barbearia.nome_fantasia).all()
    except Exception as e:
        current_app.logger.error(f"Erro ao buscar lista de barbearias: {e}", exc_info=True)
        flash('Ocorreu um erro ao carregar a lista de barbearias.', 'danger')
        lista_barbearias = [] 

    return render_template('superadmin/barbearias.html', barbearias=lista_barbearias)

# --- ROTA: ADICIONAR BARBEARIA (CORRIGIDA) ---
@bp.route('/barbearias/novo', methods=['GET', 'POST'])
@login_required
@super_admin_required
def nova_barbearia():
    """Exibe o formulário (GET) e processa a criação (POST)."""
    
    if request.method == 'POST':
        # --- 1. Obter Dados do Formulário ---
        nome_fantasia = request.form.get('nome_fantasia')
        telefone_whatsapp = request.form.get('telefone_whatsapp')
        status_assinatura = request.form.get('status_assinatura')
        admin_email = request.form.get('admin_email')
        admin_senha = request.form.get('admin_senha')

        # --- 2. Validar Dados ---
        erros = []
        if not nome_fantasia: erros.append("O Nome Fantasia é obrigatório.")
        if not telefone_whatsapp: erros.append("O Telefone WhatsApp é obrigatório.")
        if not status_assinatura: erros.append("O Status da Assinatura é obrigatório.")
        if not admin_email: erros.append("O Email do Admin é obrigatório.")
        if not admin_senha: erros.append("A Senha do Admin é obrigatória.")
            
        if telefone_whatsapp and Barbearia.query.filter_by(telefone_whatsapp=telefone_whatsapp).first():
            erros.append(f"O telefone {telefone_whatsapp} já está em uso por outra barbearia.")
        if admin_email and User.query.filter_by(email=admin_email).first():
            erros.append(f"O email {admin_email} já está em uso por outro usuário.")

        if erros:
            for erro in erros:
                flash(erro, 'danger')
            return render_template('superadmin/novo.html', form_data=request.form)

        # --- 3. Criar os Registos no Banco ---
        try:
            nova_barbearia = Barbearia(
                nome_fantasia=nome_fantasia,
                telefone_whatsapp=telefone_whatsapp,
                status_assinatura=status_assinatura
            )
            db.session.add(nova_barbearia)
            db.session.flush() 

            novo_admin = User(
                email=admin_email,
                nome=f"Admin {nome_fantasia}", 
                role='admin',
                barbearia_id=nova_barbearia.id 
            )
            novo_admin.set_password(admin_senha) 
            db.session.add(novo_admin)
            
            db.session.commit()
            
            flash(f'Barbearia "{nome_fantasia}" e seu admin foram criados com sucesso!', 'success')
            return redirect(url_for('superadmin.listar_barbearias'))

        except Exception as e:
            db.session.rollback() 
            current_app.logger.error(f"Erro ao criar nova barbearia: {e}", exc_info=True)
            flash(f'Erro ao salvar no banco de dados: {e}', 'danger')
            return render_template('superadmin/novo.html', form_data=request.form)

    # --- 🚀 CORREÇÃO: Adicionado o return para o método GET ---
    # Apenas mostra o formulário de adição vazio
    return render_template('superadmin/novo.html', form_data={})

# --- ROTA: EDITAR BARBEARIA ---
# (Código da rota editar_barbearia que já funcionava)
@bp.route('/barbearias/editar/<int:barbearia_id>', methods=['GET', 'POST'])
@login_required
@super_admin_required
def editar_barbearia(barbearia_id):
    barbearia = Barbearia.query.get_or_404(barbearia_id)
    
    if request.method == 'POST':
        nome_fantasia = request.form.get('nome_fantasia')
        telefone_whatsapp = request.form.get('telefone_whatsapp')
        status_assinatura = request.form.get('status_assinatura')
        
        erros = []
        if not nome_fantasia: erros.append("O Nome Fantasia é obrigatório.")
        if not telefone_whatsapp: erros.append("O Telefone WhatsApp é obrigatório.")
        if not status_assinatura: erros.append("O Status da Assinatura é obrigatório.")
            
        if telefone_whatsapp:
            existente = Barbearia.query.filter(
                Barbearia.telefone_whatsapp == telefone_whatsapp,
                Barbearia.id != barbearia_id 
            ).first()
            if existente:
                erros.append(f"O telefone {telefone_whatsapp} já está em uso por outra barbearia.")

        if erros:
            for erro in erros:
                flash(erro, 'danger')
            return render_template('superadmin/editar.html', barbearia=barbearia, form_data=request.form)

        try:
            barbearia.nome_fantasia = nome_fantasia
            barbearia.telefone_whatsapp = telefone_whatsapp
            barbearia.status_assinatura = status_assinatura
            
            db.session.commit() 
            
            flash(f'Barbearia "{nome_fantasia}" atualizada com sucesso!', 'success')
            return redirect(url_for('superadmin.listar_barbearias'))

        except Exception as e:
            db.session.rollback() 
            current_app.logger.error(f"Erro ao editar barbearia {barbearia_id}: {e}", exc_info=True)
            flash(f'Erro ao salvar no banco de dados: {e}', 'danger')
            return render_template('superadmin/editar.html', barbearia=barbearia, form_data=request.form)

    # --- Método GET ---
    form_data_preenchido = {
        'nome_fantasia': barbearia.nome_fantasia,
        'telefone_whatsapp': barbearia.telefone_whatsapp,
        'status_assinatura': barbearia.status_assinatura
    }
    return render_template('superadmin/editar.html', barbearia=barbearia, form_data=form_data_preenchido)