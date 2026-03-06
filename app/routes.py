# app/routes.py
# (VERSÃO FINAL: BASEADO NO SEU ARQUIVO ORIGINAL + ATUALIZAÇÃO DE PLANOS)

import os
import logging
import json
import requests
import threading
import urllib.parse
import pytz
from werkzeug.utils import secure_filename
from datetime import datetime, date, time, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, abort, jsonify
from sqlalchemy.orm import joinedload
from app.models.tables import ChatLog, db # Certifique-se que db está importado também
from sqlalchemy import func

# Importações de modelos (ADICIONADO Assinatura e Pagamento)
from app.models.tables import Agendamento, Profissional, Servico, User, Barbearia, Plano, Assinatura, Pagamento, ChatLog
from app.extensions import db
from sqlalchemy import text

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

def gerar_link_google_calendar(inicio: datetime, fim: datetime, titulo: str, descricao: str, local: str):
    """Gera um link clicável para adicionar ao Google Agenda"""
    # Formato exigido pelo Google: YYYYMMDDTHHMMSSZ (UTC)
    # Como estamos simplificando, vamos usar o horário local sem o 'Z' no final para ele pegar o fuso do celular da pessoa
    fmt = '%Y%m%dT%H%M%S'
    datas = f"{inicio.strftime(fmt)}/{fim.strftime(fmt)}"
    
    base_url = "https://www.google.com/calendar/render?action=TEMPLATE"
    params = {
        'text': titulo,
        'dates': datas,
        'details': descricao,
        'location': local,
        'sf': 'true',
        'output': 'xml'
    }
    return f"{base_url}&{urllib.parse.urlencode(params)}"

# ✅ Tenta importar Serviço de Pagamento (Mercado Pago)
try:
    from app.services.mercadopago_service import mercadopago_service
    MP_AVAILABLE = True
except ImportError:
    logging.warning("⚠️ O arquivo mercadopago_service.py não foi encontrado. Pagamentos desativados.")
    mercadopago_service = None
    MP_AVAILABLE = False

# ✅ Importação Direta do SDK (Para garantir funcionamento do PIX/Cartão)
try:
    import mercadopago
except ImportError:
    logging.warning("⚠️ Biblioteca 'mercadopago' não instalada.")

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
    # 1. Se o usuário já estiver logado quando entra na página de login:
    if current_user.is_authenticated:
        # Se for Super Admin, joga pro Painel Novo
        if getattr(current_user, 'role', 'admin') == 'super_admin':
            return redirect(url_for('main.admin_painel_novo'))
        # Se for Cliente comum, joga pro Dashboard normal
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
                flash('Login realizado com sucesso!', 'success')

                # ============================================================
                # 🚀 AQUI ESTÁ A MÁGICA DO REDIRECIONAMENTO INTELIGENTE
                # ============================================================
                
                # VERIFICAÇÃO 1: É o Chefe (Você)? Vai para o Centro de Comando
                if getattr(user, 'role', 'admin') == 'super_admin':
                    return redirect(url_for('main.admin_painel_novo'))
                
                # VERIFICAÇÃO 2: É Cliente? Segue o fluxo normal (Dashboard ou página anterior)
                next_page = request.args.get('next')
                if not next_page or not next_page.startswith('/'):
                    next_page = url_for('dashboard.index')
                
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

                # 1. Gerar o Link Mágico
                novo_fim = novo_inicio + timedelta(minutes=servico.duracao)
                link_agenda = gerar_link_google_calendar(
                    inicio=novo_inicio,
                    fim=novo_fim,
                    titulo=f"Agendamento: {servico.nome}",
                    descricao=f"Profissional: {profissional.nome}\nLocal: {profissional.barbearia.nome_fantasia}",
                    local=profissional.barbearia.nome_fantasia
                )

                # =================================================================
                # 📢 NOTIFICAÇÃO 1: PARA O CLIENTE (LINK CURTO 🔗)
                # =================================================================
                try:
                    barbearia_atual = Barbearia.query.get(barbearia_id_logada)
                    
                    if barbearia_atual.assinatura_ativa:
                        
                        # GERAR LINK CURTO (Aponta para a rota que criamos no Passo 1)
                        link_curto = url_for('main.redirect_gcal', agendamento_id=novo_agendamento.id, _external=True)
                        
                        # Mensagem mais limpa
                        msg_cliente = (
                            f"✅ *Agendamento Confirmado!*\n\n"
                            f"🗓 {novo_inicio.strftime('%d/%m')} às {novo_inicio.strftime('%H:%M')}\n"
                            f"💇 {servico.nome}\n\n"
                            f"📅 *Salvar na Agenda:* 👇\n{link_curto}"
                        )
                        
                        tel_destino = telefone_cliente
                        if len(tel_destino) <= 11: tel_destino = "55" + tel_destino
                        
                        enviar_mensagem_whatsapp_meta(tel_destino, msg_cliente, barbearia_atual)

                except Exception as e_client:
                    current_app.logger.error(f"Erro ao notificar cliente: {e_client}")
                
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
                    # TEXTO
                if msg_type == 'text':
                    mensagem_recebida = message_data['text']['body']
                    
                    # ✅ NOVO: ESPIÃO DO CLIENTE (SALVA O QUE ELE FALOU)
                    try:
                        log_cliente = ChatLog(
                            barbearia_id=barbearia.id,
                            cliente_telefone=remetente,
                            mensagem=mensagem_recebida,
                            tipo='cliente'
                        )
                        db.session.add(log_cliente)
                        db.session.commit()
                    except Exception as e:
                        logging.error(f"Erro ao salvar log cliente: {e}")
                    # ----------------------------------------------------

                    resposta_ia = ai_service.processar_ia_gemini(
                        user_message=mensagem_recebida,
                        barbearia_id=barbearia.id,
                        cliente_whatsapp=remetente
                    )
                    
                    if resposta_ia:
                        # ✅ NOVO: ESPIÃO DA IA (SALVA O QUE ELA RESPONDEU)
                        try:
                            log_ia = ChatLog(
                                barbearia_id=barbearia.id,
                                cliente_telefone=remetente,
                                mensagem=resposta_ia,
                                tipo='ia'
                            )
                            db.session.add(log_ia)
                            db.session.commit()
                        except Exception as e:
                            logging.error(f"Erro ao salvar log IA: {e}")
                        # ------------------------------------------------

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

            barbearia.regras_negocio = request.form.get('regras_negocio')

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
    return render_template('superadmin/barbearias.html', barbearias=barbearias)

# ============================================
# ✅ ROTA 1: EXIBIR O PAINEL DE CRIAÇÃO (GET)
# ============================================
@bp.route('/admin/barbearia/painel-criacao', methods=['GET'])
@login_required
def admin_painel_criacao():
    if getattr(current_user, 'role', 'admin') != 'super_admin':
        return redirect(url_for('main.agenda'))
    return render_template('superadmin/novo.html', barbearia=None)

# ==============================================================================
# ✅ ROTA 2: SALVAR NOVA LOJA (POST)
# ==============================================================================
@bp.route('/admin/barbearia/nova', methods=['POST'])
@login_required
def admin_nova_barbearia():
    # 1. Segurança
    if getattr(current_user, 'role', 'admin') != 'super_admin':
        flash('Acesso restrito.', 'danger')
        return redirect(url_for('main.agenda'))

    try:
        nome_fantasia = request.form.get('nome_fantasia')
        telefone_zap = request.form.get('telefone_whatsapp')
        
        # 🏨 CAPTURA O TIPO DE NEGÓCIO
        tipo_negocio = request.form.get('business_type', 'barbershop') 
        
        meta_id = request.form.get('meta_phone_number_id')
        meta_token = request.form.get('meta_access_token')
        status_assinatura = request.form.get('status_assinatura', 'inativa')
        
        h_abre = request.form.get('horario_abertura', '09:00')
        h_fecha = request.form.get('horario_fechamento', '19:00')
        h_sabado = request.form.get('horario_fechamento_sabado', '14:00')
        dias_func = request.form.get('dias_funcionamento', 'Terça a Sábado')
        cor = request.form.get('cor_primaria', '#EC4899')
        emojis = request.form.get('emojis_sistema', '🦋✨💖')
        tel_admin = request.form.get('telefone_admin')

        email_admin = request.form.get('admin_email')
        senha_admin = request.form.get('admin_senha')

        if not nome_fantasia or not telefone_zap or not email_admin or not senha_admin:
            flash('Preencha os campos obrigatórios (*)', 'warning')
            return redirect(url_for('main.admin_painel_criacao'))

        if User.query.filter_by(email=email_admin).first():
            flash('Este email de admin já está em uso.', 'danger')
            return redirect(url_for('main.admin_painel_criacao'))

        nova_loja = Barbearia(
            nome_fantasia=nome_fantasia,
            telefone_whatsapp=telefone_zap, 
            business_type=tipo_negocio, # ✅ SALVANDO
            
            meta_phone_number_id=meta_id,
            meta_access_token=meta_token,
            status_assinatura=status_assinatura,
            horario_abertura=h_abre,
            horario_fechamento=h_fecha,
            horario_fechamento_sabado=h_sabado,
            dias_funcionamento=dias_func,
            cor_primaria=cor,
            emojis_sistema=emojis,
            telefone_admin=tel_admin
        )
        
        if status_assinatura in ['ativa', 'teste']:
            nova_loja.assinatura_ativa = True
            dias = 30 if status_assinatura == 'ativa' else 7
            nova_loja.assinatura_expira_em = datetime.now() + timedelta(days=dias)
        
        db.session.add(nova_loja)
        db.session.flush()

        novo_usuario = User(
            email=email_admin,
            nome=f"Admin {nome_fantasia}",
            role='admin',
            barbearia_id=nova_loja.id 
        )
        novo_usuario.set_password(senha_admin)
        
        db.session.add(novo_usuario)
        db.session.commit()

        flash(f'✅ Loja "{nome_fantasia}" criada com sucesso! Tipo: {tipo_negocio.upper()}', 'success')
        return redirect(url_for('main.admin_barbearias'))

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Erro ao criar loja: {e}")
        flash(f'Erro ao criar: {str(e)}', 'danger')
        return redirect(url_for('main.admin_barbearias'))

# ==============================================================================
# ✅ ROTA 3: EDITAR LOJA EXISTENTE (GET e POST)
# ==============================================================================
@bp.route('/admin/barbearia/editar/<int:barbearia_id>', methods=['GET', 'POST'])
@login_required
def admin_editar_barbearia(barbearia_id):
    if getattr(current_user, 'role', 'admin') != 'super_admin':
        flash('Acesso restrito.', 'danger')
        return redirect(url_for('main.login'))

    barbearia = Barbearia.query.get_or_404(barbearia_id)

    if request.method == 'POST':
        barbearia.nome_fantasia = request.form.get('nome_fantasia')
        barbearia.regras_negocio = request.form.get('regras_negocio')
        
        # ✅ PERMITE MUDAR O TIPO NA EDIÇÃO
        barbearia.business_type = request.form.get('business_type', 'barbershop')
        
        raw_tel = request.form.get('telefone_whatsapp')
        if raw_tel:
            barbearia.telefone_admin = ''.join(filter(str.isdigit, raw_tel))

        barbearia.meta_phone_number_id = request.form.get('meta_phone_number_id')
        barbearia.meta_access_token = request.form.get('meta_access_token')
        
        status_input = request.form.get('status_assinatura')
        if status_input:
            barbearia.status_assinatura = status_input
            status_clean = str(status_input).strip().lower()
            
            if status_clean == 'ativa':
                barbearia.assinatura_ativa = True
                if not barbearia.assinatura_expira_em or barbearia.assinatura_expira_em < datetime.now():
                    barbearia.assinatura_expira_em = datetime.now() + timedelta(days=30)
                flash('✅ Assinatura ativada! Validade renovada.', 'success')
            elif status_clean == 'teste':
                barbearia.assinatura_ativa = True
                if not barbearia.assinatura_expira_em:
                    barbearia.assinatura_expira_em = datetime.now() + timedelta(days=7)
                flash('✅ Modo Teste ativado (7 dias).', 'success')
            else:
                barbearia.assinatura_ativa = False
                barbearia.assinatura_expira_em = None
                flash('🚫 Assinatura DESATIVADA.', 'warning')

        nova_senha = request.form.get('nova_senha_admin')
        if nova_senha and nova_senha.strip():
            dono = User.query.filter_by(barbearia_id=barbearia.id).first()
            if dono:
                dono.set_password(nova_senha)
                flash(f'🔑 Senha do cliente alterada.', 'success')

        arquivo = request.files.get('arquivo_tabela_admin')
        if arquivo and arquivo.filename != '':
            pasta_uploads = os.path.join(current_app.root_path, 'static', 'uploads')
            os.makedirs(pasta_uploads, exist_ok=True)
            
            extensao = os.path.splitext(arquivo.filename)[1] or '.jpg'
            nome_seguro = f"tabela_{barbearia.id}{extensao}"
            
            caminho_completo = os.path.join(pasta_uploads, nome_seguro)
            arquivo.save(caminho_completo)
            
            url_base = request.host_url.rstrip('/') 
            barbearia.url_tabela_precos = f"{url_base}/static/uploads/{nome_seguro}"

        db.session.commit()
        if not (nova_senha and nova_senha.strip()):
             flash('✅ Dados atualizados com sucesso!', 'success')

        return redirect(url_for('main.admin_barbearias'))

    return render_template('superadmin/novo.html', barbearia=barbearia)

# ============================================
# 💳 PAGAMENTOS (MERCADO PAGO) - INTEGRADO
# ============================================

@bp.route('/assinatura/planos')
@login_required
def listar_planos():
    """Lista os planos disponíveis"""
    planos = Plano.query.filter_by(ativo=True).order_by(Plano.preco_mensal).all()
    return render_template('assinatura/planos.html', planos=planos, barbearia=current_user.barbearia)

@bp.route('/assinatura/assinar/<int:plano_id>', methods=['POST'])
@login_required
def assinar_plano(plano_id):
    """Cria a preferência de pagamento"""
    if not MP_AVAILABLE:
        flash('Erro: Biblioteca Mercado Pago não instalada.', 'danger')
        return redirect(url_for('main.listar_planos'))

    try:
        # 1. Configura SDK (Pega o token MP_ACCESS_TOKEN do ambiente)
        token = os.getenv('MP_ACCESS_TOKEN')
        if not token:
            flash('Erro: Token do Mercado Pago não configurado.', 'danger')
            return redirect(url_for('main.listar_planos'))
            
        sdk = mercadopago.SDK(token)
        
        # 2. Busca dados
        plano = Plano.query.get_or_404(plano_id)
        barbearia = current_user.barbearia
        email_cliente = current_user.email
        
        logging.info(f"💳 Iniciando Pagamento: {barbearia.nome_fantasia} - Plano {plano.nome}")

        # 3. Cria Preferência (Checkout Pro)
        preference_data = {
            "items": [
                {
                    "id": str(plano.id),
                    "title": f"Assinatura - {plano.nome}",
                    "quantity": 1,
                    "currency_id": "BRL",
                    "unit_price": float(plano.preco_mensal)
                }
            ],
            "payer": {
                "email": email_cliente,
            },
            "back_urls": {
                "success": url_for('main.retorno_mp', _external=True) + "?status=success",
                "failure": url_for('main.retorno_mp', _external=True) + "?status=failure",
                "pending": url_for('main.retorno_mp', _external=True) + "?status=pending"
            },
            "auto_return": "approved",
            "external_reference": f"barbearia_{barbearia.id}_plano_{plano.id}",
            "payment_methods": {
                "excluded_payment_types": [], # Vazio = Aceita tudo (PIX, Cartão, Boleto)
                "installments": 1
            },
            "statement_descriptor": "BARBER APP"
        }

        preference_response = sdk.preference().create(preference_data)
        preference = preference_response["response"]
        
        # 4. Redireciona
        if "init_point" in preference:
            logging.info(f"🚀 Link Gerado: {preference['init_point']}")
            return redirect(preference["init_point"])
        else:
            logging.error(f"❌ Erro MP: {preference}")
            flash('Erro ao comunicar com Mercado Pago.', 'danger')
            return redirect(url_for('main.listar_planos'))

    except Exception as e:
        logging.error(f"❌ Erro Crítico Assinatura: {e}", exc_info=True)
        flash('Erro interno ao processar pagamento.', 'danger')
        return redirect(url_for('main.listar_planos'))

@bp.route('/assinatura/retorno')
def retorno_mp():
    st = request.args.get('status', 'pending')
    if st == 'success': flash('Pagamento recebido! Sua assinatura será ativada em instantes.', 'success')
    elif st == 'failure': flash('Pagamento recusado.', 'danger')
    return redirect(url_for('dashboard.index'))

@bp.route('/assinatura/webhook', methods=['POST'])
def webhook_mp():
    """Webhook do Mercado Pago (Com Logs de Erro Detalhados)"""
    try:
        data = request.get_json() or {}
        # Captura ID e Tópico
        p_id = request.args.get('id') or request.args.get('data.id')
        if not p_id and data: p_id = data.get('data', {}).get('id')
        
        topic = request.args.get('topic') or data.get('type')
        
        logging.info(f"🔔 Webhook MP Recebido: Tópico={topic}, ID={p_id}")

        # Se for merchant_order, apenas logamos e damos OK
        if topic == 'merchant_order':
            logging.info(f"📦 Pedido recebido (merchant_order). Aguardando pagamento...")
            return jsonify(status="ok"), 200
        
        # Se for pagamento, processamos
        if (topic == 'payment' or str(topic) == 'payment') and p_id:
            token = os.getenv('MP_ACCESS_TOKEN')
            if not token: return jsonify(error="Token missing"), 500
            
            sdk = mercadopago.SDK(token)
            pay_info = sdk.payment().get(p_id)
            
            if pay_info["status"] == 200:
                payment = pay_info["response"]
                status = payment.get("status")
                ref = payment.get("external_reference")
                
                logging.info(f"💳 Status Pagamento {p_id}: {status} | Ref: {ref}")
                
                if status == 'approved' and ref:
                    try:
                        # Ref: barbearia_{id}_plano_{id}
                        parts = ref.split('_')
                        bid = int(parts[1])
                        
                        b = Barbearia.query.get(bid)
                        if b:
                            b.assinatura_ativa = True
                            b.status_assinatura = 'ativa'
                            # Renova por 30 dias
                            b.assinatura_expira_em = datetime.now() + timedelta(days=30)
                            db.session.commit()
                            logging.info(f"✅ SUCESSO: Barbearia {bid} ativada via Webhook!")
                    except Exception as ex:
                        logging.error(f"Erro ao ativar: {ex}")
            
        return jsonify(status="ok"), 200
        
    except Exception as e:
        logging.error(f"Erro Webhook MP: {e}")
        return jsonify(status="error"), 500

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
# 🛠️ ROTA DE ATUALIZAÇÃO DE PLANOS (Executar 1x)
# ============================================
@bp.route('/admin/atualizar-planos')
@login_required
def atualizar_planos_db():
    # Segurança: Só Super Admin pode rodar
    if current_user.role != 'super_admin': 
        abort(403)
    
    try:
        # 1. Limpa planos antigos (Remove o de R$ 0,50 e outros)
        try:
            db.session.query(Pagamento).delete()
            db.session.query(Assinatura).delete()
            db.session.query(Plano).delete()
            db.session.commit()
        except:
            db.session.rollback()
            return "Erro ao limpar banco. Resete o banco primeiro em /admin/reset-database/<key>.", 500
        
        # 2. Cria os Novos Planos
        novos_planos = [
            Plano(
                nome="Plano Básico",
                descricao="Ideal para quem trabalha sozinho. Agenda IA + Link Exclusivo.",
                preco_mensal=1.00, # ⚠️ VALOR DE TESTE: 1 Real
                max_profissionais=1,
                max_servicos=15,
                tem_ia=True,
                tem_notificacao_whatsapp=False,
                tem_ia_avancada=False,
                tem_google_agenda=False,
                tem_espelhamento=False,
                tem_suporte_prioritario=False,
                ativo=True
            ),
            Plano(
                nome="Plano Premium",
                descricao="Automação completa. IA entende áudio, envia imagens e notificações.",
                preco_mensal=89.90,
                max_profissionais=3,
                max_servicos=40,
                tem_ia=True,
                tem_notificacao_whatsapp=True,
                tem_ia_avancada=True,
                tem_google_agenda=False,
                tem_espelhamento=False,
                tem_suporte_prioritario=False,
                ativo=True
            ),
            Plano(
                nome="Plano Plus",
                descricao="Gestão total. Sincronização Google Agenda e Serviços Ilimitados.",
                preco_mensal=149.90,
                max_profissionais=10,
                max_servicos=999, # Ilimitado na prática
                tem_ia=True,
                tem_notificacao_whatsapp=True,
                tem_ia_avancada=True,
                tem_google_agenda=True,
                tem_espelhamento=True,
                tem_suporte_prioritario=True,
                ativo=True
            )
        ]
        
        db.session.add_all(novos_planos)
        db.session.commit()
        
        return "✅ Sucesso! Planos atualizados para: Básico (1,00), Premium (89,90) e Plus (149,90).", 200

    except Exception as e:
        db.session.rollback()
        return f"❌ Erro ao atualizar planos: {str(e)}", 500
        
        # --- ROTA DE MONITORAMENTO (ESPELHO) ---

# app/routes.py

# Certifique-se de importar 'func' do sqlalchemy lá em cima, junto com os outros imports:
# from sqlalchemy import func

# No app/routes.py (Substitua a função monitor_chat inteira)

@bp.route('/dashboard/monitor')
@login_required
def monitor_chat():
    if not current_user.barbearia_id:
        flash("Você precisa estar vinculado a uma loja para ver o chat.", "warning")
        return redirect(url_for('main.agenda'))

    # ⏱️ CONFIGURA O FUSO HORÁRIO
    sao_paulo_tz = pytz.timezone('America/Sao_Paulo')

    # 1. PEGAR LISTA DE CONTATOS (Agrupados) e IGNORAR VAZIOS/FANTASMAS
    subquery = db.session.query(
        ChatLog.cliente_telefone,
        func.max(ChatLog.data_hora).label('ultima_interacao')
    ).filter(
        ChatLog.barbearia_id == current_user.barbearia_id,
        ChatLog.cliente_telefone != None,
        ChatLog.cliente_telefone != ''
    ).group_by(ChatLog.cliente_telefone)\
     .order_by(func.max(ChatLog.data_hora).desc())\
     .all()

    lista_contatos = []
    
    # MÁGICA 1: Formatador de Telefone Padrão WhatsApp
    def formatar_tel(tel):
        t = ''.join(filter(str.isdigit, str(tel)))
        if len(t) == 13 and t.startswith('55'): 
            return f"+{t[:2]} ({t[2:4]}) {t[4:9]}-{t[9:]}"
        if len(t) == 12 and t.startswith('55'): # Sem o nono dígito
            return f"+{t[:2]} ({t[2:4]}) {t[4:8]}-{t[8:]}"
        if len(t) == 11: 
            return f"+55 ({t[:2]}) {t[2:7]}-{t[7:]}"
        return f"+{t}" if t else ""

    for item in subquery:
        phone = item.cliente_telefone
        telefone_formatado = formatar_tel(phone)
        display_name = telefone_formatado

        # MÁGICA 2: Busca Inteligente de Nome (Pega só os últimos 8 dígitos para não falhar)
        base_phone = phone[-8:] if len(phone) >= 8 else phone 
        cliente_conhecido = Agendamento.query.filter(
            Agendamento.barbearia_id == current_user.barbearia_id,
            Agendamento.telefone_cliente.like(f"%{base_phone}%")
        ).order_by(Agendamento.id.desc()).first()

        if cliente_conhecido and cliente_conhecido.nome_cliente:
            # Capitaliza o Primeiro e o Último nome para ficar elegante
            nome_parts = cliente_conhecido.nome_cliente.strip().split()
            display_name = nome_parts[0].capitalize()
            if len(nome_parts) > 1:
                display_name += " " + nome_parts[-1].capitalize()

        # Ajuste Fuso Horário da Lista Lateral
        hora_br = item.ultima_interacao
        if hora_br:
            hora_utc = hora_br.replace(tzinfo=pytz.utc) if hora_br.tzinfo is None else hora_br
            hora_br = hora_utc.astimezone(sao_paulo_tz)

        lista_contatos.append({
            'telefone': phone,
            'telefone_formatado': telefone_formatado, # Adicionado para o HTML
            'nome_exibicao': display_name,
            'hora': hora_br 
        })

    # 2. CARREGAR CONVERSA SELECIONADA
    telefone_selecionado = request.args.get('telefone')
    mensagens = []
    nome_selecionado = ""

    if telefone_selecionado:
        # Preenche nome e formata o topo do chat
        for c in lista_contatos:
            if c['telefone'] == telefone_selecionado:
                nome_selecionado = c['nome_exibicao']
                break
        
        if not nome_selecionado:
            nome_selecionado = formatar_tel(telefone_selecionado)

        # Busca APENAS as mensagens daquele telefone exato
        mensagens_db = ChatLog.query.filter_by(
            barbearia_id=current_user.barbearia_id,
            cliente_telefone=telefone_selecionado
        ).order_by(ChatLog.data_hora.asc()).all()

        for msg in mensagens_db:
            if msg.data_hora:
                hora_utc = msg.data_hora.replace(tzinfo=pytz.utc) if msg.data_hora.tzinfo is None else msg.data_hora
                msg.data_hora = hora_utc.astimezone(sao_paulo_tz)
            mensagens.append(msg)

    # Motor de Auto-Update Invisível
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return render_template('monitor_partial.html', msgs=mensagens)

    return render_template(
        'monitor.html', 
        contatos=lista_contatos, 
        msgs=mensagens, 
        selecionado=telefone_selecionado,
        nome_selecionado=nome_selecionado
    )

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

# ==============================================================================
# 📊 CÉREBRO FINANCEIRO (PRECISÃO GEMINI FLASH)
# ==============================================================================
@bp.route('/admin/painel-novo')
@login_required
def admin_painel_novo():
    # 1. Segurança Absoluta
    if getattr(current_user, 'role', 'admin') != 'super_admin':
        flash('Acesso restrito à diretoria.', 'danger')
        return redirect(url_for('main.agenda'))

    # 2. Métricas de Volume
    total_lojas = Barbearia.query.count()
    lojas_ativas = Barbearia.query.filter_by(assinatura_ativa=True).count()
    
    hoje = datetime.now()
    inicio_mes = datetime(hoje.year, hoje.month, 1)
    
    total_agendamentos = Agendamento.query.filter(Agendamento.data_hora >= inicio_mes).count()
    
    # 3. CONTABILIZADOR DE TOKENS (AUDITORIA DE CUSTO)
    # A IA cobra por "Token". 
    # Média da Indústria: 1 Token ≈ 4 Caracteres (Português/Inglês)
    
    # Soma caracteres que o CLIENTE enviou (Input - Mais barato)
    chars_input = db.session.query(func.sum(func.length(ChatLog.mensagem)))\
        .filter(ChatLog.data_hora >= inicio_mes, ChatLog.tipo == 'cliente').scalar() or 0
    
    # Soma caracteres que a IA respondeu (Output - Mais caro)
    chars_output = db.session.query(func.sum(func.length(ChatLog.mensagem)))\
        .filter(ChatLog.data_hora >= inicio_mes, ChatLog.tipo == 'ia').scalar() or 0
    
    # Conversão para Tokens
    tokens_input = int(chars_input / 4)
    tokens_output = int(chars_output / 4)
    total_tokens = tokens_input + tokens_output
    
    # 4. Faturamento (MRR)
    # Soma planos reais + estimativa para manuais
    mrr_real = db.session.query(func.sum(Plano.preco_mensal))\
        .join(Assinatura).join(Barbearia)\
        .filter(Barbearia.assinatura_ativa == True).scalar() or 0
    
    mrr_estimado = lojas_ativas * 89.90
    mrr_final = max(mrr_real, mrr_estimado)

    # =================================================================
    # 💰 CALCULADORA DE CUSTOS (TABELA GEMINI FLASH & META)
    # =================================================================
    DOLAR_HOJE = 6.10 
    
    # A. CUSTO META (WHATSAPP API)
    # Categoria "Utility" (Notificações de agendamento): $0.008 USD
    # As conversas de "Service" (Chat da IA) são GRÁTIS na janela de 24h.
    custo_meta_usd = total_agendamentos * 0.008
    
    # B. CUSTO IA (GEMINI FLASH - PREÇO PAY-AS-YOU-GO)
    # Tabela Oficial Google Cloud (Vertex AI / Studio):
    # Input: $0.075 por 1 Milhão de tokens
    # Output: $0.30 por 1 Milhão de tokens
    custo_input_usd = (tokens_input / 1_000_000) * 0.075
    custo_output_usd = (tokens_output / 1_000_000) * 0.30
    custo_ia_usd = custo_input_usd + custo_output_usd
    
    # C. CUSTO INFRA (RENDER)
    # Web Service ($7) + Postgres ($7) = $14.00 Fixo
    custo_render_usd = 14.00
    
    # CONSOLIDAÇÃO (EM REAIS)
    custo_variavel_brl = (custo_meta_usd + custo_ia_usd) * DOLAR_HOJE
    custo_fixo_brl = custo_render_usd * DOLAR_HOJE
    custo_total_brl = custo_fixo_brl + custo_variavel_brl
    
    lucro_liquido = mrr_final - custo_total_brl

    # Lista de Lojas para a tabela
    barbearias = Barbearia.query.order_by(Barbearia.id.desc()).all()

    return render_template(
        'superadmin/dashboard_v2.html', 
        total_lojas=total_lojas,
        lojas_ativas=lojas_ativas,
        total_agendamentos=total_agendamentos,
        # Dados de IA para o Gráfico
        total_tokens=total_tokens,
        tokens_input=tokens_input,
        tokens_output=tokens_output,
        custo_ia_brl=custo_ia_usd * DOLAR_HOJE,
        # Financeiro
        mrr=mrr_final,
        custo_total=custo_total_brl,
        lucro_liquido=lucro_liquido,
        barbearias=barbearias
    )

@bp.route('/admin/planos', methods=['GET', 'POST'])
@login_required
def admin_planos():
    # Segurança: Só Super Admin
    if getattr(current_user, 'role', 'admin') != 'super_admin':
        flash('Acesso restrito.', 'danger')
        return redirect(url_for('main.agenda'))

    if request.method == 'POST':
        try:
            plano_id = request.form.get('plano_id')
            novo_nome = request.form.get('novo_nome')
            novo_preco = request.form.get('novo_preco')
            
            plano = Plano.query.get(plano_id)
            if plano:
                if novo_nome:
                    plano.nome = novo_nome
                if novo_preco:
                    # Troca vírgula por ponto para o banco aceitar
                    plano.preco_mensal = float(novo_preco.replace(',', '.'))
                
                db.session.commit()
                flash(f'✅ Plano "{plano.nome}" atualizado com sucesso!', 'success')
            else:
                flash('❌ Plano não encontrado.', 'danger')
                
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao atualizar: {str(e)}', 'danger')
        
        return redirect(url_for('main.admin_planos'))

    # Listar Planos (Ordenados pelo preço)
    planos = Plano.query.order_by(Plano.preco_mensal.asc()).all()
    return render_template('superadmin/planos.html', planos=planos)
    
    # --- NOVO: ROTA ENCURTADORA PARA O GOOGLE CALENDAR ---
@bp.route('/gcal/<int:agendamento_id>')
def redirect_gcal(agendamento_id):
    """
    Cria o link do Google com o Emoji correto (Lash ou Barber) no título do evento.
    """
    try:
        ag = Agendamento.query.get_or_404(agendamento_id)
        
        # 1. DETECÇÃO DE TEMA (IGUAL FIZEMOS NA NOTIFICAÇÃO)
        nome_loja = ag.barbearia.nome_fantasia.lower()
        palavras_lash = ['lash', 'studio', 'cílios', 'sobrancelha', 'beleza', 'estética', 'lima', 'mulher', 'lady']
        is_lash = any(x in nome_loja for x in palavras_lash)
        
        # Define o Emoji do Título
        if is_lash:
            emoji_titulo = "🦋"
        else:
            emoji_titulo = "✂️"

        # 2. MONTAGEM DO LINK
        fmt = '%Y%m%dT%H%M%S'
        inicio = ag.data_hora
        fim = inicio + timedelta(minutes=ag.servico.duracao)
        datas = f"{inicio.strftime(fmt)}/{fim.strftime(fmt)}"
        
        base_url = "https://www.google.com/calendar/render?action=TEMPLATE"
        params = {
            # AQUI ESTÁ A MUDANÇA: O EMOJI VAI NO TÍTULO
            'text': f"{emoji_titulo} {ag.servico.nome} - {ag.barbearia.nome_fantasia}",
            'dates': datas,
            'details': f"Profissional: {ag.profissional.nome}\nCliente: {ag.nome_cliente}\nTel: {ag.telefone_cliente}",
            'location': ag.barbearia.nome_fantasia,
            'sf': 'true',
            'output': 'xml'
        }
        
        final_url = f"{base_url}&{urllib.parse.urlencode(params)}"
        return redirect(final_url)
        
    except Exception as e:
        current_app.logger.error(f"Erro no redirecionamento GCal: {e}")
        return "Erro ao gerar link da agenda."

@bp.route('/fix_db_column_v2')
def fix_db_column_v2():
    try:
        # 1. Cria a coluna 'business_type' se não existir
        # 2. Define 'barbershop' para todo mundo que já existe
        sql = text("ALTER TABLE barbearia ADD COLUMN IF NOT EXISTS business_type VARCHAR(50) DEFAULT 'barbershop';")
        db.session.execute(sql)
        
        # Opcional: Garante que ninguém fique com valor Nulo
        sql_update = text("UPDATE barbearia SET business_type = 'barbershop' WHERE business_type IS NULL;")
        db.session.execute(sql_update)
        
        db.session.commit()
        return "SUCESSO! Coluna 'business_type' criada e clientes antigos protegidos."
    except Exception as e:
        db.session.rollback()
        return f"ERRO na correção: {str(e)}"

        # ============================================
# ============================================
# 🏨 API EXCLUSIVA PARA O CALENDÁRIO DA POUSADA
# ============================================
from flask import jsonify

@bp.route('/api/reservas_calendario')
@login_required
def api_reservas_calendario():
    if not current_user.barbearia_id:
        return jsonify([])
    
    agendamentos = Agendamento.query.filter_by(barbearia_id=current_user.barbearia_id).all()
    eventos = []
    
    # Paleta de cores premium para diferenciar os quartos
    cores = ['#0ea5e9', '#8b5cf6', '#f59e0b', '#10b981', '#f43f5e', '#6366f1', '#14b8a6', '#f97316']
    
    for ag in agendamentos:
        duracao = ag.servico.duracao if ag.servico else 1440
        fim = ag.data_hora + timedelta(minutes=duracao)
        
        # Lógica inteligente: Se for menos de 12h (720 min) ou tiver 'day' no nome, é Day Use.
        is_day_use = duracao <= 720 or (ag.servico and 'day' in ag.servico.nome.lower())
        icone = '☀️' if is_day_use else '🛏️'
        tipo_texto = 'Day Use' if is_day_use else 'Diária'
        
        # Cada quarto ganha uma cor fixa baseada no ID dele
        cor_quarto = cores[ag.profissional_id % len(cores)]
        
        eventos.append({
            'id': ag.id,
            'title': f"{icone} {ag.nome_cliente}",
            'start': ag.data_hora.strftime('%Y-%m-%dT%H:%M:%S'),
            'end': fim.strftime('%Y-%m-%dT%H:%M:%S'),
            'color': cor_quarto, # Envia a cor para o calendário
            'extendedProps': {
                'quarto_id': str(ag.profissional_id),
                'quarto_nome': ag.profissional.nome,
                'telefone': ag.telefone_cliente,
                'tipo': tipo_texto,
                'checkin': ag.data_hora.strftime('%d/%m às %H:%M'),
                'checkout': fim.strftime('%d/%m às %H:%M')
            }
        })
        
    return jsonify(eventos)
