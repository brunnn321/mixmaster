"""Cliente mínimo de la API de Anthropic (Messages API) vía requests.

Modelo y API key son configurables en settings.json — nada hardcodeado.
"""

import requests

from .logger import get_logger
from .settings import Settings

log = get_logger("mixmaster.claude")

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
TIMEOUT_S = 120


class ClaudeError(Exception):
    """Error de comunicación con la API (mensaje apto para mostrar en UI)."""


def enviar_mensaje(settings: Settings, contexto: str,
                   historial: list[dict] | None = None) -> str:
    """Envía el contexto a Claude y devuelve el texto de respuesta.

    `historial` es una lista de {"role": "user"|"assistant", "content": str}
    con los turnos previos del chat (sin el mensaje actual).
    """
    api_key = settings.get("api_key", "").strip()
    if not api_key:
        raise ClaudeError("No hay API key configurada. Ve a Settings o usa el modo manual.")

    mensajes = list(historial or [])
    mensajes.append({"role": "user", "content": contexto})

    payload = {
        "model": settings.get("modelo", "claude-sonnet-5"),
        "max_tokens": int(settings.get("max_tokens", 2048)),
        "messages": mensajes,
    }
    headers = {
        "x-api-key": api_key,
        "anthropic-version": API_VERSION,
        "content-type": "application/json",
    }

    try:
        resp = requests.post(API_URL, json=payload, headers=headers, timeout=TIMEOUT_S)
    except requests.RequestException as e:
        log.exception("Fallo de red hacia la API")
        raise ClaudeError(f"Error de red: {e}") from e

    if resp.status_code != 200:
        detalle = ""
        try:
            detalle = resp.json().get("error", {}).get("message", "")
        except Exception:
            detalle = resp.text[:300]
        log.error("API respondió %s: %s", resp.status_code, detalle)
        raise ClaudeError(f"API error {resp.status_code}: {detalle}")

    data = resp.json()
    textos = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
    respuesta = "\n".join(t for t in textos if t)
    if not respuesta:
        raise ClaudeError("La API respondió sin texto (ver app.log).")
    return respuesta
