"""Pone los stems de Moises a tempo fijo y genera un click exacto (método v0.4 de REGISTRO_app_tempo.md).

Uso: python stems_fix.py "<carpeta stems Moises>" "<carpeta salida>" [BPM] [--forzar-estirar] [--fase=0..3]

--fase fija en qué tiempo cae el "1" (lo usa el botón "mover el 1" de Tempo Genius).

No depende de MixMaster. Necesita numpy, scipy, soundfile (lee MP3) y pylibrb (solo en modo estirar).
"""
import json
import re
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import butter, resample_poly, sosfiltfilt

SR = 44100
RE_STEM = re.compile(r"-([^-]+)-[A-G][b#]? (major|minor)")   # sin ignorar mayúsculas ("LETRA")
RE_TEMA = re.compile(r"^(.*)-[A-G][b#]? (major|minor)-")
RE_BPM = re.compile(r"(\d+(?:\.\d+)?)bpm")
DRUMS = {"drums", "bateria", "batería"}
CLICKS = {"metronome", "click", "metronomo", "metrónomo"}

TOL_TEMPO = 0.03         # tramo a tempo: ±3 % del BPM
TOL_BPM_ESTUDIO = 0.0005  # ajuste lineal a ±0.05 %
TOL_TERCIO = 0.001       # cada tercio a ±0.1 %
MAX_SECCION_MS = 8.0     # ninguna sección de 24 tiempos corrida más de 8 ms
UMBRAL_CHEQUEO_MS = 3.0  # chequeo final: si la batería queda a más de 3 ms del click, se corre todo


# ---------- audio ----------

def cargar(path):
    x, sr = sf.read(str(path), dtype="float32", always_2d=True)
    if sr != SR:
        x = resample_poly(x, SR, sr, axis=0).astype(np.float32)
    return x


def suavizar(e, ms):
    n = max(1, int(SR * ms / 1000))
    return np.convolve(e, np.ones(n, np.float32) / n, mode="same")


def envolvente(x, ms=2):
    return suavizar(np.abs(x.mean(axis=1)), ms)


def desplazar(x, s):
    """Corre el audio s segundos (positivo = más tarde, agrega silencio; negativo = recorta el inicio)."""
    n = int(round(s * SR))
    if n >= 0:
        return np.concatenate([np.zeros((n, x.shape[1]), x.dtype), x])
    return x[-n:]


# ---------- mediciones ----------

def detectar_clicks(x):
    e = suavizar(np.abs(x.mean(axis=1)), 1)
    umbral = 0.3 * np.percentile(e, 99.9)
    arriba = e > umbral
    subidas = np.flatnonzero(arriba[1:] & ~arriba[:-1]) + 1
    out = []
    for r in subidas:
        if not out or r - out[-1] > 0.1 * SR:
            out.append(r)
    return np.array(out) / SR


def ataque_erp(env, tiempos, pre=0.15, post=0.15):
    """Promedia env alrededor de los tiempos (ERP) y devuelve (ataque al 50 % del pico relativo al tiempo, pico)."""
    a, b = int(pre * SR), int(post * SR)
    idx = np.round(np.asarray(tiempos) * SR).astype(int)
    idx = idx[(idx - a >= 0) & (idx + b < len(env))]
    if len(idx) == 0:
        return None, 0.0
    seg = np.mean([env[i - a:i + b] for i in idx], axis=0)
    base = np.median(seg[:int(0.07 * SR)])
    lo, hi = a - int(0.08 * SR), a + int(0.08 * SR)
    pk = lo + int(np.argmax(seg[lo:hi]))
    pico = seg[pk] - base
    if pico <= 0:
        return None, 0.0
    mitad = base + 0.5 * pico
    j = pk
    while j > 0 and seg[j] > mitad:
        j -= 1
    d = seg[j + 1] - seg[j]
    frac = (mitad - seg[j]) / d if d else 0.0
    return (j + frac - a) / SR, float(pico)


def ajuste_local(y, mitad):
    """Valor y pendiente de una recta ajustada en una ventana de ±mitad alrededor de cada índice."""
    n = len(y)
    idx = np.arange(n)
    val, pend = np.empty(n), np.empty(n)
    for i in range(n):
        lo, hi = max(0, i - mitad), min(n, i + mitad + 1)
        p = np.polyfit(idx[lo:hi], y[lo:hi], 1)
        val[i], pend[i] = np.polyval(p, i), p[0]
    return val, pend


def medir_tiempos(env, guia, ventana=8):
    """Corrige cada tiempo de la guía promediando la batería en una ventana de 17 tiempos."""
    off_global, pico_global = ataque_erp(env, guia)
    if off_global is None:
        raise SystemExit("No se encontró ataque de batería alrededor de los clicks.")
    n = len(guia)
    tiempos = np.empty(n)
    confiable = np.zeros(n, bool)
    for i in range(n):
        lo, hi = max(0, i - ventana), min(n, i + ventana + 1)
        off, pico = ataque_erp(env, guia[lo:hi])
        if off is not None and pico > 0.35 * pico_global:
            tiempos[i], confiable[i] = guia[i] + off, True
        else:
            tiempos[i] = guia[i] + off_global
    return tiempos, confiable, off_global


def tramo_a_tempo(tiempos, bpm):
    _, pend = ajuste_local(tiempos, 4)
    ok = np.abs((60.0 / pend) / bpm - 1) < TOL_TEMPO
    corridas, i = [], 0
    while i < len(ok):
        if ok[i]:
            j = i
            while j < len(ok) and ok[j]:
                j += 1
            if j - i >= 8:
                corridas.append((i, j - 1))
            i = j
        else:
            i += 1
    if not corridas:
        raise SystemExit("No hay ningún tramo a tempo cerca del BPM indicado.")
    return corridas[0][0], corridas[-1][1]


def fase_downbeat(drums, tiempos, a, z):
    """La caja cae en 2 y 4; el bombo decide entre las dos fases posibles."""
    mono = drums.mean(axis=1)
    bombo = suavizar(np.abs(sosfiltfilt(butter(4, 120, "lowpass", fs=SR, output="sos"), mono)), 5)
    caja = suavizar(np.abs(sosfiltfilt(butter(4, [1500, 5000], "bandpass", fs=SR, output="sos"), mono)), 5)

    def fuerza(env):
        f = np.zeros(len(tiempos))
        for i, t in enumerate(tiempos):
            lo, hi = int((t - 0.02) * SR), int((t + 0.06) * SR)
            if lo >= 0 and hi < len(env):
                f[i] = env[lo:hi].max()
        return f

    fb, fc = fuerza(bombo), fuerza(caja)
    idx = np.arange(a, z + 1)
    caja_par = [fc[idx[idx % 2 == q]].mean() for q in (0, 1)]
    q = int(np.argmax(caja_par))          # paridad de los tiempos 2 y 4
    p0 = (q + 1) % 2
    puntaje = {}
    for p in (p0, p0 + 2):
        puntaje[p] = float(fb[idx[idx % 4 == p]].mean() - fb[idx[idx % 4 == (p + 2) % 4]].mean())
    p = max(puntaje, key=puntaje.get)
    return p, {"caja_por_paridad": [float(v) for v in caja_par], "bombo_por_fase": puntaje}


def secciones(env, tiempos, largo, con_bateria):
    """Desfase promedio de la batería respecto de los tiempos, por secciones (ms).

    Solo cuenta los tiempos donde hay batería: sin golpes no hay referencia y la sección queda en None.
    """
    out = []
    for i in range(0, len(tiempos), largo):
        t = tiempos[i:i + largo][con_bateria[i:i + largo]]
        off = ataque_erp(env, t)[0] if len(t) >= largo // 2 else None
        out.append(None if off is None else round(float(off) * 1000, 1))
    return out


def peor(secs):
    vals = [abs(v) for v in secs if v is not None]
    return max(vals) if vals else 0.0


# ---------- estirar ----------

def estirar(x, mapa, largo):
    """Estira siguiendo el mapa (muestra real → muestra en la grilla) sin cambiar el tono.

    pylibrb no acepta el mapa de Rubber Band (set_keyframe_map falla), así que se usa el modo en tiempo
    real cambiando la proporción tramo a tramo para que cada tiempo caiga donde indica el mapa.
    """
    import pylibrb as rb
    O = rb.Option
    opciones = (O.PROCESS_REALTIME | O.ENGINE_FASTER | O.TRANSIENTS_CRISP | O.DETECTOR_COMPOUND
                | O.PHASE_INDEPENDENT | O.WINDOW_SHORT)   # equivale a R2 --crisp 6
    a = np.ascontiguousarray(x.T, dtype=np.float32)
    n = a.shape[1]
    puntos = [(0, 0)] + mapa + [(n, largo)]
    st = rb.RubberBandStretcher(SR, a.shape[0], opciones, puntos[1][1] / max(1, puntos[1][0]), 1.0)
    quitar = st.get_start_delay()
    st.process(np.zeros((a.shape[0], st.get_preferred_start_pad()), np.float32))
    out, virtual, k, i = [], 0.0, 0, 0
    while i < n:
        while k < len(puntos) - 2 and i >= puntos[k + 1][0]:
            k += 1
        o1, d1 = puntos[k + 1]
        fin = min(i + 1024, o1, n)
        ratio = min(2.0, max(0.5, (d1 - virtual) / (o1 - i)))
        st.time_ratio = ratio
        st.process(a[:, i:fin], final=fin >= n)
        virtual += (fin - i) * ratio
        i = fin
        while (m := st.available()) > 0:
            out.append(st.retrieve(m))
    y = np.concatenate(out, axis=1).T[quitar:]
    if len(y) < largo:
        y = np.concatenate([y, np.zeros((largo - len(y), y.shape[1]), y.dtype)])
    return y[:largo]


def procesar(x, plan):
    """Aplica el plan (desplazar y, si corresponde, estirar) a un stem."""
    y = desplazar(x, plan["s_ini"])
    if plan["mapa"] is not None:
        y = estirar(y, plan["mapa"], len(y) + plan["extra"])
    return desplazar(y, plan["s_fin"])


def armar_mapa(origen, destino, n_entrada):
    mapa, ult_o, ult_d = [], 0, 0
    for o, d in zip(np.round(origen * SR).astype(int), np.round(destino * SR).astype(int)):
        if 0 < o < n_entrada and o > ult_o and d > ult_d:
            mapa.append((int(o), int(d)))
            ult_o, ult_d = o, d
    return mapa


# ---------- click ----------

def generar_click(tiempos, acentos, largo):
    y = np.zeros(largo, np.float32)
    n = int(0.03 * SR)
    t = np.arange(n) / SR
    env = np.exp(-t * 150)
    tonos = {True: (np.sin(2 * np.pi * 1500 * t) * env * 0.8).astype(np.float32),
             False: (np.sin(2 * np.pi * 1000 * t) * env * 0.6).astype(np.float32)}
    for ti, ac in zip(tiempos, acentos):
        i = int(round(ti * SR))
        if 0 <= i < largo:
            k = min(n, largo - i)
            y[i:i + k] += tonos[bool(ac)][:k]
    return np.stack([y, y], axis=1)


# ---------- principal ----------

def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    forzar = "--forzar-estirar" in sys.argv
    fase_forzada = next((int(x.split("=")[1]) % 4 for x in sys.argv if x.startswith("--fase=")), None)
    if len(args) < 2:
        raise SystemExit(__doc__)
    entrada, salida = Path(args[0]), Path(args[1])
    m = RE_BPM.search(entrada.name)
    bpm = float(args[2]) if len(args) > 2 else (float(m.group(1)) if m else None)
    if bpm is None:
        raise SystemExit("No se encontró el BPM en el nombre de la carpeta; pásalo como tercer argumento.")
    mt = RE_TEMA.match(entrada.name)
    tema = mt.group(1).strip() if mt else entrada.name

    stems = {}
    for f in sorted(entrada.iterdir()):
        if f.suffix.lower() not in (".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aiff", ".aif"):
            continue
        ms = RE_STEM.search(f.stem)
        stems[ms.group(1) if ms else f.stem] = f
    n_drums = next((k for k in stems if k.lower() in DRUMS), None)
    n_click = next((k for k in stems if k.lower() in CLICKS), None)
    if not n_drums or not n_click:
        raise SystemExit(f"Faltan stems de batería o metrónomo. Encontrados: {list(stems)}")
    musicales = [k for k in stems if k != n_click]
    print(f"{tema} | {bpm} BPM | stems: {', '.join(musicales)}")

    drums = cargar(stems[n_drums])
    env = envolvente(drums)
    clicks = detectar_clicks(cargar(stems[n_click]))
    if len(clicks) < 32:
        raise SystemExit("El metrónomo de Moises tiene muy pocos clicks.")

    # inicio de la música (para dejar como máximo un compás de click antes)
    inicio = None
    for k in musicales:
        x = cargar(stems[k]) if k != n_drums else drums
        e = suavizar(np.abs(x.mean(axis=1)), 50)
        on = np.flatnonzero(e > 0.02 * e.max())
        if len(on):
            t = on[0] / SR
            inicio = t if inicio is None else min(inicio, t)
        del x

    guia, _ = ajuste_local(clicks, 8)          # el click de Moises redondea a 20 ms: se suaviza
    tiempos, confiable, off_global = medir_tiempos(env, guia)
    a, z = tramo_a_tempo(tiempos, bpm)
    fase, fase_info = fase_downbeat(drums, tiempos, a, z)
    if fase_forzada is not None:
        fase_info["detectada"], fase = fase, fase_forzada
    P = 60.0 / bpm
    compas = 4 * P

    j = np.arange(a, z + 1)
    tt = tiempos[a:z + 1]
    bpm_ajuste = 60.0 / np.polyfit(j, tt, 1)[0]
    tercios = [60.0 / np.polyfit(jj, t3, 1)[0] for jj, t3 in zip(np.array_split(j, 3), np.array_split(tt, 3))]
    resid = tt - j * P
    resid -= resid[confiable[a:z + 1]].mean()
    cb = confiable[a:z + 1]
    secs24 = [float(np.mean(resid[i:i + 24][cb[i:i + 24]]) * 1000) for i in range(0, len(resid), 24)
              if cb[i:i + 24].sum() >= 12]
    estudio = (not forzar and abs(bpm_ajuste / bpm - 1) < TOL_BPM_ESTUDIO
               and all(abs(b / bpm - 1) < TOL_TERCIO for b in tercios)
               and max(abs(v) for v in secs24) <= MAX_SECCION_MS)

    # grilla de salida: el "1" en inicio de compás, con la música dentro del primer compás
    jd = next(i for i in range(a, z + 1) if (i - fase) % 4 == 0)
    rel = (j - jd) * P
    s_base = float(np.mean(rel - tt)) if estudio else rel[0] - tt[0]
    K = int(np.ceil((0.05 - inicio - s_base) / compas))
    destino_tempo = rel + K * compas
    s_ini = s_base + K * compas
    print(f"ajuste {bpm_ajuste:.4f} BPM | tercios {', '.join(f'{b:.3f}' for b in tercios)} | "
          f"peor sección {max(abs(v) for v in secs24):.1f} ms | modo {'ESTUDIO' if estudio else 'ESTIRAR'} | a tempo: tiempos {a}-{z} de {len(tiempos)}")

    # destino de todos los tiempos (los tramos libres conservan su forma)
    destino = tiempos + s_ini
    if not estudio:
        destino[a:z + 1] = destino_tempo
        destino[z + 1:] = tiempos[z + 1:] + (destino_tempo[-1] - tiempos[z])
    else:
        destino[a:z + 1] = destino_tempo

    log = {"tema": tema, "bpm": bpm, "bpm_ajuste": round(bpm_ajuste, 4), "tercios": [round(b, 4) for b in tercios],
           "secciones_24_ms": [round(v, 1) for v in secs24], "modo": "estudio" if estudio else "estirar",
           "offset_click_bateria_ms": round(off_global * 1000, 1), "tiempos_confiables": int(confiable.sum()),
           "tiempos": len(tiempos), "tramo_a_tempo": {"desde_tiempo": a, "hasta_tiempo": z,
           "desde_s": round(tiempos[a], 2), "hasta_s": round(tiempos[z], 2)},
           "inicio_libre": a > 0, "final_libre": z < len(tiempos) - 1,
           "downbeat_fase": fase, "downbeat_detalle": fase_info, "inicio_musica_s": round(inicio, 3)}

    # plan y pasadas sobre la batería
    if estudio:
        plan = {"s_ini": s_ini, "mapa": None, "extra": 0, "s_fin": 0.0}
        d_out = procesar(drums, plan)
    else:
        n_in = len(drums) + int(round(s_ini * SR))
        extra = int(round((destino[-1] - (tiempos[-1] + s_ini)) * SR))
        origen = tiempos[a:z + 1] + s_ini
        pasadas = []
        objetivo = destino_tempo.copy()
        for k in range(2):
            plan = {"s_ini": s_ini, "mapa": armar_mapa(origen, objetivo, n_in), "extra": extra, "s_fin": 0.0}
            d_out = procesar(drums, plan)
            env_o = envolvente(d_out)
            error = peor(secciones(env_o, destino_tempo, 32, confiable[a:z + 1]))
            print(f"  pasada {k + 1}: peor sección {error:.1f} ms")
            pasadas.append((error, plan, d_out))
            # 2.ª pasada: medir el resultado con el mismo método robusto y corregir lo que queda
            medidos, _, _ = medir_tiempos(env_o, destino_tempo)
            objetivo = objetivo - (medidos - destino_tempo)
        error, plan, d_out = min(pasadas, key=lambda p: p[0])
        log["pasadas_peor_seccion_ms"] = [round(p[0], 1) for p in pasadas]

    # chequeo final independiente: batería de salida contra el click de salida
    env_o = envolvente(d_out)
    off_final, _ = ataque_erp(env_o, destino[a:z + 1])
    if off_final is not None and abs(off_final * 1000) > UMBRAL_CHEQUEO_MS:
        plan["s_fin"] = -off_final
        d_out = desplazar(d_out, -off_final)
        env_o = envolvente(d_out)
        print(f"  chequeo final: corrido {off_final * 1000:+.1f} ms → se corrige")
    verif = secciones(env_o, destino[a:z + 1], 32, confiable[a:z + 1])
    log["chequeo_final_ms"] = None if off_final is None else round(off_final * 1000, 1)
    log["verificacion_secciones_32_ms"] = verif
    print(f"  verificación por secciones de 32 tiempos (ms): {verif}")

    # click: tiempos de salida + cuenta previa hacia atrás hasta 0
    previos = []
    t = destino[0] - P
    while t > -1e-6:
        previos.insert(0, t)
        t -= P
    click_t = np.concatenate([previos, destino])
    indices = np.concatenate([np.arange(-len(previos), 0), np.arange(len(destino))])
    acentos = (indices - fase) % 4 == 0

    # salida
    salida.mkdir(parents=True, exist_ok=True)
    base = f"{tema} - {bpm:g} BPM"
    mezcla = None
    for k in musicales:
        y = d_out if k == n_drums else procesar(cargar(stems[k]), plan)
        sf.write(str(salida / f"{base} - {k}.flac"), y, SR, subtype="PCM_24")
        if mezcla is None:
            mezcla = y.astype(np.float32).copy()
        else:
            n = max(len(mezcla), len(y))
            mezcla = np.pad(mezcla, ((0, n - len(mezcla)), (0, 0)))
            mezcla[:len(y)] += y
        print(f"  {k} listo")
    pico = float(np.abs(mezcla).max())
    if pico > 0.999:
        mezcla *= 0.999 / pico
        log["mezcla_bajada_db"] = round(20 * np.log10(0.999 / pico), 2)
    sf.write(str(salida / f"{base} - MEZCLA.flac"), mezcla, SR, subtype="PCM_24")
    sf.write(str(salida / f"{base} - CLICK.flac"), generar_click(click_t, acentos, len(mezcla)), SR, subtype="PCM_24")
    log["desplazamiento_s"] = round(s_ini + plan["s_fin"], 4)
    (salida / "log.json").write_text(json.dumps(log, ensure_ascii=False, indent=2, default=float), encoding="utf-8")
    print(f"Listo: {salida}")


if __name__ == "__main__":
    main()
