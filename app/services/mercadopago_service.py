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
        logging.info("✅ MercadoPago SDK inicializado")
    
    def criar_assinatura(self, barbearia, plano, email_pagador):
        """Cria assinatura recorrente no Mercado Pago"""
        try:
            logging.info(f"📝 Criando assinatura para {barbearia.nome_fantasia} - Plano: {plano.nome}")
            
            # Data de início (hoje) e fim (1 ano)
            data_inicio = datetime.now()
            data_fim = data_inicio + timedelta(days=365)
            
            # ✅ CORRIGIDO: Formato ISO 8601 com timezone UTC correto
            start_date_str = data_inicio.strftime("%Y-%m-%dT%H:%M:%S.000Z")
            end_date_str = data_fim.strftime("%Y-%m-%dT%H:%M:%S.000Z")
            
            logging.info(f"📅 Data início: {start_date_str}")
            logging.info(f"📅 Data fim: {end_date_str}")
            logging.info(f"💰 Valor: R$ {plano.preco_mensal}")
            
            preapproval_data = {
                "reason": f"Assinatura {plano.nome} - {barbearia.nome_fantasia}",
                "auto_recurring": {
                    "frequency": 1,
                    "frequency_type": "months",
                    "transaction_amount": float(plano.preco_mensal),  # ✅ Garantir float
                    "currency_id": "BRL",
                    "start_date": start_date_str,
                    "end_date": end_date_str
                },
                "back_url": f"{os.getenv('BASE_URL', 'https://assistente-agendamento-ia.onrender.com')}/assinatura/retorno",
                "payer_email": email_pagador,
                "status": "pending"
            }
            
            logging.info(f"📤 Enviando dados para Mercado Pago: {preapproval_data}")
            
            result = self.sdk.preapproval().create(preapproval_data)
            
            logging.info(f"📥 Resposta do Mercado Pago: Status {result['status']}")
            
            if result["status"] == 201:
                logging.info(f"✅ Assinatura criada com sucesso!")
                logging.info(f"   ID: {result['response']['id']}")
                logging.info(f"   Init Point: {result['response'].get('init_point')}")
                logging.info(f"   Sandbox Init Point: {result['response'].get('sandbox_init_point')}")
                
                return {
                    "success": True,
                    "preapproval_id": result["response"]["id"],
                    "init_point": result["response"]["init_point"],
                    "sandbox_init_point": result["response"].get("sandbox_init_point")
                }
            else:
                logging.error(f"❌ Erro ao criar assinatura!")
                logging.error(f"   Status: {result['status']}")
                logging.error(f"   Response: {result.get('response')}")
                return {"success": False, "error": result}
                
        except Exception as e:
            logging.error(f"❌ ERRO CRÍTICO no MercadoPagoService.criar_assinatura: {e}", exc_info=True)
            return {"success": False, "error": str(e)}
    
    def consultar_assinatura(self, preapproval_id):
        """Consulta status da assinatura"""
        try:
            logging.info(f"🔍 Consultando assinatura: {preapproval_id}")
            result = self.sdk.preapproval().get(preapproval_id)
            
            if result["status"] == 200:
                logging.info(f"✅ Assinatura encontrada: Status {result['response'].get('status')}")
                return {"success": True, "data": result["response"]}
            else:
                logging.error(f"❌ Erro ao consultar assinatura: {result}")
                return {"success": False, "error": result}
                
        except Exception as e:
            logging.error(f"❌ Erro ao consultar assinatura: {e}", exc_info=True)
            return {"success": False, "error": str(e)}
    
    def cancelar_assinatura(self, preapproval_id):
        """Cancela assinatura"""
        try:
            logging.info(f"🚫 Cancelando assinatura: {preapproval_id}")
            result = self.sdk.preapproval().update(preapproval_id, {"status": "cancelled"})
            
            if result["status"] == 200:
                logging.info(f"✅ Assinatura cancelada com sucesso: {preapproval_id}")
                return {"success": True}
            else:
                logging.error(f"❌ Erro ao cancelar assinatura: {result}")
                return {"success": False, "error": result}
                
        except Exception as e:
            logging.error(f"❌ Erro ao cancelar assinatura: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

# Instância global
mercadopago_service = MercadoPagoService()

#TESTE
