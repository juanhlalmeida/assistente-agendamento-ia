from app.types.business_types import BusinessType
from app.plugins.barbershop_plugin import BarbershopPlugin
# Futuro: from app.plugins.pousada_plugin import PousadaPlugin

def carregar_plugin_negocio(barbearia):
    """
    Fábrica de Plugins: Retorna a instância correta do plugin
    baseada no tipo de negócio da barbearia.
    """
    
    # 1. Descobre o tipo (usa 'barbershop' como segurança se for None)
    tipo_str = getattr(barbearia, 'business_type', 'barbershop') or 'barbershop'
    
    # 2. Retorna o Plugin correto
    if tipo_str == BusinessType.POUSADA.value:
        # return PousadaPlugin(barbearia) # (Ainda vamos criar este)
        pass 
        
    # 3. Padrão: Retorna o Plugin de Barbearia
    return BarbershopPlugin(barbearia)
