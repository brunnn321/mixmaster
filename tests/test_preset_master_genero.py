"""El bloque `master` del preset de género pisa la config global. Sin pytest.

Regresión real (2026-09-15, them_bones2): se masterizó un tema de grunge con
los parámetros de math rock — tope de matching ±6 dB y notches de -3 dB en
554/829/1254 Hz, justo sobre el cuerpo de la voz y del riff — porque el género
solo definía umbrales de alerta y el pipeline leía siempre config/master.json.

Uso:  .venv\Scripts\python tests\test_preset_master_genero.py
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mixmaster import processing, profiles
from mixmaster.processing import cargar_config_master


def _escribir_genero(generos_dir: Path, slug: str, preset: dict) -> None:
    (generos_dir / f"{slug}.md").write_text(f"# Género {slug}", encoding="utf-8")
    (generos_dir / f"{slug}.json").write_text(
        json.dumps(preset, ensure_ascii=False), encoding="utf-8")


def main() -> int:
    fallos = []

    def check(nombre: str, cond: bool, detalle: str = ""):
        estado = "OK " if cond else "FAIL"
        print(f"[{estado}] {nombre}" + (f" — {detalle}" if detalle else ""))
        if not cond:
            fallos.append(nombre)

    generos_original = profiles.GENEROS_DIR
    master_original = processing.MASTER_CONFIG_FILE
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        generos = tmp / "generos"
        generos.mkdir()
        profiles.GENEROS_DIR = generos
        processing.MASTER_CONFIG_FILE = tmp / "master.json"
        try:
            _escribir_genero(generos, "con_master", {
                "nombre": "Con master",
                "master": {
                    "target_lufs_default": -10.5,
                    "eq_correctivo": {"max_correccion_db": 10.0},
                    "resonancias": {"max_cut_db": 2.0},
                },
            })
            _escribir_genero(generos, "sin_master",
                             {"nombre": "Sin master", "crest_min_db": 9.0})

            base = cargar_config_master()
            cfg = cargar_config_master("con_master")

            check("el género pisa el loudness por defecto",
                  cfg["target_lufs_default"] == -10.5, str(cfg["target_lufs_default"]))
            check("el género pisa el tope de matching",
                  cfg["eq_correctivo"]["max_correccion_db"] == 10.0,
                  str(cfg["eq_correctivo"]["max_correccion_db"]))
            check("el género pisa el corte de resonancias",
                  cfg["resonancias"]["max_cut_db"] == 2.0,
                  str(cfg["resonancias"]["max_cut_db"]))
            check("lo que el género NO define se hereda de la config global",
                  cfg["eq_correctivo"]["activo"] is True
                  and cfg["limitador"]["ceiling_dbtp"] == -1.0
                  and cfg["resonancias"]["umbral_db"] == base["resonancias"]["umbral_db"])
            check("la config global no quedó contaminada",
                  cargar_config_master() == base)
            check("género sin bloque master: config global intacta",
                  cargar_config_master("sin_master") == base)
            check("género inexistente: no rompe, usa la config global",
                  cargar_config_master("no_existe") == base)
        finally:
            profiles.GENEROS_DIR = generos_original
            processing.MASTER_CONFIG_FILE = master_original

    # los dos géneros reales del repo traen su bloque master
    for slug, tope in (("grunge", 10.0), ("math_rock", 6.0)):
        _, preset = profiles.leer_genero(slug)
        cfg = cargar_config_master(slug)
        check(f"{slug}: preset con bloque master",
              bool(preset.get("master")))
        check(f"{slug}: tope de matching {tope:g} dB",
              cfg["eq_correctivo"]["max_correccion_db"] == tope,
              str(cfg["eq_correctivo"]["max_correccion_db"]))

    print()
    if fallos:
        print(f"RESULTADO: {len(fallos)} fallo(s): {fallos}")
        return 1
    print("RESULTADO: todos los checks pasaron")
    return 0


if __name__ == "__main__":
    sys.exit(main())
