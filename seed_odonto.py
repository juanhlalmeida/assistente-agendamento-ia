"""
seed_odonto.py — Script de Seed da Vitrine Odontológica 'Concept Dental Studio'.
Pode ser executado via terminal (`python seed_odonto.py`) ou acessando a rota `/setup-odonto`.
"""
from werkzeug.security import generate_password_hash
from app import create_app
from app.extensions import db
from app.models.tables import User
from app.routes import executar_seed_odonto


def main():
    app = create_app()
    with app.app_context():
        clinica, admin_user, resumo = executar_seed_odonto()

        # Garante atualização explícita do hash da senha caso o usuário já existisse no banco
        usuario_existente = User.query.filter_by(email="contato@conceptdental.com.br").first()
        if usuario_existente:
            usuario_existente.password_hash = generate_password_hash("odonto123")
            db.session.add(usuario_existente)
            db.session.commit()
        print("=" * 64)
        print("🦷 VITRINE ODONTOLÓGICA CRIADA / ATUALIZADA COM SUCESSO!")
        print("=" * 64)
        print(f"Clínica:        {clinica.nome_fantasia} (ID: {clinica.id})")
        print(f"Nicho (Tipo):   {clinica.business_type}")
        print(f"E-mail Login:   {resumo['email_login']}")
        print(f"Senha Login:    {resumo['senha_login']}")
        print(f"Profissionais:  {resumo['profissionais']} (Dr. Carlos - Ortodontia, Dra. Ana - Clínica Geral)")
        print(f"Procedimentos:  {resumo['servicos']} (Avaliação 30m, Limpeza/Profilaxia 45m, Clareamento 60m, Manutenção 30m)")
        print(f"Agendamentos:   {resumo['agendamentos_criados']} criados na grade de vitrine")
        print("=" * 64)


if __name__ == "__main__":
    main()
