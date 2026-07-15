"""Registro de decisiones en decisiones-y-feedback.md del proyecto."""

from datetime import datetime

from .logger import get_logger
from .project import Project

log = get_logger("mixmaster.decisions")

FEEDBACK_VALIDO = ("aprobado", "rechazado", "ajustado")


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
