# app/__init__.py (COM BLUEPRINT PROFISSIONAIS)
from __future__ import annotations

from flask import Flask
from config import Config
from app.extensions import db  
from flask_migrate import Migrate
from flask_login import LoginManager
from flask import current_app 

# --- INSTÂNCIAS GLOBAIS ---
login_manager = LoginManager()
login_manager.login_view = 'main.login' # Assumindo que login está no blueprint 'main' agora
login_manager.login_message = 'Por favor, faça login para aceder a esta página.'
login_manager.login_message_category = 'info' 

migrate = Migrate()
# ---------------------------

# --- USER LOADER ---
@login_manager.user_loader
def load_user(user_id):
    current_app.logger.info(f"Tentando carregar usuário com ID da sessão: {user_id}")
    try:
        user_id_int = int(user_id) 
    except ValueError:
        current_app.logger.error(f"ID do usuário na sessão não é um inteiro válido: {user_id}")
        return None
        
    try:
        from app.models.tables import User 
        user = User.query.get(user_id_int)
        
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
    app.config.from_object(config_class)

    # --- INICIALIZAÇÃO DAS EXTENSÕES ---
    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)
    # ---------------------------------

    # --- REGISTO DOS BLUEPRINTS ---
    try:
        from app.routes import bp as main_routes_bp 
        app.register_blueprint(main_routes_bp) 
    except Exception as e:
         app.logger.error(f"ERRO ao registar blueprint 'main': {e}")
         
    try:
        from app.blueprints.servicos.routes import bp as servicos_bp 
        app.register_blueprint(servicos_bp) 
    except Exception as e:
         app.logger.error(f"ERRO ao registar blueprint 'servicos': {e}")

    # --- NOVO BLUEPRINT PROFISSIONAIS ---
    try:
        from app.blueprints.profissionais.routes import bp as profissionais_bp 
        app.register_blueprint(profissionais_bp) # Já tem url_prefix='/profissionais'
    except Exception as e:
         app.logger.error(f"ERRO ao registar blueprint 'profissionais': {e}")
    # ------------------------------------
    try:
        from app.blueprints.clientes.routes import bp as clientes_bp 
        app.register_blueprint(clientes_bp) # Já tem url_prefix='/clientes'
    except Exception as e:
         app.logger.error(f"ERRO ao registar blueprint 'clientes': {e}")     
    # -------------------------------
    try:
        from app.blueprints.dashboard.routes import bp as dashboard_bp 
        app.register_blueprint(dashboard_bp) # Já tem url_prefix='/dashboard'
    except Exception as e:
         app.logger.error(f"ERRO ao registar blueprint 'dashboard': {e}")

         # --- NOVO BLUEPRINT SUPERADMIN ---
    try:
        from app.blueprints.superadmin.routes import bp as superadmin_bp 
        app.register_blueprint(superadmin_bp) # Já tem url_prefix='/superadmin'
    except Exception as e:
         app.logger.error(f"ERRO ao registar blueprint 'superadmin': {e}")

    # Healthcheck
    @app.get("/health")
    def health():
        return {"status": "ok"}, 200

    # --- IMPORTAR MODELOS ---
    with app.app_context():
        from app.models import tables
    # --------------------------

    return app