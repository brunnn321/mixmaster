"""Diálogo de historial de decisiones (v0.9): ver, editar feedback y borrar."""

from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QListWidget, QMessageBox, QPushButton,
    QVBoxLayout,
)

from ..decisions import borrar_decision, editar_feedback, listar_decisiones
from ..logger import get_logger
from ..project import Project

log = get_logger("mixmaster.ui.historial")

_ICONO_FEEDBACK = {"aprobado": "✔", "rechazado": "✗", "ajustado": "~"}


class HistorialDialog(QDialog):
    """Lista las decisiones del proyecto y permite editar feedback o borrar."""

    def __init__(self, proyecto: Project, parent=None):
        super().__init__(parent)
        self.proyecto = proyecto
        self.setWindowTitle(f"Historial de decisiones — {proyecto.nombre}")
        self.resize(680, 420)

        raiz = QVBoxLayout(self)
        raiz.addWidget(QLabel(
            "Decisiones registradas (de la más antigua a la más nueva). "
            "Selecciona una para editar su feedback o borrarla."))

        self.lista = QListWidget()
        raiz.addWidget(self.lista, stretch=1)

        fila = QHBoxLayout()
        self.btn_aprob = QPushButton("✔ Aprobado")
        self.btn_ajust = QPushButton("~ Ajustado")
        self.btn_rech = QPushButton("✗ Rechazado")
        self.btn_borrar = QPushButton("🗑 Borrar")
        self.btn_cerrar = QPushButton("Cerrar")
        self.btn_aprob.clicked.connect(lambda: self._set_feedback("aprobado"))
        self.btn_ajust.clicked.connect(lambda: self._set_feedback("ajustado"))
        self.btn_rech.clicked.connect(lambda: self._set_feedback("rechazado"))
        self.btn_borrar.clicked.connect(self._borrar)
        self.btn_cerrar.clicked.connect(self.accept)
        for b in (self.btn_aprob, self.btn_ajust, self.btn_rech, self.btn_borrar):
            fila.addWidget(b)
        fila.addStretch()
        fila.addWidget(self.btn_cerrar)
        raiz.addLayout(fila)

        self._refrescar()

    def _refrescar(self):
        """Recarga la lista desde el archivo."""
        self.lista.clear()
        self._decisiones = listar_decisiones(self.proyecto)
        if not self._decisiones:
            self.lista.addItem("(sin decisiones registradas todavía)")
            return
        for d in self._decisiones:
            ico = _ICONO_FEEDBACK.get(d["feedback"], "?")
            etiqueta = f" · {d['etiqueta']}" if d["etiqueta"] else ""
            refs = f"  [refs: {d['referencias']}]" if d["referencias"] else ""
            self.lista.addItem(
                f"{ico} [{d['version']}] {d['decision']}  — {d['feedback']}"
                f"{etiqueta}  ({d['timestamp']}){refs}")

    def _indice_sel(self) -> int:
        """Índice seleccionado válido, o -1."""
        fila = self.lista.currentRow()
        return fila if (self._decisiones and 0 <= fila < len(self._decisiones)) else -1

    def _set_feedback(self, feedback: str):
        i = self._indice_sel()
        if i < 0:
            QMessageBox.information(self, "Historial", "Selecciona una decisión primero.")
            return
        if editar_feedback(self.proyecto, i, feedback):
            self._refrescar()
            self.lista.setCurrentRow(i)

    def _borrar(self):
        i = self._indice_sel()
        if i < 0:
            QMessageBox.information(self, "Historial", "Selecciona una decisión primero.")
            return
        d = self._decisiones[i]
        if QMessageBox.question(
                self, "Borrar decisión",
                f"¿Borrar esta decisión?\n\n[{d['version']}] {d['decision']}",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        if borrar_decision(self.proyecto, i):
            self._refrescar()
