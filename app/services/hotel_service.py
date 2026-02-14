from datetime import datetime, timedelta
from app.models.tables import Agendamento, Profissional, Servico
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
        Lista de nomes dos quartos disponíveis.
    """
    try:
        # 1. Define Horários Padrão (Check-in 12:00 / Check-out 11:00 do último dia)
        dt_entrada = datetime.strptime(data_entrada_str, '%Y-%m-%d').replace(hour=12, minute=0, second=0)
        dt_saida = dt_entrada + timedelta(days=float(qtd_dias))
        # Ajuste fino: Check-out geralmente é um pouco antes do Check-in para limpeza
        dt_saida = dt_saida.replace(hour=11, minute=0, second=0)

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
                
                # Se o serviço tem duração (em minutos), usamos ela. Se não, assumimos 23h (1 diária)
                duracao = ag.servico.duracao if ag.servico else 1380
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
        # Ex: 2 diárias = 2 * 24h * 60min = 2880 min
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
