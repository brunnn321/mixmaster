"""Verifica que la UI (asistente de 3 pasos) se construye sin errores.

Uso:  .venv\\Scripts\\python tests\\test_ui_offscreen.py
"""

import os
import sys
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication

from mixmaster.settings import Settings
from mixmaster.ui.chat_dialog import ChatDialog
from mixmaster.ui.main_window import MainWindow
from mixmaster.ui.settings_dialog import SettingsDialog


def main() -> int:
    app = QApplication(sys.argv)
    settings = Settings()

    ventana = MainWindow(settings)
    assert ventana.pila.count() == 3  # asistente de 3 pasos
    assert ventana.menuBar() is not None
    print("[OK] MainWindow (asistente de 3 pasos) construida")

    # Sin proyecto: los botones de trabajo deshabilitados y guía de arranque
    if ventana.proyecto is None:
        assert not ventana.btn_cargar.isEnabled()
        assert "Nuevo proyecto" in ventana.lbl_guia.text()
        print("[OK] Estado sin proyecto correcto")
    else:
        print(f"[OK] Reabrió último proyecto: {ventana.proyecto.nombre}")

    dlg = SettingsDialog(settings, ventana)
    assert dlg.ed_modelo.text() != ""
    assert dlg.cb_genero.count() >= 2
    print("[OK] SettingsDialog construido (combo de género poblado)")

    chat = ChatDialog(ventana)
    ctx = chat._contexto("hola")
    assert "PERFIL DE USUARIO" in ctx and "PERFIL DE GÉNERO" in ctx
    print("[OK] ChatDialog construido, contexto usuario + género")

    print("RESULTADO: UI instanciada correctamente")
    return 0


if __name__ == "__main__":
    sys.exit(main())
