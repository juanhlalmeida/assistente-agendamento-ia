# app/commands.py
import logging
import os
from flask import current_app
from app.extensions import db
from app.models.tables import Barbearia, User, Profissional, Servico, Agendamento # type: ignore
from datetime import datetime # Para o agendamento de teste

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

def reset_database_logic():
    """
    Apaga todas as tabelas, recria a estrutura a partir dos modelos atuais
    e popula com dados iniciais para a primeira barbearia de teste.
    """
    try:
        logging.info("Iniciando reset do banco de dados...")
        
        # Apaga todas as tabelas existentes
        db.drop_all()
        logging.info("Tabelas antigas apagadas.")
        
        # Cria todas as tabelas novamente, com a estrutura atualizada
        db.create_all()
        logging.info("Tabelas recriadas com a nova estrutura.")

        # --- POPULANDO COM DADOS INICIAIS ---

        # 1. Criar a primeira Barbearia (Teste)
        numero_sandbox_twilio = "+14155238886" # Certifique-se que este é o número exato
        
        primeira_barbearia = Barbearia(
            nome_fantasia="Vila Chic Teste",
            telefone_whatsapp=numero_sandbox_twilio,
            status_assinatura='ativa' 
        )
        db.session.add(primeira_barbearia)
        
        # 🚀 CORREÇÃO: Força o banco a atribuir um ID à barbearia AGORA
        db.session.flush() 
        
        # Verificação (opcional, mas bom para debug)
        if primeira_barbearia.id is None:
             raise Exception("Falha crítica: Barbearia não recebeu um ID após o flush.")
        
        logging.info(f"Barbearia '{primeira_barbearia.nome_fantasia}' pré-criada com ID {primeira_barbearia.id}.")

        # 2. Criar o Usuário Admin para esta Barbearia (AGORA o ID existe)
        email_admin_padrao = "admin@email.com" 
        senha_admin_padrao = "admin123"      
        
        admin_user = User(
            email=email_admin_padrao,
            nome='Admin Barbearia Teste',
            role='admin', 
            barbearia_id=primeira_barbearia.id # Agora temos a certeza que o ID existe
        )
        admin_user.set_password(senha_admin_padrao)
        db.session.add(admin_user)
        logging.info(f"Usuário admin '{admin_user.email}' preparado.")
        
        # 3. Criar Profissionais para esta Barbearia (AGORA o ID existe)
        prof1 = Profissional(nome="Romario", barbearia_id=primeira_barbearia.id)
        prof2 = Profissional(nome="Guilherme", barbearia_id=primeira_barbearia.id)
        db.session.add_all([prof1, prof2])
        logging.info("Profissionais 'Romario' e 'Guilherme' preparados.")

        # 4. Criar Serviços para esta Barbearia (AGORA o ID existe)
        serv1 = Servico(nome="Corte de Cabelo", duracao=30, preco=40.00, barbearia_id=primeira_barbearia.id)
        serv2 = Servico(nome="Barba Terapia", duracao=30, preco=35.00, barbearia_id=primeira_barbearia.id)
        serv3 = Servico(nome="Corte e Barba", duracao=60, preco=70.00, barbearia_id=primeira_barbearia.id)
        db.session.add_all([serv1, serv2, serv3])
        logging.info("Serviços preparados.")
        
        # 5. (Opcional) Criar um Agendamento de Teste (AGORA o ID existe)
        # Precisamos dar 'flush' de novo para ter IDs de profissional/serviço
        db.session.flush() 
        # hoje_as_15 = datetime.now().replace(hour=15, minute=0, second=0, microsecond=0)
        # ag_teste = Agendamento(
        #     nome_cliente="Cliente Teste",
        #     telefone_cliente="+55999999999",
        #     data_hora=hoje_as_15,
        #     profissional_id=prof1.id, 
        #     servico_id=serv1.id,      
        #     barbearia_id=primeira_barbearia.id 
        # )
        # db.session.add(ag_teste)
        # logging.info("Agendamento de teste preparado.")

        # 🚀 CORREÇÃO: Salva TUDO no banco de dados DE UMA VEZ
        db.session.commit() 
        logging.info("População inicial do banco de dados concluída com sucesso.")

    except Exception as e:
        db.session.rollback() 
        logging.error(f"ERRO CRÍTICO durante o reset e população do banco: {e}", exc_info=True)
        raise e