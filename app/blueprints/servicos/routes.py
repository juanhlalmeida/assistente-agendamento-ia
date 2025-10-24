# app/blueprints/servicos/routes.py
import logging
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from app.models.tables import Servico # Importa o modelo Servico
from app.extensions import db
from flask_login import login_required, current_user # Para proteger a rota e filtrar

# Cria o Blueprint chamado 'servicos' com prefixo de URL
bp = Blueprint('servicos', __name__, url_prefix='/servicos')

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

@bp.route('/') # Esta é a rota raiz DO BLUEPRINT, ou seja, /servicos/
@login_required # Garante que apenas usuários logados acessem
def index():
    """Exibe a lista de serviços da barbearia logada."""
    
    # Validação do usuário e barbearia (importante manter)
    if not hasattr(current_user, 'barbearia_id') or not current_user.barbearia_id:
        flash('Erro: Usuário inválido ou não associado a uma barbearia.', 'danger')
        return redirect(url_for('auth.login')) # Redireciona para o login (assumindo que login está em 'auth')
        # Se seu login ainda estiver no 'main', use 'main.login'
        
    barbearia_id_logada = current_user.barbearia_id
    
    try:
        # Busca no banco APENAS os serviços pertencentes a esta barbearia
        lista_servicos = Servico.query.filter_by(barbearia_id=barbearia_id_logada).order_by(Servico.nome).all()
    except Exception as e:
        # Loga o erro caso a consulta falhe
        current_app.logger.error(f"Erro ao buscar serviços para barbearia {barbearia_id_logada}: {e}", exc_info=True)
        flash('Ocorreu um erro ao carregar os serviços.', 'danger')
        lista_servicos = [] # Retorna lista vazia em caso de erro

    # Passa a lista de serviços para o template
    return render_template('servicos.html', servicos=lista_servicos)

# --- ROTAS FUTURAS ---
# @bp.route('/novo', methods=['GET', 'POST'])
# @login_required
# def novo_servico(): pass

# @bp.route('/editar/<int:servico_id>', methods=['GET', 'POST'])
# @login_required
# def editar_servico(servico_id): pass

# @bp.route('/apagar/<int:servico_id>', methods=['POST'])
# @login_required
# def apagar_servico(servico_id): pass