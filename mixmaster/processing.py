"""Masterizado automático (v0.3.1): mezcla o stems → master competitivo.

Cadena: EQ correctivo de 7 bandas hacia la referencia (acotado, orientativo)
→ ajuste de imagen estéreo por banda (M/S, acotado) → densidad opcional
(soft-clip suave si hay que empujar mucho el loudness) → normalización al
target → limitador true-peak → export WAV 24-bit a 06_masters/ y MP3 a
07_entregables/.

Todo es configurable en config/master.json (editable, no hardcodeado).
Filosofía del perfil: la referencia orienta, nunca se clona.
"""

import json
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy import signal

from .app_paths import CONFIG_DIR
from .audio_analysis import (
    BANDAS_HZ, analisis_estereo, balance_bandas_db, cargar_audio, crest_factor_db,
    db, espectro_suavizado, lufs_integrado, perfil_referencias, true_peak_db,
)
from .logger import get_logger

log = get_logger("mixmaster.processing")

MASTER_CONFIG_FILE = CONFIG_DIR / "master.json"

CONFIG_MASTER_DEFAULT = {
    "target_lufs_default": -8.5,
    "eq_correctivo": {
        "activo": True,
        "modo": "fino",              # "fino" = curva 1/3 octava · "bandas" = 7 bloques
        "max_correccion_db": 4.0,
        "analizar_imagen_stereo": True,
        "max_ajuste_ancho_db": 2.0,
    },
    "clipper": {
        # recorta solo los picos (transitorios de batería) antes del limitador:
        # así el limitador trabaja poco y el master no suena "a tope"
        "activo": True,
        "umbral_dbfs": -0.5,
    },
    "densidad": {
        "activo": True,
        # si el limitador tendría que recortar más de esto, se añade
        # saturación suave antes para ganar densidad sin bombeo
        "umbral_reduccion_db": 3.0,
        "drive": 1.5,
    },
    "limitador": {
        "ceiling_dbtp": -1.0,
        "release_ms": 50,
        "lookahead_ms": 5,
    },
}

FIR_TAPS = 4097            # filtro de fase lineal para el EQ de matching
FORMATOS_STEM = (".wav", ".flac", ".aiff", ".aif")

# Compatibilidad con la UI/tests previos (modo destino único competitivo)
DESTINOS = {
    "Master único competitivo — -8.5 LUFS": -8.5,
}


def cargar_config_master() -> dict:
    """Lee config/master.json; lo crea con defaults si no existe."""
    if not MASTER_CONFIG_FILE.exists():
        try:
            MASTER_CONFIG_FILE.write_text(
                json.dumps(CONFIG_MASTER_DEFAULT, indent=2, ensure_ascii=False),
                encoding="utf-8")
            log.info("Config de master creada: %s", MASTER_CONFIG_FILE)
        except Exception:
            log.exception("No se pudo crear master.json; se usan defaults")
        return json.loads(json.dumps(CONFIG_MASTER_DEFAULT))
    try:
        cfg = json.loads(MASTER_CONFIG_FILE.read_text(encoding="utf-8"))
        base = json.loads(json.dumps(CONFIG_MASTER_DEFAULT))
        for k, v in cfg.items():
            if isinstance(v, dict) and isinstance(base.get(k), dict):
                base[k].update(v)
            else:
                base[k] = v
        return base
    except Exception:
        log.exception("master.json ilegible; se usan defaults")
        return json.loads(json.dumps(CONFIG_MASTER_DEFAULT))


# ------------------------------------------------------------ stems → mezcla

def sumar_stems(carpeta: Path) -> tuple[np.ndarray, int]:
    """Suma todos los stems de una carpeta en una mezcla virtual estéreo.

    Alinea longitudes al stem más largo y deja headroom (pico a -6 dBFS)
    antes del master. Lanza excepción si no hay stems.
    """
    archivos = sorted(p for p in Path(carpeta).iterdir()
                      if p.is_file() and p.suffix.lower() in FORMATOS_STEM)
    if not archivos:
        raise FileNotFoundError(f"No hay stems en {carpeta}")

    pistas, srs = [], []
    for p in archivos:
        audio, sr = cargar_audio(p)
        if audio.shape[1] == 1:
            audio = np.repeat(audio, 2, axis=1)
        pistas.append(audio)
        srs.append(sr)
    if len(set(srs)) > 1:
        raise ValueError(f"Los stems tienen sample rates distintos: {sorted(set(srs))}")

    n = max(p.shape[0] for p in pistas)
    mezcla = np.zeros((n, 2))
    for p in pistas:
        mezcla[: p.shape[0]] += p

    pico = float(np.max(np.abs(mezcla)))
    if pico > 1e-9:
        mezcla *= (10 ** (-6.0 / 20)) / pico  # headroom -6 dBFS para el master
    log.info("Mezcla virtual: %d stems sumados desde %s", len(pistas), carpeta)
    return mezcla, srs[0]


# ------------------------------------------------------------------ EQ match

def _curva_fir(gan_db_por_banda: dict[str, float], sr: int) -> np.ndarray:
    """FIR de fase lineal con la ganancia indicada (dB) en cada banda."""
    centros, ganancias = [0.0], [None]
    for banda, (f_lo, f_hi) in BANDAS_HZ.items():
        centros.append(float(np.sqrt(f_lo * f_hi)))
        ganancias.append(10 ** (gan_db_por_banda.get(banda, 0.0) / 20))
    ganancias[0] = ganancias[1]  # DC = banda sub

    nyq = sr / 2
    freqs = [c / nyq for c in centros] + [1.0]
    gains = ganancias + [ganancias[-1]]  # Nyquist = banda air
    freqs = np.clip(freqs, 0.0, 1.0)
    freqs, idx = np.unique(freqs, return_index=True)
    gains = np.array(gains)[idx]
    return signal.firwin2(FIR_TAPS, freqs, gains)


def _aplicar_fir(audio: np.ndarray, fir: np.ndarray) -> np.ndarray:
    """Aplica el FIR a cada canal compensando el retardo de grupo."""
    demora = len(fir) // 2
    out = np.empty_like(audio)
    for ch in range(audio.shape[1]):
        conv = signal.fftconvolve(audio[:, ch], fir, mode="full")
        out[:, ch] = conv[demora:demora + audio.shape[0]]
    return out


def _ajustar_imagen(audio: np.ndarray, sr: int, ancho_mix: dict, ancho_ref: dict,
                    max_db: float) -> tuple[np.ndarray, dict]:
    """Acerca el ancho estéreo por banda al de la referencia (M/S, acotado).

    Solo actúa donde la diferencia es notable (>0.10). En sub/low únicamente
    estrecha (nunca ensancha graves: compatibilidad mono). Devuelve el audio
    ajustado y el mapa de ganancias de side aplicadas (dB).
    """
    ajustes = {}
    for banda in BANDAS_HZ:
        delta = ancho_ref.get(banda, 0) - ancho_mix.get(banda, 0)
        if abs(delta) <= 0.10:
            continue
        # delta de ancho → dB de side: escala suave (0.10 de ancho ≈ 1 dB)
        g = float(np.clip(delta * 10.0, -max_db, max_db))
        if banda in ("sub", "low") and g > 0:
            continue  # nunca ensanchar graves
        ajustes[banda] = round(g, 1)

    if not ajustes:
        return audio, {}

    mid = (audio[:, 0] + audio[:, 1]) / 2
    side = (audio[:, 0] - audio[:, 1]) / 2
    fir = _curva_fir(ajustes, sr)
    demora = len(fir) // 2
    conv = signal.fftconvolve(side, fir, mode="full")
    side = conv[demora:demora + audio.shape[0]]
    return np.stack([mid + side, mid - side], axis=1), ajustes


def _curva_fir_fina(freqs: np.ndarray, gan_db: np.ndarray, sr: int) -> np.ndarray:
    """FIR de fase lineal desde una curva fina de ganancias (1/3 de octava)."""
    nyq = sr / 2
    f = np.concatenate(([0.0], freqs / nyq, [1.0]))
    g_lin = 10 ** (np.concatenate(([gan_db[0]], gan_db, [gan_db[-1]])) / 20)
    f = np.clip(f, 0.0, 1.0)
    f, idx = np.unique(f, return_index=True)
    return signal.firwin2(FIR_TAPS, f, g_lin[idx])


def _clipper(audio: np.ndarray, umbral_dbfs: float) -> np.ndarray:
    """Clipper con codo suave: recorta solo lo que pasa el umbral.

    Los transitorios de milisegundos (picos de batería) se recortan de forma
    inaudible; el resto de la señal pasa intacto → el limitador posterior
    trabaja mucho menos y no bombea.
    """
    t = 10 ** (umbral_dbfs / 20)
    x = audio.copy()
    exceso = np.abs(x) > t
    if exceso.any():
        # por encima del umbral: compresión tanh hacia el techo (codo suave)
        x[exceso] = np.sign(x[exceso]) * (
            t + (1.0 - t) * np.tanh((np.abs(x[exceso]) - t) / (1.0 - t))
        )
    return x


def _score_ab(audio: np.ndarray, sr: int, perfil: dict) -> dict:
    """Similitud del master vs el perfil de referencias (0–100 por aspecto).

    - tonal: distancia media de la curva espectral (solo forma, sin nivel)
    - dinamica: diferencia de crest factor
    - imagen: distancia media del ancho estéreo por banda
    """
    _, esp_master = espectro_suavizado(audio, sr)
    esp_ref = np.asarray(perfil["espectro_db"])
    forma_master = esp_master - esp_master.mean()
    forma_ref = esp_ref - esp_ref.mean()
    mad_tonal = float(np.mean(np.abs(forma_master - forma_ref)))
    tonal = max(0.0, 100.0 - 10.0 * mad_tonal)

    crest_diff = abs(crest_factor_db(audio) - perfil["crest_db"])
    dinamica = max(0.0, 100.0 - 8.0 * crest_diff)

    ancho_master = analisis_estereo(audio, sr)["ancho_por_banda"]
    mad_ancho = float(np.mean([abs(ancho_master[b] - perfil["ancho_por_banda"][b])
                               for b in BANDAS_HZ]))
    imagen = max(0.0, 100.0 - 250.0 * mad_ancho)

    return {
        "tonal": round(tonal),
        "dinamica": round(dinamica),
        "imagen": round(imagen),
        "global": round(0.5 * tonal + 0.25 * dinamica + 0.25 * imagen),
    }


def _soft_clip(audio: np.ndarray, drive: float) -> np.ndarray:
    """Saturación suave (tanh) para ganar densidad antes del limitador."""
    return np.tanh(audio * drive) / np.tanh(drive)


def _limitador(audio: np.ndarray, sr: int, cfg_lim: dict) -> np.ndarray:
    """Limitador con lookahead sobre envolvente de TRUE peak (inter-sample)."""
    ceiling_db = float(cfg_lim.get("ceiling_dbtp", -1.0))
    ceiling = 10 ** (ceiling_db / 20)
    objetivo = ceiling * 10 ** (-0.2 / 20)  # margen de seguridad

    n = audio.shape[0]
    up = signal.resample_poly(audio, 4, 1, axis=0)
    pico_up = np.max(np.abs(up), axis=1)
    pico = pico_up[: n * 4].reshape(n, 4).max(axis=1)

    ventana = max(int(cfg_lim.get("lookahead_ms", 5) / 1000 * sr), 1)
    from scipy.ndimage import maximum_filter1d
    env = maximum_filter1d(pico, size=ventana * 2 + 1)

    alpha = np.exp(-1.0 / (cfg_lim.get("release_ms", 50) / 1000 * sr))
    ganancia = np.ones_like(env)
    exceso = env > objetivo
    ganancia[exceso] = objetivo / env[exceso]
    suave = np.empty_like(ganancia)
    g = 1.0
    for i in range(len(ganancia)):
        g = min(ganancia[i], alpha * g + (1 - alpha) * ganancia[i])
        suave[i] = g
    out = audio * suave[:, np.newaxis]
    out = np.clip(out, -ceiling, ceiling)

    tp = true_peak_db(out, sr)
    if tp > ceiling_db:
        out = out * 10 ** ((ceiling_db - tp) / 20)
    return out


# ------------------------------------------------------------------ pipeline

def masterizar(path_mezcla: Path | None, path_referencia: Path | None,
               target_lufs: float, dir_masters: Path, dir_entregables: Path,
               version: str = "V01", carpeta_stems: Path | None = None,
               progreso=None) -> dict:
    """Pipeline de masterizado. Entrada: mezcla estéreo O carpeta de stems.

    Devuelve resumen con rutas, mediciones y qué corrección se aplicó.
    """
    def avisar(msg):
        log.info(msg)
        if progreso:
            progreso(msg)

    cfg = cargar_config_master()
    cfg_eq = cfg["eq_correctivo"]
    cfg_den = cfg["densidad"]
    cfg_lim = cfg["limitador"]

    if carpeta_stems:
        avisar("Sumando stems en mezcla virtual…")
        audio, sr = sumar_stems(Path(carpeta_stems))
        nombre_base = "stems"
    else:
        avisar("Cargando mezcla…")
        audio, sr = cargar_audio(Path(path_mezcla))
        nombre_base = Path(path_mezcla).stem
    if audio.shape[1] == 1:
        audio = np.repeat(audio, 2, axis=1)

    correccion, ajuste_ancho = {}, {}
    nombres_ref, perfil = [], None
    if path_referencia and cfg_eq.get("activo", True):
        refs = path_referencia if isinstance(path_referencia, list) else [path_referencia]
        avisar(f"Analizando {len(refs)} referencia(s) (niveladas, perfil promedio)…")
        l_mix = lufs_integrado(audio, sr)
        perfil = perfil_referencias(refs, l_mix)
        nombres_ref = perfil["nombres"]
        tope = float(cfg_eq.get("max_correccion_db", 4.0))

        if cfg_eq.get("modo", "fino") == "fino":
            # Matching espectral FINO: curva completa a 1/3 de octava
            avisar(f"Matching espectral fino (1/3 octava, máx ±{tope:g} dB)…")
            freqs, esp_mix = espectro_suavizado(audio, sr)
            esp_ref = np.asarray(perfil["espectro_db"])
            delta = esp_ref - esp_mix
            delta = delta - float(np.mean(delta))       # solo forma, no nivel
            delta = np.clip(delta, -tope, tope)
            delta = np.convolve(delta, [0.25, 0.5, 0.25], mode="same")  # suaviza
            audio = _aplicar_fir(audio, _curva_fir_fina(freqs, delta, sr))
            # resumen por banda para el reporte
            correccion = {}
            for b, (f_lo, f_hi) in BANDAS_HZ.items():
                sel = (freqs >= f_lo) & (freqs < f_hi)
                correccion[b] = round(float(delta[sel].mean()), 1) if sel.any() else 0.0
        else:
            # Modo clásico: EQ correctivo de 7 bandas
            bandas_mix = balance_bandas_db(audio, sr)
            correccion = {
                b: round(float(np.clip(perfil["bandas_db"][b] - bandas_mix[b], -tope, tope)), 1)
                for b in BANDAS_HZ
            }
            avisar(f"Aplicando EQ correctivo 7 bandas (máx ±{tope:g} dB)…")
            audio = _aplicar_fir(audio, _curva_fir(correccion, sr))

        # Imagen estéreo: acerca el ancho por banda al promedio de referencias
        if cfg_eq.get("analizar_imagen_stereo", True):
            avisar("Ajustando imagen estéreo por banda…")
            ancho_mix = analisis_estereo(audio, sr)["ancho_por_banda"]
            audio, ajuste_ancho = _ajustar_imagen(
                audio, sr, ancho_mix, perfil["ancho_por_banda"],
                float(cfg_eq.get("max_ajuste_ancho_db", 2.0)))

    # ¿Cuánto habrá que empujar? Si es mucho, densidad previa (soft-clip suave).
    # Drive PROPORCIONAL: empuje moderado → densidad casi transparente; solo los
    # empujes extremos usan el drive máximo. Antes era binario (siempre 1.5).
    densidad_aplicada = False
    lufs_actual = lufs_integrado(audio, sr)
    if np.isfinite(lufs_actual):
        empuje = target_lufs - lufs_actual
        tp_actual = true_peak_db(audio, sr)
        reduccion_estimada = max(0.0, (tp_actual + empuje) - cfg_lim["ceiling_dbtp"])
        umbral_den = float(cfg_den.get("umbral_reduccion_db", 3.0))
        if cfg_den.get("activo", True) and reduccion_estimada > umbral_den:
            drive_max = float(cfg_den.get("drive", 1.5))
            rango = float(cfg_den.get("rango_proporcional_db", 6.0))
            frac = min(1.0, (reduccion_estimada - umbral_den) / rango)
            drive = 1.1 + (drive_max - 1.1) * frac  # 1.1 (suave) → drive_max (extremo)
            avisar(f"Añadiendo densidad (drive {drive:.2f}, empuje {reduccion_estimada:.1f} dB)…")
            audio = _soft_clip(audio, drive)
            densidad_aplicada = True
            lufs_actual = lufs_integrado(audio, sr)

    # Loudness con convergencia: el limitador come nivel al empujar fuerte,
    # así que se itera (normalizar → clipper → limitar → medir) hasta el target.
    # El clipper recorta solo picos → el limitador trabaja poco → sin bombeo.
    cfg_clip = cfg.get("clipper", {})
    avisar(f"Normalizando a {target_lufs} LUFS (con convergencia)…")
    for intento in range(4):
        lufs_actual = lufs_integrado(audio, sr)
        if not np.isfinite(lufs_actual):
            break
        diff = target_lufs - lufs_actual
        if abs(diff) <= 0.3:
            break
        audio = audio * 10 ** (diff / 20)
        if cfg_clip.get("activo", True):
            audio = _clipper(audio, float(cfg_clip.get("umbral_dbfs", -0.5)))
        avisar(f"Limitando picos (techo {cfg_lim['ceiling_dbtp']:g} dBTP, pasada {intento + 1})…")
        audio = _limitador(audio, sr, cfg_lim)

    lufs_final = lufs_integrado(audio, sr)
    tp_final = true_peak_db(audio, sr)
    crest_final = crest_factor_db(audio)

    score = None
    if perfil is not None:
        avisar("Calculando score de similitud vs referencias…")
        try:
            score = _score_ab(audio, sr, perfil)
        except Exception:
            log.exception("No se pudo calcular el score A/B")

    dir_masters.mkdir(parents=True, exist_ok=True)
    dir_entregables.mkdir(parents=True, exist_ok=True)
    out_wav = dir_masters / f"master_{version.lower()}_{nombre_base}.wav"
    out_mp3 = dir_entregables / f"master_{version.lower()}_{nombre_base}.mp3"

    avisar("Exportando WAV 24-bit y MP3…")
    sf.write(str(out_wav), audio, sr, subtype="PCM_24")
    sf.write(str(out_mp3), audio, sr)

    resumen = {
        "wav": str(out_wav),
        "mp3": str(out_mp3),
        "lufs_final": round(float(lufs_final), 1),
        "true_peak_final": round(tp_final, 1),
        "crest_final": round(crest_final, 1),
        "target_lufs": target_lufs,
        "eq_aplicado_db": correccion,
        "ajuste_ancho_db": ajuste_ancho,
        "densidad_aplicada": densidad_aplicada,
        "fuente": "stems" if carpeta_stems else "mezcla",
        "referencias": nombres_ref,
        "score": score,
    }
    avisar("Master listo.")
    log.info("Master: %s", resumen)
    return resumen
