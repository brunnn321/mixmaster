"""Análisis de audio local: LUFS, espectro por bandas, estéreo, secciones.

El audio nunca sale del disco: este módulo solo produce números y texto.
Dependencias: soundfile, pyloudnorm, numpy, scipy.
"""

from datetime import datetime
from pathlib import Path

import numpy as np
import pyloudnorm as pyln
import soundfile as sf
from scipy import signal

from .logger import get_logger

log = get_logger("mixmaster.analysis")

# Bandas espectrales (Hz), 7 bandas. "air" llega hasta Nyquist.
BANDAS_HZ = {
    "sub": (20, 60),
    "low": (60, 200),
    "low_mid": (200, 500),
    "mid": (500, 2000),
    "high_mid": (2000, 6000),
    "high": (6000, 10000),
    "air": (10000, 20000),
}

VENTANA_ST_S = 3.0        # ventana short-term LUFS (EBU R128)
PASO_ST_S = 1.0           # paso entre ventanas short-term
UMBRAL_CLIP = 0.9995      # amplitud considerada "en el techo"
MUESTRAS_CLIP = 3         # nº de muestras consecutivas en el techo = clipping


# ---------------------------------------------------------------- utilidades

def db(x: float, floor: float = -100.0) -> float:
    """Convierte lineal a dB con piso para evitar log(0)."""
    if x <= 0:
        return floor
    return float(max(20.0 * np.log10(x), floor))


def parse_tiempo(txt: str) -> float:
    """Convierte 'm:ss', 'h:mm:ss' o segundos ('12.5') a segundos."""
    txt = txt.strip()
    partes = txt.split(":")
    try:
        if len(partes) == 1:
            return float(partes[0])
        segs = 0.0
        for p in partes:
            segs = segs * 60 + float(p)
        return segs
    except ValueError:
        raise ValueError(f"Tiempo no reconocido: '{txt}' (usa m:ss o segundos)")


def parse_marcadores(texto: str, duracion_s: float) -> list[dict]:
    """Parsea marcadores manuales tipo 'Intro: 0:00, Riff A: 0:23'.

    Devuelve lista de {nombre, inicio_s, fin_s} ordenada; el fin de cada
    sección es el inicio de la siguiente (la última termina en la duración).
    """
    if not texto.strip():
        return []
    crudos = []
    for trozo in texto.replace("\n", ",").split(","):
        trozo = trozo.strip()
        if not trozo:
            continue
        if ":" not in trozo:
            raise ValueError(f"Marcador sin ':' → '{trozo}'")
        nombre, _, tiempo = trozo.partition(":")
        crudos.append({"nombre": nombre.strip(), "inicio_s": parse_tiempo(tiempo)})

    crudos.sort(key=lambda m: m["inicio_s"])
    secciones = []
    for i, m in enumerate(crudos):
        fin = crudos[i + 1]["inicio_s"] if i + 1 < len(crudos) else duracion_s
        if fin > m["inicio_s"]:
            secciones.append({"nombre": m["nombre"], "inicio_s": m["inicio_s"], "fin_s": fin})
    return secciones


# ------------------------------------------------------------ carga de audio

FORMATOS_SOPORTADOS = (".wav", ".mp3", ".flac", ".ogg", ".aiff", ".aif", ".m4a", ".wma")


def cargar_audio(path: Path) -> tuple[np.ndarray, int]:
    """Carga un archivo de audio (WAV, MP3, FLAC, OGG…) como float64.

    Intenta soundfile (rápido, formatos nativos de libsndfile) y si el
    formato no está soportado cae a librosa/audioread (m4a, wma, etc.).
    """
    try:
        audio, sr = sf.read(str(path), always_2d=True)
    except Exception:
        log.info("soundfile no pudo leer %s; probando librosa", path.name)
        import librosa
        y, sr = librosa.load(str(path), sr=None, mono=False)
        audio = y.T if y.ndim > 1 else y[:, np.newaxis]
    if audio.shape[1] > 2:
        audio = audio[:, :2]  # solo consideramos L/R
    return audio.astype(np.float64), int(sr)


# Alias por compatibilidad con código/tests previos
cargar_wav = cargar_audio


# --------------------------------------------------------------- mediciones

def lufs_integrado(audio: np.ndarray, sr: int) -> float:
    """LUFS integrado (BS.1770 vía pyloudnorm)."""
    meter = pyln.Meter(sr)
    return float(meter.integrated_loudness(audio))


def lufs_short_term(audio: np.ndarray, sr: int) -> tuple[list[float], list[float]]:
    """Serie de LUFS short-term (ventanas de 3 s, paso 1 s).

    Devuelve (tiempos_centro_s, valores_lufs). Ventanas silenciosas dan -inf
    y se filtran.
    """
    meter = pyln.Meter(sr, block_size=0.400)
    n = audio.shape[0]
    win = int(VENTANA_ST_S * sr)
    paso = int(PASO_ST_S * sr)
    tiempos, valores = [], []
    if n < win:
        v = lufs_integrado(audio, sr)
        return [n / sr / 2], [v]
    for ini in range(0, n - win + 1, paso):
        bloque = audio[ini:ini + win]
        try:
            v = float(meter.integrated_loudness(bloque))
        except Exception:
            continue
        if np.isfinite(v):
            tiempos.append((ini + win / 2) / sr)
            valores.append(v)
    return tiempos, valores


def lra(valores_st: list[float]) -> float:
    """LRA aproximado: percentil 95 - percentil 10 del short-term gateado.

    Gating relativo simple a -20 LU del promedio (aprox. EBU Tech 3342).
    """
    v = np.array([x for x in valores_st if np.isfinite(x)])
    if v.size < 2:
        return 0.0
    umbral = v.mean() - 20.0
    v = v[v >= umbral]
    if v.size < 2:
        return 0.0
    return float(np.percentile(v, 95) - np.percentile(v, 10))


def true_peak_db(audio: np.ndarray, sr: int) -> float:
    """True peak (dBTP) con sobremuestreo 4x."""
    up = signal.resample_poly(audio, 4, 1, axis=0)
    return db(float(np.max(np.abs(up))))


def crest_factor_db(audio: np.ndarray) -> float:
    """Crest factor global: pico dB - RMS dB. Alto = transientes vivos."""
    pico = float(np.max(np.abs(audio)))
    rms = float(np.sqrt(np.mean(audio ** 2)))
    if rms <= 0 or pico <= 0:
        return 0.0
    return db(pico) - db(rms)


def detectar_clipping(audio: np.ndarray) -> bool:
    """True si hay >= MUESTRAS_CLIP muestras consecutivas pegadas al techo."""
    for ch in range(audio.shape[1]):
        techo = np.abs(audio[:, ch]) >= UMBRAL_CLIP
        if not techo.any():
            continue
        # longitud máxima de racha de True
        cambios = np.diff(techo.astype(np.int8))
        inicios = np.where(cambios == 1)[0]
        fines = np.where(cambios == -1)[0]
        if techo[0]:
            inicios = np.concatenate(([0], inicios + 1))
        else:
            inicios = inicios + 1
        if techo[-1]:
            fines = np.concatenate((fines + 1, [len(techo)]))
        else:
            fines = fines + 1
        if inicios.size and fines.size:
            if int(np.max(fines[:inicios.size] - inicios[:fines.size])) >= MUESTRAS_CLIP:
                return True
    return False


def _filtrar_banda(mono: np.ndarray, sr: int, f_lo: float, f_hi: float) -> np.ndarray:
    """Filtra pasa-banda Butterworth de 4º orden (o pasa-bajos/altos en extremos)."""
    nyq = sr / 2
    f_hi = min(f_hi, nyq * 0.999)
    if f_lo <= 20:
        sos = signal.butter(4, f_hi / nyq, btype="lowpass", output="sos")
    elif f_hi >= nyq * 0.99:
        sos = signal.butter(4, f_lo / nyq, btype="highpass", output="sos")
    else:
        sos = signal.butter(4, [f_lo / nyq, f_hi / nyq], btype="bandpass", output="sos")
    return signal.sosfilt(sos, mono)


def balance_bandas_db(audio: np.ndarray, sr: int) -> dict[str, float]:
    """Energía RMS (dBFS) por banda espectral, sobre la suma mono."""
    mono = audio.mean(axis=1)
    resultado = {}
    for nombre, (f_lo, f_hi) in BANDAS_HZ.items():
        banda = _filtrar_banda(mono, sr, f_lo, f_hi)
        resultado[nombre] = round(db(float(np.sqrt(np.mean(banda ** 2)))), 1)
    return resultado


def analisis_estereo(audio: np.ndarray, sr: int) -> dict:
    """Correlación L/R global, ancho por banda y compatibilidad mono."""
    if audio.shape[1] < 2:
        return {
            "correlacion_global": 1.0,
            "correlacion_por_banda": {b: 1.0 for b in BANDAS_HZ},
            "ancho_por_banda": {b: 0.0 for b in BANDAS_HZ},
            "perdida_mono_db": 0.0,
            "es_mono": True,
        }

    L, R = audio[:, 0], audio[:, 1]

    def correlacion(a: np.ndarray, b: np.ndarray) -> float:
        ea, eb = np.sqrt(np.mean(a ** 2)), np.sqrt(np.mean(b ** 2))
        if ea <= 1e-9 or eb <= 1e-9:
            return 1.0
        return float(np.clip(np.mean(a * b) / (ea * eb), -1.0, 1.0))

    corr_global = correlacion(L, R)

    corr_banda, ancho_banda = {}, {}
    for nombre, (f_lo, f_hi) in BANDAS_HZ.items():
        Lb = _filtrar_banda(L, sr, f_lo, f_hi)
        Rb = _filtrar_banda(R, sr, f_lo, f_hi)
        corr_banda[nombre] = round(correlacion(Lb, Rb), 2)
        mid = (Lb + Rb) / 2
        side = (Lb - Rb) / 2
        e_mid = float(np.mean(mid ** 2))
        e_side = float(np.mean(side ** 2))
        total = e_mid + e_side
        # ancho 0 = mono puro, 1 = todo side
        ancho_banda[nombre] = round(e_side / total, 2) if total > 1e-12 else 0.0

    # Compatibilidad mono: cuánto nivel se pierde al sumar L+R
    rms_st = float(np.sqrt(np.mean(((np.abs(L) + np.abs(R)) / 2) ** 2)))
    mono = (L + R) / 2
    rms_mono = float(np.sqrt(np.mean(mono ** 2)))
    perdida = db(rms_st) - db(rms_mono) if rms_mono > 0 else 99.0

    return {
        "correlacion_global": round(corr_global, 2),
        "correlacion_por_banda": corr_banda,
        "ancho_por_banda": ancho_banda,
        "perdida_mono_db": round(max(perdida, 0.0), 1),
        "es_mono": False,
    }


# ---------------------------------------------------------------- secciones

def analizar_secciones(audio: np.ndarray, sr: int, secciones: list[dict]) -> list[dict]:
    """LUFS short-term, pico y clipping por sección definida por marcadores."""
    resultado = []
    meter = pyln.Meter(sr, block_size=0.400)
    for sec in secciones:
        ini = int(sec["inicio_s"] * sr)
        fin = min(int(sec["fin_s"] * sr), audio.shape[0])
        trozo = audio[ini:fin]
        if trozo.shape[0] < sr // 2:  # menos de 0.5 s: se omite
            continue
        try:
            lufs_st = float(meter.integrated_loudness(trozo))
            if not np.isfinite(lufs_st):
                lufs_st = -70.0
        except Exception:
            lufs_st = -70.0
        pico = db(float(np.max(np.abs(trozo))))
        crest = crest_factor_db(trozo)

        notas = []
        if crest >= 18.0:
            notas.append("Crest factor alto — revisar transientes")
        if crest < 12.0:
            notas.append("Transientes comprimidos — vigilar")

        resultado.append({
            "nombre": sec["nombre"],
            "inicio_s": round(sec["inicio_s"], 2),
            "fin_s": round(sec["fin_s"], 2),
            "lufs_st": round(lufs_st, 1),
            "pico_max": round(pico, 1),
            "clipping": detectar_clipping(trozo),
            "crest_db": round(crest, 1),
            "notas_auto": notas,
        })
    return resultado


# -------------------------------------------------------------- vs referencia

def espectro_suavizado(audio: np.ndarray, sr: int, n_puntos: int = 31) -> tuple[np.ndarray, np.ndarray]:
    """Espectro suavizado a ~1/3 de octava: (frecuencias, dB) en n_puntos.

    Base del matching espectral fino: captura la huella tonal completa,
    no solo 7 bloques.
    """
    mono = audio.mean(axis=1) if audio.ndim > 1 else audio
    f, pxx = signal.welch(mono, sr, nperseg=min(8192, len(mono)))
    puntos = np.geomspace(25.0, min(19000.0, sr / 2 * 0.95), n_puntos)
    dbs = []
    for fc in puntos:
        lo, hi = fc / 2 ** (1 / 6), fc * 2 ** (1 / 6)  # ventana de 1/3 de octava
        sel = (f >= lo) & (f <= hi)
        p = float(pxx[sel].mean()) if sel.any() else 1e-20
        dbs.append(10 * np.log10(max(p, 1e-20)))
    return puntos, np.array(dbs)


def perfil_referencias(paths_ref, lufs_mix: float) -> dict:
    """Perfil tonal PROMEDIO de una o varias referencias, niveladas al LUFS
    de la mezcla. Devuelve {nombres, bandas_db, ancho_por_banda, lufs}.

    Con varias referencias se obtiene el "consenso" del género en vez de
    copiar un solo tema.
    """
    if isinstance(paths_ref, (str, Path)):
        paths_ref = [paths_ref]
    paths_ref = [Path(p) for p in paths_ref]

    bandas_acum, anchos_acum, lufs_refs, nombres = [], [], [], []
    espectros, crests = [], []
    freqs = None
    for p in paths_ref:
        audio_ref, sr_ref = cargar_audio(p)
        lufs_ref = lufs_integrado(audio_ref, sr_ref)
        if np.isfinite(lufs_ref) and np.isfinite(lufs_mix):
            audio_ref = audio_ref * (10 ** ((lufs_mix - lufs_ref) / 20))
        bandas_acum.append(balance_bandas_db(audio_ref, sr_ref))
        anchos_acum.append(analisis_estereo(audio_ref, sr_ref)["ancho_por_banda"])
        freqs, esp = espectro_suavizado(audio_ref, sr_ref)
        espectros.append(esp)
        crests.append(crest_factor_db(audio_ref))
        if np.isfinite(lufs_ref):
            lufs_refs.append(float(lufs_ref))
        nombres.append(p.name)

    bandas_prom = {b: round(float(np.mean([bb[b] for bb in bandas_acum])), 1)
                   for b in BANDAS_HZ}
    ancho_prom = {b: round(float(np.mean([aa[b] for aa in anchos_acum])), 2)
                  for b in BANDAS_HZ}
    return {
        "nombres": nombres,
        "bandas_db": bandas_prom,
        "ancho_por_banda": ancho_prom,
        "espectro_freqs": freqs,
        "espectro_db": np.mean(espectros, axis=0),
        "crest_db": round(float(np.mean(crests)), 1),
        "lufs": round(float(np.mean(lufs_refs)), 1) if lufs_refs else None,
    }


def comparar_referencia(mezcla: dict, paths_ref) -> dict:
    """Compara la mezcla contra una o varias referencias NIVELADAS en loudness.

    Con varias, los deltas son contra el promedio de todas (consenso tonal).
    """
    lufs_mix = mezcla["global"]["lufs_i"]
    perfil = perfil_referencias(paths_ref, lufs_mix)

    delta_bandas = {
        b: round(mezcla["bandas_db"][b] - perfil["bandas_db"][b], 1) for b in BANDAS_HZ
    }
    delta_lufs = (round(lufs_mix - perfil["lufs"], 1)
                  if perfil["lufs"] is not None and np.isfinite(lufs_mix) else None)

    return {
        "referencia": ", ".join(perfil["nombres"]),
        "n_referencias": len(perfil["nombres"]),
        "lufs_referencia": perfil["lufs"],
        "delta_bandas_db": delta_bandas,
        "delta_lufs": delta_lufs,
    }


# ------------------------------------------------------- alertas inteligentes

def generar_alertas(diag: dict, umbrales: dict | None = None) -> list[str]:
    """Reglas automáticas con umbrales del género activo (data-driven).

    `umbrales` viene del preset de género (config/generos/<nombre>.json);
    si es None se usan los defaults (equivalentes a math rock).
    """
    from .profiles import UMBRALES_DEFAULT
    u = dict(UMBRALES_DEFAULT)
    if umbrales:
        u.update(umbrales)

    alertas = []
    g = diag["global"]
    bandas = diag["bandas_db"]
    estereo = diag["estereo"]
    vs_ref = diag.get("vs_referencia") or {}

    # Low-mid elevado sobre la referencia
    delta = vs_ref.get("delta_bandas_db") or {}
    if delta.get("low_mid") is not None and delta["low_mid"] >= u["low_mid_delta_max_db"]:
        alertas.append(
            f"Low-mid elevado (+{delta['low_mid']:.1f} dB vs referencia) — {u['nota_low_mid']}"
        )

    # Crest factor bajo → dinámica comprimida
    if g["crest_factor_db"] < u["crest_min_db"]:
        alertas.append(
            f"Crest factor {g['crest_factor_db']:.1f} dB (<{u['crest_min_db']:g}) — {u['nota_crest']}"
        )

    # Sub-graves muy bajos para el género
    if bandas["sub"] < u["sub_min_db"]:
        alertas.append(
            f"Sub-graves en {bandas['sub']:.1f} dB (<{u['sub_min_db']:g}) — {u['nota_sub']}"
        )

    # Correlación estéreo inestable en mid / high-mid
    corr = estereo.get("correlacion_por_banda", {})
    for banda in ("mid", "high_mid"):
        c = corr.get(banda)
        if c is not None and c < u["correlacion_min"]:
            alertas.append(
                f"Correlación estéreo {c:.2f} en {banda} (<{u['correlacion_min']:g}) — {u['nota_correlacion']}"
            )

    # Loudness excesivo para el género
    if np.isfinite(g["lufs_i"]) and g["lufs_i"] > u["lufs_max"]:
        alertas.append(
            f"LUFS integrado {g['lufs_i']:.1f} (>{u['lufs_max']:g}) — {u['nota_lufs']}"
        )

    # Clipping global
    if diag.get("clipping_global"):
        alertas.append("Clipping detectado — hay muestras consecutivas en el techo digital")

    # True peak por encima de -1 dBTP (seguridad streaming)
    if g["true_peak_db"] > -1.0:
        alertas.append(
            f"True peak {g['true_peak_db']:.1f} dBTP (>-1.0) — riesgo de distorsión en códecs de streaming"
        )

    # Compatibilidad mono
    if estereo.get("perdida_mono_db", 0) > 3.0:
        alertas.append(
            f"Pérdida de {estereo['perdida_mono_db']:.1f} dB al sumar a mono — revisar anchura estéreo falsa"
        )

    return alertas


# ------------------------------------------------------------------ pipeline

def analizar_wav(path_wav: Path, marcadores_txt: str = "",
                 path_referencia: Path | None = None,
                 version: str = "V01",
                 umbrales: dict | None = None,
                 progreso=None) -> dict:
    """Pipeline completo de análisis. Devuelve el diagnóstico como dict.

    `progreso` es un callable opcional (str) para reportar avance a la UI.
    """
    def avisar(msg: str):
        log.info(msg)
        if progreso:
            progreso(msg)

    path_wav = Path(path_wav)
    avisar(f"Cargando {path_wav.name}…")
    audio, sr = cargar_wav(path_wav)
    duracion = audio.shape[0] / sr

    avisar("Midiendo loudness (LUFS)…")
    lufs_i = lufs_integrado(audio, sr)
    _, st_vals = lufs_short_term(audio, sr)
    lufs_s_max = max(st_vals) if st_vals else lufs_i

    avisar("Midiendo true peak y dinámica…")
    tp = true_peak_db(audio, sr)
    crest = crest_factor_db(audio)
    clip = detectar_clipping(audio)

    avisar("Analizando balance espectral…")
    bandas = balance_bandas_db(audio, sr)

    avisar("Analizando imagen estéreo…")
    estereo = analisis_estereo(audio, sr)

    secciones = []
    if marcadores_txt.strip():
        avisar("Analizando secciones…")
        marcas = parse_marcadores(marcadores_txt, duracion)
        secciones = analizar_secciones(audio, sr, marcas)

    diag = {
        "archivo": path_wav.name,
        "fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "version": version,
        "duracion_s": round(duracion, 1),
        "sample_rate": sr,
        "global": {
            "lufs_i": round(float(lufs_i), 1) if np.isfinite(lufs_i) else None,
            "lufs_s": round(float(lufs_s_max), 1) if np.isfinite(lufs_s_max) else None,
            "true_peak_db": round(tp, 1),
            "lra": round(lra(st_vals), 1),
            "crest_factor_db": round(crest, 1),
        },
        "clipping_global": clip,
        "bandas_db": bandas,
        "estereo": {
            "correlacion_global": estereo["correlacion_global"],
            "correlacion_por_banda": estereo["correlacion_por_banda"],
            "ancho_por_banda": estereo["ancho_por_banda"],
            "perdida_mono_db": estereo["perdida_mono_db"],
        },
        "secciones": secciones,
        "vs_referencia": None,
        "alertas": [],
    }

    if path_referencia:
        refs = path_referencia if isinstance(path_referencia, list) else [path_referencia]
        avisar(f"Comparando contra {len(refs)} referencia(s) (niveladas en loudness)…")
        try:
            diag["vs_referencia"] = comparar_referencia(diag, refs)
        except Exception:
            log.exception("Fallo al comparar con la referencia")
            diag["vs_referencia"] = {"error": "No se pudo analizar la referencia (ver app.log)"}

    avisar("Generando alertas…")
    diag["alertas"] = generar_alertas(diag, umbrales)

    avisar("Análisis completado.")
    return diag
