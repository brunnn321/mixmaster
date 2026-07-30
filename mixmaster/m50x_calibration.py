"""Calibración de escucha para Audio-Technica ATH-M50x (v0.9+).

Genera una COPIA de escucha con la curva de corrección real medida por
oratory1990 (proyecto AutoEq, target Harman over-ear 2018). El master
exportado NUNCA se toca — esta copia es solo para decidir con el oído
"plano" en los M50x.

Fuente de los filtros: github.com/jaakkopasanen/AutoEq
  results/oratory1990/over-ear/Audio-Technica ATH-M50x/ParametricEQ.txt
"""

from pathlib import Path

import numpy as np
import soundfile as sf
from scipy import signal

from .logger import get_logger

log = get_logger("mixmaster.m50x")

# Preamp de -3.1 dB + 10 filtros paramétricos (PK / LSC / HSC), RBJ cookbook.
M50X_PREAMP_DB = -3.1
M50X_FILTERS = [
    {"tipo": "LSC", "freq": 105, "gain_db": 0.6, "q": 0.70},
    {"tipo": "PK", "freq": 156, "gain_db": -5.2, "q": 0.73},
    {"tipo": "PK", "freq": 326, "gain_db": 5.3, "q": 1.59},
    {"tipo": "PK", "freq": 7077, "gain_db": 2.8, "q": 2.22},
    {"tipo": "PK", "freq": 3483, "gain_db": 2.1, "q": 5.82},
    {"tipo": "HSC", "freq": 10000, "gain_db": -4.1, "q": 0.70},
    {"tipo": "PK", "freq": 45, "gain_db": -1.1, "q": 1.90},
    {"tipo": "PK", "freq": 66, "gain_db": 1.4, "q": 3.59},
    {"tipo": "PK", "freq": 787, "gain_db": -0.5, "q": 1.79},
    {"tipo": "PK", "freq": 1640, "gain_db": 0.9, "q": 3.41},
]


def _peaking(f0: float, gain_db: float, q: float, sr: int):
    """Coeficientes (b, a) de un peaking EQ (RBJ cookbook)."""
    A = 10 ** (gain_db / 40.0)
    w0 = 2 * np.pi * f0 / sr
    alpha = np.sin(w0) / (2 * q)
    cos_w0 = np.cos(w0)
    b = [1 + alpha * A, -2 * cos_w0, 1 - alpha * A]
    a = [1 + alpha / A, -2 * cos_w0, 1 - alpha / A]
    return np.array(b) / a[0], np.array(a) / a[0]


def _low_shelf(f0: float, gain_db: float, q: float, sr: int):
    """Coeficientes (b, a) de un low-shelf (RBJ cookbook)."""
    A = 10 ** (gain_db / 40.0)
    w0 = 2 * np.pi * f0 / sr
    alpha = np.sin(w0) / (2 * q)
    cos_w0 = np.cos(w0)
    sqrtA = np.sqrt(A)
    b0 = A * ((A + 1) - (A - 1) * cos_w0 + 2 * sqrtA * alpha)
    b1 = 2 * A * ((A - 1) - (A + 1) * cos_w0)
    b2 = A * ((A + 1) - (A - 1) * cos_w0 - 2 * sqrtA * alpha)
    a0 = (A + 1) + (A - 1) * cos_w0 + 2 * sqrtA * alpha
    a1 = -2 * ((A - 1) + (A + 1) * cos_w0)
    a2 = (A + 1) + (A - 1) * cos_w0 - 2 * sqrtA * alpha
    return np.array([b0, b1, b2]) / a0, np.array([a0, a1, a2]) / a0


def _high_shelf(f0: float, gain_db: float, q: float, sr: int):
    """Coeficientes (b, a) de un high-shelf (RBJ cookbook)."""
    A = 10 ** (gain_db / 40.0)
    w0 = 2 * np.pi * f0 / sr
    alpha = np.sin(w0) / (2 * q)
    cos_w0 = np.cos(w0)
    sqrtA = np.sqrt(A)
    b0 = A * ((A + 1) + (A - 1) * cos_w0 + 2 * sqrtA * alpha)
    b1 = -2 * A * ((A - 1) + (A + 1) * cos_w0)
    b2 = A * ((A + 1) + (A - 1) * cos_w0 - 2 * sqrtA * alpha)
    a0 = (A + 1) - (A - 1) * cos_w0 + 2 * sqrtA * alpha
    a1 = 2 * ((A - 1) - (A + 1) * cos_w0)
    a2 = (A + 1) - (A - 1) * cos_w0 - 2 * sqrtA * alpha
    return np.array([b0, b1, b2]) / a0, np.array([a0, a1, a2]) / a0


_COEFS = {"PK": _peaking, "LSC": _low_shelf, "HSC": _high_shelf}


def aplicar_curva_m50x(audio: np.ndarray, sr: int) -> np.ndarray:
    """Aplica preamp + 10 filtros (fase cero) → copia de escucha plana en M50x."""
    out = audio * (10 ** (M50X_PREAMP_DB / 20.0))
    for f in M50X_FILTERS:
        b, a = _COEFS[f["tipo"]](float(f["freq"]), f["gain_db"], f["q"], sr)
        out = signal.filtfilt(b, a, out, axis=0)
    return out


def _rms_db(audio: np.ndarray) -> float:
    rms = np.sqrt(np.mean(audio ** 2))
    return 20 * np.log10(max(rms, 1e-12))


def generar_copia_calibrada(path_master: Path, dir_salida: Path) -> dict:
    """Genera <dir_salida>/<nombre>_M50x.wav: copia calibrada + nivel igualado.

    El nivel se compensa por RMS contra el original para que el A/B no lo
    gane el que suena más fuerte (comparación justa, ±0.5 dB tolerancia).
    """
    audio, sr = sf.read(str(path_master), always_2d=True)
    audio = audio.astype(np.float64)

    calibrado = aplicar_curva_m50x(audio, sr)

    rms_orig = _rms_db(audio)
    rms_cal = _rms_db(calibrado)
    compensacion_db = rms_orig - rms_cal
    calibrado *= 10 ** (compensacion_db / 20.0)

    pico = np.max(np.abs(calibrado))
    if pico > 0.99:
        calibrado *= 0.99 / pico  # evita clipping tras la compensación

    dir_salida.mkdir(parents=True, exist_ok=True)
    out_path = dir_salida / f"{path_master.stem}_M50x.wav"
    sf.write(str(out_path), calibrado, sr, subtype="PCM_24")

    log.info("Copia M50x generada: %s (compensación %.2f dB)", out_path, compensacion_db)
    return {
        "ruta": str(out_path),
        "compensacion_db": round(compensacion_db, 2),
    }
