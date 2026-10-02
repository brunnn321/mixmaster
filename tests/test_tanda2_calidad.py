"""Tests de la tanda 2/10 (investigación de calidad, ítems 16 y 18):
exciter de graves y no linealidades a 2x. El ítem 12 (MP3 decodificado)
lo recorre test_smoke.py al masterizar. Sin pytest.

Uso:  .venv\\Scripts\\python tests\\test_tanda2_calidad.py
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mixmaster.processing import _a_2x, _clipper, _exciter_graves

SR = 44100


def _estereo(x: np.ndarray) -> np.ndarray:
    return np.repeat(x.reshape(-1, 1), 2, axis=1)


def _energia(x: np.ndarray, f_lo: float, f_hi: float) -> float:
    esp = np.abs(np.fft.rfft(x)) ** 2
    f = np.fft.rfftfreq(len(x), 1 / SR)
    return float(esp[(f >= f_lo) & (f < f_hi)].sum())


def main() -> int:
    fallos = []

    def check(nombre: str, cond: bool, detalle: str = ""):
        estado = "OK " if cond else "FAIL"
        print(f"[{estado}] {nombre}" + (f" - {detalle}" if detalle else ""))
        if not cond:
            fallos.append(nombre)

    t = np.arange(SR * 2) / SR

    # --- 18. clipper a 2x: menos aliasing
    # 15 kHz recortado: el 3er armónico (45 kHz) se refleja a 900 Hz a 44.1 kHz
    tono = _estereo(1.5 * np.sin(2 * np.pi * 15000 * t))
    directo = _clipper(tono, -0.5)[:, 0]
    a2x = _a_2x(_clipper, tono, -0.5)[:, 0]
    alias_d, alias_2x = _energia(directo, 500, 1300), _energia(a2x, 500, 1300)
    check("clipper a 2x: menos aliasing que directo", alias_2x < 0.3 * alias_d,
          f"{10 * np.log10(alias_2x / alias_d):.1f} dB")
    check("clipper a 2x: mismo largo y sin NaN",
          a2x.shape[0] == tono.shape[0] and bool(np.isfinite(a2x).all()))

    # --- 16. exciter de graves
    mezcla = np.stack([0.4 * np.sin(2 * np.pi * 60 * t) + 0.05 * np.sin(2 * np.pi * 1000 * t),
                       0.4 * np.sin(2 * np.pi * 60 * t) - 0.05 * np.sin(2 * np.pi * 1000 * t)],
                      axis=1)
    out = _exciter_graves(mezcla, SR, 40.0, 100.0, 0.25)
    check("exciter: sin NaN", bool(np.isfinite(out).all()))
    check("exciter: suma armónicos en 100-400 Hz",
          _energia(out[:, 0], 100, 400) > 100 * _energia(mezcla[:, 0], 100, 400))
    side_in = mezcla[:, 0] - mezcla[:, 1]
    side_out = out[:, 0] - out[:, 1]
    check("exciter: no toca el side (grave sigue mono)", np.allclose(side_in, side_out))
    fund_in, fund_out = _energia(mezcla[:, 0], 50, 70), _energia(out[:, 0], 50, 70)
    check("exciter: la fundamental queda casi igual",
          abs(10 * np.log10(fund_out / fund_in)) < 0.5,
          f"{10 * np.log10(fund_out / fund_in):+.2f} dB")
    check("exciter: cantidad 0 no cambia nada",
          np.array_equal(_exciter_graves(mezcla, SR, 40.0, 100.0, 0.0), mezcla))

    print()
    if fallos:
        print(f"RESULTADO: {len(fallos)} fallo(s): {fallos}")
        return 1
    print("RESULTADO: todos los checks pasaron")
    return 0


if __name__ == "__main__":
    sys.exit(main())
