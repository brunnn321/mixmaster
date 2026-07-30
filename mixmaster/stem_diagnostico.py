"""Diagnóstico por stem (v0.9+): analiza CADA stem por separado y genera
observaciones accionables — el diferenciador "coaching" de MixMaster.

No masteriza ni procesa: solo mira cada stem y te dice qué mejorar en tu
mezcla, en lenguaje directo ("tu bajo no tiene definición en 250 Hz").

Reglas por tipo de instrumento (deducido del nombre del archivo):
  - bajo   → definición de medios (growl 150-400 Hz) vs sub
  - batería→ pegada (crest) y balance de graves
  - guitarra→ acumulación en low-mid (barro), presencia
  - genérico→ mono/estéreo, nivel, rango dinámico
"""

from pathlib import Path

import numpy as np

from .audio_analysis import (
    BANDAS_HZ, balance_bandas_db, cargar_audio, crest_factor_db,
)
from .logger import get_logger

log = get_logger("mixmaster.stem_diagnostico")

FORMATOS = (".wav", ".mp3", ".flac", ".ogg", ".aiff", ".aif")

_BAJO = ("bass", "bajo", "sub", "808")
_BATERIA = ("drum", "bater", "kick", "bombo", "snare", "caja", "tom", "perc", "hat", "plato", "od", "oh")
_GUITARRA = ("gtr", "guit", "guitar", "riff")
_VOZ = ("voc", "voz", "vox", "lead vox", "coro")


def _tipo(nombre: str) -> str:
    n = nombre.lower()
    if any(k in n for k in _BAJO):
        return "bajo"
    if any(k in n for k in _BATERIA):
        return "bateria"
    if any(k in n for k in _GUITARRA):
        return "guitarra"
    if any(k in n for k in _VOZ):
        return "voz"
    return "generico"


def _rms_db(audio: np.ndarray) -> float:
    r = float(np.sqrt(np.mean(audio ** 2)))
    return 20 * np.log10(max(r, 1e-9))


def _correlacion(audio: np.ndarray) -> float:
    if audio.shape[1] < 2:
        return 1.0
    L, R = audio[:, 0], audio[:, 1]
    if np.std(L) < 1e-9 or np.std(R) < 1e-9:
        return 1.0
    return float(np.corrcoef(L, R)[0, 1])


def diagnosticar_stem(path: Path) -> dict:
    """Analiza un stem y devuelve {nombre, tipo, bandas, crest, obs:[...]}."""
    path = Path(path)
    audio, sr = cargar_audio(path)
    bandas = balance_bandas_db(audio, sr)
    crest = crest_factor_db(audio)
    corr = _correlacion(audio)
    tipo = _tipo(path.stem)
    obs = []

    # --- reglas por tipo ---
    if tipo == "bajo":
        growl = bandas.get("low_mid", -99)   # 200-500 Hz: donde se "entiende" el bajo
        peso = bandas.get("low", -99)         # 60-200 Hz: cuerpo
        if growl - peso < -6:
            obs.append(("⚠", "Tu bajo pesa pero no se define: falta growl en 150-400 Hz. "
                             "Subí esa zona o meté saturación de medios para que se entienda la nota."))
        elif growl - peso > 8:
            obs.append(("·", "Bajo con buena definición de medios."))
        if bandas.get("sub", -99) - peso > 6:
            obs.append(("⚠", "Mucho sub (<60 Hz) sin cuerpo — puede sonar 'bola'. Bajá sub o subí 80-120 Hz."))

    elif tipo == "bateria":
        if crest < 8:
            obs.append(("⚠", f"Batería aplastada (crest {crest:.1f} dB) — ya viene muy comprimida. "
                             "Dejá los transientes más vivos en la mezcla."))
        else:
            obs.append(("·", f"Batería con pegada sana (crest {crest:.1f} dB)."))
        if bandas.get("high", -99) < bandas.get("mid", -99) - 12:
            obs.append(("⚠", "Platos/aire flojos — le falta brillo arriba (6-10 kHz)."))

    elif tipo == "guitarra":
        barro = bandas.get("low_mid", -99)
        cuerpo = bandas.get("mid", -99)
        if barro - cuerpo > 3:
            obs.append(("⚠", "Guitarra embarrada en 200-500 Hz — hacé un corte ahí para limpiar."))
        if bandas.get("high_mid", -99) - cuerpo > 6:
            obs.append(("⚠", "Presencia dura en 2-5 kHz — puede fatigar. Suavizá si se acumula con otras guitarras."))

    elif tipo == "voz":
        if bandas.get("low", -99) - bandas.get("mid", -99) > -6:
            obs.append(("⚠", "Voz con graves de más (proximidad) — highpass en 80-120 Hz."))

    # --- reglas generales (todos) ---
    if corr < 0.3 and audio.shape[1] >= 2:
        obs.append(("⚠", f"Imagen muy ancha/fuera de fase (corr {corr:.2f}) — riesgo en mono."))
    if _rms_db(audio) < -30:
        obs.append(("·", "Stem muy bajo de nivel — normal si es un elemento de apoyo."))
    if not obs:
        obs.append(("·", "Sin observaciones — este stem está balanceado."))

    return {
        "nombre": path.name,
        "tipo": tipo,
        "bandas_db": bandas,
        "crest_db": round(crest, 1),
        "correlacion": round(corr, 2),
        "observaciones": obs,
    }


def diagnosticar_carpeta(carpeta: Path) -> list[dict]:
    """Diagnostica todos los stems de una carpeta, ordenados por nombre."""
    carpeta = Path(carpeta)
    if not carpeta.is_dir():
        return []
    stems = sorted(p for p in carpeta.iterdir()
                   if p.is_file() and p.suffix.lower() in FORMATOS)
    resultado = []
    for s in stems:
        try:
            resultado.append(diagnosticar_stem(s))
        except Exception:
            log.exception("No se pudo diagnosticar el stem %s", s.name)
    return resultado
