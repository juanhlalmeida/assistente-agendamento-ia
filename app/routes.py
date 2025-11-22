# app/routes.py
# (CÓDIGO COMPLETO E BLINDADO PARA PRODUÇÃO)

import os
import logging
import google.generativeai as genai
from datetime import datetime, date, time, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, abort, jsonify
from sqlalchemy.orm import joinedload

# Importações de modelos
from app.models.tables import Agendamento, Profissional, Servico, User, Barbearia
from app.extensions import db

# Importa sanitize_msisdn (assumindo que está em whatsapp_client)
from app.whatsapp_client import WhatsAppClient, sanitize_msisdn
from app.services import ai_service  # <-- IMPORTAÇÃO CORRETA DA IA

# 🚀 IMPORTAÇÃO DA NOVA FUNÇÃO UNIFICADA DE CÁLCULO DE HORÁRIOS
from app.utils import calcular_horarios_disponiveis
from app.commands import reset_database_logic

# Importações do flask_login
from flask_login import login_required, current_user, login_user, logout_user

import requests  # <-- Adicionámos 'requests'
import json  # <-- Adicionámos 'json'

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Define o blueprint principal
bp = Blueprint('main', __name__)

# ============================================
# 🔒 PROTEÇÃO DE SEGURANÇA PARA PRODUÇÃO
# ============================================
# Desabilita rotas perigosas em produção automaticamente
ENABLE_DEV_ROUTES = os.getenv('ENABLE_DEV_ROUTES', 'false').lower() == 'true'

def dev_route_required():
    """
    Verifica se as rotas de desenvolvimento estão habilitadas.
    Em produção (Render), ENABLE_DEV_ROUTES não existe, então retorna 404.
    Isso "esconde" as rotas perigosas de hackers.
    """
    if not ENABLE_DEV_ROUTES:
        logging.warning("Tentativa de acesso a rota de desenvolvimento em produção bloqueada")
        abort(404)  # Retorna 404 (Not Found) para esconder a rota

# ============================================

# --- ADIÇÃO: Carregar Token de Verificação da Meta ---
META_VERIFY_TOKEN = os.getenv('META_VERIFY_TOKEN')

# --- FUNÇÃO DE ENVIO DO TWILIO (Preservada) ---
def enviar_mensagem_whatsapp_twilio(destinatario, mensagem):
    """
    Envia uma mensagem de texto para o destinatário usando a API do Twilio.
    """
    try:
        client = WhatsAppClient()
        api_res = client.send_text(destinatario, mensagem)
        if api_res.get("status") not in ('queued', 'sent', 'delivered', 'accepted'):
            logging.error("Falha no envio da resposta da IA via Twilio: %s", api_res)
            return False
        logging.info(f"Mensagem enviada para {destinatario} via Twilio.")
        return True
    except Exception as e:
        logging.error(f"Erro ao enviar mensagem via Twilio: {e}")
        return False

# --- CORREÇÃO CRÍTICA: FUNÇÃO DE ENVIO DA META ---
# (Agora lê os tokens DA BARBEARIA, e não do 'os.getenv')
def enviar_mensagem_whatsapp_meta(destinatario: str, mensagem: str, barbearia: Barbearia):
    """
    Envia uma mensagem de texto para o destinatário usando a API do WhatsApp (Meta).
    Lê as credenciais diretamente da barbearia (do banco de dados).
    """
    # 1. Lê os tokens do objeto 'barbearia' que veio do banco de dados
    access_token = barbearia.meta_access_token
    phone_number_id = barbearia.meta_phone_number_id
    
    # 2. Verifica se os tokens existem no banco de dados
    if not access_token or not phone_number_id:
        logging.error(f"Erro: Barbearia ID {barbearia.id} está sem META_ACCESS_TOKEN ou META_PHONE_NUMBER_ID no banco de dados.")
        return False
    
    # 3. Garante o formato do número
    if destinatario.startswith('whatsapp:'):
        destinatario = destinatario.replace('whatsapp:', '')
    
    url = f"https://graph.facebook.com/v19.0/{phone_number_id}/messages"
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    payload = {
        "messaging_product": "whatsapp",
        "to": destinatario,
        "type": "text",
        "text": {"body": mensagem}
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        logging.info(f"Mensagem enviada para {destinatario} via Meta: {response.json()}")
        return True
    except requests.exceptions.RequestException as e:
        # Se o erro for 401 ou 403, o token no banco de dados está errado/expirado
        logging.error(f"Erro ao enviar mensagem via Meta (Token expirado?): {e}")
        logging.error(f"Response Body: {e.response.text if e.response else 'Sem resposta'}")
        return False

# -------------------------------------------------------------
# --- FUNÇÕES DE AUTENTICAÇÃO (Preservadas) ---

@bp.route('/', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))
    
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        current_app.logger.info(f"Tentativa de login para o email: {email}")
        
        user = User.query.filter_by(email=email).first()
        if user:
            current_app.logger.info(f"Usuário encontrado no banco: {user.email} (ID: {user.id})")
            current_app.logger.info("Verificando senha...")
            
            if user.check_password(password):
                current_app.logger.info(f"Senha CORRETA para {user.email}. Realizando login.")
                login_user(user, remember=request.form.get('remember-me') is not None)
                current_app.logger.info(f"Função login_user executada. Usuário {user.email} deve estar na sessão.")
                
                next_page = request.args.get('next')
                if not next_page or not next_page.startswith('/'):
                    next_page = url_for('dashboard.index')
                
                flash('Login realizado com sucesso!', 'success')
                return redirect(next_page)
            else:
                current_app.logger.warning(f"Senha INCORRETA para o email: {email}")
                flash('Email ou senha inválidos.', 'danger')
        else:
            current_app.logger.warning(f"Usuário NÃO encontrado no banco para o email: {email}")
            flash('Email ou senha inválidos.', 'danger')
    
    return render_template('login.html')

@bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Você saiu do sistema.', 'info')
    return redirect(url_for('main.login'))

# --- FUNÇÕES DO PAINEL WEB (Preservadas) ---

def _range_do_dia(dia_dt: datetime):
    inicio = datetime.combine(dia_dt.date(), time.min)
    fim = inicio + timedelta(days=1)
    return inicio, fim

@bp.route('/agenda', methods=['GET', 'POST'])
@login_required
def agenda():
    if not hasattr(current_user, 'role') or current_user.role == 'super_admin' or not current_user.barbearia_id:
        flash('Acesso não permitido ou usuário inválido.', 'danger')
        return redirect(url_for('main.login'))
    
    barbearia_id_logada = current_user.barbearia_id
    
    if request.method == 'POST':
        nome_cliente = request.form.get('nome_cliente')
        telefone_cliente = request.form.get('telefone_cliente')
        data_hora_str = request.form.get('data_hora')
        profissional_id = request.form.get('profissional_id')
        servico_id = request.form.get('servico_id')
        
        if not all([nome_cliente, telefone_cliente, data_hora_str, profissional_id, servico_id]):
            flash('Erro: Todos os campos são obrigatórios.', 'danger')
            return redirect(url_for('main.agenda'))
        
        try:
            profissional = Profissional.query.filter_by(id=profissional_id, barbearia_id=barbearia_id_logada).first()
            if not profissional:
                flash('Profissional inválido ou não pertence à sua barbearia.', 'danger')
                raise ValueError("Profissional inválido.")
            
            servico = Servico.query.filter_by(id=servico_id, barbearia_id=barbearia_id_logada).first()
            if not servico:
                flash('Serviço inválido ou não pertence à sua barbearia.', 'danger')
                raise ValueError("Serviço inválido.")
            
            novo_inicio = datetime.strptime(data_hora_str, '%Y-%m-%dT%H:%M').replace(tzinfo=None)
            novo_fim = novo_inicio + timedelta(minutes=servico.duracao)
            
            inicio_dia, fim_dia = _range_do_dia(novo_inicio)
            ags = (
                Agendamento.query
                .options(joinedload(Agendamento.servico))
                .filter(
                    Agendamento.barbearia_id == barbearia_id_logada,
                    Agendamento.profissional_id == profissional.id,
                    Agendamento.data_hora >= inicio_dia,
                    Agendamento.data_hora < fim_dia
                )
                .all()
            )
            
            conflito = any(
                max(novo_inicio, ag.data_hora) < min(novo_fim, ag.data_hora + timedelta(minutes=ag.servico.duracao))
                for ag in ags
            )
            
            if conflito:
                flash('Erro: O profissional já está ocupado neste horário.', 'danger')
            else:
                novo_agendamento = Agendamento(
                    nome_cliente=nome_cliente,
                    telefone_cliente=telefone_cliente,
                    data_hora=novo_inicio,
                    profissional_id=profissional.id,
                    servico_id=servico.id,
                    barbearia_id=barbearia_id_logada
                )
                db.session.add(novo_agendamento)
                db.session.commit()
                flash('Agendamento criado com sucesso!', 'success')
        
        except ValueError as ve:
            pass
        except Exception as e:
            db.session.rollback()
            flash(f'Ocorreu um erro ao processar o agendamento: {str(e)}', 'danger')
            current_app.logger.error(f"Erro POST /agenda: {e}", exc_info=True)
        
        redirect_date_str = (novo_inicio if 'novo_inicio' in locals() else datetime.now()).strftime('%Y-%m-%d')
        prof_id_redirect = profissional_id if 'profissional_id' in locals() and profissional_id else None
        if prof_id_redirect:
            prof_check = Profissional.query.filter_by(id=prof_id_redirect, barbearia_id=barbearia_id_logada).first()
            if not prof_check:
                prof_id_redirect = None
        
        return redirect(url_for('main.agenda', data=redirect_date_str, profissional_id=prof_id_redirect))
    
    # --- Lógica GET (Preservada) ---
    data_sel_str = request.args.get('data', date.today().strftime('%Y-%m-%d'))
    profissional_sel_id = request.args.get('profissional_id')
    
    try:
        data_sel = datetime.strptime(data_sel_str, '%Y-%m-%d')
    except ValueError:
        flash('Data inválida fornecida.', 'warning')
        data_sel = datetime.combine(date.today(), time.min)
        data_sel_str = data_sel.strftime('%Y-%m-%d')
    
    profissionais = Profissional.query.filter_by(barbearia_id=barbearia_id_logada).order_by(Profissional.nome).all()
    servicos = Servico.query.filter_by(barbearia_id=barbearia_id_logada).order_by(Servico.nome).all()
    
    horarios_disponiveis_dt = []
    profissional_sel = None
    
    if profissional_sel_id:
        profissional_sel = Profissional.query.filter_by(id=profissional_sel_id, barbearia_id=barbearia_id_logada).first()
        if not profissional_sel and profissionais:
            profissional_sel = profissionais[0]
            profissional_sel_id = profissional_sel.id
    elif profissionais:
        profissional_sel = profissionais[0]
        profissional_sel_id = profissional_sel.id
    
    if profissional_sel:
        horarios_disponiveis_dt = calcular_horarios_disponiveis(profissional_sel, data_sel)
    
    inicio_query, fim_query = _range_do_dia(data_sel)
    ags_dia = (
        Agendamento.query
        .options(joinedload(Agendamento.servico), joinedload(Agendamento.profissional))
        .filter(
            Agendamento.barbearia_id == barbearia_id_logada,
            Agendamento.data_hora >= inicio_query,
            Agendamento.data_hora < fim_query
        )
        .filter(Agendamento.profissional_id == profissional_sel.id if profissional_sel else True)
        .order_by(Agendamento.data_hora.asc())
        .all()
    )
    
    return render_template(
        'agenda.html',
        agendamentos=ags_dia,
        profissionais=profissionais,
        servicos=servicos,
        horarios_disponiveis=horarios_disponiveis_dt,
        data_selecionada=data_sel,
        profissional_selecionado=profissional_sel
    )

@bp.route('/agendamento/excluir/<int:agendamento_id>', methods=['POST'])
@login_required
def excluir_agendamento(agendamento_id):
    barbearia_id_logada = current_user.barbearia_id
    ag = Agendamento.query.filter_by(id=agendamento_id, barbearia_id=barbearia_id_logada).first_or_404("Agendamento não encontrado ou não pertence à sua barbearia.")
    
    data_redirect = ag.data_hora.strftime('%Y-%m-%d')
    prof_redirect = ag.profissional_id
    
    try:
        db.session.delete(ag)
        db.session.commit()
        flash('Agendamento excluído com sucesso!', 'warning')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao excluir agendamento: {str(e)}', 'danger')
    
    return redirect(url_for('main.agenda', data=data_redirect, profissional_id=prof_redirect))

@bp.route('/agendamento/editar/<int:agendamento_id>', methods=['GET', 'POST'])
@login_required
def editar_agendamento(agendamento_id):
    barbearia_id_logada = current_user.barbearia_id
    ag = Agendamento.query.filter_by(id=agendamento_id, barbearia_id=barbearia_id_logada).first_or_404("Agendamento não encontrado ou não pertence à sua barbearia.")
    
    if request.method == 'POST':
        try:
            novo_profissional_id = int(request.form.get('profissional_id'))
            novo_servico_id = int(request.form.get('servico_id'))
            
            prof = Profissional.query.filter_by(id=novo_profissional_id, barbearia_id=barbearia_id_logada).first()
            serv = Servico.query.filter_by(id=novo_servico_id, barbearia_id=barbearia_id_logada).first()
            
            if not prof or not serv:
                flash('Profissional ou Serviço inválido para esta barbearia.', 'danger')
                raise ValueError("Profissional ou Serviço inválido.")
            
            ag.nome_cliente = request.form.get('nome_cliente')
            ag.telefone_cliente = request.form.get('telefone_cliente')
            ag.data_hora = datetime.strptime(request.form.get('data_hora'), '%Y-%m-%dT%H:%M').replace(tzinfo=None)
            ag.profissional_id = novo_profissional_id
            ag.servico_id = novo_servico_id
            
            db.session.commit()
            flash('Agendamento atualizado com sucesso!', 'success')
            return redirect(url_for('main.agenda',
                                    data=ag.data_hora.strftime('%Y-%m-%d'),
                                    profissional_id=ag.profissional_id))
        
        except ValueError as ve:
            pass
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao atualizar agendamento: {str(e)}', 'danger')
            return redirect(url_for('main.editar_agendamento', agendamento_id=agendamento_id))
    
    profissionais = Profissional.query.filter_by(barbearia_id=barbearia_id_logada).order_by(Profissional.nome).all()
    servicos = Servico.query.filter_by(barbearia_id=barbearia_id_logada).order_by(Servico.nome).all()
    
    return render_template('editar_agendamento.html',
                           agendamento=ag, profissionais=profissionais, servicos=servicos)

# --- ROTA DO TWILIO (Preservada) ---
@bp.route('/webhook', methods=['POST'])
def webhook_twilio():
    data = request.values
    logging.info("PAYLOAD RECEBIDO DA TWILIO: %s", data)
    
    try:
        mensagem_recebida = data.get('Body')
        remetente = data.get('From')
        to_number_raw = data.get('To')
        
        if not remetente or not mensagem_recebida or not to_number_raw:
            logging.warning("Webhook da Twilio recebido sem 'From', 'Body' ou 'To'.")
            return 'OK', 200
        
        barbearia_phone = sanitize_msisdn(to_number_raw)
        barbearia = Barbearia.query.filter_by(telefone_whatsapp=barbearia_phone).first()
        
        if not barbearia:
            logging.error(f"CRÍTICO: Nenhuma barbearia encontrada para o número {barbearia_phone}. Ignorando mensagem.")
            return 'OK', 200
        
        if barbearia.status_assinatura != 'ativa':
            logging.warning(f"Mensagem recebida para barbearia '{barbearia.nome_fantasia}' com assinatura '{barbearia.status_assinatura}'. Ignorando.")
            return 'OK', 200
        
        barbearia_id = barbearia.id
        logging.info(f"Mensagem roteada para Barbearia ID: {barbearia_id} ({barbearia.nome_fantasia})")
        print(f"Mensagem recebida do Twilio de {remetente}: {mensagem_recebida}")
        
        # --- CORREÇÃO DA IA (Chamando a função correta) ---
        resposta_ia = ai_service.processar_ia_gemini(
            user_message=mensagem_recebida,
            barbearia_id=barbearia.id,
            cliente_whatsapp=remetente
        )
        # -----------------------------------------------
        
        if resposta_ia:
            enviar_mensagem_whatsapp_twilio(remetente, resposta_ia)
        
        return "Mensagem processada", 200
    
    except Exception as e:
        logging.error(f"Erro no webhook do Twilio: {e}")
        return "Erro interno", 500

# ============================================
# ✨ ROTA DO WEBHOOK DA META - ATUALIZADA
# ============================================
@bp.route('/meta-webhook', methods=['GET', 'POST'])
def webhook_meta():
    """
    Webhook para verificação e recebimento de mensagens da Meta.
    """
    if request.method == 'GET':
        # --- VERIFICAÇÃO DO WEBHOOK (Preservado) ---
        mode = request.args.get('hub.mode')
        token = request.args.get('hub.verify_token')
        challenge = request.args.get('hub.challenge')
        
        if mode == 'subscribe' and token == META_VERIFY_TOKEN:
            logging.info("Webhook da Meta verificado com sucesso!")
            return challenge, 200
        else:
            logging.warning(f"Falha na verificação do Webhook da Meta. Token recebido: {token}")
            return "Falha na verificação", 403
    
    elif request.method == 'POST':
        # --- RECEBIMENTO DE MENSAGENS ---
        data = request.get_json()
        logging.info(f"Payload recebido da Meta: {json.dumps(data, indent=2)}")
        
        try:
            # Verifica se é uma mensagem de texto (Preservado)
            if (data.get('object') == 'whatsapp_business_account' and
                data.get('entry') and data['entry'][0].get('changes') and
                data['entry'][0]['changes'][0].get('value') and
                data['entry'][0]['changes'][0]['value'].get('messages')):
                
                message_data = data['entry'][0]['changes'][0]['value']['messages'][0]
                
                if message_data.get('type') == 'text':
                    mensagem_recebida = message_data['text']['body']
                    remetente = message_data['from']  # Formato: "55..."
                    
                    # ============================================
                    # ✨ LÓGICA DE ROTEAMENTO + BLOQUEIO DE ASSINATURA
                    # ============================================
                    phone_number_id = data['entry'][0]['changes'][0]['value']['metadata']['phone_number_id']
                    barbearia = Barbearia.query.filter_by(meta_phone_number_id=phone_number_id).first()
                    
                    if not barbearia:
                        logging.error(f"CRÍTICO: Nenhuma barbearia encontrada para phone_number_id {phone_number_id}. Ignorando mensagem.")
                        return jsonify({"status": "ignored"}), 200
                    
                    # ✅ BLOQUEIO 1: Verifica se assinatura está ativa
                    if not barbearia.assinatura_ativa:
                        logging.warning(f"🚫 Barbearia '{barbearia.nome_fantasia}' (ID: {barbearia.id}) com assinatura INATIVA. Ignorando mensagem do WhatsApp.")
                        return jsonify({"status": "subscription_inactive"}), 200
                    
                    # ✅ BLOQUEIO 2: Verifica se assinatura expirou
                    if barbearia.assinatura_expira_em and barbearia.assinatura_expira_em < datetime.now():
                        logging.warning(f"🚫 Barbearia '{barbearia.nome_fantasia}' (ID: {barbearia.id}) com assinatura EXPIRADA em {barbearia.assinatura_expira_em}. Ignorando mensagem.")
                        return jsonify({"status": "subscription_expired"}), 200
                    
                    # ✅ (OPCIONAL) Mantém verificação do status_assinatura antigo (por compatibilidade)
                    if barbearia.status_assinatura != 'ativa':
                        logging.warning(f"Mensagem recebida para barbearia '{barbearia.nome_fantasia}' com status_assinatura '{barbearia.status_assinatura}'. Ignorando.")
                        return jsonify({"status": "ignored"}), 200
                    
                    logging.info(f"✅ Mensagem autorizada para Barbearia: {barbearia.nome_fantasia} (assinatura ativa até {barbearia.assinatura_expira_em})")
                    # ============================================
                    
                    # --- PROCESSAMENTO DA IA ---
                    resposta_ia = ai_service.processar_ia_gemini(
                        user_message=mensagem_recebida,
                        barbearia_id=barbearia.id,
                        cliente_whatsapp=remetente
                    )
                    
                    if resposta_ia:
                        enviar_mensagem_whatsapp_meta(remetente, resposta_ia, barbearia)
                    
                    return jsonify({"status": "success"}), 200
            
            else:
                # Isto é normal, são os recibos de "sent", "delivered", "read"
                logging.info("Payload da Meta recebido, mas não é uma mensagem de texto (provavelmente um status). Ignorando.")
                return jsonify({"status": "ignored"}), 200
        
        except Exception as e:
            logging.error(f"Erro ao processar payload da Meta: {e}", exc_info=True)
            return jsonify({"status": "error"}), 500
    
    else:
        return "Método não permitido", 405

# ============================================
# 🔒 ROTAS PERIGOSAS - PROTEGIDAS
# ============================================

@bp.route('/admin/reset-database/<secret_key>')
def reset_database(secret_key):
    """
    🔒 ROTA PERIGOSA - Apaga TODO o banco de dados.
    BLOQUEADA automaticamente em produção (Render).
    """
    # ✅ PRIMEIRA COISA: Verifica se está em produção
    dev_route_required()  # Se estiver em produção, retorna 404 aqui e para
    
    # Resto do código CONTINUA IGUAL (só roda em desenvolvimento local)
    expected_key = os.getenv('RESET_DB_KEY')
    if not expected_key or secret_key != expected_key:
        abort(404)
    
    try:
        logging.info("Iniciando o reset do banco de dados via rota segura...")
        reset_database_logic()
        logging.info("Banco de dados recriado com sucesso.")
        return "Banco de dados recriado com sucesso! Pode tentar fazer login agora.", 200
    except Exception as e:
        logging.error("Erro ao recriar o banco de dados: %s", e, exc_info=True)
        return f"Ocorreu um erro ao recriar o banco de dados: {str(e)}", 500

@bp.route('/admin/criar-primeiro-usuario/<secret_key>')
def criar_primeiro_usuario(secret_key):
    """
    🔒 ROTA PERIGOSA - Cria usuário admin sem validação.
    BLOQUEADA automaticamente em produção (Render).
    """
    # ✅ PRIMEIRA COISA: Verifica se está em produção
    dev_route_required()  # Se estiver em produção, retorna 404 aqui e para
    
    # Resto do código CONTINUA IGUAL (só roda em desenvolvimento local)
    expected_key = os.getenv('ADMIN_KEY')
    if not expected_key or secret_key != expected_key:
        abort(404)
    
    email_admin = "admin@email.com"
    user = User.query.filter_by(email=email_admin).first()
    if user:
        return f"O usuário '{email_admin}' já existe."
    
    try:
        senha_admin = "admin123"
        barbearia_teste = Barbearia.query.get(1)
        if not barbearia_teste:
            return "Erro: Nenhuma barbearia encontrada no banco para associar o usuário.", 500
        
        u = User(email=email_admin, nome='Admin Criado Via Rota', role='admin', barbearia_id=barbearia_teste.id)
        u.set_password(senha_admin)
        db.session.add(u)
        db.session.commit()
        
        msg = f"Usuário '{email_admin}' (Senha: '{senha_admin}') foi criado com sucesso para a Barbearia ID {barbearia_teste.id}!"
        current_app.logger.info(msg)
        return msg
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Erro ao criar usuário admin via rota: {e}")
        return f"Ocorreu um erro: {e}", 500
