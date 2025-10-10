# config.py
from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"

# Carrega .env se existir (não sobrescreve variáveis já definidas no ambiente)
if ENV_FILE.exists():
    load_dotenv(ENV_FILE)

class Config:
    # Ambiente explícito (evite FLASK_ENV no Flask 3)
    APP_ENV: str = os.getenv("APP_ENV", "development").lower()

    # Segurança
    SECRET_KEY: str = os.getenv("SECRET_KEY", "change-me")

    # SQLAlchemy
    SQLALCHEMY_DATABASE_URI: str | None = None
    SQLALCHEMY_TRACK_MODIFICATIONS: bool = False

    # Diretório para SQLite local (dev)
    INSTANCE_DIR = BASE_DIR / "instance"
    INSTANCE_DIR.mkdir(exist_ok=True)

    @classmethod
    def init_app(cls) -> None:
        """
        Define SQLALCHEMY_DATABASE_URI de forma consistente:
        - Em produção: exige DATABASE_URL (Render/Heroku) e corrige 'postgres://' -> 'postgresql://'
        - Em dev: usa DATABASE_URL se existir; senão, SQLite local
        """
        db_url = (os.getenv("DATABASE_URL") or "").strip()

        if db_url.startswith("postgres://"):
            db_url = db_url.replace("postgres://", "postgresql://", 1)

        if cls.APP_ENV == "production":
            if not db_url:
                raise RuntimeError(
                    "DATABASE_URL não definido em produção. "
                    "No Render, configure a variável de ambiente DATABASE_URL."
                )
            cls.SQLALCHEMY_DATABASE_URI = db_url
            return

        # development/test
        cls.SQLALCHEMY_DATABASE_URI = db_url or f"sqlite:///{cls.INSTANCE_DIR / 'database.db'}"