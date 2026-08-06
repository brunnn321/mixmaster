"""Convertidor de audio: WAV/MP3/FLAC/OGG/AIFF/M4A/WMA → WAV o MP3.

Pensado para el caso real de Bruno: le mandan tomas por WhatsApp en formatos
que Studio One no reconoce (m4a sobre todo) y necesita pasarlas a WAV/MP3
antes de poder usarlas.

Solo copia el AUDIO — no preserva metadata de tempo/BPM embebida (chunks
ACID/Broadcast WAV, tags ID3 de tempo, etc.), porque el pipeline decodifica
a muestras planas y no retiene chunks no-audio. En la práctica casi nunca
importa para este caso de uso (una nota de voz de WhatsApp no trae esa
metadata), pero hay que ser honesto: si el WAV origen SÍ la tuviera, se
pierde en la conversión.
"""

from pathlib import Path

import soundfile as sf
from scipy import signal

from .audio_analysis import FORMATOS_SOPORTADOS, cargar_audio
from .logger import get_logger
from .processing import SR_MP3_VALIDOS

log = get_logger("mixmaster.convertidor")

FORMATOS_SALIDA = ("wav", "mp3")
CARPETA_SALIDA = "Audioconverter Mixmaster"


def convertir_archivo(path_entrada: Path, formato_salida: str,
                      dir_salida: Path | None = None) -> Path:
    """Convierte un archivo a WAV o MP3. Devuelve la ruta del resultado.

    Si `dir_salida` es None, escribe en una subcarpeta "convertidos" al
    lado del original — no directo en la misma carpeta (evita ensuciarla
    y que el resultado se confunda con el archivo original).
    """
    path_entrada = Path(path_entrada)
    if formato_salida not in FORMATOS_SALIDA:
        raise ValueError(f"Formato de salida no soportado: {formato_salida}")

    audio, sr = cargar_audio(path_entrada)
    carpeta = Path(dir_salida) if dir_salida else path_entrada.parent / CARPETA_SALIDA
    carpeta.mkdir(parents=True, exist_ok=True)

    destino = carpeta / f"{path_entrada.stem}.{formato_salida}"
    if destino.resolve() == path_entrada.resolve():
        destino = carpeta / f"{path_entrada.stem}_convertido.{formato_salida}"

    if formato_salida == "wav":
        sf.write(str(destino), audio, sr, subtype="PCM_24")
    else:
        # mismo criterio que el export de MP3 del master: si el sample rate
        # no es válido para MP3, se resamplea solo esta copia.
        if sr not in SR_MP3_VALIDOS:
            sr_destino = 48000 if sr > 44100 else 44100
            from math import gcd
            g = gcd(sr_destino, sr)
            audio = signal.resample_poly(audio, sr_destino // g, sr // g, axis=0)
            sr = sr_destino
        sf.write(str(destino), audio, sr)

    log.info("Convertido: %s → %s", path_entrada.name, destino)
    return destino
