"""Registro de decisiones en decisiones-y-feedback.md del proyecto."""

import re
from datetime import datetime

from .logger import get_logger
from .project import Project

log = get_logger("mixmaster.decisions")

FEEDBACK_VALIDO = ("aprobado", "rechazado", "ajustado")

# Bloque de decisión (una línea por campo, como los escribe guardar_decision)
_PAT_DECISION = re.compile(
    r"\[(?P<ts>[^\]]+)\] Versión: (?P<ver>[^|\n]+?)"
    r"(?: \| Canción: (?P<cancion>[^|\n]+?))?"
    r"(?: \| Etiqueta: (?P<etiqueta>[^|\n]+?))?\n"
    r"Decisión: (?P<decision>[^\n]*)\n"
    r"Feedback: (?P<feedback>[^\n]+)"
    r"(?:\nReferencias: (?P<refs>[^\n]+))?")


def guardar_decision(proyecto: Project, version: str, cancion: str,
                     decision: str, feedback: str, etiqueta: str = "", referencias: list[str] | None = None) -> None:
    """Añade una decisión al final de decisiones-y-feedback.md.

    Formato:
    [TIMESTAMP] Versión: V01 | Canción: Riff A | Etiqueta: prog
    Decisión: [texto]
    Feedback: aprobado / rechazado / ajustado
    Referencias: archivo1.wav, archivo2.wav
    """
    if feedback not in FEEDBACK_VALIDO:
        feedback = "ajustado"

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    etiqueta_txt = f" | Etiqueta: {etiqueta}" if etiqueta else ""
    bloque = (
        f"\n[{timestamp}] Versión: {version} | Canción: {cancion}{etiqueta_txt}\n"
        f"Decisión: {decision.strip()}\n"
        f"Feedback: {feedback}\n"
    )
    if referencias:
        bloque += f"Referencias: {', '.join(referencias)}\n"

    with open(proyecto.decisiones_path, "a", encoding="utf-8") as f:
        f.write(bloque)
    log.info("Decisión guardada en %s", proyecto.decisiones_path)


def listar_decisiones(proyecto: Project) -> list[dict]:
    """Parsea las decisiones del proyecto (más nueva al final, como en el md)."""
    if not proyecto.decisiones_path.exists():
        return []
    texto = proyecto.decisiones_path.read_text(encoding="utf-8")
    decisiones = []
    for m in _PAT_DECISION.finditer(texto):
        decisiones.append({
            "timestamp": m.group("ts"),
            "version": (m.group("ver") or "").strip(),
            "cancion": (m.group("cancion") or "").strip(),
            "etiqueta": (m.group("etiqueta") or "").strip(),
            "decision": (m.group("decision") or "").strip(),
            "feedback": (m.group("feedback") or "").strip(),
            "referencias": (m.group("refs") or "").strip(),
            "_raw": m.group(0),
        })
    return decisiones


def borrar_decision(proyecto: Project, indice: int) -> bool:
    """Borra la decisión #indice (según listar_decisiones). Devuelve si borró."""
    decisiones = listar_decisiones(proyecto)
    if not (0 <= indice < len(decisiones)):
        return False
    texto = proyecto.decisiones_path.read_text(encoding="utf-8")
    raw = decisiones[indice]["_raw"]
    # quita el bloque (y su salto de línea previo si lo tiene) una sola vez
    nuevo = texto.replace("\n" + raw, "", 1)
    if nuevo == texto:
        nuevo = texto.replace(raw, "", 1)
    proyecto.decisiones_path.write_text(nuevo, encoding="utf-8")
    log.info("Decisión #%d borrada de %s", indice, proyecto.decisiones_path)
    return True


def editar_feedback(proyecto: Project, indice: int, nuevo_feedback: str) -> bool:
    """Cambia el feedback de la decisión #indice (aprobado/rechazado/ajustado)."""
    if nuevo_feedback not in FEEDBACK_VALIDO:
        return False
    decisiones = listar_decisiones(proyecto)
    if not (0 <= indice < len(decisiones)):
        return False
    raw = decisiones[indice]["_raw"]
    raw_nuevo = re.sub(r"Feedback: [^\n]+", f"Feedback: {nuevo_feedback}", raw, count=1)
    texto = proyecto.decisiones_path.read_text(encoding="utf-8")
    proyecto.decisiones_path.write_text(texto.replace(raw, raw_nuevo, 1), encoding="utf-8")
    log.info("Feedback de decisión #%d → %s", indice, nuevo_feedback)
    return True
