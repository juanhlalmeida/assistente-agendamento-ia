from __future__ import annotations

from flask import Flask
from config import Config
from .extensions import db
from .routes import bp  # importa o Blueprint principal

def create_app() -> Flask:
    # prepara configuração dinâmica (DB etc.)
    Config.init_app()

    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(Config)

    # extensões
    db.init_app(app)

    # blueprints
    app.register_blueprint(bp)

    # healthcheck
    @app.get("/health")
    def health():
        return {"status": "ok"}, 200

    return app