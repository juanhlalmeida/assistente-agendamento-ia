# app/commands.py
import logging
import os
from flask import current_app
from app.extensions import db
# Importamos TODOS os modelos necessários
from app.models.tables import Barbearia, User, Profissional, Servico, Agendamento # type: ignore
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

def reset_database_logic():
    """
    Apaga todas as tabelas, recria a estrutura e popula com dados
    da "Barber Shop Jeziel Oliveira".
    """
    try:
        logging.info("Iniciando reset do banco de dados para Barber Shop Jeziel Oliveira...")
        
        db.drop_all()
        logging.info("Tabelas antigas apagadas.")
        
        db.create_all()
        logging.info("Tabelas recriadas com a estrutura atual.")

        # --- POPULANDO COM DADOS INICIAIS ---

        # 1. Criar a Barbearia "Jeziel Oliveira"
        numero_sandbox_twilio = "+14155238886" # Número do Sandbox Twilio
        
        barbearia_principal = Barbearia(
            nome_fantasia="Barber Shop Jeziel Oliveira", # Nome real
            telefone_whatsapp=numero_sandbox_twilio,
            status_assinatura='ativa' 
        )
        db.session.add(barbearia_principal)
        db.session.flush() # Garante o ID
        
        if barbearia_principal.id is None:
             raise Exception("Falha crítica: Barbearia não recebeu um ID após o flush.")
        
        logging.info(f"Barbearia '{barbearia_principal.nome_fantasia}' pré-criada com ID {barbearia_principal.id}.")

        # 2. Criar o Usuário Admin para esta Barbearia
        email_admin_padrao = "admin@email.com" 
        senha_admin_padrao = "admin123"      
        
        admin_user = User(
            email=email_admin_padrao,
            nome='Admin Jeziel Oliveira', # Nome descritivo
            role='admin', 
            barbearia_id=barbearia_principal.id 
        )
        admin_user.set_password(senha_admin_padrao)
        db.session.add(admin_user)
        logging.info(f"Usuário admin '{admin_user.email}' preparado.")

        # --- NOVO: Criar o Usuário Super Admin (VOCÊ) ---
        # Substitua pelo seu email e senha desejados!
        email_super_admin = "juanhl_almeida@hotmail.com" 
        senha_super_admin = "174848STi@"

        # Verifica se já existe para evitar erro em resets futuros (opcional)
        super_admin_existente = User.query.filter_by(email=email_super_admin).first()
        if not super_admin_existente:
            super_admin_user = User(
                email=email_super_admin,
                nome="Super Admin", # Ou seu nome
                role='super_admin', # Role especial!
                barbearia_id=None # Super admin não pertence a nenhuma barbearia
            )
            super_admin_user.set_password(senha_super_admin)
            db.session.add(super_admin_user)
            logging.info(f"Usuário Super Admin '{super_admin_user.email}' preparado.")
        else:
             logging.info(f"Usuário Super Admin '{email_super_admin}' já existe.")
        
        # 3. Criar Profissional(is) para esta Barbearia
        prof_fabio = Profissional(nome="Fabio", barbearia_id=barbearia_principal.id)
        # Mantendo Romario e Guilherme como exemplos, remova se não quiser
        prof_romario = Profissional(nome="Romario", barbearia_id=barbearia_principal.id)
        prof_guilherme = Profissional(nome="Guilherme", barbearia_id=barbearia_principal.id)
        db.session.add_all([prof_fabio, prof_romario, prof_guilherme])
        logging.info("Profissionais 'Fabio', 'Romario', 'Guilherme' preparados.")

        # 4. Criar Serviços com durações estimadas
        servicos = [
            Servico(nome="Freestyle", duracao=30, preco=15.00, barbearia_id=barbearia_principal.id),
            Servico(nome="Pezinho do Cabelo (Acabamento)", duracao=15, preco=15.00, barbearia_id=barbearia_principal.id),
            Servico(nome="Platinado", duracao=120, preco=100.00, barbearia_id=barbearia_principal.id), # Usando preço base
            Servico(nome="Luzes", duracao=90, preco=50.00, barbearia_id=barbearia_principal.id),      # Usando preço base
            Servico(nome="Coloração", duracao=60, preco=50.00, barbearia_id=barbearia_principal.id),   # Usando preço base
            Servico(nome="Pigmentação", duracao=30, preco=30.00, barbearia_id=barbearia_principal.id), # Usando preço base
            Servico(nome="Selagem", duracao=90, preco=70.00, barbearia_id=barbearia_principal.id),     # Usando preço base
            Servico(nome="Escova Progressiva", duracao=120, preco=70.00, barbearia_id=barbearia_principal.id), # Usando preço base
            Servico(nome="Relaxamento", duracao=60, preco=70.00, barbearia_id=barbearia_principal.id),# Usando preço base
            Servico(nome="Alisamento", duracao=90, preco=70.00, barbearia_id=barbearia_principal.id), # Usando preço base
            Servico(nome="Hidratação", duracao=30, preco=40.00, barbearia_id=barbearia_principal.id),  # Usando preço base
            Servico(nome="Reconstrução", duracao=45, preco=70.00, barbearia_id=barbearia_principal.id),# Usando preço base
            Servico(nome="Sobrancelha", duracao=15, preco=10.00, barbearia_id=barbearia_principal.id),
            Servico(nome="Aparar a barba", duracao=15, preco=15.00, barbearia_id=barbearia_principal.id),
            Servico(nome="Barba Terapia", duracao=30, preco=30.00, barbearia_id=barbearia_principal.id),
            Servico(nome="Corte Tradicional", duracao=30, preco=30.00, barbearia_id=barbearia_principal.id),
            Servico(nome="Corte Navalhado", duracao=45, preco=35.00, barbearia_id=barbearia_principal.id)
        ]
        db.session.add_all(servicos)
        logging.info("Serviços da 'Barber Shop Jeziel Oliveira' preparados.")
        
        # 5. Commit Final
        db.session.commit() 
        logging.info("População inicial (Jeziel + Super Admin) concluída com sucesso.")

    except Exception as e:
        db.session.rollback() 
        logging.error(f"ERRO CRÍTICO durante o reset e população (Jeziel Oliveira): {e}", exc_info=True)
        raise e