"""Test de EQ y compresión por sección (12/10, herramienta top 8): un
estribillo cargado de medios graves se acerca al balance del tema, la estrofa
casi no cambia y sin margen la salida es idéntica a la entrada. Sin pytest.

Uso:  .venv\\Scripts\\python tests\\test_eq_por_seccion.py
"""

import sys
from pathlib import Path

import numpy as np
from scipy import signal

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mixmaster.processing import _eq_comp_por_seccion

SR = 44100
rng = np.random.default_rng(8)
fallos = []


def check(nombre, ok, detalle=""):
    print(f"[{'OK ' if ok else 'FAIL'}] {nombre} — {detalle}")
    if not ok:
        fallos.append(nombre)


def banda(x, lo, hi):
    return signal.sosfiltfilt(signal.butter(4, [lo, hi], "bandpass", fs=SR, output="sos"), x, axis=0)


def db(x):
    return 10 * np.log10(np.mean(x ** 2) + 1e-12)


# 4 secciones de 8 s: estrofa, estribillo, estrofa, estribillo
base = signal.sosfiltfilt(signal.butter(2, 4000, "lowpass", fs=SR, output="sos"),
                          rng.standard_normal((int(SR * 32), 2)), axis=0) * 0.1
seccion = int(SR * 8)
audio = base.copy()
for k in (1, 3):   # estribillos: +6 dB en 250–500 Hz y +3 dB en general
    s = slice(k * seccion, (k + 1) * seccion)
    audio[s] = (audio[s] + banda(audio[s], 250, 500) * 1.0) * 1.41

out, info = _eq_comp_por_seccion(audio, SR)


def exceso_medios(x, k):
    s = slice(k * seccion + SR, (k + 1) * seccion - SR)
    return db(banda(x[s], 250, 500)) - db(x[s])


antes = exceso_medios(audio, 3) - exceso_medios(audio, 2)
despues = exceso_medios(out, 3) - exceso_medios(out, 2)
check("el estribillo cargado se acerca al balance de la estrofa", despues < antes - 1.0,
      f"diferencia de medios graves {antes:.1f} → {despues:.1f} dB")
s2 = slice(2 * seccion + 2 * SR, 3 * seccion - 2 * SR)
cambio_estrofa = db(out[s2]) - db(audio[s2])
check("la estrofa casi no cambia de nivel", abs(cambio_estrofa) < 1.0, f"{cambio_estrofa:+.2f} dB")
check("respeta los topes", info["eq_max_db"] <= 2.0 and info["comp_max_db"] <= 1.5, str(info))
neutro, _ = _eq_comp_por_seccion(audio, SR, max_eq_db=0.0, max_comp_db=0.0)
check("sin margen la salida es igual a la entrada", np.max(np.abs(neutro - audio)) < 1e-9,
      f"dif máx {np.max(np.abs(neutro - audio)):.1e}")

print(f"\nRESULTADO: {'todos los checks pasaron' if not fallos else f'{len(fallos)} fallo(s): {fallos}'}")
sys.exit(1 if fallos else 0)
