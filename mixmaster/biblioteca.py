"""Biblioteca de conocimiento: la app analiza sola las carpetas de música de
Bruno y acumula un informe por tema en config/biblioteca/analisis.jsonl (una
línea JSON por archivo). Claude los lee y ordena solo cuando Bruno lo pide.

Lo que se mide es lo que usa el master para decidir: volumen, picos, dinámica,
ancho estéreo y cuánto sobresale cada zona (mixmaster/qc.py).
"""

import json
from datetime import datetime
from pathlib import Path

from .app_paths import CONFIG_DIR

ARCHIVO = CONFIG_DIR / "biblioteca" / "analisis.jsonl"
EXTENSIONES = {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aiff", ".aif"}


def ya_analizados() -> set[str]:
    """Rutas que ya tienen informe (para seguir donde quedó si se cortó)."""
    if not ARCHIVO.exists():
        return set()
    hechos = set()
    for linea in ARCHIVO.read_text(encoding="utf-8").splitlines():
        try:
            hechos.add(json.loads(linea)["ruta"])
        except Exception:
            continue
    return hechos


def analizar_archivo(ruta: Path, raiz: Path | None = None) -> dict:
    """Informe de un tema. Artista y álbum salen de las carpetas que lo contienen."""
    from .audio_analysis import (
        analisis_estereo, cargar_audio, crest_factor_db, lufs_integrado, true_peak_db,
    )
    from .qc import nivel_zonas
    audio, sr = cargar_audio(ruta)
    # la carpeta elegida también cuenta: si es la del artista, su nombre queda guardado
    carpetas = ((raiz.name,) + ruta.relative_to(raiz).parts[:-1]
                if raiz and ruta.is_relative_to(raiz) else ruta.parts[-3:-1])
    return {
        "ruta": str(ruta),
        "carpetas": list(carpetas),   # p. ej. ["Matthew Mcghee"] o ["Rock", "Artista", "Álbum"]
        "fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "duracion_s": round(len(audio) / sr, 1),
        "lufs": round(float(lufs_integrado(audio, sr)), 1),
        "true_peak_db": round(float(true_peak_db(audio, sr)), 1),
        "crest_db": round(float(crest_factor_db(audio)), 1),
        "correlacion": round(float(analisis_estereo(audio, sr)["correlacion_global"]), 2),
        "zonas_db": {z: round(v, 1) for z, v in nivel_zonas(audio, sr).items()},
    }


def analizar_carpetas(carpetas: list[Path], progreso=None, parar=lambda: False) -> int:
    """Recorre las carpetas y agrega un informe por tema nuevo. Devuelve cuántos sumó."""
    ARCHIVO.parent.mkdir(parents=True, exist_ok=True)
    hechos = ya_analizados()
    pendientes = [(p, Path(c)) for c in carpetas for p in sorted(Path(c).rglob("*"))
                  if p.suffix.lower() in EXTENSIONES and str(p) not in hechos]
    sumados = 0
    with open(ARCHIVO, "a", encoding="utf-8") as f:
        for i, (p, raiz) in enumerate(pendientes, 1):
            if parar():
                break
            if progreso:
                progreso(f"Biblioteca {i}/{len(pendientes)}: {p.name}")
            try:
                f.write(json.dumps(analizar_archivo(p, raiz), ensure_ascii=False) + "\n")
                f.flush()   # si se corta, lo hecho queda guardado
                sumados += 1
            except Exception as e:
                if progreso:
                    progreso(f"No se pudo analizar {p.name}: {e}")
    return sumados
