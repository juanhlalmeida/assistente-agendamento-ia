# app/blueprints/assinaturas/__init__.py
"""
Blueprint de Assinaturas e Pagamentos via Mercado Pago
"""
from flask import Blueprint

# Criar o blueprint
bp = Blueprint(
    'assinaturas',
    __name__,
    url_prefix='/assinatura'
)

# Importar as rotas DEPOIS de criar o blueprint
from app.blueprints.assinaturas import routes
