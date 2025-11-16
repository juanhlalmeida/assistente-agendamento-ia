# config.py
# (Código completo, com as variáveis de Cache (Redis) adicionadas)

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
    SECRET_KEY: str = os.getenv("APP_SECRET_KEY") or os.getenv("SECRET_KEY") or "fallback-secret-key-mude-isto"

    # SQLAlchemy
    SQLALCHEMY_DATABASE_URI: str | None = None
    SQLALCHEMY_TRACK_MODIFICATIONS: bool = False

    # Diretório para SQLite local (dev)
    INSTANCE_DIR = BASE_DIR / "instance"
    INSTANCE_DIR.mkdir(exist_ok=True)

    # --- INÍCIO DA IMPLEMENTAÇÃO (Conforme o Relatório Técnico) ---
    # [cite: 63-72]
    
    # Define o tipo de cache para 'redis'.
    CACHE_TYPE: str = os.environ.get('CACHE_TYPE', 'redis')
    
    # Host do servidor Redis.
    CACHE_REDIS_HOST: str = os.environ.get('REDIS_HOST', 'localhost')
    
    # Porta do servidor Redis.
    CACHE_REDIS_PORT: int = int(os.environ.get('REDIS_PORT', 6379))
    
    # Password do servidor Redis (None se não estiver definida).
    CACHE_REDIS_PASSWORD: str | None = os.environ.get('REDIS_PASSWORD', None)
    
    # Número da base de dados Redis (0-15).
    CACHE_REDIS_DB: int = int(os.environ.get('REDIS_DB', 0))
    
    # Timeout padrão (1 hora = 3600s) para o histórico da conversa.
    CACHE_DEFAULT_TIMEOUT: int = int(os.environ.get('CACHE_DEFAULT_TIMEOUT', 3600))

    # Esta variável (CACHE_REDIS_URL) é a forma mais fácil
    # de configurar no Render. Ela sobrescreve as de cima.
    CACHE_REDIS_URL: str | None = os.environ.get('CACHE_REDIS_URL', None)
    # --- FIM DA IMPLEMENTAÇÃO ---

    @classmethod
    def init_app(cls) -> None:
        """
        Define SQLALCHEMY_DATABASE_URI de forma consistente:
        - Em produção: exige DATABASE_URL (Render/Heroku) e corrige 'postgres://' -> 'postgresql://'
        - Em dev: usa DATABASE_URL se existir; senão, SQLite local
        """
        # (O seu código original de 'init_app' está 100% preservado aqui)
        db_url = (os.getenv("DATABASE_URL") or "").strip()

        if db_url.startswith("postgres://"):
            db_url = db_url.replace("postgres://", "postgresql://", 1)

        if cls.APP_ENV == "production":
            if not db_url:
                raise RuntimeError(
                    "DATABASE_URL não definido em produção. "
                    "No Render, configure a variável de ambiente DATABASE_URL."
                )
            
            # Adiciona 'sslmode=require' (necessário para o banco pago do Render)
            if "postgresql://" in db_url and "sslmode=" not in db_url:
                 db_url = db_url + "?sslmode=require"
            
            cls.SQLALCHEMY_DATABASE_URI = db_url
            return

        # development/test
        cls.SQLALCHEMY_DATABASE_URI = db_url or f"sqlite:///{cls.INSTANCE_DIR / 'database.db'}"