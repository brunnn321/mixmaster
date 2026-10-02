"""Tests de la tanda 8 (investigación de calidad, ítems 22, 23 y 24):
dinámica por grupo, consola optimizada y EQ perceptual. Sin pytest.

Uso:  .venv\\Scripts\\python tests\\test_tanda8_calidad.py
"""

import sys
from pathlib import Path

import numpy as np
from scipy import signal

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mixmaster.audio_analysis import espectro_suavizado, rango_corto_db
from mixmaster.processing import _consola_optimizada, _dinamica_por_grupo, _eq_perceptual

SR = 44100
rng = np.random.default_rng(13)


def _estereo(x: np.ndarray) -> np.ndarray:
    return np.repeat(x.reshape(-1, 1), 2, axis=1)


def _banda(x: np.ndarray, lo: float, hi: float) -> np.ndarray:
    return signal.sosfiltfilt(signal.butter(4, [lo, hi], "bandpass", fs=SR, output="sos"), x)


def _db(x: np.ndarray) -> float:
    return 20 * np.log10(np.sqrt(np.mean(x ** 2)) + 1e-12)


def main() -> int:
    fallos = []

    def check(nombre: str, cond: bool, detalle: str = ""):
        estado = "OK " if cond else "FAIL"
        print(f"[{estado}] {nombre}" + (f" - {detalle}" if detalle else ""))
        if not cond:
            fallos.append(nombre)

    n = SR * 8

    # --- 22. dinámica por grupo
    golpes = np.zeros(n)
    g = rng.standard_normal(int(0.2 * SR)) * np.exp(-np.arange(int(0.2 * SR)) / (0.03 * SR))
    for i in range(0, n - len(g), SR // 2):
        golpes[i: i + len(g)] += 0.6 * g
    golpes += 0.01 * rng.standard_normal(n)
    guit = _estereo(0.2 * rng.standard_normal(n))
    pistas = [_estereo(golpes), _estereo(golpes * 0.5), guit.copy()]
    roles = ["kick", "snare", "guitarra"]
    r_antes = rango_corto_db((pistas[0] + pistas[1]).mean(axis=1), SR)[0]
    hecho = _dinamica_por_grupo(pistas, roles, SR, {"drums": r_antes / 2, "other": None})
    r_despues = rango_corto_db((pistas[0] + pistas[1]).mean(axis=1), SR)[0]
    check("grupos: la batería se acerca al rango de la ref",
          abs(r_despues - r_antes / 2) < abs(r_antes - r_antes / 2) / 2,
          f"{r_antes:.1f} -> {r_despues:.1f} (ref {r_antes / 2:.1f})")
    check("grupos: el balance interno de la batería se mantiene",
          abs(_db(pistas[0]) - _db(pistas[1]) - 6.02) < 0.05)
    check("grupos: la guitarra (sin dato de ref) no se toca", np.array_equal(pistas[2], guit))
    check("grupos: informa solo lo que tocó", set(hecho) == {"drums"}, str(hecho))

    # --- 23. consola optimizada
    t = np.arange(n) / SR
    bat = _estereo(golpes)
    gtr = _estereo(_banda(rng.standard_normal(n), 100, 8000) * 0.2)
    freqs, esp_bat = espectro_suavizado(bat, SR)
    _, esp_gtr = espectro_suavizado(gtr, SR)
    inclinacion = -4 * np.log2(np.asarray(freqs) / 1000) / 3   # la ref: guitarras más oscuras
    medidas = {"freqs": list(freqs),
               "espectro": {"drums": list(esp_bat), "other": list(esp_gtr + inclinacion)}}
    pistas = [bat.copy(), gtr.copy()]
    params = _consola_optimizada(pistas, ["kick", "guitarra"], SR, medidas, {"other"}, pasos=200)
    _, esp_nuevo = espectro_suavizado(pistas[1], SR)
    util = (np.asarray(freqs) > 150) & (np.asarray(freqs) < 7000)
    forma = lambda x: x[util] - x[util].mean()
    err_antes = np.mean((forma(esp_gtr) - forma(esp_gtr + inclinacion)) ** 2)
    err_despues = np.mean((forma(esp_nuevo) - forma(esp_gtr + inclinacion)) ** 2)
    check("consola: la forma de las guitarras se acerca a la ref", err_despues < 0.7 * err_antes,
          f"{err_antes:.2f} -> {err_despues:.2f}")
    check("consola: la batería (sin permiso de EQ) solo cambia de ganancia",
          params.get("drums", {}).get("eq_db") == [0.0, 0.0, 0.0], str(params.get("drums")))

    # --- 24. EQ perceptual
    domina = _banda(rng.standard_normal(n), 900, 1100)
    tapada = _banda(rng.standard_normal(n), 1150, 1300)
    domina *= 0.3 / np.sqrt(np.mean(domina ** 2))
    tapada *= 0.3 * 10 ** (-16 / 20) / np.sqrt(np.mean(tapada ** 2))
    mezcla = _estereo(domina + tapada + 0.001 * rng.standard_normal(n))
    y, cambio = _eq_perceptual(mezcla, SR, 2.0, 2.0)
    d_dom = _db(_banda(y[:, 0], 900, 1100)) - _db(_banda(mezcla[:, 0], 900, 1100))
    d_tap = _db(_banda(y[:, 0], 1150, 1300)) - _db(_banda(mezcla[:, 0], 1150, 1300))
    check("perceptual: sin NaN y mismo largo", bool(np.isfinite(y).all()) and y.shape == mezcla.shape)
    check("perceptual: la banda tapada gana frente a la dominante", d_tap - d_dom > 0.5,
          f"domina {d_dom:+.2f} dB, tapada {d_tap:+.2f} dB")
    check("perceptual: cambios acotados (±2 dB)", abs(d_dom) <= 2.1 and abs(d_tap) <= 2.1)

    print()
    if fallos:
        print(f"RESULTADO: {len(fallos)} fallo(s): {fallos}")
        return 1
    print("RESULTADO: todos los checks pasaron")
    return 0


if __name__ == "__main__":
    sys.exit(main())
