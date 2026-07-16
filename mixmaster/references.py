"""Gestión de referencias dinámicas etiquetadas por el usuario (v0.5+).

PASO A: Subir referencia (archivo + etiqueta → config/referencias/{etiqueta}/)
PASO B: Detector de etiqueta (analiza mezcla contra todas las referencias)
"""

import json
import shutil
from datetime import datetime
from pathlib import Path

import numpy as np

from .app_paths import CONFIG_DIR, REFERENCIAS_DIR, HISTORIAL_REFERENCIAS_JSON
from .audio_analysis import cargar_audio, espectro_suavizado
from .logger import get_logger

log = get_logger("mixmaster.references")


def ensure_referencias_dirs() -> None:
    """Crea config/referencias/ si no existe."""
    REFERENCIAS_DIR.mkdir(parents=True, exist_ok=True)


def subir_referencia(archivo_path: Path, etiqueta: str) -> dict:
    """PASO A: Subir una referencia con etiqueta.

    Copia archivo a config/referencias/{etiqueta}/ y guarda metadatos.

    Args:
        archivo_path: ruta del audio (WAV/MP3/FLAC/OGG/AIFF)
        etiqueta: etiqueta libre (ej. "prog", "djent", "funk")

    Returns:
        {"exito": True/False, "ruta_destino": ..., "etiqueta": ...}
    """
    ensure_referencias_dirs()
    archivo_path = Path(archivo_path)

    if not archivo_path.exists():
        log.error("Archivo no existe: %s", archivo_path)
        return {"exito": False, "error": "Archivo no encontrado"}

    if archivo_path.suffix.lower() not in (".wav", ".mp3", ".flac", ".ogg", ".aiff", ".aif"):
        log.error("Formato no soportado: %s", archivo_path.suffix)
        return {"exito": False, "error": "Formato no soportado"}

    etiqueta_norm = etiqueta.strip().lower().replace(" ", "_")
    if not etiqueta_norm:
        return {"exito": False, "error": "Etiqueta vacía"}

    carpeta_etiqueta = REFERENCIAS_DIR / etiqueta_norm
    carpeta_etiqueta.mkdir(parents=True, exist_ok=True)

    nombre_dest = archivo_path.name
    ruta_dest = carpeta_etiqueta / nombre_dest

    # Si existe, versionar
    if ruta_dest.exists():
        stem, suffix = archivo_path.stem, archivo_path.suffix
        i = 1
        while (carpeta_etiqueta / f"{stem}_{i}{suffix}").exists():
            i += 1
        nombre_dest = f"{stem}_{i}{suffix}"
        ruta_dest = carpeta_etiqueta / nombre_dest

    try:
        shutil.copy2(str(archivo_path), str(ruta_dest))
        log.info("Referencia subida: %s → %s", archivo_path.name, ruta_dest)
    except Exception as e:
        log.error("Error al copiar: %s", e)
        return {"exito": False, "error": str(e)}

    # Guardar metadatos
    metadata = {
        "archivo": nombre_dest,
        "etiqueta": etiqueta_norm,
        "fecha_subida": datetime.now().isoformat(),
        "tamaño_bytes": int(ruta_dest.stat().st_size),
    }
    _guardar_metadata_referencia(metadata)

    return {
        "exito": True,
        "ruta_destino": str(ruta_dest),
        "nombre_archivo": nombre_dest,
        "etiqueta": etiqueta_norm,
    }


def _guardar_metadata_referencia(metadata: dict) -> None:
    """Guarda metadatos en historial_referencias.json."""
    ensure_referencias_dirs()

    historial = []
    if HISTORIAL_REFERENCIAS_JSON.exists():
        try:
            with open(HISTORIAL_REFERENCIAS_JSON, "r", encoding="utf-8") as f:
                historial = json.load(f)
        except Exception as e:
            log.warning("Error leyendo historial: %s", e)

    historial.append(metadata)

    with open(HISTORIAL_REFERENCIAS_JSON, "w", encoding="utf-8") as f:
        json.dump(historial, f, indent=2, ensure_ascii=False)

    log.info("Metadata guardada: %s", HISTORIAL_REFERENCIAS_JSON)


def listar_referencias_por_etiqueta() -> dict[str, list[str]]:
    """Lista referencias agrupadas por etiqueta."""
    ensure_referencias_dirs()
    resultado = {}

    if not REFERENCIAS_DIR.exists():
        return resultado

    for carpeta_etiqueta in REFERENCIAS_DIR.iterdir():
        if not carpeta_etiqueta.is_dir():
            continue
        etiqueta = carpeta_etiqueta.name
        archivos = [
            f.name for f in carpeta_etiqueta.iterdir()
            if f.is_file() and f.suffix.lower() in (".wav", ".mp3", ".flac", ".ogg", ".aiff", ".aif")
        ]
        if archivos:
            resultado[etiqueta] = sorted(archivos)

    return resultado


def detectar_etiqueta_sugerida(audio_mezcla_path: Path) -> dict:
    """PASO B: Detecta etiqueta sugerida comparando mezcla vs referencias.

    Analiza MFCC (13 coefs) + espectro suavizado (31 puntos).
    Compara contra TODAS las referencias de TODAS las etiquetas.

    Returns:
        {
            "exito": True,
            "etiqueta_sugerida": "prog",
            "confianza": 0.75,
            "similitudes": {"prog": 0.75, "djent": 0.55, ...},
        }
    """
    from .audio_analysis import cepstral_fingerprint

    audio_mezcla_path = Path(audio_mezcla_path)
    if not audio_mezcla_path.exists():
        log.error("Audio no encontrado: %s", audio_mezcla_path)
        return {
            "exito": False,
            "etiqueta_sugerida": None,
            "confianza": 0.0,
            "similitudes": {},
        }

    try:
        audio_mezcla, sr_mezcla = cargar_audio(audio_mezcla_path)
        mfcc_mezcla = cepstral_fingerprint(audio_mezcla, sr_mezcla)["mfcc_mean"]
        _, spec_mezcla = espectro_suavizado(audio_mezcla, sr_mezcla)
    except Exception as e:
        log.error("Error analizando mezcla: %s", e)
        return {
            "exito": False,
            "etiqueta_sugerida": None,
            "confianza": 0.0,
        }

    similitudes = {}
    referencias_por_etiqueta = listar_referencias_por_etiqueta()

    if not referencias_por_etiqueta:
        log.warning("Sin referencias cargadas")
        return {
            "exito": True,
            "etiqueta_sugerida": None,
            "confianza": 0.0,
            "similitudes": {},
            "nota": "Sin referencias",
        }

    # Comparar contra cada etiqueta
    for etiqueta, nombres_archivos in referencias_por_etiqueta.items():
        scores_etiqueta = []

        for nombre in nombres_archivos:
            ruta_ref = REFERENCIAS_DIR / etiqueta / nombre
            try:
                from .audio_analysis import analizar_referencia_cacheada
                e = analizar_referencia_cacheada(ruta_ref)  # cacheado: rápido
                mfcc_ref = e["mfcc_mean"]
                spec_ref = np.asarray(e["espectro_db"])

                # Score MFCC: similitud coseno normalizada
                score_mfcc = 1.0 - np.linalg.norm(
                    np.array(mfcc_mezcla) - np.array(mfcc_ref)
                ) / (np.linalg.norm(np.array(mfcc_ref)) + 1e-9)
                score_mfcc = float(np.clip(score_mfcc, 0.0, 1.0))

                # Score espectro: diferencia normalizada
                min_len = min(len(spec_mezcla), len(spec_ref))
                score_spec = 1.0 - np.mean(
                    np.abs(spec_mezcla[:min_len] - spec_ref[:min_len])
                ) / (np.std(spec_ref[:min_len]) + 1e-9)
                score_spec = float(np.clip(score_spec, 0.0, 1.0))

                # Promedio ponderado
                score = 0.5 * score_mfcc + 0.5 * score_spec
                scores_etiqueta.append(score)
            except Exception as e:
                log.debug("Fallo analizando %s: %s", nombre, e)
                continue

        if scores_etiqueta:
            similitudes[etiqueta] = round(float(np.mean(scores_etiqueta)), 2)

    if not similitudes:
        log.warning("No se pudo comparar ninguna referencia")
        return {
            "exito": True,
            "etiqueta_sugerida": None,
            "confianza": 0.0,
            "similitudes": {},
        }

    # Etiqueta ganadora
    etiqueta_sugerida = max(similitudes, key=similitudes.get)
    confianza = similitudes[etiqueta_sugerida]

    return {
        "exito": True,
        "etiqueta_sugerida": etiqueta_sugerida,
        "confianza": confianza,
        "similitudes": similitudes,
    }
