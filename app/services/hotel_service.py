from datetime import datetime, timedelta
from app.models.tables import Agendamento, Profissional, Servico, Barbearia
from app.extensions import db
import logging

def verificar_disponibilidade_hotel(barbearia_id: int, data_entrada_str: str, qtd_dias: float, qtd_pessoas: float) -> str:
    """
    Verifica disponibilidade real de hotelaria (Colisão de Datas) e retorna STRING formatada para a IA.
    """
    try:
        qtd_dias_float = float(qtd_dias)
        qtd_pessoas_int = int(float(qtd_pessoas))

        # Carrega a barbearia para obter as regras de negócio
        barbearia = Barbearia.query.get(barbearia_id)
        if not barbearia:
            return "Erro interno: Estabelecimento não encontrado."

        # 🚨 VALIDAÇÕES DINÂMICAS DO BANCO DE DADOS (A Barreira)
        min_pessoas = getattr(barbearia, 'min_pessoas_reserva', 1)
        if qtd_pessoas_int < min_pessoas:
            logging.info(f"Reserva recusada: pessoas ({qtd_pessoas_int}) abaixo do mínimo ({min_pessoas})")
            return f"❌ REGRA DA POUSADA: Não aceitamos reservas para {qtd_pessoas_int} pessoa(s). O mínimo exigido é de {min_pessoas} pessoas. Avise o cliente educadamente e encerre a tentativa."

        min_dias = getattr(barbearia, 'min_dias_reserva', 1)
        if qtd_dias_float < min_dias:
            logging.info(f"Reserva recusada: dias ({qtd_dias_float}) abaixo do mínimo ({min_dias})")
            return f"❌ REGRA DA POUSADA: O mínimo de estadia exigido é de {min_dias} diárias. Avise o cliente educadamente e encerre a tentativa."

        # 1. Define Horários Padrão (Check-in 12:00 / Check-out 16:00 do último dia) - alinhado com o plugin
        dt_entrada = datetime.strptime(data_entrada_str, '%Y-%m-%d').replace(hour=12, minute=0, second=0)
        dt_saida = dt_entrada + timedelta(days=qtd_dias_float)
        dt_saida = dt_saida.replace(hour=16, minute=0, second=0)  # Check-out 16h

        # 2. Busca quartos que comportam a quantidade de pessoas
        quartos_candidatos = Profissional.query.filter(
            Profissional.barbearia_id == barbearia_id,
            Profissional.tipo == 'quarto',
            Profissional.capacidade >= qtd_pessoas_int
        ).all()
        
        disponiveis = []

        for quarto in quartos_candidatos:
            # 3. Verifica se tem agendamento colidindo nesse período
            agendamentos = Agendamento.query.filter(
                Agendamento.profissional_id == quarto.id,
                Agendamento.data_hora >= datetime.now().replace(hour=0, minute=0)
            ).all()
            
            ocupado = False
            for ag in agendamentos:
                ag_inicio = ag.data_hora
                
                # Se o serviço tem duração (em minutos), usamos ela. Se não, assumimos 24h (1440 min)
                duracao = ag.servico.duracao if ag.servico else 1440
                ag_fim = ag_inicio + timedelta(minutes=duracao)
                
                # Teste de colisão de datas: (StartA < EndB) and (EndA > StartB)
                if dt_entrada < ag_fim and dt_saida > ag_inicio:
                    ocupado = True
                    break  # Já achou um bloqueio, para de procurar
            
            if not ocupado:
                disponiveis.append(f"{quarto.nome}")

        if not disponiveis:
            return f"Infelizmente não temos nenhum quarto disponível que comporte {qtd_pessoas_int} pessoas para estas datas."

        # Retornamos como String para a IA não se perder
        return f"✅ Quartos disponíveis encontrados: {', '.join(disponiveis)}."

    except Exception as e:
        logging.error(f"Erro na disponibilidade hotel: {e}")
        return "Erro ao processar as datas. Verifique se o formato está correto."

def realizar_reserva_quarto(barbearia_id: int, nome_cliente: str, telefone: str, quarto_nome: str, data_entrada_str: str, qtd_dias: int) -> str:
    """
    Cria a reserva no banco com a duração correta em minutos.
    O parâmetro telefone é preenchido automaticamente pelo sistema.
    """
    try:
        qtd_dias_float = float(qtd_dias)

        # 🚨 1. TRAVA DE REGRA DE NEGÓCIO (MÍNIMO DE DIAS) 🚨
        if qtd_dias_float < 1.5:
            return "A Pousada Recanto da Maré exige um mínimo de 1 diária e meia (por favor, informe 2 dias ou mais para prosseguir com a reserva)."

        # 2. Busca o Quarto (Pelo nome e ID da loja)
        quarto = Profissional.query.filter_by(barbearia_id=barbearia_id, nome=quarto_nome).first()
        if not quarto:
            return "Erro: Quarto não encontrado no sistema. Por favor, escolha um da lista disponível."

        # 3. Define datas
        dt_entrada = datetime.strptime(data_entrada_str, '%Y-%m-%d').replace(hour=12, minute=0)
        
        # 4. Define Duração Total em Minutos para bloquear a agenda no painel
        duracao_total_minutos = int(qtd_dias_float * 1440)
        
        # 5. Busca ou Cria um Serviço ESPECÍFICO para essa duração
        nome_servico = f"Reserva Hospedagem ({int(qtd_dias_float)} dias)"
        servico = Servico.query.filter_by(barbearia_id=barbearia_id, nome=nome_servico).first()
        
        if not servico:
            servico = Servico(nome=nome_servico, preco=0.0, duracao=duracao_total_minutos, barbearia_id=barbearia_id)
            db.session.add(servico)
            db.session.commit()

        # 6. Cria o Agendamento
        nova_reserva = Agendamento(
            nome_cliente=nome_cliente,
            telefone_cliente=telefone,
            data_hora=dt_entrada,
            profissional_id=quarto.id,
            servico_id=servico.id,
            barbearia_id=barbearia_id
        )

        db.session.add(nova_reserva)
        db.session.commit()
        
        return f"✅ Tudo certo! Pré-reserva confirmada no {quarto.nome} para o dia {data_entrada_str} ({int(qtd_dias_float)} diárias)!"

    except Exception as e:
        logging.error(f"Erro ao reservar: {e}")
        return f"Desculpe, ocorreu um erro ao registrar a reserva no sistema: {e}"
