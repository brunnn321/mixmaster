"""Diario de sesión (v0.9+): notas libres por proyecto, guardadas en
notas-sesion.md dentro de la carpeta del proyecto.
"""

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QTextEdit, QVBoxLayout

from ..logger import get_logger

log = get_logger("mixmaster.ui.notas")

NOTAS_MD = "notas-sesion.md"


class NotasDialog(QDialog):
    """Editor simple de notas de sesión del proyecto activo."""

    def __init__(self, proyecto, parent=None):
        super().__init__(parent)
        self.proyecto = proyecto
        self.setWindowTitle(f"📝 Notas de sesión — {proyecto.nombre}")
        self.resize(480, 400)

        lay = QVBoxLayout(self)
        self.txt = QTextEdit()
        self.txt.setPlaceholderText(
            "Anota lo que hiciste hoy: decisiones, pendientes, ideas…\n"
            "Ej: até el bajo con el kick, falta aire en hi-hats, probar -8 LUFS")
        ruta = self.proyecto.root / NOTAS_MD
        if ruta.exists():
            try:
                self.txt.setPlainText(ruta.read_text(encoding="utf-8"))
            except Exception:
                log.exception("No se pudieron leer las notas de sesión")
        lay.addWidget(self.txt)

        botones = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Close)
        botones.accepted.connect(self._guardar_y_cerrar)
        botones.rejected.connect(self.reject)
        lay.addWidget(botones)

    def _guardar_y_cerrar(self):
        try:
            ruta = self.proyecto.root / NOTAS_MD
            ruta.write_text(self.txt.toPlainText(), encoding="utf-8")
            log.info("Notas de sesión guardadas: %s", ruta)
        except Exception:
            log.exception("No se pudieron guardar las notas de sesión")
        self.accept()
