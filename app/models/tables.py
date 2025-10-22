# app/models/tables.py
from app.extensions import db
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

# 🚀 CORREÇÃO: Adicionado o modelo User que faltava
# O UserMixin é necessário para o Flask-Login funcionar
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    
    # Assumindo login por email
    email = db.Column(db.String(120), index=True, unique=True, nullable=False) 
    
    # Usado no template do menu (current_user.nome)
    nome = db.Column(db.String(100), nullable=True) 
    
    # Campo para a senha criptografada
    password_hash = db.Column(db.String(256)) 

    def set_password(self, password):
        """Cria um hash seguro para a senha."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """Verifica se a senha fornecida bate com o hash."""
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

# --- Seus modelos existentes (sem alterações) ---

class Profissional(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    agendamentos = db.relationship('Agendamento', backref='profissional', lazy=True)

class Servico(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    duracao = db.Column(db.Integer, nullable=False) # Duração em minutos
    preco = db.Column(db.Float, nullable=False, default=0.0) # ✅ Esta linha está correta
    agendamentos = db.relationship('Agendamento', backref='servico', lazy=True)

class Agendamento(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    data_hora = db.Column(db.DateTime, nullable=False)
    nome_cliente = db.Column(db.String(100), nullable=False)
    telefone_cliente = db.Column(db.String(20), nullable=False)
    profissional_id = db.Column(db.Integer, db.ForeignKey('profissional.id'), nullable=False)
    servico_id = db.Column(db.Integer, db.ForeignKey('servico.id'), nullable=False)

# A função init_db() não é necessária quando se usa Flask-Migrate
# db.create_all() é chamado pelo 'flask db upgrade'