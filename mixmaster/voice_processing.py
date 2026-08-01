"""Motor de procesamiento de voz/podcast.

Cadena DISTINTA a la de música (`processing.py::masterizar`): sin multibanda
por referencia, sin imagen estéreo. Sí: puerta de ruido (gate), compresión
suave de voz, de-esser, limitador, y un matching tonal opcional hacia una
referencia — usa el mismo matching FINO de 1/3 de octava que música (curva
completa, no 7 bloques), con tope más generoso (±6 dB) porque el gap real
entre una toma cruda y una referencia ya masterizada suele ser grande.
Diseño acordado con el usuario, ver config/roadmap.md "Modo Voz/Podcast".

Nota honesta de alcance: NO es streaming por bloques desde disco (la cadena
es liviana — sin copias multibanda — así que cargar completo en memoria ya es
seguro incluso para 1h+ mono/estéreo, sin el riesgo de memoria documentado
para el motor musical). Si en el futuro hace falta audio de varias horas, ahí
sí conviene streaming real.
"""

import json
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy import signal

from .audio_analysis import (
    BANDAS_HZ, cargar_audio, crest_factor_db, espectro_suavizado,
    lufs_integrado, true_peak_db,
)
from .logger import get_logger
from .processing import _aplicar_fir, _comprimir_banda, _curva_fir_fina, _limitador

log = get_logger("mixmaster.voice")

CONFIG_VOZ_DEFAULT = {
    # sugeridos por estándar de plataformas de podcast; ajustables por el usuario
    "target_lufs_mono": -16.0,
    "target_lufs_stereo": -19.0,
    "gate": {
        # expansor descendente: atenúa lo que queda por DEBAJO del umbral
        # (ruido de fondo entre frases), no toca la voz por encima de él
        "activo": True,
        "umbral_db": -45.0,
        "ratio": 4.0,
        "attack_ms": 5.0,
        "release_ms": 150.0,
    },
    "compresor": {
        "activo": True,
        "umbral_db": -22.0,
        "ratio": 2.5,
        "attack_ms": 8.0,
        "release_ms": 120.0,
    },
    "de_esser": {
        # comprime SOLO la banda de sibilancia (s/sh/ch), el resto intacto
        "activo": True,
        "f_lo": 5000.0,
        "f_hi": 9000.0,
        "umbral_db": -24.0,
        "ratio": 3.0,
        "attack_ms": 3.0,
        "release_ms": 60.0,
    },
    "match_referencia": {
        # matching tonal SUAVE hacia una referencia de voz (opcional). Mucho
        # más conservador que el de música (±2 dB vs ±4) y por 7 bandas, no
        # 1/3 de octava: en voz una curva fina copia el timbre de OTRA persona
        # y suena artificial — acá solo se busca acercar presencia/brillo.
        "activo": True,
        # 2026-08-01: subido de 2.0 a 6.0. Con ±2 el matching contra una
        # referencia de voz real (podcast) quedaba muy corto — el gap típico
        # entre una toma cruda con antipop (menos efecto de proximidad) y una
        # referencia ya masterizada puede ser de +7 dB en graves. Validado
        # con audio real de Bruno: 5 de 7 bandas topeaban en ±2, la voz
        # procesada terminaba "distinta" a la referencia, no parecida.
        "max_correccion_db": 6.0,
        # Solo "sub" (20-60 Hz) se restringe a bajar nunca subir: ahí no hay
        # cuerpo de voz real, solo rumble/ruido de manejo — subirlo no suma
        # calidez, solo mete barro. "low" (60-200 Hz) SÍ puede subir: es
        # justo el rango de cuerpo/calidez de la voz (efecto de proximidad),
        # y es la banda que más gap mostró en la prueba real.
        "solo_cortar": ("sub",),
    },
    "limitador": {
        "ceiling_dbtp": -1.0,
        "release_ms": 60,
        "lookahead_ms": 5,
    },
}


def cargar_config_voz() -> dict:
    return json.loads(json.dumps(CONFIG_VOZ_DEFAULT))


def _match_referencia(audio: np.ndarray, sr: int, path_ref: Path,
                      cfg_match: dict) -> tuple[np.ndarray, dict]:
    """Acerca el balance tonal de la voz al de una referencia.

    Usa la misma curva FINA de 1/3 de octava que el modo música por defecto
    (`espectro_suavizado` + `_curva_fir_fina`), no un promedio grosero de 7
    bandas — mucho más preciso para "sonar parecido" a una referencia real
    (2026-08-01: antes usaba 7 bandas, se subió a la curva fina tras probar
    con audio real y ver que el matching grueso no se acercaba lo suficiente).
    `_curva_fir_fina`/`_aplicar_fir` son FIR de fase LINEAL con retardo
    compensado, así que se trasplantan bien a voz (no introduce el problema
    de causalidad que sí tenía el detector del gate — ver "Reglas de
    trabajo" en config/roadmap.md).

    Devuelve (audio, correccion_db_por_banda) — el resumen de 7 bandas es
    solo para mostrar en el reporte; el EQ real aplicado es la curva fina
    completa (~30 puntos), más preciso que lo que ese resumen muestra.
    """
    tope = float(cfg_match.get("max_correccion_db", 6.0))
    solo_cortar = tuple(cfg_match.get("solo_cortar", ("sub",)))

    ref, sr_ref = cargar_audio(Path(path_ref))
    # nivela la referencia al loudness de la voz: si no, la diferencia de
    # volumen se lee como diferencia de timbre y el EQ sale todo para un lado
    l_voz, l_ref = lufs_integrado(audio, sr), lufs_integrado(ref, sr_ref)
    if np.isfinite(l_voz) and np.isfinite(l_ref):
        ref = ref * 10 ** ((l_voz - l_ref) / 20)

    freqs, esp_voz = espectro_suavizado(audio, sr)
    _, esp_ref = espectro_suavizado(ref, sr_ref)
    delta = esp_ref - esp_voz
    delta = delta - float(np.mean(delta))       # solo forma, no nivel
    delta = np.clip(delta, -tope, tope)

    # Bandas restringidas a solo-cortar (ej. "sub" = rumble, no cuerpo de
    # voz): en los puntos de la curva que caen ahí, nunca se sube.
    for banda in solo_cortar:
        f_lo, f_hi = BANDAS_HZ[banda]
        sel = (freqs >= f_lo) & (freqs < f_hi)
        delta[sel] = np.minimum(delta[sel], 0.0)

    delta = np.convolve(delta, [0.25, 0.5, 0.25], mode="same")  # suaviza

    correccion = {}
    for banda, (f_lo, f_hi) in BANDAS_HZ.items():
        sel = (freqs >= f_lo) & (freqs < f_hi)
        correccion[banda] = round(float(delta[sel].mean()), 1) if sel.any() else 0.0

    if all(abs(v) < 0.1 for v in correccion.values()):
        return audio, {}
    return _aplicar_fir(audio, _curva_fir_fina(freqs, delta, sr)), correccion


def _gate(audio: np.ndarray, sr: int, cfg_gate: dict) -> np.ndarray:
    """Expansor descendente: reduce lo que está por debajo del umbral."""
    umbral_db = float(cfg_gate.get("umbral_db", -45.0))
    ratio = float(cfg_gate.get("ratio", 4.0))
    attack_ms = float(cfg_gate.get("attack_ms", 5.0))
    release_ms = float(cfg_gate.get("release_ms", 150.0))

    mono = np.max(np.abs(audio), axis=1)
    tau = max((attack_ms + release_ms) / 2 / 1000 * sr, 1.0)
    alpha = float(np.exp(-1.0 / tau))
    # CAUSAL (lfilter, no filtfilt): un gate no puede "ver el futuro" — con
    # filtro de fase cero, la sílaba siguiente se filtraba hacia atrás en el
    # tiempo y el hueco entre palabras nunca llegaba a cerrar.
    power = signal.lfilter([1 - alpha], [1.0, -alpha], mono ** 2)
    env_db = 10.0 * np.log10(np.maximum(power, 1e-12))

    bajo = np.maximum(umbral_db - env_db, 0.0)   # dB por debajo del umbral
    gan_db = -bajo * (1.0 - 1.0 / ratio)
    gan = 10 ** (gan_db / 20.0)
    return audio * gan[:, np.newaxis]


def _compresor_voz(audio: np.ndarray, sr: int, cfg_comp: dict) -> np.ndarray:
    umbral_db = float(cfg_comp.get("umbral_db", -22.0))
    ratio = float(cfg_comp.get("ratio", 2.5))
    attack_ms = float(cfg_comp.get("attack_ms", 8.0))
    release_ms = float(cfg_comp.get("release_ms", 120.0))
    comp = _comprimir_banda(audio, sr, ratio, umbral_db, attack_ms, release_ms)
    rms_pre = float(np.sqrt(np.mean(audio ** 2)))
    rms_post = float(np.sqrt(np.mean(comp ** 2)))
    if rms_post > 0:
        comp = comp * (rms_pre / rms_post)   # makeup: conserva el RMS previo
    return comp


def _de_esser(audio: np.ndarray, sr: int, cfg_de: dict) -> np.ndarray:
    f_lo = float(cfg_de.get("f_lo", 5000.0))
    f_hi = float(cfg_de.get("f_hi", 9000.0))
    umbral_db = float(cfg_de.get("umbral_db", -24.0))
    ratio = float(cfg_de.get("ratio", 3.0))
    attack_ms = float(cfg_de.get("attack_ms", 3.0))
    release_ms = float(cfg_de.get("release_ms", 60.0))

    nyq = sr / 2.0
    f_hi = min(f_hi, nyq * 0.98)
    sos = signal.butter(4, [f_lo, f_hi], btype="band", fs=sr, output="sos")
    banda = signal.sosfiltfilt(sos, audio, axis=0)
    banda_comp = _comprimir_banda(banda, sr, ratio, umbral_db, attack_ms, release_ms)
    return audio - banda + banda_comp


def procesar_voz(path_entrada: Path, path_salida: Path, cfg: dict | None = None,
                 path_referencia: Path | None = None, target_lufs: float | None = None,
                 progreso=None) -> dict:
    """Pipeline de voz/podcast. Entrada: WAV/MP3/etc. mono o estéreo.

    `cfg` opcional (ver CONFIG_VOZ_DEFAULT); si no, usa los defaults.
    `path_referencia` opcional: matching tonal suave hacia esa voz.
    `target_lufs` opcional: si no se pasa, usa el default según mono/estéreo.
    Devuelve resumen con ruta, LUFS/true-peak/crest final.
    """
    def avisar(msg):
        log.info(msg)
        if progreso:
            progreso(msg)

    if cfg is None:
        cfg = cargar_config_voz()

    avisar("Cargando audio…")
    audio, sr = cargar_audio(Path(path_entrada))
    es_mono = audio.shape[1] == 1

    if target_lufs is None:
        target_lufs = float(cfg.get(
            "target_lufs_mono" if es_mono else "target_lufs_stereo",
            CONFIG_VOZ_DEFAULT["target_lufs_mono" if es_mono else "target_lufs_stereo"]))
    else:
        target_lufs = float(target_lufs)

    # Matching tonal PRIMERO: la cadena dinámica (gate/comp/de-esser) trabaja
    # después sobre el timbre ya corregido, igual que en el motor musical
    correccion_db = {}
    cfg_match = cfg.get("match_referencia", {})
    if path_referencia and cfg_match.get("activo", True):
        avisar("Matching tonal suave hacia la referencia…")
        audio, correccion_db = _match_referencia(audio, sr, Path(path_referencia), cfg_match)
        if correccion_db:
            avisar(f"EQ hacia la referencia (dB): {correccion_db}")

    if cfg.get("gate", {}).get("activo", True):
        avisar("Puerta de ruido (reduce silencios/fondo)…")
        audio = _gate(audio, sr, cfg["gate"])

    if cfg.get("compresor", {}).get("activo", True):
        avisar("Compresión suave de voz…")
        audio = _compresor_voz(audio, sr, cfg["compresor"])

    if cfg.get("de_esser", {}).get("activo", True):
        avisar("De-esser (sibilancia)…")
        audio = _de_esser(audio, sr, cfg["de_esser"])

    cfg_lim = cfg.get("limitador", CONFIG_VOZ_DEFAULT["limitador"])
    avisar(f"Normalizando a {target_lufs:g} LUFS (con convergencia)…")
    for intento in range(6):
        lufs_actual = lufs_integrado(audio, sr)
        if not np.isfinite(lufs_actual):
            break
        diff = target_lufs - lufs_actual
        if abs(diff) <= 0.3:
            break
        audio = audio * 10 ** (diff / 20)
        avisar(f"Limitando picos (pasada {intento + 1})…")
        audio = _limitador(audio, sr, cfg_lim)

    lufs_final = lufs_integrado(audio, sr)
    tp_final = true_peak_db(audio, sr)
    crest_final = crest_factor_db(audio)

    path_salida = Path(path_salida)
    path_salida.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path_salida), audio, sr, subtype="PCM_24")

    avisar("Procesamiento de voz listo.")
    resumen = {
        "wav": str(path_salida),
        "mono": es_mono,
        "target_lufs": target_lufs,
        "lufs_final": round(float(lufs_final), 2) if np.isfinite(lufs_final) else None,
        "true_peak_final": round(float(tp_final), 2),
        "crest_final": round(float(crest_final), 2),
        "eq_referencia_db": correccion_db,
        "referencia": Path(path_referencia).name if path_referencia else None,
    }
    log.info("Voz: %s", resumen)
    return resumen
