"""Resumen de la biblioteca: lee todos los informes (analisis.jsonl) y escribe
resumen.md enfocado en DÓNDE SE EQUIVOCA LA APP frente a masters profesionales:
reglas de zonas que saltan en temas buenos, chequeos de calidad que dan falsas
alarmas, y volumen/dinámica reales contra los valores por defecto. El detalle
canción por canción sigue completo en analisis.jsonl.
"""

import json
from collections import defaultdict
from datetime import datetime

import numpy as np

from .biblioteca import ARCHIVO
from .qc import NORMAS

RESUMEN = ARCHIVO.with_name("resumen.md")
NORMAS_SUGERIDAS = ARCHIVO.with_name("normas_sugeridas.json")


def _valores(inf: dict) -> dict:
    """Las medidas de un informe, sea completo (con diagnóstico) o básico viejo."""
    g = (inf.get("diagnostico") or {}).get("global") or {}
    est = (inf.get("diagnostico") or {}).get("estereo") or {}
    return {
        "lufs": g.get("lufs_i", inf.get("lufs")),
        "tp": g.get("true_peak_db", inf.get("true_peak_db")),
        "crest": g.get("crest_factor_db", inf.get("crest_db")),
        "corr": est.get("correlacion_global", inf.get("correlacion")),
        "zonas": inf.get("zonas_db") or {},
        "qc": {c["nombre"]: c["estado"] for c in inf.get("qc") or []},
        # si Bruno escribió el género, se agrupa por género; si no, por carpeta
        "grupo": inf.get("genero") or " / ".join(inf.get("carpetas") or []) or "(sin carpeta)",
    }


def _med(xs):
    xs = [x for x in xs if isinstance(x, (int, float)) and np.isfinite(x)]
    return (float(np.median(xs)), float(np.percentile(xs, 10)), float(np.percentile(xs, 90))) if xs else None


def resumir() -> str:
    """Escribe resumen.md y normas_sugeridas.json. Devuelve la ruta del resumen."""
    informes = []
    if ARCHIVO.exists():
        for linea in ARCHIVO.read_text(encoding="utf-8").splitlines():
            try:
                informes.append(json.loads(linea))
            except Exception:
                continue
    # si un tema se analizó dos veces (básico y completo), vale el último
    por_ruta = {inf["ruta"]: inf for inf in informes}
    vals = [_valores(i) for i in por_ruta.values()]
    n = len(vals)
    L = [f"# Resumen de la biblioteca — {datetime.now():%d/%m/%Y %H:%M}", "",
         f"**{n} temas analizados.** Detalle completo de cada uno en `{ARCHIVO.name}`.", ""]
    if not n:
        L.append("Todavía no hay informes.")
        RESUMEN.write_text("\n".join(L), encoding="utf-8")
        return str(RESUMEN)

    L += ["## 1. Dónde se equivoca la app", "",
          "### Zonas: ¿cuántos masters profesionales marcaría como problema?",
          "Un master profesional casi nunca debería saltar (lo esperable es menos del 5 %). "
          "Si una zona salta mucho, su norma está mal calibrada.", "",
          "| Zona | Saltan | Norma actual (media ± desvío) | Norma medida en tu biblioteca | Veredicto |",
          "|---|---|---|---|---|"]
    sugeridas = {}
    for zona, (media, desv) in NORMAS.items():
        xs = [v["zonas"][zona] for v in vals if zona in v["zonas"]]
        if not xs:
            continue
        saltan = sum(x > media + 2 * desv for x in xs) / len(xs) * 100
        m, s = float(np.mean(xs)), float(np.std(xs))
        sugeridas[zona] = [round(m, 1), round(max(s, 0.5), 1)]
        veredicto = "mal calibrada: corrige de más" if saltan > 10 else ("revisar" if saltan > 5 else "bien")
        L.append(f"| {zona} | {saltan:.0f} % | {media:+.1f} ± {desv:.1f} | {m:+.1f} ± {s:.1f} | {veredicto} |")

    L += ["", "### Control de calidad: falsas alarmas en masters profesionales",
          "Lo esperable en música publicada es verde casi siempre.", "",
          "| Chequeo | Verde | Aviso | Mal |", "|---|---|---|---|"]
    conteo = defaultdict(lambda: defaultdict(int))
    for v in vals:
        for nombre, estado in v["qc"].items():
            conteo[nombre][estado] += 1
    for nombre, c in conteo.items():
        tot = sum(c.values()) or 1
        L.append(f"| {nombre} | {c['ok'] / tot * 100:.0f} % | {c['aviso'] / tot * 100:.0f} % | {c['mal'] / tot * 100:.0f} % |")

    L += ["", "### Volumen y dinámica reales (mediana, del 10 % al 90 %)", ""]
    for clave, nombre, unidad in (("lufs", "Volumen", "LUFS"), ("crest", "Crest (dinámica)", "dB"),
                                  ("tp", "Pico real", "dBTP"), ("corr", "Correlación estéreo", "")):
        r = _med([v[clave] for v in vals])
        if r:
            L.append(f"- **{nombre}:** {r[0]:.1f} {unidad} (de {r[1]:.1f} a {r[2]:.1f})")
    L.append("- La app usa por defecto: −10,5 LUFS (tu zona aprobada), techo −1 dBTP y crest objetivo ~10 dB.")

    L += ["", "## 2. Por género (o carpeta, si no tiene género)", "",
          "| Carpeta | Temas | LUFS | Crest | Pico | Correl. | Retumbe | Barro | Encajonado | Aspereza | Sibilancia |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    grupos = defaultdict(list)
    for v in vals:
        grupos[v["grupo"]].append(v)
    for grupo, vs in sorted(grupos.items(), key=lambda kv: -len(kv[1])):
        def m(clave):
            r = _med([v[clave] for v in vs])
            return f"{r[0]:.1f}" if r else "—"
        def z(zona):
            r = _med([v["zonas"].get(zona) for v in vs])
            return f"{r[0]:+.1f}" if r else "—"
        L.append(f"| {grupo} | {len(vs)} | {m('lufs')} | {m('crest')} | {m('tp')} | {m('corr')} | "
                 f"{z('retumbe')} | {z('embarrado')} | {z('encajonado')} | {z('aspero')} | {z('sibilante')} |")

    L += ["", "---", f"Normas sugeridas guardadas en `{NORMAS_SUGERIDAS.name}` (no se aplican solas: "
          "se revisan juntas antes de cambiar la app)."]
    RESUMEN.write_text("\n".join(L), encoding="utf-8")
    NORMAS_SUGERIDAS.write_text(json.dumps(sugeridas, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(RESUMEN)


if __name__ == "__main__":
    print(resumir())
