"""Guardado del diagnóstico (JSON de formato fijo) y reporte legible."""

import json
from pathlib import Path

from .logger import get_logger
from .project import Project

log = get_logger("mixmaster.report")


def guardar_diagnostico(proyecto: Project, diag: dict) -> tuple[Path, Path]:
    """Escribe diagnostico_<version>.json y diagnostico_legible.txt en 04_analisis."""
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
    lineas += ["", "— BALANCE ESPECTRAL (dB RMS por banda) —"]
    for banda, valor in diag["bandas_db"].items():
        lineas.append(f"  {banda:<9} {valor}")

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
