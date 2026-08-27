"""Test de diagnosticar_stem: headroom, clipping y sobre-procesado por stem
(sin pytest).

Uso:  .venv\\Scripts\\python tests\\test_diagnostico_stem.py
"""

import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mixmaster.stem_diagnostico import diagnosticar_stem

SR = 44100
DUR_S = 2.0


def _tono(freq_hz: float, amplitud: float = 0.25) -> np.ndarray:
    t = np.arange(int(SR * DUR_S)) / SR
    señal = amplitud * np.sin(2 * np.pi * freq_hz * t)
    return np.repeat(señal.reshape(-1, 1), 2, axis=1)


def _tono_clipeado(freq_hz: float) -> np.ndarray:
    """Seno amplificado y recortado en ±1.0 — clipping duro sostenido."""
    audio = _tono(freq_hz, amplitud=3.0)
    return np.clip(audio, -1.0, 1.0)


def _tono_limitado(freq_hz: float) -> np.ndarray:
    """Simula un limitador agresivo: saturación suave (tanh) que aplasta el
    crest factor y deja el pico pegado cerca de 0 dBFS, sin clipping duro."""
    audio = _tono(freq_hz, amplitud=1.0)
    aplastado = np.tanh(audio * 6.0) * 0.98
    return aplastado


def _obs_textos(d: dict) -> list[str]:
    return [txt for _, txt in d["observaciones"]]


def main() -> int:
    fallos = []

    def check(nombre: str, cond: bool, detalle: str = ""):
        estado = "OK " if cond else "FAIL"
        print(f"[{estado}] {nombre}" + (f" — {detalle}" if detalle else ""))
        if not cond:
            fallos.append(nombre)

    tmp = Path(tempfile.mkdtemp(prefix="mixmaster_diagstem_"))
    try:
        # --- caso 1: stem limpio, buen headroom -> sin avisos de headroom/clip/limitador ---
        limpio = tmp / "limpio.wav"
        sf.write(str(limpio), _tono(150, amplitud=0.25), SR)  # ~-12 dBFS
        d = diagnosticar_stem(limpio)
        textos = _obs_textos(d)
        check("stem limpio: sin aviso de clipping",
              not any("clipeado" in t for t in textos), str(textos))
        check("stem limpio: sin aviso de headroom",
              not any("margen" in t for t in textos), str(textos))
        check("stem limpio: sin aviso de sobre-procesado",
              not any("limitador" in t for t in textos), str(textos))

        # --- caso 2: stem clipeado -> aviso de clipping ---
        clip = tmp / "clip.wav"
        sf.write(str(clip), _tono_clipeado(150), SR)
        d = diagnosticar_stem(clip)
        textos = _obs_textos(d)
        check("stem clipeado: detecta clipping",
              any("clipeado" in t for t in textos), str(textos))

        # --- caso 3: pico alto sin clipping duro -> aviso de headroom ---
        justo = tmp / "justo.wav"
        # amplitud calculada para pico ~ -0.2 dBFS sin llegar al umbral de clip
        sf.write(str(justo), _tono(150, amplitud=0.976), SR)
        d = diagnosticar_stem(justo)
        textos = _obs_textos(d)
        check("stem con poco headroom: sin clipping",
              not any("clipeado" in t for t in textos), str(textos))
        check("stem con poco headroom: aviso de margen",
              any("margen" in t for t in textos), str(textos))

        # --- caso 4: crest bajo + pico alto -> "ya viene masterizado/limitado" ---
        limitado = tmp / "limitado.wav"
        sf.write(str(limitado), _tono_limitado(150), SR)
        d = diagnosticar_stem(limitado)
        textos = _obs_textos(d)
        check(f"stem limitado: crest bajo (crest={d['crest_db']} dB)", d["crest_db"] < 6.0)
        check("stem limitado: aviso de sobre-procesado",
              any("limitador" in t for t in textos), str(textos))

        # --- campo nuevo expuesto en el dict ---
        check("true_peak_db presente en el resultado", "true_peak_db" in d, str(d.keys()))

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if fallos:
        print(f"RESULTADO: {len(fallos)} fallo(s): {fallos}")
        return 1
    print("RESULTADO: todos los checks pasaron")
    return 0


if __name__ == "__main__":
    sys.exit(main())
