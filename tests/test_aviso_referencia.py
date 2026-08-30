"""Test del aviso de referencia que no calza en timbre (pendiente #4, tanda
real 2026-08-09). Sin pytest.

Uso:  .venv\\Scripts\\python tests\\test_aviso_referencia.py
"""

import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mixmaster.processing import masterizar

SR = 44100


def _ruido_banda(dur_s, f_lo, f_hi, seed):
    """Ruido filtrado a una banda -> perfil espectral concentrado ahí,
    para poder controlar a propósito qué tan lejos está mix de referencia."""
    from scipy import signal
    rng = np.random.default_rng(seed)
    n = int(SR * dur_s)
    ruido = rng.normal(0, 0.3, n)
    sos = signal.butter(4, [max(f_lo, 20), min(f_hi, SR / 2 - 1)], "bandpass", fs=SR, output="sos")
    filtrado = signal.sosfilt(sos, ruido)
    filtrado = filtrado / (np.max(np.abs(filtrado)) + 1e-9) * 0.7
    return np.repeat(filtrado.reshape(-1, 1), 2, axis=1)


def main() -> int:
    fallos = []

    def check(nombre: str, cond: bool, detalle: str = ""):
        estado = "OK " if cond else "FAIL"
        print(f"[{estado}] {nombre}" + (f" — {detalle}" if detalle else ""))
        if not cond:
            fallos.append(nombre)

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)

        mezcla = _ruido_banda(4.0, 100, 400, seed=1)     # grave/low_mid
        p_mezcla = tmp / "mezcla.wav"
        sf.write(str(p_mezcla), mezcla, SR, subtype="PCM_24")

        # referencia LEJOS: energía casi toda en agudos -> distancia grande
        ref_lejos = _ruido_banda(4.0, 6000, 12000, seed=2)
        p_ref_lejos = tmp / "ref_lejos.wav"
        sf.write(str(p_ref_lejos), ref_lejos, SR, subtype="PCM_24")

        resumen_lejos = masterizar(p_mezcla, p_ref_lejos, -14.0, tmp / "m1", tmp / "e1")
        print(f"    distancia_referencia_db (lejos): {resumen_lejos['distancia_referencia_db']}")
        check("referencia lejos: trae el campo distancia_referencia_db",
              bool(resumen_lejos.get("distancia_referencia_db")))
        check("referencia lejos: dispara el aviso de no-calza",
              resumen_lejos.get("aviso_referencia_no_calza") is not None,
              str(resumen_lejos.get("aviso_referencia_no_calza")))

        # referencia CERCA: misma banda que la mezcla -> distancia chica
        ref_cerca = _ruido_banda(4.0, 100, 400, seed=3)
        p_ref_cerca = tmp / "ref_cerca.wav"
        sf.write(str(p_ref_cerca), ref_cerca, SR, subtype="PCM_24")

        resumen_cerca = masterizar(p_mezcla, p_ref_cerca, -14.0, tmp / "m2", tmp / "e2")
        print(f"    distancia_referencia_db (cerca): {resumen_cerca['distancia_referencia_db']}")
        check("referencia cerca: NO dispara el aviso",
              resumen_cerca.get("aviso_referencia_no_calza") is None,
              str(resumen_cerca.get("aviso_referencia_no_calza")))

    print()
    if fallos:
        print(f"RESULTADO: {len(fallos)} fallo(s): {fallos}")
        return 1
    print("RESULTADO: todos los checks pasaron")
    return 0


if __name__ == "__main__":
    sys.exit(main())
