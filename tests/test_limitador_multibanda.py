"""Test del limitador multibanda: menos bombeo que el de banda completa,
mismo techo. Sin pytest.

Uso:  .venv\\Scripts\\python tests\\test_limitador_multibanda.py
"""

import sys
from pathlib import Path

import numpy as np
from scipy import signal

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mixmaster.audio_analysis import true_peak_db
from mixmaster.processing import _limitador, _limitador_multibanda, _limitar

SR = 44100
CFG = {"ceiling_dbtp": -1.0, "release_ms": 50, "lookahead_ms": 5}


def _db(x):
    return 20 * np.log10(np.sqrt(np.mean(x ** 2)) + 1e-12)


def main() -> int:
    fallos = []

    def check(nombre: str, cond: bool, detalle: str = ""):
        estado = "OK " if cond else "FAIL"
        print(f"[{estado}] {nombre}" + (f" - {detalle}" if detalle else ""))
        if not cond:
            fallos.append(nombre)

    n = SR * 6
    t = np.arange(n) / SR
    bombo = np.zeros(n)
    g = np.sin(2 * np.pi * 55 * t[: SR // 5]) * np.exp(-t[: SR // 5] / 0.08)
    for i in range(0, n - len(g), SR // 2):
        bombo[i: i + len(g)] += 1.4 * g
    guitarra = 0.25 * np.sin(2 * np.pi * 1500 * t)
    mezcla = np.repeat((bombo + guitarra).reshape(-1, 1), 2, axis=1)

    def bombeo(salida):
        """Cuánto baja la guitarra (banda 1–2 kHz) durante el golpe vs entre golpes."""
        sos = signal.butter(4, [1000, 2000], "bandpass", fs=SR, output="sos")
        gt = signal.sosfiltfilt(sos, salida[:, 0])
        en_golpe = np.concatenate([gt[i + SR // 50: i + SR // 12] for i in range(SR, n - SR, SR // 2)])
        entre = np.concatenate([gt[i + SR // 4: i + SR * 2 // 5] for i in range(SR, n - SR, SR // 2)])
        return _db(entre) - _db(en_golpe)

    banda_completa = _limitador(mezcla, SR, CFG)
    multi = _limitar(mezcla, SR, CFG)
    b_full, b_multi = bombeo(banda_completa), bombeo(multi)
    check("multibanda: la guitarra casi no baja con el bombo", b_multi < 0.5 * b_full,
          f"banda completa {b_full:.1f} dB, multibanda {b_multi:.1f} dB")
    check("multibanda: respeta el techo de true peak", true_peak_db(multi, SR) <= -0.95,
          f"{true_peak_db(multi, SR):.2f} dBTP")
    check("multibanda: sin NaN", bool(np.isfinite(multi).all()))
    tranquilo = 0.1 * mezcla
    check("multibanda: por debajo del techo no toca nada",
          np.allclose(_limitador_multibanda(tranquilo, SR, CFG), tranquilo, atol=1e-6))

    print()
    if fallos:
        print(f"RESULTADO: {len(fallos)} fallo(s): {fallos}")
        return 1
    print("RESULTADO: todos los checks pasaron")
    return 0


if __name__ == "__main__":
    sys.exit(main())
