"""Null test (v0.9+): resta dos audios (fase invertida) para escuchar SOLO
la diferencia entre dos versiones — técnica de mastering de alto nivel.

Si son idénticos, la resta da silencio. Lo que suena es exactamente lo que
cambió entre v1 y v2 (EQ, compresión, ancho estéreo, loudness, etc.).
"""

from pathlib import Path

import numpy as np
import soundfile as sf

from .logger import get_logger

log = get_logger("mixmaster.null_test")


def generar_diferencia(path_a: Path, path_b: Path, dir_salida: Path,
                       igualar_loudness: bool = True) -> dict:
    """Genera un WAV con SOLO la diferencia entre A y B (resta de fase).

    Si igualar_loudness, nivela el RMS de B a A antes de restar — si no, un
    simple cambio de volumen entre versiones domina la resta y tapa lo demás
    (lo que de verdad interesa: EQ, estéreo, compresión).
    """
    path_a, path_b = Path(path_a), Path(path_b)
    a, sr_a = sf.read(str(path_a), always_2d=True)
    b, sr_b = sf.read(str(path_b), always_2d=True)
    if sr_a != sr_b:
        raise ValueError(f"Sample rates distintos: {sr_a} vs {sr_b}")

    n = min(len(a), len(b))
    a, b = a[:n].astype(np.float64), b[:n].astype(np.float64)
    if a.shape[1] != b.shape[1]:
        ch = min(a.shape[1], b.shape[1])
        a, b = a[:, :ch], b[:, :ch]

    gain_db = 0.0
    if igualar_loudness:
        rms_a = float(np.sqrt(np.mean(a ** 2)))
        rms_b = float(np.sqrt(np.mean(b ** 2)))
        if rms_b > 1e-9:
            gain = rms_a / rms_b
            gain_db = 20 * np.log10(gain)
            b = b * gain

    diferencia = a - b  # null test: resta de fase

    pico = float(np.max(np.abs(diferencia)))
    if pico > 1e-6:
        # normaliza a -3 dBFS para que se escuche cómodo (la diferencia suele ser muy baja)
        objetivo = 10 ** (-3 / 20)
        diferencia = diferencia * (objetivo / pico)
        silencio = False
    else:
        silencio = True

    dir_salida.mkdir(parents=True, exist_ok=True)
    out = dir_salida / f"null_test_{path_a.stem}_vs_{path_b.stem}.wav"
    sf.write(str(out), diferencia, sr_a, subtype="PCM_24")

    rms_dif_db = 20 * np.log10(max(float(np.sqrt(np.mean(diferencia ** 2))), 1e-9))
    log.info("Null test generado: %s (silencio=%s, gain_b=%.2f dB)", out, silencio, gain_db)
    return {
        "ruta": str(out),
        "silencio": silencio,
        "gain_b_aplicado_db": round(gain_db, 2),
        "rms_diferencia_db": round(rms_dif_db, 1),
        "nota": ("Prácticamente idénticos (diferencia inaudible)." if silencio else
                 "Escuchá esto: es EXACTAMENTE lo que cambió entre las dos versiones."),
    }
