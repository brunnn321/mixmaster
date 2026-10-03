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
from .automezcla import aplicar_pan, clasificar_rol
from .stem_diagnostico import _cross_correlacion_maxima, _decimar_para_correlacion
from .audio_analysis import espectro_ms, tramos_fuertes
from .audio_analysis import (
    BANDAS_HZ, CRUCES_HZ, analisis_estereo, balance_bandas_db, cargar_audio,
    crest_factor_db, crest_por_banda, db, declip_ligero, detectar_resonancias,
    espectro_suavizado, lufs_integrado, perfil_referencias, rango_corto_db,
    rango_corto_por_banda, recortar_silencio_extremos,
    true_peak_db,
)
from .logger import get_logger
from .profiles import leer_arbol, leer_genero

log = get_logger("mixmaster.processing")

MASTER_CONFIG_FILE = CONFIG_DIR / "master.json"

CONFIG_MASTER_DEFAULT = {
    "target_lufs_default": -9.0,
    "eq_correctivo": {
        "activo": True,
        "modo": "ms",                # "ms" = mid/side sobre tramos fuertes · "fino" = curva 1/3 oct. en mono · "bandas" = 7 bloques
        # Subido de 4.0 a 6.0 (2026-08-30) con evidencia real, no a ciegas:
        # en config/aprendizaje.json, 5/22 masters votados por Bruno pegaban
        # exacto en el techo de ±4.0dB (tanto aprobados como rechazados) —
        # el algoritmo pedía más corrección de la que el tope dejaba aplicar.
        # Coincide con el pendiente #3 de la tanda real 2026-08-09: "el
        # matching tonal casi no se nota" en 3 temas. Pendiente confirmar de
        # oído en la próxima tanda real que 6.0 no se pase de rosca.
        "max_correccion_db": 6.0,
        # 0..1: cuánto de la corrección mid/side se aplica (prueba A/B del
        # mentor: 0.5 vs 1.0 a igual volumen)
        "intensidad": 1.0,
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
        # 2/10 (ítem 9): "rango" iguala cómo se mueve cada banda (p95−p50 en
        # 50 ms) contra la referencia; "crest" es el modo anterior
        "modo": "rango",
        "umbral_rango_db": 1.0,
        "ratio_max_rango": 4.0,
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
    # 2/10 (ítem 11): supresión dinámica de resonancias, estilo soothe. Corta
    # solo los picos que sobresalen del espectro suavizado y solo mientras
    # aparecen. Con "EQ solo en guitarras" actúa solo sobre las guitarras.
    "resonancias_dinamicas": {
        "activo": True,
        "f_lo": 1000.0,
        "f_hi": 10000.0,
        "selectividad_db": 6.0,   # cuánto debe sobresalir un pico para tocarlo
        "profundidad": 0.3,       # fracción del exceso que se corta
        "max_db": 3.0,
        "release_ms": 100.0,
    },
    # 2/10 (ítem 21): una mezcla casi mono se abre con un side sintético
    # (retardo + pasa-altos) que se cancela al sumar a mono
    "abrir_mono": {
        "activo": True,
        "correlacion_mono": 0.95,     # por encima de esto se considera mono
        "correlacion_objetivo": 0.7,
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
        # Activado por defecto (2026-08-31, pedido de Bruno — "no quiero
        # que la app se vuelva un limitador andante como Ozone/LANDR"):
        # recupera el contorno dinámico macro (verso vs estribillo) que el
        # limitado aplana. cantidad 0..1, acotado a max_db
        "activo": True,
        "cantidad": 0.5,
        "ventana_s": 1.0,
        "max_db": 2.0,
    },
    "stems_master": {
        # v0.8.3: al masterizar desde stems, realza la pegada de los stems de
        # percusión/batería (por nombre) antes de sumar
        "mejorar_percusion": True,
        "transient_cantidad": 0.3,
        # claves de nombre de los stems que reciben el EQ de master (matching y
        # notches). Vacío = toda la mezcla. Pedido de Bruno: solo guitarras.
        "eq_solo_en": [],
        # 30/9 (investigación de calidad, ítems 7 y 8): procesado por rol
        # antes de sumar; el rol sale del nombre (automezcla.clasificar_rol).
        "bus_bateria": True,     # compresión paralela + pegamento del bus
        "bajo_dividido": True,   # grave limpio y mono + medios saturados
        # 2/10 (ítems 3 y 6): fase/polaridad entre micrófonos de la misma
        # fuente, pasa-altos por rol y EQ espejo bajo/guitarras
        "alinear_fase": True,
        "filtros_por_rol": True,
        # 2/10 (ítems 5 y 19): cadena de voz y estribillos que levantan
        "cadena_voz": True,
        "estribillos": True,
        "desenmascarar": True,   # ítem 6 parte 2: la voz se abre paso en 1–4 kHz
        # ítem 2: separa la referencia (Demucs) y lleva batería/bajo/voz/resto
        # a su balance. Sin torch/demucs instalados se salta solo.
        "balance_referencia": True,
        # ítems 23 y 22: ganancia + EQ por grupo aprendidas contra la
        # referencia separada, y dinámica de cada grupo como en la referencia
        "consola_optimizada": True,
        "dinamica_grupos": True,
    },
    # 2/10 (ítem 24): EQ perceptual estilo Gullfoss. "recuperar" realza lo
    # que queda enmascarado por bandas vecinas; "domar" baja lo que domina.
    # Con "EQ solo en guitarras" actúa solo sobre las guitarras.
    "eq_perceptual": {
        "activo": True,
        "recuperar_db": 2.0,
        "domar_db": 2.0,
    },
    # 2/10 (ítem 13): pegamento 2:1 + saturación suave, después del EQ
    "bus_master": {
        "activo": True,
        "saturacion": "cinta",   # "cinta" (simétrica) o "valvula" (armónicos pares)
        "drive": 1.3,
    },
    "clipper": {
        # recorta solo los picos (transitorios de batería) antes del limitador:
        # así el limitador trabaja poco y el master no suena "a tope"
        "activo": True,
        "umbral_dbfs": -0.5,
        # 2/10 (ítem 10): recorta solo los golpes; lo sostenido va al limitador
        "solo_transitorios": True,
    },
    # 2/10 (investigación de calidad, ítem 16): armónicos del grave para que
    # se oiga en parlantes chicos (tono residual: el oído reconstruye la
    # fundamental a partir de sus armónicos). Solo en el centro (mid).
    "exciter_graves": {
        "activo": True,
        "banda_hz": [40.0, 100.0],
        "cantidad": 0.25,   # RMS de los armónicos / RMS de la banda (~ -12 dB)
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

F_MAX_MATCH_HZ = 16000.0  # techo del matching tonal (ver masterizar)
FIR_TAPS = 4097            # filtro de fase lineal para el EQ de matching
FORMATOS_STEM = (".wav", ".flac", ".aiff", ".aif")

# MP3 (MPEG-1/2/2.5) solo soporta estos sample rates.
SR_MP3_VALIDOS = (8000, 11025, 12000, 16000, 22050, 24000, 32000, 44100, 48000)

# Compatibilidad con la UI/tests previos (modo destino único competitivo)
DESTINOS = {
    "Master único competitivo — -8.5 LUFS": -8.5,
}


def _merge_cfg(base: dict, extra: dict) -> dict:
    """Mezcla `extra` sobre `base` un nivel de profundidad (dicts anidados)."""
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            base[k].update(v)
        else:
            base[k] = v
    return base


def cargar_config_master(genero: str | None = None) -> dict:
    """Config del pipeline: defaults -> config/master.json -> preset de género.

    El bloque `"master"` de `config/generos/<genero>.json` pisa los valores
    globales: cada género masteriza con sus propios parámetros (tope de
    matching, resonancias, mono-bass, transientes…), que es lo que distingue
    a un grunge de un math rock más allá de los umbrales de alerta.
    """
    if not MASTER_CONFIG_FILE.exists():
        try:
            MASTER_CONFIG_FILE.write_text(
                json.dumps(CONFIG_MASTER_DEFAULT, indent=2, ensure_ascii=False),
                encoding="utf-8")
            log.info("Config de master creada: %s", MASTER_CONFIG_FILE)
        except Exception:
            log.exception("No se pudo crear master.json; se usan defaults")
        return _aplicar_preset_genero(
            json.loads(json.dumps(CONFIG_MASTER_DEFAULT)), genero)
    try:
        cfg = json.loads(MASTER_CONFIG_FILE.read_text(encoding="utf-8"))
        base = _merge_cfg(json.loads(json.dumps(CONFIG_MASTER_DEFAULT)), cfg)
        return _aplicar_preset_genero(base, genero)
    except Exception:
        log.exception("master.json ilegible; se usan defaults")
        return _aplicar_preset_genero(
            json.loads(json.dumps(CONFIG_MASTER_DEFAULT)), genero)


def _aplicar_preset_genero(base: dict, genero: str | None) -> dict:
    """Aplica el master del género sobre la config base, en dos capas:

    1. el árbol de géneros (config/generos/arbol.json, exportado desde
       RED-NEURONAL): perfil de su familia de mastering + ajustes propios;
    2. el preset local (config/generos/<genero>.json), que gana si existe.
    """
    if not genero:
        return base

    del_arbol = (leer_arbol().get(genero) or {}).get("master") or {}
    if del_arbol:
        log.info("Master del árbol para '%s': %s", genero, list(del_arbol))
        base = _merge_cfg(base, json.loads(json.dumps(del_arbol)))  # sin tocar el cache

    try:
        _, preset = leer_genero(genero)
    except Exception:
        log.exception("No se pudo leer el género '%s'; se usa la config global", genero)
        return base
    overrides = preset.get("master") or {}
    if not isinstance(overrides, dict) or not overrides:
        log.info("Género '%s' sin bloque 'master': se usa la config global", genero)
        return base
    log.info("Config de master del género '%s': %s", genero, list(overrides))
    return _merge_cfg(base, overrides)


# ------------------------------------------------------------ stems → mezcla

# Claves de nombre para identificar stems de percusión (v0.8.3)
_PERC_CLAVES = ("kick", "bombo", "snare", "caja", "tom", "drum", "bater", "perc",
                "oh", "overhead", "cymbal", "crash", "ride", "hihat", "hat", "clap")


def _es_percusion(nombre: str) -> bool:
    """True si el nombre del stem sugiere percusión/batería."""
    n = nombre.lower()
    return any(k in n for k in _PERC_CLAVES)


# Roles (automezcla.clasificar_rol) que van al bus de batería
_ROLES_BATERIA = ("kick", "snare", "toms", "hats", "overhead", "room")


def _rms(audio: np.ndarray) -> float:
    return float(np.sqrt(np.mean(audio ** 2)))


def _compresor_bus(audio: np.ndarray, sr: int, ratio: float, attack_ms: float,
                   release_ms: float, percentil: float = 90.0, margen_db: float = 3.0,
                   knee_db: float = 6.0) -> tuple[np.ndarray, float]:
    """Compresor con ataque y release separados, para buses de mezcla.

    A diferencia de `_comprimir_banda` (detector de fase cero, pensado para el
    master), este es causal: con ataque de 10-30 ms deja pasar el transitorio
    y comprime lo que viene después, que es lo que se busca en un bus.
    Suavizado de la reducción en dB con ataque/release por rama (Giannoulis,
    Massberg & Reiss, JAES 2012). La reducción se calcula en bloques de 32
    muestras (<1 ms) y se interpola: mismo resultado audible, 32 veces menos
    iteraciones de Python.

    El umbral es automático: `percentil` de los picos de la parte con señal,
    menos `margen_db`. Devuelve (audio, reducción media en dB mientras suena).
    """
    bloque = 32
    mono = np.max(np.abs(audio), axis=1)
    n_b = -(-len(mono) // bloque)
    picos = np.pad(mono, (0, n_b * bloque - len(mono))).reshape(n_b, bloque).max(axis=1)
    det_db = 20 * np.log10(np.maximum(picos, 1e-9))
    activos = det_db > det_db.max() - 40
    if not activos.any():
        return audio, 0.0
    umbral_db = float(np.percentile(det_db[activos], percentil)) - margen_db

    exceso = det_db - umbral_db
    pend = 1.0 / ratio - 1.0
    red = np.where(2 * exceso < -knee_db, 0.0,
                   np.where(2 * np.abs(exceso) <= knee_db,
                            pend * (exceso + knee_db / 2) ** 2 / (2 * knee_db),
                            pend * exceso))
    fs_b = sr / bloque
    a_at = float(np.exp(-1.0 / max(attack_ms / 1000 * fs_b, 1e-3)))
    a_re = float(np.exp(-1.0 / max(release_ms / 1000 * fs_b, 1e-3)))
    suave = np.empty_like(red)
    g = 0.0
    for i, x in enumerate(red):
        a = a_at if x < g else a_re
        g = a * g + (1 - a) * x
        suave[i] = g
    gan_db = np.interp(np.arange(len(mono)), np.arange(n_b) * bloque + bloque / 2, suave)
    return audio * (10 ** (gan_db / 20))[:, np.newaxis], float(-suave[activos].mean())


def _bus_bateria(bus: np.ndarray, sr: int, paralela: float = 0.35) -> tuple[np.ndarray, dict]:
    """Bus de batería: compresión paralela ("New York") + pegamento suave.

    1. Copia aplastada (10:1, ataque 1 ms): suma cuerpo y sustain.
    2. Se mezcla por debajo de la original (`paralela`, ~ -9 dB): el golpe
       queda intacto porque la original no se toca.
    3. Pegamento 3:1 con ataque 20 ms sobre la suma: une los tambores sin
       comerse el ataque.
    4. Vuelve al RMS de entrada: cambia la densidad, no el balance del plan.
    """
    rms_in = _rms(bus)
    if rms_in < 1e-9:
        return bus, {"reduccion_paralela_db": 0.0, "reduccion_pegamento_db": 0.0}
    aplastada, red_par = _compresor_bus(bus, sr, ratio=10.0, attack_ms=1.0,
                                        release_ms=80.0, percentil=50.0, margen_db=0.0)
    aplastada *= rms_in / max(_rms(aplastada), 1e-12)
    suma = bus + paralela * aplastada
    pegado, red_peg = _compresor_bus(suma, sr, ratio=3.0, attack_ms=20.0,
                                     release_ms=150.0, percentil=90.0, margen_db=3.0)
    pegado *= rms_in / max(_rms(pegado), 1e-12)
    return pegado, {"reduccion_paralela_db": round(red_par, 1),
                    "reduccion_pegamento_db": round(red_peg, 1)}


def _saturar_2x(x: np.ndarray, drive: float) -> np.ndarray:
    """Saturación tanh con sobremuestreo 2x (menos aliasing). `x` 1-D,
    normalizado internamente a pico 1 para que el drive no dependa del nivel
    de grabación del stem."""
    pico = float(np.max(np.abs(x)))
    if pico < 1e-9:
        return x
    up = signal.resample_poly(x / pico, 2, 1)
    sat = np.tanh(up * drive) / np.tanh(drive)
    return signal.resample_poly(sat, 1, 2)[: len(x)] * pico


def _bajo_dividido(audio: np.ndarray, sr: int, corte_hz: float = 200.0,
                   drive: float = 3.0, mezcla_sat: float = 0.6) -> np.ndarray:
    """Bajo dividido, práctica del metal moderno: el grave limpio, mono y
    parejo; los medios saturados para que el bajo se oiga en parlantes chicos.

    Crossover Linkwitz-Riley de 4º orden (dos Butterworth de 2º en cascada):
    las dos bandas quedan en fase y suman plano en amplitud. El camino
    saturado se filtra a 6 kHz antes y después (como una caja de
    amplificador): sin agudos altos la saturación a 2x no genera aliasing
    audible. Vuelve al RMS de entrada, así el nivel del plan no cambia.
    """
    sos_lp = signal.butter(2, corte_hz, "lowpass", fs=sr, output="sos")
    sos_hp = signal.butter(2, corte_hz, "highpass", fs=sr, output="sos")
    sos_caja = signal.butter(4, min(6000.0, sr * 0.45), "lowpass", fs=sr, output="sos")

    grave = signal.sosfilt(sos_lp, signal.sosfilt(sos_lp, audio, axis=0), axis=0)
    medios = signal.sosfilt(sos_hp, signal.sosfilt(sos_hp, audio, axis=0), axis=0)

    grave = np.repeat(grave.mean(axis=1, keepdims=True), 2, axis=1)
    grave, _ = _compresor_bus(grave, sr, ratio=4.0, attack_ms=10.0, release_ms=120.0,
                              percentil=50.0, margen_db=0.0)

    canales = [0] if np.allclose(medios[:, 0], medios[:, 1]) else [0, 1]
    sat = np.empty_like(medios)
    for c in canales:
        filtrado = signal.sosfilt(sos_caja, medios[:, c])
        sat[:, c] = signal.sosfilt(sos_caja, _saturar_2x(filtrado, drive))
    if canales == [0]:
        sat[:, 1] = sat[:, 0]
    sat *= _rms(medios) / max(_rms(sat), 1e-12)
    medios = (1 - mezcla_sat) * medios + mezcla_sat * sat

    salida = grave + medios
    return salida * (_rms(audio) / max(_rms(salida), 1e-12))


def _desplazar(audio: np.ndarray, muestras: float) -> np.ndarray:
    """Desplaza en el tiempo con precisión sub-muestra (positivo = retrasa,
    negativo = adelanta; offline se puede adelantar). Parte entera por
    corrimiento con ceros; parte fraccional con un sinc enventanado de 33
    coeficientes (fase lineal, centrado: no agrega retardo propio)."""
    entero = int(np.floor(muestras))
    frac = muestras - entero
    out = np.zeros_like(audio)
    if entero >= 0:
        out[entero:] = audio[: len(audio) - entero]
    else:
        out[: len(audio) + entero] = audio[-entero:]
    if frac > 1e-3:
        k = np.arange(-16, 17)
        h = np.sinc(k - frac) * np.hanning(35)[1:-1]
        h /= h.sum()
        out = signal.lfilter(h, [1.0], np.concatenate([out, np.zeros((16, out.shape[1]))]),
                             axis=0)[16:]
    return out


# Familias que pueden compartir fuente por bleed: los micrófonos de batería
# entre sí, y dentro de cada rol (bajo DI + amplificador, guitarra DI + mic)
_ANCLA_BATERIA = ("snare", "kick", "overhead")


def _alinear_fase(pistas: list, roles: list, nombres: list, sr: int,
                  umbral: float = 0.6, max_lag_ms: float = 30.0) -> list[str]:
    """Corrige polaridad y tiempo entre micrófonos de la MISMA fuente
    (ítem 3). Modifica `pistas` en el lugar y devuelve lo que hizo.

    Por familia (batería, o cada rol) se elige un ancla (caja, si no bombo,
    si no overhead; fuera de batería, el stem con más nivel). Cada miembro
    se correlaciona con el ancla (GCC acotado a `max_lag_ms`, señal
    decimada); si |correlación| ≥ `umbral` es la misma fuente: se invierte
    si la correlación es negativa y se lleva al tiempo del ancla. El retardo
    grueso se afina a la frecuencia completa con interpolación parabólica
    sobre los 10 s más fuertes del ancla. Lo que no correlaciona no se toca.
    """
    familias: dict[str, list[int]] = {}
    for i, rol in enumerate(roles):
        clave = "bateria" if rol in _ROLES_BATERIA else rol
        if clave != "generico":
            familias.setdefault(clave, []).append(i)

    hechos = []
    for fam, idx in familias.items():
        if len(idx) < 2:
            continue
        monos = {i: pistas[i].mean(axis=1) for i in idx}
        ancla = None
        if fam == "bateria":
            for r in _ANCLA_BATERIA:
                ancla = next((i for i in idx if roles[i] == r), None)
                if ancla is not None:
                    break
        if ancla is None:
            ancla = max(idx, key=lambda i: float(np.mean(monos[i] ** 2)))
        a_dec, sr_dec = _decimar_para_correlacion(monos[ancla], sr)
        factor = sr / sr_dec

        # tramo de 10 s más fuerte del ancla, para afinar a resolución completa
        largo = min(len(monos[ancla]), 10 * sr)
        paso = max(1, sr // 2)
        energias = [float(np.sum(monos[ancla][s: s + largo] ** 2))
                    for s in range(0, max(1, len(monos[ancla]) - largo), paso)]
        ini = int(np.argmax(energias)) * paso if energias else 0

        for i in idx:
            if i == ancla:
                continue
            m_dec, _ = _decimar_para_correlacion(monos[i], sr)
            lag_ms, corr = _cross_correlacion_maxima(m_dec, a_dec, sr_dec, max_lag_ms)
            if abs(corr) < umbral:
                continue
            signo = -1.0 if corr < 0 else 1.0
            # afinado: correlación a frecuencia completa alrededor del lag grueso
            grueso = int(round(lag_ms / 1000 * sr))
            radio = int(np.ceil(factor)) + 1
            ref = monos[ancla][ini: ini + largo]
            m = monos[i] * signo
            lags = np.arange(grueso - radio, grueso + radio + 1)
            vals = []
            for k in lags:
                s0 = ini + k
                if s0 < 0 or s0 + len(ref) > len(m):
                    vals.append(-np.inf)
                    continue
                vals.append(float(np.dot(m[s0: s0 + len(ref)], ref)))
            vals = np.array(vals)
            j = int(np.argmax(vals))
            fino = float(lags[j])
            if 0 < j < len(vals) - 1 and np.isfinite(vals[j - 1]) and np.isfinite(vals[j + 1]):
                den = vals[j - 1] - 2 * vals[j] + vals[j + 1]
                if den < 0:
                    fino += 0.5 * (vals[j - 1] - vals[j + 1]) / den
            if signo < 0:
                pistas[i] = -pistas[i]
            if abs(fino) >= 0.25:
                pistas[i] = _desplazar(pistas[i], -fino)
            if signo < 0 or abs(fino) >= 0.25:
                hechos.append(f"{nombres[i]} (respecto de {nombres[ancla]}): "
                              f"{'polaridad invertida, ' if signo < 0 else ''}"
                              f"{fino / sr * 1000:+.2f} ms (corr {abs(corr):.2f})")
    return hechos


# Pasa-altos por rol (Hz, 12 dB/oct): saca el grave que no aporta y deja
# lugar a bombo y bajo. Valores de oficio para rock/metal, no medidos.
_HPF_ROL = {
    "guitarra": 70.0, "voz_principal": 90.0, "coros": 120.0, "overhead": 120.0,
    "hats": 250.0, "snare": 70.0, "toms": 50.0, "teclas": 40.0, "vientos": 100.0,
    "percusion_mayor": 60.0, "percusion_menor": 200.0, "bajo": 30.0,
}
# EQ espejo (Nolly Getgood, Periphery): el bajo sube ~80 Hz y las guitarras
# bajan lo mismo ahí, para que cada uno tenga su lugar en el grave.
_ESPEJO_HZ, _ESPEJO_DB, _ESPEJO_Q = 80.0, 1.5, 0.9


def _filtros_por_rol(audio: np.ndarray, sr: int, rol: str, espejo: bool) -> np.ndarray:
    """Pasa-altos según el rol y, si `espejo`, la EQ espejo bajo/guitarras."""
    corte = _HPF_ROL.get(rol)
    if corte:
        sos = signal.butter(2, corte, "highpass", fs=sr, output="sos")
        audio = signal.sosfilt(sos, audio, axis=0)
    if espejo and rol in ("bajo", "guitarra"):
        b, a = _peaking_biquad(_ESPEJO_HZ, _ESPEJO_DB if rol == "bajo" else -_ESPEJO_DB,
                               _ESPEJO_Q, sr)
        audio = signal.lfilter(b, a, audio, axis=0)
    return audio


def _cadena_voz(audio: np.ndarray, sr: int) -> np.ndarray:
    """Cadena de voz (ítem 5): rider, dos compresores en serie y de-esser.

    1. Rider: nivela la voz en ventanas de 400 ms hacia su propia mediana
       (±6 dB, solo donde canta: en los silencios no sube el bleed).
    2. Compresor rápido 4:1, ataque 1 ms (estilo 1176): caza los picos.
    3. Compresor lento 3:1, ataque 10 ms, release 300 ms (estilo óptico):
       da cuerpo parejo. Dos de ~3 dB suenan más naturales que uno de 6.
    4. De-esser: comprime solo la banda de 5–9 kHz.
    Vuelve al RMS de entrada: el nivel del plan no cambia.
    """
    rms_in = _rms(audio)
    if rms_in < 1e-9:
        return audio
    n = audio.shape[0]
    mono = audio.mean(axis=1)
    v = int(0.4 * sr)
    nb = n // v
    if nb >= 4:
        r_db = 20 * np.log10(np.sqrt(np.mean(mono[: nb * v].reshape(nb, v) ** 2, axis=1)) + 1e-12)
        activos = r_db > r_db.max() - 30
        g = np.where(activos, np.clip(np.median(r_db[activos]) - r_db, -6.0, 6.0), 0.0)
        g = np.convolve(g, np.ones(3) / 3, mode="same")
        audio = audio * (10 ** (np.interp(np.arange(n), np.arange(nb) * v + v / 2, g) / 20))[:, None]
    audio, _ = _compresor_bus(audio, sr, ratio=4.0, attack_ms=1.0, release_ms=60.0,
                              percentil=90.0, margen_db=3.0)
    audio, _ = _compresor_bus(audio, sr, ratio=3.0, attack_ms=10.0, release_ms=300.0,
                              percentil=70.0, margen_db=0.0)
    sos = signal.butter(4, [5000.0, min(9000.0, sr * 0.45)], "bandpass", fs=sr, output="sos")
    banda = signal.sosfiltfilt(sos, audio, axis=0)
    banda_c, _ = _compresor_bus(banda, sr, ratio=4.0, attack_ms=1.0, release_ms=60.0,
                                percentil=90.0, margen_db=3.0)
    audio = audio - banda + banda_c
    return audio * (rms_in / max(_rms(audio), 1e-12))


def _grupo_separacion(rol: str) -> str:
    """Rol de la auto-mezcla → grupo del separador (drums/bass/vocals/other)."""
    if rol in _ROLES_BATERIA or rol in ("percusion_mayor", "percusion_menor"):
        return "drums"
    if rol == "bajo":
        return "bass"
    if rol in ("voz_principal", "coros"):
        return "vocals"
    return "other"


def _igualar_balance(pistas: list, roles: list, sr: int, balance_ref: dict,
                     tope_db: float = 6.0) -> dict:
    """Lleva el balance batería/bajo/voz/resto de los stems al de la
    referencia separada (ítem 2). Cada grupo se mide en LU respecto del
    total, igual que en la referencia, y se corrige con ganancia (±`tope_db`).
    Dos vueltas: al mover un grupo cambia el total. Modifica `pistas` en el
    lugar. Devuelve {grupo: {"ref", "antes", "despues", "ajuste_db"}}."""
    grupos = [_grupo_separacion(r) for r in roles]
    n = max(p.shape[0] for p in pistas)

    def medir():
        total = np.zeros((n, 2))
        sumas = {}
        for p, g in zip(pistas, grupos):
            total[: p.shape[0]] += p
            sumas.setdefault(g, np.zeros((n, 2)))[: p.shape[0]] += p
        l_tot = lufs_integrado(total, sr)
        return {g: lufs_integrado(s, sr) - l_tot for g, s in sumas.items()}

    antes = medir()
    ajuste = {g: 0.0 for g in antes}
    actual = antes
    for _ in range(2):
        for g, rel in actual.items():
            obj = balance_ref.get(g)
            if obj is None or not np.isfinite(rel):
                continue
            nuevo = float(np.clip(ajuste[g] + (obj - rel), -tope_db, tope_db))
            k = 10 ** ((nuevo - ajuste[g]) / 20)
            for i, gi in enumerate(grupos):
                if gi == g:
                    pistas[i] = pistas[i] * k
            ajuste[g] = nuevo
        actual = medir()
    return {g: {"ref": balance_ref.get(g),
                "antes": round(float(antes[g]), 1) if np.isfinite(antes[g]) else None,
                "despues": round(float(actual[g]), 1) if np.isfinite(actual[g]) else None,
                "ajuste_db": round(ajuste[g], 1)} for g in antes}


def _ganancia_compresion(mono: np.ndarray, sr: int, ratio: float, umbral_db: float,
                         attack_ms: float, release_ms: float) -> np.ndarray:
    """La curva de ganancia de `_comprimir_banda` (mismo detector RMS de
    fase cero), para aplicarla igual a varias pistas de un grupo."""
    tau = max((attack_ms + release_ms) / 2 / 1000 * sr, 1.0)
    alpha = float(np.exp(-1.0 / tau))
    power = signal.filtfilt([1 - alpha], [1.0, -alpha], mono ** 2)
    env_db = 10.0 * np.log10(np.maximum(power, 1e-12))
    return 10 ** (-np.maximum(env_db - umbral_db, 0.0) * (1.0 - 1.0 / ratio) / 20.0)


def _dinamica_por_grupo(pistas: list, roles: list, sr: int, rango_ref: dict,
                        umbral_db: float = 1.0, ratio_max: float = 4.0) -> dict:
    """Master por grupos (ítem 22): cada grupo (batería, bajo, voz, resto) se
    comprime como un bus hasta moverse como ESE grupo en la referencia
    separada (rango p95−p50 en 50 ms). Es dinámica, no EQ: respeta "EQ solo
    en guitarras". La ganancia sale de la suma del grupo y se aplica igual a
    todas sus pistas (no cambia el balance interno). Ratio por bisección,
    nunca expande. Modifica `pistas`; devuelve {grupo: dB de rango quitados}."""
    grupos = [_grupo_separacion(r) for r in roles]
    n = max(p.shape[0] for p in pistas)
    hecho = {}
    for g in set(grupos):
        r_ref = rango_ref.get(g)
        if r_ref is None:
            continue
        idx = [i for i, gi in enumerate(grupos) if gi == g]
        suma = np.zeros(n)
        for i in idx:
            suma[: pistas[i].shape[0]] += pistas[i].mean(axis=1)
        r_mix, p50 = rango_corto_db(suma, sr)
        if r_mix - r_ref <= umbral_db:
            continue
        lo, hi = 1.0, ratio_max
        mejor, r_mejor = np.ones(n), r_mix
        for _ in range(5):
            ratio = (lo + hi) / 2
            gan = _ganancia_compresion(suma, sr, ratio, p50, 15.0, 120.0)
            r_post = rango_corto_db(suma * gan, sr)[0]
            if abs(r_post - r_ref) < abs(r_mejor - r_ref):
                mejor, r_mejor = gan, r_post
            if r_post > r_ref + 0.3:
                lo = ratio
            else:
                hi = ratio
        makeup = np.sqrt(np.mean(suma ** 2) / max(np.mean((suma * mejor) ** 2), 1e-24))
        for i in idx:
            pistas[i] = pistas[i] * (mejor[: pistas[i].shape[0]] * makeup)[:, None]
        hecho[g] = round(r_mix - r_mejor, 1)
    return hecho


def _curva_consola(freqs: np.ndarray, graves_db, medios_db, agudos_db, xp=np):
    """EQ de 3 bandas de la consola optimizada: shelf de graves (120 Hz),
    campana ancha (1 kHz, ±1 octava) y shelf de agudos (6 kHz), en dB.
    `xp` permite evaluarla con numpy o con torch (para derivarla)."""
    l2 = xp.log2(freqs)
    sig = lambda x: 1 / (1 + xp.exp(-x))
    return (graves_db * sig(-(l2 - np.log2(120.0)) * 2)
            + medios_db * xp.exp(-0.5 * ((l2 - np.log2(1000.0)) / 1.0) ** 2)
            + agudos_db * sig((l2 - np.log2(6000.0)) * 2))


def _consola_optimizada(pistas: list, roles: list, sr: int, medidas_ref: dict,
                        grupos_con_eq: set, pasos: int = 300) -> dict:
    """Mezcla por optimización diferenciable (ítem 23), en la línea de las
    consolas diferenciables (Steinmetz et al., ICASSP 2021; DeepAFx-ST, JAES
    2022), en versión chica: por grupo se aprenden la ganancia (±3 dB) y una
    EQ de 3 bandas (±4 dB) con descenso de gradiente (Adam, torch) para que
    la FORMA del espectro de cada grupo y la del total se parezcan a las de
    la referencia separada. Trabaja sobre espectros (los grupos suman en
    potencia), así que no procesa audio en el bucle: tarda segundos.

    Solo los grupos de `grupos_con_eq` reciben EQ (respeta "EQ solo en
    guitarras"); el resto solo ganancia. No es una red entrenada: aprende
    los parámetros para ESTE tema. Modifica `pistas`; devuelve los
    parámetros por grupo."""
    import torch

    freqs_ref = np.asarray(medidas_ref.get("freqs") or [], dtype=float)
    esp_ref = medidas_ref.get("espectro") or {}
    grupos = [_grupo_separacion(r) for r in roles]
    activos = [g for g in GRUPOS_SEP if g in grupos and esp_ref.get(g)]
    if len(activos) < 2 or freqs_ref.size == 0:
        return {}
    n = max(p.shape[0] for p in pistas)
    esp_mix = {}
    for g in activos:
        suma = np.zeros((n, 2))
        for p, gi in zip(pistas, grupos):
            if gi == g:
                suma[: p.shape[0]] += p
        f, e = espectro_suavizado(suma, sr, n_puntos=len(freqs_ref))
        esp_mix[g] = e
    util = freqs_ref <= F_MAX_MATCH_HZ
    F = torch.tensor(freqs_ref[util])
    M = {g: torch.tensor(esp_mix[g][util]) for g in activos}
    R = {g: torch.tensor(np.asarray(esp_ref[g], dtype=float)[util]) for g in activos}
    r_tot = 10 * torch.log10(sum(10 ** (R[g] / 10) for g in activos))

    def forma(x):
        return x - x.mean()

    gan = {g: torch.zeros(1, requires_grad=True) for g in activos}
    eq = {g: torch.zeros(3, requires_grad=(g in grupos_con_eq)) for g in activos}
    params = [gan[g] for g in activos] + [eq[g] for g in activos if g in grupos_con_eq]
    opt = torch.optim.Adam(params, lr=0.05)
    for _ in range(pasos):
        opt.zero_grad()
        nuevos = {}
        for g in activos:
            e = 4 * torch.tanh(eq[g] / 4)
            nuevos[g] = M[g] + 3 * torch.tanh(gan[g] / 3) + _curva_consola(F, e[0], e[1], e[2], torch)
        tot = 10 * torch.log10(sum(10 ** (nuevos[g] / 10) for g in activos))
        perdida = ((forma(tot) - forma(r_tot)) ** 2).mean()
        perdida = perdida + 0.5 * sum(((forma(nuevos[g]) - forma(R[g])) ** 2).mean()
                                      for g in activos if g in grupos_con_eq) / max(len(activos), 1)
        perdida.backward()
        opt.step()

    resultado = {}
    for g in activos:
        g_db = float(3 * np.tanh(gan[g].item() / 3))
        e = (4 * torch.tanh(eq[g] / 4)).detach().numpy() if g in grupos_con_eq else np.zeros(3)
        curva = _curva_consola(freqs_ref, *e) + g_db
        fir = _curva_fir_fina(freqs_ref, curva, sr)
        for i, gi in enumerate(grupos):
            if gi == g:
                pistas[i] = _aplicar_fir(pistas[i], fir)
        resultado[g] = {"ganancia_db": round(g_db, 1), "eq_db": [round(float(x), 1) for x in e]}
    return resultado


GRUPOS_SEP = ("drums", "bass", "vocals", "other")
_ROLES_ACOMPANAMIENTO = ("guitarra", "teclas", "vientos")


def _desenmascarar_voz(pistas: list, roles: list, sr: int, f_lo: float = 1000.0,
                       f_hi: float = 4000.0, tope_db: float = 3.0) -> float:
    """Desenmascarado dinámico (ítem 6, parte 2), estilo trackspacer: la
    banda de inteligibilidad de la voz (1–4 kHz) de guitarras, teclas y
    vientos baja hasta `tope_db` SOLO mientras la voz canta y el
    acompañamiento compite con ella ahí (está a menos de 6 dB de la voz en
    esa banda). Fuera de esa banda y cuando la voz calla, nada cambia.
    Ataque ~10 ms, release 150 ms. Modifica `pistas` en el lugar y devuelve
    la reducción media mientras canta."""
    idx_voz = [i for i, r in enumerate(roles) if r == "voz_principal"]
    idx_acomp = [i for i, r in enumerate(roles) if r in _ROLES_ACOMPANAMIENTO]
    if not idx_voz or not idx_acomp:
        return 0.0
    n = max(p.shape[0] for p in pistas)
    v = max(1, int(0.01 * sr))
    nb = n // v
    if nb < 10:
        return 0.0
    sos = signal.butter(4, [f_lo, f_hi], "bandpass", fs=sr, output="sos")

    def env_db(x):
        x = np.pad(x, (0, max(0, nb * v - len(x))))[: nb * v]
        return 20 * np.log10(np.sqrt(np.mean(x.reshape(nb, v) ** 2, axis=1)) + 1e-12)

    voz = np.zeros(n)
    for i in idx_voz:
        voz[: pistas[i].shape[0]] += pistas[i].mean(axis=1)
    ev = env_db(signal.sosfiltfilt(sos, voz))
    canta = ev > ev.max() - 25
    a_re = float(np.exp(-1.0 / max(0.15 / 0.01, 1e-3)))
    medias = []
    for i in idx_acomp:
        x = pistas[i]
        banda = signal.sosfiltfilt(sos, x, axis=0)
        compite = canta & (env_db(banda.mean(axis=1)) > ev - 6)
        red = np.where(compite, tope_db, 0.0)
        g = 0.0
        for t in range(nb):
            g = max(red[t], a_re * g)
            red[t] = g
        gan = 10 ** (-np.interp(np.arange(x.shape[0]), np.arange(nb) * v + v / 2, red) / 20)
        pistas[i] = x - banda + banda * gan[:, None]
        if canta.any():
            medias.append(float(red[canta].mean()))
    return float(np.mean(medias)) if medias else 0.0


# Capas de arreglo que suben en los estribillos (ítem 19); batería, bajo y
# voz quedan como están
_ROLES_CAPA = ("guitarra", "teclas", "coros", "vientos")


def _levantar_estribillos(total: np.ndarray, capas: np.ndarray, sr: int,
                          subida_db: float = 1.0, ancho: float = 0.15) -> tuple[np.ndarray, float]:
    """Partes fuertes del tema (estribillos): las capas suben `subida_db` y
    se abren un `ancho` en estéreo (ítem 19).

    Secciones por energía: sonoridad en bloques de 0.5 s suavizada ~4 s; es
    "fuerte" lo que pasa la mediana del tema + 1.5 dB. Transiciones de ~1 s.
    Si el tema no tiene contraste (todo parejo), no cambia nada. Devuelve
    (lo que hay que sumarle a la mezcla, fracción del tema marcada fuerte).
    """
    n = total.shape[0]
    v = int(0.5 * sr)
    nb = n // v
    if nb < 16 or _rms(capas) < 1e-9:
        return np.zeros_like(capas), 0.0
    mono = total.mean(axis=1)
    r_db = 20 * np.log10(np.sqrt(np.mean(mono[: nb * v].reshape(nb, v) ** 2, axis=1)) + 1e-12)
    # relleno con el borde, no con ceros: 0 dB sería "muy fuerte" en los extremos
    s = np.convolve(np.pad(r_db, (4, 3), mode="edge"), np.ones(8) / 8, mode="valid")
    activos = s > s.max() - 30
    mascara = (s > np.median(s[activos]) + 1.5).astype(float)
    mascara = np.convolve(mascara, np.ones(2) / 2, mode="same")
    m = np.interp(np.arange(n), np.arange(nb) * v + v / 2, mascara)
    g = 10 ** (subida_db * m / 20)
    mid = (capas[:, 0] + capas[:, 1]) / 2
    side = (capas[:, 0] - capas[:, 1]) / 2 * (1 + ancho * m)
    nuevo = np.stack([(mid + side) * g, (mid - side) * g], axis=1)
    return nuevo - capas, float(np.mean(mascara > 0.5))


def sumar_stems(carpeta: Path, mejorar_percusion: bool = True,
                transient_cant: float = 0.3, progreso=None,
                plan_mezcla: dict | None = None,
                separar: tuple[str, ...] | None = None,
                bus_bateria: bool = False, bajo_dividido: bool = False,
                alinear_fase: bool = False, filtros_por_rol: bool = False,
                cadena_voz: bool = False, estribillos: bool = False,
                desenmascarar: bool = False, balance_ref: dict | None = None,
                informe: dict | None = None, medidas_ref: dict | None = None,
                consola_ml: bool = False, dinamica_grupos: bool = False,
                grupos_eq: set | None = None):
    """Suma todos los stems de una carpeta en una mezcla virtual estéreo.

    Alinea longitudes al stem más largo y deja headroom (pico a -6 dBFS)
    antes del master. Lanza excepción si no hay stems.

    v0.8.3: si `mejorar_percusion`, aplica transient shaping suave a los stems
    de batería/percusión ANTES de sumar → más pegada en el master por stems.

    `plan_mezcla` (opcional, de `automezcla.calcular_plan`): aplica ganancia
    +panning de PUNTO DE PARTIDA por rol antes de sumar, en vez de la suma
    plana centrada de siempre. Sin esto, comportamiento igual que antes
    (compatibilidad hacia atrás). Con esto, el resultado sigue siendo un
    punto de partida — no una mezcla terminada, ver `automezcla.py`.

    `separar` (opcional): claves de nombre (p. ej. ("gtr", "guit")). Si se
    pasa, devuelve (mezcla, sr, grupo, nombres_grupo): `grupo` es la suma de
    los stems cuyo nombre contiene alguna clave, con la MISMA ganancia de
    headroom que la mezcla, para poder procesarlo aparte y volver a sumarlo.

    `bus_bateria` / `bajo_dividido` (30/9), `alinear_fase` / `filtros_por_rol`
    (2/10), `cadena_voz` / `estribillos` (2/10): procesado por rol antes de
    sumar (ver `_bus_bateria`, `_bajo_dividido`, `_alinear_fase`,
    `_filtros_por_rol`, `_cadena_voz` y `_levantar_estribillos`).
    `balance_ref` (de `separacion.balance_por_instrumento`): lleva el balance
    batería/bajo/voz/resto al de la referencia; `informe` (dict) recibe el
    detalle en "balance_referencia". Con `medidas_ref` (de
    `separacion.medidas_por_instrumento`): `consola_ml` aprende ganancia y EQ
    por grupo (`_consola_optimizada`, EQ solo en `grupos_eq`) y
    `dinamica_grupos` comprime cada grupo como en la referencia. El rol sale del plan si hay, o
    del nombre del archivo. Apagados por defecto; `masterizar` los prende
    desde `stems_master` del config.
    """
    archivos = sorted(p for p in Path(carpeta).iterdir()
                      if p.is_file() and p.suffix.lower() in FORMATOS_STEM)
    if not archivos:
        raise FileNotFoundError(f"No hay stems en {carpeta}")

    # Estimación de RAM previa (barata: solo lee cabeceras, no decodifica) —
    # cada stem se carga completo como float64 y TODOS quedan en memoria a
    # la vez hasta sumarlos. Sin esto, con muchas pistas el primer síntoma
    # de quedarse sin RAM es la app colgada sin explicación.
    try:
        gb_estimado = sum(
            sf.info(str(p)).frames * sf.info(str(p)).channels * 8
            for p in archivos
        ) / 1e9
        if gb_estimado > 4.0:
            msg = (f"⚠ Sumando {len(archivos)} stems: ~{gb_estimado:.1f} GB de RAM "
                   "estimados antes de sumarlos (cada uno se carga completo en "
                   "memoria). Si la máquina tiene menos RAM libre que eso, puede "
                   "ir muy lento o fallar con MemoryError.")
            log.warning(msg)
            if progreso:
                progreso(msg)
    except Exception:
        log.exception("No se pudo estimar RAM previa para %s", carpeta)

    pistas, srs, en_grupo, roles = [], [], [], []
    claves_grupo = tuple(c.lower() for c in (separar or ()))
    for p in archivos:
        audio, sr = cargar_audio(p)
        if audio.shape[1] == 1:
            audio = np.repeat(audio, 2, axis=1)
        if mejorar_percusion and transient_cant > 0 and _es_percusion(p.name):
            audio = _transient_shape(audio, sr, transient_cant)
            log.info("Stem percusivo realzado (pegada): %s", p.name)
        if plan_mezcla:
            info = plan_mezcla.get("stems", {}).get(p.stem)
            if info:
                ganancia = 10 ** (info["ganancia_db"] / 20)
                # L==R tras el dup de arriba (o si venía estéreo real de
                # fábrica, se colapsa a mono para repanear — caso raro en
                # stems de grabación en vivo, casi siempre mono por mic).
                audio = aplicar_pan(audio[:, 0] * ganancia, info["pan"])
        rol = ((plan_mezcla or {}).get("stems", {}).get(p.stem, {}).get("rol")
               or clasificar_rol(p.stem))
        if rol == "bajo" and _es_percusion(p.name):
            rol = "kick"  # "Bass Drum" contiene "bass": no es un bajo
        if bajo_dividido and rol == "bajo":
            audio = _bajo_dividido(audio, sr)
            log.info("Bajo dividido (grave limpio + medios saturados): %s", p.name)
        if cadena_voz and rol in ("voz_principal", "coros"):
            audio = _cadena_voz(audio, sr)
            log.info("Cadena de voz (rider + 2 compresores + de-esser): %s", p.name)
        pistas.append(audio)
        roles.append(rol)
        srs.append(sr)
        en_grupo.append(bool(claves_grupo)
                        and any(c in p.name.lower() for c in claves_grupo))
    if len(set(srs)) > 1:
        raise ValueError(f"Los stems tienen sample rates distintos: {sorted(set(srs))}")

    if alinear_fase:
        hechos = _alinear_fase(pistas, roles, [p.stem for p in archivos], srs[0])
        for h in hechos:
            log.info("Fase: %s", h)
        if hechos and progreso:
            progreso("Fase alineada: " + "; ".join(hechos))
    if filtros_por_rol:
        espejo = "bajo" in roles and "guitarra" in roles
        pistas = [_filtros_por_rol(p, srs[0], r, espejo) for p, r in zip(pistas, roles)]
    if balance_ref:
        bal = _igualar_balance(pistas, roles, srs[0], balance_ref)
        if informe is not None:
            informe["balance_referencia"] = bal
        msg = "Balance como la referencia: " + ", ".join(
            f"{g} {v['ajuste_db']:+.1f} dB" for g, v in bal.items() if v["ajuste_db"])
        log.info(msg)
        if progreso:
            progreso(msg)
    if medidas_ref and consola_ml:
        try:
            consola = _consola_optimizada(pistas, roles, srs[0], medidas_ref,
                                          grupos_eq if grupos_eq is not None else set(GRUPOS_SEP))
        except ImportError:
            consola = {}
            log.warning("Consola optimizada: torch no está instalado, se salta")
        if informe is not None:
            informe["consola_optimizada"] = consola
        if consola and progreso:
            progreso("Consola optimizada: " + ", ".join(
                f"{g} {v['ganancia_db']:+.1f} dB" for g, v in consola.items()))
    if medidas_ref and dinamica_grupos:
        din = _dinamica_por_grupo(pistas, roles, srs[0], medidas_ref.get("rango") or {})
        if informe is not None:
            informe["dinamica_grupos"] = din
        if din and progreso:
            progreso("Dinámica por grupo como la referencia: " + ", ".join(
                f"{g} −{v:.1f} dB de rango" for g, v in din.items()))
    if desenmascarar:
        red_voz = _desenmascarar_voz(pistas, roles, srs[0])
        if red_voz > 0:
            msg = f"Desenmascarado: el acompañamiento deja lugar a la voz ({red_voz:.1f} dB en 1–4 kHz)"
            log.info(msg)
            if progreso:
                progreso(msg)

    n = max(p.shape[0] for p in pistas)
    mezcla = np.zeros((n, 2))
    en_bus = [bus_bateria and r in _ROLES_BATERIA for r in roles]
    bus = np.zeros((n, 2)) if any(en_bus) else None
    for p, b in zip(pistas, en_bus):
        (bus if b else mezcla)[: p.shape[0]] += p
    if bus is not None:
        bus, info_bus = _bus_bateria(bus, srs[0])
        msg = (f"Bus de batería ({sum(en_bus)} stems): paralela "
               f"{info_bus['reduccion_paralela_db']} dB, pegamento "
               f"{info_bus['reduccion_pegamento_db']} dB")
        log.info(msg)
        if progreso:
            progreso(msg)
        mezcla += bus

    if estribillos:
        capas = np.zeros((n, 2))
        for p, r in zip(pistas, roles):
            if r in _ROLES_CAPA:
                capas[: p.shape[0]] += p
        delta, frac = _levantar_estribillos(mezcla, capas, srs[0])
        if frac > 0:
            mezcla += delta
            msg = f"Estribillos: las capas suben 1 dB y se abren en el {frac:.0%} del tema"
            log.info(msg)
            if progreso:
                progreso(msg)

    pico = float(np.max(np.abs(mezcla)))
    k = (10 ** (-6.0 / 20)) / pico if pico > 1e-9 else 1.0
    mezcla *= k  # headroom -6 dBFS para el master
    log.info("Mezcla virtual: %d stems sumados desde %s", len(pistas), carpeta)
    if separar is None:
        return mezcla, srs[0]

    grupo = np.zeros((n, 2))
    nombres = []
    for pista, sel, arch in zip(pistas, en_grupo, archivos):
        if sel:
            grupo[: pista.shape[0]] += pista
            nombres.append(arch.name)
    grupo *= k
    return mezcla, srs[0], grupo, nombres


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


# Ítem 17: "mixta" = graves (< ~200 Hz) en fase mínima y el resto en fase
# lineal. Un FIR de fase lineal que mueve graves genera pre-eco (energía
# ANTES del golpe del bombo); en fase mínima no hay pre-eco. Arriba, la fase
# lineal no corre la fase entre bandas y el pre-eco es corto e inaudible.
FASE_EQ = "mixta"
F_CRUCE_FASE_HZ = (150.0, 300.0)   # transición de mínima a lineal


def _firwin2_curva(freqs: np.ndarray, gan_db: np.ndarray, sr: int, taps: int) -> np.ndarray:
    nyq = sr / 2
    f = np.concatenate(([0.0], freqs / nyq, [1.0]))
    g_lin = 10 ** (np.concatenate(([gan_db[0]], gan_db, [gan_db[-1]])) / 20)
    f = np.clip(f, 0.0, 1.0)
    f, idx = np.unique(f, return_index=True)
    return signal.firwin2(taps, f, g_lin[idx])


def _curva_fir_fina(freqs: np.ndarray, gan_db: np.ndarray, sr: int,
                    fase: str | None = None) -> np.ndarray:
    """FIR desde una curva fina de ganancias (1/3 de octava).

    `fase` "lineal": un solo FIR de fase lineal (lo de siempre). "mixta"
    (por defecto, `FASE_EQ`): la curva se parte en la parte de graves (fase
    mínima) y el resto (fase lineal) y se encadenan. El FIR resultante se
    rellena con ceros al principio para que `len // 2` siga siendo su retardo
    real: `_aplicar_fir` y `_aplicar_ms` lo usan sin cambios.
    """
    fase = fase or FASE_EQ
    if fase != "mixta":
        return _firwin2_curva(freqs, gan_db, sr, FIR_TAPS)
    f_a, f_b = F_CRUCE_FASE_HZ
    w = np.clip(np.log(np.maximum(freqs, 1.0) / f_a) / np.log(f_b / f_a), 0.0, 1.0)
    graves_db = gan_db * (1 - w)
    resto_db = gan_db - graves_db
    # minimum_phase (homomórfico) devuelve la raíz de la magnitud: se diseña
    # con el doble de dB para que el resultado tenga la magnitud pedida
    h_min = signal.minimum_phase(_firwin2_curva(freqs, 2 * graves_db, sr, FIR_TAPS),
                                 method="homomorphic", n_fft=2 ** 17)
    h_lin = _firwin2_curva(freqs, resto_db, sr, FIR_TAPS)
    h = np.convolve(h_min, h_lin)
    return np.concatenate([np.zeros(len(h_min) - 1), h])


def _aplicar_ms(audio: np.ndarray, fir_mid: np.ndarray, fir_side: np.ndarray) -> np.ndarray:
    """Filtra el MID y el SIDE con FIR distintos y vuelve a L/R."""
    mid = (audio[:, 0] + audio[:, 1]) / 2
    side = (audio[:, 0] - audio[:, 1]) / 2
    demora = len(fir_mid) // 2
    mid = signal.fftconvolve(mid, fir_mid, mode="full")[demora:demora + audio.shape[0]]
    side = signal.fftconvolve(side, fir_side, mode="full")[demora:demora + audio.shape[0]]
    return np.stack([mid + side, mid - side], axis=1)


F_SIDE_MIN_HZ = 150.0  # debajo de esto el side nunca se abre: el grave se desarma en mono


def _deltas_ms(audio: np.ndarray, sr: int, perfil: dict):
    """Corrección mid/side (dB, sin tope) para llevar `audio` a la referencia.

    MID: solo forma (se resta la media). SIDE: relativo a la media del MID de
    cada uno, así la corrección incluye cuánto ancho le falta o le sobra a
    cada banda. Mide sobre los tramos fuertes.
    """
    freqs, mid, side = espectro_ms(tramos_fuertes(audio, sr), sr)
    util = freqs <= F_MAX_MATCH_HZ
    ref_mid = np.asarray(perfil["espectro_mid_db"])
    ref_side = np.asarray(perfil["espectro_side_db"])
    base_mix, base_ref = float(np.mean(mid[util])), float(np.mean(ref_mid[util]))
    d_mid = (ref_mid - base_ref) - (mid - base_mix)
    d_side = (ref_side - base_ref) - (side - base_mix)
    d_mid[~util] = 0.0
    d_side[~util] = 0.0
    graves = freqs < F_SIDE_MIN_HZ
    d_side[graves] = np.minimum(d_side[graves], 0.0)   # graves: solo estrechar
    return freqs, d_mid, d_side, util


def _suavizar(delta: np.ndarray) -> np.ndarray:
    return np.convolve(delta, [0.25, 0.5, 0.25], mode="same")


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


def _clipper_transitorios(audio: np.ndarray, sr: int, umbral_dbfs: float) -> np.ndarray:
    """Clipper solo en los golpes (ítem 10): separa golpe y sostenido.

    Recortar un transitorio de pocos ms no se oye (enmascaramiento temporal),
    pero recortar una nota sostenida (bajo, acorde) sí: es distorsión. Con
    dos envolventes (1 ms y 50 ms), donde la rápida pasa a la lenta hay un
    golpe; ahí se usa la señal recortada (a 2x) y en lo sostenido la señal
    entra intacta y la controla el limitador, que es más limpio para eso.
    La máscara se suaviza ~2 ms para que el cambio no haga clic."""
    mono = np.max(np.abs(audio), axis=1)
    a_f = float(np.exp(-1.0 / max(0.001 * sr, 1.0)))
    a_s = float(np.exp(-1.0 / max(0.050 * sr, 1.0)))
    env_f = signal.filtfilt([1 - a_f], [1.0, -a_f], mono)
    env_s = signal.filtfilt([1 - a_s], [1.0, -a_s], mono)
    golpe = np.clip((env_f / (env_s + 1e-9) - 1.2) / 0.8, 0.0, 1.0)
    # se ensancha 3 ms a cada lado antes de suavizar: si no, el suavizado
    # baja la máscara justo en el pico del golpe, que es donde tiene que valer 1
    from scipy.ndimage import maximum_filter1d
    golpe = maximum_filter1d(golpe, size=max(1, int(0.006 * sr)))
    a_m = float(np.exp(-1.0 / max(0.002 * sr, 1.0)))
    golpe = np.clip(signal.filtfilt([1 - a_m], [1.0, -a_m], golpe), 0.0, 1.0)
    recortado = _a_2x(_clipper, audio, umbral_dbfs)
    return audio + golpe[:, None] * (recortado - audio)


def _a_2x(funcion, audio: np.ndarray, *args) -> np.ndarray:
    """Aplica una no linealidad (clipper, saturación) a 2x la frecuencia de
    muestreo: los armónicos que crea por encima de Nyquist se reflejarían
    como ruido inarmónico (aliasing); al subir primero y filtrar al bajar,
    esos armónicos se descartan (ítem 18 de la investigación de calidad)."""
    up = signal.resample_poly(audio, 2, 1, axis=0)
    return signal.resample_poly(funcion(up, *args), 1, 2, axis=0)[: audio.shape[0]]


def _saturar(x: np.ndarray, drive: float, tipo: str) -> np.ndarray:
    """Curva de saturación sobre señal normalizada a pico 1 (conserva el pico).
    "cinta": tanh simétrica (armónicos impares, redondea picos).
    "valvula": tanh con sesgo (agrega armónicos pares, más cálida)."""
    if tipo == "valvula":
        s = 0.15
        y = np.tanh(drive * (x + s)) - np.tanh(drive * s)
        c = max(abs(np.tanh(drive * (1 + s)) - np.tanh(drive * s)),
                abs(np.tanh(drive * (-1 + s)) - np.tanh(drive * s)))
        return y / c
    return np.tanh(drive * x) / np.tanh(drive)


def _bus_master(audio: np.ndarray, sr: int, tipo: str = "cinta",
                drive: float = 1.3) -> tuple[np.ndarray, float]:
    """Pegamento + saturación del bus (ítem 13).

    Compresión 2:1, ataque 30 ms, release 200 ms (estilo bus de consola SSL):
    1–2 dB sobre lo más fuerte, deja pasar el golpe. Después saturación suave
    a 2x (sin aliasing). Vuelve al RMS de entrada y saca la continua que
    agrega la curva de válvula. Devuelve (audio, reducción media en dB)."""
    rms_in = _rms(audio)
    if rms_in < 1e-9:
        return audio, 0.0
    audio, red = _compresor_bus(audio, sr, ratio=2.0, attack_ms=30.0, release_ms=200.0,
                                percentil=90.0, margen_db=3.0)
    pico = float(np.max(np.abs(audio)))
    audio = _a_2x(lambda x: _saturar(x / pico, drive, tipo) * pico, audio)
    if tipo == "valvula":
        sos = signal.butter(2, 10.0, "highpass", fs=sr, output="sos")
        audio = signal.sosfiltfilt(sos, audio, axis=0)
    return audio * (rms_in / max(_rms(audio), 1e-12)), red


def _resonancias_dinamicas(audio: np.ndarray, sr: int, f_lo: float, f_hi: float,
                           selectividad_db: float, profundidad: float, max_db: float,
                           release_ms: float) -> tuple[np.ndarray, float]:
    """Supresión dinámica de resonancias (ítem 11), mismo principio que
    soothe: en cada cuadro del espectro (STFT 2048, salto 1024) se compara la
    magnitud con su versión suavizada a 1/3 de octava; lo que sobresale más
    de `selectividad_db` se baja `profundidad` veces el exceso (tope
    `max_db`), solo entre `f_lo` y `f_hi`. El corte entra en un cuadro y se
    suelta con `release_ms`, por bin. Ganancia enlazada L/R (no mueve la
    imagen). Devuelve (audio, corte medio en dB donde actuó)."""
    nper, salto = 2048, 1024
    n = audio.shape[0]
    if n < nper * 4:
        return audio, 0.0
    f, _, Z = signal.stft(audio.T.astype(np.float32), fs=sr, nperseg=nper,
                          noverlap=nper - salto, boundary="even")
    # potencia promediada en ~8 cuadros (~190 ms): una resonancia se sostiene,
    # el ruido fluctúa al azar cuadro a cuadro y no debe confundirse con picos
    from scipy.ndimage import uniform_filter1d
    pot = uniform_filter1d((np.abs(Z) ** 2).mean(axis=0), size=8, axis=1, mode="nearest")
    mag_db = 10 * np.log10(pot + 1e-18)                              # (bins, cuadros)
    k = np.arange(len(f))
    lo = np.clip(np.floor(k / 2 ** (1 / 6)).astype(int), 0, len(f) - 1)
    hi = np.clip(np.ceil(k * 2 ** (1 / 6)).astype(int) + 1, 1, len(f))
    cs = np.concatenate([np.zeros((1, mag_db.shape[1])), np.cumsum(mag_db, axis=0)])
    suave = (cs[hi] - cs[lo]) / (hi - lo)[:, None]
    exceso = mag_db - suave - selectividad_db
    banda = (f >= f_lo) & (f <= f_hi)
    red = np.zeros_like(mag_db)
    red[banda] = np.clip(profundidad * exceso[banda], 0.0, max_db)
    a_re = float(np.exp(-1.0 / max(release_ms / 1000 * sr / salto, 1e-3)))
    g = np.zeros(mag_db.shape[0])
    for t in range(red.shape[1]):
        g = np.maximum(red[:, t], a_re * g)
        red[:, t] = g
    Z *= (10 ** (-red / 20)).astype(np.float32)[None]
    _, y = signal.istft(Z, fs=sr, nperseg=nper, noverlap=nper - salto, boundary=True)
    y = y.T[:n].astype(np.float64)
    if y.shape[0] < n:
        y = np.vstack([y, np.zeros((n - y.shape[0], y.shape[1]))])
    activo = red[banda] > 0.1
    return y, float(red[banda][activo].mean()) if activo.any() else 0.0


def _eq_perceptual(audio: np.ndarray, sr: int, recuperar_db: float = 2.0,
                   domar_db: float = 2.0) -> tuple[np.ndarray, float]:
    """EQ perceptual adaptativa (ítem 24), aproximación propia de la idea de
    Gullfoss con un modelo clásico de enmascaramiento: bandas críticas de
    Bark (Zwicker) y la función de dispersión de Schroeder et al. (JASA 1979).

    En cada cuadro (STFT 2048/1024, ~23 ms; energía promediada ~190 ms):
    - "Recuperar": una banda que sus vecinas tapan por 0–12 dB sube hasta
      `recuperar_db` (está por perderse, todavía se puede rescatar; si la
      tapan más, subirla no sirve).
    - "Domar": una banda que sobresale más de 6 dB sobre sus vecinas (±2 Bark)
      baja hasta `domar_db` (es la que enmascara a las demás).
    La ganancia se suaviza en el tiempo (~50 ms). Ganancia enlazada L/R.
    Devuelve (audio, cambio medio absoluto en dB)."""
    nper, salto = 2048, 1024
    n = audio.shape[0]
    if n < nper * 4:
        return audio, 0.0
    f, _, Z = signal.stft(audio.T.astype(np.float32), fs=sr, nperseg=nper,
                          noverlap=nper - salto, boundary="even")
    bark = 13 * np.arctan(0.00076 * f) + 3.5 * np.arctan((f / 7500.0) ** 2)
    banda = np.minimum(bark.astype(int), 24)
    nb = int(banda.max()) + 1
    from scipy.ndimage import uniform_filter1d
    pot = uniform_filter1d((np.abs(Z) ** 2).mean(axis=0), size=8, axis=1, mode="nearest")
    E = np.stack([pot[banda == b].sum(axis=0) for b in range(nb)]) + 1e-18  # (bandas, cuadros)
    E_db = 10 * np.log10(E)

    dz = np.arange(nb)[:, None] - np.arange(nb)[None, :]
    sf_db = 15.81 + 7.5 * (dz + 0.474) - 17.5 * np.sqrt(1 + (dz + 0.474) ** 2)
    W = 10 ** ((sf_db - 10.0) / 10)          # −10 dB: umbral de enmascaramiento
    np.fill_diagonal(W, 0.0)
    M_db = 10 * np.log10(W @ E + 1e-18)       # lo que las vecinas tapan en cada banda

    deficit = M_db - E_db
    subir = np.where((deficit > 0) & (deficit < 12), recuperar_db * np.clip(deficit / 6, 0, 1), 0.0)
    # promedio de las vecinas en POTENCIA (en dB, una vecina fuerte rodeada de
    # silencio quedaría escondida y la banda débil parecería dominar)
    vecinas = 10 * np.log10(np.stack([np.mean(np.delete(E[max(0, b - 2): b + 3], min(b, 2), axis=0),
                                              axis=0) for b in range(nb)]))
    dominio = E_db - vecinas
    bajar = domar_db * np.clip((dominio - 6) / 6, 0, 1)
    activo = E_db > E_db.max() - 60           # no tocar silencio ni ruido de fondo
    g_db = np.where(activo, subir - bajar, 0.0)

    a = float(np.exp(-1.0 / max(0.05 * sr / salto, 1e-3)))
    g_db = signal.filtfilt([1 - a], [1.0, -a], g_db, axis=1)
    Z *= (10 ** (g_db[banda] / 20)).astype(np.float32)[None]
    _, y = signal.istft(Z, fs=sr, nperseg=nper, noverlap=nper - salto, boundary=True)
    y = y.T[:n].astype(np.float64)
    if y.shape[0] < n:
        y = np.vstack([y, np.zeros((n - y.shape[0], y.shape[1]))])
    return y, float(np.mean(np.abs(g_db[:, activo.any(axis=0)]))) if activo.any() else 0.0


def _abrir_mono(audio: np.ndarray, sr: int, umbral_mono: float = 0.95,
                objetivo: float = 0.7) -> tuple[np.ndarray, float | None]:
    """Abre una mezcla casi mono (ítem 21). Side sintético = mid retrasado
    12 ms y sin graves (pasa-altos 300 Hz, el grave sigue mono). L = M + S,
    R = M − S: al sumar a mono S se cancela, así que la suma mono queda
    idéntica. El nivel de S se fija para llegar a la correlación `objetivo`.
    Si la mezcla ya tiene estéreo, no hace nada. Devuelve (audio, correlación
    original si se abrió, o None)."""
    l, r = audio[:, 0], audio[:, 1]
    den = np.sqrt(np.sum(l ** 2) * np.sum(r ** 2))
    if den < 1e-12:
        return audio, None
    corr = float(np.sum(l * r) / den)
    if corr < umbral_mono:
        return audio, None
    mid = (l + r) / 2
    retardo = int(0.012 * sr)
    s = np.concatenate([np.zeros(retardo), mid[:-retardo]])
    sos = signal.butter(2, 300.0, "highpass", fs=sr, output="sos")
    s = signal.sosfiltfilt(sos, s)
    e_m, e_s = float(np.sum(mid ** 2)), float(np.sum(s ** 2))
    if e_s < 1e-12:
        return audio, None
    # corr(L,R) = (Em − Es·g²) / (Em + Es·g²) → g para llegar al objetivo
    g = np.sqrt((1 - objetivo) / (1 + objetivo) * e_m / e_s)
    side = (l - r) / 2 + g * s
    return np.stack([mid + side, mid - side], axis=1), corr


def _exciter_graves(audio: np.ndarray, sr: int, f_lo: float, f_hi: float,
                    cantidad: float) -> np.ndarray:
    """Suma armónicos (2º a 4º) del grave en el centro de la imagen.

    La banda f_lo–f_hi se satura con tanh y se recorta a 2·f_lo–4·f_hi, así
    queda solo lo nuevo (los armónicos) sin tocar la fundamental. Se suma en
    mid para no abrir el grave. `cantidad` fija el RMS de los armónicos
    respecto del RMS de la banda original.
    """
    if cantidad <= 0:
        return audio
    mid = audio.mean(axis=1)
    sos_banda = signal.butter(4, [f_lo, f_hi], "bandpass", fs=sr, output="sos")
    banda = signal.sosfiltfilt(sos_banda, mid)
    rms_banda = float(np.sqrt(np.mean(banda ** 2)))
    if rms_banda < 1e-9:
        return audio
    sat = np.tanh(3.0 * banda / (np.max(np.abs(banda)) + 1e-12))
    sos_arm = signal.butter(4, [2 * f_lo, min(4 * f_hi, sr * 0.45)], "bandpass",
                            fs=sr, output="sos")
    armonicos = signal.sosfiltfilt(sos_arm, sat)
    rms_arm = float(np.sqrt(np.mean(armonicos ** 2)))
    if rms_arm < 1e-12:
        return audio
    armonicos *= cantidad * rms_banda / rms_arm
    return audio + armonicos[:, np.newaxis]


def _score_ab(audio: np.ndarray, sr: int, perfil: dict) -> dict:
    """Similitud del master vs el perfil de referencias (0–100 por aspecto).

    - tonal: distancia media de la curva espectral (solo forma, sin nivel)
    - dinamica: diferencia de crest factor
    - imagen: distancia media del ancho estéreo por banda
    """
    if perfil.get("espectro_mid_db") is not None:
        # mismo criterio que el matching mid/side: MID de los tramos fuertes
        freqs, esp_master, _ = espectro_ms(tramos_fuertes(audio, sr), sr)
        esp_ref = np.asarray(perfil["espectro_mid_db"])
    else:
        freqs, esp_master = espectro_suavizado(audio, sr)
        esp_ref = np.asarray(perfil["espectro_db"])
    util = freqs <= F_MAX_MATCH_HZ  # misma zona que el matching
    esp_master, esp_ref = esp_master[util], esp_ref[util]
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


def _multibanda_rango(audio: np.ndarray, sr: int, rango_ref: dict, cfg_mb: dict
                      ) -> tuple[np.ndarray, dict]:
    """Matching de dinámica por banda (ítem 9): cada banda se comprime hasta
    que se MUEVE como la de la referencia (rango corto p95−p50 en ventanas de
    50 ms, ver `rango_corto_db`), no solo hasta un crest global.

    Umbral en la mediana de la banda; el ratio se busca por bisección (5
    pasos, tope `ratio_max_rango`) hasta quedar a ≤0.3 dB del rango de la
    referencia. Solo comprime bandas más dinámicas que la ref (nunca
    expande). Makeup al RMS original de la banda. Devuelve (audio,
    {banda: dB de rango quitados})."""
    umbral = float(cfg_mb.get("umbral_rango_db", 1.0))
    ratio_max = float(cfg_mb.get("ratio_max_rango", 4.0))
    attack = float(cfg_mb.get("attack_ms", 15.0))
    release = float(cfg_mb.get("release_ms", 120.0))

    salida = np.zeros_like(audio)
    aplicado = {}
    for nombre, banda in _split_bandas(audio, sr).items():
        r_mix, p50 = rango_corto_db(banda.mean(axis=1), sr)
        r_ref = rango_ref.get(nombre)
        rms = float(np.sqrt(np.mean(banda ** 2)))
        if r_ref is None or rms <= 0 or r_mix - r_ref <= umbral:
            salida += banda
            continue
        lo, hi = 1.0, ratio_max
        mejor, r_mejor = banda, r_mix
        for _ in range(5):
            ratio = (lo + hi) / 2
            comp = _comprimir_banda(banda, sr, ratio, p50, attack, release)
            r_post = rango_corto_db(comp.mean(axis=1), sr)[0]
            if abs(r_post - r_ref) < abs(r_mejor - r_ref):
                mejor, r_mejor = comp, r_post
            if r_post > r_ref + 0.3:
                lo = ratio
            else:
                hi = ratio
        rms_post = float(np.sqrt(np.mean(mejor ** 2)))
        salida += mejor * (rms / rms_post if rms_post > 0 else 1.0)
        aplicado[nombre] = round(r_mix - r_mejor, 1)
    return salida, aplicado


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


def _ganancia_soft_knee(pico: np.ndarray, objetivo: float, knee_db: float) -> np.ndarray:
    """Ganancia (lineal) con rodilla suave cerca del techo — gain computer
    estándar de compresión/limitación digital (Giannoulis, Massberg & Reiss,
    "Digital Dynamic Range Compressor Design", JAES/DAFx 2012).

    Sin esto, la reducción es un escalón duro justo al llegar al techo, lo
    que suena "áspero" al empujar fuerte. Con la rodilla, la reducción entra
    de forma gradual unos dB antes — más transparente, menos distorsión
    audible, mismo techo de seguridad.
    """
    db_pico = 20 * np.log10(np.maximum(pico, 1e-9))
    db_obj = 20 * np.log10(objetivo)
    reduccion_db = np.zeros_like(db_pico)

    delta = db_pico - db_obj
    en_rodilla = np.abs(2 * delta) <= knee_db
    sobre = 2 * delta > knee_db

    reduccion_db[en_rodilla] = ((delta[en_rodilla] + knee_db / 2) ** 2) / (2 * knee_db)
    reduccion_db[sobre] = delta[sobre]
    return 10 ** (-reduccion_db / 20)


def _envolvente_lookahead(pico: np.ndarray, sr: int, lookahead_ms: float,
                          release_ms: float, objetivo: float, knee_db: float) -> np.ndarray:
    """Envolvente de ganancia suavizada (ataque instantáneo, release exponencial)."""
    from scipy.ndimage import maximum_filter1d
    ventana = max(int(lookahead_ms / 1000 * sr), 1)
    env = maximum_filter1d(pico, size=ventana * 2 + 1)
    ganancia = _ganancia_soft_knee(env, objetivo, knee_db)

    alpha = np.exp(-1.0 / (release_ms / 1000 * sr))
    suave = np.empty_like(ganancia)
    g = 1.0
    for i in range(len(ganancia)):
        g = min(ganancia[i], alpha * g + (1 - alpha) * ganancia[i])
        suave[i] = g
    return suave


def _medir_limitacion(pre: np.ndarray, post: np.ndarray, sr: int) -> dict:
    """Medidores de la etapa de volumen (ítem 14): cuánto bajó la ganancia,
    cuánta distorsión agregó y si bombea con el grave.

    `pre` es la señal antes de clipper + limitador, `post` el master. La
    ganancia se mide en ventanas de 10 ms (relativa a su mediana, así no
    cuenta la subida de nivel). Distorsión: lo que queda al quitarle a `post`
    esa ganancia lenta (lo que no es un cambio de volumen es deformación de
    la onda). Bombeo: si la ganancia en medios (300 Hz–5 kHz) baja cada vez
    que sube el grave (<150 Hz), el bombo está "empujando" la mezcla.
    Umbrales de aviso iniciales, a calibrar de oído.
    """
    n = min(len(pre), len(post))
    a, b = pre[:n].mean(axis=1), post[:n].mean(axis=1)
    v = max(1, int(sr * 0.01))
    nb = n // v
    if nb < 10:
        return {}

    def rms_b(x):
        return np.sqrt(np.mean(x[: nb * v].reshape(nb, v) ** 2, axis=1) + 1e-12)

    r_pre = rms_b(a)
    activos = 20 * np.log10(r_pre) > 20 * np.log10(r_pre.max()) - 30
    g_db = 20 * np.log10(rms_b(b) / r_pre)
    red = np.median(g_db[activos]) - g_db
    g_lin = np.interp(np.arange(n), np.arange(nb) * v + v / 2, 10 ** (g_db / 20))
    residuo = b - a * g_lin
    dist_db = 10 * np.log10(np.sum(residuo ** 2) / max(np.sum(b ** 2), 1e-12))

    sos_g = signal.butter(2, 150, "lowpass", fs=sr, output="sos")
    sos_m = signal.butter(2, [300, 5000], "bandpass", fs=sr, output="sos")
    grave = 20 * np.log10(rms_b(signal.sosfilt(sos_g, a)))
    g_medios = 20 * np.log10(rms_b(signal.sosfilt(sos_m, b)) / rms_b(signal.sosfilt(sos_m, a)))
    corr = float(np.corrcoef(grave[activos], g_medios[activos])[0, 1]) if activos.sum() > 10 else 0.0
    rango_medios = float(np.percentile(g_medios[activos], 95) - np.percentile(g_medios[activos], 5))
    return {
        "reduccion_media_db": round(float(np.mean(red[activos])), 1),
        "reduccion_p95_db": round(float(np.percentile(red[activos], 95)), 1),
        "distorsion_db": round(float(dist_db), 1),
        "bombeo_corr": round(corr, 2),
        "bombeo": bool(corr < -0.4 and rango_medios > 2.0),
    }


def _limitador(audio: np.ndarray, sr: int, cfg_lim: dict) -> np.ndarray:
    """Limitador de DOS ETAPAS con lookahead sobre TRUE peak (inter-sample) y
    rodilla suave — reduce distorsión audible al empujar fuerte, comparado
    con un limitador de una sola etapa/escalón duro.

    Etapa MACRO (lenta, lookahead largo): absorbe pasajes sostenidos fuertes
    por adelantado, de forma suave — así la etapa rápida no tiene que
    trabajar tan duro (menos "bombeo", más transparente).
    Etapa RÁPIDA (lookahead corto): atrapa picos puntuales/transitorios que
    la etapa lenta no ve venir — garantiza el techo real de seguridad.
    """
    ceiling_db = float(cfg_lim.get("ceiling_dbtp", -1.0))
    ceiling = 10 ** (ceiling_db / 20)
    objetivo = ceiling * 10 ** (-0.2 / 20)  # margen de seguridad
    knee_db = float(cfg_lim.get("knee_db", 3.0))

    n = audio.shape[0]
    up = signal.resample_poly(audio, 4, 1, axis=0)
    pico_up = np.max(np.abs(up), axis=1)
    pico = pico_up[: n * 4].reshape(n, 4).max(axis=1)

    # etapa macro: lookahead largo, release lento — suaviza pasajes sostenidos
    macro_ms = float(cfg_lim.get("lookahead_macro_ms", 20))
    g_macro = _envolvente_lookahead(pico, sr, macro_ms, macro_ms * 1.5, objetivo, knee_db)
    audio_macro = audio * g_macro[:, np.newaxis]

    # re-mide el pico tras la etapa macro para que la etapa rápida trabaje
    # sobre lo que realmente queda (no duplica reducción a ciegas)
    up2 = signal.resample_poly(audio_macro, 4, 1, axis=0)
    pico2 = np.max(np.abs(up2), axis=1)[: n * 4].reshape(n, 4).max(axis=1)

    # etapa rápida: lookahead corto, release normal — atrapa picos puntuales
    rapido_ms = float(cfg_lim.get("lookahead_ms", 5))
    g_rapido = _envolvente_lookahead(pico2, sr, rapido_ms, cfg_lim.get("release_ms", 50),
                                     objetivo, knee_db)
    out = audio_macro * g_rapido[:, np.newaxis]
    out = np.clip(out, -ceiling, ceiling)

    tp = true_peak_db(out, sr)
    if tp > ceiling_db:
        out = out * 10 ** ((ceiling_db - tp) / 20)
    return out


# ------------------------------------------------------------------ pipeline

def masterizar(path_mezcla: Path | None, path_referencia: Path | None,
               target_lufs: float, dir_masters: Path, dir_entregables: Path,
               version: str = "V01", carpeta_stems: Path | None = None,
               progreso=None, cfg: dict | None = None,
               genero: str | None = None) -> dict:
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
        cfg = cargar_config_master(genero)
        if genero:
            avisar(f"Preset de género: {genero}")
    cfg_eq = cfg["eq_correctivo"]
    cfg_den = cfg["densidad"]
    cfg_lim = cfg["limitador"]

    grupo_eq, stems_eq = None, []
    informe_stems = {}
    if carpeta_stems:
        avisar("Sumando stems en mezcla virtual…")
        cfg_sm = cfg.get("stems_master", {})
        claves_eq = tuple(cfg_sm.get("eq_solo_en") or ())
        balance_ref, medidas_ref = None, None
        usa_sep = any(cfg_sm.get(k, True) for k in
                      ("balance_referencia", "consola_optimizada", "dinamica_grupos"))
        if path_referencia and usa_sep:
            from .separacion import medidas_por_instrumento
            ref0 = (path_referencia if isinstance(path_referencia, list) else [path_referencia])[0]
            medidas_ref = medidas_por_instrumento(Path(ref0), progreso=avisar)
            if medidas_ref and cfg_sm.get("balance_referencia", True):
                balance_ref = medidas_ref["balance"]
            if medidas_ref is None:
                avisar("⚠ No se pudo medir el balance de la referencia por instrumento "
                       "(separador no instalado o falló): se usa la jerarquía por rol.")
        resultado = sumar_stems(
            Path(carpeta_stems),
            mejorar_percusion=cfg_sm.get("mejorar_percusion", True),
            transient_cant=float(cfg_sm.get("transient_cantidad", 0.3)),
            progreso=progreso,
            separar=claves_eq or None,
            bus_bateria=bool(cfg_sm.get("bus_bateria", True)),
            bajo_dividido=bool(cfg_sm.get("bajo_dividido", True)),
            alinear_fase=bool(cfg_sm.get("alinear_fase", True)),
            filtros_por_rol=bool(cfg_sm.get("filtros_por_rol", True)),
            cadena_voz=bool(cfg_sm.get("cadena_voz", True)),
            estribillos=bool(cfg_sm.get("estribillos", True)),
            desenmascarar=bool(cfg_sm.get("desenmascarar", True)),
            balance_ref=balance_ref, informe=informe_stems, medidas_ref=medidas_ref,
            consola_ml=bool(cfg_sm.get("consola_optimizada", True)),
            dinamica_grupos=bool(cfg_sm.get("dinamica_grupos", True)),
            # con "EQ solo en guitarras", la consola solo ecualiza el grupo "other"
            grupos_eq={"other"} if claves_eq else None)
        if claves_eq:
            audio, sr, grupo_eq, stems_eq = resultado
            if stems_eq:
                avisar(f"EQ solo en: {', '.join(stems_eq)} — voz y batería no se tocan.")
            else:
                grupo_eq = None
                avisar(f"⚠ Ningún stem coincide con {list(claves_eq)}: "
                       "el EQ se aplica a toda la mezcla.")
        else:
            audio, sr = resultado
        nombre_base = "stems"
    else:
        avisar("Cargando mezcla…")
        audio, sr = cargar_audio(Path(path_mezcla))
        nombre_base = Path(path_mezcla).stem
    if audio.shape[1] == 1:
        audio = np.repeat(audio, 2, axis=1)

    def aplicar_eq(proceso):
        """EQ sobre toda la mezcla, o solo sobre el grupo de stems elegido.

        Con grupo (p. ej. las guitarras), el resto de la mezcla pasa intacto:
        mezcla = (mezcla - grupo) + proceso(grupo). Así el matching y los
        notches no le tocan el tono a la voz ni a la batería.
        """
        nonlocal audio, grupo_eq
        if grupo_eq is None:
            audio = proceso(audio)
            return
        procesado = proceso(grupo_eq)
        audio = audio - grupo_eq + procesado
        grupo_eq = procesado

    # Declip ligero (AES 141st Convention, Laguna & Lerch 2016): repara por
    # interpolación cúbica las corridas CORTAS de clipping de la fuente —
    # no toca clipping largo/duro, que no se puede reconstruir de forma
    # confiable (sigue avisándose más abajo/en el diagnóstico de stems).
    audio, muestras_declipeadas = declip_ligero(audio)
    if muestras_declipeadas > 0:
        avisar(f"Declip ligero: {muestras_declipeadas} muestra(s) reparada(s) "
               "por interpolación (clipping corto de la fuente).")

    # Top-and-tail (pendiente URGENTE, tanda real 2026-08-09): recorta
    # silencio real de cabeza/cola antes de cualquier otro proceso.
    largo_previo = audio.shape[0]
    audio, recorte_inicio_s, recorte_fin_s = recortar_silencio_extremos(audio, sr)
    # Para la pantalla de la consola: el espectro y la correlación de la mezcla
    # ANTES de procesar, a la misma resolución que el del master.
    _, esp_entrada = espectro_suavizado(audio, sr, n_puntos=200)
    corr_entrada = analisis_estereo(audio, sr)["correlacion_global"]
    if grupo_eq is not None and audio.shape[0] != largo_previo:
        i0 = int(round(recorte_inicio_s * sr))
        grupo_eq = grupo_eq[i0: i0 + audio.shape[0]]
        if grupo_eq.shape[0] != audio.shape[0]:  # redondeo: se ajusta al largo real
            grupo_eq = np.resize(grupo_eq, audio.shape)
    if recorte_inicio_s > 0 or recorte_fin_s > 0:
        avisar(f"Recortado silencio: {recorte_inicio_s:.2f}s al inicio, "
               f"{recorte_fin_s:.2f}s al final.")

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
            info_notches = {}

            def _notches(x):
                y, info_notches["db"] = _aplicar_notches(
                    x, sr, res,
                    float(cfg_res.get("max_cut_db", 3.0)),
                    float(cfg_res.get("q", 6.0)))
                return y
            aplicar_eq(_notches)
            resonancias_db = info_notches.get("db", [])

    cfg_rd = cfg.get("resonancias_dinamicas", {})
    if cfg_rd.get("activo", False):
        info_rd = {}

        def _dinamicas(x):
            y, info_rd["media_db"] = _resonancias_dinamicas(
                x, sr, float(cfg_rd.get("f_lo", 1000.0)), float(cfg_rd.get("f_hi", 10000.0)),
                float(cfg_rd.get("selectividad_db", 6.0)), float(cfg_rd.get("profundidad", 0.3)),
                float(cfg_rd.get("max_db", 3.0)), float(cfg_rd.get("release_ms", 100.0)))
            return y
        aplicar_eq(_dinamicas)
        avisar(f"Resonancias dinámicas: {info_rd.get('media_db', 0):.1f} dB de corte medio "
               f"en {cfg_rd.get('f_lo', 1000):g}–{cfg_rd.get('f_hi', 10000):g} Hz")

    cfg_ep = cfg.get("eq_perceptual", {})
    if cfg_ep.get("activo", False):
        info_ep = {}

        def _perceptual(x):
            y, info_ep["db"] = _eq_perceptual(x, sr, float(cfg_ep.get("recuperar_db", 2.0)),
                                              float(cfg_ep.get("domar_db", 2.0)))
            return y
        aplicar_eq(_perceptual)
        avisar(f"EQ perceptual: {info_ep.get('db', 0):.1f} dB de ajuste medio (recuperar/domar)")

    cfg_mono = cfg.get("abrir_mono", {})
    if cfg_mono.get("activo", False):
        audio, corr_mono = _abrir_mono(audio, sr, float(cfg_mono.get("correlacion_mono", 0.95)),
                                       float(cfg_mono.get("correlacion_objetivo", 0.7)))
        if corr_mono is not None:
            avisar(f"Mezcla casi mono (correlación {corr_mono:.2f}): se abre en estéreo "
                   "sin cambiar la suma mono")

    # Exciter solo SIN referencia. Medido en test_smoke (mezcla = referencia):
    # con referencia, los armónicos caen en la banda "low", el matching la
    # recorta para compensar y se lleva puesta la fundamental (low −1.8 dB,
    # el master se aleja de la referencia). Con referencia manda el matching.
    cfg_exc = cfg.get("exciter_graves", {})
    if cfg_exc.get("activo", False) and not path_referencia:
        f_lo, f_hi = (float(f) for f in cfg_exc.get("banda_hz", (40.0, 100.0)))
        audio = _exciter_graves(audio, sr, f_lo, f_hi, float(cfg_exc.get("cantidad", 0.25)))
        avisar(f"Exciter de graves: armónicos de {f_lo:g}–{f_hi:g} Hz para parlantes chicos")

    correccion, ajuste_ancho, correccion_side = {}, {}, {}
    aviso_eq_grande = aviso_calidad_ref = None
    segunda_pasada = {}
    modo_eq = None
    nombres_ref, perfil = [], None
    distancia_bandas_db, aviso_referencia = {}, None
    if path_referencia and cfg_eq.get("activo", True):
        refs = path_referencia if isinstance(path_referencia, list) else [path_referencia]
        avisar(f"Analizando {len(refs)} referencia(s) (niveladas, perfil promedio)…")
        l_mix = lufs_integrado(audio, sr)
        perfil = perfil_referencias(refs, l_mix)
        nombres_ref = perfil["nombres"]
        tope = float(cfg_eq.get("max_correccion_db", 4.0))
        corte = perfil.get("corte_agudos_hz")
        if corte and corte < 17000:
            aviso_calidad_ref = (
                f"La referencia se corta cerca de {corte / 1000:.1f} kHz (típico de un MP3 "
                "comprimido): arriba de eso no tiene agudos reales para copiar. "
                "Una versión WAV/FLAC o un MP3 de 320 kbps da un matching más fiel.")
            avisar(f"⚠ {aviso_calidad_ref}")

        # Distancia SIN RECORTAR mix<->referencia por banda (pendiente #4,
        # tanda real 2026-08-09): 13/20 temas no calzaban con la biblioteca
        # (solo había math_rock), medido en 4.6-12.8 dB/banda de distancia —
        # varios sonaron "a nada" o "sin cercanía a la referencia" pese a
        # converger en loudness. No hay atajo para conseguir referencias del
        # estilo correcto, pero sí se puede avisar ANTES de confiar en un
        # matching que no va a sonar a nada.
        distancia_bandas_db = {}
        modo_eq = cfg_eq.get("modo", "ms")
        if modo_eq == "ms" and perfil.get("espectro_mid_db") is None:
            modo_eq = "fino"   # caché de referencia sin datos mid/side

        if modo_eq == "ms":
            # Matching MID/SIDE sobre los tramos fuertes (Consejo 26/9, idea de
            # Matchering): el mid lleva el tono y el side el ancho por banda,
            # así la imagen estéreo también se acerca a la referencia.
            avisar(f"Matching mid/side sobre las partes fuertes (máx ±{tope:g} dB)…")
            freqs, d_mid, d_side, util = _deltas_ms(audio, sr, perfil)
            for b, (f_lo, f_hi) in BANDAS_HZ.items():
                sel = (freqs >= f_lo) & (freqs < f_hi) & util
                distancia_bandas_db[b] = round(float(np.abs(d_mid[sel]).mean()), 1) if sel.any() else 0.0
            grandes = [b for b, (f_lo, f_hi) in BANDAS_HZ.items()
                       if (sel := (freqs >= f_lo) & (freqs < f_hi) & util).any()
                       and float(np.abs(d_mid[sel]).max()) > 6.0]
            if grandes:
                aviso_eq_grande = (
                    f"La referencia pide más de 6 dB en: {', '.join(grandes)}. "
                    "Eso ya no es mastering, es arreglar la mezcla: conviene corregirlo "
                    "en la mezcla o elegir una referencia más parecida.")
                avisar(f"⚠ {aviso_eq_grande}")
            dm = _suavizar(np.clip(d_mid, -tope, tope))
            # el side se limita a ±6 dB aunque el tope del mid sea mayor: más que
            # eso, en una mezcla casi mono, solo levanta ruido y artefactos de
            # fase (mentor, 26/9: >6 dB ya es arreglar la mezcla)
            tope_side = min(tope, float(cfg_eq.get("max_correccion_side_db", 6.0)))
            ds = _suavizar(np.clip(d_side, -tope_side, tope_side))
            # intensidad del matching (A/B del mentor: 50% vs 100%)
            intensidad = float(cfg_eq.get("intensidad", 1.0))
            dm, ds = dm * intensidad, ds * intensidad
            fir_m = _curva_fir_fina(freqs, dm, sr)
            fir_s = _curva_fir_fina(freqs, ds, sr)
            aplicar_eq(lambda x: _aplicar_ms(x, fir_m, fir_s))
            correccion, correccion_side = {}, {}
            for b, (f_lo, f_hi) in BANDAS_HZ.items():
                sel = (freqs >= f_lo) & (freqs < f_hi)
                correccion[b] = round(float(dm[sel].mean()), 1) if sel.any() else 0.0
                correccion_side[b] = round(float(ds[sel].mean()), 1) if sel.any() else 0.0
        elif modo_eq == "fino":
            # Matching espectral FINO: curva completa a 1/3 de octava
            avisar(f"Matching espectral fino (1/3 octava, máx ±{tope:g} dB)…")
            freqs, esp_mix = espectro_suavizado(audio, sr)
            esp_ref = np.asarray(perfil["espectro_db"])
            # Por encima de F_MAX_MATCH_HZ ni la mezcla ni un MP3 de referencia
            # suelen tener contenido real (them_bones2: -140 dB a 19 kHz). Medir
            # ahí inflaba la distancia de aire con 14.8 dB falsos y empujaba el
            # EQ a levantar ruido: esa zona queda fuera del matching.
            util = freqs <= F_MAX_MATCH_HZ
            delta_sin_tope = esp_ref - esp_mix
            delta_sin_tope = delta_sin_tope - float(np.mean(delta_sin_tope[util]))  # solo forma, no nivel
            delta_sin_tope[~util] = 0.0
            for b, (f_lo, f_hi) in BANDAS_HZ.items():
                sel = (freqs >= f_lo) & (freqs < f_hi) & util
                distancia_bandas_db[b] = round(float(np.abs(delta_sin_tope[sel]).mean()), 1) if sel.any() else 0.0
            delta = np.clip(delta_sin_tope, -tope, tope)
            delta = np.convolve(delta, [0.25, 0.5, 0.25], mode="same")  # suaviza
            fir_fino = _curva_fir_fina(freqs, delta, sr)
            aplicar_eq(lambda x: _aplicar_fir(x, fir_fino))
            # resumen por banda para el reporte
            correccion = {}
            for b, (f_lo, f_hi) in BANDAS_HZ.items():
                sel = (freqs >= f_lo) & (freqs < f_hi)
                correccion[b] = round(float(delta[sel].mean()), 1) if sel.any() else 0.0
        else:
            # Modo clásico: EQ correctivo de 7 bandas
            bandas_mix = balance_bandas_db(audio, sr)
            distancia_bandas_db = {
                b: round(float(abs(perfil["bandas_db"][b] - bandas_mix[b])), 1) for b in BANDAS_HZ
            }
            correccion = {
                b: round(float(np.clip(perfil["bandas_db"][b] - bandas_mix[b], -tope, tope)), 1)
                for b in BANDAS_HZ
            }
            avisar(f"Aplicando EQ correctivo 7 bandas (máx ±{tope:g} dB)…")
            fir_bandas = _curva_fir(correccion, sr)
            aplicar_eq(lambda x: _aplicar_fir(x, fir_bandas))

        distancia_media_db = round(float(np.mean(list(distancia_bandas_db.values()))), 1) if distancia_bandas_db else 0.0
        aviso_referencia = None
        if distancia_media_db >= 4.6:
            peor_banda = max(distancia_bandas_db, key=distancia_bandas_db.get)
            aviso_referencia = (
                f"La(s) referencia(s) elegida(s) están lejos del timbre de tu mezcla "
                f"(distancia media {distancia_media_db:.1f} dB/banda, peor en «{peor_banda}» "
                f"con {distancia_bandas_db[peor_banda]:.1f} dB). En tu tanda real, distancias "
                "así (4.6-12.8 dB/banda) sonaron \"a nada\" o \"sin cercanía a la referencia\" "
                "pese a converger en loudness — considerá buscar una referencia más parecida "
                "en estilo/instrumentación."
            )
            log.warning(aviso_referencia)
            avisar(f"⚠ {aviso_referencia}")

        # Imagen estéreo: acerca el ancho por banda al promedio de referencias
        if modo_eq != "ms" and cfg_eq.get("analizar_imagen_stereo", True):
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
        rango_ref = None
        if cfg_multi.get("modo", "rango") == "rango" and path_referencia:
            try:
                refs_mb = path_referencia if isinstance(path_referencia, list) else [path_referencia]
                medidas = [rango_corto_por_banda(*cargar_audio(Path(r))) for r in refs_mb]
                rango_ref = {b: float(np.mean([m[b] for m in medidas])) for b in medidas[0]}
            except Exception:
                log.exception("No se pudo medir la dinámica por banda de la referencia")
        if rango_ref:
            audio, multibanda_db = _multibanda_rango(audio, sr, rango_ref, cfg_multi)
        else:
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

    # Bus (ítem 13) DESPUÉS del EQ: es no lineal, y si se aplicara antes, el
    # "mezcla - grupo + EQ(grupo)" del EQ solo en guitarras restaría unas
    # guitarras crudas de una mezcla ya comprimida y saturada.
    cfg_bus = cfg.get("bus_master", {})
    if cfg_bus.get("activo", False):
        tipo = str(cfg_bus.get("saturacion", "cinta"))
        audio, red_bus = _bus_master(audio, sr, tipo, float(cfg_bus.get("drive", 1.3)))
        avisar(f"Bus: pegamento 2:1 ({red_bus:.1f} dB) + saturación {tipo}")

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
            audio = _a_2x(_soft_clip, audio, drive)
            densidad_aplicada = True
            lufs_actual = lufs_integrado(audio, sr)

    # Loudness con convergencia: el limitador come nivel al empujar fuerte,
    # así que se itera (normalizar → clipper → limitar → medir) hasta el target.
    # El clipper recorta solo picos → el limitador trabaja poco → sin bombeo.
    cfg_clip = cfg.get("clipper", {})

    # SEGURIDAD, y va ANTES del bucle a propósito: el bucle puede salir por
    # convergencia sin haber limitado nunca (si el audio ya venía en target),
    # y entonces nada garantiza el techo de true peak. Bug real (2026-08-09):
    # "Good Mornig SIN MEZCLA" salió a +0.2 dBTP CON clipping y tardó 40 s
    # contra 100-500 s de los demás, justamente porque se saltó el limitador.
    # Poniéndola acá y no después, todas las mediciones del bucle son
    # POST-limitador: el bucle converge al loudness que realmente va a salir.
    # Con la pasada al final, el limitador se comía ~0.3 LU después de la
    # última medición y nadie los compensaba — de ahí el sesgo sistemático de
    # la tanda del 2026-08-09 (18 de 20 por debajo, media -9.33 con target -9).
    # El limitador solo toca lo que pasa el techo: si no hay nada, es un no-op.
    pre_volumen = audio.copy()  # para los medidores de limitación (ítem 14)
    avisar(f"Limitando picos — pasada de seguridad (techo {cfg_lim['ceiling_dbtp']:g} dBTP)…")
    audio = _limitador(audio, sr, cfg_lim)

    avisar(f"Normalizando a {target_lufs} LUFS (con convergencia)…")
    # 6 pasadas (antes 4): el limitador de 2 etapas reduce algo más de nivel
    # por pasada que el de 1 etapa — necesita 1-2 vueltas más para converger.
    # Tolerancia 0.15 LU (antes 0.3): con 0.3 el bucle cortaba apenas entraba
    # en ventana y, como el limitador SIEMPRE come nivel, el resultado caía
    # sistemáticamente por debajo — 18 de 20 masters de la tanda del
    # 2026-08-09 quedaron bajos, media -9.33 con target -9.0.
    tol_lufs = 0.15
    # Compensación predictiva: en vez de gastar pasadas extra persiguiendo lo
    # que el limitador se come, se le suma a la ganancia lo que se comió en la
    # pasada anterior. Converge en 1-2 vueltas en vez de 4-6 (cada pasada del
    # limitador cuesta ~45 s en un tema largo).
    perdida_prev = 0.0
    mejor: tuple[float, np.ndarray] | None = None
    for intento in range(6):
        lufs_actual = lufs_integrado(audio, sr)
        if not np.isfinite(lufs_actual):
            break
        diff = target_lufs - lufs_actual
        if mejor is None or abs(diff) < mejor[0]:
            mejor = (abs(diff), audio)
        if abs(diff) <= tol_lufs:
            break
        ganancia = diff + perdida_prev
        esperado = lufs_actual + ganancia
        audio = audio * 10 ** (ganancia / 20)
        if cfg_clip.get("activo", True):
            umbral_clip = float(cfg_clip.get("umbral_dbfs", -0.5))
            if cfg_clip.get("solo_transitorios", True):
                audio = _clipper_transitorios(audio, sr, umbral_clip)
            else:
                audio = _a_2x(_clipper, audio, umbral_clip)
        avisar(f"Limitando picos (techo {cfg_lim['ceiling_dbtp']:g} dBTP, pasada {intento + 1})…")
        audio = _limitador(audio, sr, cfg_lim)
        lufs_post = lufs_integrado(audio, sr)
        if np.isfinite(lufs_post):
            # tope de 2 LU: si se comió más que eso no fue el limitador
            # afinando, es material que no da — que lo diga el warning de
            # no-convergencia y no que dispare la ganancia en la vuelta siguiente
            perdida_prev = float(np.clip(esperado - lufs_post, 0.0, 2.0))

    # Quedarse con la pasada más cercana al target: subir de más y volver a
    # limitar puede alejar en vez de acercar, y en ese caso la vuelta anterior
    # era mejor master (mismo loudness, menos limitador encima).
    lufs_fin = lufs_integrado(audio, sr)
    if (mejor is not None and np.isfinite(lufs_fin)
            and abs(target_lufs - lufs_fin) > mejor[0]):
        audio = mejor[1]

    # Aviso de no-convergencia: si tras las 6 pasadas sigue lejos del target,
    # el material no da para ese loudness sin machacarse (pasó con "Hasta mis
    # ultimos dias": target -9, quedó en -10.0 con el crest aplastado a 5.8).
    lufs_tras_bucle = lufs_integrado(audio, sr)
    convergio = bool(np.isfinite(lufs_tras_bucle)
                     and abs(target_lufs - lufs_tras_bucle) <= 0.5)
    if not convergio:
        log.warning("No convergió al target: %.1f LUFS pedido, %.1f real — "
                    "el material no da para ese loudness sin comprimir de más",
                    target_lufs, lufs_tras_bucle)

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

    # Segunda pasada de matching (Consejo + mentor, 26/9): el clipper, la
    # densidad y el limitador cambian el agudo y dejan un residuo contra la
    # referencia. Una corrección suave (≤ max dB) lo cierra; después, limitador
    # y ajuste fino de loudness otra vez. No corre si el EQ se aplicó solo a
    # las guitarras: después del limitador la mezcla ya no se puede separar.
    max_2p = float(cfg_eq.get("segunda_pasada_max_db", 2.0))
    if (modo_eq == "ms" and grupo_eq is None and max_2p > 0
            and cfg_eq.get("segunda_pasada", True)):
        avisar(f"Segunda pasada de matching (residuo, máx ±{max_2p:g} dB)…")
        freqs2, r_mid, r_side, util2 = _deltas_ms(audio, sr, perfil)
        rm = _suavizar(np.clip(r_mid, -max_2p, max_2p))
        rs = _suavizar(np.clip(r_side, -max_2p, max_2p))
        audio = _aplicar_ms(audio, _curva_fir_fina(freqs2, rm, sr), _curva_fir_fina(freqs2, rs, sr))
        for b, (f_lo, f_hi) in BANDAS_HZ.items():
            sel = (freqs2 >= f_lo) & (freqs2 < f_hi)
            segunda_pasada[b] = round(float(rm[sel].mean()), 1) if sel.any() else 0.0
        audio = _limitador(audio, sr, cfg_lim)
        l2 = lufs_integrado(audio, sr)
        if np.isfinite(l2) and abs(target_lufs - l2) > tol_lufs:
            audio = _limitador(audio * 10 ** ((target_lufs - l2) / 20), sr, cfg_lim)

    lufs_final = lufs_integrado(audio, sr)
    tp_final = true_peak_db(audio, sr)
    crest_final = crest_factor_db(audio)

    # Aviso de sobre-limitación / sub-procesamiento (pendiente #2, tanda real
    # 2026-08-09): umbrales MEDIDOS de 22 votos reales de Bruno, no teoría —
    # zona sana ~10 dB de crest; <6 lo rechazó como "machacado", >12 como
    # "casi no noto diferencia".
    aviso_crest = None
    if crest_final < 6.0:
        aviso_crest = (f"Crest final {crest_final:.1f} dB, por debajo de 6 dB. "
                       "En tus votos reales rechazaste masters así por \"machacados\" "
                       "— considerá bajar la ganancia de entrada o aflojar el limitador.")
    elif crest_final > 12.0:
        aviso_crest = (f"Crest final {crest_final:.1f} dB, por encima de 12 dB. "
                       "En tus votos reales rechazaste masters así por \"casi no noto "
                       "diferencia\" — el master puede estar sub-procesado para el "
                       "target pedido.")
    if aviso_crest:
        log.warning(aviso_crest)
        avisar(f"⚠ {aviso_crest}")

    limitacion, aviso_limitacion = {}, None
    try:
        limitacion = _medir_limitacion(pre_volumen, audio, sr)
    except Exception:
        log.exception("No se pudieron medir bombeo/distorsión")
    del pre_volumen
    partes = []
    if limitacion.get("bombeo"):
        partes.append("el limitador bombea con el grave (los medios bajan en cada "
                      f"golpe, correlación {limitacion['bombeo_corr']:+.2f})")
    if limitacion.get("distorsion_db", -99) > -30:
        partes.append(f"la limitación agrega distorsión ({limitacion['distorsion_db']:.0f} dB "
                      "respecto de la señal)")
    if partes:
        aviso_limitacion = ("Etapa de volumen: " + "; ".join(partes)
                            + ". Probar un objetivo de LUFS más bajo.")
        avisar(f"⚠ {aviso_limitacion}")

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

    # MP3 (MPEG-1/2/2.5) solo soporta ciertos sample rates. Si el original no
    # es uno de ellos (ej. 96000, 88200), se resamplea SOLO para el MP3 — el
    # WAV master queda intacto en el sample rate original.
    if sr in SR_MP3_VALIDOS:
        sf.write(str(out_mp3), audio, sr)
    else:
        sr_mp3 = 48000 if sr > 44100 else 44100
        from math import gcd
        g = gcd(sr_mp3, sr)
        audio_mp3 = signal.resample_poly(audio, sr_mp3 // g, sr // g, axis=0)
        sf.write(str(out_mp3), audio_mp3, sr_mp3)

    # Vista previa de códec (ítem 12): el MP3 decodificado puede tener picos
    # más altos que el WAV (el códec deforma la onda). Se mide lo que de
    # verdad va a sonar en un reproductor.
    tp_mp3, aviso_codec = None, None
    try:
        dec, sr_dec = sf.read(str(out_mp3), always_2d=True)
        tp_mp3 = round(float(true_peak_db(dec, sr_dec)), 2)
        if tp_mp3 > -0.1:
            aviso_codec = (f"El MP3 decodificado llega a {tp_mp3:+.2f} dBTP: puede distorsionar "
                           "en Spotify/YouTube. Bajar el techo del limitador (p. ej. -1.5 dBTP).")
            avisar(f"⚠ {aviso_codec}")
    except Exception:
        log.exception("No se pudo medir el MP3 decodificado")

    # espectro del master final (alta resolución) para la gráfica pre/post
    freqs_out, esp_out = espectro_suavizado(audio, sr, n_puntos=200)

    # Referencia a la misma resolución (la del caché es de 31 puntos): se lee
    # una vez más el archivo, solo para dibujarla junto a mezcla y master.
    esp_ref_200 = None
    if nombres_ref and path_referencia:
        try:
            ref0 = (path_referencia if isinstance(path_referencia, list) else [path_referencia])[0]
            a_ref, sr_ref = cargar_audio(Path(ref0))
            _, esp_ref_200 = espectro_suavizado(a_ref, sr_ref, n_puntos=200)
        except Exception:
            log.exception("No se pudo calcular el espectro de la referencia para la pantalla")

    # Envolvente L/R (dB RMS, 10 por segundo) para las barras LED: el
    # recorrido real del master, no una animación inventada.
    paso = max(1, sr // 10)
    n_fr = audio.shape[0] // paso
    env = []
    if n_fr:
        bloques = audio[: n_fr * paso].reshape(n_fr, paso, audio.shape[1])
        rms = np.sqrt(np.mean(bloques ** 2, axis=1) + 1e-12)
        env = np.round(20 * np.log10(rms), 1)
        if env.shape[1] == 1:
            env = np.repeat(env, 2, axis=1)
        if len(env) > 3000:
            env = env[np.linspace(0, len(env) - 1, 3000).astype(int)]
        env = env.tolist()

    resumen = {
        "wav": str(out_wav),
        "mp3": str(out_mp3),
        "lufs_final": round(float(lufs_final), 1),
        "true_peak_final": round(tp_final, 1),
        "crest_final": round(crest_final, 1),
        "espectro_master": {
            "freqs": [round(float(f), 1) for f in freqs_out],
            "db": [round(float(d), 1) for d in esp_out],
        },
        "espectro_mezcla": [round(float(d), 1) for d in esp_entrada],
        "espectro_referencia": ([round(float(d), 1) for d in esp_ref_200]
                                if esp_ref_200 is not None else None),
        "correlacion_mezcla": round(float(corr_entrada), 2),
        "correlacion_master": round(float(analisis_estereo(audio, sr)["correlacion_global"]), 2),
        "envolvente_lr": env,
        "target_lufs": target_lufs,
        "recorte_silencio_s": {"inicio": recorte_inicio_s, "fin": recorte_fin_s},
        "muestras_declipeadas": muestras_declipeadas,
        "eq_aplicado_db": correccion,
        "ajuste_ancho_db": ajuste_ancho,
        "multibanda_db": multibanda_db,
        "resonancias_db": resonancias_db,
        "transient_shaping": round(transient_cant, 2) if transient_cant else None,
        "dinamica_macro": dinamica_aplicada,
        "densidad_aplicada": densidad_aplicada,
        # False = el material no llegó al loudness pedido sin machacarse;
        # la UI puede avisar en vez de entregar un master aplastado en silencio.
        "convergio_target": convergio,
        "aviso_crest_fuera_zona": aviso_crest,
        "distancia_referencia_db": distancia_bandas_db,
        "aviso_referencia_no_calza": aviso_referencia,
        "mono_bass_hz": mono_bass_hz,
        "fuente": "stems" if carpeta_stems else "mezcla",
        "genero": genero,
        "eq_solo_en": stems_eq if grupo_eq is not None else [],
        "balance_referencia": informe_stems.get("balance_referencia"),
        "consola_optimizada": informe_stems.get("consola_optimizada"),
        "dinamica_grupos": informe_stems.get("dinamica_grupos"),
        "modo_eq": modo_eq,
        "eq_side_db": correccion_side,
        "segunda_pasada_db": segunda_pasada,
        "aviso_eq_grande": aviso_eq_grande,
        "aviso_referencia_calidad": aviso_calidad_ref,
        "true_peak_mp3_dbtp": tp_mp3,
        "aviso_codec": aviso_codec,
        "limitacion": limitacion,
        "aviso_limitacion": aviso_limitacion,
        "referencias": nombres_ref,
        "score": score,
    }
    avisar("Master listo.")
    log.info("Master: %s", resumen)
    return resumen
