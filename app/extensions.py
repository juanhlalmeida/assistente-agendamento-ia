# app/extensions.py
# (Código completo, com a extensão Cache adicionada)

from flask_sqlalchemy import SQLAlchemy
from flask_caching import Cache # [cite: 80]

db = SQLAlchemy()
cache = Cache() # [cite: 81]