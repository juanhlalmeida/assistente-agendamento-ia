# app/__init__.py (SIMPLIFICADO E CORRIGIDO)
from __future__ import annotations

from flask import Flask
from config import Config
from app.extensions import db  
from flask_migrate import Migrate
from flask_login import LoginManager
# Importa current_app para o user_loader
from flask import current_app 

# --- INSTÂNCIAS GLOBAIS ---
login_manager = LoginManager()
# Aponta para a rota de login DENTRO do blueprint principal (main)
login_manager.login_view = 'main.login' 
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
    # 1. Importa o blueprint ÚNICO do seu app/routes.py principal
    #    (Assumindo que a variável lá se chama 'bp')
    try:
        from app.routes import bp as main_routes_bp 
        app.register_blueprint(main_routes_bp) # Regista o blueprint principal
    except ImportError:
         app.logger.error("ERRO CRÍTICO: Não foi possível importar o blueprint de 'app.routes'. Verifique se o arquivo existe e se a variável 'bp' está definida.")
         # Considerar levantar uma exceção aqui para parar a inicialização
    except AttributeError:
         app.logger.error("ERRO CRÍTICO: O arquivo 'app.routes.py' foi encontrado, mas não define uma variável chamada 'bp'.")
         # Considerar levantar uma exceção

    # 2. Importa e regista o NOVO blueprint de serviços
    try:
        from app.blueprints.servicos.routes import bp as servicos_bp 
        app.register_blueprint(servicos_bp) # Já tem url_prefix='/servicos'
    except ImportError:
         app.logger.error("ERRO CRÍTICO: Não foi possível importar o blueprint de 'app.blueprints.servicos'. Verifique a estrutura de pastas e arquivos.")
    except AttributeError:
         app.logger.error("ERRO CRÍTICO: O arquivo 'app/blueprints/servicos/routes.py' não define uma variável chamada 'bp'.")
         
    # Removidos os outros registros de blueprints (auth, webhook, admin)
    # -------------------------------

    # Healthcheck
    @app.get("/health")
    def health():
        return {"status": "ok"}, 200

    # --- IMPORTAR MODELOS ---
    with app.app_context():
        from app.models import tables
    # --------------------------

    return app