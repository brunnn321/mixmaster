"""Master por stems con EQ solo en guitarras. Sin pytest.

Pedido de Bruno (2026-09-15, them_bones2): que el master no le toque la EQ a
la voz ni a la batería, solo a las guitarras. Con stems se puede hacer de
verdad: el matching y los notches se aplican al grupo de guitarras y el resto
de la mezcla pasa intacto.

Método: tres stems de tono puro (bombo 60 Hz, guitarra 800 Hz, voz 3 kHz) y
una referencia de ruido plano, que obliga al matching a corregir fuerte. Con
la dinámica apagada y target bajo (sin limitar), el master solo cambia el
nivel global, así que la relación voz/bombo tiene que quedar igual si el EQ
no los tocó. Se corre también con el EQ en toda la mezcla para comprobar que
el test distingue un caso del otro.

Uso:  .venv\\\\Scripts\\\\python tests\\\\test_eq_solo_guitarras.py
"""

import copy
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mixmaster.processing import cargar_config_master, masterizar

SR = 44100
DUR = 8.0


def _tono(f, amp):
    t = np.arange(int(SR * DUR)) / SR
    x = amp * np.sin(2 * np.pi * f * t)
    return np.stack([x, x], axis=1)


def _nivel_db(audio, f):
    """Nivel (dB) del tono f en la señal, por FFT con ventana."""
    mono = audio.mean(axis=1)
    ventana = np.hanning(len(mono))
    espectro = np.abs(np.fft.rfft(mono * ventana))
    freqs = np.fft.rfftfreq(len(mono), 1 / SR)
    sel = (freqs > f * 0.97) & (freqs < f * 1.03)
    return 20 * np.log10(espectro[sel].max() + 1e-12)


def _cfg_sin_dinamica(eq_solo_en):
    cfg = copy.deepcopy(cargar_config_master())
    for clave in ("multibanda", "transient_shaping", "densidad", "clipper",
                  "mono_bass", "dinamica_secciones"):
        cfg.setdefault(clave, {})["activo"] = False
    cfg["eq_correctivo"]["analizar_imagen_stereo"] = False
    cfg["eq_correctivo"]["max_correccion_db"] = 10.0
    cfg["stems_master"]["mejorar_percusion"] = False
    cfg["stems_master"]["eq_solo_en"] = eq_solo_en
    return cfg


def main() -> int:
    fallos = []

    def check(nombre, cond, detalle=""):
        print(f"[{'OK ' if cond else 'FAIL'}] {nombre}" + (f" — {detalle}" if detalle else ""))
        if not cond:
            fallos.append(nombre)

    tmp = Path(tempfile.mkdtemp())
    try:
        stems = tmp / "stems"
        stems.mkdir()
        sf.write(stems / "kick.wav", _tono(60, 0.30), SR, subtype="PCM_24")
        sf.write(stems / "gtr_ritmica.wav", _tono(800, 0.30), SR, subtype="PCM_24")
        sf.write(stems / "vox.wav", _tono(3000, 0.30), SR, subtype="PCM_24")
        ruido = np.random.default_rng(0).normal(0, 0.1, (int(SR * DUR), 2))
        sf.write(tmp / "ref.wav", ruido, SR, subtype="PCM_24")

        entrada = sum(sf.read(str(stems / n))[0]
                      for n in ("kick.wav", "gtr_ritmica.wav", "vox.wav"))
        rel_in = _nivel_db(entrada, 3000) - _nivel_db(entrada, 60)
        gtr_in = _nivel_db(entrada, 800) - _nivel_db(entrada, 60)

        resultados = {}
        for caso, claves in (("solo_guitarras", ["gtr", "guit"]), ("toda_la_mezcla", [])):
            r = masterizar(None, tmp / "ref.wav", -20.0, tmp / caso, tmp / caso,
                           carpeta_stems=stems, cfg=_cfg_sin_dinamica(claves))
            salida, _ = sf.read(r["wav"])
            resultados[caso] = (r, _nivel_db(salida, 3000) - _nivel_db(salida, 60),
                                _nivel_db(salida, 800) - _nivel_db(salida, 60))

        r, rel_out, gtr_out = resultados["solo_guitarras"]
        check("el resumen informa qué stems recibieron el EQ",
              r.get("eq_solo_en") == ["gtr_ritmica.wav"], str(r.get("eq_solo_en")))
        check("voz vs bombo intactos (EQ solo en guitarras)",
              abs(rel_out - rel_in) < 0.5, f"cambio {rel_out - rel_in:+.2f} dB")
        check("la guitarra sí recibió el EQ",
              abs(gtr_out - gtr_in) > 1.0, f"cambio {gtr_out - gtr_in:+.2f} dB")

        _, rel_todo, _ = resultados["toda_la_mezcla"]
        check("control: con EQ en toda la mezcla, voz vs bombo SÍ cambia",
              abs(rel_todo - rel_in) > 1.0, f"cambio {rel_todo - rel_in:+.2f} dB")
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
