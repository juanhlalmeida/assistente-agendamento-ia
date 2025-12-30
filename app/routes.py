# app/routes.py
# (VERSÃO FINAL: BASEADO NO SEU ARQUIVO + LOGS DETALHADOS PARA MERCHANT ORDER)

import os
import logging
import json
import requests
import threading
from werkzeug.utils import secure_filename
from datetime import datetime, date, time, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, abort, jsonify
from sqlalchemy.orm import joinedload

# Importações de modelos
from app.models.tables import Agendamento, Profissional, Servico, User, Barbearia, Plano
from app.extensions import db

# ============================================
# ✅ IMPORTAÇÕES OPCIONAIS DO TWILIO
# ============================================
try:
    from app.whatsapp_client import WhatsAppClient, sanitize_msisdn
    TWILIO_AVAILABLE = True
    logging.info("✅ Twilio/WhatsAppClient disponível")
except ImportError as e:
    TWILIO_AVAILABLE = False
    WhatsAppClient = None
    sanitize_msisdn = None
    logging.warning(f"⚠️ Twilio/WhatsAppClient não disponível: {e}. Webhook Twilio desabilitado.")
# ============================================

# ✅ Tenta importar Serviço de Pagamento (Mercado Pago)
try:
    from app.services.mercadopago_service import mercadopago_service
    MP_AVAILABLE = True
except ImportError:
    logging.warning("⚠️ O arquivo mercadopago_service.py não foi encontrado. Pagamentos desativados.")
    mercadopago_service = None
    MP_AVAILABLE = False

from app.services import ai_service  
from app.services.audio_service import AudioService

# Importação da função unificada de cálculo de horários
from app.utils import calcular_horarios_disponiveis
from app.commands import reset_database_logic

# Importações do flask_login
from flask_login import login_required, current_user, login_user, logout_user

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Define o blueprint principal
bp = Blueprint('main', __name__)

# Instancia o serviço de áudio globalmente
audio_service = AudioService()

# ============================================
# 🔒 PROTEÇÃO DE SEGURANÇA PARA PRODUÇÃO
# ============================================
ENABLE_DEV_ROUTES = os.getenv('ENABLE_DEV_ROUTES', 'false').lower() == 'true'

def dev_route_required():
    """
    Verifica se as rotas de desenvolvimento estão habilitadas.
    Em produção (Render), ENABLE_DEV_ROUTES não existe, então retorna 404.
    """
    if not ENABLE_DEV_ROUTES:
        logging.warning("Tentativa de acesso a rota de desenvolvimento em produção bloqueada")
        abort(404)

# ============================================

META_VERIFY_TOKEN = os.getenv('META_VERIFY_TOKEN')

# --- FUNÇÃO DE ENVIO DO TWILIO (OPCIONAL/LEGADO) ---
def enviar_mensagem_whatsapp_twilio(destinatario, mensagem):
    """
    Envia mensagem via Twilio (apenas se biblioteca estiver disponível)
    """
    if not TWILIO_AVAILABLE:
        return False

    try:
        client = WhatsAppClient() 
        api_res = client.send_text(destinatario, mensagem)
        if api_res.get("status") not in ('queued', 'sent', 'delivered', 'accepted'):
            logging.error(f"Falha no envio via Twilio: {api_res}")
            return False
        logging.info(f"✅ Mensagem enviada para {destinatario} via Twilio.")
        return True
    except Exception as e:
        logging.error(f"❌ Erro ao enviar mensagem via Twilio: {e}")
        return False

# --- FUNÇÃO DE ENVIO DA META (PRINCIPAL) ---
def enviar_mensagem_whatsapp_meta(destinatario: str, mensagem: str, barbearia: Barbearia):
    """
    Envia uma mensagem de texto para o destinatário usando a API do WhatsApp (Meta).
    Lê as credenciais diretamente da barbearia.
    """
    access_token = barbearia.meta_access_token
    phone_number_id = barbearia.meta_phone_number_id
    
    if not access_token or not phone_number_id:
        logging.error(f"Erro: Barbearia ID {barbearia.id} está sem META_ACCESS_TOKEN ou META_PHONE_NUMBER_ID.")
        return False
    
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
        # logging.info(f"✅ Mensagem enviada para {destinatario} via Meta: {response.json()}")
        return True
    except requests.exceptions.RequestException as e:
        logging.error(f"❌ Erro ao enviar mensagem via Meta: {e}")
        return False

# --- NOVO: FUNÇÃO PARA ENVIAR MÍDIA (FOTO/PDF) ---
def enviar_midia_whatsapp_meta(destinatario: str, url_arquivo: str, barbearia: Barbearia):
    """
    Envia imagem para o WhatsApp do cliente via Meta API.
    """
    if not url_arquivo: return False
    
    # Remove prefixo whatsapp: se existir
    if destinatario.startswith('whatsapp:'):
        destinatario = destinatario.replace('whatsapp:', '')

    url = f"https://graph.facebook.com/v19.0/{barbearia.meta_phone_number_id}/messages"
    headers = {"Authorization": f"Bearer {barbearia.meta_access_token}", "Content-Type": "application/json"}
    
    payload = {
        "messaging_product": "whatsapp",
        "to": destinatario,
        "type": "image", 
        "image": {"link": url_arquivo}
    }
    try:
        response = requests.post(url, headers=headers, json=payload)
        # Não damos raise_for_status aqui para não quebrar o fluxo se a URL for inválida temporariamente
        if response.status_code == 200:
            logging.info(f"✅ Mídia enviada com sucesso para {destinatario}")
            return True
        else:
            logging.error(f"❌ Erro Meta Media: {response.text}")
            return False
    except Exception as e:
        logging.error(f"❌ Erro ao enviar mídia: {e}")
        return False

# --- NOVO: FUNÇÃO MARCAR COMO LIDO ---
def marcar_como_lido(message_id: str, barbearia: Barbearia):
    """
    Marca a mensagem recebida como lida (tiques azuis) para dar feedback ao usuário.
    """
    if not message_id: return
    
    url = f"https://graph.facebook.com/v19.0/{barbearia.meta_phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {barbearia.meta_access_token}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": message_id
    }
    try:
        requests.post(url, headers=headers, json=payload)
    except Exception:
        pass

# --- HELPER PARA PROCESSAMENTO DE ÁUDIO EM THREAD ---
def processar_audio_background(audio_id, wa_id, access_token, phone_number_id, barbearia_id, app_instance): # <-- Recebe app_instance
    """
    Processa o áudio em background e envia a resposta.
    IMPORTANTE: Usa 'app_instance.app_context()' para permitir acesso ao banco de dados na thread.
    """
    # Cria o contexto manualmente usando a instância do app passada
    with app_instance.app_context():
        try:
            # logging.info(f"🧵 Thread áudio iniciada: {audio_id}")
            
            # Passa a instância do app para o serviço (embora o contexto já esteja ativo aqui, o serviço pode precisar)
            resposta_texto = audio_service.processar_audio(audio_id, access_token, wa_id, barbearia_id, app_instance)
            
            if resposta_texto:
                # Envia resposta
                url = f"https://graph.facebook.com/v19.0/{phone_number_id}/messages"
                headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
                payload = {
                    "messaging_product": "whatsapp",
                    "to": wa_id,
                    "type": "text",
                    "text": {"body": resposta_texto}
                }
                requests.post(url, headers=headers, json=payload)
                logging.info(f"✅ 🧵 Resposta do áudio enviada com sucesso para {wa_id}")
                
        except Exception as e:
            logging.error(f"❌ Erro crítico na thread de áudio: {e}")

# -------------------------------------------------------------
# --- FUNÇÕES DE AUTENTICAÇÃO ---

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
            if user.check_password(password):
                current_app.logger.info(f"Senha CORRETA para {user.email}. Realizando login.")
                login_user(user, remember=request.form.get('remember-me') is not None)
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

# --- FUNÇÕES DO PAINEL WEB ---

def _range_do_dia(dia_dt: datetime):
    inicio = datetime.combine(dia_dt.date(), time.min)
    fim = inicio + timedelta(days=1)
    return inicio, fim

@bp.route('/agenda', methods=['GET', 'POST'])
@login_required
def agenda():
    # CORREÇÃO: Removemos o bloqueio do 'super_admin'. Agora ele PODE acessar.
    # Apenas verificamos se tem barbearia vinculada.
    if not hasattr(current_user, 'role') or not current_user.barbearia_id:
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
                flash('Profissional inválido.', 'danger')
                raise ValueError("Profissional inválido.")
            
            servico = Servico.query.filter_by(id=servico_id, barbearia_id=barbearia_id_logada).first()
            if not servico:
                flash('Serviço inválido.', 'danger')
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
                
                # =================================================================
                # 🔔 NOTIFICAÇÃO PARA O DONO (COM TEMA DINÂMICO LASH/BARBER)
                # =================================================================
                try:
                    barbearia_dono = profissional.barbearia
                    if barbearia_dono.telefone_admin and barbearia_dono.assinatura_ativa:
                        
                        # --- DETECÇÃO DE TEMA DINÂMICO ---
                        nome_loja = barbearia_dono.nome_fantasia.lower()
                        # Lista de palavras-chave para o nicho de beleza
                        is_lash = any(x in nome_loja for x in ['lash', 'studio', 'cílios', 'sobrancelha', 'beleza', 'estética'])
                        
                        if is_lash:
                            emoji_titulo = "🦋✨"
                            emoji_servico = "💅"
                            emoji_prof = "👩‍⚕️"
                        else:
                            emoji_titulo = "💈✂️"
                            emoji_servico = "🪒"
                            emoji_prof = "👊"

                        msg_dono = (
                            f"🔔 *Novo Agendamento (Via Painel)* {emoji_titulo}\n\n"
                            f"👤 Cliente: {nome_cliente}\n"
                            f"📞 Tel: {telefone_cliente}\n"
                            f"{emoji_servico} Serviço: {servico.nome}\n"
                            f"🗓 Data: {novo_inicio.strftime('%d/%m às %H:%M')}\n"
                            f"{emoji_prof} Prof: {profissional.nome}"
                        )
                        enviar_mensagem_whatsapp_meta(barbearia_dono.telefone_admin, msg_dono, barbearia_dono)
                except Exception as e_notify:
                    # Não bloqueia o agendamento se a notificação falhar
                    logging.error(f"Erro ao notificar dono: {e_notify}")
                # =================================================================

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
    
    # --- Lógica GET ---
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
    ag = Agendamento.query.filter_by(id=agendamento_id, barbearia_id=barbearia_id_logada).first_or_404()
    
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
    ag = Agendamento.query.filter_by(id=agendamento_id, barbearia_id=barbearia_id_logada).first_or_404()
    
    if request.method == 'POST':
        try:
            novo_profissional_id = int(request.form.get('profissional_id'))
            novo_servico_id = int(request.form.get('servico_id'))
            
            prof = Profissional.query.filter_by(id=novo_profissional_id, barbearia_id=barbearia_id_logada).first()
            serv = Servico.query.filter_by(id=novo_servico_id, barbearia_id=barbearia_id_logada).first()
            
            if not prof or not serv:
                flash('Profissional ou Serviço inválido.', 'danger')
                raise ValueError("Dados inválidos.")
            
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
        
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao atualizar agendamento: {str(e)}', 'danger')
            return redirect(url_for('main.editar_agendamento', agendamento_id=agendamento_id))
    
    profissionais = Profissional.query.filter_by(barbearia_id=barbearia_id_logada).order_by(Profissional.nome).all()
    servicos = Servico.query.filter_by(barbearia_id=barbearia_id_logada).order_by(Servico.nome).all()
    
    return render_template('editar_agendamento.html',
                           agendamento=ag, profissionais=profissionais, servicos=servicos)

# --- ROTA DO TWILIO (PRESERVADA COM PROTEÇÃO) ---
@bp.route('/webhook', methods=['POST'])
def webhook_twilio():
    """
    Webhook do Twilio (apenas funciona se biblioteca estiver instalada)
    """
    if not TWILIO_AVAILABLE:
        logging.warning("⚠️ Webhook Twilio chamado, mas biblioteca não instalada.")
        return jsonify({"status": "twilio_disabled"}), 200

    data = request.values
    try:
        mensagem_recebida = data.get('Body')
        remetente = data.get('From')
        to_number_raw = data.get('To')
        
        if not remetente or not mensagem_recebida or not to_number_raw:
            return 'OK', 200
        
        barbearia_phone = sanitize_msisdn(to_number_raw)
        barbearia = Barbearia.query.filter_by(telefone_whatsapp=barbearia_phone).first()
        
        if not barbearia or barbearia.status_assinatura != 'ativa':
            return 'OK', 200
        
        # --- IA (TEXTO) ---
        resposta_ia = ai_service.processar_ia_gemini(
            user_message=mensagem_recebida,
            barbearia_id=barbearia.id,
            cliente_whatsapp=remetente
        )
        if resposta_ia:
            enviar_mensagem_whatsapp_twilio(remetente, resposta_ia)
        
        return "Mensagem processada", 200
    
    except Exception as e:
        logging.error(f"❌ Erro no webhook do Twilio: {e}")
        return "Erro interno", 500

# ==============================================================================
# ✨ ROTA DO WEBHOOK DA META (COM DEBUG ATIVADO)
# ==============================================================================
@bp.route('/meta-webhook', methods=['GET', 'POST'])
def webhook_meta():
    """
    Webhook para verificação e recebimento de mensagens da Meta (Texto e Áudio).
    """
    if request.method == 'GET':
        mode = request.args.get('hub.mode')
        token = request.args.get('hub.verify_token')
        challenge = request.args.get('hub.challenge')
        
        if mode == 'subscribe' and token == META_VERIFY_TOKEN:
            logging.info("✅ Webhook da Meta verificado com sucesso!")
            return challenge, 200
        else:
            logging.warning(f"⚠️ Falha na verificação do Webhook. Token: {token}")
            return "Falha na verificação", 403
    
    elif request.method == 'POST':
        data = request.get_json()
        
        try:
            if (data.get('object') == 'whatsapp_business_account' and
                data.get('entry') and data['entry'][0].get('changes') and
                data['entry'][0]['changes'][0].get('value') and
                data['entry'][0]['changes'][0]['value'].get('messages')):
                
                value = data['entry'][0]['changes'][0]['value']
                message_data = value['messages'][0]
                
                # -------------------------------------------------------------
                # 🕵️‍♂️ DEBUGGER DE ID (RASTREIO DO ERRO)
                # -------------------------------------------------------------
                raw_id = value['metadata']['phone_number_id']
                phone_number_id = str(raw_id).strip() # Limpa espaços
                
                logging.info(f"📨 DEBUG META: Recebi ID '{phone_number_id}'")
                
                # Busca Barbearia com o ID limpo
                barbearia = Barbearia.query.filter_by(meta_phone_number_id=phone_number_id).first()
                
                if not barbearia:
                    logging.error(f"❌ ERRO CRÍTICO: ID '{phone_number_id}' não encontrado no banco!")
                    return jsonify({"status": "ignored_id_not_found"}), 200
                
                logging.info(f"✅ Loja Encontrada: {barbearia.nome_fantasia} (ID: {barbearia.id})")
                # -------------------------------------------------------------

                # 🔥 CORREÇÃO DE ASSINATURA + DEBUG
                status_str = str(barbearia.status_assinatura).lower()
                data_validade = barbearia.assinatura_expira_em
                agora = datetime.now()
                
                # Regra: Se está 'Ativa' (manual) OU se tem data futura, libera.
                # O admin agora corrige a data ao salvar, então isso deve funcionar.
                assinatura_ok = False
                
                if status_str in ['ativa', 'teste']:
                    assinatura_ok = True
                elif data_validade and data_validade > agora:
                    assinatura_ok = True
                
                if not assinatura_ok:
                    logging.warning(f"🚫 BLOQUEIO: Assinatura '{barbearia.nome_fantasia}' expirada. Status: {status_str}, Venceu: {data_validade}")
                    return jsonify({"status": "inactive"}), 200

                remetente = message_data['from']
                msg_type = message_data.get('type')
                
                # Marcar como lido
                message_id = message_data.get('id')
                if message_id:
                    threading.Thread(target=marcar_como_lido, args=(message_id, barbearia)).start()
                
                logging.info(f"✅ Mensagem ({msg_type}) autorizada para IA.")
                
                # TEXTO
                if msg_type == 'text':
                    mensagem_recebida = message_data['text']['body']
                    resposta_ia = ai_service.processar_ia_gemini(
                        user_message=mensagem_recebida,
                        barbearia_id=barbearia.id,
                        cliente_whatsapp=remetente
                    )
                    if resposta_ia:
                        enviar_mensagem_whatsapp_meta(remetente, resposta_ia, barbearia)
                
                # ÁUDIO
                elif msg_type == 'audio':
                    audio_id = message_data['audio']['id']
                    # Captura o app real para passar para a thread
                    app_real = current_app._get_current_object()
                    threading.Thread(
                        target=processar_audio_background,
                        args=(
                            audio_id, 
                            remetente, 
                            barbearia.meta_access_token, 
                            barbearia.meta_phone_number_id,
                            barbearia.id,
                            app_real
                        )
                    ).start()

                return jsonify({"status": "success"}), 200
            
            else:
                return jsonify({"status": "ignored_no_message"}), 200
        
        except Exception as e:
            logging.error(f"❌ Erro Webhook: {e}", exc_info=True)
            return jsonify({"status": "error"}), 500
    
    else:
        return "Método não permitido", 405

# ============================================
# ⚙️ ROTA DE CONFIGURAÇÕES (ATUALIZADA)
# ============================================
@bp.route('/configuracoes', methods=['GET', 'POST'])
@login_required
def configuracoes():
    # Segurança: Apenas quem tem barbearia pode acessar
    if not current_user.barbearia:
        flash('Você precisa estar vinculado a uma loja para acessar as configurações.', 'warning')
        return redirect(url_for('main.agenda'))
    
    barbearia = current_user.barbearia

    if request.method == 'POST':
        try:
            # 1. Captura dados de texto
            barbearia.horario_abertura = request.form.get('horario_abertura')
            barbearia.horario_fechamento = request.form.get('horario_fechamento')
            barbearia.horario_fechamento_sabado = request.form.get('horario_fechamento_sabado') # <--- NOVO
            barbearia.dias_funcionamento = request.form.get('dias_funcionamento')
            barbearia.cor_primaria = request.form.get('cor_primaria')
            barbearia.emojis_sistema = request.form.get('emojis_sistema')

            # Limpa telefone
            raw_tel = request.form.get('telefone_admin')
            if raw_tel:
                barbearia.telefone_admin = ''.join(filter(str.isdigit, raw_tel))

            # 2. LÓGICA DE UPLOAD DA FOTO (NOVA E SEGURA) 📸
            arquivo = request.files.get('arquivo_tabela')
            if arquivo and arquivo.filename != '':
                # Define pasta de salvamento (Render Disk)
                pasta_uploads = os.path.join(current_app.root_path, 'static', 'uploads')
                os.makedirs(pasta_uploads, exist_ok=True)
                
                # RENOMEIA USANDO O ID DA BARBEARIA (Segurança)
                extensao = os.path.splitext(arquivo.filename)[1] # ex: .jpg
                if not extensao: extensao = '.jpg'
                
                nome_seguro = f"tabela_{barbearia.id}{extensao}" # Ex: tabela_1.jpg
                
                caminho_completo = os.path.join(pasta_uploads, nome_seguro)
                arquivo.save(caminho_completo)
                
                # Gera o Link Completo
                # request.host_url retorna algo como "https://meuapp.onrender.com/"
                url_base = request.host_url.rstrip('/') 
                url_final = f"{url_base}/static/uploads/{nome_seguro}"
                
                barbearia.url_tabela_precos = url_final

            db.session.commit()
            flash('✅ Configurações salvas com sucesso!', 'success')
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Erro ao salvar configurações: {e}", exc_info=True)
            flash(f'Erro ao salvar: {str(e)}', 'danger')
            
        return redirect(url_for('main.configuracoes'))

    return render_template('configuracoes.html', barbearia=barbearia)

# ============================================
# 👑 ROTAS DO SUPER ADMIN (GESTÃO DE BARBEARIAS)
# ============================================

@bp.route('/admin/barbearias', methods=['GET'])
@login_required
def admin_barbearias():
    if current_user.role != 'super_admin':
        flash('Acesso restrito.', 'danger')
        return redirect(url_for('main.login'))
    barbearias = Barbearia.query.order_by(Barbearia.id).all()
    # Garante que carrega o template correto da LISTA
    return render_template('admin_barbearias.html', barbearias=barbearias)

@bp.route('/admin/barbearia/editar/<int:barbearia_id>', methods=['GET', 'POST'])
@login_required
def admin_editar_barbearia(barbearia_id):
    # 1. Segurança
    if current_user.role != 'super_admin':
        flash('Acesso restrito.', 'danger')
        return redirect(url_for('main.login'))

    barbearia = Barbearia.query.get_or_404(barbearia_id)

    if request.method == 'POST':
        # 2. Atualiza dados da empresa
        barbearia.nome_fantasia = request.form.get('nome_fantasia')
        
        raw_tel = request.form.get('telefone_whatsapp')
        if raw_tel:
            barbearia.telefone_admin = ''.join(filter(str.isdigit, raw_tel))

        barbearia.meta_phone_number_id = request.form.get('meta_phone_number_id')
        barbearia.meta_access_token = request.form.get('meta_access_token')
        
        # ✅ AQUI ESTÁ A CORREÇÃO CRÍTICA DO STATUS E DATA ✅
        status_input = request.form.get('status_assinatura')
        
        if status_input:
            barbearia.status_assinatura = status_input
            
            # Normaliza para letras minúsculas e sem espaços
            status_clean = str(status_input).strip().lower()
            
            if status_clean == 'ativa':
                barbearia.assinatura_ativa = True
                # Se não tem data ou data é passada, renova 30 dias
                if not barbearia.assinatura_expira_em or barbearia.assinatura_expira_em < datetime.now():
                    barbearia.assinatura_expira_em = datetime.now() + timedelta(days=30)
                    flash('✅ Assinatura ativada! Validade renovada por 30 dias.', 'success')
            
            elif status_clean == 'teste':
                barbearia.assinatura_ativa = True
                if not barbearia.assinatura_expira_em:
                    barbearia.assinatura_expira_em = datetime.now() + timedelta(days=7)
                flash('✅ Modo Teste ativado (7 dias).', 'success')
            
            else:
                # SE FOR 'inativa', 'bloqueada', 'pendente', etc.
                barbearia.assinatura_ativa = False
                barbearia.assinatura_expira_em = None # Remove a data para sumir a faixa verde
                flash('🚫 Assinatura DESATIVADA. O acesso foi revogado.', 'warning')

        # 3. Troca de Senha
        nova_senha = request.form.get('nova_senha_admin')
        if nova_senha and nova_senha.strip():
            dono = User.query.filter_by(barbearia_id=barbearia.id).first()
            if dono:
                dono.set_password(nova_senha)
                flash(f'🔑 Senha do cliente alterada para: {nova_senha}', 'success')

        # 4. Upload Tabela
        arquivo = request.files.get('arquivo_tabela_admin')
        if arquivo and arquivo.filename != '':
            pasta_uploads = os.path.join(current_app.root_path, 'static', 'uploads')
            os.makedirs(pasta_uploads, exist_ok=True)
            
            extensao = os.path.splitext(arquivo.filename)[1] or '.jpg'
            nome_seguro = f"tabela_{barbearia.id}{extensao}"
            
            caminho_completo = os.path.join(pasta_uploads, nome_seguro)
            arquivo.save(caminho_completo)
            
            url_base = request.host_url.rstrip('/') 
            url_final = f"{url_base}/static/uploads/{nome_seguro}"
            barbearia.url_tabela_precos = url_final

        db.session.commit()
        if not (nova_senha and nova_senha.strip()):
             flash('✅ Dados atualizados com sucesso!', 'success')

        return redirect(url_for('main.admin_barbearias'))

    return render_template('editar_barbearia.html', barbearia=barbearia)

# ============================================
# 💳 PAGAMENTOS (IMPLEMENTAÇÃO COMPLETA MERCADO PAGO)
# ============================================

# --- ROTA: LISTAR PLANOS ---
@bp.route('/assinatura/planos')
@login_required
def planos():
    """Exibe página de escolha de planos"""
    try:
        # Buscar todos os planos ativos
        lista_planos = Plano.query.filter_by(ativo=True).order_by(Plano.preco_mensal).all()
        
        # Buscar barbearia do usuário
        barbearia = Barbearia.query.filter_by(id=current_user.barbearia_id).first()
        
        return render_template(
            'assinatura/planos.html',
            planos=lista_planos,
            barbearia=barbearia
        )
    except Exception as e:
        logging.error(f"Erro ao carregar planos: {e}", exc_info=True)
        flash('Erro ao carregar planos. Tente novamente.', 'danger')
        return redirect(url_for('main.agenda')) # Redireciona para agenda se falhar

# --- ROTA: ASSINAR PLANO ---
# ATENÇÃO: Se seu HTML chamar 'assinaturas.assinar', mude para 'main.assinar'
@bp.route('/assinatura/assinar/<int:plano_id>', methods=['POST'])
@login_required
def assinar_plano(plano_id):
    """Processar assinatura de plano"""
    if not MP_AVAILABLE or not mercadopago_service:
        flash('Sistema de pagamento indisponível.', 'danger')
        return redirect(url_for('main.planos'))

    try:
        # Buscar plano
        plano = Plano.query.get_or_404(plano_id)
        
        if not plano.ativo:
            flash('Este plano não está mais disponível.', 'warning')
            return redirect(url_for('main.planos'))
        
        # Buscar barbearia do usuário
        barbearia = Barbearia.query.filter_by(id=current_user.barbearia_id).first()
        
        if not barbearia:
            flash('Erro: Barbearia não encontrada.', 'danger')
            return redirect(url_for('main.planos'))
        
        logging.info(f"📝 Processando assinatura do plano {plano.nome} para {barbearia.nome_fantasia}")
        
        # Cria pagamento único
        resultado = mercadopago_service.criar_pagamento(barbearia, plano, current_user.email)
        
        if not resultado.get("success"):
            logging.error(f"❌ Erro ao criar pagamento: {resultado.get('error')}")
            flash('Erro ao processar pagamento. Tente novamente.', 'danger')
            return redirect(url_for('main.planos'))
        
        # Redirecionar direto para Mercado Pago usando init_point
        init_point = resultado.get("init_point")
        preference_id = resultado.get("preference_id")
        
        if init_point:
            logging.info(f"🚀 Redirecionando para Mercado Pago: {init_point}")
            logging.info(f"   Preference ID: {preference_id}")
            return redirect(init_point)
        else:
            logging.error(f"❌ Init point não encontrado na resposta: {resultado}")
            flash('Erro ao gerar link de pagamento. Tente novamente.', 'danger')
            return redirect(url_for('main.planos'))
            
    except Exception as e:
        logging.error(f"❌ Erro no processo de assinatura: {e}", exc_info=True)
        flash('Erro ao processar assinatura. Tente novamente.', 'danger')
        return redirect(url_for('main.planos'))

# --- ROTA: RETORNO DO MERCADO PAGO ---
@bp.route('/assinatura/retorno')
def retorno():
    """Página de retorno após pagamento no Mercado Pago"""
    status = request.args.get('status', 'pending')
    
    if status == 'success':
        flash('Pagamento aprovado! Sua assinatura foi ativada.', 'success')
    elif status == 'pending':
        flash('Pagamento pendente. Aguardando confirmação.', 'warning')
    else:
        flash('Pagamento não aprovado. Tente novamente.', 'danger')
    
    return redirect(url_for('main.agenda')) # Volta para agenda/dashboard

# --- ROTA: WEBHOOK DO MERCADO PAGO ---
@bp.route('/assinatura/webhook', methods=['POST'])
def webhook_mp_pagamento():
    """Recebe notificações do Mercado Pago sobre pagamentos"""
    if not MP_AVAILABLE or not mercadopago_service:
        return {'status': 'error', 'message': 'MP service unavailable'}, 503

    try:
        data = request.get_json() or {}
        # logging.info(f"📥 Webhook recebido do Mercado Pago: {data}")
        
        # Verificar tipo de notificação
        topic = data.get('topic') or data.get('type')
        
        # LOG PARA DIAGNOSTICO: Se for apenas um pedido (antes de pagar), loga e retorna OK
        if topic == 'merchant_order':
            logging.info(f"📦 Pedido recebido (merchant_order). Aguardando pagamento...")
            return jsonify(status="ok"), 200

        if topic == 'payment' or str(topic) == 'payment':
            # Pega o ID de várias formas possíveis
            payment_id = data.get('data', {}).get('id') or data.get('id') or request.args.get('id') or request.args.get('data.id')
            
            if payment_id:
                logging.info(f"💳 Processando pagamento ID: {payment_id}")
                
                # Consultar pagamento no Mercado Pago
                resultado = mercadopago_service.consultar_pagamento(payment_id)
                
                if resultado.get("success"):
                    payment_data = resultado.get("data")
                    status = payment_data.get("status")
                    external_reference = payment_data.get("external_reference")
                    
                    logging.info(f"✅ Pagamento ID {payment_id} - Status: {status}")
                    
                    # Se pagamento aprovado, ativar barbearia
                    if status == 'approved':
                        # Extrair barbearia_id do external_reference
                        # Formato esperado no service: "barbearia_{id}_plano_{id}"
                        if external_reference:
                            try:
                                parts = external_reference.split('_')
                                # parts[0] = "barbearia"
                                barbearia_id = int(parts[1])
                                # parts[2] = "plano"
                                plano_id = int(parts[3])
                                
                                barbearia = Barbearia.query.get(barbearia_id)
                                plano = Plano.query.get(plano_id)
                                
                                if barbearia and plano:
                                    # ✅ ATIVAR ASSINATURA
                                    barbearia.assinatura_ativa = True
                                    barbearia.status_assinatura = 'ativa'
                                    # Adiciona 30 dias a partir de agora
                                    barbearia.assinatura_expira_em = datetime.now() + timedelta(days=30)
                                    
                                    db.session.commit()
                                    
                                    logging.info(f"🎉 BARBEARIA {barbearia.nome_fantasia} ATIVADA VIA WEBHOOK!")
                                    logging.info(f"   - Assinatura ativa: {barbearia.assinatura_ativa}")
                                    logging.info(f"   - Status: {barbearia.status_assinatura}")
                                    logging.info(f"   - Expira em: {barbearia.assinatura_expira_em}")
                                else:
                                    logging.error(f"❌ Barbearia ou plano não encontrado: barbearia_id={barbearia_id}, plano_id={plano_id}")
                            except (ValueError, IndexError) as e:
                                logging.error(f"❌ Erro ao processar external_reference '{external_reference}': {e}")
                        else:
                            logging.warning(f"⚠️ External reference não encontrado no pagamento {payment_id}")
                else:
                    logging.error(f"❌ Erro ao consultar pagamento {payment_id}: {resultado.get('error')}")
        
        return {'status': 'ok'}, 200
        
    except Exception as e:
        logging.error(f"❌ Erro ao processar webhook MP: {e}", exc_info=True)
        return {'status': 'error', 'message': str(e)}, 500

# --- ROTA: CANCELAR ASSINATURA ---
@bp.route('/assinatura/cancelar', methods=['POST'])
@login_required
def cancelar_assinatura():
    """Cancelar assinatura atual"""
    try:
        barbearia = Barbearia.query.filter_by(id=current_user.barbearia_id).first()
        
        if not barbearia:
            flash('Erro: Barbearia não encontrada.', 'danger')
            return redirect(url_for('main.agenda'))
        
        if not barbearia.assinatura_ativa:
            flash('Você não possui assinatura ativa.', 'warning')
            return redirect(url_for('main.agenda'))
        
        # Desativar assinatura
        barbearia.assinatura_ativa = False
        barbearia.status_assinatura = 'inativa'
        barbearia.assinatura_expira_em = None
        
        db.session.commit()
        
        logging.info(f"🚫 Assinatura cancelada para {barbearia.nome_fantasia}")
        flash('Assinatura cancelada com sucesso.', 'success')
        
        return redirect(url_for('main.agenda'))
        
    except Exception as e:
        logging.error(f"Erro ao cancelar assinatura: {e}", exc_info=True)
        flash('Erro ao cancelar assinatura. Tente novamente.', 'danger')
        return redirect(url_for('main.agenda'))


# ============================================
# 🔒 ROTAS PERIGOSAS - PROTEGIDAS
# ============================================

@bp.route('/admin/reset-database/<secret_key>')
def reset_database(secret_key):
    dev_route_required()
    
    expected_key = os.getenv('RESET_DB_KEY')
    if not expected_key or secret_key != expected_key:
        abort(404)
    
    try:
        logging.info("Iniciando o reset do banco de dados via rota segura...")
        reset_database_logic()
        return "Banco de dados recriado com sucesso!", 200
    except Exception as e:
        return f"Ocorreu um erro: {str(e)}", 500
