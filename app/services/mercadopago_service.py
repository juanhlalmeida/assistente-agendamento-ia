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
    
    def criar_pagamento(self, barbearia, plano, email_pagador):
        """Cria pagamento único (não recorrente) no Mercado Pago"""
        try:
            logging.info(f"📝 Criando pagamento para {barbearia.nome_fantasia} - Plano: {plano.nome}")
            
            # ✅ NOVO: Preference para pagamento único
            preference_data = {
                "items": [
                    {
                        "title": f"Assinatura {plano.nome} - {barbearia.nome_fantasia}",
                        "description": f"{plano.descricao} - Válida por 30 dias",
                        "quantity": 1,
                        "currency_id": "BRL",
                        "unit_price": float(plano.preco_mensal)
                    }
                ],
                "payer": {
                    "email": email_pagador
                },
                "back_urls": {
                    "success": f"{os.getenv('BASE_URL', 'https://assistente-agendamento-ia.onrender.com')}/assinatura/retorno?status=success",
                    "failure": f"{os.getenv('BASE_URL', 'https://assistente-agendamento-ia.onrender.com')}/assinatura/retorno?status=failure",
                    "pending": f"{os.getenv('BASE_URL', 'https://assistente-agendamento-ia.onrender.com')}/assinatura/retorno?status=pending"
                },
                "auto_return": "approved",
                "external_reference": f"barbearia_{barbearia.id}_plano_{plano.id}",
                "notification_url": f"{os.getenv('BASE_URL', 'https://assistente-agendamento-ia.onrender.com')}/assinatura/webhook",
                "statement_descriptor": f"Assinatura {plano.nome}",
                "expires": False,
                "payment_methods": {
                    "excluded_payment_types": [],
                    "installments": 1  # ✅ Apenas 1x (mensal)
                }
            }
            
            logging.info(f"📤 Enviando dados para Mercado Pago")
            
            result = self.sdk.preference().create(preference_data)
            
            logging.info(f"📥 Resposta do Mercado Pago: Status {result['status']}")
            
            if result["status"] == 201:
                logging.info(f"✅ Pagamento criado com sucesso!")
                logging.info(f"   ID: {result['response']['id']}")
                
                # ✅ Retorna init_point correto baseado no ambiente
                if os.getenv('MERCADOPAGO_ACCESS_TOKEN', '').startswith('TEST-'):
                    init_point = result['response'].get('sandbox_init_point', result['response']['init_point'])
                else:
                    init_point = result['response']['init_point']
                
                logging.info(f"   Init Point: {init_point}")
                
                return {
                    "success": True,
                    "preference_id": result["response"]["id"],
                    "init_point": init_point
                }
            else:
                logging.error(f"❌ Erro ao criar pagamento!")
                logging.error(f"   Status: {result['status']}")
                logging.error(f"   Response: {result.get('response')}")
                return {"success": False, "error": result}
                
        except Exception as e:
            logging.error(f"❌ ERRO CRÍTICO no MercadoPagoService.criar_pagamento: {e}", exc_info=True)
            return {"success": False, "error": str(e)}
    
    def consultar_pagamento(self, payment_id):
        """Consulta status do pagamento"""
        try:
            logging.info(f"🔍 Consultando pagamento: {payment_id}")
            result = self.sdk.payment().get(payment_id)
            
            if result["status"] == 200:
                logging.info(f"✅ Pagamento encontrado: Status {result['response'].get('status')}")
                return {"success": True, "data": result["response"]}
            else:
                logging.error(f"❌ Erro ao consultar pagamento: {result}")
                return {"success": False, "error": result}
                
        except Exception as e:
            logging.error(f"❌ Erro ao consultar pagamento: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

# Instância global
mercadopago_service = MercadoPagoService()
