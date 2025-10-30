# app/blueprints/superadmin/routes.py
import logging
from functools import wraps
# 🚀 ADICIONADO 'request', 'redirect', 'flash'
from flask import Blueprint, render_template, redirect, url_for, flash, current_app, abort, request
# 🚀 ADICIONADO 'User'
from app.models.tables import Barbearia, User 
from app.extensions import db
from flask_login import login_required, current_user 
# 🚀 ADICIONADO 'generate_password_hash' para criar a senha do novo admin
from werkzeug.security import generate_password_hash

# Cria o Blueprint 'superadmin' com prefixo /superadmin
bp = Blueprint('superadmin', __name__, url_prefix='/superadmin')

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# --- DECORATOR PARA PROTEGER ROTAS SUPER ADMIN ---
# (Preservado como estava)
def super_admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not hasattr(current_user, 'role') or current_user.role != 'super_admin':
            flash('Acesso não autorizado.', 'danger')
            return redirect(url_for('main.login')) 
        return f(*args, **kwargs)
    return decorated_function
# -------------------------------------------------

# --- ROTA PRINCIPAL: LISTAR BARBEARIAS ---
# (Preservada como estava)
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

# --- 🚀 NOVA ROTA: ADICIONAR BARBEARIA ---
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


# --- 🚀 NOVA ROTA: EDITAR BARBEARIA ---
@bp.route('/barbearias/editar/<int:barbearia_id>', methods=['GET', 'POST'])
@login_required
@super_admin_required
def editar_barbearia(barbearia_id):
    """Exibe o formulário (GET) e processa a atualização (POST) de uma barbearia."""
    
    # Busca a barbearia específica no banco
    barbearia = Barbearia.query.get_or_404(barbearia_id)
    
    # (Opcional) Busca o admin principal desta barbearia, se quisermos editar o email
    # user_admin = User.query.filter_by(barbearia_id=barbearia.id, role='admin').first()

    if request.method == 'POST':
        # --- 1. Obter Dados do Formulário ---
        nome_fantasia = request.form.get('nome_fantasia')
        telefone_whatsapp = request.form.get('telefone_whatsapp')
        status_assinatura = request.form.get('status_assinatura')

        # --- 2. Validar Dados ---
        erros = []
        if not nome_fantasia:
            erros.append("O Nome Fantasia é obrigatório.")
        if not telefone_whatsapp:
            erros.append("O Telefone WhatsApp é obrigatório.")
        if not status_assinatura:
            erros.append("O Status da Assinatura é obrigatório.")
        if not admin_email:
            erros.append("O Email do Admin é obrigatório.")
        if not admin_senha:
            erros.append("A Senha do Admin é obrigatória.")
            
        # Verifica se telefone ou email já existem
        if telefone_whatsapp and Barbearia.query.filter_by(telefone_whatsapp=telefone_whatsapp).first():
            erros.append(f"O telefone {telefone_whatsapp} já está em uso por outra barbearia.")
        if admin_email and User.query.filter_by(email=admin_email).first():
            erros.append(f"O email {admin_email} já está em uso por outro usuário.")

        if erros:
            for erro in erros:
                flash(erro, 'danger')
            # Re-renderiza o formulário com os dados que o usuário já digitou
            return render_template('superadmin/novo.html', form_data=request.form)

        # --- 3. Criar os Registos no Banco ---
        try:
            # Cria a Barbearia
            nova_barbearia = Barbearia(
                nome_fantasia=nome_fantasia,
                telefone_whatsapp=telefone_whatsapp,
                status_assinatura=status_assinatura
            )
            db.session.add(nova_barbearia)
            # Precisamos do ID da barbearia para associar ao usuário
            db.session.flush() 

            # Cria o Usuário Admin para esta barbearia
            novo_admin = User(
                email=admin_email,
                nome=f"Admin {nome_fantasia}", # Nome padrão
                role='admin',
                barbearia_id=nova_barbearia.id # Associa ao ID da barbearia
            )
            novo_admin.set_password(admin_senha) # Define a senha com hash
            db.session.add(novo_admin)
            
            # Salva tudo no banco
            db.session.commit()
            
            flash(f'Barbearia "{nome_fantasia}" e seu admin foram criados com sucesso!', 'success')
            return redirect(url_for('superadmin.listar_barbearias'))

        except Exception as e:
            db.session.rollback() # Desfaz as alterações em caso de erro
            current_app.logger.error(f"Erro ao criar nova barbearia: {e}", exc_info=True)
            flash(f'Erro ao salvar no banco de dados: {e}', 'danger')
            return render_template('superadmin/novo.html', form_data=request.form)

    # --- Método GET ---
    # Apenas mostra o formulário de adição vazio
    return render_template('superadmin/novo.html', form_data={})