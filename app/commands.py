# app/commands.py
import click
from datetime import datetime
from .extensions import db
from .models.tables import Profissional, Servico, Agendamento

def init_app(app):
    @app.cli.command("seed-db")
    def seed_db_command():
        """Cria e povoa o banco de dados com dados de teste."""
        db.drop_all()
        db.create_all()

        p1 = Profissional(nome="Bruno Silva")
        s1 = Servico(nome="Corte Masculino", duracao=30)
        db.session.add(p1)
        db.session.add(s1)
        db.session.commit()

        a1 = Agendamento(
            nome_cliente="Ana Costa",
            telefone_cliente="11987654321",
            data_hora=datetime.now(),
            profissional_id=p1.id,
            servico_id=s1.id
        )
        db.session.add(a1)
        db.session.commit()
        
        click.echo("Banco de dados povoado com sucesso!")