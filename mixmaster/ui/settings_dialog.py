"""Diálogo de Settings: ruta de proyectos y perfil de usuario."""

from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QHBoxLayout, QLineEdit, QPushButton,
)

from ..settings import Settings


class SettingsDialog(QDialog):
    """Edición de settings.json desde la UI."""

    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Settings — MixMaster")
        self.setMinimumWidth(480)

        form = QFormLayout(self)

        # Ruta de proyectos con botón examinar
        self.ed_ruta = QLineEdit(settings.get("ruta_proyectos"))
        btn_ruta = QPushButton("…")
        btn_ruta.setFixedWidth(30)
        btn_ruta.clicked.connect(self._elegir_ruta)
        fila_ruta = QHBoxLayout()
        fila_ruta.addWidget(self.ed_ruta)
        fila_ruta.addWidget(btn_ruta)
        form.addRow("Carpeta de proyectos:", fila_ruta)

        self.ed_perfil = QLineEdit(settings.get("perfil_usuario"))
        btn_perfil = QPushButton("…")
        btn_perfil.setFixedWidth(30)
        btn_perfil.clicked.connect(self._elegir_perfil)
        fila_perfil = QHBoxLayout()
        fila_perfil.addWidget(self.ed_perfil)
        fila_perfil.addWidget(btn_perfil)
        form.addRow("Perfil de usuario (.md):", fila_perfil)

        botones = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        botones.accepted.connect(self._guardar)
        botones.rejected.connect(self.reject)
        form.addRow(botones)

    def _elegir_ruta(self):
        """Selector de carpeta de proyectos."""
        ruta = QFileDialog.getExistingDirectory(self, "Carpeta de proyectos", self.ed_ruta.text())
        if ruta:
            self.ed_ruta.setText(ruta)

    def _elegir_perfil(self):
        """Selector del archivo de perfil de usuario."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Perfil de usuario", "", "Markdown (*.md);;Todos (*.*)")
        if path:
            self.ed_perfil.setText(path)

    def _guardar(self):
        """Persiste los cambios en settings.json y cierra."""
        s = self.settings
        s.set("ruta_proyectos", self.ed_ruta.text().strip())
        s.set("perfil_usuario", self.ed_perfil.text().strip())
        self.accept()
