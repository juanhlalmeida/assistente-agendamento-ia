from datetime import datetime, timedelta
from app.models.tables import Agendamento, Profissional, Servico, Barbearia
from app.extensions import db
import logging

def verificar_disponibilidade_hotel(barbearia_id: int, data_entrada_str: str, qtd_dias: int, qtd_pessoas: int) -> list:
    """
    Verifica disponibilidade real de hotelaria (Colisão de Datas).
    
    Args:
        data_entrada_str: 'YYYY-MM-DD'
        qtd_dias: Quantas diárias
        qtd_pessoas: Quantidade de hóspedes
        
    Returns:
        Lista de nomes dos quartos disponíveis (ou lista vazia se nenhum disponível ou regras não atendidas).
    """
    try:
        # Carrega a barbearia para obter as regras de negócio
        barbearia = Barbearia.query.get(barbearia_id)
        if not barbearia:
            logging.error(f"Barbearia ID {barbearia_id} não encontrada em verificar_disponibilidade_hotel")
            return []

        # Validações das regras de negócio da pousada
        if qtd_pessoas < barbearia.min_pessoas_reserva:
            logging.info(f"Reserva recusada: número de pessoas ({qtd_pessoas}) abaixo do mínimo ({barbearia.min_pessoas_reserva})")
            return []  # IA interpretará como nenhum quarto disponível e poderá explicar a regra

        if qtd_dias < barbearia.min_dias_reserva:
            logging.info(f"Reserva recusada: número de dias ({qtd_dias}) abaixo do mínimo ({barbearia.min_dias_reserva})")
            return []

        # 1. Define Horários Padrão (Check-in 12:00 / Check-out 16:00 do último dia) - alinhado com o plugin
        dt_entrada = datetime.strptime(data_entrada_str, '%Y-%m-%d').replace(hour=12, minute=0, second=0)
        dt_saida = dt_entrada + timedelta(days=float(qtd_dias))
        dt_saida = dt_saida.replace(hour=16, minute=0, second=0)  # Check-out 16h

        # 2. Busca quartos que comportam a quantidade de pessoas
        quartos_candidatos = Profissional.query.filter(
            Profissional.barbearia_id == barbearia_id,
            Profissional.tipo == 'quarto',
            Profissional.capacidade >= int(float(qtd_pessoas))
        ).all()
        
        disponiveis = []

        for quarto in quartos_candidatos:
            # 3. Verifica se tem agendamento colidindo nesse período
            # Lógica de Colisão: (StartA < EndB) and (EndA > StartB)
            
            # Busca agendamentos futuros desse quarto
            agendamentos = Agendamento.query.filter(
                Agendamento.profissional_id == quarto.id,
                Agendamento.data_hora >= datetime.now().replace(hour=0, minute=0)
            ).all()
            
            ocupado = False
            for ag in agendamentos:
                # Calcula início e fim do agendamento existente
                ag_inicio = ag.data_hora
                
                # Se o serviço tem duração (em minutos), usamos ela. Se não, assumimos 24h (1440 min)
                duracao = ag.servico.duracao if ag.servico else 1440  # Alterado de 1380 para 1440 para manter consistência
                ag_fim = ag_inicio + timedelta(minutes=duracao)
                
                # Teste de colisão de datas
                if dt_entrada < ag_fim and dt_saida > ag_inicio:
                    ocupado = True
                    break  # Já achou um bloqueio, para de procurar
            
            if not ocupado:
                disponiveis.append(f"{quarto.nome}")

        return disponiveis

    except Exception as e:
        logging.error(f"Erro na disponibilidade hotel: {e}")
        return []

def realizar_reserva_quarto(barbearia_id: int, nome_cliente: str, telefone: str, quarto_nome: str, data_entrada_str: str, qtd_dias: int) -> str:
    """
    Cria a reserva no banco com a duração correta em minutos.
    """
    try:
        # Carrega a barbearia para obter as regras de negócio
        barbearia = Barbearia.query.get(barbearia_id)
        if not barbearia:
            return "Erro: Estabelecimento não encontrado no sistema."

        qtd_dias_float = float(qtd_dias)

        # 🚨 VALIDAÇÕES DE REGRA DE NEGÓCIO (dinâmicas por barbearia) 🚨
        if qtd_pessoas < barbearia.min_pessoas_reserva:
            return f"Esta pousada só aceita reservas a partir de {barbearia.min_pessoas_reserva} pessoa(s). Por favor, ajuste a quantidade de hóspedes."

        if qtd_dias_float < barbearia.min_dias_reserva:
            return f"Esta pousada exige um mínimo de {barbearia.min_dias_reserva} diária(s). Por favor, informe um período maior."

        # 2. Busca o Quarto (Pelo nome e ID da loja)
        quarto = Profissional.query.filter_by(barbearia_id=barbearia_id, nome=quarto_nome).first()
        if not quarto:
            return "Erro: Quarto não encontrado no sistema. Por favor, escolha um da lista disponível."

        # Verifica capacidade do quarto (reforço de segurança)
        if qtd_pessoas > quarto.capacidade:
            return f"O quarto {quarto.nome} comporta no máximo {quarto.capacidade} pessoas. Por favor, escolha outro quarto."

        # 3. Define datas
        dt_entrada = datetime.strptime(data_entrada_str, '%Y-%m-%d').replace(hour=12, minute=0)
        
        # 4. Define Duração Total em Minutos para bloquear a agenda no painel
        duracao_total_minutos = int(qtd_dias_float * 1440)
        
        # 5. Busca ou Cria um Serviço ESPECÍFICO para essa duração (Garante que apareça no Painel)
        nome_servico = f"Reserva Hospedagem ({int(qtd_dias_float)} dias)"
        servico = Servico.query.filter_by(barbearia_id=barbearia_id, nome=nome_servico).first()
        
        if not servico:
            servico = Servico(nome=nome_servico, preco=0.0, duracao=duracao_total_minutos, barbearia_id=barbearia_id)
            db.session.add(servico)
            db.session.commit() # Importante salvar para gerar o ID antes de usar no agendamento

        # 6. Cria o Agendamento vinculando ao Quarto (Profissional) e ao Serviço correto
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
