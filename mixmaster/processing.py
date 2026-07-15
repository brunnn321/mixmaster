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
    BANDAS_HZ, CRUCES_HZ, analisis_estereo, balance_bandas_db, cargar_audio,
    crest_factor_db, crest_por_banda, db, detectar_resonancias, espectro_suavizado,
    lufs_integrado, perfil_referencias, true_peak_db,
)
from .logger import get_logger

log = get_logger("mixmaster.processing")

MASTER_CONFIG_FILE = CONFIG_DIR / "master.json"

CONFIG_MASTER_DEFAULT = {
    "target_lufs_default": -9.0,
    "eq_correctivo": {
        "activo": True,
        "modo": "fino",              # "fino" = curva 1/3 octava · "bandas" = 7 bloques
        "max_correccion_db": 4.0,
        "analizar_imagen_stereo": True,
        "max_ajuste_ancho_db": 1.0,
    },
    "mono_bass": {
        # colapsa a mono el grave por debajo de freq_hz (punch + compatibilidad
        # vinilo/clubs/mono). cantidad 0..1 = cuánto mono-izar (1 = todo)
        "activo": True,
        "freq_hz": 100.0,
        "cantidad": 1.0,
    },
    "multibanda": {
        # compresión multibanda CONSERVADORA guiada por el crest-por-banda de
        # la referencia. Solo comprime bandas > umbral_crest_db más dinámicas
        # que la ref. cantidad 0..1 = intensidad global (0.6 = suave)
        "activo": True,
        "umbral_crest_db": 2.0,
        "reduccion_max_db": 3.0,
        "ratio_max": 2.5,
        "attack_ms": 15.0,
        "release_ms": 120.0,
        "cantidad": 0.6,
    },
    "resonancias": {
        # notch suave de picos estrechos anómalos (Q alto). umbral_db = cuánto
        # debe sobresalir del espectro suave; max_cut_db = corte máximo
        "activo": True,
        "umbral_db": 6.0,
        "max_cut_db": 3.0,
        "q": 6.0,
        "max_n": 4,
    },
    "transient_shaping": {
        # realza los ataques (pegada) antes del limitador. cantidad 0..1
        # (0.25 = suave). fast/slow_ms = envolventes de detección del ataque
        "activo": True,
        "cantidad": 0.25,
        "fast_ms": 5.0,
        "slow_ms": 80.0,
    },
    "dinamica_secciones": {
        # OPT-IN (default off): recupera el contorno dinámico macro (verso vs
        # estribillo) que el limitado aplana. cantidad 0..1, acotado a max_db
        "activo": False,
        "cantidad": 0.5,
        "ventana_s": 1.0,
        "max_db": 2.0,
    },
    "stems_master": {
        # v0.8.3: al masterizar desde stems, realza la pegada de los stems de
        # percusión/batería (por nombre) antes de sumar
        "mejorar_percusion": True,
        "transient_cantidad": 0.3,
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
        "rango_proporcional_db": 6.0,
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

# Claves de nombre para identificar stems de percusión (v0.8.3)
_PERC_CLAVES = ("kick", "bombo", "snare", "caja", "tom", "drum", "bater", "perc",
                "oh", "overhead", "cymbal", "crash", "ride", "hihat", "hat", "clap")


def _es_percusion(nombre: str) -> bool:
    """True si el nombre del stem sugiere percusión/batería."""
    n = nombre.lower()
    return any(k in n for k in _PERC_CLAVES)


def sumar_stems(carpeta: Path, mejorar_percusion: bool = True,
                transient_cant: float = 0.3) -> tuple[np.ndarray, int]:
    """Suma todos los stems de una carpeta en una mezcla virtual estéreo.

    Alinea longitudes al stem más largo y deja headroom (pico a -6 dBFS)
    antes del master. Lanza excepción si no hay stems.

    v0.8.3: si `mejorar_percusion`, aplica transient shaping suave a los stems
    de batería/percusión ANTES de sumar → más pegada en el master por stems.
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
        if mejorar_percusion and transient_cant > 0 and _es_percusion(p.name):
            audio = _transient_shape(audio, sr, transient_cant)
            log.info("Stem percusivo realzado (pegada): %s", p.name)
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


def _transient_shape(audio: np.ndarray, sr: int, cantidad: float,
                     fast_ms: float = 5.0, slow_ms: float = 80.0) -> np.ndarray:
    """Realza los ataques (transient shaping) — v0.8 · Tier 3.

    Dos envolventes (rápida vs lenta): donde la rápida supera a la lenta hay un
    ataque, y se aplica una ganancia extra acotada. Devuelve más pegada sin
    tocar el sostenido. La MISMA ganancia va a L y R (no rompe la imagen).
    Pensado para correr ANTES del limitador, que controla los picos nuevos.
    """
    if cantidad <= 0:
        return audio
    mono = np.max(np.abs(audio), axis=1)
    a_f = float(np.exp(-1.0 / max(fast_ms / 1000 * sr, 1.0)))
    a_s = float(np.exp(-1.0 / max(slow_ms / 1000 * sr, 1.0)))
    # envolventes de FASE CERO (offline): la ganancia se alinea con el ataque
    # (un detector causal se desfasaría y realzaría la cola, no el golpe)
    env_fast = signal.filtfilt([1 - a_f], [1.0, -a_f], mono)
    env_slow = signal.filtfilt([1 - a_s], [1.0, -a_s], mono)
    # ataque = la envolvente rápida por encima de la lenta (solo positivo)
    ratio = np.clip((env_fast - env_slow) / (env_slow + 1e-6), 0.0, 1.0)
    ganancia = 1.0 + cantidad * ratio           # máx 1 + cantidad
    return audio * ganancia[:, np.newaxis]


def _preservar_dinamica_macro(audio: np.ndarray, contorno_ref: np.ndarray, sr: int,
                              cantidad: float, win_s: float = 1.0,
                              max_db: float = 2.0) -> np.ndarray:
    """Recupera el contorno dinámico macro (secciones) — v0.8 · Tier 3.

    Compara la envolvente de largo plazo (~win_s) del audio actual contra la de
    `contorno_ref` (la señal ANTES de densidad/limitado, más dinámica) y acerca
    la actual a ese contorno, de forma acotada (±max_db). Recupera el «verso más
    bajo que el estribillo» que el limitado tiende a aplanar. Ganancia lenta.
    """
    if cantidad <= 0:
        return audio
    from scipy.ndimage import uniform_filter1d
    win = max(int(win_s * sr), 1)

    def contorno(x):
        m = x.mean(axis=1)
        env = np.sqrt(uniform_filter1d(m * m, win) + 1e-12)
        return env / (env.mean() + 1e-12)   # solo forma, no nivel

    e_cur = contorno(audio)
    e_ref = contorno(contorno_ref)
    gan_db = np.clip(cantidad * 20.0 * np.log10(e_ref / (e_cur + 1e-12)),
                     -max_db, max_db)
    return audio * (10 ** (gan_db / 20.0))[:, np.newaxis]


def _mono_bass(audio: np.ndarray, sr: int, freq_hz: float, cantidad: float = 1.0) -> np.ndarray:
    """Colapsa a mono el grave por debajo de freq_hz (v0.7 · Tier 2).

    Crossover de FASE CERO (filtfilt): el low se separa con un lowpass de fase
    cero, así `high = audio - low` es el complemento exacto y la suma queda
    plana (sin artefactos de fase). El low se mono-iza y se recombina.

    `cantidad` 0..1 mezcla entre el low estéreo original y el mono (1 = todo mono).
    Beneficio: más punch y compatibilidad (vinilo, clubs, sistemas mono).
    """
    if audio.shape[1] < 2 or cantidad <= 0 or freq_hz <= 0:
        return audio
    sos = signal.butter(4, freq_hz, "low", fs=sr, output="sos")
    low = signal.sosfiltfilt(sos, audio, axis=0)     # banda baja, fase cero
    high = audio - low                                # complemento exacto
    low_mono = low.mean(axis=1, keepdims=True)        # a mono
    low_mix = (1.0 - cantidad) * low + cantidad * low_mono
    return high + low_mix


# ------------------------------------------ resonancias (v0.7.3 · notch suave)

def _peaking_biquad(f0: float, gain_db: float, q: float, sr: int):
    """Coeficientes (b, a) de un peaking EQ (RBJ) — para notches suaves."""
    A = 10 ** (gain_db / 40.0)
    w0 = 2 * np.pi * f0 / sr
    alpha = np.sin(w0) / (2 * q)
    cos_w0 = np.cos(w0)
    b = [1 + alpha * A, -2 * cos_w0, 1 - alpha * A]
    a = [1 + alpha / A, -2 * cos_w0, 1 - alpha / A]
    return np.array(b) / a[0], np.array(a) / a[0]


def _aplicar_notches(audio: np.ndarray, sr: int, resonancias: list,
                     max_cut_db: float, q: float) -> tuple[np.ndarray, list]:
    """Aplica notches suaves (fase cero) en las resonancias detectadas.

    El corte es proporcional al exceso, acotado a max_cut_db (nunca destruye).
    """
    out = audio
    aplicados = []
    for r in resonancias:
        corte = -min(float(r["exceso_db"]) * 0.6, max_cut_db)  # suave y acotado
        if corte > -0.5:
            continue
        b, a = _peaking_biquad(float(r["freq"]), corte, q, sr)
        out = signal.filtfilt(b, a, out, axis=0)
        aplicados.append({"freq": r["freq"], "corte_db": round(corte, 1)})
    return out, aplicados


# --------------------------------------------- multibanda (v0.7 · Tier 2)

def _split_bandas(audio: np.ndarray, sr: int) -> dict[str, np.ndarray]:
    """Divide el audio ESTÉREO en las 7 bandas (suma exacta, fase cero).

    Mismos cruces que `split_bandas_mono` del análisis → coherencia total entre
    la medición de crest y el procesado.
    """
    nombres = list(BANDAS_HZ.keys())
    bandas, resto = {}, audio
    for i, fc in enumerate(CRUCES_HZ):
        sos = signal.butter(4, min(fc, sr / 2 * 0.99), "low", fs=sr, output="sos")
        low = signal.sosfiltfilt(sos, resto, axis=0)
        bandas[nombres[i]] = low
        resto = resto - low
    bandas[nombres[-1]] = resto  # "air" = lo que queda por encima del último cruce
    return bandas


def _comprimir_banda(banda: np.ndarray, sr: int, ratio: float, umbral_db: float,
                     attack_ms: float, release_ms: float) -> np.ndarray:
    """Compresor de detección RMS suave para una banda estéreo (v0.7 · Tier 2).

    Detector RMS con envolvente one-pole (program-dependent, estilo mastering):
    controla la densidad MACRO y PRESERVA los transientes rápidos (no los caza),
    que es justo lo deseable en un máster. Ganancia enlazada L/R (no rompe imagen).
    """
    mono = np.max(np.abs(banda), axis=1)               # detector enlazado L/R
    tau = max((attack_ms + release_ms) / 2 / 1000 * sr, 1.0)
    alpha = float(np.exp(-1.0 / tau))
    # detector RMS de FASE CERO (filtfilt): en mastering offline equivale a
    # look-ahead perfecto → la envolvente se alinea con la señal y sí atenúa el
    # pico (un detector causal se desfasaría y no lo cazaría)
    power = signal.filtfilt([1 - alpha], [1.0, -alpha], mono ** 2)
    env_db = 10.0 * np.log10(np.maximum(power, 1e-12))  # 10·log10 de potencia = dB

    exceso = np.maximum(env_db - umbral_db, 0.0)        # dB sobre umbral
    gan_db = -exceso * (1.0 - 1.0 / ratio)              # reducción estática
    gan = 10 ** (gan_db / 20.0)
    return banda * gan[:, np.newaxis]


def _multibanda(audio: np.ndarray, sr: int, crest_ref: dict, cfg_mb: dict
                ) -> tuple[np.ndarray, dict]:
    """Compresión multibanda guiada por el crest-por-banda de la referencia.

    Solo comprime las bandas NOTABLEMENTE más dinámicas que la referencia
    (excess > umbral). Reducción acotada, ratio suave, makeup para conservar
    el RMS de la banda. Devuelve (audio, reduccion_db_por_banda).
    """
    umbral = float(cfg_mb.get("umbral_crest_db", 2.0))
    red_max = float(cfg_mb.get("reduccion_max_db", 3.0))
    ratio_max = float(cfg_mb.get("ratio_max", 2.5))
    attack = float(cfg_mb.get("attack_ms", 15.0))
    release = float(cfg_mb.get("release_ms", 120.0))
    cantidad = float(cfg_mb.get("cantidad", 0.6))

    bandas = _split_bandas(audio, sr)
    aplicado = {}
    salida = np.zeros_like(audio)
    for nombre, banda in bandas.items():
        pico = float(np.max(np.abs(banda)))
        rms = float(np.sqrt(np.mean(banda ** 2)))
        if pico <= 0 or rms <= 0:
            salida += banda
            continue
        crest_banda = db(pico) - db(rms)
        exceso = crest_banda - float(crest_ref.get(nombre, crest_banda))
        objetivo = min(max((exceso - umbral) * cantidad, 0.0), red_max)
        if objetivo < 0.1:
            salida += banda           # esta banda ya es tan densa como la ref
            continue
        # umbral y ratio para lograr ~objetivo dB de reducción en los picos
        umbral_db = db(rms) + 3.0
        headroom = db(pico) - umbral_db
        if headroom <= 0.5:
            salida += banda
            continue
        ratio = min(1.0 / max(1.0 - objetivo / headroom, 1e-3), ratio_max)
        comp = _comprimir_banda(banda, sr, ratio, umbral_db, attack, release)
        # makeup: conservar el RMS de la banda (no perder nivel)
        rms_post = float(np.sqrt(np.mean(comp ** 2)))
        if rms_post > 0:
            comp *= rms / rms_post
        salida += comp
        aplicado[nombre] = round(objetivo, 1)
    return salida, aplicado


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
               progreso=None, cfg: dict | None = None) -> dict:
    """Pipeline de masterizado. Entrada: mezcla estéreo O carpeta de stems.

    `cfg` opcional permite pasar una configuración a medida (A/B, tests);
    si no, se lee de config/master.json.

    Devuelve resumen con rutas, mediciones y qué corrección se aplicó.
    """
    def avisar(msg):
        log.info(msg)
        if progreso:
            progreso(msg)

    if cfg is None:
        cfg = cargar_config_master()
    cfg_eq = cfg["eq_correctivo"]
    cfg_den = cfg["densidad"]
    cfg_lim = cfg["limitador"]

    if carpeta_stems:
        avisar("Sumando stems en mezcla virtual…")
        cfg_sm = cfg.get("stems_master", {})
        audio, sr = sumar_stems(
            Path(carpeta_stems),
            mejorar_percusion=cfg_sm.get("mejorar_percusion", True),
            transient_cant=float(cfg_sm.get("transient_cantidad", 0.3)))
        nombre_base = "stems"
    else:
        avisar("Cargando mezcla…")
        audio, sr = cargar_audio(Path(path_mezcla))
        nombre_base = Path(path_mezcla).stem
    if audio.shape[1] == 1:
        audio = np.repeat(audio, 2, axis=1)

    # Resonancias (v0.7.3): notch suave de picos estrechos anómalos, temprano
    # (antes del matching tonal). Corte acotado, fase cero. Se reporta cuáles.
    resonancias_db = []
    cfg_res = cfg.get("resonancias", {})
    if cfg_res.get("activo", True):
        res = detectar_resonancias(
            audio, sr,
            umbral_db=float(cfg_res.get("umbral_db", 4.0)),
            max_n=int(cfg_res.get("max_n", 4)))
        if res:
            avisar(f"Resonancias detectadas: {[r['freq'] for r in res]} Hz")
            audio, resonancias_db = _aplicar_notches(
                audio, sr, res,
                float(cfg_res.get("max_cut_db", 3.0)),
                float(cfg_res.get("q", 6.0)))

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

    # Compresión multibanda (v0.7 · Tier 2): iguala la dinámica POR BANDA a la
    # referencia. CONSERVADORA: solo actúa donde la mezcla es más dinámica que
    # la ref (excess > umbral), con ratio suave y makeup. Requiere referencia.
    multibanda_db = {}
    cfg_multi = cfg.get("multibanda", {})
    if perfil is not None and cfg_multi.get("activo", True):
        avisar("Compresión multibanda guiada por la referencia…")
        audio, multibanda_db = _multibanda(
            audio, sr, perfil.get("crest_por_banda", {}), cfg_multi)
        if multibanda_db:
            avisar(f"Multibanda (dB de reducción por banda): {multibanda_db}")

    # Mono-bass (v0.7): colapsa el grave a mono → punch + compatibilidad.
    # Se aplica SIEMPRE (con o sin referencia), tras el EQ/imagen.
    cfg_mb = cfg.get("mono_bass", {})
    mono_bass_hz = None
    if cfg_mb.get("activo", True):
        mono_bass_hz = float(cfg_mb.get("freq_hz", 100.0))
        cant_mb = float(cfg_mb.get("cantidad", 1.0))
        avisar(f"Mono-bass < {mono_bass_hz:g} Hz (punch + compatibilidad)…")
        audio = _mono_bass(audio, sr, mono_bass_hz, cant_mb)

    # Transient shaping (v0.8): realza ataques → pegada. Antes del limitador,
    # que controla los picos nuevos. Suave por defecto.
    cfg_tr = cfg.get("transient_shaping", {})
    transient_cant = 0.0
    if cfg_tr.get("activo", True):
        transient_cant = float(cfg_tr.get("cantidad", 0.25))
        if transient_cant > 0:
            avisar(f"Transient shaping (pegada, cantidad {transient_cant:g})…")
            audio = _transient_shape(
                audio, sr, transient_cant,
                float(cfg_tr.get("fast_ms", 5.0)), float(cfg_tr.get("slow_ms", 80.0)))

    # Contorno dinámico ANTES de densidad/limitado (para preservar macro-dinámica)
    cfg_din = cfg.get("dinamica_secciones", {})
    dinamica_cant = float(cfg_din.get("cantidad", 0.0)) if cfg_din.get("activo", False) else 0.0
    contorno_pre = audio.copy() if dinamica_cant > 0 else None

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

    # Preservación de dinámica macro (v0.8, opt-in): recupera el contorno de
    # secciones y re-limita por seguridad (el nudge puede subir picos).
    dinamica_aplicada = False
    if contorno_pre is not None:
        avisar("Preservando dinámica macro (contorno de secciones)…")
        audio = _preservar_dinamica_macro(
            audio, contorno_pre, sr, dinamica_cant,
            float(cfg_din.get("ventana_s", 1.0)), float(cfg_din.get("max_db", 2.0)))
        audio = _limitador(audio, sr, cfg_lim)   # seguridad
        dinamica_aplicada = True

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
    # el nombre lleva el loudness objetivo (marca lo específico del master, ej. -7)
    base_nombre = f"master_{version.lower()}_{nombre_base}_{target_lufs:g}LUFS"
    out_wav = dir_masters / f"{base_nombre}.wav"
    out_mp3 = dir_entregables / f"{base_nombre}.mp3"

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
        "multibanda_db": multibanda_db,
        "resonancias_db": resonancias_db,
        "transient_shaping": round(transient_cant, 2) if transient_cant else None,
        "dinamica_macro": dinamica_aplicada,
        "densidad_aplicada": densidad_aplicada,
        "mono_bass_hz": mono_bass_hz,
        "fuente": "stems" if carpeta_stems else "mezcla",
        "referencias": nombres_ref,
        "score": score,
    }
    avisar("Master listo.")
    log.info("Master: %s", resumen)
    return resumen
