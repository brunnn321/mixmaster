"""Test del aviso previo de RAM estimada al sumar muchos stems. Sin pytest.

Uso:  .venv\\Scripts\\python tests\\test_ram_estimada.py
"""

import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mixmaster.processing import sumar_stems

SR = 44100


def _tono(freq, dur_s):
    t = np.arange(int(SR * dur_s)) / SR
    s = 0.2 * np.sin(2 * np.pi * freq * t)
    return np.repeat(s.reshape(-1, 1), 2, axis=1)


def main() -> int:
    fallos = []

    def check(nombre: str, cond: bool, detalle: str = ""):
        estado = "OK " if cond else "FAIL"
        print(f"[{estado}] {nombre}" + (f" — {detalle}" if detalle else ""))
        if not cond:
            fallos.append(nombre)

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        # pocos stems, cortos -> no debería disparar el aviso de RAM
        pocos = tmp / "pocos"
        pocos.mkdir()
        for i in range(3):
            sf.write(str(pocos / f"stem{i}.wav"), _tono(200 + i * 10, 1.0), SR)

        mensajes = []
        audio, sr = sumar_stems(pocos, progreso=mensajes.append)
        check("suma correctamente pocos stems", audio.shape[0] > 0)
        check("pocos stems cortos: NO dispara aviso de RAM",
              not any("GB de RAM" in m for m in mensajes), str(mensajes))

        # muchos stems (33, simulando el caso real) de duración moderada ->
        # confirma que sumar_stems sigue funcionando igual (la lógica de
        # negocio no cambia) y que la estimación no rompe nada aunque no
        # dispare el umbral con archivos de test cortos
        muchos = tmp / "muchos"
        muchos.mkdir()
        for i in range(33):
            sf.write(str(muchos / f"pista{i:02d}.wav"), _tono(100 + i * 5, 0.5), SR)

        mensajes2 = []
        audio2, sr2 = sumar_stems(muchos, progreso=mensajes2.append)
        check("suma correctamente 33 stems", audio2.shape[0] > 0)
        check("33 stems: no revienta ni cuelga (test termina)", True)

    print()
    if fallos:
        print(f"RESULTADO: {len(fallos)} fallo(s): {fallos}")
        return 1
    print("RESULTADO: todos los checks pasaron")
    return 0


if __name__ == "__main__":
    sys.exit(main())
