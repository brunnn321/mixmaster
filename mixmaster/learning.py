"""Aprendizaje de preferencias (v0.9+): la app aprende de los masters que
apruebas y afina sus defaults por género.

Guarda en config/aprendizaje.json. Reversible (olvidar). Primer mecanismo:
loudness preferido por género (media de los masters aprobados). Se guarda
además el perfil del master para el futuro «tu sonido» (matching hacia tus
propios masters aprobados).
"""

import json
from datetime import datetime

from .app_paths import CONFIG_DIR
from .logger import get_logger

log = get_logger("mixmaster.learning")

APRENDIZAJE_JSON = CONFIG_DIR / "aprendizaje.json"


def _cargar() -> dict:
    if APRENDIZAJE_JSON.exists():
        try:
            return json.loads(APRENDIZAJE_JSON.read_text(encoding="utf-8"))
        except Exception:
            log.exception("aprendizaje.json ilegible; se ignora")
    return {}


def _guardar(datos: dict) -> None:
    APRENDIZAJE_JSON.parent.mkdir(parents=True, exist_ok=True)
    APRENDIZAJE_JSON.write_text(
        json.dumps(datos, indent=2, ensure_ascii=False), encoding="utf-8")


def registrar_aprobado(genero: str, resumen: dict) -> int:
    """Registra un master aprobado para el género. Devuelve el total acumulado."""
    datos = _cargar()
    g = datos.setdefault(genero, {"aprobados": []})
    g["aprobados"].append({
        "fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "target_lufs": resumen.get("target_lufs"),
        "lufs_final": resumen.get("lufs_final"),
        "crest_final": resumen.get("crest_final"),
        "true_peak_final": resumen.get("true_peak_final"),
        "eq_aplicado_db": resumen.get("eq_aplicado_db"),
        "ajuste_ancho_db": resumen.get("ajuste_ancho_db"),
        "multibanda_db": resumen.get("multibanda_db"),
        "mono_bass_hz": resumen.get("mono_bass_hz"),
        "score": resumen.get("score"),
        "referencias": resumen.get("referencias"),
    })
    _guardar(datos)
    n = len(g["aprobados"])
    log.info("Master aprobado registrado para '%s' (%d total)", genero, n)
    return n


def registrar_rechazado(genero: str, resumen: dict) -> int:
    """Registra un master que NO aprobaste. Devuelve el total acumulado.

    Guarda exactamente los mismos campos que `registrar_aprobado` pero en
    una lista aparte: saber qué NO te gusta es tan informativo como saber
    qué sí, y hasta ahora esa mitad de los datos se descartaba. No afecta
    a `preferencias()` — los rechazados no promedian con los aprobados,
    solo quedan disponibles para comparar (ver `contraste_aprobado_rechazado`).
    """
    datos = _cargar()
    g = datos.setdefault(genero, {"aprobados": []})
    rechazados = g.setdefault("rechazados", [])
    rechazados.append({
        "fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "target_lufs": resumen.get("target_lufs"),
        "lufs_final": resumen.get("lufs_final"),
        "crest_final": resumen.get("crest_final"),
        "true_peak_final": resumen.get("true_peak_final"),
        "eq_aplicado_db": resumen.get("eq_aplicado_db"),
        "ajuste_ancho_db": resumen.get("ajuste_ancho_db"),
        "multibanda_db": resumen.get("multibanda_db"),
        "mono_bass_hz": resumen.get("mono_bass_hz"),
        "score": resumen.get("score"),
        "referencias": resumen.get("referencias"),
    })
    _guardar(datos)
    n = len(rechazados)
    log.info("Master rechazado registrado para '%s' (%d total)", genero, n)
    return n


def contraste_aprobado_rechazado(genero: str, minimo: int = 3) -> dict:
    """Qué separa lo que aprobás de lo que rechazás, métrica por métrica.

    Solo devuelve algo con al menos `minimo` de CADA lado — con menos, la
    diferencia sería ruido, no patrón. Devuelve {metrica: {aprobado, rechazado,
    delta}} para las métricas escalares comparables.
    """
    g = _cargar().get(genero, {})
    aprobados, rechazados = g.get("aprobados", []), g.get("rechazados", [])
    if len(aprobados) < minimo or len(rechazados) < minimo:
        return {}

    def _media(items: list[dict], clave: str) -> float | None:
        vals = [i[clave] for i in items if isinstance(i.get(clave), (int, float))]
        return sum(vals) / len(vals) if vals else None

    resultado = {"n_aprobados": len(aprobados), "n_rechazados": len(rechazados)}
    for clave in ("target_lufs", "lufs_final", "crest_final", "true_peak_final"):
        m_ok, m_no = _media(aprobados, clave), _media(rechazados, clave)
        if m_ok is not None and m_no is not None:
            resultado[clave] = {
                "aprobado": round(m_ok, 1),
                "rechazado": round(m_no, 1),
                "delta": round(m_ok - m_no, 1),
            }
    return resultado


def _promedio_por_banda(aprobados: list[dict], clave: str) -> dict[str, float]:
    """Promedia un dict-por-banda (ej. eq_aplicado_db) a través de los aprobados."""
    acumulado: dict[str, list[float]] = {}
    for a in aprobados:
        d = a.get(clave) or {}
        for banda, valor in d.items():
            if isinstance(valor, (int, float)):
                acumulado.setdefault(banda, []).append(valor)
    return {banda: round(sum(vals) / len(vals), 1) for banda, vals in acumulado.items()}


def preferencias(genero: str) -> dict:
    """Defaults aprendidos del género a partir de los masters aprobados.

    Cada campo se calcula solo si hay datos suficientes; sonido más "tuyo"
    cuantos más masters apruebes. Todo viene de datos ya guardados en
    registrar_aprobado — nada se re-analiza, solo se promedia.
    """
    aprobados = _cargar().get(genero, {}).get("aprobados", [])
    lufs = [a["target_lufs"] for a in aprobados if a.get("target_lufs") is not None]
    if not lufs:
        return {}

    resultado = {
        "target_lufs": round(sum(lufs) / len(lufs) * 2) / 2,  # media redondeada a 0.5
        "n": len(aprobados),
    }

    crest = [a["crest_final"] for a in aprobados if a.get("crest_final") is not None]
    if crest:
        resultado["crest_target"] = round(sum(crest) / len(crest), 1)

    eq_sig = _promedio_por_banda(aprobados, "eq_aplicado_db")
    if eq_sig:
        resultado["eq_signature"] = eq_sig

    ancho_sig = _promedio_por_banda(aprobados, "ajuste_ancho_db")
    if ancho_sig:
        resultado["ancho_signature"] = ancho_sig

    mb_sig = _promedio_por_banda(aprobados, "multibanda_db")
    if mb_sig:
        resultado["multibanda_signature"] = mb_sig

    tp = [a["true_peak_final"] for a in aprobados if a.get("true_peak_final") is not None]
    if tp:
        resultado["true_peak_margin"] = round(sum(tp) / len(tp), 1)

    mono_bass = [a["mono_bass_hz"] for a in aprobados if a.get("mono_bass_hz")]
    if mono_bass:
        resultado["mono_bass_hz"] = round(sum(mono_bass) / len(mono_bass))

    # tu umbral de calidad: el score más bajo que SÍ aprobaste (piso real, no promedio)
    scores = [a["score"]["global"] for a in aprobados
              if isinstance(a.get("score"), dict) and a["score"].get("global") is not None]
    if scores:
        resultado["score_umbral"] = min(scores)

    # referencias que más repetís (tu sonido de cabecera)
    conteo: dict[str, int] = {}
    for a in aprobados:
        for ref in (a.get("referencias") or []):
            conteo[ref] = conteo.get(ref, 0) + 1
    if conteo:
        top = sorted(conteo.items(), key=lambda kv: kv[1], reverse=True)[:3]
        resultado["referencias_top"] = [{"nombre": n, "veces": v} for n, v in top if v > 1]

    return resultado


def registrar_mezcla_propia(genero: str, caracter: dict) -> int:
    """Registra el carácter de una mezcla marcada como propia (antes de masterizar).

    A diferencia de `registrar_aprobado` (que guarda el resultado del master
    final), esto guarda cómo suena TU mezcla cruda — permite encontrar
    patrones recurrentes en tu forma de mezclar, no solo en cómo masterizás.
    """
    datos = _cargar()
    g = datos.setdefault(genero, {"aprobados": []})
    mezclas = g.setdefault("mezclas_propias", [])
    mezclas.append({
        "fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "inclinacion_db_oct": caracter.get("inclinacion_db_oct"),
        "definicion_graves_db": caracter.get("definicion_graves_db"),
        "punch": caracter.get("punch"),
        "centroide_hz": caracter.get("centroide_hz"),
        "rolloff_hz": caracter.get("rolloff_hz"),
        "plr_db": caracter.get("plr_db"),
    })
    _guardar(datos)
    n = len(mezclas)
    log.info("Mezcla propia registrada para '%s' (%d total)", genero, n)
    return n


def patrones_mezcla(genero: str) -> dict:
    """Promedios del carácter de tus mezclas propias registradas."""
    mezclas = _cargar().get(genero, {}).get("mezclas_propias", [])
    if not mezclas:
        return {}
    claves = ["inclinacion_db_oct", "definicion_graves_db", "punch",
              "centroide_hz", "rolloff_hz", "plr_db"]
    resultado = {"n": len(mezclas)}
    for clave in claves:
        vals = [m[clave] for m in mezclas if isinstance(m.get(clave), (int, float))]
        if vals:
            resultado[clave] = round(sum(vals) / len(vals), 2)
    return resultado


def consejo_mezcla(genero: str, caracter_actual: dict, minimo: int = 3) -> str | None:
    """Compara la mezcla actual contra tu histórico y sugiere qué mirar.

    Solo devuelve texto cuando hay suficiente historial (>= minimo mezclas
    propias registradas) para que el patrón sea confiable y no ruido.
    """
    patrones = patrones_mezcla(genero)
    if not patrones or patrones.get("n", 0) < minimo:
        return None

    lineas = [f"— TU PATRÓN COMO MEZCLADOR (de {patrones['n']} mezclas propias) —"]

    def_graves_hist = patrones.get("definicion_graves_db")
    def_graves_hoy = caracter_actual.get("definicion_graves_db")
    if def_graves_hist is not None and def_graves_hoy is not None:
        if def_graves_hist < -1.0:
            lineas.append(
                f"Tus graves suelen venir poco definidos (histórico {def_graves_hist:+.1f}dB, "
                f"hoy {def_graves_hoy:+.1f}dB) — revisá si es un patrón que te conviene corregir "
                f"antes de mezclar, no solo al masterizar.")

    punch_hist = patrones.get("punch")
    punch_hoy = caracter_actual.get("punch")
    if punch_hist is not None and punch_hoy is not None and punch_hist < punch_hoy * 0.7:
        lineas.append(
            f"Esta mezcla tiene más punch de batería que tu promedio histórico "
            f"({punch_hoy:.2f} vs {punch_hist:.2f}) — si es intencional, bien; si no, "
            f"puede ser inconsistencia entre sesiones.")

    tilt_hist = patrones.get("inclinacion_db_oct")
    if tilt_hist is not None:
        if tilt_hist < -1.5:
            lineas.append(
                f"Tu inclinación tonal promedio es oscura ({tilt_hist:+.2f} dB/oct) — "
                f"si buscás más brillo consistente, es algo a trabajar en la mezcla, "
                f"no solo con EQ de masterización.")
        elif tilt_hist > 1.5:
            lineas.append(
                f"Tu inclinación tonal promedio es brillante ({tilt_hist:+.2f} dB/oct) — "
                f"vigilá que no se vuelva fatigante en sesiones largas.")

    return "\n".join(lineas) if len(lineas) > 1 else None


def olvidar(genero: str | None = None) -> None:
    """Borra el aprendizaje de un género (o de todos si genero es None)."""
    datos = _cargar()
    if genero is None:
        datos = {}
    else:
        datos.pop(genero, None)
    _guardar(datos)
    log.info("Aprendizaje olvidado: %s", genero or "TODO")
