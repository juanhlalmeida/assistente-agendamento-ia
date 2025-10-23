# app/blueprints/servicos/routes.py
import logging
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from app.models.tables import Servico # Importa o modelo Servico
from app.extensions import db
from flask_login import login_required, current_user # Para proteger a rota e filtrar

# Cria o Blueprint chamado 'servicos'
# O url_prefix='/servicos' significa que todas as rotas aqui dentro começarão com /servicos
bp = Blueprint('servicos', __name__, url_prefix='/servicos')

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

@bp.route('/') # Rota raiz do blueprint (/servicos/)
@login_required # Garante que apenas usuários logados acessem
def index():
    """Exibe a lista de serviços da barbearia logada."""
    
    # --- LÓGICA MULTI-TENANCY ---
    # Garante que temos um ID de barbearia para filtrar
    if not current_user or not hasattr(current_user, 'barbearia_id') or not current_user.barbearia_id:
        flash('Erro: Usuário inválido ou não associado a uma barbearia.', 'danger')
        # Podemos redirecionar para o login ou outra página de erro
        return redirect(url_for('auth.login')) 
        
    barbearia_id_logada = current_user.barbearia_id
    # --- FIM DA LÓGICA ---

    # Busca no banco APENAS os serviços pertencentes a esta barbearia
    lista_servicos = Servico.query.filter_by(barbearia_id=barbearia_id_logada).order_by(Servico.nome).all()

    # Passa a lista de serviços para o template
    return render_template('servicos.html', servicos=lista_servicos)

# --- FUTURAS ROTAS (Adicionar, Editar, Apagar) ---
# @bp.route('/novo', methods=['GET', 'POST'])
# @login_required
# def novo_servico():
#     # Lógica para adicionar novo serviço
#     pass

# @bp.route('/editar/<int:servico_id>', methods=['GET', 'POST'])
# @login_required
# def editar_servico(servico_id):
#     # Lógica para editar serviço
#     pass

# @bp.route('/apagar/<int:servico_id>', methods=['POST'])
# @login_required
# def apagar_servico(servico_id):
#     # Lógica para apagar serviço
#     pass