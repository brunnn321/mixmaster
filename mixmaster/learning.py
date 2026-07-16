"""Aprendizaje de preferencias (v0.9+): la app aprende de los masters que
apruebas y afina sus defaults por género.

Guarda en config/aprendizaje.json. Reversible (olvidar). Primer mecanismo:
loudness preferido por género (media de los masters aprobados). Se guarda
además el perfil del master para el futuro «tu sonido» (matching hacia tus
propios masters aprobados).
"""

import json
from datetime import datetime

from .app_paths import CONFIG_DIR
from .logger import get_logger

log = get_logger("mixmaster.learning")

APRENDIZAJE_JSON = CONFIG_DIR / "aprendizaje.json"


def _cargar() -> dict:
    if APRENDIZAJE_JSON.exists():
        try:
            return json.loads(APRENDIZAJE_JSON.read_text(encoding="utf-8"))
        except Exception:
            log.exception("aprendizaje.json ilegible; se ignora")
    return {}


def _guardar(datos: dict) -> None:
    APRENDIZAJE_JSON.parent.mkdir(parents=True, exist_ok=True)
    APRENDIZAJE_JSON.write_text(
        json.dumps(datos, indent=2, ensure_ascii=False), encoding="utf-8")


def registrar_aprobado(genero: str, resumen: dict) -> int:
    """Registra un master aprobado para el género. Devuelve el total acumulado."""
    datos = _cargar()
    g = datos.setdefault(genero, {"aprobados": []})
    g["aprobados"].append({
        "fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "target_lufs": resumen.get("target_lufs"),
        "lufs_final": resumen.get("lufs_final"),
        "crest_final": resumen.get("crest_final"),
        "eq_aplicado_db": resumen.get("eq_aplicado_db"),
        "score": resumen.get("score"),
        "referencias": resumen.get("referencias"),
    })
    _guardar(datos)
    n = len(g["aprobados"])
    log.info("Master aprobado registrado para '%s' (%d total)", genero, n)
    return n


def preferencias(genero: str) -> dict:
    """Defaults aprendidos del género a partir de los masters aprobados."""
    aprobados = _cargar().get(genero, {}).get("aprobados", [])
    lufs = [a["target_lufs"] for a in aprobados if a.get("target_lufs") is not None]
    if not lufs:
        return {}
    return {
        "target_lufs": round(sum(lufs) / len(lufs) * 2) / 2,  # media redondeada a 0.5
        "n": len(aprobados),
    }


def olvidar(genero: str | None = None) -> None:
    """Borra el aprendizaje de un género (o de todos si genero es None)."""
    datos = _cargar()
    if genero is None:
        datos = {}
    else:
        datos.pop(genero, None)
    _guardar(datos)
    log.info("Aprendizaje olvidado: %s", genero or "TODO")
