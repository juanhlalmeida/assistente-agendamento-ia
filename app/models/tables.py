# app/models/tables.py
from app.extensions import db
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

# ---------------------------------------------------------------------
# FASE DE EXPANSÃO: NOVO MODELO (O "DONO")
# ---------------------------------------------------------------------
# Esta é a tabela mais importante. Ela representa o SEU cliente (a barbearia).
# Todos os outros dados serão "etiquetados" com o ID desta tabela.
class Barbearia(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome_fantasia = db.Column(db.String(100), nullable=False)
    
    # Este é o "Número do Robô" (ex: o n.º da Twilio) que esta barbearia usa.
    # É assim que o webhook saberá de qual barbearia a mensagem veio.
    # Deve ser único!
    telefone_whatsapp = db.Column(db.String(20), unique=True, nullable=False)
    
    # Campo para controlo de pagamentos (FASE DE NEGÓCIO)
    status_assinatura = db.Column(db.String(20), nullable=False, default='inativa')
    
    # Relações: Define o que "pertence" a esta barbearia
    # O 'cascade="all, delete-orphan"' significa que se uma barbearia for
    # apagada, todos os seus dados (usuários, profissionais, etc.) são
    # apagados automaticamente, mantendo o banco limpo.
    
    # O admin do painel
    usuarios = db.relationship('User', backref='barbearia', lazy=True, cascade="all, delete-orphan")
    
    # Os funcionários da barbearia
    profissionais = db.relationship('Profissional', backref='barbearia', lazy=True, cascade="all, delete-orphan")
    
    # Os serviços da barbearia
    servicos = db.relationship('Servico', backref='barbearia', lazy=True, cascade="all, delete-orphan")
    
    # Os agendamentos da barbearia
    agendamentos = db.relationship('Agendamento', backref='barbearia', lazy=True, cascade="all, delete-orphan")


# ---------------------------------------------------------------------
# FASE DE EXPANSÃO: MODELOS ATUALIZADOS (AS "ETIQUETAS")
# ---------------------------------------------------------------------

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), index=True, unique=True, nullable=False) 
    nome = db.Column(db.String(100), nullable=True) 
    password_hash = db.Column(db.String(256)) 
    
    # --- DETALHE IMPORTANTE (Para o Super-Admin) ---
    # O 'role' permite-nos saber quem é "Super Admin" (você)
    # e quem é "Admin" (o dono da barbearia).
    role = db.Column(db.String(20), nullable=False, default='admin')
    
    # --- A "ETIQUETA" ---
    # Adicionamos a ligação à Barbearia.
    # É 'nullable=True' porque o Super Admin (você) não pertence
    # a nenhuma barbearia específica.
    barbearia_id = db.Column(db.Integer, db.ForeignKey('barbearia.id'), nullable=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

class Profissional(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    
    # --- A "ETIQUETA" ---
    # Adicionamos a ligação à Barbearia.
    # É 'nullable=False' porque um profissional TEM de pertencer a uma barbearia.
    barbearia_id = db.Column(db.Integer, db.ForeignKey('barbearia.id'), nullable=False)
    
    # A relação 'agendamentos' continua igual
    agendamentos = db.relationship('Agendamento', backref='profissional', lazy=True)

class Servico(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    duracao = db.Column(db.Integer, nullable=False) # Duração em minutos
    preco = db.Column(db.Float, nullable=False, default=0.0) 
    
    # --- A "ETIQUETA" ---
    # Adicionamos a ligação à Barbearia.
    barbearia_id = db.Column(db.Integer, db.ForeignKey('barbearia.id'), nullable=False)

    # A relação 'agendamentos' continua igual
    agendamentos = db.relationship('Agendamento', backref='servico', lazy=True)

class Agendamento(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    data_hora = db.Column(db.DateTime, nullable=False)
    nome_cliente = db.Column(db.String(100), nullable=False)
    telefone_cliente = db.Column(db.String(20), nullable=False)
    
    # As chaves de profissional e serviço continuam iguais
    profissional_id = db.Column(db.Integer, db.ForeignKey('profissional.id'), nullable=False)
    servico_id = db.Column(db.Integer, db.ForeignKey('servico.id'), nullable=False)
    
    # --- A "ETIQUETA" ---
    # Adicionamos a ligação à Barbearia.
    barbearia_id = db.Column(db.Integer, db.ForeignKey('barbearia.id'), nullable=False)