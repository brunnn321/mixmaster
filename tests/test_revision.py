"""Test de las perillas de revisión del master (brillo, grave, volumen,
matching). Sin pytest.

Uso:  .venv\\Scripts\\python tests\\test_revision.py
"""

import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mixmaster.audio_analysis import cargar_audio
from mixmaster.processing import cargar_config_master, masterizar

SR = 44100
rng = np.random.default_rng(21)


def _banda_db(x: np.ndarray, lo: float, hi: float) -> float:
    esp = np.abs(np.fft.rfft(x.mean(axis=1))) ** 2
    f = np.fft.rfftfreq(len(x), 1 / SR)
    return 10 * np.log10(esp[(f >= lo) & (f < hi)].sum() / esp[(f >= 300) & (f < 1000)].sum())  # relativo a los medios


def main() -> int:
    fallos = []

    def check(nombre: str, cond: bool, detalle: str = ""):
        estado = "OK " if cond else "FAIL"
        print(f"[{estado}] {nombre}" + (f" - {detalle}" if detalle else ""))
        if not cond:
            fallos.append(nombre)

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        mezcla = tmp / "mezcla.wav"
        ruido = rng.standard_normal((SR * 12, 2)) * 0.1
        sf.write(str(mezcla), ruido, SR)
        cfg = cargar_config_master()

        def master(nombre, revision=None):
            r = masterizar(mezcla, None, -12.0, tmp / nombre, tmp / (nombre + "_e"),
                           version="V01", cfg=cfg, revision=revision)
            return r, cargar_audio(Path(r["wav"]))[0]

        r0, a0 = master("base")
        r1, a1 = master("brillo", {"brillo_db": 3.0, "grave_db": -3.0})
        d_agudos = _banda_db(a1, 8000, 16000) - _banda_db(a0, 8000, 16000)
        d_graves = _banda_db(a1, 30, 80) - _banda_db(a0, 30, 80)
        check("revisión: +3 dB de brillo sube los agudos", 1.5 < d_agudos < 4.5, f"{d_agudos:+.1f} dB")
        check("revisión: -3 dB de grave baja los graves", -4.5 < d_graves < -1.5, f"{d_graves:+.1f} dB")
        r2, _ = master("fuerte", {"volumen_lu": 2.0})
        check("revisión: +2 LU sube el objetivo",
              abs(r2["target_lufs"] - (r0["target_lufs"] + 2.0)) < 1e-6
              and r2["lufs_final"] > r0["lufs_final"] + 1.0,
              f"{r0['lufs_final']} -> {r2['lufs_final']}")
        check("revisión: queda anotada en el resumen", r1["revision"] == {"brillo_db": 3.0, "grave_db": -3.0})
        check("revisión: sin perillas no cambia nada", r0["revision"] == {})

    print()
    if fallos:
        print(f"RESULTADO: {len(fallos)} fallo(s): {fallos}")
        return 1
    print("RESULTADO: todos los checks pasaron")
    return 0


if __name__ == "__main__":
    sys.exit(main())
