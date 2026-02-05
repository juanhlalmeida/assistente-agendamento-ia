from enum import Enum

class BusinessType(Enum):
    """
    Define os tipos de negócios suportados pelo sistema SaaS.
    """
    BARBERSHOP = "barbershop"      # Barbearias, Salões, Studios (Lógica de Slots/Minutos)
    POUSADA = "accommodation"      # Pousadas, Hotéis, Airbnb (Lógica de Diárias/Noites)

    @classmethod
    def default(cls):
        return cls.BARBERSHOP
