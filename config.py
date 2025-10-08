# config.py
import os
from dotenv import load_dotenv

basedir = os.path.abspath(os.path.dirname(__file__))
# Carrega o .env apenas em ambiente de desenvolvimento
if os.getenv('FLASK_ENV') != 'production':
    load_dotenv(os.path.join(basedir, '.env'))

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY')
    FLASK_APP = os.getenv('FLASK_APP')
    FLASK_ENV = os.getenv('FLASK_ENV')
    
    # Lógica de Banco de Dados Inteligente
    if FLASK_ENV == 'production':
        # Em produção (na Render), OBRIGATORIAMENTE usa a DATABASE_URL.
        # Se essa variável não existir, o app vai quebrar (o que é bom, pois nos avisa do erro).
        SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL')
        if SQLALCHEMY_DATABASE_URI and SQLALCHEMY_DATABASE_URI.startswith("postgres://"):
            SQLALCHEMY_DATABASE_URI = SQLALCHEMY_DATABASE_URI.replace("postgres://", "postgresql://", 1)
    else:
        # Em desenvolvimento (no seu PC), usa o SQLite como plano B.
        SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL') or \
            'sqlite:///' + os.path.join(basedir, 'instance', 'database.db')
            
    SQLALCHEMY_TRACK_MODIFICATIONS = False