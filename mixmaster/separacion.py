"""Balance por instrumento de una referencia (ítem 2 de la investigación de
calidad, 2/10/2026).

La referencia se separa en batería, bajo, voz y resto con HT Demucs (Rouard,
Massa y Défossez, ICASSP 2023) y se mide cuánto suena cada grupo respecto
del total, en LU. **Solo se mide: el audio separado no se usa**, así que los
artefactos de la separación no llegan al master. Con esos números la mezcla
por stems apunta al balance real de un disco, en vez de a una jerarquía fija.

Tarda ~0.6x la duración del tema en CPU; el resultado se guarda en caché
por huella del archivo (el mismo tema no se vuelve a separar).
"""

import json
from pathlib import Path

import numpy as np
from scipy import signal

from .app_paths import CONFIG_DIR
from .audio_analysis import _hash_archivo, cargar_audio, lufs_integrado
from .logger import get_logger

log = get_logger("mixmaster.separacion")

MODELO = "htdemucs"
CACHE = CONFIG_DIR / "cache_balance_referencias.json"
GRUPOS = ("drums", "bass", "vocals", "other")


def _leer_cache() -> dict:
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def disponible() -> bool:
    """True si el separador está instalado (torch + demucs)."""
    try:
        import demucs  # noqa: F401
        import torch  # noqa: F401
        return True
    except Exception:
        return False


def balance_por_instrumento(path: Path, progreso=None) -> dict | None:
    """{grupo: LU respecto del total} para drums, bass, vocals, other. Un
    grupo casi en silencio (más de 30 LU abajo) vale None. Devuelve None si
    el separador no está instalado o falla."""
    path = Path(path)
    clave = f"{MODELO}:{_hash_archivo(path)}"
    cache = _leer_cache()
    if clave in cache:
        return cache[clave]
    if not disponible():
        log.warning("Separador no instalado (torch/demucs): no se mide el balance de la referencia")
        return None
    try:
        import torch
        from demucs.apply import apply_model
        from demucs.pretrained import get_model

        if progreso:
            progreso(f"Separando la referencia por instrumento ({path.name}, 1-3 min la primera vez)…")
        modelo = get_model(MODELO)
        modelo.eval()
        audio, sr = cargar_audio(path)
        if audio.shape[1] == 1:
            audio = np.repeat(audio, 2, axis=1)
        if sr != modelo.samplerate:
            from math import gcd
            g = gcd(modelo.samplerate, sr)
            audio = signal.resample_poly(audio, modelo.samplerate // g, sr // g, axis=0)
            sr = modelo.samplerate
        wav = torch.tensor(audio.T, dtype=torch.float32)
        ref = wav.mean(0)
        media, desvio = ref.mean(), ref.std() + 1e-8
        with torch.no_grad():
            fuentes = apply_model(modelo, ((wav - media) / desvio)[None], device="cpu",
                                  split=True, overlap=0.25, progress=False)[0]
        fuentes = (fuentes * desvio + media).numpy()

        total = lufs_integrado(audio, sr)
        balance = {}
        for nombre, fuente in zip(modelo.sources, fuentes):
            l = lufs_integrado(fuente.T.astype(np.float64), sr)
            balance[nombre] = (round(float(l - total), 1)
                               if np.isfinite(l) and l - total > -30 else None)
        cache[clave] = balance
        CACHE.write_text(json.dumps(cache, indent=1), encoding="utf-8")
        log.info("Balance de %s: %s", path.name, balance)
        return balance
    except Exception:
        log.exception("Falló la separación de %s", path.name)
        return None
