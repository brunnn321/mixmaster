"""Tests de la tanda 30/9 (investigación de calidad, ítems 1, 7 y 8):
igual sonoridad en los comparadores, bus de batería y bajo dividido.
Sin pytest.

Uso:  .venv\\Scripts\\python tests\\test_bus_bajo_volumen.py
"""

import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mixmaster.audio_analysis import volumenes_igual_sonoridad
from mixmaster.processing import _bajo_dividido, _bus_bateria, sumar_stems

SR = 44100
rng = np.random.default_rng(7)


def _estereo(x: np.ndarray) -> np.ndarray:
    return np.repeat(x.reshape(-1, 1), 2, axis=1)


def _bajo(dur_s: float = 4.0) -> np.ndarray:
    t = np.arange(int(SR * dur_s)) / SR
    return _estereo(0.3 * np.sin(2 * np.pi * 55 * t) + 0.1 * np.sin(2 * np.pi * 330 * t))


def _bateria(dur_s: float = 4.0) -> np.ndarray:
    n = int(SR * dur_s)
    x = np.zeros(n)
    golpe = rng.standard_normal(int(0.3 * SR)) * np.exp(-np.arange(int(0.3 * SR)) / (0.04 * SR))
    for i in range(0, n - len(golpe), SR // 2):
        x[i: i + len(golpe)] += 0.5 * golpe
    return _estereo(x)


def _cuerpo_db(x: np.ndarray) -> float:
    """Energía del cuerpo (60-250 ms después de cada golpe) respecto del
    ataque (primeros 20 ms). Sube si la batería gana sustain."""
    cuerpo = ataque = 0.0
    for i in range(0, len(x) - SR // 2, SR // 2):
        ataque += np.sum(x[i: i + int(0.02 * SR)] ** 2)
        cuerpo += np.sum(x[i + int(0.06 * SR): i + int(0.25 * SR)] ** 2)
    return 10 * np.log10(cuerpo / ataque)


def _energia_banda(x: np.ndarray, f_lo: float, f_hi: float) -> float:
    esp = np.abs(np.fft.rfft(x[:, 0])) ** 2
    f = np.fft.rfftfreq(len(x), 1 / SR)
    return float(esp[(f >= f_lo) & (f < f_hi)].sum())


def main() -> int:
    fallos = []

    def check(nombre: str, cond: bool, detalle: str = ""):
        estado = "OK " if cond else "FAIL"
        print(f"[{estado}] {nombre}" + (f" — {detalle}" if detalle else ""))
        if not cond:
            fallos.append(nombre)

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)

        # --- 1. igual sonoridad
        t = np.arange(SR * 3) / SR
        tono = _estereo(0.1 * np.sin(2 * np.pi * 440 * t))
        sf.write(str(tmp / "suave.wav"), tono, SR)
        sf.write(str(tmp / "fuerte.wav"), tono * 2.0, SR)  # +6 dB
        v = volumenes_igual_sonoridad([tmp / "suave.wav", tmp / "fuerte.wav"])
        check("igual sonoridad: el suave queda en 1.0", abs(v[0] - 1.0) < 1e-6, str(v))
        check("igual sonoridad: el de +6 dB baja a ~0.5", abs(v[1] - 0.5) < 0.02, str(v))
        v2 = volumenes_igual_sonoridad([tmp / "no_existe.wav", tmp / "suave.wav"])
        check("igual sonoridad: archivo que falta queda en 1.0", v2 == [1.0, 1.0], str(v2))

        # --- 8. bajo dividido
        bajo = _bajo()
        salida = _bajo_dividido(bajo, SR)
        rms_in, rms_out = np.sqrt(np.mean(bajo ** 2)), np.sqrt(np.mean(salida ** 2))
        check("bajo dividido: sin NaN", bool(np.isfinite(salida).all()))
        check("bajo dividido: conserva el RMS", abs(20 * np.log10(rms_out / rms_in)) < 0.1,
              f"{20 * np.log10(rms_out / rms_in):+.2f} dB")
        armon_in = _energia_banda(bajo, 700, 5000)
        armon_out = _energia_banda(salida, 700, 5000)
        check("bajo dividido: suma armónicos en 0.7-5 kHz (se oye en parlante chico)",
              armon_out > 10 * armon_in, f"x{armon_out / max(armon_in, 1e-12):.0f}")
        check("bajo dividido: nada por encima de ~12 kHz (sin aliasing audible)",
              _energia_banda(salida, 12000, 22050) < 1e-4 * _energia_banda(salida, 20, 22050))

        # --- 7. bus de batería
        bat = _bateria()
        pegado, info = _bus_bateria(bat, SR)
        check("bus de batería: sin NaN", bool(np.isfinite(pegado).all()))
        check("bus de batería: conserva el RMS",
              abs(20 * np.log10(np.sqrt(np.mean(pegado ** 2)) / np.sqrt(np.mean(bat ** 2)))) < 0.1)
        check("bus de batería: más cuerpo después del golpe",
              _cuerpo_db(pegado) > _cuerpo_db(bat) + 0.5,
              f"{_cuerpo_db(bat):.1f} -> {_cuerpo_db(pegado):.1f} dB")
        check("bus de batería: las dos compresiones trabajan",
              info["reduccion_paralela_db"] > 1 and info["reduccion_pegamento_db"] > 0.1, str(info))

        # --- integración con sumar_stems
        stems = tmp / "stems"
        stems.mkdir()
        sf.write(str(stems / "Kick.wav"), _bateria()[:, 0], SR)
        sf.write(str(stems / "Bass DI.wav"), _bajo()[:, 0], SR)
        sf.write(str(stems / "GTR L.wav"), 0.2 * rng.standard_normal(SR * 4), SR)
        plano, _ = sumar_stems(stems, mejorar_percusion=False)
        de_nuevo, _ = sumar_stems(stems, mejorar_percusion=False,
                                  bus_bateria=False, bajo_dividido=False)
        check("sumar_stems apagado: igual que antes", np.array_equal(plano, de_nuevo))
        procesado, _ = sumar_stems(stems, mejorar_percusion=False,
                                   bus_bateria=True, bajo_dividido=True)
        check("sumar_stems prendido: cambia la mezcla", not np.allclose(plano, procesado))
        check("sumar_stems prendido: pico en -6 dBFS",
              abs(20 * np.log10(np.max(np.abs(procesado))) + 6.0) < 0.01)

        solo_bombo = tmp / "bombo"
        solo_bombo.mkdir()
        sf.write(str(solo_bombo / "Bass Drum.wav"), _bateria()[:, 0], SR)
        a, _ = sumar_stems(solo_bombo, mejorar_percusion=False, bajo_dividido=True)
        b, _ = sumar_stems(solo_bombo, mejorar_percusion=False)
        check("'Bass Drum' no se trata como bajo", np.array_equal(a, b))

    print()
    if fallos:
        print(f"RESULTADO: {len(fallos)} fallo(s): {fallos}")
        return 1
    print("RESULTADO: todos los checks pasaron")
    return 0


if __name__ == "__main__":
    sys.exit(main())
