# app/services/waha_utils.py
import logging

def extrair_e_filtrar_mensagem_waha(payload):
    """
    Processa o payload do WAHA, extrai o texto de forma universal
    e aplica os escudos de segurança contra grupos e mensagens vazias.
    
    Retorna: (bool_sucesso, resultado_ou_mensagem_erro)
    """
    if not payload:
        return False, "Sem payload"

    from_number = payload.get('from')
    body_raw = payload.get('body')

    # 1. 🛡️ ESCUDO ANTI-GRUPOS
    if from_number and '@g.us' in str(from_number):
        logging.info(f"🚫 [ESCUDO-UTILS] Mensagem de grupo ignorada: {from_number}")
        return False, "mensagem_de_grupo"

    # 2. 🛠️ EXTRATOR UNIVERSAL DE TEXTO (Evita o erro de dicionário/NoneType)
    if isinstance(body_raw, dict):
        # Trata respostas encadeadas, botões, mídias ou enquetes pegando o texto interno
        body = str(body_raw.get('text', body_raw.get('caption', '')))
    else:
        # Texto puro comum ou None
        body = str(body_raw) if body_raw is not None else ""

    body = body.strip()

    # 3. 🛡️ ESCUDO MENSAGENS VAZIAS / FIGURINHAS SEM TEXTO
    if not body or body == "" or body.lower() == "none":
        logging.info(f"🚫 [ESCUDO-UTILS] Mensagem sem texto/mídia ignorada de: {from_number}")
        return False, "sem_texto"

    # Se passou por tudo, retorna Sucesso e o Texto extraído perfeito!
    return True, body