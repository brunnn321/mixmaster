"""Auto-mezcla (v1.0+): balance de nivel + panning de PUNTO DE PARTIDA para
stems, según convención estándar de mezcla — batería/bajo llevan la base,
voz principal al frente, el resto son capas de arreglo o textura/color
(mentor, síntesis I5-electronica-produccion.md/B1-texturas.md + convención
de panning de grabación en vivo — kick/snare/bajo/voz centro, overheads/hats
anchos ±75%, pares L/R opuestos).

ESTO NO ES UNA MEZCLA TERMINADA. Es un arranque razonable y transparente
(nivel + pan por rol, no artístico) que reemplaza la suma plana centrada de
antes — se ajusta de oído después. Ver `feedback_no_presentar_sin_escuchar`
en memoria: nunca reportar el resultado de esto como si fuera una mezcla
validada.
"""

import re
from pathlib import Path

import numpy as np
import soundfile as sf

FORMATOS_STEM = (".wav", ".flac", ".aiff", ".aif")

# Normalización de nivel de ENTRADA (antes del offset por rol) — corrige
# que dos stems del mismo rol suenen distinto en la mezcla final solo
# porque uno se grabó más caliente que el otro (encontrado con audio real:
# guitarra a -27dB RMS vs teclas a -32dB RMS, mismo rol/offset, la
# guitarra dominaba igual; voz principal a -42.5dB RMS, 15dB más floja que
# el resto, quedaba "lejos" pese al +2dB de rol). Sin esto, la jerarquía
# de rol solo es correcta si todos los stems entraron grabados parejo,
# lo cual no pasa en grabaciones en vivo reales.
#
# La referencia es la MEDIANA de RMS de la propia sesión, no un número
# absoluto fijo — bug real encontrado al probar con audio real: con un
# valor fijo (-20dB), CASI TODOS los stems de una tanda grabada floja a
# propósito (headroom conservador para un show en vivo, decisión válida
# del ingeniero) pedían el tope de ganancia — intentaba "corregir" una
# sesión entera en vez de solo los outliers reales dentro de ella.
REF_RMS_DB_FALLBACK = -20.0  # solo si no hay suficientes stems con señal real
MAX_NORM_DB = 18.0          # tope de ganancia de normalización
UMBRAL_SILENCIO_DB = -60.0  # por debajo de esto no se normaliza (probable
                             # silencio real en este tramo, no un problema
                             # de nivel — amplificarlo solo sube ruido)

# --- Clasificación de rol por nombre (más granular que _tipo de
# stem_diagnostico.py, que solo distingue bajo/batería/guitarra/voz/genérico) ---
_ROLES_CLAVES = {
    "kick": ("kick", "bombo"),
    "bajo": ("bass", "bajo"),
    "snare": ("snr", "snare", "caja", "redoblante"),
    "voz_principal": ("lead vox", "voz principal", "vocal principal", "lead vocal"),
    "coros": ("coro", "backing", "bgvoc", "bgvox"),
    "toms": ("tom", "ton"),
    "hats": ("hh", "hihat", "hi-hat", "hat"),
    "overhead": ("over", "oh", "overhead"),
    "room": ("room", "ambiente", "sala"),
    "percusion_mayor": ("conga", "tumba"),
    "percusion_menor": ("bongo", "campana", "cencerro", "guiro", "shaker", "pandereta"),
    "guitarra": ("gtr", "guitar", "guitarra"),
    "teclas": ("keys", "teclado", "piano", "synth"),
    "vientos": ("tromp", "trump", "bone", "trombon", "sax", "brass", "horn"),
}

# Nivel relativo (dB) por rol — jerarquía de mezcla estándar: batería/bajo/
# voz son la base rítmica-armónica-melódica, el resto son capas de arreglo
# (guitarra/teclas/vientos) o color/textura (hats/overhead/percusión menor/
# room). No son números arbitrarios — es la convención de "quién manda"
# igual que `_PRIORIDAD_BANDA` en stem_diagnostico.py, aplicada a nivel en
# vez de a banda de EQ.
NIVEL_DB = {
    "kick": 0.0, "bajo": 0.0, "snare": 0.0,
    "voz_principal": 2.0,
    "toms": -3.0, "percusion_mayor": -3.0,
    "guitarra": -3.0, "teclas": -3.0, "vientos": -3.0, "coros": -2.0,
    "hats": -5.0, "overhead": -5.0, "percusion_menor": -5.0,
    "room": -8.0,
    "generico": -4.0,
}

# Pan por defecto (-1..1) por rol cuando NO hay par L/R detectado por
# nombre. Overhead/hats/room anchos (±75%, convención real de grabación en
# vivo — ver investigación citada arriba); base rítmica y voz al centro.
PAN_DEFAULT = {
    "kick": 0.0, "bajo": 0.0, "snare": 0.0, "voz_principal": 0.0,
    "toms": 0.2, "overhead": 0.75, "hats": 0.75, "room": 0.6,
    "coros": 0.3, "guitarra": 0.4, "teclas": 0.3, "vientos": 0.3,
    "generico": 0.0,
}

# Percusión sin par explícito: posiciones alternadas fijas para que no se
# apilen todas en el centro (conga/tumba/bongó/campana suelen sonar a la vez).
PAN_ALTERNADO = (-0.4, 0.4, -0.2, 0.2, -0.6, 0.6)

_TOKEN_SEP = re.compile(r"[\s_-]+")


def detectar_par(nombre: str) -> tuple[str, str | None]:
    """Detecta un token L/R o 1/2 en el nombre de un stem — en cualquier
    posición, no solo al final: nombres reales de grabación en vivo suelen
    llevar número de pista y timestamp DESPUÉS del canal
    ("16-GTR L-260815_2214.wav", "18-GTR R-260815_2214.wav").

    Devuelve (clave_agrupacion, lado) — lado es 'A' (izquierda/1), 'B'
    (derecha/2), o None si no hay par. `clave_agrupacion` ignora tokens
    puramente numéricos (número de pista, timestamp) porque esos SUELEN
    diferir entre los dos lados de un mismo par aunque sea el mismo
    instrumento (pista 16 = GTR L, pista 18 = GTR R) — sin ignorarlos, la
    comparación nunca matchea. Solo sirve para AGRUPAR, no es el nombre
    para mostrar.
    """
    tokens = [t for t in _TOKEN_SEP.split(nombre.strip()) if t]
    lado, idx = None, None
    for i, tok in enumerate(tokens):
        if tok.upper() in ("L", "R"):
            lado, idx = ("A" if tok.upper() == "L" else "B"), i
            break
    if lado is None:
        for i, tok in enumerate(tokens):
            if tok in ("1", "2"):
                lado, idx = ("A" if tok == "1" else "B"), i
                break
    if lado is None:
        return nombre.strip(), None
    resto = tokens[:idx] + tokens[idx + 1:]
    significativos = tuple(t.lower() for t in resto if not t.isdigit())
    return significativos or tuple(t.lower() for t in resto), lado


def clasificar_rol(nombre: str, roles_manual: dict[str, str] | None = None) -> str:
    """Rol de mezcla de un stem por nombre. `roles_manual` (nombre exacto
    de archivo -> rol) pisa la clasificación automática — para los casos
    ambiguos que no se pueden adivinar (ver `sin_clasificar` en
    `calcular_plan`)."""
    if roles_manual and nombre in roles_manual:
        return roles_manual[nombre]
    n = nombre.lower()
    for rol, claves in _ROLES_CLAVES.items():
        if any(c in n for c in claves):
            return rol
    return "generico"


def _rms_db_archivo(path: Path) -> float:
    """RMS en dB de un archivo de audio (downmix a mono)."""
    audio, _ = sf.read(str(path), always_2d=True)
    mono = audio.mean(axis=1).astype(np.float64)
    rms = float(np.sqrt(np.mean(mono ** 2)))
    return 20 * np.log10(max(rms, 1e-12))


def calcular_plan(carpeta: Path, roles_manual: dict[str, str] | None = None,
                   normalizar_nivel: bool = True) -> dict:
    """Calcula ganancia (dB) y pan (-1..1) por stem — PUNTO DE PARTIDA de
    balance/panning por convención de mezcla, no una mezcla terminada.

    `normalizar_nivel` (default True): mide el RMS real de cada stem y lo
    lleva a la MEDIANA de RMS de la propia sesión (no un número absoluto
    fijo — ver nota en las constantes de arriba) ANTES de aplicar el
    offset de rol. Sin esto, dos stems del mismo rol pueden sonar muy
    distinto en la mezcla final solo porque uno se grabó más caliente.
    Los stems casi silenciosos (< `UMBRAL_SILENCIO_DB`) no se
    normalizan — se reportan aparte en "silenciosos", puede ser silencio
    real de ese
    tramo del tema, no un problema de nivel.

    Devuelve:
      {"stems": {nombre_stem: {"rol":, "ganancia_db":, "pan":, "rms_db":,
                                "normalizacion_db":}},
       "sin_clasificar": [...], "silenciosos": [...]}
    """
    carpeta = Path(carpeta)
    paths = sorted(p for p in carpeta.iterdir()
                   if p.is_file() and p.suffix.lower() in FORMATOS_STEM)
    archivos = [p.stem for p in paths]
    ruta_por_nombre = {p.stem: p for p in paths}

    grupos: dict = {}
    for nombre in archivos:
        clave, lado = detectar_par(nombre)
        clave = clave.lower() if isinstance(clave, str) else clave
        grupos.setdefault(clave, []).append((nombre, lado))

    rms_por_nombre: dict[str, float | None] = {}
    ref_rms_db = REF_RMS_DB_FALLBACK
    if normalizar_nivel:
        for nombre in archivos:
            try:
                rms_por_nombre[nombre] = _rms_db_archivo(ruta_por_nombre[nombre])
            except Exception:
                rms_por_nombre[nombre] = None
        con_senal = [v for v in rms_por_nombre.values()
                     if v is not None and v > UMBRAL_SILENCIO_DB]
        if con_senal:
            ref_rms_db = float(np.median(con_senal))

    plan: dict[str, dict] = {}
    sin_clasificar, silenciosos = [], []
    alterno_idx = 0
    for miembros in grupos.values():
        es_par = len(miembros) == 2 and all(lado is not None for _, lado in miembros)
        for nombre, lado in miembros:
            rol = clasificar_rol(nombre, roles_manual)
            manual = bool(roles_manual and nombre in roles_manual)
            if rol == "generico" and not manual:
                sin_clasificar.append(nombre)

            rol_db = NIVEL_DB.get(rol, NIVEL_DB["generico"])
            rms_db = rms_por_nombre.get(nombre)
            norm_db = 0.0
            if normalizar_nivel and rms_db is not None:
                if rms_db <= UMBRAL_SILENCIO_DB:
                    silenciosos.append(nombre)
                else:
                    norm_db = float(np.clip(ref_rms_db - rms_db, -MAX_NORM_DB, MAX_NORM_DB))
            ganancia_db = round(rol_db + norm_db, 1)

            if es_par:
                pan = -0.7 if lado == "A" else 0.7
            elif rol in ("percusion_mayor", "percusion_menor"):
                pan = PAN_ALTERNADO[alterno_idx % len(PAN_ALTERNADO)]
                alterno_idx += 1
            else:
                pan = PAN_DEFAULT.get(rol, 0.0)

            plan[nombre] = {
                "rol": rol, "ganancia_db": ganancia_db, "pan": round(pan, 2),
                "rms_db": round(rms_db, 1) if rms_db is not None else None,
                "normalizacion_db": round(norm_db, 1),
            }

    return {"stems": plan, "sin_clasificar": sorted(sin_clasificar),
            "silenciosos": sorted(silenciosos), "ref_rms_db": round(ref_rms_db, 1)}


def aplicar_pan(mono: np.ndarray, pan: float) -> np.ndarray:
    """Ley de panning de potencia constante (-3dB al centro), estándar de
    consola/DAW. `pan` en [-1, 1]: -1 = izquierda dura, 0 = centro,
    1 = derecha dura. Devuelve señal estéreo (n, 2)."""
    pan = max(-1.0, min(1.0, pan))
    theta = (pan + 1.0) * (np.pi / 4)
    gan_l, gan_r = float(np.cos(theta)), float(np.sin(theta))
    return np.stack([mono * gan_l, mono * gan_r], axis=1)


def plan_legible(plan: dict) -> str:
    """Texto plano del plan de auto-mezcla, para mostrar antes de aplicar."""
    lineas = ["══ PLAN DE AUTO-MEZCLA — punto de partida, no una mezcla terminada ══"]
    for nombre, info in sorted(plan["stems"].items()):
        pan_txt = ("centro" if abs(info["pan"]) < 0.01
                    else f"{'izq' if info['pan'] < 0 else 'der'} {abs(info['pan']) * 100:.0f}%")
        rms_txt = f" (RMS {info['rms_db']:.1f}dB, norm {info['normalizacion_db']:+.1f}dB)" \
            if info.get("rms_db") is not None else ""
        aviso_gan = "  ⚠ ganancia grande, revisá ruido de fondo" \
            if abs(info.get("normalizacion_db", 0)) >= 10 else ""
        lineas.append(f"  {nombre:<24} [{info['rol']:<16}] "
                      f"{info['ganancia_db']:+.1f} dB   pan {pan_txt}{rms_txt}{aviso_gan}")
    if plan["sin_clasificar"]:
        lineas += ["", "— SIN CLASIFICAR (nivel/pan neutro, ajustá de oído o decime el rol) —"]
        lineas += [f"  {n}" for n in plan["sin_clasificar"]]
    if plan.get("silenciosos"):
        lineas += ["", "— CASI SIN SEÑAL en este tramo (no normalizado; puede ser silencio real, no un problema de nivel) —"]
        lineas += [f"  {n}" for n in plan["silenciosos"]]
    return "\n".join(lineas)
