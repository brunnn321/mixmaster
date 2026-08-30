"""Test del aviso de sobre-limitación/sub-procesamiento por crest fuera de
zona (pendiente #2, tanda real 2026-08-09). Sin pytest.

Uso:  .venv\\Scripts\\python tests\\test_aviso_crest.py
"""

import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mixmaster.processing import masterizar

SR = 44100


def _ruido_dinamico(dur_s: float, seed: int) -> np.ndarray:
    """Ruido con envolvente muy variable -> crest alto (sub-procesado)."""
    rng = np.random.default_rng(seed)
    n = int(SR * dur_s)
    t = np.arange(n) / SR
    envolvente = 0.5 + 0.5 * np.sign(np.sin(2 * np.pi * 0.2 * t))  # pulsos duros
    señal = rng.normal(0, 0.3, n) * envolvente
    señal = señal / (np.max(np.abs(señal)) + 1e-9) * 0.9
    return np.repeat(señal.reshape(-1, 1), 2, axis=1)


def main() -> int:
    fallos = []

    def check(nombre: str, cond: bool, detalle: str = ""):
        estado = "OK " if cond else "FAIL"
        print(f"[{estado}] {nombre}" + (f" — {detalle}" if detalle else ""))
        if not cond:
            fallos.append(nombre)

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        mezcla = _ruido_dinamico(4.0, seed=1)
        p = tmp / "mezcla.wav"
        sf.write(str(p), mezcla, SR, subtype="PCM_24")

        # target de loudness bajo (poco empuje) -> debería converger con
        # crest alto, disparando el aviso de sub-procesamiento
        resumen = masterizar(p, None, -16.0, tmp / "masters", tmp / "entregables")
        check("resumen trae el campo aviso_crest_fuera_zona",
              "aviso_crest_fuera_zona" in resumen)
        crest = resumen["crest_final"]
        aviso = resumen["aviso_crest_fuera_zona"]
        print(f"    crest_final={crest}  aviso={aviso!r}")
        if crest > 12.0:
            check("crest > 12 -> aviso de sub-procesamiento", aviso is not None and "diferencia" in aviso)
        elif crest < 6.0:
            check("crest < 6 -> aviso de sobre-limitación", aviso is not None and "machacad" in aviso)
        else:
            check("crest en zona sana -> sin aviso", aviso is None)

    print()
    if fallos:
        print(f"RESULTADO: {len(fallos)} fallo(s): {fallos}")
        return 1
    print("RESULTADO: todos los checks pasaron")
    return 0


if __name__ == "__main__":
    sys.exit(main())
