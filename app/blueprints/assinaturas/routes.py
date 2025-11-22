# app/blueprints/assinaturas/routes.py
import logging
from flask import render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from datetime import datetime, timedelta

from app.blueprints.assinaturas import bp
from app.models.tables import Plano, Assinatura, Pagamento, Barbearia
from app.extensions import db
from app.services.mercadopago_service import mercadopago_service

logging.basicConfig(level=logging.INFO)

@bp.route('/planos')
@login_required
def listar_planos():
    """Lista todos os planos disponíveis"""
    try:
        planos = Plano.query.filter_by(ativo=True).all()
        barbearia = current_user.barbearia
        
        return render_template(
            'assinatura/planos.html', 
            planos=planos,
            barbearia=barbearia
        )
    except Exception as e:
        logging.error(f"Erro ao listar planos: {e}", exc_info=True)
        flash('Erro ao carregar planos de assinatura.', 'danger')
        return redirect(url_for('dashboard.index'))

@bp.route('/assinar/<int:plano_id>', methods=['POST'])
@login_required
def assinar(plano_id):
    """Inicia processo de assinatura"""
    try:
        plano = Plano.query.get_or_404(plano_id)
        barbearia = current_user.barbearia
        
        if not barbearia:
            flash('Erro: Usuário sem barbearia associada.', 'danger')
            return redirect(url_for('assinaturas.listar_planos'))
        
        resultado = mercadopago_service.criar_assinatura(
            barbearia=barbearia,
            plano=plano,
            email_pagador=current_user.email
        )
        
        if resultado["success"]:
            nova_assinatura = Assinatura(
                barbearia_id=barbearia.id,
                plano_id=plano.id,
                mp_preapproval_id=resultado["preapproval_id"],
                status='pending'
            )
            db.session.add(nova_assinatura)
            db.session.commit()
            
            init_point = resultado.get("sandbox_init_point") or resultado.get("init_point")
            return redirect(init_point)
        else:
            logging.error(f"Erro ao criar assinatura: {resultado.get('error')}")
            flash('Erro ao processar assinatura. Tente novamente.', 'danger')
            return redirect(url_for('assinaturas.listar_planos'))
            
    except Exception as e:
        logging.error(f"Erro no processo de assinatura: {e}", exc_info=True)
        flash('Erro ao processar assinatura.', 'danger')
        return redirect(url_for('assinaturas.listar_planos'))

@bp.route('/retorno')
@login_required
def retorno():
    """Página de retorno após pagamento"""
    status = request.args.get('status')
    barbearia = current_user.barbearia
    return render_template('assinatura/retorno.html', status=status, barbearia=barbearia)

@bp.route('/webhook', methods=['POST'])
def webhook():
    """Recebe notificações do Mercado Pago"""
    try:
        data = request.get_json()
        logging.info(f"Webhook recebido: {data}")
        
        if data.get('type') == 'subscription_preapproval':
            preapproval_id = data['data']['id']
            processar_atualizacao_assinatura(preapproval_id)
        
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        logging.error(f"Erro no webhook: {e}", exc_info=True)
        return jsonify({"status": "error"}), 500

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
                    assinatura.barbearia.assinatura_expira_em = datetime.now() + timedelta(days=30)
                    logging.info(f"🎉 BARBEARIA {assinatura.barbearia.id} ATIVADA!")
                
                elif assinatura.status in ['cancelled', 'paused']:
                    assinatura.barbearia.assinatura_ativa = False
                    logging.warning(f"⚠️ Barbearia {assinatura.barbearia.id} DESATIVADA")
                
                db.session.commit()
                
    except Exception as e:
        logging.error(f"Erro ao processar assinatura: {e}", exc_info=True)
