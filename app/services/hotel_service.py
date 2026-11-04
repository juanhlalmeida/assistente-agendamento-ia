from datetime import datetime, timedelta
from sqlalchemy.orm import joinedload
from app.models.tables import Agendamento, Profissional, Servico, Barbearia
from app.extensions import db
import logging
import traceback


def calcular_janela_estadia(data_entrada_str: str, qtd_dias_float: float) -> tuple[datetime, datetime]:
    """
    Calcula os horários exatos de Check-in e Check-out segundo a regra de negócio da pousada.
    """
    if qtd_dias_float == 1.5:
        # 1.5 Diária: Entrada 10h até dia seguinte 17h
        dt_entrada = datetime.strptime(data_entrada_str, '%Y-%m-%d').replace(hour=10, minute=0, second=0)
        dt_saida = (dt_entrada + timedelta(days=1)).replace(hour=17, minute=0, second=0)
    elif qtd_dias_float == 2.0:
        # 2 Diárias: Entrada 12h até +2 dias 17h
        dt_entrada = datetime.strptime(data_entrada_str, '%Y-%m-%d').replace(hour=12, minute=0, second=0)
        dt_saida = (dt_entrada + timedelta(days=2)).replace(hour=17, minute=0, second=0)
    else:
        # 1 Diária (ou padrão): Entrada 12h até +N dias 14h (ou proporcional para Day Use < 1 dia)
        dt_entrada = datetime.strptime(data_entrada_str, '%Y-%m-%d').replace(hour=12, minute=0, second=0)
        if qtd_dias_float < 1.0:
            dt_saida = dt_entrada + timedelta(minutes=int(qtd_dias_float * 1440))
        else:
            dt_saida = (dt_entrada + timedelta(days=int(qtd_dias_float))).replace(hour=14, minute=0, second=0)
    return dt_entrada, dt_saida


def verificar_colisao_quarto(
    barbearia_id: int,
    quarto_id: int,
    dt_entrada: datetime,
    dt_saida: datetime,
    ignorar_agendamento_id: int | None = None
) -> tuple[bool, Agendamento | None]:
    """
    Verifica de forma atômica e otimizada se há sobreposição de datas (Overbooking)
    para a acomodação informada no intervalo [dt_entrada, dt_saida).
    Busca reservas iniciadas até 15 dias antes para capturar estadias longas em andamento.
    """
    janela_busca_inicio = dt_entrada - timedelta(days=15)
    query = (
        Agendamento.query
        .options(joinedload(Agendamento.servico))
        .filter(
            Agendamento.barbearia_id == barbearia_id,
            Agendamento.profissional_id == quarto_id,
            Agendamento.data_hora >= janela_busca_inicio,
            Agendamento.data_hora < dt_saida
        )
    )
    if ignorar_agendamento_id is not None:
        query = query.filter(Agendamento.id != ignorar_agendamento_id)

    reservas_existentes = query.all()
    for ag in reservas_existentes:
        ag_inicio = ag.data_hora
        duracao = ag.servico.duracao if ag.servico and ag.servico.duracao else 1440
        ag_fim = ag_inicio + timedelta(minutes=duracao)
        if dt_entrada < ag_fim and dt_saida > ag_inicio:
            return True, ag

    return False, None


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
        dt_entrada, dt_saida = calcular_janela_estadia(data_entrada_str, qtd_dias_float)

        quartos_candidatos = Profissional.query.filter(
            Profissional.barbearia_id == barbearia_id,
            Profissional.tipo == 'quarto',
            Profissional.capacidade >= qtd_pessoas_int
        ).order_by(Profissional.capacidade.asc(), Profissional.id.asc()).all()

        if not quartos_candidatos:
            return f"Infelizmente não temos nenhuma acomodação disponível para {qtd_pessoas_int} pessoas nestas datas."

        # Consulta única otimizada (Zero N+1) para todas as acomodações candidatas
        ids_quartos = [q.id for q in quartos_candidatos]
        janela_busca_inicio = dt_entrada - timedelta(days=15)
        agendamentos_periodo = (
            Agendamento.query
            .options(joinedload(Agendamento.servico))
            .filter(
                Agendamento.barbearia_id == barbearia_id,
                Agendamento.profissional_id.in_(ids_quartos),
                Agendamento.data_hora >= janela_busca_inicio,
                Agendamento.data_hora < dt_saida
            )
            .all()
        )

        reservas_por_quarto: dict[int, list[Agendamento]] = {}
        for ag in agendamentos_periodo:
            reservas_por_quarto.setdefault(ag.profissional_id, []).append(ag)
        
        disponiveis = []

        for quarto in quartos_candidatos:
            agendamentos = reservas_por_quarto.get(quarto.id, [])
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
    Inclui trava atômica anti-overbooking.
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

        # 3. Define datas de entrada e saída baseadas na regra da dona
        dt_entrada, dt_saida_janela = calcular_janela_estadia(data_entrada_str, qtd_dias_float)
        duracao_total_minutos = int(qtd_dias_float * 1440)
        dt_saida_efetiva = max(dt_saida_janela, dt_entrada + timedelta(minutes=duracao_total_minutos))
        dias_formatado = f"{qtd_dias_float:g}"

        # 🛡️ TRAVA ATÔMICA ANTI-OVERBOOKING NA CRIAÇÃO DA RESERVA PELA IA
        em_conflito, _ = verificar_colisao_quarto(barbearia_id, quarto.id, dt_entrada, dt_saida_efetiva)
        if em_conflito:
            logging.warning(f"🚨 [ANTI-OVERBOOKING] Quarto '{quarto.nome}' já ocupado em {data_entrada_str}. Buscando quarto equivalente livre...")
            quartos_alternativos = Profissional.query.filter(
                Profissional.barbearia_id == barbearia_id,
                Profissional.tipo == 'quarto',
                Profissional.capacidade >= qtd_pessoas_int,
                Profissional.id != quarto.id
            ).order_by(Profissional.capacidade.asc(), Profissional.id.asc()).all()

            quarto_substituto = None
            for q_alt in quartos_alternativos:
                conflito_alt, _ = verificar_colisao_quarto(barbearia_id, q_alt.id, dt_entrada, dt_saida_efetiva)
                if not conflito_alt:
                    quarto_substituto = q_alt
                    break

            if quarto_substituto:
                logging.info(f"✅ [ANTI-OVERBOOKING] Realocado automaticamente de '{quarto.nome}' para '{quarto_substituto.nome}'.")
                quarto = quarto_substituto
            else:
                logging.error(f"❌ [ANTI-OVERBOOKING] Reserva bloqueada para {nome_cliente} em {data_entrada_str}: todas as acomodações ocupadas.")
                return (
                    "❌ Indisponibilidade de última hora: A acomodação para este período acabou de ser preenchida e não temos outro quarto "
                    f"disponível para {qtd_pessoas_int} pessoas nessas datas. Avise o cliente com educação e pergunte se deseja consultar outra data."
                )
        
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
        db.session.rollback()
        logging.error(f"Erro ao reservar: {e}\n{traceback.format_exc()}")
        return f"Desculpe, ocorreu um erro ao registrar a reserva no sistema."