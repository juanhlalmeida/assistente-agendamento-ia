# app/blueprints/dashboard/routes.py
import logging
from flask import Blueprint, render_template, redirect, url_for, flash, current_app, request, jsonify
from sqlalchemy import func, distinct
from app.models.tables import Agendamento, User, Servico, Barbearia  # type: ignore
from app.extensions import db
from flask_login import login_required, current_user
from datetime import datetime, date, time, timedelta
import pytz
import locale

# Cria o Blueprint 'dashboard' com prefixo /dashboard
bp = Blueprint('dashboard', __name__, url_prefix='/dashboard')

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

_PALAVRAS_TROCA = ('troca', 'permuta', 'parceria', 'cortesia')
_SERVICOS_TROCA_PADRAO = (
    ("Troca de Serviço - Colocação", 120, 0.0),
    ("Troca de Serviço - Manutenção", 90, 0.0),
)

_MESES_PT = {
    1: 'Janeiro', 2: 'Fevereiro', 3: 'Março', 4: 'Abril',
    5: 'Maio', 6: 'Junho', 7: 'Julho', 8: 'Agosto',
    9: 'Setembro', 10: 'Outubro', 11: 'Novembro', 12: 'Dezembro'
}


def _range_do_dia_utc(dia_dt: date):
    inicio = datetime.combine(dia_dt, time.min)
    fim = inicio + timedelta(days=1)
    return inicio, fim


def _range_do_mes_atual(dia_dt: date):
    inicio_mes = dia_dt.replace(day=1)
    if dia_dt.month == 12:
        prox_mes = date(dia_dt.year + 1, 1, 1)
    else:
        prox_mes = date(dia_dt.year, dia_dt.month + 1, 1)
    return datetime.combine(inicio_mes, time.min), datetime.combine(prox_mes, time.min), inicio_mes, prox_mes - timedelta(days=1)


def _eh_bloqueio(ag) -> bool:
    nome_cli = (getattr(ag, 'nome_cliente', '') or '').lower()
    nome_srv = (getattr(ag.servico, 'nome', '') or '').lower() if getattr(ag, 'servico', None) else ''
    return 'bloqueio' in nome_cli or 'bloqueio' in nome_srv or '⛔' in nome_cli


def _eh_troca_servico(ag) -> bool:
    if _eh_bloqueio(ag):
        return False
    nome_cli = (getattr(ag, 'nome_cliente', '') or '').lower()
    nome_srv = (getattr(ag.servico, 'nome', '') or '').lower() if getattr(ag, 'servico', None) else ''
    return any(p in nome_srv for p in _PALAVRAS_TROCA) or any(p in nome_cli for p in _PALAVRAS_TROCA)


def _eh_agendamento_pago(ag) -> bool:
    """
    Retorna True estritamente para atendimentos pagos reais:
    exclui Bloqueio Administrativo, Troca de Serviço/Permuta/Parceria/Cortesia e serviços R$ 0,00.
    """
    if _eh_bloqueio(ag) or _eh_troca_servico(ag):
        return False
    if not getattr(ag, 'servico', None) or getattr(ag.servico, 'preco', None) is None:
        return False
    try:
        return float(ag.servico.preco) > 0.0
    except (TypeError, ValueError):
        return False


def _eh_agendamento_valido(ag) -> bool:
    return not _eh_bloqueio(ag)


def _formatar_moeda_br(valor: float) -> str:
    return f"{float(valor or 0.0):,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')


def garantir_servicos_troca_studio(barbearia_id: int) -> None:
    """
    Rotina idempotente executada ao carregar o Dashboard/Agenda que garante a existência
    dos serviços de parceria ("Troca de Serviço - Colocação" 120m R$0,00 e
    "Troca de Serviço - Manutenção" 90m R$0,00) no Studio Lima Lash e demais clínicas/studios.
    """
    try:
        lojas_alvo = []
        if barbearia_id:
            loja_atual = Barbearia.query.get(barbearia_id)
            if loja_atual and getattr(loja_atual, 'business_type', '') != 'pousada':
                lojas_alvo.append(loja_atual)

        # Garante também no Studio Lima Lash caso exista no banco com outro ID
        lojas_lash = Barbearia.query.filter(
            Barbearia.nome_fantasia.ilike('%lash%')
        ).all()
        ids_vistos = {b.id for b in lojas_alvo}
        for l_lash in lojas_lash:
            if l_lash.id not in ids_vistos and getattr(l_lash, 'business_type', '') != 'pousada':
                lojas_alvo.append(l_lash)
                ids_vistos.add(l_lash.id)

        alterou = False
        for loja in lojas_alvo:
            for nome_padrao, duracao_padrao, preco_padrao in _SERVICOS_TROCA_PADRAO:
                srv = Servico.query.filter_by(barbearia_id=loja.id, nome=nome_padrao).first()
                if not srv:
                    srv = Servico(
                        nome=nome_padrao,
                        duracao=duracao_padrao,
                        preco=preco_padrao,
                        barbearia_id=loja.id
                    )
                    db.session.add(srv)
                    alterou = True
                else:
                    if srv.preco is None or float(srv.preco) != 0.0:
                        srv.preco = 0.0
                        alterou = True
                    if not srv.duracao:
                        srv.duracao = duracao_padrao
                        alterou = True

        if alterou:
            db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.warning(f"Aviso ao garantir serviços de troca no studio: {e}")


def _resolver_intervalo_filtro(hoje_local: date, periodo: str, data_inicio_str: str = "", data_fim_str: str = ""):
    periodo_norm = (periodo or 'este_mes').strip().lower()
    _, _, ini_mes_atual, fim_mes_atual = _range_do_mes_atual(hoje_local)

    if periodo_norm == 'hoje':
        dt_ini = hoje_local
        dt_fim = hoje_local
        label = f"Hoje ({hoje_local.strftime('%d/%m/%Y')})"
    elif periodo_norm == 'esta_semana':
        dt_ini = hoje_local - timedelta(days=hoje_local.weekday())
        dt_fim = dt_ini + timedelta(days=6)
        label = f"Esta Semana ({dt_ini.strftime('%d/%m')} a {dt_fim.strftime('%d/%m')})"
    elif periodo_norm == 'mes_passado':
        ultimo_mes_passado = ini_mes_atual - timedelta(days=1)
        dt_ini = ultimo_mes_passado.replace(day=1)
        dt_fim = ultimo_mes_passado
        nome_m = _MESES_PT.get(dt_ini.month, dt_ini.strftime('%m'))
        label = f"Mês Passado ({nome_m}/{dt_ini.year})"
    elif periodo_norm == 'personalizado':
        try:
            dt_ini = datetime.strptime(data_inicio_str.strip(), '%Y-%m-%d').date() if data_inicio_str else ini_mes_atual
        except ValueError:
            dt_ini = ini_mes_atual
        try:
            dt_fim = datetime.strptime(data_fim_str.strip(), '%Y-%m-%d').date() if data_fim_str else fim_mes_atual
        except ValueError:
            dt_fim = fim_mes_atual
        if dt_fim < dt_ini:
            dt_ini, dt_fim = dt_fim, dt_ini
        label = f"Período ({dt_ini.strftime('%d/%m/%Y')} a {dt_fim.strftime('%d/%m/%Y')})"
    else:
        periodo_norm = 'este_mes'
        dt_ini = ini_mes_atual
        dt_fim = fim_mes_atual
        nome_m = _MESES_PT.get(hoje_local.month, hoje_local.strftime('%m'))
        label = f"Este Mês ({nome_m}/{hoje_local.year})"

    inicio_db = datetime.combine(dt_ini, time.min)
    fim_db = datetime.combine(dt_fim + timedelta(days=1), time.min)
    return periodo_norm, dt_ini, dt_fim, inicio_db, fim_db, label


def _calcular_relatorio_financeiro(
    barbearia_id: int,
    hoje_local: date,
    periodo: str = 'este_mes',
    data_inicio_str: str = '',
    data_fim_str: str = '',
    servico_id_str: str = 'todos'
) -> dict:
    periodo_norm, dt_ini, dt_fim, inicio_db, fim_db, label_periodo = _resolver_intervalo_filtro(
        hoje_local, periodo, data_inicio_str, data_fim_str
    )

    query = (
        Agendamento.query.options(
            db.joinedload(Agendamento.servico),
            db.joinedload(Agendamento.profissional)
        )
        .filter(
            Agendamento.barbearia_id == barbearia_id,
            Agendamento.data_hora >= inicio_db,
            Agendamento.data_hora < fim_db
        )
    )

    servico_id_int = None
    if servico_id_str and str(servico_id_str).strip().lower() not in ('', 'todos', 'all'):
        try:
            servico_id_int = int(servico_id_str)
            query = query.filter(Agendamento.servico_id == servico_id_int)
        except ValueError:
            servico_id_int = None

    agendamentos_periodo = query.order_by(Agendamento.data_hora.asc()).all()

    pagos = []
    trocas = []
    bloqueios = []

    for ag in agendamentos_periodo:
        if _eh_bloqueio(ag):
            bloqueios.append(ag)
        elif _eh_troca_servico(ag):
            trocas.append(ag)
        elif _eh_agendamento_pago(ag):
            pagos.append(ag)

    receita_real = sum(float(ag.servico.preco) for ag in pagos)
    total_pagos = len(pagos)
    total_trocas = len(trocas)
    total_bloqueios = len(bloqueios)
    ticket_medio_real = (receita_real / total_pagos) if total_pagos > 0 else 0.0

    # Ranking de Serviços (apenas procedimentos pagos)
    mapa_ranking = {}
    for ag in pagos:
        srv_nome = ag.servico.nome if ag.servico else 'Procedimento'
        srv_id = ag.servico.id if ag.servico else 0
        preco_val = float(ag.servico.preco) if ag.servico else 0.0
        chave = (srv_id, srv_nome)
        if chave not in mapa_ranking:
            mapa_ranking[chave] = {
                'servico_id': srv_id,
                'nome': srv_nome,
                'qtd': 0,
                'receita': 0.0,
            }
        mapa_ranking[chave]['qtd'] += 1
        mapa_ranking[chave]['receita'] += preco_val

    ranking_servicos = sorted(
        mapa_ranking.values(),
        key=lambda item: (item['receita'], item['qtd']),
        reverse=True
    )

    for item in ranking_servicos:
        item['receita_fmt'] = _formatar_moeda_br(item['receita'])
        item['ticket_medio'] = (item['receita'] / item['qtd']) if item['qtd'] > 0 else 0.0
        item['ticket_medio_fmt'] = _formatar_moeda_br(item['ticket_medio'])
        item['percentual'] = round((item['receita'] / receita_real) * 100, 1) if receita_real > 0 else 0.0

    # Resumo detalhado de Trocas de Serviço realizadas no período (separado do caixa pago)
    mapa_trocas = {}
    for ag in trocas:
        srv_nome = ag.servico.nome if ag.servico else 'Troca de Serviço'
        mapa_trocas[srv_nome] = mapa_trocas.get(srv_nome, 0) + 1

    resumo_trocas = [
        {'nome': nome_t, 'qtd': qtd_t}
        for nome_t, qtd_t in sorted(mapa_trocas.items(), key=lambda x: x[1], reverse=True)
    ]

    return {
        'periodo': periodo_norm,
        'label_periodo': label_periodo,
        'data_inicio': dt_ini.strftime('%Y-%m-%d'),
        'data_fim': dt_fim.strftime('%Y-%m-%d'),
        'data_inicio_br': dt_ini.strftime('%d/%m/%Y'),
        'data_fim_br': dt_fim.strftime('%d/%m/%Y'),
        'servico_id': str(servico_id_int) if servico_id_int else 'todos',
        'receita_real': receita_real,
        'receita_real_fmt': _formatar_moeda_br(receita_real),
        'total_pagos': total_pagos,
        'total_trocas': total_trocas,
        'total_bloqueios': total_bloqueios,
        'ticket_medio_real': ticket_medio_real,
        'ticket_medio_real_fmt': _formatar_moeda_br(ticket_medio_real),
        'ranking_servicos': ranking_servicos,
        'resumo_trocas': resumo_trocas,
    }


@bp.route('/api/financeiro')
@login_required
def api_financeiro():
    """Endpoint JSON ágil para filtragem dinâmica do Controle Financeiro sem recarregar a página."""
    if not hasattr(current_user, 'barbearia_id') or not current_user.barbearia_id:
        return jsonify({'success': False, 'error': 'Barbearia não identificada.'}), 403

    sao_paulo_tz = pytz.timezone('America/Sao_Paulo')
    hoje_local = datetime.now(sao_paulo_tz).date()

    periodo = request.args.get('periodo', 'este_mes')
    data_inicio = request.args.get('data_inicio', '')
    data_fim = request.args.get('data_fim', '')
    servico_id = request.args.get('servico_id', 'todos')

    try:
        relatorio = _calcular_relatorio_financeiro(
            barbearia_id=current_user.barbearia_id,
            hoje_local=hoje_local,
            periodo=periodo,
            data_inicio_str=data_inicio,
            data_fim_str=data_fim,
            servico_id_str=servico_id
        )
        return jsonify({'success': True, **relatorio})
    except Exception as e:
        current_app.logger.error(f"Erro na API financeira: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Não foi possível calcular o relatório financeiro.'}), 500


def renderizar_pagina_financeiro():
    """Renderiza a página dedicada de Controle Financeiro & Relatórios (financeiro.html)."""
    if hasattr(current_user, 'role') and current_user.role == 'super_admin':
        return redirect(url_for('superadmin.listar_barbearias'))

    if not hasattr(current_user, 'barbearia_id') or not current_user.barbearia_id:
        flash('Erro: Usuário admin inválido ou não associado a uma barbearia.', 'danger')
        return redirect(url_for('main.login'))

    barbearia_id_logada = current_user.barbearia_id
    garantir_servicos_troca_studio(barbearia_id_logada)

    sao_paulo_tz = pytz.timezone('America/Sao_Paulo')
    hoje_local = datetime.now(sao_paulo_tz).date()
    nome_mes_atual = _MESES_PT.get(hoje_local.month, hoje_local.strftime('%B').capitalize())

    filtro_periodo = request.args.get('periodo', 'este_mes')
    filtro_data_inicio = request.args.get('data_inicio', '')
    filtro_data_fim = request.args.get('data_fim', '')
    filtro_servico_id = request.args.get('servico_id', 'todos')

    try:
        servicos_filtro = (
            Servico.query.filter(
                Servico.barbearia_id == barbearia_id_logada,
                Servico.nome != 'Bloqueio Administrativo'
            )
            .order_by(Servico.nome.asc())
            .all()
        )

        relatorio_financeiro = _calcular_relatorio_financeiro(
            barbearia_id=barbearia_id_logada,
            hoje_local=hoje_local,
            periodo=filtro_periodo,
            data_inicio_str=filtro_data_inicio,
            data_fim_str=filtro_data_fim,
            servico_id_str=filtro_servico_id
        )
    except Exception as e:
        current_app.logger.error(f"Erro ao carregar página financeiro para barbearia {barbearia_id_logada}: {e}", exc_info=True)
        flash('Ocorreu um erro ao carregar os relatórios financeiros.', 'danger')
        servicos_filtro = []
        relatorio_financeiro = {
            'periodo': 'este_mes',
            'label_periodo': f'Este Mês ({nome_mes_atual})',
            'data_inicio': hoje_local.replace(day=1).strftime('%Y-%m-%d'),
            'data_fim': hoje_local.strftime('%Y-%m-%d'),
            'data_inicio_br': hoje_local.replace(day=1).strftime('%d/%m/%Y'),
            'data_fim_br': hoje_local.strftime('%d/%m/%Y'),
            'servico_id': 'todos',
            'receita_real': 0.0,
            'receita_real_fmt': '0,00',
            'total_pagos': 0,
            'total_trocas': 0,
            'total_bloqueios': 0,
            'ticket_medio_real': 0.0,
            'ticket_medio_real_fmt': '0,00',
            'ranking_servicos': [],
            'resumo_trocas': [],
        }

    return render_template(
        'financeiro.html',
        servicos_filtro=servicos_filtro,
        relatorio_financeiro=relatorio_financeiro,
        nome_mes_atual=nome_mes_atual
    )


@bp.route('/financeiro')
@login_required
def financeiro():
    """Rota /dashboard/financeiro para a aba dedicada de Controle Financeiro."""
    return renderizar_pagina_financeiro()


@bp.route('/')
@login_required
def index():
    """Exibe o dashboard executivo da barbearia/studio para admins,
       ou redireciona Super Admins para o painel deles."""

    if hasattr(current_user, 'role') and current_user.role == 'super_admin':
        return redirect(url_for('superadmin.listar_barbearias'))

    if not hasattr(current_user, 'barbearia_id') or not current_user.barbearia_id:
        flash('Erro: Usuário admin inválido ou não associado a uma barbearia.', 'danger')
        return redirect(url_for('main.login'))

    barbearia_id_logada = current_user.barbearia_id

    # 0. Garante de forma idempotente os serviços de Troca de Serviço (Colocação 120m / Manutenção 90m)
    garantir_servicos_troca_studio(barbearia_id_logada)

    sao_paulo_tz = pytz.timezone('America/Sao_Paulo')
    hoje_local = datetime.now(sao_paulo_tz).date()

    inicio_hoje_db, fim_hoje_db = _range_do_dia_utc(hoje_local)

    # Intervalo da semana atual (Segunda-feira 00:00 até Domingo 23:59:59)
    inicio_semana_date = hoje_local - timedelta(days=hoje_local.weekday())
    fim_semana_date = inicio_semana_date + timedelta(days=7)
    inicio_semana_db = datetime.combine(inicio_semana_date, time.min)
    fim_semana_db = datetime.combine(fim_semana_date, time.min)

    # Intervalo do mês vigente (Dia 01 00:00 até último dia do mês 23:59:59)
    inicio_mes_db, fim_mes_db, _, _ = _range_do_mes_atual(hoje_local)
    nome_mes_atual = _MESES_PT.get(hoje_local.month, hoje_local.strftime('%B').capitalize())

    # Parâmetros opcionais do filtro financeiro (suporta GET direto e AJAX)
    filtro_periodo = request.args.get('periodo', 'este_mes')
    filtro_data_inicio = request.args.get('data_inicio', '')
    filtro_data_fim = request.args.get('data_fim', '')
    filtro_servico_id = request.args.get('servico_id', 'todos')

    try:
        # 1. Buscar agendamentos de hoje (com serviço e profissional carregados)
        proximos_agendamentos_db = (
            Agendamento.query.options(
                db.joinedload(Agendamento.servico),
                db.joinedload(Agendamento.profissional)
            )
            .filter(
                Agendamento.barbearia_id == barbearia_id_logada,
                Agendamento.data_hora >= inicio_hoje_db,
                Agendamento.data_hora < fim_hoje_db
            )
            .order_by(Agendamento.data_hora.asc())
            .all()
        )

        # 2. Buscar agendamentos da semana atual para KPIs executivos
        agendamentos_semana_db = (
            Agendamento.query.options(
                db.joinedload(Agendamento.servico)
            )
            .filter(
                Agendamento.barbearia_id == barbearia_id_logada,
                Agendamento.data_hora >= inicio_semana_db,
                Agendamento.data_hora < fim_semana_db
            )
            .all()
        )

        # 2.1 Buscar agendamentos do mês atual para o Card Mensal em destaque
        agendamentos_mes_db = (
            Agendamento.query.options(
                db.joinedload(Agendamento.servico)
            )
            .filter(
                Agendamento.barbearia_id == barbearia_id_logada,
                Agendamento.data_hora >= inicio_mes_db,
                Agendamento.data_hora < fim_mes_db
            )
            .all()
        )

        # 3. Calcular indicadores executivos (excluindo Bloqueios e Trocas de Serviço da Receita e dos Pagos)
        agendamentos_pagos_hoje = [ag for ag in proximos_agendamentos_db if _eh_agendamento_pago(ag)]
        agendamentos_pagos_semana = [ag for ag in agendamentos_semana_db if _eh_agendamento_pago(ag)]
        agendamentos_pagos_mes = [ag for ag in agendamentos_mes_db if _eh_agendamento_pago(ag)]

        trocas_hoje_count = sum(1 for ag in proximos_agendamentos_db if _eh_troca_servico(ag))
        trocas_semana_count = sum(1 for ag in agendamentos_semana_db if _eh_troca_servico(ag))
        trocas_mes_count = sum(1 for ag in agendamentos_mes_db if _eh_troca_servico(ag))

        agendamentos_hoje_count = len(agendamentos_pagos_hoje)
        agendamentos_semana_count = len(agendamentos_pagos_semana)
        agendamentos_mes_count = len(agendamentos_pagos_mes)

        receita_hoje_val = sum(float(ag.servico.preco) for ag in agendamentos_pagos_hoje)
        receita_semana_val = sum(float(ag.servico.preco) for ag in agendamentos_pagos_semana)
        receita_mes_val = sum(float(ag.servico.preco) for ag in agendamentos_pagos_mes)

        ticket_medio_mes_val = (receita_mes_val / agendamentos_mes_count) if agendamentos_mes_count > 0 else 0.0

        # 4. Contar Clientes Únicos (Total da Loja)
        total_clientes_count = (
            db.session.query(func.count(distinct(Agendamento.telefone_cliente)))
            .filter(
                Agendamento.barbearia_id == barbearia_id_logada,
                Agendamento.telefone_cliente != '00000000000'
            )
            .scalar()
            or 0
        )

        # 5. Formatar horários e flags visuais (Troca de Serviço vs Bloqueio vs Pago) para a timeline de hoje
        proximos_agendamentos_formatados = []
        for ag in proximos_agendamentos_db:
            hora_formatada = '--:--'
            if ag.data_hora:
                try:
                    hora_formatada = ag.data_hora.strftime('%H:%M')
                except Exception as fmt_e:
                    current_app.logger.warning(f"Erro ao formatar hora {ag.data_hora} para agendamento {ag.id}: {fmt_e}")
            ag.hora_formatada = hora_formatada
            ag.eh_bloqueio = _eh_bloqueio(ag)
            ag.eh_troca = _eh_troca_servico(ag)
            ag.eh_pago = _eh_agendamento_pago(ag)
            proximos_agendamentos_formatados.append(ag)

        # 6. Lista de serviços da loja para o seletor de filtro financeiro (excluindo Bloqueio Administrativo)
        servicos_filtro = (
            Servico.query.filter(
                Servico.barbearia_id == barbearia_id_logada,
                Servico.nome != 'Bloqueio Administrativo'
            )
            .order_by(Servico.nome.asc())
            .all()
        )

        # 7. Relatório Financeiro Completo com Filtros
        relatorio_financeiro = _calcular_relatorio_financeiro(
            barbearia_id=barbearia_id_logada,
            hoje_local=hoje_local,
            periodo=filtro_periodo,
            data_inicio_str=filtro_data_inicio,
            data_fim_str=filtro_data_fim,
            servico_id_str=filtro_servico_id
        )

        # 8. Formatar data atual para cabeçalho
        try:
            locale.setlocale(locale.LC_TIME, 'pt_BR.UTF-8')
        except locale.Error:
            try:
                locale.setlocale(locale.LC_TIME, 'Portuguese_Brazil.1252')
            except locale.Error:
                locale.setlocale(locale.LC_TIME, '')

        data_hoje_formatada = hoje_local.strftime('%A, %d de %B de %Y').capitalize()

    except Exception as e:
        current_app.logger.error(f"Erro ao buscar dados do dashboard para barbearia {barbearia_id_logada}: {e}", exc_info=True)
        flash('Ocorreu um erro ao carregar os dados do dashboard.', 'danger')
        agendamentos_hoje_count = 0
        agendamentos_semana_count = 0
        agendamentos_mes_count = 0
        trocas_hoje_count = 0
        trocas_semana_count = 0
        trocas_mes_count = 0
        receita_hoje_val = 0.0
        receita_semana_val = 0.0
        receita_mes_val = 0.0
        ticket_medio_mes_val = 0.0
        total_clientes_count = 0
        proximos_agendamentos_formatados = []
        servicos_filtro = []
        relatorio_financeiro = {
            'periodo': 'este_mes',
            'label_periodo': f'Este Mês ({nome_mes_atual})',
            'data_inicio': hoje_local.replace(day=1).strftime('%Y-%m-%d'),
            'data_fim': hoje_local.strftime('%Y-%m-%d'),
            'data_inicio_br': hoje_local.replace(day=1).strftime('%d/%m/%Y'),
            'data_fim_br': hoje_local.strftime('%d/%m/%Y'),
            'servico_id': 'todos',
            'receita_real': 0.0,
            'receita_real_fmt': '0,00',
            'total_pagos': 0,
            'total_trocas': 0,
            'total_bloqueios': 0,
            'ticket_medio_real': 0.0,
            'ticket_medio_real_fmt': '0,00',
            'ranking_servicos': [],
            'resumo_trocas': [],
        }
        data_hoje_formatada = hoje_local.strftime('%d/%m/%Y')

    return render_template(
        'dashboard.html',
        agendamentos_hoje=agendamentos_hoje_count,
        agendamentos_semana=agendamentos_semana_count,
        agendamentos_mes=agendamentos_mes_count,
        trocas_hoje=trocas_hoje_count,
        trocas_semana=trocas_semana_count,
        trocas_mes=trocas_mes_count,
        receita_hoje=receita_hoje_val,
        receita_semana=receita_semana_val,
        receita_mes=receita_mes_val,
        ticket_medio_mes=ticket_medio_mes_val,
        nome_mes_atual=nome_mes_atual,
        total_clientes=total_clientes_count,
        proximos_agendamentos=proximos_agendamentos_formatados,
        servicos_filtro=servicos_filtro,
        relatorio_financeiro=relatorio_financeiro,
        data_hoje=data_hoje_formatada
    )
