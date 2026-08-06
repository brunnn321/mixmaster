"""Convertidor de audio (v1.0+): WAV/MP3/FLAC/OGG/AIFF/M4A/WMA → WAV o MP3.

Diálogo standalone, no depende de un proyecto abierto — es una herramienta
suelta para el caso de "me mandaron un m4a por WhatsApp y Studio One no lo
reconoce". Sin explicaciones en pantalla: elegís archivos, elegís formato,
tocás Convertir.
"""

from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QListWidget,
    QMessageBox, QProgressBar, QPushButton, QVBoxLayout,
)

from ..audio_analysis import FORMATOS_SOPORTADOS
from ..convertidor import convertir_archivo
from ..logger import get_logger

log = get_logger("mixmaster.ui.convertidor")

_FILTRO = "Audio (" + " ".join(f"*{e}" for e in FORMATOS_SOPORTADOS) + ")"


class ConvertidorWorker(QThread):
    """Convierte una lista de archivos fuera del hilo de la UI."""

    progreso = Signal(int, int)     # (hechos, total)
    terminado = Signal(list, list)  # (rutas_ok, [(archivo, error), …])

    def __init__(self, archivos: list[Path], formato: str):
        super().__init__()
        self.archivos, self.formato = archivos, formato

    def run(self):
        ok, fallos = [], []
        for i, path in enumerate(self.archivos, start=1):
            try:
                ok.append(convertir_archivo(path, self.formato))
            except Exception as e:
                log.exception("No se pudo convertir %s", path)
                fallos.append((path, str(e)))
            self.progreso.emit(i, len(self.archivos))
        self.terminado.emit(ok, fallos)


class ConvertidorDialog(QDialog):
    """Elegís archivos, elegís WAV o MP3, tocás Convertir."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🔄 Convertidor")
        self.resize(420, 340)
        self._worker = None
        self.setAcceptDrops(True)

        lay = QVBoxLayout(self)

        self.lista = QListWidget()
        self.lista.setAcceptDrops(False)  # el drop lo maneja el diálogo entero
        lay.addWidget(self.lista)

        fila_archivos = QHBoxLayout()
        btn_agregar = QPushButton("➕ Agregar archivos…")
        btn_agregar.clicked.connect(self._agregar)
        btn_quitar = QPushButton("Quitar seleccionado")
        btn_quitar.clicked.connect(self._quitar_seleccionado)
        fila_archivos.addWidget(btn_agregar)
        fila_archivos.addWidget(btn_quitar)
        lay.addLayout(fila_archivos)

        fila_formato = QHBoxLayout()
        fila_formato.addWidget(QLabel("Convertir a:"))
        self.combo_formato = QComboBox()
        self.combo_formato.addItems(["WAV", "MP3"])
        fila_formato.addWidget(self.combo_formato)
        fila_formato.addStretch()
        lay.addLayout(fila_formato)

        self.barra = QProgressBar()
        self.barra.setVisible(False)
        lay.addWidget(self.barra)

        self.btn_convertir = QPushButton("CONVERTIR")
        self.btn_convertir.setCursor(Qt.PointingHandCursor)
        self.btn_convertir.setMinimumHeight(48)
        # Mismo estilo llamativo que el botón MASTER de la ventana principal —
        # coherencia visual, y que se note que es la acción principal.
        self.btn_convertir.setStyleSheet(
            "QPushButton { font-weight: 800; font-size: 16px; letter-spacing: 2px; color: white;"
            " border-radius: 10px; border: 1px solid #4fa76a;"
            " background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #4aa06a, stop:1 #2c6b46); }"
            " QPushButton:hover { background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #55b478, stop:1 #337a50); }"
            " QPushButton:pressed { background: #2a5f3e; }"
            " QPushButton:disabled { background: #2a3b31; color: #6f8579; border-color: #33463b; }")
        self.btn_convertir.clicked.connect(self._convertir)
        lay.addWidget(self.btn_convertir)

    def _agregar(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Elegir archivos", "", _FILTRO)
        self._agregar_paths(paths)

    def _agregar_paths(self, paths):
        agregados = 0
        for p in paths:
            if Path(p).suffix.lower() not in FORMATOS_SOPORTADOS:
                continue
            if not self.lista.findItems(p, Qt.MatchExactly):
                self.lista.addItem(p)
                agregados += 1
        return agregados

    def dragEnterEvent(self, event):
        mime = event.mimeData()
        if mime.hasUrls() and any(
                Path(u.toLocalFile()).suffix.lower() in FORMATOS_SOPORTADOS
                for u in mime.urls() if u.isLocalFile()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        self._agregar_paths(paths)

    def _quitar_seleccionado(self):
        for item in self.lista.selectedItems():
            self.lista.takeItem(self.lista.row(item))

    def _convertir(self):
        archivos = [Path(self.lista.item(i).text()) for i in range(self.lista.count())]
        if not archivos:
            QMessageBox.information(self, "Convertidor", "Agregá al menos un archivo.")
            return
        formato = self.combo_formato.currentText().lower()

        self.btn_convertir.setEnabled(False)
        self.barra.setVisible(True)
        self.barra.setRange(0, len(archivos))
        self.barra.setValue(0)

        self._worker = ConvertidorWorker(archivos, formato)
        self._worker.setParent(self)
        self._worker.progreso.connect(lambda h, t: self.barra.setValue(h))
        self._worker.terminado.connect(self._terminado)
        self._worker.start()

    def _terminado(self, ok: list, fallos: list):
        self.btn_convertir.setEnabled(True)
        self.barra.setVisible(False)
        if fallos:
            detalle = "\n".join(f"{p.name}: {err}" for p, err in fallos)
            QMessageBox.warning(
                self, "Convertidor",
                f"{len(ok)} convertido(s), {len(fallos)} con error:\n\n{detalle}")
        else:
            QMessageBox.information(self, "Convertidor", f"{len(ok)} archivo(s) convertido(s).")
        if ok:
            try:
                import os
                os.startfile(str(ok[0].parent))
            except Exception:
                log.exception("No se pudo abrir la carpeta de salida")
        self.lista.clear()
