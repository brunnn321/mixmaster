"""Test de recortar_silencio_extremos (top-and-tail, pendiente URGENTE
tanda real 2026-08-09). Sin pytest.

Uso:  .venv\\Scripts\\python tests\\test_top_and_tail.py
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mixmaster.audio_analysis import recortar_silencio_extremos

SR = 44100


def _tono(freq_hz: float, dur_s: float) -> np.ndarray:
    t = np.arange(int(SR * dur_s)) / SR
    señal = 0.5 * np.sin(2 * np.pi * freq_hz * t)
    return np.repeat(señal.reshape(-1, 1), 2, axis=1)


def _silencio(dur_s: float) -> np.ndarray:
    return np.zeros((int(SR * dur_s), 2))


def main() -> int:
    fallos = []

    def check(nombre: str, cond: bool, detalle: str = ""):
        estado = "OK " if cond else "FAIL"
        print(f"[{estado}] {nombre}" + (f" — {detalle}" if detalle else ""))
        if not cond:
            fallos.append(nombre)

    # caso 1: 2s de silencio real + 1s de tono + 1.5s de silencio real
    audio = np.concatenate([_silencio(2.0), _tono(440, 1.0), _silencio(1.5)])
    recortado, ini_s, fin_s = recortar_silencio_extremos(audio, SR)
    check("recorta ~2s del inicio", abs(ini_s - 2.0) < 0.01, str(ini_s))
    check("recorta ~1.5s del final", abs(fin_s - 1.5) < 0.01, str(fin_s))
    check("largo resultante ~1s de audio", abs(len(recortado) / SR - 1.0) < 0.01)

    # caso 2: sin silencio en los extremos -> no recorta nada
    audio2 = _tono(440, 1.0)
    recortado2, ini2, fin2 = recortar_silencio_extremos(audio2, SR)
    # tolerancia: el tono arranca en 0 (cruce por cero), esa única muestra
    # es silencio real — no hay nada mal en recortarla.
    check("sin silencio: no recorta (tolerancia 1ms)", ini2 < 0.001 and fin2 < 0.001)
    check("sin silencio: largo casi intacto", len(recortado2) >= len(audio2) - 1)

    # caso 3: todo silencio -> caso degenerado, no toca nada
    audio3 = _silencio(1.0)
    recortado3, ini3, fin3 = recortar_silencio_extremos(audio3, SR)
    check("todo silencio: no recorta (degenerado)", ini3 == 0.0 and fin3 == 0.0)
    check("todo silencio: largo intacto", len(recortado3) == len(audio3))

    # caso 4: material bajo pero real (-40dBFS) en los extremos NO se recorta
    # (umbral es -60dBFS, holgado a propósito)
    bajo = 0.01 * np.sin(2 * np.pi * 440 * np.arange(int(SR * 0.5)) / SR)  # ~ -40dBFS
    bajo = np.repeat(bajo.reshape(-1, 1), 2, axis=1)
    audio4 = np.concatenate([bajo, _tono(440, 1.0)])
    recortado4, ini4, fin4 = recortar_silencio_extremos(audio4, SR)
    check("material bajo pero real: NO se recorta", ini4 == 0.0, str(ini4))

    print()
    if fallos:
        print(f"RESULTADO: {len(fallos)} fallo(s): {fallos}")
        return 1
    print("RESULTADO: todos los checks pasaron")
    return 0


if __name__ == "__main__":
    sys.exit(main())
