"""Regresión: las resonancias detectadas tienen que estar separadas entre sí.

Cuando hay varios picos juntos (parciales vecinos, un modo de sala con sus
bins alrededor), `detectar_resonancias` los devolvía todos y ese grupito se
llevaba varios de los 4 slots de notch — que además se pisan entre ellos,
porque un notch es mucho más ancho que la distancia entre esos picos. El
resto del espectro quedaba sin tocar.

Caso real de la tanda del 2026-08-09: "CRISIntro 2" salió con
5275/5577/6153/6255 Hz, 3 de 4 slots dentro de 1/6 de octava. Pasó en 7 de
los 20 masters de esa tanda.

Uso:  .venv\\Scripts\\python tests\\test_resonancias_separadas.py
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mixmaster.audio_analysis import detectar_resonancias

SR = 44100
DUR_S = 6.0
RAZON_MIN = 2 ** (1 / 6)


def audio_con_resonancias(picos: list[tuple[float, float]]) -> np.ndarray:
    """Ruido con resonancias en las (frecuencia, amplitud) pedidas."""
    n = int(DUR_S * SR)
    t = np.arange(n) / SR
    rng = np.random.default_rng(11)
    base = 0.05 * rng.standard_normal(n)
    for f0, amp in picos:
        base += amp * np.sin(2 * np.pi * f0 * t)
    return np.stack([base, base], axis=1)


def pegadas(freqs: list[float]) -> list[tuple[float, float]]:
    return [(a, b) for a, b in zip(freqs, freqs[1:]) if b / a < RAZON_MIN]


def main() -> int:
    fallos = []

    def check(nombre: str, cond: bool, detalle: str = ""):
        estado = "OK " if cond else "FAIL"
        print(f"[{estado}] {nombre}" + (f" — {detalle}" if detalle else ""))
        if not cond:
            fallos.append(nombre)

    # tres picos apretados dentro de 1/6 de octava + uno lejos: es el caso que
    # gastaba 3 de 4 slots en la misma zona del espectro
    apretados = [(1000.0, 0.30), (1059.0, 0.28), (1122.0, 0.26), (4000.0, 0.20)]
    audio = audio_con_resonancias(apretados)

    # el comportamiento viejo se reproduce con sep_octavas=0 — si esto deja de
    # fallar, el test dejó de probar algo y hay que revisarlo
    viejas = sorted(r["freq"] for r in detectar_resonancias(audio, SR, sep_octavas=0))
    check("el caso sigue siendo reproducible (sin separación se apelotonan)",
          bool(pegadas(viejas)), f"{viejas}")

    nuevas = sorted(r["freq"] for r in detectar_resonancias(audio, SR))
    check("EL BUG: ninguna resonancia a menos de 1/6 de octava de otra",
          not pegadas(nuevas), f"{nuevas}")
    check("del grupo apretado sobrevive el pico más prominente",
          any(abs(f - 1000.0) / 1000.0 < 0.05 for f in nuevas), f"{nuevas}")
    check("no se pierde el pico lejano",
          any(abs(f - 4000.0) / 4000.0 < 0.05 for f in nuevas), f"{nuevas}")

    # cuatro picos bien separados: se devuelven los cuatro, no se filtra de más
    separados = [(220.0, 0.30), (1000.0, 0.30), (3000.0, 0.28), (8000.0, 0.26)]
    res = sorted(r["freq"] for r in detectar_resonancias(
        audio_con_resonancias(separados), SR))
    check("con picos separados devuelve los cuatro", len(res) == 4, f"{res}")
    check("y coinciden con las frecuencias inyectadas",
          all(any(abs(f - p) / p < 0.05 for f in res) for p, _ in separados),
          f"{res}")

    res = detectar_resonancias(audio_con_resonancias(separados), SR, max_n=2)
    check("respeta max_n", len(res) == 2, f"{[r['freq'] for r in res]}")

    print()
    if fallos:
        print(f"RESULTADO: {len(fallos)} fallo(s): {fallos}")
        return 1
    print("RESULTADO: todos los checks pasaron")
    return 0


if __name__ == "__main__":
    sys.exit(main())
