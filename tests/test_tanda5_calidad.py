"""Tests de la tanda 5 (investigación de calidad, ítems 6 parte 2, 11 y 21):
desenmascarado de la voz, resonancias dinámicas y apertura de mezclas mono.
Sin pytest.

Uso:  .venv\\Scripts\\python tests\\test_tanda5_calidad.py
"""

import sys
from pathlib import Path

import numpy as np
from scipy import signal

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mixmaster.processing import _abrir_mono, _desenmascarar_voz, _resonancias_dinamicas

SR = 44100
rng = np.random.default_rng(5)


def _estereo(x: np.ndarray) -> np.ndarray:
    return np.repeat(x.reshape(-1, 1), 2, axis=1)


def _banda_db(x: np.ndarray, f_lo: float, f_hi: float) -> float:
    sos = signal.butter(4, [f_lo, f_hi], "bandpass", fs=SR, output="sos")
    y = signal.sosfiltfilt(sos, x)
    return 20 * np.log10(np.sqrt(np.mean(y ** 2)) + 1e-12)


def main() -> int:
    fallos = []

    def check(nombre: str, cond: bool, detalle: str = ""):
        estado = "OK " if cond else "FAIL"
        print(f"[{estado}] {nombre}" + (f" - {detalle}" if detalle else ""))
        if not cond:
            fallos.append(nombre)

    t = np.arange(SR * 6) / SR

    # --- 11. resonancias dinámicas
    ruido = 0.05 * rng.standard_normal(len(t))
    con_pico = _estereo(ruido + 0.2 * np.sin(2 * np.pi * 3000 * t))
    y, media = _resonancias_dinamicas(con_pico, SR, 1000, 10000, 3.0, 0.5, 6.0, 100.0)
    check("resonancias: sin NaN y mismo largo",
          bool(np.isfinite(y).all()) and y.shape == con_pico.shape)
    baja = _banda_db(con_pico[:, 0], 2900, 3100) - _banda_db(y[:, 0], 2900, 3100)
    check("resonancias: baja el pico de 3 kHz", baja > 2.0, f"{baja:.1f} dB")
    fuera = _banda_db(con_pico[:, 0], 300, 700) - _banda_db(y[:, 0], 300, 700)
    check("resonancias: fuera de la banda no toca", abs(fuera) < 0.3, f"{fuera:+.2f} dB")
    plano = _estereo(ruido)
    y2, _ = _resonancias_dinamicas(plano, SR, 1000, 10000, 3.0, 0.5, 6.0, 100.0)
    dif = _banda_db(plano[:, 0], 1000, 10000) - _banda_db(y2[:, 0], 1000, 10000)
    check("resonancias: ruido sin picos casi no cambia", dif < 1.0, f"{dif:.2f} dB")

    # --- 21. abrir mono
    mono = _estereo(signal.sosfilt(signal.butter(2, 5000, fs=SR, output="sos"),
                                   rng.standard_normal(len(t))) * 0.2)
    abierto, corr = _abrir_mono(mono, SR)
    c_out = float(np.corrcoef(abierto[:, 0], abierto[:, 1])[0, 1])
    check("mono: detecta la mezcla mono", corr is not None and corr > 0.99)
    check("mono: queda abierta cerca de 0.7", 0.6 < c_out < 0.8, f"{c_out:.2f}")
    check("mono: la suma mono no cambia",
          np.allclose(abierto.sum(axis=1), mono.sum(axis=1)))
    estereo = np.stack([rng.standard_normal(len(t)), rng.standard_normal(len(t))], axis=1) * 0.1
    igual, c2 = _abrir_mono(estereo, SR)
    check("mono: una mezcla estéreo no se toca", c2 is None and np.array_equal(igual, estereo))

    # --- 6 parte 2. desenmascarado
    voz = _estereo(0.2 * np.sin(2 * np.pi * 2000 * t) * (t < 3))
    guitarra = _estereo(0.3 * rng.standard_normal(len(t)))  # compite con la voz en 1-4 kHz
    pistas = [voz.copy(), guitarra.copy()]
    red = _desenmascarar_voz(pistas, ["voz_principal", "guitarra"], SR)
    g = pistas[1][:, 0]
    canta = _banda_db(guitarra[SR // 2: SR * 5 // 2, 0], 1500, 3000) - _banda_db(g[SR // 2: SR * 5 // 2], 1500, 3000)
    calla = _banda_db(guitarra[SR * 4: SR * 6 - 100, 0], 1500, 3000) - _banda_db(g[SR * 4: SR * 6 - 100], 1500, 3000)
    graves = _banda_db(guitarra[:, 0], 100, 400) - _banda_db(g, 100, 400)
    check("desenmascarado: la guitarra baja en 1-4 kHz mientras canta", 2.0 < canta < 4.0,
          f"{canta:.1f} dB (media {red:.1f})")
    check("desenmascarado: cuando la voz calla, nada", abs(calla) < 0.3, f"{calla:+.2f} dB")
    check("desenmascarado: fuera de la banda, nada", abs(graves) < 0.3, f"{graves:+.2f} dB")
    check("desenmascarado: la voz no se toca", np.array_equal(pistas[0], voz))

    print()
    if fallos:
        print(f"RESULTADO: {len(fallos)} fallo(s): {fallos}")
        return 1
    print("RESULTADO: todos los checks pasaron")
    return 0


if __name__ == "__main__":
    sys.exit(main())
