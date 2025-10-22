# app/__init__.py
from __future__ import annotations

from flask import Flask
from config import Config
from .extensions import db  # Isto importa o 'db' do seu app/extensions.py
from .routes import bp      # Isto importa o 'bp' do seu app/routes.py
from flask_migrate import Migrate
from flask_login import LoginManager

# --- INSTÂNCIAS GLOBAIS ---
# Definimos as extensões AQUI, fora da função
login_manager = LoginManager()
# Esta linha redireciona utilizadores não logados para a página de login
login_manager.login_view = 'auth.login' 
login_manager.login_message = 'Por favor, faça login para aceder a esta página.'

migrate = Migrate()
# ---------------------------


# --- USER LOADER (O CÓDIGO QUE FALTAVA) ---
# Esta função diz ao Flask-Login como encontrar um usuário
# a partir do ID guardado na sessão (cookie).
@login_manager.user_loader
def load_user(user_id):
    # Importamos o 'models' aqui dentro da função
    # para evitar erros de "importação circular"
    from . import models 
    
    # Assumimos que o seu modelo de usuário se chama 'User'
    # O user_id vem da sessão como string, convertemos para int
    try:
        return models.User.query.get(int(user_id))
    except:
        # Se o user_id for inválido por algum motivo
        return None
# --- FIM DO USER LOADER ---


def create_app() -> Flask:
    # Prepara configuração dinâmica (DB etc.)
    Config.init_app()

    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(Config)

    # --- INICIALIZAÇÃO DAS EXTENSÕES ---
    # Agora ligamos as instâncias globais ao 'app'
    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)
    # ---------------------------------

    # Blueprints
    app.register_blueprint(bp)

    # Healthcheck
    @app.get("/health")
    def health():
        return {"status": "ok"}, 200

    # --- IMPORTAR MODELOS ---
    # Esta é a parte mais importante para o 'flask db'
    # Sem isto, o migrate não sabe quais tabelas existem.
    # O seu 'models.py' TEM que existir.
    with app.app_context():
        from . import models
    # --------------------------

    return app