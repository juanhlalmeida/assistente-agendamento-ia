from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Any, Dict

class BaseBusinessPlugin(ABC):
    """
    Interface Abstrata (Contrato) que todo plugin de negócio deve implementar.
    Isso garante que o Core do sistema (WhatsApp, Auth) consiga falar 
    com qualquer negócio (Pousada ou Barbearia) do mesmo jeito.
    """

    def __init__(self, business_model):
        self.business = business_model

    @abstractmethod
    def gerar_system_prompt(self) -> str:
        """
        Retorna o Prompt de Sistema (Persona da IA) específico para este negócio.
        Ex: "Você é um recepcionista..." ou "Você é um barbeiro..."
        """
        pass

    @abstractmethod
    def calcular_disponibilidade(self, data_ref: datetime, **kwargs) -> List[Any]:
        """
        Calcula o que está livre.
        - Barbearia retorna: Lista de Horários (datetime)
        - Pousada retorna: Lista de Quartos Livres ou Datas
        """
        pass

    @abstractmethod
    def buscar_recursos(self) -> List[Any]:
        """
        Retorna o 'produto principal' do negócio.
        - Barbearia: Lista de Profissionais
        - Pousada: Lista de Quartos/Acomodações
        """
        pass

    @abstractmethod
    def buscar_servicos(self) -> List[Any]:
        """
        Retorna o que é vendável.
        - Barbearia: Cortes, Barba, Cílios
        - Pousada: Diárias, Pacotes de Feriado
        """
        pass
