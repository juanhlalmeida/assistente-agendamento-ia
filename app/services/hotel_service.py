from datetime import datetime, timedelta
from app.models.tables import Agendamento, Profissional, Servico, Barbearia
from app.extensions import db
import logging
import traceback

def verificar_disponibilidade_hotel(barbearia_id: int, data_entrada_str: str, qtd_dias: float, qtd_pessoas: float) -> str:
    """
    Verifica disponibilidade real de hotelaria (Colisão de Datas) com as regras exatas de horários da dona.
    """
    try:
        qtd_dias_float = float(qtd_dias)
        qtd_pessoas_int = int(float(qtd_pessoas))

        barbearia = Barbearia.query.get(barbearia_id)
        if not barbearia:
            return "Erro interno: Estabelecimento não encontrado."

        if barbearia_id == 8:
            min_pessoas_real = getattr(barbearia, 'min_pessoas_reserva', 2)
            min_dias_real = getattr(barbearia, 'min_dias_reserva', 1.5) 
        else:
            min_pessoas_real = getattr(barbearia, 'min_pessoas_reserva', 1)
            min_dias_real = getattr(barbearia, 'min_dias_reserva', 1.0)

        # VALIDAÇÕES RÍGIDAS
        if qtd_pessoas_int < min_pessoas_real:
            logging.warning(f"[TRAVA] Reserva recusada (ID {barbearia_id}): pessoas ({qtd_pessoas_int}) abaixo do mínimo")
            return f"❌ REGRA: A pousada só aceita no mínimo {min_pessoas_real} pessoas. Avise o cliente com simpatia, NÃO encerre a conversa, e pergunte se ele gostaria de adicionar mais alguém."

        if qtd_dias_float < min_dias_real:
            logging.warning(f"[TRAVA] Reserva recusada (ID {barbearia_id}): dias ({qtd_dias_float}) abaixo do mínimo")
            return f"❌ REGRA: A pousada exige um mínimo de {min_dias_real:g} diárias. Avise o cliente com simpatia, NÃO encerre a conversa, e pergunte se ele gostaria de estender a estadia."
            
        # 🌟 LÓGICA DE HORÁRIOS EXATOS DA DONA 🌟
        if qtd_dias_float == 1.5:
            # 1.5 Diária: Sexta 10h até Sábado 17h
            dt_entrada = datetime.strptime(data_entrada_str, '%Y-%m-%d').replace(hour=10, minute=0, second=0)
            dt_saida = dt_entrada + timedelta(days=1)
            dt_saida = dt_saida.replace(hour=17, minute=0, second=0)
        elif qtd_dias_float == 2.0:
            # 2 Diárias: Sexta 12h até Domingo 17h
            dt_entrada = datetime.strptime(data_entrada_str, '%Y-%m-%d').replace(hour=12, minute=0, second=0)
            dt_saida = dt_entrada + timedelta(days=2)
            dt_saida = dt_saida.replace(hour=17, minute=0, second=0)
        else:
            # 1 Diária (ou padrão): Sexta 12h até Sábado 14h
            dt_entrada = datetime.strptime(data_entrada_str, '%Y-%m-%d').replace(hour=12, minute=0, second=0)
            dt_saida = dt_entrada + timedelta(days=int(qtd_dias_float))
            dt_saida = dt_saida.replace(hour=14, minute=0, second=0) 

        quartos_candidatos = Profissional.query.filter(
            Profissional.barbearia_id == barbearia_id,
            Profissional.tipo == 'quarto',
            Profissional.capacidade >= qtd_pessoas_int
        ).all()
        
        disponiveis = []

        for quarto in quartos_candidatos:
            agendamentos = Agendamento.query.filter(
                Agendamento.profissional_id == quarto.id,
                Agendamento.data_hora >= datetime.now().replace(hour=0, minute=0)
            ).all()
            
            ocupado = False
            for ag in agendamentos:
                ag_inicio = ag.data_hora
                duracao = ag.servico.duracao if ag.servico else 1440
                ag_fim = ag_inicio + timedelta(minutes=duracao)
                
                # Teste de colisão
                if dt_entrada < ag_fim and dt_saida > ag_inicio:
                    ocupado = True
                    break  
            
            if not ocupado:
                disponiveis.append(quarto.nome)

        if not disponiveis:
            return f"Infelizmente não temos nenhuma acomodação disponível para {qtd_pessoas_int} pessoas nestas datas."

        # 🌟 MAGIA DA IA: Procurar o Pacote exato para dar o preço ao cliente 🌟
        minutos_buscados = int(qtd_dias_float * 1440)
        pacote = Servico.query.filter_by(barbearia_id=barbearia_id, duracao=minutos_buscados).first()
        
        info_pacote = ""
        if pacote:
            info_pacote = f" 💰 O pacote para este período é o '{pacote.nome}' no valor total de R$ {pacote.preco:.2f}. Informe O VALOR TOTAL ao cliente e pergunte se quer fazer a pré-reserva."
        else:
            info_pacote = " ⚠️ Informe que temos acomodação e diga que a receção confirmará o valor final, mas pergunte se quer garantir a pré-reserva."

        quarto_para_reserva = disponiveis[0]

        # MÁGICA: Instrução oculta para a IA esconder o número do quarto
        return (f"✅ Vaga Encontrada! [INSTRUÇÃO INTERNA DA IA: Para concluir a reserva, use o quarto '{quarto_para_reserva}' na ferramenta]. "
                f"🚨 REGRA OBRIGATÓRIA DA POUSADA: NUNCA diga o nome ou número do quarto (ex: Quarto 01) para o cliente! Diga apenas que tem disponibilidade "
                f"e descreva a estrutura se for necessário (ex: 'Quarto com beliche', 'Suíte com ar', etc).{info_pacote}")

    except Exception as e:
        logging.error(f"Erro na disponibilidade hotel: {e}\n{traceback.format_exc()}")
        return "Erro ao processar as datas. Verifique se o formato está correto."


def realizar_reserva_quarto(barbearia_id: int, nome_cliente: str, telefone: str, quarto_nome: str, data_entrada_str: str, qtd_dias: float, qtd_pessoas: float) -> str:
    """
    Cria a reserva no banco de dados e amarra ao pacote/tarifa real do financeiro.
    """
    try:
        qtd_dias_float = float(qtd_dias)
        qtd_pessoas_int = int(float(qtd_pessoas))

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

        quarto = Profissional.query.filter_by(barbearia_id=barbearia_id, nome=quarto_nome).first()
        if not quarto:
            return "Erro: Quarto não encontrado no sistema. Por favor, escolha um da lista disponível."

        # 3. Define datas de entrada baseadas na regra da dona
        if qtd_dias_float == 1.5:
            dt_entrada = datetime.strptime(data_entrada_str, '%Y-%m-%d').replace(hour=10, minute=0)
        else:
            dt_entrada = datetime.strptime(data_entrada_str, '%Y-%m-%d').replace(hour=12, minute=0)
        
        duracao_total_minutos = int(qtd_dias_float * 1440)
        dias_formatado = f"{qtd_dias_float:g}"
        
        # 🌟 O SEGREDO DO FINANCEIRO: Procura o pacote real criado pela dona (PRESERVADO!) 🌟
        servico = Servico.query.filter_by(barbearia_id=barbearia_id, duracao=duracao_total_minutos).first()
        
        if not servico:
            # Fallback de Segurança
            nome_servico_generico = f"Reserva Personalizada ({dias_formatado} diárias)"
            servico = Servico.query.filter_by(barbearia_id=barbearia_id, nome=nome_servico_generico).first()
            
            if not servico:
                servico = Servico(nome=nome_servico_generico, preco=0.0, duracao=duracao_total_minutos, barbearia_id=barbearia_id)
                db.session.add(servico)
                db.session.commit()

        # Adicionar a quantidade de pessoas ao nome do cliente para a dona ver rápido no calendário
        nome_cliente_formatado = f"{nome_cliente} ({qtd_pessoas_int} pess.)"

        nova_reserva = Agendamento(
            nome_cliente=nome_cliente_formatado,
            telefone_cliente=telefone,
            data_hora=dt_entrada,
            profissional_id=quarto.id,
            servico_id=servico.id,
            barbearia_id=barbearia_id
        )

        db.session.add(nova_reserva)
        db.session.commit()
        
        return f"✅ Tudo certo! Pré-reserva confirmada para o dia {data_entrada_str} ({dias_formatado} diárias para {qtd_pessoas_int} pessoas). O pacote vinculado foi: {servico.nome}."

    except Exception as e:
        logging.error(f"Erro ao reservar: {e}\n{traceback.format_exc()}")
        return f"Desculpe, ocorreu um erro ao registrar a reserva no sistema."