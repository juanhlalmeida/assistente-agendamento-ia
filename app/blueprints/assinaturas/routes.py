def processar_atualizacao_assinatura(preapproval_id):
    """Atualiza status da assinatura e ATIVA a barbearia automaticamente"""
    try:
        # Consultar no Mercado Pago
        resultado = mercadopago_service.consultar_assinatura(preapproval_id)
        
        if resultado["success"]:
            mp_data = resultado["data"]
            
            # Buscar assinatura no banco
            assinatura = Assinatura.query.filter_by(mp_preapproval_id=preapproval_id).first()
            
            if assinatura:
                # Atualizar status
                assinatura.status = mp_data.get('status', 'pending')
                assinatura.mp_payer_id = mp_data.get('payer_id')
                
                # ✅ AUTOMAÇÃO: Se status = authorized, ATIVA A BARBEARIA
                if assinatura.status == 'authorized':
                    assinatura.barbearia.assinatura_ativa = True
                    
                    # Calcula data de expiração (1 mês a partir de agora)
                    if 'next_payment_date' in mp_data:
                        assinatura.barbearia.assinatura_expira_em = datetime.fromisoformat(
                            mp_data['next_payment_date']
                        )
                    else:
                        # Se não tiver, calcula 30 dias
                        assinatura.barbearia.assinatura_expira_em = datetime.now() + timedelta(days=30)
                    
                    logging.info(f"🎉 BARBEARIA {assinatura.barbearia.id} ATIVADA AUTOMATICAMENTE!")
                
                # ❌ AUTOMAÇÃO: Se cancelado/pausado, DESATIVA
                elif assinatura.status in ['cancelled', 'paused']:
                    assinatura.barbearia.assinatura_ativa = False
                    logging.warning(f"⚠️ Barbearia {assinatura.barbearia.id} DESATIVADA (status: {assinatura.status})")
                
                db.session.commit()
                logging.info(f"✅ Assinatura {preapproval_id} atualizada para: {assinatura.status}")
                
    except Exception as e:
        logging.error(f"Erro ao processar assinatura: {e}", exc_info=True)
