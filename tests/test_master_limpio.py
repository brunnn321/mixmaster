"""Cadena Limpia (21/11/2026): llega al LUFS pedido, respeta el techo true-peak
y no toca la imagen estéreo.

Uso:  .venv\\Scripts\\python tests\\test_master_limpio.py
"""

import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mixmaster.audio_analysis import analisis_estereo, cargar_audio, true_peak_db  # noqa: E402
from mixmaster.processing import config_limpia, masterizar  # noqa: E402

SR = 48000


def main() -> int:
    fallos = []

    def check(nombre, cond, detalle=""):
        print(f"[{'OK ' if cond else 'FAIL'}] {nombre}" + (f" — {detalle}" if detalle else ""))
        if not cond:
            fallos.append(nombre)

    t = np.arange(SR * 20) / SR
    rng = np.random.default_rng(1)
    golpe = np.sin(2 * np.pi * 55 * t) * np.exp(-((t % 0.5) * 12)) * 0.5
    l = golpe + 0.08 * np.sin(2 * np.pi * 220 * t) + 0.03 * rng.standard_normal(len(t))
    r = golpe + 0.08 * np.sin(2 * np.pi * 330 * t) + 0.03 * rng.standard_normal(len(t))
    tmp = Path(tempfile.mkdtemp())
    mezcla = tmp / "mezcla.wav"
    sf.write(mezcla, np.stack([l, r], 1) * 0.3, SR, subtype="PCM_24")

    cfg = config_limpia()
    # a -16 LUFS el limitador casi no trabaja: así se mide la cadena y no el limitado
    res = masterizar(mezcla, None, -16.0, tmp, tmp, cfg=cfg)
    check("LUFS en objetivo", abs(res["lufs_final"] + 16.0) <= 0.5, f"lufs={res['lufs_final']}")
    a, sr = cargar_audio(Path(res["wav"]))
    tp = true_peak_db(a, sr)
    check("true peak bajo techo", tp <= cfg["limitador"]["ceiling_dbtp"] + 0.1, f"tp={tp:.2f}")
    c_in = analisis_estereo(*cargar_audio(mezcla))["correlacion_global"]
    c_out = analisis_estereo(a, sr)["correlacion_global"]
    # la cadena limpia nunca procesa el lado (side) ni el ancho: lo que corrige va
    # igual en L y R (un corte de zona puede mover la correlación, y está bien)
    check("no toca el ancho ni el side", not res["ajuste_ancho_db"] and not res["eq_side_db"],
          f"{c_in:.2f} → {c_out:.2f} {res['etapas']}")
    check("nombre marca la cadena limpia", Path(res["wav"]).stem.endswith("_limpio"))

    print("RESULTADO:", "todos los checks pasaron" if not fallos else f"{len(fallos)} fallo(s): {fallos}")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
