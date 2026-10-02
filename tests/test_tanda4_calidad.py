"""Tests de la tanda 4 (investigación de calidad, ítems 5, 13 y 19):
cadena de voz, bus del master y estribillos que levantan. Sin pytest.

Uso:  .venv\\Scripts\\python tests\\test_tanda4_calidad.py
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mixmaster.processing import _bus_master, _cadena_voz, _levantar_estribillos

SR = 44100
rng = np.random.default_rng(11)


def _estereo(x: np.ndarray) -> np.ndarray:
    return np.repeat(x.reshape(-1, 1), 2, axis=1)


def _rms_db(x: np.ndarray) -> float:
    return 20 * np.log10(np.sqrt(np.mean(x ** 2)) + 1e-12)


def _nivel_db(x: np.ndarray, f: float) -> float:
    t = np.arange(len(x)) / SR
    return 20 * np.log10(abs(np.sum(x * np.exp(-2j * np.pi * f * t))) + 1e-12)


def main() -> int:
    fallos = []

    def check(nombre: str, cond: bool, detalle: str = ""):
        estado = "OK " if cond else "FAIL"
        print(f"[{estado}] {nombre}" + (f" - {detalle}" if detalle else ""))
        if not cond:
            fallos.append(nombre)

    # --- 5. cadena de voz: una frase floja (-8 dB) y una fuerte
    t = np.arange(SR * 4) / SR
    silaba = np.sin(2 * np.pi * 220 * t) * (0.6 + 0.4 * np.sin(2 * np.pi * 4 * t))
    voz = silaba * np.where(t < 2, 10 ** (-8 / 20), 1.0) * 0.3
    entrada = _estereo(voz)
    salida = _cadena_voz(entrada, SR)
    dif_in = _rms_db(entrada[SR // 4: SR * 7 // 4, 0]) - _rms_db(entrada[SR * 9 // 4: SR * 15 // 4, 0])
    dif_out = _rms_db(salida[SR // 4: SR * 7 // 4, 0]) - _rms_db(salida[SR * 9 // 4: SR * 15 // 4, 0])
    check("voz: sin NaN", bool(np.isfinite(salida).all()))
    check("voz: las frases quedan más parejas", abs(dif_out) < abs(dif_in) - 4,
          f"{dif_in:+.1f} -> {dif_out:+.1f} dB")
    check("voz: conserva el RMS", abs(_rms_db(salida) - _rms_db(entrada)) < 0.1)

    # --- 13. bus del master
    tono = _estereo(0.5 * np.sin(2 * np.pi * 1000 * t))
    cinta, red = _bus_master(tono, SR, "cinta", 1.3)
    valv, _ = _bus_master(tono, SR, "valvula", 1.3)
    check("bus: sin NaN", bool(np.isfinite(cinta).all() and np.isfinite(valv).all()))
    check("bus: conserva el RMS", abs(_rms_db(cinta) - _rms_db(tono)) < 0.1)
    check("bus cinta: agrega 3er armónico, no 2do",
          _nivel_db(cinta[:, 0], 3000) > _nivel_db(cinta[:, 0], 2000) + 20)
    check("bus válvula: agrega 2do armónico",
          _nivel_db(valv[:, 0], 2000) > _nivel_db(cinta[:, 0], 2000) + 20)

    # --- 19. estribillos
    n = SR * 40
    tt = np.arange(n) / SR
    base = 0.1 * rng.standard_normal(n)
    total = _estereo(base * np.where((tt > 20) & (tt < 32), 10 ** (6 / 20), 1.0))
    capas = _estereo(0.05 * np.sin(2 * np.pi * 300 * tt))
    capas[:, 1] *= 0.5  # algo de side
    delta, frac = _levantar_estribillos(total, capas, SR)
    nuevo = capas + delta
    sube = _rms_db(nuevo[SR * 24: SR * 28]) - _rms_db(capas[SR * 24: SR * 28])
    quieto = _rms_db(nuevo[SR * 5: SR * 15]) - _rms_db(capas[SR * 5: SR * 15])
    check("estribillos: marca la parte fuerte", 0.2 < frac < 0.45, f"{frac:.2f}")
    check("estribillos: las capas suben ~1 dB en el estribillo", 0.7 < sube < 1.6, f"{sube:+.2f} dB")
    check("estribillos: la estrofa no cambia", abs(quieto) < 0.05, f"{quieto:+.3f} dB")
    lado_in = np.std(capas[SR * 24: SR * 28, 0] - capas[SR * 24: SR * 28, 1])
    lado_out = np.std(nuevo[SR * 24: SR * 28, 0] - nuevo[SR * 24: SR * 28, 1])
    check("estribillos: se abre el estéreo", lado_out > lado_in * 1.1)
    plano = _estereo(0.1 * rng.standard_normal(n))
    d0, f0 = _levantar_estribillos(plano, capas, SR)
    check("estribillos: tema parejo no cambia", f0 == 0.0 or np.max(np.abs(d0)) < 1e-3, f"{f0:.2f}")

    print()
    if fallos:
        print(f"RESULTADO: {len(fallos)} fallo(s): {fallos}")
        return 1
    print("RESULTADO: todos los checks pasaron")
    return 0


if __name__ == "__main__":
    sys.exit(main())
