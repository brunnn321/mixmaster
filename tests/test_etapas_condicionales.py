"""Cadena limpia que decide (21/11/2026): con barro en 200–400 Hz corta ahí y lo
explica; con una mezcla sana no corta nada.

Uso:  .venv\\Scripts\\python tests\\test_etapas_condicionales.py
"""

import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy import signal

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mixmaster.processing import config_limpia, masterizar  # noqa: E402

SR = 48000


def _mezcla(barro: bool) -> np.ndarray:
    rng = np.random.default_rng(3)
    ruido = rng.standard_normal((SR * 12, 2)) * 0.05
    b, a = signal.butter(1, 2000 / (SR / 2))           # caída suave de agudos, como música
    x = signal.lfilter(b, a, ruido, axis=0) + ruido * 0.2
    if barro:
        b, a = signal.butter(2, [220 / (SR / 2), 380 / (SR / 2)], "band")
        x = x + 3.0 * signal.lfilter(b, a, x, axis=0)
    return x * 0.5


def main() -> int:
    fallos = []

    def check(nombre, cond, detalle=""):
        print(f"[{'OK ' if cond else 'FAIL'}] {nombre}" + (f" — {detalle}" if detalle else ""))
        if not cond:
            fallos.append(nombre)

    tmp = Path(tempfile.mkdtemp())
    for caso in ("barro", "sana"):
        p = tmp / f"{caso}.wav"
        sf.write(p, _mezcla(caso == "barro"), SR, subtype="PCM_24")
        r = masterizar(p, None, -16.0, tmp / caso, tmp / caso, cfg=config_limpia())
        if caso == "barro":
            check("con barro corta en 300 Hz", "embarrado" in r["etapas"], str(r["etapas"]))
            check("explica la decisión", any("300 Hz" in d for d in r["decisiones"]), str(r["decisiones"]))
        else:
            check("mezcla sana: ningún corte de zona",
                  not set(r["etapas"]) & {"retumbe", "embarrado", "encajonado", "aspero", "sibilante"},
                  str(r["etapas"]))
        check(f"{caso}: QC antes y después", bool(r["qc_antes"]) and bool(r["qc_despues"]))

    print("RESULTADO:", "todos los checks pasaron" if not fallos else f"{len(fallos)} fallo(s): {fallos}")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
