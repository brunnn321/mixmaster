"""Corre el pipeline de master sobre un lote de mezclas y vuelca métricas a CSV.

Para qué: la tanda del 2026-08-09 fueron 20 masters a mano por la UI, 68
minutos de reloj, y las métricas quedaron enterradas en logs/app.log. Esto
hace lo mismo desatendido y deja una tabla comparable entre versiones: se
corre antes y después de tocar el DSP y se miran las diferencias.

No reemplaza escuchar. Mide lo medible (loudness, techo, crest, score de
similitud, cuántos notches se pisan); el juicio de oído va aparte.

Ejemplos
--------
    # lote básico, una carpeta de mezclas
    .venv\\Scripts\\python tools\\batch_regresion.py "E:\\mezclas" -o base.csv

    # con referencia y variando UN parámetro (el resto igual)
    .venv\\Scripts\\python tools\\batch_regresion.py "E:\\mezclas" --ref "ref.mp3" \\
        --set transient_shaping.cantidad=0.4 -o transient040.csv

    # comparar contra una corrida anterior
    .venv\\Scripts\\python tools\\batch_regresion.py "E:\\mezclas" -o nuevo.csv \\
        --comparar base.csv
"""

import argparse
import csv
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mixmaster.processing import cargar_config_master, masterizar

EXTS = {".wav", ".flac", ".aiff", ".aif", ".mp3", ".ogg", ".m4a"}
RAZON_MIN = 2 ** (1 / 6)  # misma separación mínima que detectar_resonancias

COLUMNAS = [
    "archivo", "referencia", "target_lufs", "lufs_final", "desv_lufs",
    "true_peak_final", "sobre_techo", "crest_final", "convergio_target",
    "score_global", "score_tonal", "score_dinamica", "score_imagen",
    "eq_max_db", "eq_en_tope", "n_resonancias", "resonancias_pegadas",
    "densidad", "segundos", "error",
]


def mezclas_de(entradas: list[str]) -> list[Path]:
    """Expande archivos y carpetas a una lista ordenada de audios."""
    salida = []
    for e in entradas:
        p = Path(e)
        if p.is_dir():
            salida += [q for q in sorted(p.iterdir())
                       if q.suffix.lower() in EXTS and q.is_file()]
        elif p.is_file() and p.suffix.lower() in EXTS:
            salida.append(p)
        else:
            print(f"  (ignorado, no es audio ni carpeta: {p})")
    return salida


def aplicar_overrides(cfg: dict, overrides: list[str]) -> dict:
    """--set seccion.clave=valor sobre el cfg (para variar un parámetro por tanda)."""
    for ov in overrides:
        if "=" not in ov:
            raise SystemExit(f"--set mal formado (falta '='): {ov}")
        ruta, valor = ov.split("=", 1)
        partes = ruta.split(".")
        nodo = cfg
        for k in partes[:-1]:
            if k not in nodo or not isinstance(nodo[k], dict):
                raise SystemExit(f"--set: no existe la sección '{k}' en {ruta}")
            nodo = nodo[k]
        if partes[-1] not in nodo:
            raise SystemExit(f"--set: no existe la clave '{partes[-1]}' en {ruta}")
        try:
            nodo[partes[-1]] = json.loads(valor)  # números, true/false, listas
        except json.JSONDecodeError:
            nodo[partes[-1]] = valor
    return cfg


def resonancias_pegadas(resonancias: list[dict]) -> int:
    """Cuántos notches caen a menos de 1/6 de octava de otro (slots gastados)."""
    fs = sorted(r["freq"] for r in resonancias or [])
    return sum(1 for a, b in zip(fs, fs[1:]) if a > 0 and b / a < RAZON_MIN)


def fila_de(resumen: dict, mezcla: Path, ref: Path | None, target: float,
            techo: float, segundos: float) -> dict:
    eq = resumen.get("eq_aplicado_db") or {}
    eq_max = max((abs(v) for v in eq.values()), default=0.0)
    score = resumen.get("score") or {}
    tp = resumen.get("true_peak_final")
    return {
        "archivo": mezcla.name,
        "referencia": ref.name if ref else "",
        "target_lufs": target,
        "lufs_final": resumen.get("lufs_final"),
        "desv_lufs": round((resumen.get("lufs_final") or 0) - target, 2),
        "true_peak_final": tp,
        "sobre_techo": int(tp is not None and tp > techo + 0.1),
        "crest_final": resumen.get("crest_final"),
        "convergio_target": int(bool(resumen.get("convergio_target", True))),
        "score_global": score.get("global", ""),
        "score_tonal": score.get("tonal", ""),
        "score_dinamica": score.get("dinamica", ""),
        "score_imagen": score.get("imagen", ""),
        "eq_max_db": round(eq_max, 1),
        # el matching tiene tope de ±4 dB: pegarse al tope = se quedó corto
        "eq_en_tope": int(eq_max >= 3.5),
        "n_resonancias": len(resumen.get("resonancias_db") or []),
        "resonancias_pegadas": resonancias_pegadas(resumen.get("resonancias_db")),
        "densidad": int(bool(resumen.get("densidad_aplicada"))),
        "segundos": round(segundos, 1),
        "error": "",
    }


def resumir(filas: list[dict], techo: float) -> None:
    ok = [f for f in filas if not f["error"]]
    if not ok:
        print("\nSin corridas exitosas.")
        return
    desv = [f["desv_lufs"] for f in ok]
    print(f"\n--- Resumen ({len(ok)}/{len(filas)} sin error) ---")
    print(f"  desviación de loudness: media {sum(desv) / len(desv):+.2f} LU  "
          f"(peor {max(desv, key=abs):+.2f})  ·  "
          f"{sum(1 for d in desv if d < -0.15)} por debajo de la ventana")
    print(f"  sobre el techo de {techo:g} dBTP: {sum(f['sobre_techo'] for f in ok)}")
    print(f"  no convergieron al target: {sum(1 - f['convergio_target'] for f in ok)}")
    print(f"  con notches pisados: {sum(1 for f in ok if f['resonancias_pegadas'])}")
    print(f"  con EQ pegado al tope: {sum(f['eq_en_tope'] for f in ok)}")
    con_score = [f["score_global"] for f in ok if f["score_global"] != ""]
    if con_score:
        print(f"  score global: media {sum(con_score) / len(con_score):.1f}  "
              f"(min {min(con_score)}, max {max(con_score)})  "
              f"sobre {len(con_score)} con referencia")
    print(f"  tiempo total: {sum(f['segundos'] for f in ok) / 60:.1f} min")


def comparar(filas: list[dict], previo: Path) -> None:
    """Diferencias por pista contra una corrida anterior (misma métrica clave)."""
    with previo.open(encoding="utf-8", newline="") as fh:
        antes = {r["archivo"]: r for r in csv.DictReader(fh)}
    print(f"\n--- Contra {previo.name} ---")
    hubo = False
    for f in filas:
        a = antes.get(f["archivo"])
        if not a or f["error"]:
            continue
        deltas = []
        for col, fmt in (("lufs_final", "%+.2f"), ("crest_final", "%+.2f"),
                         ("score_global", "%+.0f"), ("resonancias_pegadas", "%+.0f")):
            try:
                d = float(f[col]) - float(a[col])
            except (TypeError, ValueError):
                continue
            if abs(d) >= 0.05:
                deltas.append(f"{col} {fmt % d}")
        if deltas:
            hubo = True
            print(f"  {f['archivo'][:45]:<45} {', '.join(deltas)}")
    if not hubo:
        print("  sin cambios relevantes")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("entradas", nargs="+", help="archivos y/o carpetas de mezclas")
    ap.add_argument("--ref", help="referencia (un archivo, la misma para todas)")
    ap.add_argument("--target", type=float, default=-9.0, help="LUFS objetivo")
    ap.add_argument("-o", "--salida", default="regresion.csv", help="CSV de salida")
    ap.add_argument("--set", dest="overrides", action="append", default=[],
                    metavar="SECCION.CLAVE=VALOR",
                    help="varía un parámetro del master (repetible)")
    ap.add_argument("--limite", type=int, help="cortar a las N primeras mezclas")
    ap.add_argument("--comparar", type=Path, help="CSV de una corrida anterior")
    ap.add_argument("--guardar-audio", type=Path,
                    help="carpeta donde dejar los masters (por defecto se tiran)")
    args = ap.parse_args()

    mezclas = mezclas_de(args.entradas)
    if args.limite:
        mezclas = mezclas[:args.limite]
    if not mezclas:
        raise SystemExit("No se encontró ninguna mezcla en las entradas dadas.")

    ref = Path(args.ref) if args.ref else None
    if ref and not ref.exists():
        raise SystemExit(f"La referencia no existe: {ref}")

    cfg = aplicar_overrides(cargar_config_master(), args.overrides)
    techo = float(cfg["limitador"]["ceiling_dbtp"])

    print(f"{len(mezclas)} mezcla(s) · target {args.target} LUFS · "
          f"referencia: {ref.name if ref else 'ninguna'}")
    if args.overrides:
        print(f"overrides: {', '.join(args.overrides)}")

    tmp = Path(tempfile.mkdtemp(prefix="mixmaster_batch_"))
    destino = args.guardar_audio or tmp
    destino.mkdir(parents=True, exist_ok=True)
    filas = []
    try:
        for i, mezcla in enumerate(mezclas, 1):
            print(f"[{i}/{len(mezclas)}] {mezcla.name}… ", end="", flush=True)
            t0 = time.monotonic()
            try:
                resumen = masterizar(
                    path_mezcla=mezcla, path_referencia=ref,
                    target_lufs=args.target,
                    dir_masters=destino / "masters",
                    dir_entregables=destino / "mp3",
                    version="v01", cfg=json.loads(json.dumps(cfg)),
                )
                fila = fila_de(resumen, mezcla, ref, args.target, techo,
                               time.monotonic() - t0)
                print(f"{fila['lufs_final']} LUFS · {fila['true_peak_final']} dBTP · "
                      f"crest {fila['crest_final']} · {fila['segundos']}s"
                      + ("  ⚠ SOBRE EL TECHO" if fila["sobre_techo"] else "")
                      + ("  ⚠ no convergió" if not fila["convergio_target"] else ""))
            except Exception as e:  # una pista rota no debe cortar el lote
                fila = {c: "" for c in COLUMNAS}
                fila.update(archivo=mezcla.name, error=str(e)[:200],
                            segundos=round(time.monotonic() - t0, 1))
                print(f"ERROR: {e}")
            filas.append(fila)
    finally:
        if destino is tmp or destino == tmp:
            shutil.rmtree(tmp, ignore_errors=True)

    salida = Path(args.salida)
    with salida.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNAS)
        w.writeheader()
        w.writerows(filas)
    print(f"\nCSV: {salida.resolve()}")

    resumir(filas, techo)
    if args.comparar:
        comparar(filas, args.comparar)
    return 1 if any(f["error"] or f["sobre_techo"] for f in filas) else 0


if __name__ == "__main__":
    sys.exit(main())
