# app/__init__.py
from flask import Flask
from config import Config
from .extensions import db

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)

    # Reativando as importações
    from . import routes
    from . import commands
    
    # Reativando as inicializações
    routes.init_app(app)
    commands.init_app(app)

    return app