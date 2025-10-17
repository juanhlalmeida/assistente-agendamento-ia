# app/commands.py
import click
from flask.cli import with_appcontext
from .extensions import db
from .models.tables import Profissional, Servico, Agendamento
from datetime import datetime

def reset_database_logic():
    """
    Esta função contém a lógica pura de apagar e recriar o banco.
    Pode ser chamada de qualquer lugar.
    """
    db.drop_all()
    db.create_all()

    # Cria os profissionais para a Vila Chic
    p1 = Profissional(nome='Romario')
    p2 = Profissional(nome='Guilherme')
    db.session.add_all([p1, p2])
    
    # Cria os serviços com duração e preço
    s1 = Servico(nome='Corte de Cabelo', duracao=30, preco=40.00)
    s2 = Servico(nome='Barba Terapia', duracao=30, preco=35.00)
    s3 = Servico(nome='Corte e Barba', duracao=60, preco=70.00)
    s4 = Servico(nome='Acabamento (Pezinho)', duracao=15, preco=15.00)
    db.session.add_all([s1, s2, s3, s4])
    
    db.session.commit()

@click.command(name='seed_db')
@with_appcontext
def seed_db_command():
    """Comando de terminal que executa a lógica de reset."""
    try:
        reset_database_logic()
        click.echo('Banco de dados povoado com sucesso!')
    except Exception as e:
        click.echo(f'Ocorreu um erro ao popular o banco de dados: {str(e)}')