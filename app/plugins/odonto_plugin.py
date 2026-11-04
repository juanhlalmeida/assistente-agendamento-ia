from app.plugins.barbershop_plugin import BarbershopPlugin
from app.models.tables import Profissional, Servico


class OdontoPlugin(BarbershopPlugin):
    """
    Plugin modular para Clínicas Odontológicas (ex: Concept Dental Studio).
    Hereda o motor de cálculo de slots em minutos (30 em 30 min) do BarbershopPlugin,
    adicionando diretrizes clínicas e vocabulário odontológico para a IA.
    """

    def gerar_system_prompt(self) -> str:
        nome_clinica = getattr(self.business, 'nome_fantasia', 'Clínica Odontológica')
        return (
            f"PERSONA: Recepcionista Virtual da {nome_clinica} (Clínica Odontológica Premium).\n"
            "TOM: Clínico, acolhedor, educado, tranquilizador e objetivo. 🦷✨\n"
            "TRATAMENTO: Trate o cliente como paciente ou pelo nome próprio com cordialidade.\n"
            "OBJETIVO: Agendar avaliações, profilaxias, clareamentos, manutenções ortodônticas e procedimentos odontológicos.\n"
            "REGRA DE OURO ESTRITA: VOCÊ ESTÁ TERMINANTEMENTE PROIBIDO DE INVENTAR OU LISTAR QUALQUER PROCEDIMENTO, PREÇO OU DURAÇÃO "
            "QUE NÃO TENHA SIDO EXPRESSAMENTE RETORNADO PELA FERRAMENTA/FUNÇÃO DE CONSULTA AO BANCO DE DADOS (`listar_servicos`). "
            "SE A FUNÇÃO FALHAR, DIGA APENAS QUE ESTÁ VERIFICANDO O SISTEMA CLÍNICO."
        )

    def buscar_recursos(self):
        """Retorna os Dentistas / Especialistas da clínica."""
        return Profissional.query.filter_by(barbearia_id=self.business.id).all()

    def buscar_servicos(self):
        """Retorna os Procedimentos Odontológicos da clínica."""
        return Servico.query.filter_by(barbearia_id=self.business.id).all()
