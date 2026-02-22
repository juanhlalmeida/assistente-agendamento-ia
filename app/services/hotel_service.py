from datetime import datetime, timedelta
from app.models.tables import Agendamento, Profissional, Servico, Barbearia
from app.extensions import db
import logging
import traceback

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

        # 🚨 TRAVA DINÂMICA (Puxa do Banco de Dados que acabamos de atualizar) 🚨
        if barbearia_id == 8:
            min_pessoas_real = getattr(barbearia, 'min_pessoas_reserva', 2)
            min_dias_real = getattr(barbearia, 'min_dias_reserva', 1.5) # Atualizado para 1.5
        else:
            min_pessoas_real = getattr(barbearia, 'min_pessoas_reserva', 1)
            min_dias_real = getattr(barbearia, 'min_dias_reserva', 1.0)

        # VALIDAÇÕES RÍGIDAS
        if qtd_pessoas_int < min_pessoas_real:
            logging.warning(f"[TRAVA] Reserva recusada (ID {barbearia_id}): pessoas ({qtd_pessoas_int}) abaixo do mínimo exigido ({min_pessoas_real})")
            return f"❌ REGRA: A pousada só aceita no mínimo {min_pessoas_real} pessoas. Avise o cliente com simpatia, NÃO encerre a conversa, e pergunte se ele gostaria de adicionar mais alguém na reserva."

        if qtd_dias_float < min_dias_real:
            logging.warning(f"[TRAVA] Reserva recusada (ID {barbearia_id}): dias ({qtd_dias_float}) abaixo do mínimo exigido ({min_dias_real})")
            return f"❌ REGRA: A pousada exige um mínimo de {min_dias_real:g} diárias. Avise o cliente com simpatia, NÃO encerre a conversa, e pergunte se ele gostaria de estender a estadia."
            
        # 1. Define Horários Padrão de Entrada (Sempre 12h)
        dt_entrada = datetime.strptime(data_entrada_str, '%Y-%m-%d').replace(hour=12, minute=0, second=0)
        
        # 🌟 LÓGICA DE LATE CHECKOUT (1.5 DIÁRIAS) 🌟
        if qtd_dias_float == 1.5:
            dt_saida = dt_entrada + timedelta(days=1)
            dt_saida = dt_saida.replace(hour=22, minute=0, second=0) # Late Checkout às 22h do dia seguinte
        else:
            dt_saida = dt_entrada + timedelta(days=int(qtd_dias_float))
            dt_saida = dt_saida.replace(hour=16, minute=0, second=0) # Check-out normal às 16h

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
        logging.error(f"Erro na disponibilidade hotel: {e}\n{traceback.format_exc()}")
        return "Erro ao processar as datas. Verifique se o formato está correto."

def realizar_reserva_quarto(barbearia_id: int, nome_cliente: str, telefone: str, quarto_nome: str, data_entrada_str: str, qtd_dias: float, qtd_pessoas: float) -> str:
    """
    Cria a reserva no banco com a duração correta em minutos.
    O parâmetro telefone é preenchido automaticamente pelo sistema.
    """
    try:
        qtd_dias_float = float(qtd_dias)
        qtd_pessoas_int = int(float(qtd_pessoas))

        # 🚨 1. TRAVA DE REGRA DE NEGÓCIO (MÍNIMO DE DIAS E PESSOAS) 🚨
        barbearia = Barbearia.query.get(barbearia_id)
        
        if barbearia_id == 8:
             min_dias_real = getattr(barbearia, 'min_dias_reserva', 1.5)
             min_pessoas_real = getattr(barbearia, 'min_pessoas_reserva', 2)
             
             if qtd_dias_float < min_dias_real:
                  return f"A Pousada Recanto da Maré exige um mínimo de {min_dias_real:g} diárias. Por favor, ajuste o período para prosseguir."
             if qtd_pessoas_int < min_pessoas_real:
                  return f"A Pousada Recanto da Maré exige um mínimo de {min_pessoas_real} pessoas. Por favor, ajuste a quantidade para prosseguir."
        else:
             min_dias_real = getattr(barbearia, 'min_dias_reserva', 1.0)
             if qtd_dias_float < min_dias_real:
                 return f"A Pousada exige um mínimo de {min_dias_real:g} diárias. Por favor, informe um período maior para prosseguir."

        # 2. Busca o Quarto (Pelo nome e ID da loja)
        quarto = Profissional.query.filter_by(barbearia_id=barbearia_id, nome=quarto_nome).first()
        if not quarto:
            return "Erro: Quarto não encontrado no sistema. Por favor, escolha um da lista disponível."

        # 3. Define datas
        dt_entrada = datetime.strptime(data_entrada_str, '%Y-%m-%d').replace(hour=12, minute=0)
        
        # 4. Define Duração Total em Minutos para bloquear a agenda no painel
        # Ex: 1.5 dias * 1440 = 2160 minutos de bloqueio
        duracao_total_minutos = int(qtd_dias_float * 1440)
        
        # Formata os dias bonitinho (ex: 1.5 ao invés de 1.500)
        dias_formatado = f"{qtd_dias_float:g}"
        
        # 5. Busca ou Cria um Serviço ESPECÍFICO para essa duração
        nome_servico = f"Reserva ({dias_formatado} diárias - {qtd_pessoas_int} pess.)"
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
        
        return f"✅ Tudo certo! Pré-reserva confirmada no {quarto.nome} para o dia {data_entrada_str} ({dias_formatado} diárias para {qtd_pessoas_int} pessoas)!"

    except Exception as e:
        logging.error(f"Erro ao reservar: {e}\n{traceback.format_exc()}")
        return f"Desculpe, ocorreu um erro ao registrar a reserva no sistema."
