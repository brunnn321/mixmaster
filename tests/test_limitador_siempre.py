"""Regresión: el limitador debe correr SIEMPRE, aunque el audio ya venga en
el loudness objetivo (sin UI, sin pytest).

Bug real encontrado el 2026-08-09 masterizando material propio: el bucle de
convergencia de `masterizar()` hace `break` cuando el audio ya está dentro de
0.3 LU del target, y ese `break` ocurría ANTES del limitador — así que un
archivo que llegaba en loudness pero con picos sobre el techo salía sin
limitar. Caso real: "Good Mornig SIN MEZCLA" → +0.04 dBTP y clipping en el
master final (debía ser -1.0 dBTP).

Uso:  .venv\\Scripts\\python tests\\test_limitador_siempre.py
"""

import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mixmaster.audio_analysis import (
    cargar_audio, detectar_clipping, lufs_integrado, true_peak_db,
)
from mixmaster.processing import cargar_config_master, masterizar

SR = 44100
DUR_S = 12.0


def mezcla_en_target_con_picos(path: Path, target_lufs: float) -> None:
    """Audio que YA está en el loudness objetivo pero con picos sobre 0 dBFS.

    Es la combinación que disparaba el bug: el bucle de convergencia corta en
    la primera vuelta (ya está en target) y nunca llega a limitar.
    """
    n = int(DUR_S * SR)
    t = np.arange(n) / SR
    rng = np.random.default_rng(7)
    # base musical de banda ancha
    base = (0.25 * np.sin(2 * np.pi * 110 * t)
            + 0.15 * np.sin(2 * np.pi * 440 * t)
            + 0.10 * rng.standard_normal(n))
    # picos puntuales muy por encima del resto (transientes tipo batería)
    for pos in range(SR, n, SR):
        base[pos:pos + 40] += 1.6
    audio = np.stack([base, base * 0.98], axis=1)

    # llevar exactamente al target para forzar el break temprano
    lufs = lufs_integrado(audio, SR)
    audio = audio * 10 ** ((target_lufs - lufs) / 20)
    sf.write(str(path), audio, SR)


def main() -> int:
    fallos = []

    def check(nombre: str, cond: bool, detalle: str = ""):
        estado = "OK " if cond else "FAIL"
        print(f"[{estado}] {nombre}" + (f" — {detalle}" if detalle else ""))
        if not cond:
            fallos.append(nombre)

    tmp = Path(tempfile.mkdtemp(prefix="mixmaster_lim_"))
    try:
        cfg = cargar_config_master()
        techo = float(cfg["limitador"]["ceiling_dbtp"])
        target = -9.0

        mezcla = tmp / "ya_en_target.wav"
        mezcla_en_target_con_picos(mezcla, target)

        audio_in, sr_in = cargar_audio(mezcla)
        tp_in = true_peak_db(audio_in, sr_in)
        lufs_in = lufs_integrado(audio_in, sr_in)
        check("la entrada reproduce el caso: ya en target",
              abs(lufs_in - target) <= 0.3, f"{lufs_in:.1f} LUFS")
        check("la entrada reproduce el caso: picos sobre el techo",
              tp_in > techo, f"{tp_in:.2f} dBTP > techo {techo:g}")

        resumen = masterizar(
            path_mezcla=mezcla, path_referencia=None, target_lufs=target,
            dir_masters=tmp / "masters", dir_entregables=tmp / "mp3",
            version="v01", cfg=cfg,
        )

        audio_out, sr_out = cargar_audio(Path(resumen["wav"]))
        tp_out = true_peak_db(audio_out, sr_out)
        # tolerancia de 0.1 dB: el true peak se estima con oversampling 4x
        check("EL BUG: el master respeta el techo de true peak",
              tp_out <= techo + 0.1, f"{tp_out:.2f} dBTP (techo {techo:g})")
        check("el master no sale con clipping",
              not detectar_clipping(audio_out), f"tp={tp_out:.2f}")
        check("el resumen reporta el true peak real",
              abs(resumen["true_peak_final"] - tp_out) <= 0.15,
              f"resumen {resumen['true_peak_final']} vs medido {tp_out:.2f}")
        check("sigue llegando al loudness pedido",
              abs(resumen["lufs_final"] - target) <= 0.6,
              f"{resumen['lufs_final']} LUFS")
        check("el resumen informa si convergió al target",
              isinstance(resumen.get("convergio_target"), bool),
              str(resumen.get("convergio_target")))

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
