"""MixMaster v0.1 — punto de entrada.

Uso:  python main.py
"""

import sys

from mixmaster.app_paths import ensure_app_dirs
from mixmaster.logger import get_logger

log = get_logger("mixmaster.main")


def main() -> int:
    """Arranca la app: settings, primera configuración si toca, ventana."""
    ensure_app_dirs()

    from PySide6.QtWidgets import QApplication

    from mixmaster.settings import Settings
    from mixmaster.ui.first_run import ejecutar_primera_configuracion
    from mixmaster.ui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("MixMaster")

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
