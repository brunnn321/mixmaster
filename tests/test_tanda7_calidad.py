"""Tests de la tanda 7 (investigación de calidad, ítems 2 y 9): balance por
instrumento contra la referencia separada, y matching de dinámica por banda.
Sin pytest.

Uso:  .venv\\Scripts\\python tests\\test_tanda7_calidad.py
"""

import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mixmaster import separacion
from mixmaster.audio_analysis import lufs_integrado, rango_corto_por_banda
from mixmaster.processing import _grupo_separacion, _igualar_balance, _multibanda_rango

SR = 44100
rng = np.random.default_rng(9)


def _estereo(x: np.ndarray) -> np.ndarray:
    return np.repeat(x.reshape(-1, 1), 2, axis=1)


def _golpes(n: int, amp: float) -> np.ndarray:
    x = np.zeros(n)
    golpe = rng.standard_normal(int(0.2 * SR)) * np.exp(-np.arange(int(0.2 * SR)) / (0.03 * SR))
    for i in range(0, n - len(golpe), SR // 2):
        x[i: i + len(golpe)] += amp * golpe
    return x


def main() -> int:
    fallos = []

    def check(nombre: str, cond: bool, detalle: str = ""):
        estado = "OK " if cond else "FAIL"
        print(f"[{estado}] {nombre}" + (f" - {detalle}" if detalle else ""))
        if not cond:
            fallos.append(nombre)

    n = SR * 8
    t = np.arange(n) / SR

    # --- 2. grupos y balance
    check("grupos: roles al separador",
          [_grupo_separacion(r) for r in ("kick", "toms", "bajo", "coros", "guitarra", "generico")]
          == ["drums", "drums", "bass", "vocals", "other", "other"])
    pistas = [_estereo(_golpes(n, 0.5)), _estereo(0.2 * np.sin(2 * np.pi * 55 * t)),
              _estereo(0.15 * np.sin(2 * np.pi * 440 * t)), _estereo(0.2 * rng.standard_normal(n))]
    roles = ["kick", "bajo", "voz_principal", "guitarra"]
    ref = {"drums": -6.0, "bass": -8.0, "vocals": -4.0, "other": -7.0}
    info = _igualar_balance(pistas, roles, SR, ref)
    errores = {g: abs(v["despues"] - ref[g]) for g, v in info.items()}
    check("balance: cada grupo queda cerca de la referencia (max 1 LU)",
          all(e <= 1.0 for e in errores.values()), str(errores).encode("ascii", "replace").decode())
    check("balance: la voz, que estaba muy baja, sube", info["vocals"]["ajuste_db"] > 2,
          str(info["vocals"]))

    # --- 9. dinámica por banda
    dinamica = _estereo(_golpes(n, 0.8) + 0.02 * rng.standard_normal(n))
    densa = _estereo(0.3 * rng.standard_normal(n))
    r_mix = rango_corto_por_banda(dinamica, SR)
    r_ref = {b: v * 0.5 for b, v in r_mix.items()}   # la ref se mueve la mitad
    salida, aplicado = _multibanda_rango(dinamica, SR, r_ref, {})
    r_post = rango_corto_por_banda(salida, SR)
    mejora = [abs(r_post[b] - r_ref[b]) < abs(r_mix[b] - r_ref[b]) for b in aplicado]
    check("dinámica: las bandas tratadas se acercan a la ref", bool(aplicado) and all(mejora),
          str(aplicado))
    check("dinámica: sin NaN", bool(np.isfinite(salida).all()))
    sin_cambio, ap2 = _multibanda_rango(densa, SR, {b: 99.0 for b in r_mix}, {})
    check("dinámica: si la mezcla ya es menos dinámica, no toca nada (no expande)",
          ap2 == {} and np.allclose(sin_cambio, densa, atol=1e-9))

    # --- 2. separador real (Demucs), con caché en carpeta temporal
    if separacion.disponible():
        with tempfile.TemporaryDirectory() as tmp:
            separacion.CACHE = Path(tmp) / "cache.json"
            ruta = Path(tmp) / "ref.wav"
            mezcla = _golpes(n, 0.4) + 0.2 * np.sin(2 * np.pi * 55 * t)
            sf.write(str(ruta), _estereo(mezcla), SR)
            b1 = separacion.balance_por_instrumento(ruta)
            check("separador: devuelve los 4 grupos", b1 is not None and set(b1) == set(separacion.GRUPOS),
                  str(b1))
            t0 = time.time()
            b2 = separacion.balance_por_instrumento(ruta)
            check("separador: la segunda vez sale de la caché", b2 == b1 and time.time() - t0 < 1.0)
    else:
        print("[--] separador no instalado: se salta la prueba real")

    print()
    if fallos:
        print(f"RESULTADO: {len(fallos)} fallo(s): {fallos}")
        return 1
    print("RESULTADO: todos los checks pasaron")
    return 0


if __name__ == "__main__":
    sys.exit(main())
