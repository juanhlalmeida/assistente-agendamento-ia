
# app/blueprints/assinaturas/__init__.py

from flask import Blueprint

bp = Blueprint('assinaturas', __name__, url_prefix='/assinatura')

from app.blueprints.assinaturas import routes
