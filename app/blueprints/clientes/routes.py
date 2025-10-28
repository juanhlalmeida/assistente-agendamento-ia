# app/blueprints/clientes/routes.py
import logging
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from sqlalchemy import distinct, func # Para buscar clientes únicos
from app.models.tables import Agendamento # Importa Agendamento para buscar clientes
from app.extensions import db
from flask_login import login_required, current_user # Para proteger e filtrar

# Cria o Blueprint 'clientes' com prefixo /clientes
bp = Blueprint('clientes', __name__, url_prefix='/clientes')

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

@bp.route('/')
@login_required
def index():
    """Exibe a lista de clientes únicos da barbearia logada."""
    if not hasattr(current_user, 'barbearia_id') or not current_user.barbearia_id:
        flash('Erro: Usuário inválido ou não associado a uma barbearia.', 'danger')
        return redirect(url_for('auth.login')) # Ajuste se necessário
        
    barbearia_id_logada = current_user.barbearia_id
    
    try:
        # Consulta para buscar clientes únicos (nome e telefone)
        # Agrupa por telefone e nome, pega o último agendamento como referência (opcional)
        # Ordena por nome
        clientes_unicos = db.session.query(
                Agendamento.nome_cliente, 
                Agendamento.telefone_cliente,
                func.max(Agendamento.data_hora).label('ultimo_agendamento') # Pega a data do último agendamento
            ).filter(
                Agendamento.barbearia_id == barbearia_id_logada
            ).group_by(
                Agendamento.nome_cliente, 
                Agendamento.telefone_cliente
            ).order_by(
                Agendamento.nome_cliente.asc()
            ).all()

        # Formatamos para facilitar o template (Opcional, pode ser feito no template)
        lista_clientes = [
            {
                'nome': nome, 
                'telefone': telefone, 
                'ultimo_agendamento': ultimo
            } 
            for nome, telefone, ultimo in clientes_unicos
        ]
        
    except Exception as e:
        current_app.logger.error(f"Erro ao buscar clientes para barbearia {barbearia_id_logada}: {e}", exc_info=True)
        flash('Ocorreu um erro ao carregar a lista de clientes.', 'danger')
        lista_clientes = [] 

    return render_template('clientes.html', clientes=lista_clientes)

# --- ROTAS FUTURAS (Ex: Ver detalhes do cliente, histórico) ---
# @bp.route('/<int:cliente_id>') # Ou talvez buscar pelo telefone?
# @login_required
# def detalhes_cliente(cliente_id): pass