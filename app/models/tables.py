# app/models/tables.py
from app.extensions import db

class Profissional(db.Model):
    # ... (código existente sem alterações)
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    agendamentos = db.relationship('Agendamento', backref='profissional', lazy=True)

class Servico(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    duracao = db.Column(db.Integer, nullable=False) # Duração em minutos
    preco = db.Column(db.Float, nullable=False, default=0.0) # ✅ NOVA LINHA ADICIONADA
    agendamentos = db.relationship('Agendamento', backref='servico', lazy=True)

class Agendamento(db.Model):
    # ... (código existente sem alterações)
    id = db.Column(db.Integer, primary_key=True)
    data_hora = db.Column(db.DateTime, nullable=False)
    nome_cliente = db.Column(db.String(100), nullable=False)
    telefone_cliente = db.Column(db.String(20), nullable=False)
    profissional_id = db.Column(db.Integer, db.ForeignKey('profissional.id'), nullable=False)
    servico_id = db.Column(db.Integer, db.ForeignKey('servico.id'), nullable=False)

def init_db():
    """Cria as tabelas no banco de dados se elas não existirem."""
    db.create_all()