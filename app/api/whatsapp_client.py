# whatsapp_client.py
"""
Cliente WhatsApp Cloud API (Meta) com:
- Env vars padronizadas
- Sanitização de telefone (somente dígitos com DDI, sem '+')
- json= no POST e logs úteis em erro 400/429
"""

from __future__ import annotations

import os
import re
import json
import logging
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)


def sanitize_msisdn(value: str) -> str:
    """
    Mantém apenas dígitos. Ex.: "+55 (11) 98888-7777" -> "5511988887777"
    Recomenda-se enviar SEM o '+' (há integrações que rejeitam '+').
    """
    return re.sub(r"\D+", "", value or "")


class WhatsAppClient:
    def __init__(
        self,
        access_token: Optional[str] = None,
        phone_number_id: Optional[str] = None,
        api_version: str = "",
        default_timeout: int = 20,
    ) -> None:
        self.access_token = access_token or os.getenv("WHATSAPP_ACCESS_TOKEN")
        self.phone_number_id = phone_number_id or os.getenv("WHATSAPP_PHONE_NUMBER_ID")
        self.api_version = api_version or os.getenv("WHATSAPP_API_VERSION", "v20.0")
        self.default_timeout = default_timeout

        self.base_url: Optional[str] = (
            f"https://graph.facebook.com/{self.api_version}/{self.phone_number_id}/messages"
            if self.phone_number_id
            else None
        )

    def _simulated(self, to_number: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        msg = {
            "status": "simulated",
            "reason": "Config ausente (WHATSAPP_ACCESS_TOKEN/WHATSAPP_PHONE_NUMBER_ID) — envio simulado.",
            "to": to_number,
            "payload": payload,
        }
        logger.info("[WhatsApp SIMULADO] %s", json.dumps(msg, ensure_ascii=False))
        return msg

    def send_text(self, to_number: str, text: str, timeout: Optional[int] = None) -> Dict[str, Any]:
        """
        Envia mensagem de texto; em dev, se faltar config, simula o envio.
        """
        msisdn = sanitize_msisdn(to_number)
        payload = {
            "messaging_product": "whatsapp",
            "to": msisdn,
            "type": "text",
            "text": {"body": text},
        }  # Forma oficial do payload para texto. [1](https://docs.360dialog.com/docs/waba-messaging/messaging)

        if not self.access_token or not self.base_url:
            return self._simulated(msisdn, payload)

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

        tout = timeout or self.default_timeout
        try:
            resp = requests.post(self.base_url, headers=headers, json=payload, timeout=tout)
            # Tente decodificar detalhes do erro 400 para log útil:
            try:
                body = resp.json() if resp.content else {"status_code": resp.status_code}
            except Exception:
                body = {"raw_text": resp.text, "status_code": resp.status_code}

            if not resp.ok:
                # Loga o corpo retornado pela Meta (traz code/message detalhados)
                logger.error("WhatsApp API ERRO %s: %s", resp.status_code, body)

            # 429: rate limit (trate com backoff se necessário)
            if resp.status_code == 429:
                logger.warning("Rate limit (429) ao enviar mensagem para %s: %s", msisdn, body)

            return {
                "status": "sent" if resp.ok else "error",
                "status_code": resp.status_code,
                "response": body,
            }
        except Exception as exc:
            logger.exception("Falha ao enviar mensagem WhatsApp: %s", exc)
            return {"status": "error", "error": str(exc)}
