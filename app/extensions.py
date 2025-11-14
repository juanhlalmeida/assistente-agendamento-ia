# app/extensions.py
# (Código completo, preservado e corrigido)
from flask_sqlalchemy import SQLAlchemy
from flask_caching import Cache # <-- ADICIONADO

db = SQLAlchemy()
cache = Cache() # <-- ADICIONADO