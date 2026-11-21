"""Panel de la biblioteca de conocimiento: arrastras carpetas de música, la app
las analiza sola en segundo plano y acumula un informe por tema."""

from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QHBoxLayout, QLabel, QListWidget, QPushButton, QVBoxLayout,
)

from ..biblioteca import ARCHIVO, analizar_carpetas, ya_analizados
from ..logger import get_logger

log = get_logger("mixmaster.ui.biblioteca")


class _Worker(QThread):
    progreso = Signal(str)
    terminado = Signal(int)

    def __init__(self, carpetas):
        super().__init__()
        self.carpetas, self.cancelar = carpetas, False

    def run(self):
        try:
            n = analizar_carpetas(self.carpetas, self.progreso.emit, lambda: self.cancelar)
        except Exception:
            log.exception("Fallo analizando la biblioteca")
            n = 0
        self.terminado.emit(n)


class BibliotecaDialog(QDialog):
    """Lista de carpetas + Analizar/Detener + dónde quedan los informes."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Biblioteca de música")
        self.resize(720, 460)
        self.setAcceptDrops(True)
        self._worker = None

        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Arrastra aquí carpetas de música (o usa Agregar). La app analiza cada tema\n"
                             "sola y guarda un informe por tema; puedes cerrar este panel y seguir usando la app."))
        self.lista = QListWidget()
        lay.addWidget(self.lista, stretch=1)

        fila = QHBoxLayout()
        btn_agregar = QPushButton("+ Agregar carpeta")
        btn_agregar.clicked.connect(self._agregar)
        btn_quitar = QPushButton("− Quitar")
        btn_quitar.clicked.connect(lambda: [self.lista.takeItem(self.lista.row(i))
                                            for i in self.lista.selectedItems()])
        self.btn_analizar = QPushButton("▶ Analizar")
        self.btn_analizar.clicked.connect(self._analizar)
        fila.addWidget(btn_agregar)
        fila.addWidget(btn_quitar)
        fila.addStretch()
        fila.addWidget(self.btn_analizar)
        lay.addLayout(fila)

        self.lbl_estado = QLabel(f"{len(ya_analizados())} tema(s) ya analizados.")
        self.lbl_estado.setWordWrap(True)
        lay.addWidget(self.lbl_estado)
        fila2 = QHBoxLayout()
        fila2.addWidget(QLabel(f"Informes: {ARCHIVO}"))
        btn_abrir = QPushButton("📂 Abrir carpeta")
        btn_abrir.clicked.connect(self._abrir_carpeta)
        fila2.addWidget(btn_abrir)
        lay.addLayout(fila2)

    def _sumar(self, ruta: str):
        if Path(ruta).is_dir() and ruta not in [self.lista.item(i).text() for i in range(self.lista.count())]:
            self.lista.addItem(ruta)

    def _agregar(self):
        carpeta = QFileDialog.getExistingDirectory(self, "Carpeta de música", r"E:\Música")
        if carpeta:
            self._sumar(carpeta)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        for u in e.mimeData().urls():
            self._sumar(u.toLocalFile())

    def _analizar(self):
        if self._worker and self._worker.isRunning():
            self._worker.cancelar = True
            self.lbl_estado.setText("Deteniendo al terminar el tema actual (lo hecho queda guardado)…")
            return
        carpetas = [Path(self.lista.item(i).text()) for i in range(self.lista.count())]
        if not carpetas:
            self.lbl_estado.setText("Agrega al menos una carpeta.")
            return
        self._worker = _Worker(carpetas)
        self._worker.setParent(self.parent() or self)   # sigue aunque se cierre el panel
        self._worker.progreso.connect(self.lbl_estado.setText)
        self._worker.terminado.connect(self._terminado)
        self._worker.start()
        self.btn_analizar.setText("⏹ Detener")

    def _terminado(self, n: int):
        self.btn_analizar.setText("▶ Analizar")
        self.lbl_estado.setText(f"Listo: {n} tema(s) nuevos. Total analizados: {len(ya_analizados())}.")

    def _abrir_carpeta(self):
        from .abrir import mostrar_en_carpeta
        ARCHIVO.parent.mkdir(parents=True, exist_ok=True)
        if ARCHIVO.exists():
            mostrar_en_carpeta(str(ARCHIVO))
        else:
            import subprocess
            subprocess.Popen(["explorer", str(ARCHIVO.parent)])
