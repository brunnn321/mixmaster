"""Construcción del contexto que acompaña cada mensaje al asistente.

Cada mensaje incluye: perfil de sonido + diagnóstico activo (últimas 2
secciones relevantes) + últimas 5 decisiones del proyecto + mensaje del usuario.
Solo texto: el audio nunca se envía.
"""

import json

from .logger import get_logger
from .project import Project
from .settings import Settings

log = get_logger("mixmaster.context")

INSTRUCCIONES_SISTEMA = """Eres un asistente de mezcla y mastering. Trabajas con reportes de \
análisis local (el audio nunca sale de la máquina del usuario). Responde siempre con esta \
estructura: Diagnóstico → Prioridad → Acciones → Razón musical → Verificación → Riesgos → \
Siguiente revisión. Prioriza pocas decisiones de alto impacto (máximo 3 problemas por revisión). \
La intención artística está por encima de una métrica; las referencias orientan, no se clonan."""


def _secciones_relevantes(diag: dict, n: int = 2) -> list[dict]:
    """Elige las N secciones más relevantes: primero con notas/clipping, luego las más fuertes."""
    secciones = diag.get("secciones") or []
    if len(secciones) <= n:
        return secciones
    ordenadas = sorted(
        secciones,
        key=lambda s: (s["clipping"], len(s["notas_auto"]), s["lufs_st"]),
        reverse=True,
    )
    return ordenadas[:n]


def resumen_diagnostico(diag: dict) -> str:
    """Versión compacta del diagnóstico para el contexto del chat."""
    compacto = {
        "archivo": diag["archivo"],
        "version": diag["version"],
        "global": diag["global"],
        "bandas_db": diag["bandas_db"],
        "estereo": {
            "correlacion_global": diag["estereo"]["correlacion_global"],
            "perdida_mono_db": diag["estereo"]["perdida_mono_db"],
        },
        "secciones_relevantes": _secciones_relevantes(diag),
        "vs_referencia": diag.get("vs_referencia"),
        "alertas": diag["alertas"],
    }
    return json.dumps(compacto, indent=2, ensure_ascii=False)


def ultimas_decisiones(proyecto: Project, n: int = 5) -> str:
    """Últimas N líneas con contenido del decisiones-y-feedback.md."""
    try:
        texto = proyecto.decisiones_path.read_text(encoding="utf-8")
    except Exception:
        return "(sin historial de decisiones)"
    lineas = [l for l in texto.splitlines() if l.strip() and not l.startswith(("#", ">"))]
    if not lineas:
        return "(sin decisiones registradas aún)"
    return "\n".join(lineas[-n:])


def construir_contexto(settings: Settings, proyecto: Project | None,
                       diag: dict | None, mensaje_usuario: str) -> str:
    """Ensambla el prompt completo (para API o para copiar/pegar en claude.ai)."""
    partes = [INSTRUCCIONES_SISTEMA, ""]

    partes += ["═══ PERFIL DE USUARIO ═══", settings.leer_perfil_usuario(), ""]

    genero_md, _ = settings.leer_genero_activo()
    partes += [f"═══ PERFIL DE GÉNERO: {settings.genero_activo()} ═══", genero_md, ""]

    if diag:
        partes += ["═══ DIAGNÓSTICO DE LA CANCIÓN ACTIVA ═══", resumen_diagnostico(diag), ""]
    else:
        partes += ["═══ DIAGNÓSTICO ═══", "(aún no se analizó ningún audio en esta sesión)", ""]

    if proyecto:
        partes += [
            f"═══ HISTORIAL DE DECISIONES ({proyecto.nombre}, últimas 5) ═══",
            ultimas_decisiones(proyecto),
            "",
        ]

    partes += ["═══ MENSAJE DEL USUARIO ═══", mensaje_usuario]
    return "\n".join(partes)
