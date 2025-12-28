# app/blueprints/superadmin/routes.py
# (CÓDIGO COMPLETO: CORREÇÃO DE STATUS INATIVO E DEBUG)

import logging
from functools import wraps
from datetime import datetime, timedelta
from flask import Blueprint, render_template, redirect, url_for, flash, current_app, abort, request
from app.models.tables import Barbearia, User
from app.extensions import db
from flask_login import login_required, current_user 
from werkzeug.security import generate_password_hash

# Cria o Blueprint 'superadmin' com prefixo /superadmin
bp = Blueprint('superadmin', __name__, url_prefix='/superadmin')

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# --- DECORATOR PARA PROTEGER ROTAS SUPER ADMIN ---
def super_admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not hasattr(current_user, 'role') or current_user.role != 'super_admin':
            flash('Acesso não autorizado.', 'danger')
            return redirect(url_for('main.login')) 
        return f(*args, **kwargs)
    return decorated_function
# -------------------------------------------------

# --- ROTA: LISTAR BARBEARIAS ---
@bp.route('/barbearias') 
@login_required
@super_admin_required 
def listar_barbearias():
    """Exibe a lista de todas as barbearias cadastradas."""
    try:
        lista_barbearias = Barbearia.query.order_by(Barbearia.nome_fantasia).all()
    except Exception as e:
        current_app.logger.error(f"Erro ao buscar lista de barbearias: {e}", exc_info=True)
        flash('Ocorreu um erro ao carregar a lista de barbearias.', 'danger')
        lista_barbearias = [] 

    return render_template('superadmin/barbearias.html', barbearias=lista_barbearias)

# --- ROTA: ADICIONAR BARBEARIA ---
@bp.route('/barbearias/novo', methods=['GET', 'POST'])
@login_required
@super_admin_required
def nova_barbearia():
    """Exibe o formulário (GET) e processa a criação (POST)."""
    
    if request.method == 'POST':
        nome_fantasia = request.form.get('nome_fantasia')
        telefone_whatsapp = request.form.get('telefone_whatsapp')
        status_assinatura = request.form.get('status_assinatura')
        admin_email = request.form.get('admin_email')
        admin_senha = request.form.get('admin_senha')
        
        # 'get' dos novos campos
        meta_phone_number_id = request.form.get('meta_phone_number_id')
        meta_access_token = request.form.get('meta_access_token')

        erros = []
        if not nome_fantasia: erros.append("O Nome Fantasia é obrigatório.")
            
        if telefone_whatsapp and Barbearia.query.filter_by(telefone_whatsapp=telefone_whatsapp).first():
            erros.append(f"O telefone {telefone_whatsapp} já está em uso por outra barbearia.")
        if admin_email and User.query.filter_by(email=admin_email).first():
            erros.append(f"O email {admin_email} já está em uso por outro usuário.")

        if erros:
            for erro in erros:
                flash(erro, 'danger')
            return render_template('superadmin/novo.html', form_data=request.form)

        try:
            # ✅ LÓGICA DE CRIAÇÃO (STATUS)
            assinatura_ativa = False
            assinatura_expira_em = None
            
            # Limpa e normaliza o status
            status_clean = str(status_assinatura).strip().lower() if status_assinatura else 'teste'

            if status_clean == 'ativa':
                assinatura_ativa = True
                assinatura_expira_em = datetime.now() + timedelta(days=30)
            elif status_clean == 'teste':
                assinatura_ativa = True
                assinatura_expira_em = datetime.now() + timedelta(days=7)
            
            nova_barbearia = Barbearia(
                nome_fantasia=nome_fantasia,
                telefone_whatsapp=telefone_whatsapp,
                status_assinatura=status_assinatura,
                assinatura_ativa=assinatura_ativa,  
                assinatura_expira_em=assinatura_expira_em,  
                meta_phone_number_id=meta_phone_number_id,
                meta_access_token=meta_access_token
            )
                        
            db.session.add(nova_barbearia)
            db.session.flush() 

            novo_admin = User(
                email=admin_email,
                nome=f"Admin {nome_fantasia}", 
                role='admin',
                barbearia_id=nova_barbearia.id 
            )
            novo_admin.set_password(admin_senha) 
            db.session.add(novo_admin)
            
            db.session.commit()
            
            flash(f'Barbearia "{nome_fantasia}" criada com sucesso!', 'success')
            return redirect(url_for('superadmin.listar_barbearias'))

        except Exception as e:
            db.session.rollback() 
            current_app.logger.error(f"Erro ao criar nova barbearia: {e}", exc_info=True)
            flash(f'Erro ao salvar: {e}', 'danger')
            return render_template('superadmin/novo.html', form_data=request.form)

    return render_template('superadmin/novo.html', form_data={})

# --- ROTA: EDITAR BARBEARIA (AQUI ESTÁ A CORREÇÃO PRINCIPAL) ---
@bp.route('/barbearias/editar/<int:barbearia_id>', methods=['GET', 'POST'])
@login_required
@super_admin_required
def editar_barbearia(barbearia_id):
    barbearia = Barbearia.query.get_or_404(barbearia_id)
    
    if request.method == 'POST':
        # Captura os dados do formulário
        novo_status = request.form.get('status_assinatura')
        novo_nome = request.form.get('nome_fantasia')
        novo_tel = request.form.get('telefone_whatsapp')
        novo_meta_id = request.form.get('meta_phone_number_id')
        novo_meta_token = request.form.get('meta_access_token')
        
        # LOG DE DEPURAÇÃO (Verifique nos logs da Render se isso aparece)
        logging.info(f"📝 EDITANDO BARBEARIA {barbearia_id}: Status Recebido='{novo_status}'")

        try:
            barbearia.nome_fantasia = novo_nome
            barbearia.telefone_whatsapp = novo_tel
            barbearia.meta_phone_number_id = novo_meta_id
            barbearia.meta_access_token = novo_meta_token
            
            # Atualiza o texto visual (para aparecer certo no dropdown depois)
            barbearia.status_assinatura = novo_status
            
            # ✅ LÓGICA BLINDADA DE ATIVAÇÃO/DESATIVAÇÃO
            # 1. Remove espaços e coloca em minúsculo para comparar
            status_clean = str(novo_status).strip().lower()

            if status_clean == 'ativa':
                logging.info("-> Decisão: ATIVAR")
                barbearia.assinatura_ativa = True
                # Se não tem data ou já venceu, renova por 30 dias
                if not barbearia.assinatura_expira_em or barbearia.assinatura_expira_em < datetime.now():
                    barbearia.assinatura_expira_em = datetime.now() + timedelta(days=30)
                    logging.info("-> Data renovada para +30 dias")
            
            elif status_clean == 'teste':
                logging.info("-> Decisão: TESTE")
                barbearia.assinatura_ativa = True
                if not barbearia.assinatura_expira_em:
                    barbearia.assinatura_expira_em = datetime.now() + timedelta(days=7)
            
            else:
                # QUALQUER OUTRA COISA (Inativa, inativa, Cancelada...) DESATIVA TUDO
                logging.info(f"-> Decisão: DESATIVAR TOTALMENTE (Status: {status_clean})")
                barbearia.assinatura_ativa = False
                barbearia.assinatura_expira_em = None # Força remover a data
            
            # Força a gravação no banco
            db.session.add(barbearia)
            db.session.commit() 
            
            flash(f'Barbearia atualizada! Status: {novo_status}', 'success')
            return redirect(url_for('superadmin.listar_barbearias'))

        except Exception as e:
            db.session.rollback() 
            current_app.logger.error(f"Erro ao editar: {e}", exc_info=True)
            flash(f'Erro ao salvar: {e}', 'danger')
            return render_template('superadmin/editar.html', barbearia=barbearia, form_data=request.form)

    # Prepara os dados para preencher o formulário
    form_data_preenchido = {
        'nome_fantasia': barbearia.nome_fantasia,
        'telefone_whatsapp': barbearia.telefone_whatsapp,
        'status_assinatura': barbearia.status_assinatura,
        'meta_phone_number_id': barbearia.meta_phone_number_id,
        'meta_access_token': barbearia.meta_access_token
    }
    return render_template('superadmin/editar.html', barbearia=barbearia, form_data=form_data_preenchido)

# --- ROTA: APAGAR BARBEARIA ---
@bp.route('/barbearias/apagar/<int:barbearia_id>', methods=['POST'])
@login_required
@super_admin_required
def apagar_barbearia(barbearia_id):
    if barbearia_id == 1:
        flash('Erro: Não é permitido apagar a barbearia principal (ID 1).', 'danger')
        return redirect(url_for('superadmin.listar_barbearias'))

    barbearia = Barbearia.query.get_or_404(barbearia_id)
    try:
        db.session.delete(barbearia)
        db.session.commit()
        flash('Barbearia apagada com sucesso!', 'warning')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao apagar: {e}', 'danger')

    return redirect(url_for('superadmin.listar_barbearias'))
