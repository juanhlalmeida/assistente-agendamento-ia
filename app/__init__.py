# app/__init__.py (COM BLUEPRINT PROFISSIONAIS, CRIAÇÃO DE ADMIN E POPULAR DADOS)
from __future__ import annotations

import os
import logging 
from flask import Flask
from config import Config
from app.extensions import db  
from flask_migrate import Migrate
from flask_login import LoginManager
from flask import current_app 
from app.blueprints.superadmin.routes import bp as superadmin_bp
from werkzeug.security import generate_password_hash 

# --- INSTÂNCIAS GLOBAIS ---
login_manager = LoginManager()
login_manager.login_view = 'main.login' 
login_manager.login_message = 'Por favor, faça login para aceder a esta página.'
login_manager.login_message_category = 'info' 

migrate = Migrate()
# ---------------------------

# --- USER LOADER ---
@login_manager.user_loader
def load_user(user_id):
    # (O seu código original do user_loader está 100% preservado aqui)
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

# --- FUNÇÃO HELPER PARA CRIAR O SUPER ADMIN ---
# (A sua função original está 100% preservada aqui)
def _create_super_admin(app: Flask):
    """
    Função interna para criar o super admin ao iniciar,
    se as variáveis de ambiente estiverem definidas e o usuário não existir.
    """
    with app.app_context():
        admin_email = os.getenv('SUPER_ADMIN_EMAIL')
        admin_pass = os.getenv('SUPER_ADMIN_PASSWORD')
        if not admin_email or not admin_pass:
            logging.info("SUPER_ADMIN_EMAIL ou SUPER_ADMIN_PASSWORD não definidos. Ignorando criação de super admin.")
            return
        try:
            from app.models.tables import User 
            if User.query.filter_by(email=admin_email).first():
                logging.info(f"Super admin com email {admin_email} já existe.")
                return
            logging.info(f"Criando novo super admin para {admin_email}...")
            new_super_admin = User(
                email=admin_email,
                nome="Super Admin", # Nome Padrão
                role="super_admin" # Garante que a role é 'super_admin'
            )
            new_super_admin.set_password(admin_pass) 
            db.session.add(new_super_admin)
            db.session.commit()
            logging.info(f"Super admin {admin_email} criado com sucesso!")
        except Exception as e:
            db.session.rollback()
            logging.error(f"ERRO CRÍTICO ao tentar criar super admin: {e}", exc_info=True)
# --------------------------------------------------

# --- ADICIONADO: FUNÇÃO HELPER PARA POPULAR DADOS DE DEMO ---
def _populate_demo_data(app: Flask):
    """
    Cria profissionais e serviços de demonstração se o banco de dados estiver vazio.
    Associado à Barbearia com ID 1 (a que você criou no admin).
    """
    with app.app_context():
        try:
            # Importa os modelos aqui dentro
            from app.models.tables import Profissional, Servico, Barbearia
            
            # 1. Verifica se já existem profissionais (sinal de que os dados já existem)
            if Profissional.query.count() > 0:
                logging.info("Banco de dados já populado. Ignorando dados de demonstração.")
                return

            # 2. Encontra a Barbearia (assumimos que é a ID 1, a primeira que você criou)
            barbearia = Barbearia.query.get(1) 
            if not barbearia:
                # Se não for a ID 1, tenta pegar a primeira que encontrar
                barbearia = Barbearia.query.first()
                if not barbearia:
                    logging.warning("Nenhuma barbearia encontrada. Não é possível popular dados de demo.")
                    return
            
            logging.info(f"Barbearia ID {barbearia.id} ({barbearia.nome_fantasia}) encontrada. Populando dados de demonstração...")

            # 3. Cria Profissionais de Demo (Tipo "Jasiel Oliveira")
            prof_jasiel = Profissional(nome="Jasiel Oliveira", barbearia_id=barbearia.id)
            prof_bruna = Profissional(nome="Bruna Santos", barbearia_id=barbearia.id)
            
            # 4. Cria Serviços de Demo
            serv_corte = Servico(nome="Corte Masculino", duracao_minutos=30, preco=40.00, barbearia_id=barbearia.id)
            serv_barba = Servico(nome="Barba e Bigode", duracao_minutos=30, preco=35.00, barbearia_id=barbearia.id)
            serv_completo = Servico(nome="Corte e Barba", duracao_minutos=60, preco=70.00, barbearia_id=barbearia.id)
            
            db.session.add_all([prof_jasiel, prof_bruna, serv_corte, serv_barba, serv_completo])
            db.session.commit()
            
            logging.info("Dados de demonstração (Profissionais e Serviços) criados com sucesso!")

        except Exception as e:
            db.session.rollback()
            logging.error(f"ERRO CRÍTICO ao tentar popular dados de demonstração: {e}", exc_info=True)
# --------------------------------------------------------


def create_app(config_class=Config) -> Flask:
    Config.init_app()
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_class)

    # --- CORREÇÃO DA URL DO BANCO DE DADOS ---
    # (O seu código original está 100% preservado aqui)
    database_url = os.environ.get('DATABASE_URL')
    if database_url is None:
        raise ValueError("DATABASE_URL não está definida no ambiente!")
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
    if 'channel_binding' in database_url:
        base_url, params = database_url.split('?', 1) if '?' in database_url else (database_url, '')
        params_list = [p for p in params.split('&') if not p.startswith('channel_binding=')]
        database_url = base_url + ('?' + '&'.join(params_list) if params_list else '')
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False 
    # ----------------------------------------

    # --- INICIALIZAÇÃO DAS EXTENSÕES ---
    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)
    # ---------------------------------

    # --- REGISTO DOS BLUEPRINTS ---
    # (O seu código original está 100% preservado aqui)
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

    try:
        from app.blueprints.profissionais.routes import bp as profissionais_bp 
        app.register_blueprint(profissionais_bp) 
    except Exception as e:
         app.logger.error(f"ERRO ao registar blueprint 'profissionais': {e}")
    
    try:
        from app.blueprints.clientes.routes import bp as clientes_bp 
        app.register_blueprint(clientes_bp) 
    except Exception as e:
         app.logger.error(f"ERRO ao registar blueprint 'clientes': {e}")     

    app.register_blueprint(superadmin_bp) 
    
    try:
        from app.blueprints.dashboard.routes import bp as dashboard_bp 
        app.register_blueprint(dashboard_bp) 
    except Exception as e:
         app.logger.error(f"ERRO ao registar blueprint 'dashboard': {e}")

    # Healthcheck
    @app.get("/health")
    def health():
        return {"status": "ok"}, 200

    # --- IMPORTAR MODELOS ---
    with app.app_context():
        from app.models import tables
    # --------------------------

    # --- CHAMA AS FUNÇÕES DE INICIALIZAÇÃO ---
    _create_super_admin(app)
    _populate_demo_data(app) # <--- ADICIONADO
    # ---------------------------------------
    
    return app