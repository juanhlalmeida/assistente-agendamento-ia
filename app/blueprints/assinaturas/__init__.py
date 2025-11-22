# app/blueprints/assinaturas/__init__.py
"""
Blueprint de assinaturas e pagamentos
"""
from flask import Blueprint

bp = Blueprint(
    'assinaturas',
    __name__,
    url_prefix='/assinatura',
    template_folder='../../templates/assinatura'
)

# Importa as rotas depois de criar o blueprint
from app.blueprints.assinaturas import routes
