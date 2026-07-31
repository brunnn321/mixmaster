"""Test del detector de bounces del DAW (sin UI, sin pytest).

Uso:  .venv\\Scripts\\python tests\\test_daw_watch.py
"""

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mixmaster.daw_watch import DetectorBounces, listar_audios
from mixmaster.project import Project


def escribir(path: Path, n_bytes: int) -> None:
    path.write_bytes(b"\0" * n_bytes)


def main() -> int:
    fallos = []

    def check(nombre: str, cond: bool, detalle: str = ""):
        estado = "OK " if cond else "FAIL"
        print(f"[{estado}] {nombre}" + (f" — {detalle}" if detalle else ""))
        if not cond:
            fallos.append(nombre)

    tmp = Path(tempfile.mkdtemp(prefix="mixmaster_daw_"))
    try:
        carpeta = tmp / "bounces"
        carpeta.mkdir()

        # --- listar_audios: solo audio, con tamaños ---
        escribir(carpeta / "viejo.wav", 100)
        escribir(carpeta / "notas.txt", 50)
        audios = listar_audios(carpeta)
        check("listar_audios: solo cuenta audio", set(audios) == {"viejo.wav"}, str(audios))
        check("listar_audios: reporta el tamaño", audios["viejo.wav"] == 100)
        check("listar_audios: carpeta inexistente no explota",
              listar_audios(tmp / "no_existe") == {})

        # --- lo que ya estaba NO se reporta como nuevo ---
        det = DetectorBounces(carpeta)
        check("detector: lo preexistente no es un bounce nuevo", det.revisar() == [])

        # --- archivo a medio escribir: NO se reporta hasta estabilizarse ---
        bounce = carpeta / "MIX_v3.wav"
        escribir(bounce, 500)                 # el DAW arrancó a escribir
        check("detector: no reporta un archivo recién aparecido (puede estar a medias)",
              det.revisar() == [])
        escribir(bounce, 2000)                # sigue creciendo
        check("detector: sigue sin reportar mientras el tamaño cambia",
              det.revisar() == [])
        # ahora el tamaño se mantiene → el DAW terminó
        listos = det.revisar()
        check("detector: reporta cuando el tamaño se estabiliza",
              [p.name for p in listos] == ["MIX_v3.wav"], str(listos))
        check("detector: no lo reporta dos veces", det.revisar() == [])

        # --- archivo de 0 bytes nunca se reporta ---
        vacio = carpeta / "vacio.wav"
        escribir(vacio, 0)
        det.revisar()
        check("detector: ignora un archivo de 0 bytes", det.revisar() == [])

        # --- re-exportar con el MISMO nombre vuelve a avisar ---
        bounce.unlink()
        det.revisar()                          # nota que desapareció
        escribir(bounce, 3000)
        det.revisar()                          # primera vista del nuevo
        listos2 = det.revisar()                # ya estable
        check("detector: re-exportar el mismo nombre vuelve a avisar",
              [p.name for p in listos2] == ["MIX_v3.wav"], str(listos2))

        # --- cambiar de carpeta reinicia el estado ---
        otra = tmp / "otra"
        otra.mkdir()
        escribir(otra / "preexistente.wav", 100)
        det.cambiar_carpeta(otra)
        check("detector: al cambiar de carpeta lo preexistente no es nuevo",
              det.revisar() == [])

        # --- config por proyecto: guarda y relee la carpeta del DAW ---
        proy = Project(tmp / "proyecto_test")
        proy.root.mkdir(parents=True, exist_ok=True)
        check("proyecto: sin config, carpeta_daw es None", proy.carpeta_daw is None)
        proy.set_config("carpeta_daw", str(carpeta))
        check("proyecto: guarda y relee la carpeta del DAW",
              proy.carpeta_daw == carpeta, str(proy.carpeta_daw))
        # releer desde otra instancia (persistió en disco, no en memoria)
        proy2 = Project(tmp / "proyecto_test")
        check("proyecto: la config persiste en disco",
              proy2.carpeta_daw == carpeta, str(proy2.carpeta_daw))
        proy2.set_config("otra_clave", 42)
        check("proyecto: setear otra clave no pisa la anterior",
              proy2.carpeta_daw == carpeta and proy2.leer_config()["otra_clave"] == 42)
        # config corrupta no explota
        proy2.config_path.write_text("{ esto no es json", encoding="utf-8")
        check("proyecto: config corrupta no explota", proy2.leer_config() == {})

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if fallos:
        print(f"RESULTADO: {len(fallos)} fallo(s): {fallos}")
        return 1
    print("RESULTADO: todos los checks pasaron")
    return 0


if __name__ == "__main__":
    sys.exit(main())
