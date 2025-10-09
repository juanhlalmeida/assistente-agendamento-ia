# app/routes.py

# Adicione esta importação no topo do seu arquivo
from .services.whatsapp_service import send_whatsapp_message

# ... (resto do seu código) ...

@bp.route('/webhook', methods=['GET', 'POST'])
def webhook():
    if request.method == 'GET':
        # A lógica de verificação GET continua a mesma
        # ...
        return 'OK', 200

    if request.method == 'POST':
        data = request.get_json()
        print("MENSAGEM DO WHATSAPP RECEBIDA:", data)

        try:
            # Extrai as informações da mensagem recebida
            if (data.get('entry') and
                data['entry'][0].get('changes') and
                data['entry'][0]['changes'][0].get('value') and
                data['entry'][0]['changes'][0]['value'].get('messages')):

                message_info = data['entry'][0]['changes'][0]['value']['messages'][0]
                from_number = message_info['from']
                received_text = message_info['text']['body']

                # Prepara a resposta (o "eco")
                response_text = f"Recebi sua mensagem: '{received_text}'"

                # Usa nosso serviço para enviar a resposta
                send_whatsapp_message(from_number, response_text)

        except (KeyError, IndexError) as e:
            print(f"Erro ao processar o payload do webhook: {e}")

        return 'OK', 200