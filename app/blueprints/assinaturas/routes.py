# app/blueprints/assinaturas/routes.py

import logging
from datetime import datetime, timedelta
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_required, current_user
from app.models.tables import Plano, Barbearia, Assinatura
from app.extensions import db
from app.services.mercadopago_service import mercadopago_service

bp = Blueprint('assinaturas', __name__, url_prefix='/assinatura')

logging.basicConfig(level=logging.INFO)

# --- ROTA: LISTAR PLANOS ---
@bp.route('/planos')
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
        return redirect(url_for('dashboard.index'))

# --- ROTA: ASSINAR PLANO ---
@bp.route('/assinar/<int:plano_id>', methods=['POST'])
@login_required
def assinar(plano_id):
    """Processar assinatura de plano"""
    try:
        # Buscar plano
        plano = Plano.query.get_or_404(plano_id)
        
        if not plano.ativo:
            flash('Este plano não está mais disponível.', 'warning')
            return redirect(url_for('assinaturas.planos'))
        
        # Buscar barbearia do usuário
        barbearia = Barbearia.query.filter_by(id=current_user.barbearia_id).first()
        
        if not barbearia:
            flash('Erro: Barbearia não encontrada.', 'danger')
            return redirect(url_for('assinaturas.planos'))
        
        logging.info(f"📝 Processando assinatura do plano {plano.nome} para {barbearia.nome_fantasia}")
        
        # ✅ CORRIGIDO: Criar pagamento único (não mais assinatura recorrente)
        resultado = mercadopago_service.criar_pagamento(barbearia, plano, current_user.email)
        
        if not resultado.get("success"):
            logging.error(f"❌ Erro ao criar pagamento: {resultado.get('error')}")
            flash('Erro ao processar pagamento. Tente novamente.', 'danger')
            return redirect(url_for('assinaturas.planos'))
        
        # ✅ CORRIGIDO: Redirecionar direto para Mercado Pago usando init_point
        init_point = resultado.get("init_point")
        preference_id = resultado.get("preference_id")
        
        if init_point:
            logging.info(f"🚀 Redirecionando para Mercado Pago: {init_point}")
            logging.info(f"   Preference ID: {preference_id}")
            return redirect(init_point)
        else:
            logging.error(f"❌ Init point não encontrado na resposta: {resultado}")
            flash('Erro ao gerar link de pagamento. Tente novamente.', 'danger')
            return redirect(url_for('assinaturas.planos'))
            
    except Exception as e:
        logging.error(f"❌ Erro no processo de assinatura: {e}", exc_info=True)
        flash('Erro ao processar assinatura. Tente novamente.', 'danger')
        return redirect(url_for('assinaturas.planos'))

# --- ROTA: RETORNO DO MERCADO PAGO ---
@bp.route('/retorno')
def retorno():
    """Página de retorno após pagamento no Mercado Pago"""
    status = request.args.get('status', 'pending')
    
    if status == 'success':
        flash('Pagamento aprovado! Sua assinatura foi ativada.', 'success')
    elif status == 'pending':
        flash('Pagamento pendente. Aguardando confirmação.', 'warning')
    else:
        flash('Pagamento não aprovado. Tente novamente.', 'danger')
    
    return redirect(url_for('dashboard.index'))

# --- ROTA: WEBHOOK DO MERCADO PAGO ---
@bp.route('/webhook', methods=['POST'])
def webhook():
    """Recebe notificações do Mercado Pago sobre pagamentos"""
    try:
        data = request.get_json()
        logging.info(f"📥 Webhook recebido do Mercado Pago: {data}")
        
        # Verificar tipo de notificação
        topic = data.get('topic') or data.get('type')
        
        if topic == 'payment':
            payment_id = data.get('data', {}).get('id') or data.get('id')
            
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
                        # Formato: "barbearia_{id}_plano_{id}"
                        if external_reference:
                            try:
                                parts = external_reference.split('_')
                                barbearia_id = int(parts[1])
                                plano_id = int(parts[3])
                                
                                barbearia = Barbearia.query.get(barbearia_id)
                                plano = Plano.query.get(plano_id)
                                
                                if barbearia and plano:
                                    # ✅ ATIVAR ASSINATURA
                                    barbearia.assinatura_ativa = True
                                    barbearia.status_assinatura = 'ativa'
                                    barbearia.assinatura_expira_em = datetime.now() + timedelta(days=30)
                                    
                                    db.session.commit()
                                    
                                    logging.info(f"🎉 BARBEARIA {barbearia.nome_fantasia} ATIVADA!")
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
        logging.error(f"❌ Erro ao processar webhook: {e}", exc_info=True)
        return {'status': 'error', 'message': str(e)}, 500

# --- ROTA: CANCELAR ASSINATURA ---
@bp.route('/cancelar', methods=['POST'])
@login_required
def cancelar():
    """Cancelar assinatura atual"""
    try:
        barbearia = Barbearia.query.filter_by(id=current_user.barbearia_id).first()
        
        if not barbearia:
            flash('Erro: Barbearia não encontrada.', 'danger')
            return redirect(url_for('dashboard.index'))
        
        if not barbearia.assinatura_ativa:
            flash('Você não possui assinatura ativa.', 'warning')
            return redirect(url_for('dashboard.index'))
        
        # Desativar assinatura
        barbearia.assinatura_ativa = False
        barbearia.status_assinatura = 'inativa'
        barbearia.assinatura_expira_em = None
        
        db.session.commit()
        
        logging.info(f"🚫 Assinatura cancelada para {barbearia.nome_fantasia}")
        flash('Assinatura cancelada com sucesso.', 'success')
        
        return redirect(url_for('dashboard.index'))
        
    except Exception as e:
        logging.error(f"Erro ao cancelar assinatura: {e}", exc_info=True)
        flash('Erro ao cancelar assinatura. Tente novamente.', 'danger')
        return redirect(url_for('dashboard.index'))
