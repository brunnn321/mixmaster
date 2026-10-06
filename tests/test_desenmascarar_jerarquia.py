"""Test del desenmascarado por jerarquía entre todas las pistas. Sin pytest.

Uso:  .venv\\Scripts\\python tests\\test_desenmascarar_jerarquia.py
"""

import sys
from pathlib import Path

import numpy as np
from scipy import signal

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mixmaster.processing import _desenmascarar_jerarquia

SR = 44100
rng = np.random.default_rng(31)


def _estereo(x):
    return np.repeat(x.reshape(-1, 1), 2, axis=1)


def _banda_db(x, lo, hi):
    y = signal.sosfiltfilt(signal.butter(4, [lo, hi], "bandpass", fs=SR, output="sos"), x)
    return 20 * np.log10(np.sqrt(np.mean(y ** 2)) + 1e-12)


def main() -> int:
    fallos = []

    def check(nombre: str, cond: bool, detalle: str = ""):
        estado = "OK " if cond else "FAIL"
        print(f"[{estado}] {nombre}" + (f" - {detalle}" if detalle else ""))
        if not cond:
            fallos.append(nombre)

    n = SR * 6
    t = np.arange(n) / SR
    voz = _estereo(0.2 * np.sin(2 * np.pi * 900 * t) * (t < 3))         # canta solo al principio
    guitarra = _estereo(0.15 * np.sin(2 * np.pi * 1100 * t) + 0.3 * np.sin(2 * np.pi * 110 * t))
    bajo = _estereo(0.4 * np.sin(2 * np.pi * 100 * t))
    pistas = [voz.copy(), guitarra.copy(), bajo.copy()]
    info = _desenmascarar_jerarquia(pistas, ["voz_principal", "guitarra", "bajo"], SR)
    g = pistas[1][:, 0]
    canta = _banda_db(guitarra[SR // 2: SR * 5 // 2, 0], 1000, 1200) - _banda_db(g[SR // 2: SR * 5 // 2], 1000, 1200)
    calla = _banda_db(guitarra[SR * 4: SR * 6 - 200, 0], 1000, 1200) - _banda_db(g[SR * 4: SR * 6 - 200], 1000, 1200)
    sub = _banda_db(guitarra[SR: -SR, 0], 105, 115) - _banda_db(g[SR: -SR], 105, 115)
    check("jerarquía: la guitarra deja lugar a la voz en los medios", 1.5 < canta < 3.5, f"{canta:.1f} dB")
    check("jerarquía: cuando la voz calla, nada", abs(calla) < 0.3, f"{calla:+.2f} dB")
    check("jerarquía: la guitarra deja lugar al bajo en los graves", 2.0 < sub < 3.5, f"{sub:.1f} dB")
    check("jerarquía: la voz (manda en medios) no se toca en medios",
          abs(_banda_db(pistas[0][:, 0], 1000, 1200) - _banda_db(voz[:, 0], 1000, 1200)) < 0.1)
    check("jerarquía: informa por banda", bool(info), str(info).encode("ascii", "replace").decode())
    dos = [guitarra.copy(), _estereo(0.2 * rng.standard_normal(n))]
    copia = [d.copy() for d in dos]
    _desenmascarar_jerarquia(dos, ["guitarra", "guitarra"], SR)
    check("jerarquía: dos pistas del mismo tipo no se tocan",
          all(np.array_equal(a, b) for a, b in zip(dos, copia)))

    print()
    if fallos:
        print(f"RESULTADO: {len(fallos)} fallo(s): {fallos}")
        return 1
    print("RESULTADO: todos los checks pasaron")
    return 0


if __name__ == "__main__":
    sys.exit(main())
