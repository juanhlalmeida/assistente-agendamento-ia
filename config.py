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
    SECRET_KEY1: str = os.getenv("SECRET_KEY1", "change-me")

    # SQLAlchemy
    SQLALCHEMY_DATABASE_URI: str | None = None
    SQLALCHEMY_TRACK_MODIFICATIONS: bool = False

    # Diretório para SQLite local (dev)
    INSTANCE_DIR = BASE_DIR / "instance"
    INSTANCE_DIR.mkdir(exist_ok=True)

    # --- INÍCIO DA IMPLEMENTAÇÃO (Conforme o PDF) ---
    # --- Configuração do Cache (Redis) ---
    # [cite: 63, 254]
    
    # O Render injeta a URL de conexão do Redis nesta variável
    REDIS_URL = os.environ.get('REDIS_URL')
    if REDIS_URL:
        # ESTAMOS NO RENDER (Produção)
        # Flask-Caching usará esta URL para se conectar ao serviço Redis
        CACHE_TYPE = 'redis'
        CACHE_REDIS_URL = REDIS_URL
        
        # Adiciona esta opção para compatibilidade com conexões SSL ('rediss://')
        # que alguns provedores de Redis (incluindo o Render) podem usar.
        CACHE_REDIS_OPTIONS = {
            'ssl_cert_reqs': None
        }
        
    else:
        # ESTAMOS LOCALMENTE (Desenvolvimento)
        # Se 'REDIS_URL' não for encontrada, usa o cache em memória simples.
        # Isso permite que você rode o projeto localmente sem o Redis instalado.
        CACHE_TYPE = 'SimpleCache'
    
    # Tempo padrão que o histórico de chat ficará salvo (1 hora)
    CACHE_DEFAULT_TIMEOUT = int(os.environ.get('CACHE_DEFAULT_TIMEOUT', 3600))
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