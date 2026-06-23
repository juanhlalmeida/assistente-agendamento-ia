# app/models/tables.py
from app.extensions import db
from datetime import datetime
from flask_login import UserMixin
from sqlalchemy import Text
from werkzeug.security import generate_password_hash, check_password_hash

# ---------------------------------------------------------------------
# FASE DE EXPANSÃO: NOVO MODELO (O "DONO")
# ---------------------------------------------------------------------
# Esta é a tabela mais importante. Ela representa o SEU cliente (a barbearia).
# Todos os outros dados serão "etiquetados" com o ID desta tabela.

class Barbearia(db.Model):
    __tablename__ = 'barbearia'  # Garante que a FK 'barbearia.id' funcione sempre

    business_type = db.Column(db.String(50), default='barbershop', server_default='barbershop', nullable=False)
    
    id = db.Column(db.Integer, primary_key=True)
    nome_fantasia = db.Column(db.String(100), nullable=False)

    # --- ADICIONE ESTAS DUAS LINHAS AQUI ---
    google_access_token = db.Column(db.String(500), nullable=True)
    google_refresh_token = db.Column(db.String(500), nullable=True)
    
    # --- CONTROLE DE ASSINATURA ---
    # Unifiquei os campos de status aqui para não haver duplicidade
    status_assinatura = db.Column(db.String(20), nullable=False, default='inativa')
    assinatura_ativa = db.Column(db.Boolean, default=False)
    assinatura_expira_em = db.Column(db.DateTime)
    
    # Relacionamento com a tabela de Assinaturas
    assinaturas = db.relationship('Assinatura', backref='barbearia', lazy=True)
    
    # --- NOVOS CAMPOS PARA API OFICIAL (META) ---
    meta_phone_number_id = db.Column(db.String(50), nullable=True)
    meta_access_token = db.Column(db.Text, nullable=True) # Access tokens
    
    # Este é o "Número do Robô" (ex: o n.º da Twilio/Meta) que esta barbearia usa.
    # É assim que o webhook saberá de qual barbearia a mensagem veio. Deve ser único!
    telefone_whatsapp = db.Column(db.String(20), unique=True, nullable=False)

    # --- NOVO: CONFIGURAÇÕES DE FUNCIONAMENTO & PERSONALIZAÇÃO ---
    # Horários (Editáveis pelo Dono no Painel)
    horario_abertura = db.Column(db.String(5), default="09:00")      # Ex: "09:00"
    horario_fechamento = db.Column(db.String(5), default="19:00")    # Ex: "19:00"
    
    # --- NOVO: Horário de Sábado (Funcionalidade criada hoje) ---
    horario_fechamento_sabado = db.Column(db.String(5), default="14:00")
    
    dias_funcionamento = db.Column(db.String(50), default="Terça a Sábado") # Ex: "Segunda a Sexta"

    # Personalização Visual e de Comportamento (IA)
    cor_primaria = db.Column(db.String(7), nullable=True)      # Ex: "#EC4899" (Para o Painel)
    emojis_sistema = db.Column(db.String(100), nullable=True)  # Ex: "🦋✨💖" (Para a IA)

    # --- NOVOS CAMPOS (Funcionalidades Extras) ---
    # Telefone pessoal do Dono para receber notificação de agendamento
    telefone_admin = db.Column(db.String(20), nullable=True)
    
    # Link da Imagem da Tabela de Preços (Segurança por ID)
    url_tabela_precos = db.Column(db.String(500), nullable=True)
    
    # 👇 A COLUNA NOVA E TÃO ESPERADA DA BASE DE CONHECIMENTO 👇
    regras_negocio = db.Column(db.Text, nullable=True)

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

# Configurações dinâmicas de negócio (Hotelaria)
    min_pessoas_reserva = db.Column(db.Integer, default=1, nullable=False)
    min_dias_reserva = db.Column(db.Float, default=1.0, nullable=False)

    # --- NOVOS CAMPOS PARA MIGRAÇÃO WAHA (Padrão Estrangulador) ---
    # Este campo define o roteamento. O 'server_default' garante que todos os seus 
    # clientes atuais continuarão automaticamente no sistema da Meta.
    provedor_mensageria = db.Column(db.String(20), default='meta', server_default='meta', nullable=False)
    
    # ID exclusivo da sessão deste cliente lá no WAHA (ex: 'barbearia_do_joao_01').
    waha_session_id = db.Column(db.String(100), unique=True, nullable=True)

# ---------------------------------------------------------------------
# FASE DE EXPANSÃO: MODELOS ATUALIZADOS (AS "ETIQUETAS")
# ---------------------------------------------------------------------

class User(UserMixin, db.Model):
    __tablename__ = 'user'

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
    __tablename__ = 'profissional'

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    
    # --- A "ETIQUETA" ---
    # Adicionamos a ligação à Barbearia.
    # É 'nullable=False' porque um profissional TEM de pertencer a uma barbearia.
    barbearia_id = db.Column(db.Integer, db.ForeignKey('barbearia.id'), nullable=False)

    # 👇 ADICIONE ESTAS DUAS LINHAS NOVAS 👇
    tipo = db.Column(db.String(50), default='humano')  # Ex: 'humano' ou 'quarto'
    capacidade = db.Column(db.Integer, default=1)      # Ex: 1 (cabeleireira) ou 4 (quarto quádruplo)
    
    # A relação 'agendamentos' continua igual
    agendamentos = db.relationship('Agendamento', backref='profissional', lazy=True)

class Servico(db.Model):
    __tablename__ = 'servico'

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
    __tablename__ = 'agendamento'

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

# ====================================
# SISTEMA DE ASSINATURAS (ATUALIZADO)
# ====================================

class Plano(db.Model):
    """Planos de assinatura com funcionalidades detalhadas"""
    __tablename__ = 'planos'
    
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(50), nullable=False)
    descricao = db.Column(db.Text)
    preco_mensal = db.Column(db.Float, nullable=False)
    
    # Limites do Plano
    max_profissionais = db.Column(db.Integer, default=3)
    max_servicos = db.Column(db.Integer, default=10)
    
    # Funcionalidades (Flags para controlar o que o plano oferece)
    tem_ia = db.Column(db.Boolean, default=True) # Agenda Básica com IA
    tem_notificacao_whatsapp = db.Column(db.Boolean, default=False)
    tem_ia_avancada = db.Column(db.Boolean, default=False) # Entende áudio e envia imagem
    tem_google_agenda = db.Column(db.Boolean, default=False)
    tem_espelhamento = db.Column(db.Boolean, default=False) # Espelhamento de WhatsApp
    tem_suporte_prioritario = db.Column(db.Boolean, default=False)
    
    ativo = db.Column(db.Boolean, default=True)
    criado_em = db.Column(db.DateTime, default=datetime.utcnow)
    
    assinaturas = db.relationship('Assinatura', backref='plano', lazy=True)


class Assinatura(db.Model):
    """Assinaturas das barbearias"""
    __tablename__ = 'assinaturas'
    
    id = db.Column(db.Integer, primary_key=True)
    barbearia_id = db.Column(db.Integer, db.ForeignKey('barbearia.id'), nullable=False)
    plano_id = db.Column(db.Integer, db.ForeignKey('planos.id'), nullable=False)
    
    # Dados do Mercado Pago
    mp_preapproval_id = db.Column(db.String(100), unique=True)
    mp_payer_id = db.Column(db.String(100))
    status = db.Column(db.String(20), default='pending')
    
    data_inicio = db.Column(db.DateTime)
    data_fim = db.Column(db.DateTime)
    proximo_vencimento = db.Column(db.DateTime)
    tentativas_falhas = db.Column(db.Integer, default=0)
    ultima_tentativa = db.Column(db.DateTime)
    
    criado_em = db.Column(db.DateTime, default=datetime.utcnow)
    atualizado_em = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    pagamentos = db.relationship('Pagamento', backref='assinatura', lazy=True, cascade='all, delete-orphan')


class Pagamento(db.Model):
    """Histórico de pagamentos"""
    __tablename__ = 'pagamentos'
    
    id = db.Column(db.Integer, primary_key=True)
    assinatura_id = db.Column(db.Integer, db.ForeignKey('assinaturas.id'), nullable=False)
    mp_payment_id = db.Column(db.String(100), unique=True)
    mp_status = db.Column(db.String(50))
    mp_status_detail = db.Column(db.String(100))
    valor = db.Column(db.Float, nullable=False)
    metodo_pagamento = db.Column(db.String(50))
    data_pagamento = db.Column(db.DateTime)
    data_vencimento = db.Column(db.DateTime)
    criado_em = db.Column(db.DateTime, default=datetime.utcnow)
    atualizado_em = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
class AgendamentoGoogleSync(db.Model):
    __tablename__ = 'agendamento_google_sync'
    
    id = db.Column(db.Integer, primary_key=True)
    agendamento_id = db.Column(db.Integer, db.ForeignKey('agendamento.id'), nullable=False)
    google_event_id = db.Column(db.String(255), nullable=True) # ID do evento lá no Google
    action = db.Column(db.String(20), nullable=False) # 'create', 'delete'
    status = db.Column(db.String(20), nullable=False) # 'success', 'failed'
    error_message = db.Column(db.Text, nullable=True)
    attempted_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    # Relacionamento (Opcional, ajuda na consulta)
    agendamento = db.relationship('Agendamento', backref=db.backref('google_syncs', lazy=True))
    
class ChatLog(db.Model):
    __tablename__ = 'chat_logs'

    id = db.Column(db.Integer, primary_key=True)
    barbearia_id = db.Column(db.Integer, db.ForeignKey('barbearia.id'))
    cliente_telefone = db.Column(db.String(30)) # Quem está falando
    mensagem = db.Column(db.Text)               # O que foi dito
    tipo = db.Column(db.String(10))             # 'cliente' ou 'ia'
    data_hora = db.Column(db.DateTime, default=datetime.now)

    # Relacionamento opcional se quiser filtrar por loja
    barbearia = db.relationship('Barbearia', backref='chats')
