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
    SECRET_KEY: str = os.getenv("SECRET_KEY", "change-me")

    # SQLAlchemy
    SQLALCHEMY_DATABASE_URI: str | None = None
    SQLALCHEMY_TRACK_MODIFICATIONS: bool = False

    # Diretório para SQLite local (dev)
    INSTANCE_DIR = BASE_DIR / "instance"
    INSTANCE_DIR.mkdir(exist_ok=True)

    # --- INÍCIO DA IMPLEMENTAÇÃO (Conforme o PDF) ---
    # --- Configuração do Cache (Redis) ---
    # [cite: 63, 254]
    
    # Define o tipo de cache para 'redis'. [cite: 65, 257]
    CACHE_TYPE: str = os.environ.get('CACHE_TYPE', 'redis')
    
    # Host do servidor Redis. [cite: 66, 259]
    CACHE_REDIS_HOST: str = os.environ.get('REDIS_HOST', 'localhost')
    
    # Porta do servidor Redis. [cite: 68, 261]
    CACHE_REDIS_PORT: int = int(os.environ.get('REDIS_PORT', 6379))
    
    # Password do servidor Redis (None se não estiver definida). [cite: 69, 263]
    CACHE_REDIS_PASSWORD: str | None = os.environ.get('REDIS_PASSWORD', None)
    
    # Número da base de dados Redis (0-15). [cite: 70, 265]
    CACHE_REDIS_DB: int = int(os.environ.get('REDIS_DB', 0))
    
    # Timeout padrão (1 hora = 3600s) para o histórico da conversa. [cite: 72, 268]
    CACHE_DEFAULT_TIMEOUT: int = int(os.environ.get('CACHE_DEFAULT_TIMEOUT', 3600))
    # --- FIM DA IMPLEMENTAÇÃO ---

    @classmethod
    def init_app(cls) -> None:
        """
        Define SQLALCHEMY_DATABASE_URI de forma consistente:
        - Em produção: exige DATABASE_URL (Render/Heroku) e corrige 'postgres://' -> 'postgresql://'
        - Em dev: usa DATABASE_URL se existir; senão, SQLite local
        """
        db_url = (os.getenv("DATABASE_URL") or "").strip()

        # --- ESTA É A ÚNICA CORREÇÃO NECESSÁRIA ---
        # A URL Interna do Render/Neon é 'postgres://'
        # O SQLAlchemy prefere 'postgresql://'
        if db_url.startswith("postgres://"):
            db_url = db_url.replace("postgres://", "postgresql://", 1)
        # ---------------------------------------------

        if cls.APP_ENV == "production":
            if not db_url:
                raise RuntimeError(
                    "DATABASE_URL não definido em produção. "
                    "No Render, configure a variável de ambiente DATABASE_URL."
                )
            
            # Sem lógicas de SSL. Apenas usa a URL interna.
            cls.SQLALCHEMY_DATABASE_URI = db_url
            return

        # development/test
        cls.SQLALCHEMY_DATABASE_URI = db_url or f"sqlite:///{cls.INSTANCE_DIR / 'database.db'}"