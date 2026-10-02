"""Tests de la tanda 6 (investigación de calidad, ítems 17 y 10): EQ de fase
mixta y clipper solo en los golpes. Sin pytest.

Uso:  .venv\\Scripts\\python tests\\test_tanda6_calidad.py
"""

import sys
from pathlib import Path

import numpy as np
from scipy import signal

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mixmaster.processing import _aplicar_fir, _clipper, _clipper_transitorios, _curva_fir_fina

SR = 44100


def main() -> int:
    fallos = []

    def check(nombre: str, cond: bool, detalle: str = ""):
        estado = "OK " if cond else "FAIL"
        print(f"[{estado}] {nombre}" + (f" - {detalle}" if detalle else ""))
        if not cond:
            fallos.append(nombre)

    # --- 17. fase mixta
    freqs = np.geomspace(20, 20000, 31)
    curva = 6 * np.exp(-0.5 * (np.log2(freqs / 60)) ** 2) - 3 * np.exp(-0.5 * (np.log2(freqs / 2000)) ** 2)
    mixta = _curva_fir_fina(freqs, curva, SR, "mixta")
    lineal = _curva_fir_fina(freqs, curva, SR, "lineal")
    w, h = signal.freqz(mixta, worN=2 ** 16, fs=SR)
    for f0, esperado in ((60, curva[np.argmin(abs(freqs - 60))]), (2000, curva[np.argmin(abs(freqs - 2000))]),
                         (8000, curva[np.argmin(abs(freqs - 8000))])):
        real = 20 * np.log10(abs(h[np.argmin(abs(w - f0))]))
        check(f"fase mixta: magnitud correcta en {f0} Hz", abs(real - esperado) < 0.6,
              f"{real:+.2f} vs {esperado:+.2f} dB")
    impulso = np.zeros((SR, 1))
    impulso[SR // 2] = 1.0
    pre = lambda fir: float(np.sum(_aplicar_fir(impulso, fir)[: SR // 2 - 30, 0] ** 2))
    check("fase mixta: mucho menos pre-eco que la lineal", pre(mixta) < 0.2 * pre(lineal),
          f"{10 * np.log10(pre(mixta) / pre(lineal)):.1f} dB")
    plano = _curva_fir_fina(freqs, np.zeros_like(freqs), SR, "mixta")
    ruido = np.random.default_rng(1).standard_normal((SR, 1))
    check("fase mixta: curva plana no cambia la señal (retardo bien compensado)",
          np.allclose(_aplicar_fir(ruido, plano), ruido, atol=1e-3))

    # --- 10. clipper solo en los golpes
    t = np.arange(SR * 2) / SR
    sostenido = np.repeat((1.4 * np.sin(2 * np.pi * 100 * t)).reshape(-1, 1), 2, axis=1)
    toca = _clipper_transitorios(sostenido, SR, -0.5)
    check("clipper: una nota sostenida no se recorta",
          np.max(np.abs(toca[SR // 2: -SR // 2] - sostenido[SR // 2: -SR // 2])) < 0.05)
    golpe = np.zeros((SR, 2))
    golpe[SR // 2: SR // 2 + 200] = 1.6 * np.exp(-np.arange(200) / 40)[:, None]
    golpe[:, :] += 0.05 * np.sin(2 * np.pi * 200 * np.arange(SR) / SR)[:, None]
    rec = _clipper_transitorios(golpe, SR, -0.5)
    check("clipper: el golpe sí se recorta", np.max(np.abs(rec)) < 1.2,
          f"pico {np.max(np.abs(rec)):.2f}")
    check("clipper: igual al clipper normal en el golpe",
          abs(np.max(np.abs(rec)) - np.max(np.abs(_clipper(golpe, -0.5)))) < 0.15)

    print()
    if fallos:
        print(f"RESULTADO: {len(fallos)} fallo(s): {fallos}")
        return 1
    print("RESULTADO: todos los checks pasaron")
    return 0


if __name__ == "__main__":
    sys.exit(main())
