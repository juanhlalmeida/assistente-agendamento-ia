# app/commands.py
import click
from flask.cli import with_appcontext
from .extensions import db
from .models.tables import Profissional, Servico, Agendamento
from datetime import datetime

@click.command(name='seed_db')
@with_appcontext
def seed_db_command():
    """Limpa e recria o banco de dados com dados de teste para a Vila Chic."""
    
    db.drop_all()
    db.create_all()

    # Cria os novos profissionais
    p1 = Profissional(nome='Romario')
    p2 = Profissional(nome='Guilherme')
    db.session.add_all([p1, p2])
    db.session.commit()
    
    # Cria os novos serviços com duração e preço
    s1 = Servico(nome='Corte de Cabelo', duracao=30, preco=40.00)
    s2 = Servico(nome='Barba Terapia', duracao=30, preco=35.00)
    s3 = Servico(nome='Corte e Barba', duracao=60, preco=70.00)
    s4 = Servico(nome='Acabamento (Pezinho)', duracao=15, preco=15.00)
    db.session.add_all([s1, s2, s3, s4])
    
    # Salva tudo para que os IDs sejam gerados
    db.session.commit()

    # Cria um agendamento de exemplo para hoje, para testes
    ag_exemplo = Agendamento(
        nome_cliente='Cliente de Teste',
        telefone_cliente='11999999999',
        data_hora=datetime.now().replace(hour=14, minute=0, second=0),
        profissional_id=p1.id,
        servico_id=s1.id
    )
    db.session.add(ag_exemplo)
    db.session.commit()
    
    click.echo('Banco de dados da Vila Chic Barber Shop povoado com sucesso!')