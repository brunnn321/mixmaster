"""Test de declip_ligero (AES 141st Convention, Laguna & Lerch 2016). Sin pytest.

Uso:  .venv\\Scripts\\python tests\\test_declip.py
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mixmaster.audio_analysis import declip_ligero, detectar_clipping

SR = 44100


def main() -> int:
    fallos = []

    def check(nombre: str, cond: bool, detalle: str = ""):
        estado = "OK " if cond else "FAIL"
        print(f"[{estado}] {nombre}" + (f" — {detalle}" if detalle else ""))
        if not cond:
            fallos.append(nombre)

    # caso 1: tono limpio con una corrida CORTA de clipping (5 muestras) en
    # el medio -> debe repararla y el pico reparado debe acercarse al que
    # tendría el tono sin clipear
    t = np.arange(int(SR * 0.5)) / SR
    limpio = 0.8 * np.sin(2 * np.pi * 440 * t)
    clipeado = limpio.copy()
    pico_idx = np.argmax(np.abs(limpio))
    i0 = max(0, pico_idx - 2)
    clipeado[i0:i0 + 5] = np.sign(clipeado[i0:i0 + 5]) * 0.999  # clip corto
    señal = np.repeat(clipeado.reshape(-1, 1), 2, axis=1)

    reparado, n = declip_ligero(señal, umbral=0.999)
    check("declip corto: repara muestras > 0", n > 0, str(n))
    check("declip corto: ya no detecta clipping tras reparar",
          not detectar_clipping(reparado))
    error = np.max(np.abs(reparado[i0:i0 + 5, 0] - limpio[i0:i0 + 5]))
    check("declip corto: el valor reparado se acerca al original sin clip",
          error < 0.1, f"error máx {error:.4f}")

    # caso 2: corrida LARGA de clipping (200 muestras, > max_muestras_corridas
    # default 20) -> NO se toca, sigue detectándose como clipping
    clipeado_largo = limpio.copy()
    clipeado_largo[1000:1200] = np.sign(clipeado_largo[1000:1200]) * 1.0
    señal_larga = np.repeat(clipeado_largo.reshape(-1, 1), 2, axis=1)
    reparado_largo, n_largo = declip_ligero(señal_larga, umbral=0.9995)
    check("declip largo: NO repara (no se puede reconstruir de forma confiable)",
          n_largo == 0, str(n_largo))
    check("declip largo: sigue detectando clipping",
          detectar_clipping(reparado_largo))

    # caso 3: sin clipping -> no hace nada
    señal_limpia = np.repeat(limpio.reshape(-1, 1), 2, axis=1)
    reparado_limpio, n_limpio = declip_ligero(señal_limpia)
    check("sin clipping: no repara nada", n_limpio == 0)
    check("sin clipping: señal intacta",
          np.array_equal(reparado_limpio, señal_limpia))

    print()
    if fallos:
        print(f"RESULTADO: {len(fallos)} fallo(s): {fallos}")
        return 1
    print("RESULTADO: todos los checks pasaron")
    return 0


if __name__ == "__main__":
    sys.exit(main())
