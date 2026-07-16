"""Pantalla de inicio (estilo Studio Pro): proyecto reciente o nuevo."""

from datetime import datetime
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QListWidget, QPushButton, QVBoxLayout,
)


class InicioDialog(QDialog):
    """Lista los proyectos recientes; elegir uno lo abre, «Nuevo» empieza vacío."""

    def __init__(self, proyectos: list[Path], parent=None):
        super().__init__(parent)
        self.seleccionado: Path | None = None
        self._proyectos = proyectos
        self.setWindowTitle("MixMaster")
        self.resize(460, 380)

        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("<b>Proyectos recientes</b>"))
        self.lista = QListWidget()
        for p in proyectos:
            fecha = datetime.fromtimestamp(p.stat().st_mtime).strftime("%d/%m/%Y")
            self.lista.addItem(f"{p.name}    ·    {fecha}")
        self.lista.itemDoubleClicked.connect(self._abrir)
        lay.addWidget(self.lista, stretch=1)

        fila = QHBoxLayout()
        btn_nuevo = QPushButton("➕ Nuevo")
        btn_nuevo.clicked.connect(self.reject)  # cierra: PASO 1 vacío
        btn_abrir = QPushButton("Abrir")
        btn_abrir.setDefault(True)
        btn_abrir.clicked.connect(self._abrir)
        fila.addWidget(btn_nuevo)
        fila.addStretch()
        fila.addWidget(btn_abrir)
        lay.addLayout(fila)

    def _abrir(self):
        fila = self.lista.currentRow()
        if 0 <= fila < len(self._proyectos):
            self.seleccionado = self._proyectos[fila]
            self.accept()
