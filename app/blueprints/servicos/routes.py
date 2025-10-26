# app/blueprints/servicos/routes.py
import logging
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from app.models.tables import Servico # Importa o modelo Servico
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
        return redirect(url_for('auth.login')) # Redireciona para o login (assumindo que login está em 'auth')
        # Se seu login ainda estiver no 'main', use 'main.login'
        
    barbearia_id_logada = current_user.barbearia_id
    
    try:
        # Busca no banco APENAS os serviços pertencentes a esta barbearia
        lista_servicos = Servico.query.filter_by(barbearia_id=barbearia_id_logada).order_by(Servico.nome).all()
    except Exception as e:
        # Loga o erro caso a consulta falhe
        current_app.logger.error(f"Erro ao buscar serviços para barbearia {barbearia_id_logada}: {e}", exc_info=True)
        flash('Ocorreu um erro ao carregar os serviços.', 'danger')
        lista_servicos = [] # Retorna lista vazia em caso de erro

    # Passa a lista de serviços para o template
    return render_template('servicos.html', servicos=lista_servicos)

@bp.route('/novo', methods=['GET', 'POST'])
@login_required
def novo_servico():
    """Exibe o formulário para adicionar um novo serviço (GET) 
       e processa a criação do serviço (POST)."""
       
    # Validação do usuário e barbearia
    if not hasattr(current_user, 'barbearia_id') or not current_user.barbearia_id:
        flash('Erro: Usuário inválido ou não associado a uma barbearia.', 'danger')
        # Ajuste 'auth.login' se seu blueprint de login tiver outro nome
        return redirect(url_for('auth.login')) 
        
    barbearia_id_logada = current_user.barbearia_id

    if request.method == 'POST':
        # Obter dados do formulário
        nome = request.form.get('nome')
        duracao_str = request.form.get('duracao')
        preco_str = request.form.get('preco')

        # Validação simples (pode ser melhorada com WTForms no futuro)
        erros = []
        if not nome:
            erros.append("O nome do serviço é obrigatório.")
        if not duracao_str or not duracao_str.isdigit() or int(duracao_str) <= 0:
            erros.append("A duração deve ser um número inteiro positivo (em minutos).")
        if not preco_str:
            erros.append("O preço é obrigatório.")
        else:
            try:
                # Tenta converter o preço para float, tratando vírgula como ponto decimal
                preco = float(preco_str.replace(',', '.'))
                if preco < 0:
                     erros.append("O preço não pode ser negativo.")
            except ValueError:
                erros.append("O preço deve ser um número válido (ex: 40.00 ou 40,00).")

        if erros:
            # Se houver erros, exibe-os e re-renderiza o formulário com os dados inseridos
            for erro in erros:
                flash(erro, 'danger')
            # Passa os dados de volta para preencher o formulário novamente
            return render_template('novo_servico.html', form_data=request.form)
        else:
            # Se não houver erros, cria o novo serviço
            try:
                novo = Servico(
                    nome=nome,
                    duracao=int(duracao_str),
                    preco=preco,
                    barbearia_id=barbearia_id_logada # Associa à barbearia correta
                )
                db.session.add(novo)
                db.session.commit()
                flash(f'Serviço "{nome}" adicionado com sucesso!', 'success')
                # Redireciona de volta para a lista de serviços
                return redirect(url_for('servicos.index')) 
            except Exception as e:
                db.session.rollback()
                flash(f'Erro ao adicionar serviço: {str(e)}', 'danger')
                current_app.logger.error(f"Erro ao adicionar serviço: {e}", exc_info=True)
                # Re-renderiza o formulário em caso de erro no banco
                return render_template('novo_servico.html', form_data=request.form)

    # Se for método GET, apenas exibe o formulário vazio
    return render_template('novo_servico.html', form_data={}) # Passa form_data vazio

# ... (Rotas Editar/Apagar futuras) ...
from app.models.tables import Servico
from app.extensions import db
from flask_login import login_required, current_user
# Importa 'abort' se ainda não estiver importado
from flask import abort 

# ... (blueprint 'bp', rota 'index', rota 'novo_servico') ...

# --- ROTA PARA EDITAR UM SERVIÇO EXISTENTE ---
@bp.route('/editar/<int:servico_id>', methods=['GET', 'POST'])
@login_required
def editar_servico(servico_id):
    """Exibe o formulário para editar um serviço (GET) 
       e processa a atualização do serviço (POST)."""

    # Validação do usuário e barbearia
    if not hasattr(current_user, 'barbearia_id') or not current_user.barbearia_id:
        flash('Erro: Usuário inválido ou não associado a uma barbearia.', 'danger')
        return redirect(url_for('auth.login')) # Ajuste se necessário

    barbearia_id_logada = current_user.barbearia_id

    # Busca o serviço específico E garante que pertence à barbearia logada
    servico = Servico.query.filter_by(id=servico_id, barbearia_id=barbearia_id_logada).first()

    # Se o serviço não for encontrado ou não pertencer à barbearia, retorna 404
    if not servico:
        abort(404, description="Serviço não encontrado ou não pertence à sua barbearia.")

    if request.method == 'POST':
        # Obter dados do formulário
        nome = request.form.get('nome')
        duracao_str = request.form.get('duracao')
        preco_str = request.form.get('preco')

        # Validação (igual à da rota 'novo_servico')
        erros = []
        if not nome:
            erros.append("O nome do serviço é obrigatório.")
        if not duracao_str or not duracao_str.isdigit() or int(duracao_str) <= 0:
            erros.append("A duração deve ser um número inteiro positivo (em minutos).")
        if not preco_str:
            erros.append("O preço é obrigatório.")
        else:
            try:
                preco = float(preco_str.replace(',', '.'))
                if preco < 0:
                     erros.append("O preço não pode ser negativo.")
            except ValueError:
                erros.append("O preço deve ser um número válido (ex: 40.00 ou 40,00).")

        if erros:
            for erro in erros:
                flash(erro, 'danger')
            # Re-renderiza o formulário de EDIÇÃO com os dados (errados) inseridos
            # Passamos o 'servico' original também para manter o ID na URL
            return render_template('editar_servico.html', servico=servico, form_data=request.form)
        else:
            # Se não houver erros, ATUALIZA o serviço existente
            try:
                servico.nome = nome
                servico.duracao = int(duracao_str)
                servico.preco = preco
                # O barbearia_id não muda
                
                db.session.commit() # Salva as alterações no banco
                flash(f'Serviço "{nome}" atualizado com sucesso!', 'success')
                return redirect(url_for('servicos.index')) 
            except Exception as e:
                db.session.rollback()
                flash(f'Erro ao atualizar serviço: {str(e)}', 'danger')
                current_app.logger.error(f"Erro ao atualizar serviço ID {servico_id}: {e}", exc_info=True)
                # Re-renderiza o formulário de EDIÇÃO em caso de erro no banco
                return render_template('editar_servico.html', servico=servico, form_data=request.form)

    # Se for método GET, exibe o formulário preenchido com os dados do serviço
    # Passamos os dados do 'servico' para a variável 'form_data' do template
    form_data_preenchido = {
        'nome': servico.nome,
        'duracao': servico.duracao,
        'preco': f"{servico.preco:.2f}".replace('.', ',') # Formata com vírgula para o input
    }
    return render_template('editar_servico.html', servico=servico, form_data=form_data_preenchido)

# ... (Rota Apagar futura) ...

@bp.route('/apagar/<int:servico_id>', methods=['POST']) # Aceita apenas POST
@login_required
def apagar_servico(servico_id):
    """Apaga um serviço existente."""

    # Validação do usuário e barbearia
    if not hasattr(current_user, 'barbearia_id') or not current_user.barbearia_id:
        flash('Erro: Usuário inválido ou não associado a uma barbearia.', 'danger')
        return redirect(url_for('auth.login')) # Ajuste se necessário
        
    barbearia_id_logada = current_user.barbearia_id

    # Busca o serviço específico E garante que pertence à barbearia logada
    servico = Servico.query.filter_by(id=servico_id, barbearia_id=barbearia_id_logada).first()

    if servico:
        try:
            nome_servico_apagado = servico.nome # Guarda o nome para a mensagem flash
            db.session.delete(servico)
            db.session.commit()
            flash(f'Serviço "{nome_servico_apagado}" apagado com sucesso!', 'warning')
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao apagar serviço: {str(e)}', 'danger')
            current_app.logger.error(f"Erro ao apagar serviço ID {servico_id}: {e}", exc_info=True)
    else:
        # Se o serviço não existe ou não pertence à barbearia, informa o usuário
        flash('Serviço não encontrado ou não pertence à sua barbearia.', 'danger')
        # Pode também usar abort(404) aqui se preferir

    # Redireciona sempre de volta para a lista de serviços
    return redirect(url_for('servicos.index'))
