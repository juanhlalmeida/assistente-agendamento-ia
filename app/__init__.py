# app/__init__.py
from __future__ import annotations

from flask import Flask
from flask import current_app
from config import Config
from app.extensions import db  
from app.routes import bp      
from flask_migrate import Migrate
from flask_login import LoginManager

# --- INSTÂNCIAS GLOBAIS ---
login_manager = LoginManager()
migrate = Migrate()
# ---------------------------


# --- USER LOADER (DESABILITADO) ---
# Vamos comentar esta função inteira para que ela não seja executada
# e não cause o erro 'user_loader ausente' ou 'tabela user não existe'.

@login_manager.user_loader
def load_user(user_id):
    # Adicionamos logging para depuração
    current_app.logger.info(f"Tentando carregar usuário com ID da sessão: {user_id}")
    try:
        user_id_int = int(user_id) # Converte para inteiro
    except ValueError:
        current_app.logger.error(f"ID do usuário na sessão não é um inteiro válido: {user_id}")
        return None
        
    try:
        from .models import tables # Importa dentro da função
        user = tables.User.query.get(user_id_int)
        
        if user:
            current_app.logger.info(f"Usuário ID {user_id_int} encontrado: {user.email}")
            return user
        else:
            current_app.logger.warning(f"Usuário ID {user_id_int} NÃO encontrado no banco de dados.")
            return None
            
    except Exception as e:
        current_app.logger.error(f"Erro EXCEPCIONAL ao tentar carregar usuário ID {user_id_int}: {e}", exc_info=True)
        return None

# --- FIM DO USER LOADER ---


def create_app(config_class=Config) -> Flask:
    Config.init_app()

    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(Config)

    # --- INICIALIZAÇÃO DAS EXTENSÕES ---
    db.init_app(app)
    
    # 🚀 CORREÇÃO: Linha desabilitada para parar o sistema de login
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
    with app.app_context():
        # Mantemos isto para que o flask db migrate (do futuro) funcione
        from app.models import tables
    # --------------------------

    return app