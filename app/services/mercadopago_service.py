# app/services/mercadopago_service.py

import os
import logging
import mercadopago
from datetime import datetime, timedelta
from flask import current_app

logging.basicConfig(level=logging.INFO)

class MercadoPagoService:
    def __init__(self):
        access_token = os.getenv('MERCADOPAGO_ACCESS_TOKEN')
        if not access_token:
            logging.error("MERCADOPAGO_ACCESS_TOKEN não encontrado!")
            raise ValueError("Credenciais do Mercado Pago não configuradas")
        
        self.sdk = mercadopago.SDK(access_token)
    
    def criar_assinatura(self, barbearia, plano, email_pagador):
        """Cria assinatura recorrente no Mercado Pago"""
        try:
            data_inicio = datetime.now()
            data_fim = data_inicio + timedelta(days=365)
            
            preapproval_data = {
                "reason": f"Assinatura {plano.nome} - {barbearia.nome_fantasia}",
                "auto_recurring": {
                    "frequency": 1,
                    "frequency_type": "months",
                    "transaction_amount": plano.preco_mensal,
                    "currency_id": "BRL",
                    "start_date": data_inicio.isoformat(),
                    "end_date": data_fim.isoformat()
                },
                "back_url": f"{os.getenv('BASE_URL')}/assinatura/retorno",
                "payer_email": email_pagador,
                "status": "pending"
            }
            
            result = self.sdk.preapproval().create(preapproval_data)
            
            if result["status"] == 201:
                logging.info(f"✅ Assinatura criada: {result['response']['id']}")
                return {
                    "success": True,
                    "preapproval_id": result["response"]["id"],
                    "init_point": result["response"]["init_point"],
                    "sandbox_init_point": result["response"].get("sandbox_init_point")
                }
            else:
                logging.error(f"Erro ao criar assinatura: {result}")
                return {"success": False, "error": result}
                
        except Exception as e:
            logging.error(f"Erro no MercadoPagoService.criar_assinatura: {e}", exc_info=True)
            return {"success": False, "error": str(e)}
    
    def consultar_assinatura(self, preapproval_id):
        """Consulta status da assinatura"""
        try:
            result = self.sdk.preapproval().get(preapproval_id)
            
            if result["status"] == 200:
                return {"success": True, "data": result["response"]}
            else:
                return {"success": False, "error": result}
                
        except Exception as e:
            logging.error(f"Erro ao consultar assinatura: {e}")
            return {"success": False, "error": str(e)}
    
    def cancelar_assinatura(self, preapproval_id):
        """Cancela assinatura"""
        try:
            result = self.sdk.preapproval().update(preapproval_id, {"status": "cancelled"})
            
            if result["status"] == 200:
                logging.info(f"✅ Assinatura cancelada: {preapproval_id}")
                return {"success": True}
            else:
                return {"success": False, "error": result}
                
        except Exception as e:
            logging.error(f"Erro ao cancelar assinatura: {e}")
            return {"success": False, "error": str(e)}

mercadopago_service = MercadoPagoService()
