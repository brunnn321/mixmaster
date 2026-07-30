"""Test de interacción entre etapas de la cadena de mezcla.

Pregunta que responde: cuando la cadena completa corre junta, ¿cada etapa
sigue sumando (o al menos no resta) frente al master de referencia, o hay
alguna que se pisa con otra y termina perjudicando el resultado conjunto?

Método: un master "cadena completa" contra uno "misma cadena con la etapa X
apagada" (mismo cfg salvo esa etapa), comparando el score A/B global vs la
referencia. El score A/B ya se sabe que no es proxy fiel de gusto (ver
memoria del proyecto), así que esto es diagnóstico, no un veredicto de
calidad — el objetivo es detectar SI una etapa, en conjunto con las demás,
empeora la similitud tonal/dinámica/de imagen frente a la referencia,
como señal de que merece revisión de oído.

Uso:  .venv\\Scripts\\python tests\\test_interaccion_etapas.py
"""

import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mixmaster.processing import cargar_config_master, masterizar

SR = 44100

# Etapas togglables en CONFIG_MASTER_DEFAULT vía cfg[clave]["activo"].
# "eq_correctivo" queda fuera: sin él no hay perfil de referencia y el
# score A/B no se puede calcular (perfil es None), así que no es comparable.
ETAPAS = [
    "resonancias",
    "multibanda",
    "mono_bass",
    "transient_shaping",
    "clipper",
    "densidad",
]


def wav_sintetico(path: Path, dur_s: float = 20.0, gain: float = 0.3,
                  seed: int = 1, percusivo: bool = False) -> None:
    n = int(dur_s * SR)
    t = np.arange(n) / SR
    rng = np.random.default_rng(seed)
    señal = (
        0.30 * np.sin(2 * np.pi * 55 * t) +
        0.28 * np.sin(2 * np.pi * 130 * t) +
        0.22 * np.sin(2 * np.pi * 400 * t) +
        0.22 * np.sin(2 * np.pi * 1200 * t) +
        0.16 * np.sin(2 * np.pi * 3200 * t) +
        0.08 * rng.standard_normal(n)
    )
    if percusivo:
        # golpes cortos espaciados → dinámica y transitorios reales para que
        # transient shaping / multibanda / clipper tengan algo que hacer.
        for c in range(int(0.3 * SR), n, int(0.5 * SR)):
            L = int(0.03 * SR)
            if c + L < n:
                señal[c:c + L] += np.exp(-np.arange(L) / (0.004 * SR)) * 0.6
    L = señal * gain
    R = señal * gain + 0.015 * rng.standard_normal(n)
    audio = np.stack([L, R], axis=1)
    audio = np.clip(audio, -0.99, 0.99)
    sf.write(str(path), audio, SR)


def score_global(wav_mix: Path, wav_ref: Path, dir_masters: Path,
                  dir_entreg: Path, version: str, cfg: dict) -> float | None:
    resumen = masterizar(wav_mix, wav_ref, -9.0, dir_masters, dir_entreg,
                          version=version, cfg=cfg)
    sc = resumen.get("score")
    return sc["global"] if sc else None


def main() -> int:
    fallos = []
    avisos = []

    def check(nombre: str, cond: bool, detalle: str = ""):
        estado = "OK " if cond else "FAIL"
        print(f"[{estado}] {nombre}" + (f" — {detalle}" if detalle else ""))
        if not cond:
            fallos.append(nombre)

    tmp = Path(tempfile.mkdtemp(prefix="mixmaster_interaccion_"))
    try:
        wav_mix = tmp / "mezcla.wav"
        wav_ref = tmp / "referencia.wav"
        wav_sintetico(wav_mix, gain=0.3, seed=1, percusivo=True)
        wav_sintetico(wav_ref, gain=0.22, seed=2, percusivo=True)

        dir_masters = tmp / "masters"
        dir_entreg = tmp / "entregables"

        cfg_full = cargar_config_master()
        score_full = score_global(wav_mix, wav_ref, dir_masters, dir_entreg,
                                   "FULL", cfg_full)
        check("cadena completa produce score", score_full is not None,
              f"score={score_full}")

        print()
        print(f"Cadena completa: score global = {score_full:.1f}")
        print()

        for etapa in ETAPAS:
            cfg = cargar_config_master()
            cfg.setdefault(etapa, {})["activo"] = False
            score_off = score_global(wav_mix, wav_ref, dir_masters, dir_entreg,
                                      f"SIN_{etapa}", cfg)
            if score_off is None:
                check(f"score con '{etapa}' apagada calculable", False)
                continue
            delta = score_full - score_off
            # No es pass/fail estricto (el score no es proxy de gusto), pero
            # una caída grande al apagar una etapa es señal de que esa etapa
            # SÍ está aportando en conjunto con las demás — la reportamos.
            # Una etapa que MEJORA el score al apagarla es la señal más útil:
            # indica que en esta cadena podría estar restando, no sumando.
            print(f"  {etapa:20s} full={score_full:5.1f}  sin={score_off:5.1f}  "
                  f"delta={delta:+5.1f}")
            if delta < -1.0:
                avisos.append(
                    f"'{etapa}' apagada da MEJOR score que encendida "
                    f"(full={score_full:.1f} vs sin={score_off:.1f}, "
                    f"delta={delta:+.1f}) — revisar de oído si en conjunto "
                    f"con las demás etapas está restando.")

        print()
        if avisos:
            print("AVISOS (candidatas a revisión de oído, no fallos duros):")
            for a in avisos:
                print(f"  - {a}")
        else:
            print("Ninguna etapa empeora el score global en conjunto "
                  "(dentro de la tolerancia de 1 punto).")

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if fallos:
        print(f"RESULTADO: {len(fallos)} fallo(s): {fallos}")
        return 1
    print("RESULTADO: todos los checks pasaron"
          + (f" ({len(avisos)} aviso(s) de interacción, ver arriba)" if avisos else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
