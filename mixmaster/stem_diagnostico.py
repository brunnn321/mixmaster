"""Diagnóstico por stem (v0.9+): analiza CADA stem por separado y genera
observaciones accionables — el diferenciador "coaching" de MixMaster.

No masteriza ni procesa: solo mira cada stem y te dice qué mejorar en tu
mezcla, en lenguaje directo ("tu bajo no tiene definición en 250 Hz").

Reglas por tipo de instrumento (deducido del nombre del archivo):
  - bajo   → definición de medios (growl 150-400 Hz) vs sub
  - batería→ pegada (crest) y balance de graves
  - guitarra→ acumulación en low-mid (barro), presencia
  - genérico→ mono/estéreo, nivel, rango dinámico
"""

from pathlib import Path

import numpy as np
from scipy import signal as _sp_signal

from .audio_analysis import (
    BANDAS_HZ, _filtrar_banda, balance_bandas_db, cargar_audio, crest_factor_db,
    detectar_clipping, true_peak_db,
)
from .logger import get_logger

log = get_logger("mixmaster.stem_diagnostico")

FORMATOS = (".wav", ".mp3", ".flac", ".ogg", ".aiff", ".aif")

_BAJO = ("bass", "bajo", "sub", "808")
_BATERIA = ("drum", "bater", "kick", "bombo", "snare", "caja", "tom", "perc", "hat", "plato", "od", "oh")
_GUITARRA = ("gtr", "guit", "guitar", "riff")
_VOZ = ("voc", "voz", "vox", "lead vox", "coro")


def _tipo(nombre: str) -> str:
    n = nombre.lower()
    if any(k in n for k in _BAJO):
        return "bajo"
    if any(k in n for k in _BATERIA):
        return "bateria"
    if any(k in n for k in _GUITARRA):
        return "guitarra"
    if any(k in n for k in _VOZ):
        return "voz"
    return "generico"


def _rms_db(audio: np.ndarray) -> float:
    r = float(np.sqrt(np.mean(audio ** 2)))
    return 20 * np.log10(max(r, 1e-9))


def _correlacion(audio: np.ndarray) -> float:
    if audio.shape[1] < 2:
        return 1.0
    L, R = audio[:, 0], audio[:, 1]
    if np.std(L) < 1e-9 or np.std(R) < 1e-9:
        return 1.0
    return float(np.corrcoef(L, R)[0, 1])


def diagnosticar_stem(path: Path) -> dict:
    """Analiza un stem y devuelve {nombre, tipo, bandas, crest, obs:[...]}."""
    path = Path(path)
    audio, sr = cargar_audio(path)
    bandas = balance_bandas_db(audio, sr)
    crest = crest_factor_db(audio)
    corr = _correlacion(audio)
    tp = true_peak_db(audio, sr)
    tiene_clipping = detectar_clipping(audio)
    tipo = _tipo(path.stem)
    obs = []

    # --- reglas por tipo ---
    if tipo == "bajo":
        growl = bandas.get("low_mid", -99)   # 200-500 Hz: donde se "entiende" el bajo
        peso = bandas.get("low", -99)         # 60-200 Hz: cuerpo
        if growl - peso < -6:
            obs.append(("⚠", "Tu bajo pesa pero no se define: falta growl en 150-400 Hz. "
                             "Subí esa zona o meté saturación de medios para que se entienda la nota."))
        elif growl - peso > 8:
            obs.append(("·", "Bajo con buena definición de medios."))
        if bandas.get("sub", -99) - peso > 6:
            obs.append(("⚠", "Mucho sub (<60 Hz) sin cuerpo — puede sonar 'bola'. Bajá sub o subí 80-120 Hz."))

    elif tipo == "bateria":
        if crest < 8:
            obs.append(("⚠", f"Batería aplastada (crest {crest:.1f} dB) — ya viene muy comprimida. "
                             "Dejá los transientes más vivos en la mezcla."))
        else:
            obs.append(("·", f"Batería con pegada sana (crest {crest:.1f} dB)."))
        if bandas.get("high", -99) < bandas.get("mid", -99) - 12:
            obs.append(("⚠", "Platos/aire flojos — le falta brillo arriba (6-10 kHz)."))

    elif tipo == "guitarra":
        barro = bandas.get("low_mid", -99)
        cuerpo = bandas.get("mid", -99)
        if barro - cuerpo > 3:
            obs.append(("⚠", "Guitarra embarrada en 200-500 Hz — hacé un corte ahí para limpiar."))
        if bandas.get("high_mid", -99) - cuerpo > 6:
            obs.append(("⚠", "Presencia dura en 2-5 kHz — puede fatigar. Suavizá si se acumula con otras guitarras."))

    elif tipo == "voz":
        if bandas.get("low", -99) - bandas.get("mid", -99) > -6:
            obs.append(("⚠", "Voz con graves de más (proximidad) — highpass en 80-120 Hz."))

    # --- reglas generales (todos) ---
    if corr < 0.3 and audio.shape[1] >= 2:
        obs.append(("⚠", f"Imagen muy ancha/fuera de fase (corr {corr:.2f}) — riesgo en mono."))
    if _rms_db(audio) < -30:
        obs.append(("·", "Stem muy bajo de nivel — normal si es un elemento de apoyo."))

    # --- headroom, clipping y sobre-procesado (stem ajeno: no confiar en que
    # venga limpio — ver caso real: "tenía un limitador puesto por seguridad...
    # creo") ---
    if tiene_clipping:
        obs.append(("⚠", "El stem ya viene clipeado en el archivo — esto no es "
                         "algo que MixMaster pueda arreglar después."))
    elif tp > -1.0:
        obs.append(("⚠", f"Pico a {tp:.1f} dBTP, casi sin margen. Si vas a procesar "
                         "este stem (EQ, compresión) corrés riesgo de clip — pedí un "
                         "bounce con más headroom si podés."))
    if crest < 6.0 and tp > -0.3:
        obs.append(("⚠", f"Este stem tiene pinta de traer compresión/limitador fuerte "
                         f"ya aplicado (crest {crest:.1f} dB, pico {tp:.1f} dBTP). Si "
                         "quien te lo mandó dijo que tenía 'un limitador por seguridad', "
                         "puede que en realidad estuviera masterizando sin darse cuenta "
                         "— pedile un bounce sin ese proceso si podés."))

    if not obs:
        obs.append(("·", "Sin observaciones — este stem está balanceado."))

    return {
        "nombre": path.name,
        "tipo": tipo,
        "bandas_db": bandas,
        "crest_db": round(crest, 1),
        "correlacion": round(corr, 2),
        "true_peak_db": round(tp, 1),
        "observaciones": obs,
    }


# Escala de Bark (Zwicker, 24 bandas críticas) — el modelo estándar de la
# PSICOACÚSTICA para masking, no una convención de mezcla: aproxima cómo la
# cóclea agrupa energía en bandas de ancho creciente con la frecuencia. Es
# el mismo principio que usa el Masking Meter de iZotope Neutron y la
# literatura AES de detección de masking ("Solving Frequency Masking in an
# Audio Mix"). Las 7 bandas de `BANDAS_HZ` (usadas para la sugerencia de EQ
# complementario, más arriba) son deliberadamente anchas y fáciles de
# nombrar en una sugerencia ("cortá en low"); Bark es más fina y sirve para
# CUANTIFICAR qué tan severo es un choque ya detectado, no para nombrarlo.
BARK_EDGES_HZ = (0, 100, 200, 300, 400, 510, 630, 770, 920, 1080, 1270, 1480,
                  1720, 2000, 2320, 2700, 3150, 3700, 4400, 5300, 6400, 7700,
                  9500, 12000, 15500, 20000)


def _energia_bark(mono: np.ndarray, sr: int) -> np.ndarray:
    """RMS por banda crítica de Bark (hasta 24 valores, menos si sr es bajo
    y Nyquist corta antes de 20 kHz)."""
    nyquist = sr / 2
    out = []
    for f_lo, f_hi in zip(BARK_EDGES_HZ[:-1], BARK_EDGES_HZ[1:]):
        f_lo = max(f_lo, 20.0)   # 0 Hz no es una frecuencia de corte válida
        if f_lo >= nyquist - 1:
            break
        filtrada = _filtrar_banda(mono, sr, f_lo, min(f_hi, nyquist - 1))
        out.append(float(np.sqrt(np.mean(filtrada ** 2))))
    return np.array(out)


def _severidad_masking_bark(mono_a: np.ndarray, mono_b: np.ndarray, sr: int,
                             umbral_db: float = -6.0) -> tuple:
    """Cuenta en cuántas bandas críticas de Bark ambos stems tienen energía
    significativa a la vez (dentro de `umbral_db` de su propio pico). Más
    bandas críticas en común = masking más severo y más difícil de arreglar
    con un solo corte de EQ ancho. Devuelve (n_bandas_en_comun, n_bandas_totales)."""
    ea = _energia_bark(mono_a, sr)
    eb = _energia_bark(mono_b, sr)
    n = min(len(ea), len(eb))
    if n == 0:
        return 0, 0
    ea, eb = ea[:n], eb[:n]
    ea_db = 20 * np.log10(np.maximum(ea, 1e-12) / max(float(ea.max()), 1e-12))
    eb_db = 20 * np.log10(np.maximum(eb, 1e-12) / max(float(eb.max()), 1e-12))
    return int(np.sum((ea_db > umbral_db) & (eb_db > umbral_db))), n


def _envolvente_banda(mono: np.ndarray, sr: int, f_lo: float, f_hi: float,
                       ventana_s: float = 0.05) -> np.ndarray:
    """RMS por ventanas no solapadas de la señal filtrada a una banda —
    sirve para comparar el RITMO de dos stems en esa banda (no el timbre)."""
    filtrada = _filtrar_banda(mono, sr, f_lo, f_hi)
    n = max(1, int(ventana_s * sr))
    recorte = len(filtrada) - (len(filtrada) % n)
    if recorte < n:
        return np.array([np.sqrt(np.mean(filtrada ** 2))])
    ventanas = filtrada[:recorte].reshape(-1, n)
    return np.sqrt(np.mean(ventanas ** 2, axis=1))


def _cross_correlacion_maxima(mono_a: np.ndarray, mono_b: np.ndarray, sr: int,
                               max_lag_ms: float = 30.0) -> tuple:
    """Cross-correlación normalizada entre dos señales, acotada a un lag
    máximo — los mics de una misma fuente en una grabación en vivo rara vez
    están a más de ~10m de diferencia de camino (~30ms). Correlación alta
    (con cualquier signo) en el pico = las dos señales comparten mucha
    energía, típico de bleed/multi-mic sobre la MISMA fuente (kick in/out,
    overheads, room mic). Devuelve (lag_muestras, correlación_en_el_pico)."""
    max_lag = max(1, int(sr * max_lag_ms / 1000))
    n = min(len(mono_a), len(mono_b))
    if n < max_lag * 2:
        return 0, 0.0
    a = mono_a[:n] - np.mean(mono_a[:n])
    b = mono_b[:n] - np.mean(mono_b[:n])
    norm = np.sqrt(np.sum(a ** 2) * np.sum(b ** 2))
    if norm < 1e-9:
        return 0, 0.0
    completa = _sp_signal.correlate(a, b, mode="full") / norm
    centro = len(completa) // 2
    ventana = completa[centro - max_lag: centro + max_lag + 1]
    idx = int(np.argmax(np.abs(ventana)))
    lag = idx - max_lag
    return lag, float(ventana[idx])


def avisos_fase_multitrack(carpeta: Path, umbral_correlacion: float = 0.6,
                            max_lag_ms: float = 30.0) -> list[str]:
    """Detecta problemas de fase/polaridad entre stems que probablemente
    capturan la MISMA fuente por mics distintos — el caso clásico de una
    grabación en vivo multi-mic (kick in/out, overheads, room mic sobre la
    batería, etc.), donde comb filtering y cancelación de fase son la causa
    #1 de que "el bombo no pega" o "el low end desaparece al sumar todo".

    Método: cross-correlación acotada a `max_lag_ms` (GCC clásico, sin
    aprendizaje automático). Si dos stems correlacionan fuerte al alinearlos
    (probable misma fuente por bleed), avisa:
      - Correlación fuerte NEGATIVA → polaridad invertida, se están
        cancelando (fix: invertir fase de uno).
      - Correlación fuerte positiva pero con lag != 0 → desalineados en el
        tiempo (fix: alinear antes de mezclar, evita comb filtering).

    No asume qué stems son "la misma fuente" por nombre — lo detecta por la
    correlación misma, así que sirve tanto para nombres genéricos (mic1/mic2)
    como para los ya reconocidos por `_tipo`.
    """
    carpeta = Path(carpeta)
    if not carpeta.is_dir():
        return []
    paths = sorted(p for p in carpeta.iterdir()
                   if p.is_file() and p.suffix.lower() in FORMATOS)
    stems = []
    for p in paths:
        try:
            audio, sr = cargar_audio(p)
            stems.append({"nombre": p.stem, "mono": audio.mean(axis=1), "sr": sr})
        except Exception:
            log.exception("No se pudo cargar %s para el chequeo de fase multitrack", p.name)
    if len(stems) < 2:
        return []

    avisos = []
    for i in range(len(stems)):
        for j in range(i + 1, len(stems)):
            a, b = stems[i], stems[j]
            if a["sr"] != b["sr"]:
                continue  # ya se avisa el SR inconsistente en checklist_pre_mezcla
            lag, corr = _cross_correlacion_maxima(a["mono"], b["mono"], a["sr"], max_lag_ms)
            if abs(corr) < umbral_correlacion:
                continue
            lag_ms = lag / a["sr"] * 1000
            if corr < 0:
                avisos.append(
                    f"«{a['nombre']}» y «{b['nombre']}» probablemente captan la MISMA "
                    f"fuente por mics distintos (correlación {corr:.2f} a {lag_ms:+.1f}ms) "
                    "con POLARIDAD INVERTIDA — se están cancelando entre sí. Probá "
                    "invertir la fase de uno de los dos."
                )
            elif abs(lag_ms) > 0.3:
                avisos.append(
                    f"«{a['nombre']}» y «{b['nombre']}» probablemente captan la MISMA "
                    f"fuente por mics distintos (correlación {corr:.2f}) pero desalineados "
                    f"{lag_ms:+.1f}ms — alinealos en el tiempo antes de mezclar, si no vas "
                    "a tener comb filtering (huecos y picos en el espectro, sonido hueco/nasal)."
                )
    return avisos


# Prioridad por banda: qué tipo de instrumento tiene más derecho convencional
# a esa zona del espectro en una mezcla (no es una medición — es la práctica
# estándar de mezcla: bajo/bombo mandan en graves, voz manda en medios donde
# se juega la inteligibilidad). El otro tipo es candidato a cortar primero.
# Tipos no listados en la tupla de una banda (no debería pasar, cubre las 5
# categorías de `_tipo`) caen al final por `len(orden)`.
_PRIORIDAD_BANDA = {
    "sub":      ("bajo", "bateria", "generico", "guitarra", "voz"),
    "low":      ("bateria", "bajo", "generico", "guitarra", "voz"),
    "low_mid":  ("voz", "guitarra", "bajo", "bateria", "generico"),
    "mid":      ("voz", "guitarra", "bateria", "bajo", "generico"),
    "high_mid": ("voz", "bateria", "guitarra", "bajo", "generico"),
    "high":     ("bateria", "voz", "guitarra", "bajo", "generico"),
    "air":      ("bateria", "voz", "guitarra", "bajo", "generico"),
}


def _sugerencia_eq_complementario(banda: str, f_lo: float, f_hi: float,
                                   nombre_a: str, tipo_a: str,
                                   nombre_b: str, tipo_b: str) -> str:
    """EQ complementario (sustractivo, no aditivo): de los dos stems que
    compiten en `banda`, sugiere cuál cortar primero según la prioridad
    convencional de `_PRIORIDAD_BANDA` — cortar es más transparente que subir
    (mentor, síntesis de I5-electronica-produccion.md/B1-texturas.md). Si
    ambos son del mismo tipo no hay convención que los distinga."""
    orden = _PRIORIDAD_BANDA.get(banda, ())
    rango_a = orden.index(tipo_a) if tipo_a in orden else len(orden)
    rango_b = orden.index(tipo_b) if tipo_b in orden else len(orden)
    if rango_a == rango_b:
        return (f" Sugerencia: son del mismo tipo, no hay convención clara — "
                f"decidí cuál manda en {banda} ({f_lo:.0f}-{f_hi:.0f} Hz) y "
                "cortale 2-3 dB ahí al otro.")
    perdedor, ganador = (nombre_a, nombre_b) if rango_a > rango_b else (nombre_b, nombre_a)
    return (f" Sugerencia: cortá «{perdedor}» 2-3 dB en {banda} "
            f"({f_lo:.0f}-{f_hi:.0f} Hz) — «{ganador}» tiene más derecho a esa "
            "zona (EQ complementario: cortar es más transparente que subir).")


def checklist_pre_mezcla(carpeta: Path) -> list[str]:
    """Compara los stems ENTRE SÍ (a diferencia de diagnosticar_stem/carpeta,
    que mira cada uno por separado) y devuelve avisos de:

    - Choque de frecuencias: 2+ stems con su banda dominante en la misma
      zona (van a competir por espacio ahí), con una sugerencia de EQ
      complementario (cuál cortar y cuánto) según `_PRIORIDAD_BANDA`.
    - Masking rítmico: de los que chocan en frecuencia, cuáles además pegan
      fuerte AL MISMO TIEMPO en esa banda (correlación de envolvente > 0.5)
      — eso es lo que realmente se enmascara; si se turnan, el choque de
      frecuencia importa menos.

    Devuelve lista de avisos en texto plano, vacía si hay <2 stems o si no
    encuentra nada. No usa género — el motor ya quedó con un bucket único
    (ver roadmap), así que esto no depende de él.
    """
    carpeta = Path(carpeta)
    if not carpeta.is_dir():
        return []
    paths = sorted(p for p in carpeta.iterdir()
                   if p.is_file() and p.suffix.lower() in FORMATOS)

    stems = []
    for p in paths:
        try:
            audio, sr = cargar_audio(p)
            stems.append({
                "nombre": p.stem,
                "tipo": _tipo(p.stem),
                "mono": audio.mean(axis=1),
                "sr": sr,
                "bandas": balance_bandas_db(audio, sr),
            })
        except Exception:
            log.exception("No se pudo cargar %s para el checklist pre-mezcla", p.name)
    if len(stems) < 2:
        return []

    def _bandas_dominantes(bandas: dict) -> set:
        pico = max(bandas.values())
        return {b for b, v in bandas.items() if v >= pico - 6}

    avisos = []

    sr_unicos = {s["sr"] for s in stems}
    if len(sr_unicos) > 1:
        detalle = ", ".join(f"{s['nombre']} ({s['sr']} Hz)" for s in stems)
        avisos.append(
            f"Sample rate inconsistente entre stems: {detalle}. Resampleá todo al "
            "mismo SR antes de mezclar — si no, el motor igual puede leerlos pero "
            "el timing/fase entre pistas puede no ser exacto."
        )

    for i in range(len(stems)):
        for j in range(i + 1, len(stems)):
            a, b = stems[i], stems[j]
            compartidas = _bandas_dominantes(a["bandas"]) & _bandas_dominantes(b["bandas"])
            for banda in sorted(compartidas, key=lambda x: BANDAS_HZ[x][0]):
                f_lo, f_hi = BANDAS_HZ[banda]
                ritmo = ""
                if a["sr"] == b["sr"]:
                    env_a = _envolvente_banda(a["mono"], a["sr"], f_lo, f_hi)
                    env_b = _envolvente_banda(b["mono"], b["sr"], f_lo, f_hi)
                    n = min(len(env_a), len(env_b))
                    if n > 10 and np.std(env_a[:n]) > 1e-9 and np.std(env_b[:n]) > 1e-9:
                        corr = float(np.corrcoef(env_a[:n], env_b[:n])[0, 1])
                        if corr > 0.5:
                            n_bark, total_bark = _severidad_masking_bark(
                                a["mono"], b["mono"], a["sr"])
                            severidad = ("severo" if total_bark and n_bark / total_bark >= 0.15
                                         else "moderado")
                            ritmo = (f" y pegan AL MISMO TIEMPO (correlación rítmica {corr:.2f}) "
                                     "— esto sí es masking real, no solo choque de EQ. "
                                     f"Psicoacústicamente se solapan en {n_bark}/{total_bark} "
                                     f"bandas críticas (Bark) — masking {severidad}")
                        else:
                            ritmo = f" pero en momentos distintos (correlación rítmica {corr:.2f}) — se turnan, menor riesgo"
                sugerencia = _sugerencia_eq_complementario(
                    banda, f_lo, f_hi, a["nombre"], a["tipo"], b["nombre"], b["tipo"])
                avisos.append(
                    f"«{a['nombre']}» y «{b['nombre']}» compiten en {banda} "
                    f"({f_lo:.0f}-{f_hi:.0f} Hz){ritmo}.{sugerencia}"
                )

    avisos += avisos_fase_multitrack(carpeta)
    return avisos


def diagnosticar_carpeta(carpeta: Path) -> list[dict]:
    """Diagnostica todos los stems de una carpeta, ordenados por nombre."""
    carpeta = Path(carpeta)
    if not carpeta.is_dir():
        return []
    stems = sorted(p for p in carpeta.iterdir()
                   if p.is_file() and p.suffix.lower() in FORMATOS)
    resultado = []
    for s in stems:
        try:
            resultado.append(diagnosticar_stem(s))
        except Exception:
            log.exception("No se pudo diagnosticar el stem %s", s.name)
    return resultado
