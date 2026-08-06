"""Test del convertidor de audio (sin UI, sin pytest).

Uso:  .venv\\Scripts\\python tests\\test_convertidor.py
"""

import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mixmaster.convertidor import convertir_archivo

SR = 44100


def main() -> int:
    fallos = []

    def check(nombre: str, cond: bool, detalle: str = ""):
        estado = "OK " if cond else "FAIL"
        print(f"[{estado}] {nombre}" + (f" — {detalle}" if detalle else ""))
        if not cond:
            fallos.append(nombre)

    tmp = Path(tempfile.mkdtemp(prefix="mixmaster_conv_"))
    try:
        t = np.arange(SR).astype(np.float64) / SR
        tono = (0.3 * np.sin(2 * np.pi * 440 * t)).reshape(-1, 1)
        wav_in = tmp / "toma.wav"
        sf.write(str(wav_in), np.repeat(tono, 2, axis=1), SR)

        # --- WAV -> MP3 ---
        out_mp3 = convertir_archivo(wav_in, "mp3")
        check("WAV->MP3: archivo creado", out_mp3.exists() and out_mp3.suffix == ".mp3")
        check("WAV->MP3: mismo nombre base", out_mp3.stem == wav_in.stem)
        check("WAV->MP3: va a la subcarpeta de salida junto al original",
              out_mp3.parent == wav_in.parent / "Audioconverter Mixmaster",
              str(out_mp3.parent))

        # --- MP3 -> WAV (ida y vuelta) ---
        out_wav = convertir_archivo(out_mp3, "wav")
        check("MP3->WAV: archivo creado", out_wav.exists() and out_wav.suffix == ".wav")
        audio_vuelta, sr_vuelta = sf.read(str(out_wav))
        check("MP3->WAV: sample rate preservado", sr_vuelta == SR)
        check("MP3->WAV: duración similar (±5%)",
              abs(audio_vuelta.shape[0] - SR) < SR * 0.05,
              f"{audio_vuelta.shape[0]} vs {SR}")

        # --- mismo formato Y misma carpeta de salida que la entrada: no pisa
        # el original (fuerza la colisión con dir_salida explícito, porque
        # el default ya no coincide con la carpeta de origen) ---
        wav_in2 = tmp / "otra.wav"
        sf.write(str(wav_in2), np.repeat(tono, 2, axis=1), SR)
        hash_antes = wav_in2.read_bytes()
        out_mismo = convertir_archivo(wav_in2, "wav", dir_salida=tmp)
        check("mismo formato+carpeta: no pisa el original",
              out_mismo != wav_in2 and wav_in2.read_bytes() == hash_antes)
        check("mismo formato+carpeta: sufijo _convertido",
              "_convertido" in out_mismo.stem)

        # --- dir_salida explícito ---
        otra_carpeta = tmp / "salida_custom"
        out_custom = convertir_archivo(wav_in, "mp3", dir_salida=otra_carpeta)
        check("dir_salida: respeta la carpeta pedida", out_custom.parent == otra_carpeta)
        check("dir_salida: la crea si no existe", otra_carpeta.is_dir())

        # --- sample rate no válido para MP3: se resamplea solo la copia ---
        wav_raro = tmp / "raro.wav"
        sf.write(str(wav_raro), np.repeat(tono, 2, axis=1), 96000)
        out_raro_mp3 = convertir_archivo(wav_raro, "mp3")
        info = sf.info(str(out_raro_mp3))
        check("sr no válido: MP3 sale en un sr soportado",
              info.samplerate in (44100, 48000), str(info.samplerate))
        # el WAV original no se toca
        check("sr no válido: el WAV origen queda intacto en 96000",
              sf.info(str(wav_raro)).samplerate == 96000)

        # --- formato de salida inválido ---
        try:
            convertir_archivo(wav_in, "ogg")
            check("formato inválido: lanza ValueError", False)
        except ValueError:
            check("formato inválido: lanza ValueError", True)

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
