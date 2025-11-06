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

# --- ROTA: ADICIONAR BARBEARIA ---
@bp.route('/barbearias/novo', methods=['GET', 'POST'])
@login_required
@super_admin_required
def nova_barbearia():
    """Exibe o formulário (GET) e processa a criação (POST)."""
    
    if request.method == 'POST':
        nome_fantasia = request.form.get('nome_fantasia')
        telefone_whatsapp = request.form.get('telefone_whatsapp')
        status_assinatura = request.form.get('status_assinatura')
        admin_email = request.form.get('admin_email')
        admin_senha = request.form.get('admin_senha')
        
        # --- CORREÇÃO 1: Adicionar o 'get' dos novos campos ---
        meta_phone_number_id = request.form.get('meta_phone_number_id')
        meta_access_token = request.form.get('meta_access_token')
        # -----------------------------------------------------

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

        try:
            # --- CORREÇÃO 2: Corrigir Indentação e adicionar campos ao construtor ---
            nova_barbearia = Barbearia(
                nome_fantasia=nome_fantasia,
                telefone_whatsapp=telefone_whatsapp,
                status_assinatura=status_assinatura,
                # Estas linhas estavam fora do construtor e com indentação errada
                meta_phone_number_id=meta_phone_number_id,
                meta_access_token=meta_access_token
            )
            # --------------------------------------------------------------------
                        
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

    return render_template('superadmin/novo.html', form_data={})

# --- ROTA: EDITAR BARBEARIA ---
@bp.route('/barbearias/editar/<int:barbearia_id>', methods=['GET', 'POST'])
@login_required
@super_admin_required
def editar_barbearia(barbearia_id):
    barbearia = Barbearia.query.get_or_404(barbearia_id)
    
    if request.method == 'POST':
        nome_fantasia = request.form.get('nome_fantasia')
        telefone_whatsapp = request.form.get('telefone_whatsapp')
        status_assinatura = request.form.get('status_assinatura')
        
        # --- CORREÇÃO 3: Adicionar o 'get' dos novos campos ---
        meta_phone_number_id = request.form.get('meta_phone_number_id')
        meta_access_token = request.form.get('meta_access_token')
        # -----------------------------------------------------

        erros = []
        if not nome_fantasia: erros.append("O Nome Fantasia é obrigatório.")
        if not telefone_whatsapp: erros.append("O Telefone WhatsApp é obrigatório.")
        if not status_assinatura: erros.append("O Status da Assinatura é obrigatório.")

        # --- CORREÇÃO 4: Remover linhas inválidas ---
        # As linhas abaixo estavam aqui e causavam um erro de sintaxe.
        # 'meta_phone_number_id': barbearia.meta_phone_number_id,
        # 'meta_access_token': barbearia.meta_access_token
        # ----------------------------------------------
            
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
            
            # --- CORREÇÃO 5: Adicionar a ATUALIZAÇÃO dos campos ---
            barbearia.meta_phone_number_id = meta_phone_number_id
            barbearia.meta_access_token = meta_access_token
            # -----------------------------------------------------
            
            db.session.commit() 
            
            flash(f'Barbearia "{nome_fantasia}" atualizada com sucesso!', 'success')
            return redirect(url_for('superadmin.listar_barbearias'))

        except Exception as e:
            db.session.rollback() 
            current_app.logger.error(f"Erro ao editar barbearia {barbearia_id}: {e}", exc_info=True)
            flash(f'Erro ao salvar no banco de dados: {e}', 'danger')
            return render_template('superadmin/editar.html', barbearia=barbearia, form_data=request.form)

    # --- CORREÇÃO 6: Adicionar campos ao dicionário de pré-preenchimento ---
    form_data_preenchido = {
        'nome_fantasia': barbearia.nome_fantasia,
        'telefone_whatsapp': barbearia.telefone_whatsapp,
        'status_assinatura': barbearia.status_assinatura,
        # Adicionar os campos aqui para o HTML preencher os <input value="...">
        'meta_phone_number_id': barbearia.meta_phone_number_id,
        'meta_access_token': barbearia.meta_access_token
    }
    # --------------------------------------------------------------------
    return render_template('superadmin/editar.html', barbearia=barbearia, form_data=form_data_preenchido)

# --- 🚀 NOVA ROTA: APAGAR BARBEARIA ---
@bp.route('/barbearias/apagar/<int:barbearia_id>', methods=['POST'])
@login_required
@super_admin_required
def apagar_barbearia(barbearia_id):
    """Apaga uma barbearia (e todos os dados associados em cascata)."""
    
    # REGRA DE NEGÓCIO: Impedir apagar a barbearia ID 1 (Principal/Sandbox)
    if barbearia_id == 1:
        flash('Erro: Não é permitido apagar a barbearia principal (ID 1) ligada ao Sandbox.', 'danger')
        return redirect(url_for('superadmin.listar_barbearias'))

    barbearia = Barbearia.query.get_or_404(barbearia_id)
    nome_barbearia = barbearia.nome_fantasia

    try:
        # Graças ao cascade="all, delete-orphan" nos modelos:
        # Apagar a barbearia irá apagar automaticamente em cascata:
        # - Usuários (Users)
        # - Profissionais
        # - Serviços
        # - Agendamentos
        # ... todos associados a esta barbearia.
        
        db.session.delete(barbearia)
        db.session.commit()
        flash(f'Barbearia "{nome_barbearia}" e TODOS os seus dados associados foram apagados com sucesso!', 'warning')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Erro ao apagar barbearia {barbearia_id}: {e}", exc_info=True)
        flash(f'Erro ao apagar barbearia (verifique logs): {e}', 'danger')

    return redirect(url_for('superadmin.listar_barbearias'))