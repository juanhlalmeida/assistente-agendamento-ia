# app/blueprints/servicos/routes.py
import logging
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, abort, jsonify
from sqlalchemy import func
from app.models.tables import Servico, Agendamento
from app.extensions import db
from flask_login import login_required, current_user # Para proteger a rota e filtrar

# Cria o Blueprint chamado 'servicos' com prefixo de URL
bp = Blueprint('servicos', __name__, url_prefix='/servicos')

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

@bp.route('/') # Esta é a rota raiz DO BLUEPRINT, ou seja, /servicos/
@login_required # Garante que apenas usuários logados acessem
def index():
    """Exibe a lista de serviços da barbearia logada."""
    
    # Validação do usuário e barbearia (importante manter)
    if not hasattr(current_user, 'barbearia_id') or not current_user.barbearia_id:
        flash('Erro: Usuário inválido ou não associado a uma barbearia.', 'danger')
        return redirect(url_for('main.login'))
        
    barbearia_id_logada = current_user.barbearia_id
    uso_por_servico = {}
    
    try:
        # Busca no banco APENAS os serviços pertencentes a esta barbearia
        lista_servicos = Servico.query.filter_by(barbearia_id=barbearia_id_logada).order_by(Servico.duracao.asc(), Servico.nome.asc()).all()

        # Consulta única agrupada (Zero N+1) para saber quantos agendamentos/reservas usam cada pacote
        contagens = (
            db.session.query(Agendamento.servico_id, func.count(Agendamento.id))
            .filter(Agendamento.barbearia_id == barbearia_id_logada)
            .group_by(Agendamento.servico_id)
            .all()
        )
        uso_por_servico = {srv_id: int(qtd) for srv_id, qtd in contagens if srv_id is not None}
    except Exception as e:
        # Loga o erro caso a consulta falhe
        current_app.logger.error(f"Erro ao buscar serviços para barbearia {barbearia_id_logada}: {e}", exc_info=True)
        flash('Ocorreu um erro ao carregar os serviços.', 'danger')
        lista_servicos = [] # Retorna lista vazia em caso de erro

    # Passa a lista de serviços para o template
    return render_template('servicos.html', servicos=lista_servicos, uso_por_servico=uso_por_servico)

@bp.route('/novo', methods=['GET', 'POST'])
@login_required
def novo_servico():
    """Exibe o formulário para adicionar um novo serviço (GET) 
       e processa a criação do serviço (POST)."""
       
    # Validação do usuário e barbearia
    if not hasattr(current_user, 'barbearia_id') or not current_user.barbearia_id:
        flash('Erro: Usuário inválido ou não associado a uma barbearia.', 'danger')
        return redirect(url_for('main.login')) 
        
    barbearia_id_logada = current_user.barbearia_id

    if request.method == 'POST':
        # Obter dados do formulário
        nome = (request.form.get('nome') or '').strip()
        duracao_str = (request.form.get('duracao') or '').strip()
        preco_str = (request.form.get('preco') or '').strip()

        # Validação simples
        erros = []
        if not nome:
            erros.append("O nome do pacote/serviço é obrigatório.")
        if not duracao_str or not duracao_str.isdigit() or int(duracao_str) <= 0:
            erros.append("A duração deve ser um número inteiro positivo (em minutos).")
        if not preco_str:
            erros.append("O preço é obrigatório.")
        else:
            try:
                # Tenta converter o preço para float, tratando vírgula como ponto decimal e pontos de milhar
                preco_normalizado = preco_str.replace('R$', '').strip()
                if ',' in preco_normalizado and '.' in preco_normalizado:
                    preco_normalizado = preco_normalizado.replace('.', '').replace(',', '.')
                else:
                    preco_normalizado = preco_normalizado.replace(',', '.')
                preco = float(preco_normalizado)
                if preco < 0:
                     erros.append("O preço não pode ser negativo.")
            except ValueError:
                erros.append("O preço deve ser um número válido (ex: 450,00).")

        if erros:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({"success": False, "error": " ".join(erros)}), 400
            for erro in erros:
                flash(erro, 'danger')
            return render_template('novo_servico.html', form_data=request.form)
        else:
            try:
                novo = Servico(
                    nome=nome,
                    duracao=int(duracao_str),
                    preco=preco,
                    barbearia_id=barbearia_id_logada
                )
                db.session.add(novo)
                db.session.commit()
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify({"success": True, "message": f'"{nome}" adicionado com sucesso!'}), 200
                flash(f'"{nome}" adicionado com sucesso!', 'success')
                return redirect(url_for('servicos.index')) 
            except Exception as e:
                db.session.rollback()
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify({"success": False, "error": str(e)}), 500
                flash(f'Erro ao adicionar serviço: {str(e)}', 'danger')
                current_app.logger.error(f"Erro ao adicionar serviço: {e}", exc_info=True)
                return render_template('novo_servico.html', form_data=request.form)

    # Se for método GET, apenas exibe o formulário vazio
    return render_template('novo_servico.html', form_data={})

# --- ROTA PARA EDITAR UM SERVIÇO EXISTENTE ---
@bp.route('/editar/<int:servico_id>', methods=['GET', 'POST'])
@login_required
def editar_servico(servico_id):
    """Exibe o formulário para editar um serviço (GET) 
       e processa a atualização do serviço (POST)."""

    # Validação do usuário e barbearia
    if not hasattr(current_user, 'barbearia_id') or not current_user.barbearia_id:
        flash('Erro: Usuário inválido ou não associado a uma barbearia.', 'danger')
        return redirect(url_for('main.login'))

    barbearia_id_logada = current_user.barbearia_id

    # Busca o serviço específico E garante que pertence à barbearia logada
    servico = Servico.query.filter_by(id=servico_id, barbearia_id=barbearia_id_logada).first()

    # Se o serviço não for encontrado ou não pertencer à barbearia, retorna 404
    if not servico:
        abort(404, description="Serviço não encontrado ou não pertence à sua barbearia.")

    if request.method == 'POST':
        nome = (request.form.get('nome') or '').strip()
        duracao_str = (request.form.get('duracao') or '').strip()
        preco_str = (request.form.get('preco') or '').strip()

        erros = []
        if not nome:
            erros.append("O nome do pacote/serviço é obrigatório.")
        if not duracao_str or not duracao_str.isdigit() or int(duracao_str) <= 0:
            erros.append("A duração deve ser um número inteiro positivo (em minutos).")
        if not preco_str:
            erros.append("O preço é obrigatório.")
        else:
            try:
                preco_normalizado = preco_str.replace('R$', '').strip()
                if ',' in preco_normalizado and '.' in preco_normalizado:
                    preco_normalizado = preco_normalizado.replace('.', '').replace(',', '.')
                else:
                    preco_normalizado = preco_normalizado.replace(',', '.')
                preco = float(preco_normalizado)
                if preco < 0:
                     erros.append("O preço não pode ser negativo.")
            except ValueError:
                erros.append("O preço deve ser um número válido (ex: 450,00).")

        if erros:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({"success": False, "error": " ".join(erros)}), 400
            for erro in erros:
                flash(erro, 'danger')
            return render_template('editar_servico.html', servico=servico, form_data=request.form)
        else:
            try:
                servico.nome = nome
                servico.duracao = int(duracao_str)
                servico.preco = preco
                
                db.session.commit()
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify({"success": True, "message": f'"{nome}" atualizado com sucesso!'}), 200
                flash(f'"{nome}" atualizado com sucesso!', 'success')
                return redirect(url_for('servicos.index')) 
            except Exception as e:
                db.session.rollback()
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify({"success": False, "error": str(e)}), 500
                flash(f'Erro ao atualizar serviço: {str(e)}', 'danger')
                current_app.logger.error(f"Erro ao atualizar serviço ID {servico_id}: {e}", exc_info=True)
                return render_template('editar_servico.html', servico=servico, form_data=request.form)

    form_data_preenchido = {
        'nome': servico.nome,
        'duracao': servico.duracao,
        'preco': f"{servico.preco:.2f}".replace('.', ',')
    }
    return render_template('editar_servico.html', servico=servico, form_data=form_data_preenchido)


@bp.route('/apagar/<int:servico_id>', methods=['POST']) 
@login_required
def apagar_servico(servico_id):
    """Apaga um serviço existente, APENAS se não houver agendamentos associados."""

    if not hasattr(current_user, 'barbearia_id') or not current_user.barbearia_id:
        flash('Erro: Usuário inválido ou não associado a uma barbearia.', 'danger')
        return redirect(url_for('main.login')) 
        
    barbearia_id_logada = current_user.barbearia_id

    servico = Servico.query.filter_by(id=servico_id, barbearia_id=barbearia_id_logada).first()

    if not servico:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({"success": False, "error": "Item não encontrado."}), 404
        flash('Serviço não encontrado ou não pertence à sua barbearia.', 'danger')
        return redirect(url_for('servicos.index'))

    # --- VERIFICAÇÃO DE DEPENDÊNCIA ---
    agendamentos_existentes = Agendamento.query.filter_by(
        servico_id=servico.id, 
        barbearia_id=barbearia_id_logada
    ).count()

    if agendamentos_existentes > 0:
        msg_dep = f'Não é possível remover "{servico.nome}", pois está vinculado a {agendamentos_existentes} reserva(s)/agendamento(s).'
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({"success": False, "error": msg_dep}), 409
        flash(f'Erro: {msg_dep}', 'danger')
        return redirect(url_for('servicos.index'))
        
    try:
        nome_servico_apagado = servico.nome 
        db.session.delete(servico)
        db.session.commit()
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({"success": True, "message": f'"{nome_servico_apagado}" removido com sucesso.'}), 200
        flash(f'"{nome_servico_apagado}" removido com sucesso!', 'warning')
    except Exception as e:
        db.session.rollback()
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({"success": False, "error": str(e)}), 500
        flash(f'Erro ao apagar serviço: {str(e)}', 'danger')
        current_app.logger.error(f"Erro ao apagar serviço ID {servico_id}: {e}", exc_info=True)

    return redirect(url_for('servicos.index'))
