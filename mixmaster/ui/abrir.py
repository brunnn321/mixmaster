"""Abrir carpetas y archivos con la app del sistema, AL FRENTE.

Problema real (roadmap, "Fixes de UX"): al terminar un master, `os.startfile`
abría la carpeta de salida detrás de la ventana de MixMaster. Windows solo
deja que un proceso nuevo pase al frente si quien lo lanza le cede el permiso
de foreground; sin eso, el Explorador se abre pero queda tapado.
"""

import os
import subprocess
import sys
from pathlib import Path

from ..logger import get_logger

log = get_logger("mixmaster.ui.abrir")

_ASFW_ANY = -1  # AllowSetForegroundWindow: cualquier proceso puede pasar al frente


def _ceder_foreground():
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.user32.AllowSetForegroundWindow(_ASFW_ANY)
    except Exception:
        log.debug("AllowSetForegroundWindow no disponible")


def abrir(ruta) -> None:
    """Abre una carpeta o un archivo con la aplicación del sistema, al frente."""
    ruta = Path(ruta)
    _ceder_foreground()
    if sys.platform == "win32":
        if ruta.is_dir():
            subprocess.Popen(["explorer", str(ruta)])
        else:
            os.startfile(str(ruta))  # noqa: S606 — archivo local
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(ruta)])
    else:
        subprocess.Popen(["xdg-open", str(ruta)])


def mostrar_en_carpeta(archivo) -> None:
    """Abre la carpeta del archivo con el archivo ya seleccionado, al frente."""
    archivo = Path(archivo)
    if sys.platform != "win32" or not archivo.exists():
        abrir(archivo.parent)
        return
    _ceder_foreground()
    # Como string y no lista: explorer no acepta /select, con la ruta entre
    # comillas pegadas al argumento, que es lo que arma Popen con espacios.
    subprocess.Popen(f'explorer /select,"{archivo}"')
