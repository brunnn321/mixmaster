"""Quita de la copia del instalador mini los bloques marcados como
herramientas en desarrollo (# <herramientas> … # </herramientas>) y
comprueba que lo que queda compila y ya no las nombra.

Uso:  python instalador/limpiar_mini.py <carpeta de la app copiada>
"""

import py_compile
import re
import sys
from pathlib import Path

BLOQUE = re.compile(r"^[ \t]*# <herramientas>.*?^[ \t]*# </herramientas>[ \t]*\n", re.M | re.S)
NOMBRES = re.compile(r"_abrir_tempo|tempo_dialog|Tempo Genius|null_test|ab_ciego|convertidor|"
                     r"arbol_generos|consola_web|notas_dialog")

app = Path(sys.argv[1])
for py in app.rglob("*.py"):
    if "python" in py.relative_to(app).parts[:1]:
        continue   # el Python portátil no se toca
    texto = py.read_text(encoding="utf-8")
    limpio = BLOQUE.sub("", texto)
    if limpio != texto:
        py.write_text(limpio, encoding="utf-8")
        print("limpio:", py.relative_to(app))
    py_compile.compile(str(py), doraise=True)
    sobra = NOMBRES.findall(limpio)
    assert not sobra, f"{py.relative_to(app)} todavía nombra {set(sobra)}"
print("ok")
