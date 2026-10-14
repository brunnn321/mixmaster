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


def _al_frente_cuando_aparezca(nombre: str, segundos: float = 4.0):
    """Busca la ventana del Explorador de esa carpeta y la trae al frente.

    Ceder el foreground no alcanza: si el Explorador ya estaba abierto, la ventana
    nueva la crea ese proceso viejo, que no recibió el permiso, y queda detrás de
    MixMaster (pasaba en el modo voz). Se busca la ventana por título durante unos
    segundos, en un hilo aparte para no trabar la interfaz.
    """
    if sys.platform != "win32" or not nombre:
        return
    import ctypes
    import threading
    import time
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    PROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def buscar():
        fin = time.time() + segundos
        while time.time() < fin:
            hallada = []

            def ver(hwnd, _):
                if not user32.IsWindowVisible(hwnd):
                    return True
                clase = ctypes.create_unicode_buffer(64)
                user32.GetClassNameW(hwnd, clase, 64)
                if clase.value != "CabinetWClass":
                    return True
                n = user32.GetWindowTextLengthW(hwnd)
                titulo = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, titulo, n + 1)
                if nombre.lower() in titulo.value.lower():
                    hallada.append(hwnd)
                    return False
                return True

            user32.EnumWindows(PROC(ver), 0)
            if hallada:
                # una pulsación de ALT habilita SetForegroundWindow desde un proceso de fondo
                user32.keybd_event(0x12, 0, 0, 0)
                user32.keybd_event(0x12, 0, 2, 0)
                user32.ShowWindow(hallada[0], 9)          # SW_RESTORE
                user32.SetForegroundWindow(hallada[0])
                return
            time.sleep(0.15)
        log.debug("No apareció la ventana del Explorador de %s", nombre)

    threading.Thread(target=buscar, daemon=True).start()


def abrir(ruta) -> None:
    """Abre una carpeta o un archivo con la aplicación del sistema, al frente."""
    ruta = Path(ruta)
    _ceder_foreground()
    if sys.platform == "win32":
        if ruta.is_dir():
            subprocess.Popen(["explorer", str(ruta)])
            _al_frente_cuando_aparezca(ruta.name)
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
    _al_frente_cuando_aparezca(archivo.parent.name)
