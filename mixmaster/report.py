"""Guardado del diagnóstico (JSON de formato fijo) y reporte legible."""

import json
from pathlib import Path

from .logger import get_logger
from .project import Project

log = get_logger("mixmaster.report")


def guardar_diagnostico(proyecto: Project, diag: dict) -> tuple[Path, Path]:
    """Escribe diagnostico_<version>.json y diagnostico_legible.txt en analisis/."""
    proyecto.dir_analisis.mkdir(parents=True, exist_ok=True)  # on-demand
    version = diag.get("version", "V01").lower()
    path_json = proyecto.dir_analisis / f"diagnostico_{version}.json"
    path_txt = proyecto.dir_analisis / "diagnostico_legible.txt"

    with open(path_json, "w", encoding="utf-8") as f:
        json.dump(diag, f, indent=2, ensure_ascii=False)

    texto = reporte_legible(diag)
    path_txt.write_text(texto, encoding="utf-8")

    log.info("Diagnóstico guardado: %s", path_json)
    return path_json, path_txt


def reporte_legible(diag: dict) -> str:
    """Convierte el diagnóstico en un resumen legible para la UI y el .txt."""
    g = diag["global"]
    lineas = [
        f"══ DIAGNÓSTICO — {diag['archivo']} ({diag['version']}) ══",
        f"Fecha: {diag['fecha']}   Duración: {diag['duracion_s']} s   SR: {diag['sample_rate']} Hz",
        "",
        "— GLOBAL —",
        f"  LUFS integrado:  {g['lufs_i']}",
        f"  LUFS short-term (máx): {g['lufs_s']}",
        f"  True peak:       {g['true_peak_db']} dBTP",
        f"  LRA:             {g['lra']} LU",
        f"  Crest factor:    {g['crest_factor_db']} dB",
        f"  Clipping:        {'SÍ ⚠' if diag.get('clipping_global') else 'no'}",
        "",
        "— ANÁLISIS EXPANDIDOS (v0.5) —",
    ]
    lr = diag.get("loudness_range")
    if lr and isinstance(lr, dict):
        lineas.append(f"  Loudness range: {lr.get('lr_global', 0):.1f} LU (dinámica: {lr.get('descripcion', '')})")
    flux = diag.get("spectral_flux")
    if flux and isinstance(flux, dict):
        lineas.append(f"  Spectral flux: {flux.get('flux_mean', 0):.3f} (cambio tímbrico: {flux.get('descripcion', '')})")
    cep = diag.get("cepstral")
    if cep and isinstance(cep, dict) and cep.get("mfcc_mean"):
        mfcc_norm = round(sum(abs(x) for x in cep["mfcc_mean"]) / len(cep["mfcc_mean"]), 3)
        lineas.append(f"  Cepstral (13 MFCC): fingerprint={mfcc_norm} (tímbrico)")
    hr = diag.get("headroom_budget")
    if hr and isinstance(hr, dict) and "pico_mezcla_dbfs" in hr:
        lineas.append(f"  Headroom budget: pico={hr.get('pico_mezcla_dbfs')} vs refs {hr.get('pico_refs_dbfs')}")

    car = diag.get("caracter")
    if car:
        lineas += ["", "— CARÁCTER TONAL (mismos ejes que la ficha de referencias) —"]
        if car.get("inclinacion_db_oct") is not None:
            lineas.append(f"  Inclinación espectral: {car['inclinacion_db_oct']:+.1f} dB/oct")
        if car.get("definicion_graves_db") is not None:
            lineas.append(f"  Definición de graves:  {car['definicion_graves_db']:+.1f} dB")
        if car.get("punch") is not None:
            lineas.append(f"  Punch (pegada):        {car['punch']:.2f}")
        if car.get("plr_db") is not None:
            lineas.append(f"  PLR (headroom):        {car['plr_db']:.1f} dB")
        if car.get("centroide_hz") is not None:
            lineas.append(f"  Centroide espectral:   {car['centroide_hz']:.0f} Hz")
        if car.get("rolloff_hz") is not None:
            lineas.append(f"  Rolloff 85%:           {car['rolloff_hz']:.0f} Hz")

    lineas += ["", "— BALANCE ESPECTRAL (dB RMS por banda) —"]
    for banda, valor in diag["bandas_db"].items():
        lineas.append(f"  {banda:<9} {valor}")

    fino = diag.get("espectro_fino")
    if fino and fino.get("freqs"):
        lineas += ["", "— ESPECTRO FINO (40 bandas, 1/3 de octava) —"]
        pares = list(zip(fino["freqs"], fino["db"]))
        for i in range(0, len(pares), 4):
            fila = pares[i:i + 4]
            lineas.append("  " + "   ".join(f"{f:>6g}Hz {d:>6.1f}dB" for f, d in fila))

    est = diag["estereo"]
    lineas += [
        "",
        "— ESTÉREO —",
        f"  Correlación global: {est['correlacion_global']}",
        f"  Pérdida al sumar a mono: {est['perdida_mono_db']} dB",
        "  Ancho por banda (0=mono, 1=todo side):",
    ]
    for banda, valor in est["ancho_por_banda"].items():
        corr = est.get("correlacion_por_banda", {}).get(banda, "-")
        lineas.append(f"    {banda:<9} ancho {valor}   corr {corr}")

    fase = est.get("fase_fina") or {}
    momentos = fase.get("momentos_criticos") or []
    if momentos:
        lineas.append(f"  Fase fina — {fase.get('n_momentos_criticos', len(momentos))} tramo(s) problemático(s) "
                      f"(ventanas de {fase.get('ventana_s', 0.5)}s, corr < 0.2):")
        for m in momentos:
            lineas.append(f"    {m['inicio_s']:>6.1f}–{m['fin_s']:<6.1f}s  corr {m['correlacion']}")
    elif not fase.get("es_mono"):
        lineas.append("  Fase fina: sin tramos problemáticos detectados.")

    if diag.get("secciones"):
        lineas += ["", "— SECCIONES —"]
        for s in diag["secciones"]:
            clip = " ⚠CLIP" if s["clipping"] else ""
            lineas.append(
                f"  {s['nombre']:<14} {s['inicio_s']:>6.1f}–{s['fin_s']:<6.1f}s  "
                f"LUFS {s['lufs_st']:>6}  pico {s['pico_max']:>6} dB{clip}"
            )
            for nota in s["notas_auto"]:
                lineas.append(f"      · {nota}")
        secs = diag["secciones"]
        if len(secs) >= 2:
            saltos = [(secs[i]["nombre"], secs[i + 1]["nombre"],
                       round(secs[i + 1]["lufs_st"] - secs[i]["lufs_st"], 1))
                      for i in range(len(secs) - 1)]
            nombre_a, nombre_b, delta = max(saltos, key=lambda x: abs(x[2]))
            signo = "+" if delta >= 0 else ""
            lineas.append(
                f"  · Mayor contraste: «{nombre_a}» → «{nombre_b}»  {signo}{delta} LU"
                f"{'  (buen impacto)' if abs(delta) >= 3 else '  (poco contraste — revisar arreglo)'}")

    vs = diag.get("vs_referencia")
    if vs and "delta_bandas_db" in vs:
        lineas += [
            "",
            f"— VS REFERENCIA: {vs['referencia']} (nivelada en loudness) —",
            f"  Delta LUFS: {vs['delta_lufs']}",
            "  Delta por banda (mezcla - referencia):",
        ]
        for banda, valor in vs["delta_bandas_db"].items():
            signo = "+" if valor >= 0 else ""
            lineas.append(f"    {banda:<9} {signo}{valor} dB")
    elif vs and "error" in vs:
        lineas += ["", f"— VS REFERENCIA — {vs['error']}"]

    lineas += ["", "— ALERTAS —"]
    if diag["alertas"]:
        for a in diag["alertas"]:
            lineas.append(f"  ⚠ {a}")
    else:
        lineas.append("  (sin alertas — dentro de parámetros)")

    return "\n".join(lineas)


def comparar_progreso(actual: dict, anterior: dict) -> str | None:
    """Compara este análisis contra el anterior del proyecto — conecta el
    historial de diagnósticos a algo útil (antes quedaban guardados sin
    usarse para nada más que archivo muerto).

    Devuelve texto con qué mejoró/empeoró, o None si no hay datos comparables.
    """
    ga, gp = actual.get("global", {}), anterior.get("global", {})
    if not ga or not gp:
        return None

    def delta(clave, decimales=1):
        va, vp = ga.get(clave), gp.get(clave)
        if va is None or vp is None:
            return None
        return round(va - vp, decimales)

    lineas = [f"— PROGRESO vs. tu análisis anterior ({anterior.get('version', '?')}) —"]
    d_crest = delta("crest_factor_db")
    if d_crest is not None:
        signo = "+" if d_crest >= 0 else ""
        nota = " (más vivo)" if d_crest > 0.3 else (" (más comprimido)" if d_crest < -0.3 else "")
        lineas.append(f"  Crest factor: {gp['crest_factor_db']} → {ga['crest_factor_db']} dB ({signo}{d_crest}){nota}")

    d_lufs = delta("lufs_i")
    if d_lufs is not None:
        lineas.append(f"  LUFS integrado: {gp['lufs_i']} → {ga['lufs_i']} ({'+' if d_lufs >= 0 else ''}{d_lufs})")

    ca, cp = actual.get("caracter") or {}, anterior.get("caracter") or {}
    d_graves = None
    if ca.get("definicion_graves_db") is not None and cp.get("definicion_graves_db") is not None:
        d_graves = round(ca["definicion_graves_db"] - cp["definicion_graves_db"], 1)
        signo = "+" if d_graves >= 0 else ""
        nota = " (bajo más definido)" if d_graves > 0.5 else (" (bajo menos definido)" if d_graves < -0.5 else "")
        lineas.append(f"  Definición de graves: {cp['definicion_graves_db']} → {ca['definicion_graves_db']} dB ({signo}{d_graves}){nota}")

    va = actual.get("vs_referencia") or {}
    vp = anterior.get("vs_referencia") or {}
    if va.get("delta_bandas_db") and vp.get("delta_bandas_db"):
        prom_a = sum(abs(v) for v in va["delta_bandas_db"].values()) / len(va["delta_bandas_db"])
        prom_p = sum(abs(v) for v in vp["delta_bandas_db"].values()) / len(vp["delta_bandas_db"])
        d_prom = round(prom_a - prom_p, 1)
        nota = " (más cerca de la referencia)" if d_prom < -0.3 else (" (más lejos de la referencia)" if d_prom > 0.3 else "")
        lineas.append(f"  Distancia promedio a la referencia: {prom_p:.1f} → {prom_a:.1f} dB{nota}")

    n_alertas_a, n_alertas_p = len(actual.get("alertas") or []), len(anterior.get("alertas") or [])
    if n_alertas_a != n_alertas_p:
        lineas.append(f"  Alertas: {n_alertas_p} → {n_alertas_a}")

    return "\n".join(lineas) if len(lineas) > 1 else None
