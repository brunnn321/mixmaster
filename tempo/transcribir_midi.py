"""Pasa a MIDI el bajo y la voz de un tema que ya salió de Tempo Genius (MuScriptor).

Uso (con el Python del entorno aparte, 3.12):
    tempo/.muscriptor/Scripts/python tempo/transcribir_midi.py "<carpeta A TEMPO/Tema - 128 BPM>" [--modelo medium|small]

Escribe "Bajo 128bpm.mid" y "Voz 128bpm.mid" en la misma carpeta, con el tempo del tema
en el archivo: se arrastran al compás 1 y las notas caen en la grilla del DAW.

Para que nunca quede trabado sin aviso (19/10: una descarga a medias tuvo 12 minutos el
proceso en "Loading model…"):
- cada paso imprime una línea al empezar, y la transcripción una por cada bloque de 5 s;
- el modelo se busca primero en la caché; si falta, se descarga una sola vez avisando, con
  tiempo límite de red, y antes se borran restos de descargas viejas;
- quien lo llama (la ventana de Tempo Genius) corta el proceso si pasa un rato sin líneas nuevas.
"""

import os
import re
import sys
import time
from pathlib import Path

os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "30")   # una red caída da error, no espera eterna

RE_BPM = re.compile(r"(\d+(?:\.\d+)?)bpm", re.I)
# pista → (instrumentos de MuScriptor a los que se limita, programa General MIDI)
PISTAS = {"Bajo": (["electric_bass", "acoustic_bass"], 33), "Voz": (["voice"], 53)}


def decir(texto):
    print(texto, flush=True)


def modelo_local(tamano: str) -> str:
    """Ruta del modelo en la caché; si no está, lo descarga una vez avisando."""
    from huggingface_hub import hf_hub_download, try_to_load_from_cache
    repo = f"MuScriptor/muscriptor-{tamano}"
    ruta = try_to_load_from_cache(repo, "model.safetensors")
    if isinstance(ruta, str) and Path(ruta).exists():
        decir(f"modelo {tamano}: ya está en la PC")
        return ruta
    cache = Path.home() / ".cache" / "huggingface" / "hub" / f"models--MuScriptor--muscriptor-{tamano}" / "blobs"
    for viejo in cache.glob("*.incomplete") if cache.exists() else []:
        if time.time() - viejo.stat().st_mtime > 3600:   # restos de descargas que quedaron a medias
            viejo.unlink(missing_ok=True)
    decir(f"modelo {tamano}: descargando una sola vez (unos cientos de MB)…")
    return hf_hub_download(repo, "model.safetensors")


def escribir_midi(notas, bpm, nombre, programa, destino: Path):
    import mido
    tpb = 480
    a_ticks = lambda s: int(round(s * bpm / 60 * tpb))
    pista = mido.MidiTrack()
    pista.append(mido.MetaMessage("track_name", name=nombre, time=0))
    pista.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(bpm), time=0))
    pista.append(mido.MetaMessage("time_signature", numerator=4, denominator=4, time=0))
    pista.append(mido.Message("program_change", program=programa, channel=0, time=0))
    eventos = []
    for ini, fin, alt in notas:
        eventos.append((a_ticks(ini), 1, alt))
        eventos.append((max(a_ticks(fin), a_ticks(ini) + 1), 0, alt))
    eventos.sort(key=lambda e: (e[0], e[1]))       # en el mismo tick, primero se apaga y después se prende
    ahora = 0
    for tick, prende, alt in eventos:
        tipo = "note_on" if prende else "note_off"
        pista.append(mido.Message(tipo, note=alt, velocity=90 if prende else 0, channel=0, time=tick - ahora))
        ahora = tick
    m = mido.MidiFile(ticks_per_beat=tpb)
    m.tracks.append(pista)
    m.save(str(destino))


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        raise SystemExit(__doc__)
    tamano = next((x.split("=")[1] for x in sys.argv if x.startswith("--modelo=")), "medium")
    carpeta = Path(args[0])

    trabajos = []
    for nombre, (instrumentos, programa) in PISTAS.items():
        audio = next(iter(sorted(carpeta.glob(f"{nombre} *bpm.flac"))), None)
        if audio is None:
            decir(f"{nombre}: no hay pista «{nombre} …bpm.flac» en la carpeta, se salta")
            continue
        trabajos.append((nombre, audio, instrumentos, programa, float(RE_BPM.search(audio.name).group(1))))
    if not trabajos:
        raise SystemExit("No hay pistas de bajo ni de voz en la carpeta: ¿salió de Tempo Genius con stems?")

    ruta = modelo_local(tamano)
    decir("cargando el modelo…")
    from muscriptor.events import NoteEndEvent, ProgressEvent
    from muscriptor.transcription_model import TranscriptionModel
    modelo = TranscriptionModel.load_model(ruta, device="cpu")
    decir("modelo listo")

    for nombre, audio, instrumentos, programa, bpm in trabajos:
        t0 = time.time()
        decir(f"{nombre}: transcribiendo…")
        notas = []
        for ev in modelo.transcribe(str(audio), instruments=instrumentos):
            if isinstance(ev, ProgressEvent):
                if ev.total:
                    decir(f"{nombre}: bloque {ev.completed} de {ev.total}")
            elif isinstance(ev, NoteEndEvent):
                notas.append((ev.start_event.start_time, ev.end_time, ev.start_event.pitch))
        etiqueta = f"{bpm:g}bpm"
        destino = carpeta / f"{nombre} {etiqueta}.mid"
        escribir_midi(sorted(notas), bpm, f"{nombre} {etiqueta}", programa, destino)
        decir(f"{nombre}: {len(notas)} notas → {destino.name} ({time.time() - t0:.0f} s)")
    decir("Listo")


if __name__ == "__main__":
    main()
