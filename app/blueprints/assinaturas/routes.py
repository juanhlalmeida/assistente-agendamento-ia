# app/blueprints/assinaturas/routes.py

from flask import render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from app.blueprints.assinaturas import bp
from app.models.tables import Barbearia, Plano, Assinatura, Pagamento
from app.extensions import db
from app.services.mercadopago_service import mercadopago_service
from datetime import datetime
import logging

@bp.route('/planos')
@login_required
def listar_planos():
    """Página com planos disponíveis"""
    planos = Plano.query.filter_by(ativo=True).all()
    barbearia = Barbearia.query.get(current_user.barbearia_id)
    
    return render_template('assinatura/planos.html', 
                         planos=planos, 
                         barbearia=barbearia)


@bp.route('/assinar/<int:plano_id>', methods=['POST'])
@login_required
def assinar(plano_id):
    """Iniciar processo de assinatura"""
    try:
        plano = Plano.query.get_or_404(plano_id)
        barbearia = Barbearia.query.get(current_user.barbearia_id)
        
        email_pagador = request.form.get('email', current_user.email)
        
        resultado = mercadopago_service.criar_assinatura(barbearia, plano, email_pagador)
        
        if resultado["success"]:
            nova_assinatura = Assinatura(
                barbearia_id=barbearia.id,
                plano_id=plano.id,
                mp_preapproval_id=resultado["preapproval_id"],
                status='pending'
            )
            db.session.add(nova_assinatura)
            db.session.commit()
            
            return redirect(resultado["init_point"])
        else:
            flash("Erro ao criar assinatura. Tente novamente.", "danger")
            return redirect(url_for('assinaturas.listar_planos'))
            
    except Exception as e:
        logging.error(f"Erro em assinar: {e}", exc_info=True)
        flash("Erro ao processar assinatura.", "danger")
        return redirect(url_for('assinaturas.listar_planos'))


@bp.route('/retorno')
def retorno():
    """Página de retorno após pagamento"""
    preapproval_id = request.args.get('preapproval_id')
    status = request.args.get('status')
    
    if preapproval_id:
        assinatura = Assinatura.query.filter_by(mp_preapproval_id=preapproval_id).first()
        
        if assinatura:
            return render_template('assinatura/retorno.html',
                                 assinatura=assinatura,
                                 status=status)
    
    return redirect(url_for('main.dashboard'))


@bp.route('/webhook', methods=['POST'])
def webhook():
    """Recebe notificações do Mercado Pago"""
    try:
        data = request.get_json()
        logging.info(f"📨 Webhook MP recebido: {data}")
        
        topic = data.get('type') or data.get('topic')
        
        if topic == 'subscription_preapproval':
            preapproval_id = data['data']['id']
            processar_atualizacao_assinatura(preapproval_id)
        
        elif topic == 'subscription_authorized_payment':
            payment_id = data['data']['id']
            logging.info(f"💰 Pagamento recebido: {payment_id}")
        
        return jsonify({"status": "ok"}), 200
        
    except Exception as e:
        logging.error(f"Erro no webhook: {e}", exc_info=True)
        return jsonify({"status": "error"}), 200


def processar_atualizacao_assinatura(preapproval_id):
    """Atualiza status da assinatura"""
    try:
        resultado = mercadopago_service.consultar_assinatura(preapproval_id)
        
        if resultado["success"]:
            mp_data = resultado["data"]
            
            assinatura = Assinatura.query.filter_by(mp_preapproval_id=preapproval_id).first()
            
            if assinatura:
                assinatura.status = mp_data.get('status', 'pending')
                assinatura.mp_payer_id = mp_data.get('payer_id')
                
                if assinatura.status == 'authorized':
                    assinatura.barbearia.assinatura_ativa = True
                    assinatura.barbearia.assinatura_expira_em = datetime.fromisoformat(
                        mp_data['auto_recurring']['end_date']
                    )
                
                elif assinatura.status in ['cancelled', 'paused']:
                    assinatura.barbearia.assinatura_ativa = False
                
                db.session.commit()
                logging.info(f"✅ Assinatura {preapproval_id} atualizada: {assinatura.status}")
                
    except Exception as e:
        logging.error(f"Erro ao processar assinatura: {e}", exc_info=True)

