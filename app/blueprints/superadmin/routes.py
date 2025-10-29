# app/blueprints/superadmin/routes.py
import logging
from functools import wraps
from flask import Blueprint, render_template, redirect, url_for, flash, current_app, abort
from app.models.tables import Barbearia, User # Importa modelos necessários
from app.extensions import db
from flask_login import login_required, current_user 

# Cria o Blueprint 'superadmin' com prefixo /superadmin
bp = Blueprint('superadmin', __name__, url_prefix='/superadmin')

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# --- DECORATOR PARA PROTEGER ROTAS SUPER ADMIN ---
def super_admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Garante que está logado E que tem a role 'super_admin'
        if not current_user.is_authenticated or not hasattr(current_user, 'role') or current_user.role != 'super_admin':
            flash('Acesso não autorizado.', 'danger')
            # Redireciona para o login normal ou um 'acesso negado'
            return redirect(url_for('main.login')) 
        return f(*args, **kwargs)
    return decorated_function
# -------------------------------------------------

# --- ROTA PRINCIPAL: LISTAR BARBEARIAS ---
@bp.route('/barbearias') # URL será /superadmin/barbearias
@login_required
@super_admin_required # Aplica a proteção extra
def listar_barbearias():
    """Exibe a lista de todas as barbearias cadastradas."""
    try:
        lista_barbearias = Barbearia.query.order_by(Barbearia.nome_fantasia).all()
    except Exception as e:
        current_app.logger.error(f"Erro ao buscar lista de barbearias: {e}", exc_info=True)
        flash('Ocorreu um erro ao carregar a lista de barbearias.', 'danger')
        lista_barbearias = [] 

    return render_template('superadmin/barbearias.html', barbearias=lista_barbearias)

# --- ROTAS FUTURAS (Adicionar, Editar Barbearia) ---
# @bp.route('/barbearias/novo', methods=['GET', 'POST'])
# @login_required
# @super_admin_required
# def nova_barbearia(): pass

# @bp.route('/barbearias/editar/<int:barbearia_id>', methods=['GET', 'POST'])
# @login_required
# @super_admin_required
# def editar_barbearia(barbearia_id): pass