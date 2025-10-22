# app/__init__.py
from __future__ import annotations

from flask import Flask
from config import Config
from app.extensions import db  # Corrigido: Mantém a sua estrutura
from app.routes import bp      # Corrigido: Mantém a sua estrutura
from flask_migrate import Migrate
from flask_login import LoginManager

# --- INSTÂNCIAS GLOBAIS ---
# Definimos as extensões AQUI, fora da função
login_manager = LoginManager()
# Esta linha redireciona utilizadores não logados para a página de login
# Assumindo que a sua rota de login está em app/routes.py e se chama 'main.login'
# Se o nome for outro (ex: 'auth.login'), mude aqui.
login_manager.login_view = 'main.login' 
login_manager.login_message = 'Por favor, faça login para aceder a esta página.'
login_manager.login_message_category = 'info' # Categoria para o flash message

migrate = Migrate()
# ---------------------------


# --- USER LOADER (O CÓDIGO QUE FALTAVA) ---
# Esta função diz ao Flask-Login como encontrar um usuário
# a partir do ID guardado na sessão (cookie).
@login_manager.user_loader
def load_user(user_id):
    # Importamos os modelos AQUI, da forma como os outros arquivos fazem
    from app.models.tables import User 
    
    try:
        # Assumindo que seu modelo de usuário se chama 'User'
        return User.query.get(int(user_id))
    except Exception as e:
        current_app.logger.error(f"Erro no user_loader: {e}")
        return None
# --- FIM DO USER LOADER ---


def create_app(config_class=Config) -> Flask:
    # Prepara configuração dinâmica (DB etc.)
    Config.init_app()

    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_class)

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
    # Corrigido: Importamos os modelos da sua estrutura
    # para que o Flask-Migrate os veja.
    with app.app_context():
        from app.models import tables
    # --------------------------

    return app