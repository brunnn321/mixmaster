"""Paquete de mejoras (.json): Bruno exporta sus ajustes de master y lo que la
app aprendió de sus votos, y quien usa MixMaster mini lo importa. Así la
versión del amigo mejora sin tocar el código ni reinstalar.
"""

import json
from pathlib import Path

from .app_paths import CONFIG_DIR

ARCHIVOS = {"master": CONFIG_DIR / "master.json",
            "aprendizaje": CONFIG_DIR / "aprendizaje.json"}


def _leer(ruta: Path) -> dict:
    return json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else {}


def _fusionar(base: dict, nuevo: dict) -> None:
    """Mezcla `nuevo` dentro de `base`: los dicts se combinan, el resto se reemplaza."""
    for k, v in nuevo.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _fusionar(base[k], v)
        else:
            base[k] = v


def exportar_paquete(destino: Path) -> None:
    """Guarda en un solo .json los ajustes del master y el aprendizaje."""
    paquete = {clave: _leer(ruta) for clave, ruta in ARCHIVOS.items()}
    Path(destino).write_text(json.dumps(paquete, indent=2, ensure_ascii=False), encoding="utf-8")


def aplicar_paquete(origen: Path) -> list[str]:
    """Aplica un paquete exportado. Devuelve qué partes se actualizaron."""
    paquete = _leer(Path(origen))
    if not isinstance(paquete, dict) or not set(paquete) & set(ARCHIVOS):
        raise ValueError("El archivo no es un paquete de mejoras de MixMaster.")
    hechas = []
    for clave, ruta in ARCHIVOS.items():
        if isinstance(paquete.get(clave), dict):
            actual = _leer(ruta)
            _fusionar(actual, paquete[clave])
            ruta.write_text(json.dumps(actual, indent=2, ensure_ascii=False), encoding="utf-8")
            hechas.append(clave)
    return hechas


if __name__ == "__main__":   # autocomprobación de la fusión
    b = {"a": {"x": 1, "y": 2}, "c": 3}
    _fusionar(b, {"a": {"y": 9}, "d": 4})
    assert b == {"a": {"x": 1, "y": 9}, "c": 3, "d": 4}, b
    print("ok")
