"""Volumen guiado por crest (14/10): con target automático el master debe quedar
cerca de crest 10 dB, la zona que Bruno aprobó, sea la mezcla dinámica o ya
apretada. Sin pytest.

Uso:  .venv\\Scripts\\python tests\\test_volumen_crest.py
"""

import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy import signal

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mixmaster.processing import masterizar

SR = 44100
rng = np.random.default_rng(14)
fallos = []


def check(nombre, ok, detalle=""):
    print(f"[{'OK ' if ok else 'FAIL'}] {nombre} — {detalle}")
    if not ok:
        fallos.append(nombre)


def mezcla(golpe_db: float, dur=30.0) -> np.ndarray:
    """Colchón de ruido rosado + golpes de bombo y caja: `golpe_db` controla cuánto
    sobresalen los golpes (más alto = mezcla más dinámica, crest más alto)."""
    n = int(SR * dur)
    b, a = signal.butter(1, 800, fs=SR)
    colchon = signal.lfilter(b, a, rng.standard_normal(n)) * 0.05
    golpes = np.zeros(n)
    t = np.arange(int(0.2 * SR)) / SR
    kick = np.sin(2 * np.pi * 55 * t) * np.exp(-t / 0.05)
    for k, i in enumerate(range(0, n - len(t), int(0.5 * SR))):
        golpes[i:i + len(t)] += kick if k % 2 == 0 else rng.standard_normal(len(t)) * np.exp(-t / 0.03)
    x = colchon + golpes * 0.05 * 10 ** (golpe_db / 20)
    x = np.stack([x, x * 0.98], axis=1)
    return x / np.max(np.abs(x)) * 0.5


tmp = Path(tempfile.mkdtemp(prefix="crest_"))
for nombre, golpe in (("dinámica", 18.0), ("apretada", 6.0)):
    entrada = tmp / f"{nombre}.wav"
    sf.write(str(entrada), mezcla(golpe), SR, subtype="PCM_24")
    (tmp / nombre).mkdir()
    r = masterizar(entrada, None, None, tmp / nombre, tmp / nombre)
    check(f"{nombre}: el objetivo se eligió por crest", r.get("target_por_crest") is True,
          f"objetivo {r['target_lufs']} LUFS, quedó en {r['lufs_final']} LUFS")
    check(f"{nombre}: crest final en la zona (8.5–11.5 dB)", 8.5 <= r["crest_final"] <= 11.5,
          f"crest {r['crest_final']:.1f} dB")

print(f"\nRESULTADO: {'todos los checks pasaron' if not fallos else f'{len(fallos)} fallo(s): {fallos}'}")
sys.exit(1 if fallos else 0)
