"""MixMaster v0.1 — punto de entrada.

Uso:  python main.py
"""

import faulthandler
import sys

from mixmaster.app_paths import ensure_app_dirs, LOGS_DIR
from mixmaster.logger import get_logger

log = get_logger("mixmaster.main")

_instancia_lock = None  # QSharedMemory que mantiene vivo el candado de instancia única

# Crashes nativos (segfault de Qt/audio) no pasan por logging normal —
# faulthandler vuelca el traceback de bajo nivel a este archivo aparte.
LOGS_DIR.mkdir(parents=True, exist_ok=True)
_crash_log = open(LOGS_DIR / "crash.log", "a", encoding="utf-8")
faulthandler.enable(file=_crash_log)


def main() -> int:
    """Arranca la app: settings, primera configuración si toca, ventana."""
    ensure_app_dirs()

    # Windows: identidad propia de la app (si no, las notificaciones dicen "Python").
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Anthropic.MixMaster")
        except Exception:
            log.debug("No se pudo fijar el AppUserModelID de Windows")

    from PySide6.QtWidgets import QApplication

    from mixmaster.settings import Settings
    from mixmaster.ui.first_run import ejecutar_primera_configuracion
    from mixmaster.ui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("MixMaster")
    app.setApplicationDisplayName("MixMaster")

    # Instancia única: si ya hay una abierta, avisar y salir (no abrir otra).
    from PySide6.QtCore import QSharedMemory
    global _instancia_lock
    _instancia_lock = QSharedMemory("MixMaster_SingleInstance_v1")
    if not _instancia_lock.create(1):
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(
            None, "MixMaster",
            "MixMaster ya se está ejecutando.\nBusca la ventana abierta.")
        log.info("Segunda instancia bloqueada — ya hay una abierta")
        return 0

    from pathlib import Path

    from PySide6.QtGui import QIcon
    icono = Path(__file__).parent / "assets" / "icon.ico"
    if icono.exists():
        app.setWindowIcon(QIcon(str(icono)))

    settings = Settings()

    ventana = MainWindow(settings)

    if settings.get("primera_ejecucion", True):
        ejecutar_primera_configuracion(ventana, settings)
        ventana._refrescar_estado()

    ventana.show()
    log.info("MixMaster iniciado")
    return app.exec()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        log.exception("Error fatal al iniciar MixMaster")
        raise
