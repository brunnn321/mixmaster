"""Prueba de Tempo Genius con audio sintético (no usa temas de Bruno).

Arma un "tema" de 120 BPM cuyo tempo se mueve ±1.5 % con un poco de imprecisión
humana, en tres formas: stems de Moises con metrónomo, la misma multipista con
compás de 3 y un solo audio sin metrónomo ni BPM en el nombre. Comprueba que la
batería cae sobre el click, que bajo y batería siguen juntos, los nombres con el
BPM, el reporte y el BPM detectado.

Uso:  .venv\\Scripts\\python tempo\\tests\\test_sintetico.py
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

SR = 44100
BPM = 120
SCRIPT = Path(__file__).resolve().parents[1] / "stems_fix.py"
rng = np.random.default_rng(5)
fallos = []


def check(nombre, ok, detalle=""):
    print(f"[{'OK ' if ok else 'FAIL'}] {nombre} — {detalle}")
    if not ok:
        fallos.append(nombre)


def tiempos_reales(n=96):
    """Pulsos de un baterista: el tempo ondula ±1.5 % y cada golpe se corre ±2 ms."""
    P = 60.0 / BPM
    k = np.arange(n)
    periodo = P * (1 + 0.015 * np.sin(2 * np.pi * k / 40))
    t = 1.0 + np.concatenate([[0], np.cumsum(periodo[:-1])])
    return t + rng.uniform(-0.002, 0.002, n)


def golpe(f, dur, decay, ruido=0.0):
    t = np.arange(int(dur * SR)) / SR
    x = np.sin(2 * np.pi * f * t) * np.exp(-t / decay)
    if ruido:
        x += ruido * rng.standard_normal(len(t)) * np.exp(-t / (decay / 2))
    return x


def pistas(beats):
    n = int((beats[-1] + 2.0) * SR)
    drums, bajo, metro = np.zeros(n), np.zeros(n), np.zeros(n)
    kick, snare = golpe(60, 0.25, 0.06), golpe(200, 0.2, 0.05, ruido=0.8)
    nota = golpe(55, 0.4, 0.15) + 0.5 * golpe(110, 0.4, 0.1)
    clk = golpe(1000, 0.02, 0.004)
    for i, b in enumerate(beats):
        j = int(b * SR)
        g = kick if i % 2 == 0 else snare
        drums[j:j + len(g)] += 0.5 * g
        bajo[j:j + len(nota)] += 0.4 * nota
        jm = int(round(b / 0.02) * 0.02 * SR)          # Moises redondea su click a 20 ms
        metro[jm:jm + len(clk)] += 0.5 * clk
    return drums, bajo, metro


def ataques(x, cerca):
    """Ataque (50 % del pico local) de cada golpe cercano a los tiempos dados."""
    e = np.convolve(np.abs(x if x.ndim == 1 else x.mean(axis=1)), np.ones(44) / 44, "same")
    out = []
    for c in cerca:
        a, b = int((c - 0.06) * SR), int((c + 0.06) * SR)
        if a < 0 or b >= len(e):
            out.append(np.nan)
            continue
        seg = e[a:b]
        pk = int(np.argmax(seg))
        j = pk
        while j > 0 and seg[j] > 0.5 * seg[pk]:
            j -= 1
        out.append((a + j) / SR)
    return np.array(out)


def clicks_de(x):
    m = x.mean(axis=1)
    e = np.abs(m)
    on, i = [], 0
    while i < len(e):
        if e[i] > 0.2:
            seg = m[i:i + 600]
            f = np.argmax(np.abs(np.fft.rfft(seg, 8192))) * SR / 8192
            on.append((i / SR, f > 1250))
            i += int(0.1 * SR)
        else:
            i += 1
    return on


def correr(entrada, salida, *extra):
    r = subprocess.run([sys.executable, str(SCRIPT), str(entrada), str(salida), *extra],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"})
    if r.returncode != 0:
        print(r.stdout[-2000:], r.stderr[-2000:])
    return r.returncode == 0


def revisar_precision(salida, nombre_bat, etiqueta, con_bajo=True, limite_seccion=3.0):
    """Mismo criterio que el registro: promedio por secciones de 32 pulsos (meta del plan: ±3 ms con
    stems, ±5 ms sin stems). Golpe a golpe manda la imprecisión humana de ±2 ms del baterista."""
    click = sf.read(str(salida / f"Click {etiqueta}.flac"), always_2d=True)[0]
    bat = sf.read(str(salida / f"{nombre_bat} {etiqueta}.flac"), always_2d=True)[0]
    c = np.array([t for t, _ in clicks_de(click)])
    c = c[(c > c[0] + 4 * 60 / BPM) & (c < c[-1] - 4 * 60 / BPM)]
    d = (ataques(bat, c) - c) * 1000
    d = d[~np.isnan(d)]
    secciones = [float(np.mean(d[i:i + 32])) for i in range(0, len(d) - 15, 32)]
    peor = max(abs(s) for s in secciones)
    check(f"{salida.name}: la batería cae sobre el click", peor <= limite_seccion,
          f"peor sección {peor:.1f} ms (meta ±{limite_seccion:g}); golpe a golpe el 95 % dentro de "
          f"{np.percentile(np.abs(d), 95):.1f} ms")
    if con_bajo:
        bajo = sf.read(str(salida / f"Bajo {etiqueta}.flac"), always_2d=True)[0]
        dif = (ataques(bajo, c) - ataques(bat, c)) * 1000
        dif = dif[~np.isnan(dif)]
        ref = (ataques(np.pad(bajo_in, (0, 0)), beats) - ataques(drums_in, beats)) * 1000
        cambio = np.median(dif) - np.nanmedian(ref)
        check(f"{salida.name}: bajo y batería siguen juntos", abs(cambio) < 1.5,
              f"cambio de la distancia bajo–batería {cambio:+.2f} ms")
    return c


tmp = Path(tempfile.mkdtemp(prefix="tempo_sintetico_"))
beats = tiempos_reales()
drums_in, bajo_in, metro = pistas(beats)

# 1) stems de Moises con metrónomo
moises = tmp / "Prueba-A minor-120bpm-440hz"
moises.mkdir()
for nombre, x in (("drums", drums_in), ("bass", bajo_in), ("metronome", metro)):
    sf.write(str(moises / f"Prueba-{nombre}-A minor-120bpm-440hz.wav"), x, SR, subtype="FLOAT")
sal1 = tmp / "salida_moises"
check("stems de Moises: el script termina", correr(moises, sal1))
if sal1.exists():
    nombres = sorted(p.name for p in sal1.iterdir())
    esperados = {"Batería 120bpm.flac", "Bajo 120bpm.flac", "Mezcla 120bpm.flac", "Click 120bpm.flac",
                 "Tempo 120bpm.mid", "REPORTE.txt", "log.json"}
    check("nombres con el BPM y reporte", esperados <= set(nombres), str(nombres))
    revisar_precision(sal1, "Batería", "120bpm")
    rep = (sal1 / "REPORTE.txt").read_text(encoding="utf-8")
    check("el reporte está en palabras", "120 BPM" in rep and "Studio One" in rep, rep.splitlines()[0])

# 2) compás de 3: acento cada 3 pulsos
sal2 = tmp / "salida_tres"
check("compás de 3: el script termina", correr(moises, sal2, "--compas=3"))
if sal2.exists():
    on = clicks_de(sf.read(str(sal2 / "Click 120bpm.flac"), always_2d=True)[0])
    idx = [i for i, (_, ac) in enumerate(on) if ac]
    pasos = set(np.diff(idx))
    check("compás de 3: acento cada 3 pulsos", pasos == {3}, f"separación entre acentos {sorted(pasos)}")

# 3) un solo audio, sin metrónomo y sin BPM en el nombre
solo = tmp / "Prueba sin datos.wav"
sf.write(str(solo), np.stack([drums_in + bajo_in] * 2, axis=1) * 0.7, SR, subtype="FLOAT")
sal3 = tmp / "salida_solo"
check("audio solo: el script termina", correr(solo, sal3, "0"))
if sal3.exists():
    info = json.loads((sal3 / "log.json").read_text(encoding="utf-8"))
    check("audio solo: BPM detectado", info["bpm_detectado"] and abs(info["bpm"] - BPM) < 1, f"{info['bpm']}")
    etq = f"{info['bpm']:g}bpm"
    if (sal3 / f"Mezcla {etq}.flac").exists():
        revisar_precision(sal3, "Mezcla", etq, con_bajo=False, limite_seccion=5.0)

print(f"\nCarpeta de la prueba: {tmp}")
print(f"RESULTADO: {'todos los checks pasaron' if not fallos else f'{len(fallos)} fallo(s): {fallos}'}")
sys.exit(1 if fallos else 0)
