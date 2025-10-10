# app/__init__.py
from __future__ import annotations

from flask import Flask
from config import Config
from .extensions import db
from .routes import bp  # Blueprint principal

def create_app() -> Flask:
    # Prepara configuração dinâmica (DB etc.)
    Config.init_app()

    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(Config)

    # Extensões
    db.init_app(app)

    # Blueprints
    app.register_blueprint(bp)

    # Healthcheck
    @app.get("/health")
    def health():
        return {"status": "ok"}, 200

    return app