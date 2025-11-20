# seed_planos.py

from app import create_app
from app.extensions import db
from app.models.tables import Plano

app = create_app()

with app.app_context():
    # Limpar planos existentes
    Plano.query.delete()
    
    # Criar planos
    basico = Plano(
        nome="Básico",
        descricao="Ideal para começar",
        preco_mensal=49.90,
        max_profissionais=2,
        max_servicos=10,
        tem_ia=True,
        ativo=True
    )
    
    premium = Plano(
        nome="Premium",
        descricao="Para barbearias em crescimento",
        preco_mensal=99.90,
        max_profissionais=5,
        max_servicos=30,
        tem_ia=True,
        ativo=True
    )
    
    empresarial = Plano(
        nome="Empresarial",
        descricao="Solução completa ilimitada",
        preco_mensal=199.90,
        max_profissionais=999,
        max_servicos=999,
        tem_ia=True,
        ativo=True
    )
    
    db.session.add_all([basico, premium, empresarial])
    db.session.commit()
    
    print("✅ 3 planos criados com sucesso!")
    print(f"  - Básico: R$ {basico.preco_mensal}")
    print(f"  - Premium: R$ {premium.preco_mensal}")
    print(f"  - Empresarial: R$ {empresarial.preco_mensal}")

