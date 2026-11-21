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
            informe = json.loads(linea)
            if "diagnostico" in informe:   # los informes básicos viejos se rehacen completos
                hechos.add(informe["ruta"])
        except Exception:
            continue
    return hechos


def analizar_archivo(ruta: Path, raiz: Path | None = None, paso=lambda pct: None) -> dict:
    """Informe completo de un tema: el mismo diagnóstico del PASO 1 (espectro fino
    de 40 bandas, balance por bandas, LUFS/LRA/PLR/true peak/crest, estéreo y fase
    por banda y momento a momento, carácter tonal, punch, secciones) + zonas de
    mixer-doctor + semáforo de calidad. Artista y álbum salen de las carpetas.
    `paso(pct)` avisa cuánto lleva del tema (0–100)."""
    from .audio_analysis import analizar_wav, cargar_audio
    from .qc import control_calidad, nivel_zonas
    pasos = {"n": 0}

    def avance(_msg):   # analizar_wav avisa ~15 etapas: cada una suma un tramo
        pasos["n"] += 1
        paso(min(85, 5 + pasos["n"] * 6))

    paso(2)
    diag = analizar_wav(ruta, "", None, version="BIB", progreso=avance)
    audio, sr = cargar_audio(ruta)
    paso(90)
    zonas = {z: round(v, 1) for z, v in nivel_zonas(audio, sr).items()}
    qc = control_calidad(audio, sr)
    paso(100)
    # la carpeta elegida también cuenta: si es la del artista, su nombre queda guardado
    carpetas = ((raiz.name,) + ruta.relative_to(raiz).parts[:-1]
                if raiz and ruta.is_relative_to(raiz) else ruta.parts[-3:-1])
    return {
        "ruta": str(ruta),
        "carpetas": list(carpetas),   # p. ej. ["Matthew Mcghee"] o ["Rock", "Artista", "Álbum"]
        "fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "duracion_s": round(len(audio) / sr, 1),
        "zonas_db": zonas,
        "qc": qc,
        "diagnostico": diag,
    }


def analizar_carpetas(carpetas: list[Path], progreso=None, parar=lambda: False) -> int:
    """Recorre todas las carpetas (y sus subcarpetas) en cola, un tema por vez, y
    agrega un informe por tema nuevo. Devuelve cuántos sumó.

    `progreso(i, total, nombre, pct_tema)` avisa en qué tema va (1..total) y
    cuánto lleva de ese tema; `progreso(0, 0, texto, -1)` es un aviso suelto.
    """
    ARCHIVO.parent.mkdir(parents=True, exist_ok=True)
    hechos = ya_analizados()
    pendientes = [(p, Path(c)) for c in carpetas for p in sorted(Path(c).rglob("*"))
                  if p.suffix.lower() in EXTENSIONES and str(p) not in hechos]
    avisar = progreso or (lambda *a: None)
    sumados = 0
    with open(ARCHIVO, "a", encoding="utf-8") as f:
        for i, (p, raiz) in enumerate(pendientes, 1):
            if parar():
                break
            avisar(i, len(pendientes), p.name, 0)
            try:
                informe = analizar_archivo(p, raiz, lambda pct, i=i, p=p: avisar(i, len(pendientes), p.name, pct))
                f.write(json.dumps(informe, ensure_ascii=False, default=str) + "\n")
                f.flush()   # si se corta, lo hecho queda guardado
                sumados += 1
            except Exception as e:
                avisar(0, 0, f"No se pudo analizar {p.name}: {e}", -1)
    return sumados
