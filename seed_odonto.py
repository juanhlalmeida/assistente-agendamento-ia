"""
seed_odonto.py — Script de Seed da Vitrine Odontológica 'Concept Dental Studio'.
Pode ser executado via terminal (`python seed_odonto.py`) ou acessando a rota `/setup-odonto`.
"""
from app import create_app
from app.routes import executar_seed_odonto


def main():
    app = create_app()
    with app.app_context():
        clinica, admin_user, resumo = executar_seed_odonto()
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
