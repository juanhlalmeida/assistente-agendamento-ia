# app/blueprints/superadmin/routes.py
# (VERSÃO BLINDADA: CORREÇÃO DE STATUS, TRIM E LOGS DE AUDITORIA)

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
        
        # Captura o status bruto
        status_assinatura_raw = request.form.get('status_assinatura')
        
        admin_email = request.form.get('admin_email')
        admin_senha = request.form.get('admin_senha')
        
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
            # ✅ LÓGICA DE STATUS BLINDADA (NOVO)
            # 1. Limpa espaços e converte para minúsculo
            status_clean = str(status_assinatura_raw).strip().lower() if status_assinatura_raw else 'teste'
            
            logging.info(f"🆕 CRIANDO BARBEARIA: Status Bruto='{status_assinatura_raw}' -> Limpo='{status_clean}'")

            assinatura_ativa = False
            assinatura_expira_em = None
            
            if status_clean == 'ativa':
                assinatura_ativa = True
                assinatura_expira_em = datetime.now() + timedelta(days=30)
                logging.info("-> Decisão: ATIVAR (30 dias)")
            elif status_clean == 'teste':
                assinatura_ativa = True
                assinatura_expira_em = datetime.now() + timedelta(days=7)
                logging.info("-> Decisão: TESTE (7 dias)")
            else:
                logging.info("-> Decisão: INATIVA (Sem acesso)")
            
            nova_barbearia = Barbearia(
                nome_fantasia=nome_fantasia,
                telefone_whatsapp=telefone_whatsapp,
                status_assinatura=status_assinatura_raw, # Salva o visual original
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

# --- ROTA: EDITAR BARBEARIA ---
@bp.route('/barbearias/editar/<int:barbearia_id>', methods=['GET', 'POST'])
@login_required
@super_admin_required
def editar_barbearia(barbearia_id):
    barbearia = Barbearia.query.get_or_404(barbearia_id)
    
    if request.method == 'POST':
        nome_fantasia = request.form.get('nome_fantasia')
        telefone_whatsapp = request.form.get('telefone_whatsapp')
        
        # Captura o status bruto
        status_assinatura_raw = request.form.get('status_assinatura')
        
        meta_phone_number_id = request.form.get('meta_phone_number_id')
        meta_access_token = request.form.get('meta_access_token')

        erros = []
        if not nome_fantasia: erros.append("O Nome Fantasia é obrigatório.")
            
        if telefone_whatsapp:
            existente = Barbearia.query.filter(
                Barbearia.telefone_whatsapp == telefone_whatsapp,
                Barbearia.id != barbearia_id 
            ).first()
            if existente:
                erros.append(f"O telefone {telefone_whatsapp} já está em uso por outra barbearia.")

        if erros:
            for erro in erros:
                flash(erro, 'danger')
            return render_template('superadmin/editar.html', barbearia=barbearia, form_data=request.form)

        try:
            barbearia.nome_fantasia = nome_fantasia
            barbearia.telefone_whatsapp = telefone_whatsapp
            barbearia.meta_phone_number_id = meta_phone_number_id
            barbearia.meta_access_token = meta_access_token
            
            # Atualiza o campo visual (texto)
            barbearia.status_assinatura = status_assinatura_raw
            
            # ✅ LÓGICA DE STATUS BLINDADA E COM LOGS (A CORREÇÃO PRINCIPAL)
            # .strip() remove espaços vazios antes/depois
            # .lower() garante que "Inativa" vire "inativa"
            status_clean = str(status_assinatura_raw).strip().lower() if status_assinatura_raw else ''
            
            logging.info(f"✏️ EDITANDO BARBEARIA {barbearia_id}: Status Bruto='{status_assinatura_raw}' -> Limpo='{status_clean}'")

            if status_clean == 'ativa':
                logging.info("-> Decisão: ATIVAR")
                barbearia.assinatura_ativa = True
                # Renovação inteligente: Só muda a data se estiver vazia ou no passado
                if not barbearia.assinatura_expira_em or barbearia.assinatura_expira_em < datetime.now():
                    barbearia.assinatura_expira_em = datetime.now() + timedelta(days=30)
                    logging.info("-> Data renovada para +30 dias")
            
            elif status_clean == 'teste':
                logging.info("-> Decisão: TESTE")
                barbearia.assinatura_ativa = True
                if not barbearia.assinatura_expira_em:
                    barbearia.assinatura_expira_em = datetime.now() + timedelta(days=7)
            
            else:
                # QUALQUER COISA DIFERENTE DE 'ativa' ou 'teste' VAI DESATIVAR
                # Isso pega: "Inativa", "Bloqueada", "Cancelada", etc.
                logging.info("-> Decisão: DESATIVAR TOTALMENTE")
                barbearia.assinatura_ativa = False
                barbearia.assinatura_expira_em = None # Força NULL no banco
            
            db.session.commit() 
            
            flash(f'Barbearia "{nome_fantasia}" atualizada com sucesso!', 'success')
            return redirect(url_for('superadmin.listar_barbearias'))

        except Exception as e:
            db.session.rollback() 
            current_app.logger.error(f"Erro ao editar barbearia {barbearia_id}: {e}", exc_info=True)
            flash(f'Erro ao salvar: {e}', 'danger')
            return render_template('superadmin/editar.html', barbearia=barbearia, form_data=request.form)

    # Preenche formulário
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
    """Apaga uma barbearia (e todos os dados associados em cascata)."""
    
    if barbearia_id == 1:
        flash('Erro: Não é permitido apagar a barbearia principal (ID 1).', 'danger')
        return redirect(url_for('superadmin.listar_barbearias'))

    barbearia = Barbearia.query.get_or_404(barbearia_id)
    nome_barbearia = barbearia.nome_fantasia

    try:
        db.session.delete(barbearia)
        db.session.commit()
        flash(f'Barbearia "{nome_barbearia}" apagada com sucesso!', 'warning')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Erro ao apagar: {e}", exc_info=True)
        flash(f'Erro ao apagar: {e}', 'danger')

    return redirect(url_for('superadmin.listar_barbearias'))
