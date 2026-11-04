from app.types.business_types import BusinessType
from app.plugins.barbershop_plugin import BarbershopPlugin
from app.plugins.pousada_plugin import PousadaPlugin
from app.plugins.odonto_plugin import OdontoPlugin

def carregar_plugin_negocio(barbearia):
    """
    Fábrica de Plugins: Retorna a instância correta do plugin
    baseada no tipo de negócio da barbearia.
    """
    
    # 1. Descobre o tipo (usa 'barbershop' como segurança se for None)
    tipo_str = (getattr(barbearia, 'business_type', 'barbershop') or 'barbershop').lower()
    
    # 2. Retorna o Plugin correto
    if tipo_str in (BusinessType.POUSADA.value, 'pousada'):
        return PousadaPlugin(barbearia)
    if tipo_str in (BusinessType.ODONTOLOGIA.value, 'odonto', 'dental'):
        return OdontoPlugin(barbearia)
        
    # 3. Padrão: Retorna o Plugin de Barbearia
    return BarbershopPlugin(barbearia)
