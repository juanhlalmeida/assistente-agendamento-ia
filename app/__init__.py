# app/__init__.py
# (VERSÃO FINAL: COMPLETA, SEGURA E COM TODOS OS MÓDULOS)
from __future__ import annotations

import os
import logging 
from flask import Flask
from config import Config
from app.extensions import db, cache
from flask_migrate import Migrate
from flask_login import LoginManager
from flask import current_app 
# Importação global do SuperAdmin (mantida conforme seu padrão)
from app.blueprints.superadmin.routes import bp as superadmin_bp
from werkzeug.security import generate_password_hash 

login_manager = LoginManager()
login_manager.login_view = 'main.login' 
login_manager.login_message = 'Por favor, faça login para aceder a esta página.'
login_manager.login_message_category = 'info' 

migrate = Migrate()

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

def _create_super_admin(app: Flask):
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
                nome="Super Admin",
                role="super_admin"
            )
            new_super_admin.set_password(admin_pass) 
            db.session.add(new_super_admin)
            db.session.commit()
            logging.info(f"Super admin {admin_email} criado com sucesso!")
        except Exception as e:
            db.session.rollback()
            logging.error(f"ERRO CRÍTICO ao tentar criar super admin: {e}", exc_info=True)

def create_app(config_class=Config) -> Flask:
    Config.init_app()
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_class)

    database_url = os.environ.get('DATABASE_URL')
    if database_url is None:
        raise ValueError("DATABASE_URL não está definida no ambiente!")

    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)

    if "postgresql://" in database_url and "sslmode=" not in database_url:
         database_url = database_url + "?sslmode=require"
    
    if 'channel_binding' in database_url:
        base_url, params = database_url.split('?', 1) if '?' in database_url else (database_url, '')
        params_list = [p for p in params.split('&') if not p.startswith('channel_binding=')]
        database_url = base_url + ('?' + '&'.join(params_list) if params_list else '')
        
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False 

    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)
    cache.init_app(app)

    # ============================================
    # 📞 FILTROS GLOBAIS JINJA2 (LIMPEZA DE TELEFONE / WAHA JID & LID)
    # ============================================
    import re as _re

    @app.template_filter('formatar_telefone')
    def formatar_telefone_filter(valor):
        if not valor:
            return "Sem telefone"
        texto = str(valor).strip()
        is_lid = '@lid' in texto.lower()
        base = texto.replace('whatsapp:', '').split('@')[0]
        digitos = _re.sub(r'\D', '', base)

        if not digitos:
            return base or "Sem telefone"

        # Padrão Brasil com DDI 55 + DDD + 9 dígitos (13 dígitos)
        if len(digitos) == 13 and digitos.startswith('55'):
            return f"({digitos[2:4]}) {digitos[4:9]}-{digitos[9:]}"
        # Padrão Brasil com DDI 55 + DDD + 8 dígitos (12 dígitos)
        if len(digitos) == 12 and digitos.startswith('55'):
            return f"({digitos[2:4]}) {digitos[4:8]}-{digitos[8:]}"
        # Padrão Brasil sem DDI: DDD + 9 dígitos (11 dígitos)
        if len(digitos) == 11:
            return f"({digitos[:2]}) {digitos[2:7]}-{digitos[7:]}"
        # Padrão Brasil sem DDI: DDD + 8 dígitos (10 dígitos)
        if len(digitos) == 10:
            return f"({digitos[:2]}) {digitos[2:6]}-{digitos[6:]}"

        # Caso seja um identificador interno de privacidade da Meta (@lid com 14+ dígitos)
        if is_lid or len(digitos) > 13:
            return f"WhatsApp (#{digitos[-4:]})"

        return f"+{digitos}"

    @app.template_filter('wa_me_link')
    def wa_me_link_filter(valor):
        if not valor:
            return ""
        texto = str(valor).strip()
        base = texto.replace('whatsapp:', '').split('@')[0]
        digitos = _re.sub(r'\D', '', base)
        if not digitos:
            return ""
        if len(digitos) in (10, 11):
            return f"55{digitos}"
        if len(digitos) in (12, 13) and digitos.startswith('55'):
            return digitos
        # Para IDs @lid puros (>13 dígitos), retorna os dígitos limpos sem sufixo @lid
        return digitos

    # ============================================
    # 🔍 REGISTRO DE BLUEPRINTS COM LOGS DETALHADOS
    # ============================================
    
    print("\n" + "=" * 60)
    print("🔍 INICIANDO REGISTRO DE BLUEPRINTS")
    print("=" * 60 + "\n")

    # BLUEPRINT: MAIN
    try:
        print("🔍 [MAIN] Importando app.routes...")
        from app.routes import bp as main_routes_bp
        print(f"✅ [MAIN] Import OK! Nome: {main_routes_bp.name}")
        app.register_blueprint(main_routes_bp)
        print("✅ [MAIN] Registrado com SUCESSO!\n")
    except Exception as e:
        print(f"❌ [MAIN] ERRO: {e}\n")
        logging.error(f"ERRO blueprint main: {e}", exc_info=True)
         
    # BLUEPRINT: SERVICOS
    try:
        print("🔍 [SERVICOS] Importando...")
        from app.blueprints.servicos.routes import bp as servicos_bp
        print(f"✅ [SERVICOS] Import OK! Nome: {servicos_bp.name}")
        app.register_blueprint(servicos_bp)
        print("✅ [SERVICOS] Registrado com SUCESSO!\n")
    except Exception as e:
        print(f"❌ [SERVICOS] ERRO: {e}\n")
        logging.error(f"ERRO blueprint servicos: {e}", exc_info=True)

    # BLUEPRINT: PROFISSIONAIS
    try:
        print("🔍 [PROFISSIONAIS] Importando...")
        from app.blueprints.profissionais.routes import bp as profissionais_bp
        print(f"✅ [PROFISSIONAIS] Import OK! Nome: {profissionais_bp.name}")
        app.register_blueprint(profissionais_bp)
        print("✅ [PROFISSIONAIS] Registrado com SUCESSO!\n")
    except Exception as e:
        print(f"❌ [PROFISSIONAIS] ERRO: {e}\n")
        logging.error(f"ERRO blueprint profissionais: {e}", exc_info=True)
    
    # BLUEPRINT: CLIENTES
    try:
        print("🔍 [CLIENTES] Importando...")
        from app.blueprints.clientes.routes import bp as clientes_bp
        print(f"✅ [CLIENTES] Import OK! Nome: {clientes_bp.name}")
        app.register_blueprint(clientes_bp)
        print("✅ [CLIENTES] Registrado com SUCESSO!\n")
    except Exception as e:
        print(f"❌ [CLIENTES] ERRO: {e}\n")
        logging.error(f"ERRO blueprint clientes: {e}", exc_info=True)

    # BLUEPRINT: SUPERADMIN
    try:
        print("🔍 [SUPERADMIN] Registrando...")
        app.register_blueprint(superadmin_bp)
        print("✅ [SUPERADMIN] Registrado com SUCESSO!\n")
    except Exception as e:
        print(f"❌ [SUPERADMIN] ERRO: {e}\n")
        logging.error(f"ERRO blueprint superadmin: {e}", exc_info=True)
    
    # BLUEPRINT: DASHBOARD
    try:
        print("🔍 [DASHBOARD] Importando...")
        from app.blueprints.dashboard.routes import bp as dashboard_bp
        print(f"✅ [DASHBOARD] Import OK! Nome: {dashboard_bp.name}")
        app.register_blueprint(dashboard_bp)
        print("✅ [DASHBOARD] Registrado com SUCESSO!\n")
    except Exception as e:
        print(f"❌ [DASHBOARD] ERRO: {e}\n")
        logging.error(f"ERRO blueprint dashboard: {e}", exc_info=True)

    # BLUEPRINT: ASSINATURAS
    try:
        print("🔍 [ASSINATURAS] Importando...")
        from app.blueprints.assinaturas.routes import bp as assinaturas_bp
        print(f"✅ [ASSINATURAS] Import OK! Nome: {assinaturas_bp.name}")
        print(f"   URL Prefix: {assinaturas_bp.url_prefix}")
        app.register_blueprint(assinaturas_bp)
        print("✅ [ASSINATURAS] Registrado com SUCESSO!\n")
    except Exception as e:
        print(f"❌ [ASSINATURAS] ERRO: {e}\n")
        logging.error(f"ERRO blueprint assinaturas: {e}", exc_info=True)

    # ==========================================================
    # 🔌 INTEGRAÇÃO GOOGLE (AUTH & SYNC) - COM LOGS SEGUROS
    # ==========================================================

    # BLUEPRINT: GOOGLE AUTH (Login)
    try:
        print("🔍 [GOOGLE AUTH] Importando...")
        from app.google.routesgoogle import bp as google_auth_bp
        print(f"✅ [GOOGLE AUTH] Import OK! Nome: {google_auth_bp.name}")
        app.register_blueprint(google_auth_bp)
        print("✅ [GOOGLE AUTH] Registrado com SUCESSO!\n")
    except Exception as e:
        print(f"❌ [GOOGLE AUTH] ERRO: {e}\n")
        logging.error(f"ERRO blueprint google auth: {e}", exc_info=True)

    # BLUEPRINT: GOOGLE SYNC (Robô)
    try:
        print("🔍 [GOOGLE SYNC] Importando...")
        from app.google.blueprint_sync import bp as google_sync_bp
        print(f"✅ [GOOGLE SYNC] Import OK! Nome: {google_sync_bp.name}")
        app.register_blueprint(google_sync_bp)
        print("✅ [GOOGLE SYNC] Registrado com SUCESSO!\n")
    except Exception as e:
        print(f"❌ [GOOGLE SYNC] ERRO: {e}\n")
        logging.error(f"ERRO blueprint google sync: {e}", exc_info=True)

    print("=" * 60)
    print("✅ REGISTRO DE BLUEPRINTS FINALIZADO")
    print("=" * 60 + "\n")

    # Healthcheck
    @app.get("/health")
    def health():
        return {"status": "ok"}, 200

    with app.app_context():
        from app.models import tables

    _create_super_admin(app)

    return app
