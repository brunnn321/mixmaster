"""Test del control del grave (7/10, herramienta top 7): el sub del bajo cede
cuando pega el bombo y vuelve entre golpes; arriba de 120 Hz no se toca.
Sin pytest.

Uso:  .venv\\Scripts\\python tests\\test_control_grave.py
"""

import sys
from pathlib import Path

import numpy as np
from scipy import signal

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mixmaster.processing import _control_grave

SR = 44100
DUR = 4.0
t = np.arange(int(SR * DUR)) / SR
fallos = []


def check(nombre, ok, detalle=""):
    print(f"[{'OK ' if ok else 'FAIL'}] {nombre} — {detalle}")
    if not ok:
        fallos.append(nombre)


def estereo(x):
    return np.repeat(x.reshape(-1, 1), 2, axis=1)


def nivel_db(x, f, i0, i1):
    seg = x[i0:i1]
    tt = np.arange(len(seg)) / SR
    return 20 * np.log10(abs(np.sum(seg * np.exp(-2j * np.pi * f * tt))) / len(seg) + 1e-12)


# bombo: golpes de 60 Hz cada 0.5 s que se apagan en ~60 ms
kick = np.zeros_like(t)
golpes = np.arange(0.25, DUR, 0.5)
for g in golpes:
    i = int(g * SR)
    n = int(0.15 * SR)
    kick[i:i + n] += np.sin(2 * np.pi * 60 * t[:n]) * np.exp(-t[:n] / 0.06)
# bajo: 45 Hz sostenido + 400 Hz (lo que está arriba del corte)
bajo = 0.5 * np.sin(2 * np.pi * 45 * t) + 0.3 * np.sin(2 * np.pi * 400 * t)

pistas = [estereo(kick), estereo(bajo.copy())]
info = _control_grave(pistas, ["kick", "bajo"], SR)
salida = pistas[1][:, 0]

g = int(golpes[3] * SR)
en_golpe = (g + int(0.005 * SR), g + int(0.045 * SR))
entre = (g + int(0.35 * SR), g + int(0.45 * SR))
d_golpe = nivel_db(salida, 45, *en_golpe) - nivel_db(bajo, 45, *en_golpe)
d_entre = nivel_db(salida, 45, *entre) - nivel_db(bajo, 45, *entre)
d_400 = nivel_db(salida, 400, *en_golpe) - nivel_db(bajo, 400, *en_golpe)

check("el sub del bajo baja cuando pega el bombo", -4.5 < d_golpe < -1.5, f"{d_golpe:+.2f} dB")
check("entre golpes el sub vuelve", abs(d_entre) < 0.5, f"{d_entre:+.2f} dB")
check("arriba de 120 Hz el bajo no se toca", abs(d_400) < 0.3, f"{d_400:+.2f} dB")
check("el informe trae la reducción", info.get("reduccion_max_db", 0) < -1, str(info))
check("sin bombo no hace nada", _control_grave([estereo(bajo)], ["bajo"], SR) == {}, "")

print(f"\nRESULTADO: {'todos los checks pasaron' if not fallos else f'{len(fallos)} fallo(s): {fallos}'}")
sys.exit(1 if fallos else 0)
