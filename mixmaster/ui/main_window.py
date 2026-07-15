"""Ventana principal de MixMaster v0.4 — asistente por pantallas.

Flujo: PASO 1 Fuente (mezcla o stems) → PASO 2 Referencias (+análisis
opcional) → PASO 3 Master final. El chat vive en el menú 💬 (ChatDialog).
"""

import json
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QProgressBar, QPushButton, QScrollArea,
    QStackedWidget, QStyle, QSystemTrayIcon, QTextEdit, QVBoxLayout, QWidget,
)

from .. import __version__
from ..audio_analysis import analizar_wav
from ..logger import get_logger
from ..processing import cargar_config_master, masterizar
from ..profiles import agregar_regla_genero, listar_referencias_genero
from ..project import Project, abrir_proyecto, crear_proyecto, nombre_seguro
from ..references import detectar_etiqueta_sugerida
from ..report import guardar_diagnostico, reporte_legible
from ..settings import Settings
from ..stems import procesar_stems, reporte_stems_legible
from .chat_dialog import ChatDialog
from .historial_dialog import HistorialDialog
from .settings_dialog import SettingsDialog

log = get_logger("mixmaster.ui")

# Extensiones que se aceptan al arrastrar audio a la app
_EXTS_AUDIO = (".wav", ".mp3", ".flac", ".ogg", ".aiff", ".aif", ".m4a", ".wma")

# Zona de "arrastra aquí" (vacía) y su versión con contenido cargado
_DROPZONE_VACIA = """
    border: 2px dashed #5a6b8c; border-radius: 10px;
    padding: 22px; color: #8a97b0; font-size: 14px;
    background: rgba(90,107,140,0.06);
"""
_DROPZONE_LLENA = """
    border: 2px solid #3a7d4f; border-radius: 10px;
    padding: 22px; color: #d6f5df; font-size: 14px; font-weight: bold;
    background: rgba(58,125,79,0.16);
"""
_DROPZONE_HOVER = """
    border: 2px dashed #6ea8ff; border-radius: 10px;
    padding: 22px; color: #cfe0ff; font-size: 14px;
    background: rgba(110,168,255,0.16);
"""


def _es_audio(path: str) -> bool:
    """True si la ruta tiene extensión de audio soportada."""
    return Path(path).suffix.lower() in _EXTS_AUDIO


class _ZonaDrop(QLabel):
    """Etiqueta-zona clicable (para cargar audio/referencias con un clic)."""

    clicked = Signal()

    def __init__(self, texto: str = ""):
        super().__init__(texto)
        self.setAlignment(Qt.AlignCenter)
        self.setWordWrap(True)
        self.setStyleSheet(_DROPZONE_VACIA)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(90)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class AnalisisWorker(QThread):
    """Ejecuta el análisis de audio fuera del hilo de la UI."""

    progreso = Signal(str)
    terminado = Signal(dict)
    fallo = Signal(str)

    def __init__(self, wav, marcadores, referencia, version, umbrales=None):
        super().__init__()
        self.wav, self.marcadores, self.referencia = wav, marcadores, referencia
        self.version, self.umbrales = version, umbrales

    def run(self):
        """Corre el pipeline y emite el diagnóstico o el error."""
        try:
            diag = analizar_wav(
                self.wav, self.marcadores, self.referencia,
                version=self.version, umbrales=self.umbrales,
                progreso=self.progreso.emit,
            )
            self.terminado.emit(diag)
        except Exception as e:
            log.exception("Fallo en el análisis")
            self.fallo.emit(str(e))


class MasterWorker(QThread):
    """Ejecuta el masterizado automático fuera del hilo de la UI."""

    progreso = Signal(str)
    terminado = Signal(dict)
    fallo = Signal(str)

    def __init__(self, mezcla, referencia, target, dir_masters, dir_entregables,
                 version, carpeta_stems=None):
        super().__init__()
        self.mezcla, self.referencia, self.target = mezcla, referencia, target
        self.dir_masters, self.dir_entregables, self.version = dir_masters, dir_entregables, version
        self.carpeta_stems = carpeta_stems

    def run(self):
        """Corre el pipeline de master y emite el resumen o el error."""
        try:
            resumen = masterizar(
                self.mezcla, self.referencia, self.target,
                self.dir_masters, self.dir_entregables,
                version=self.version, carpeta_stems=self.carpeta_stems,
                progreso=self.progreso.emit,
            )
            self.terminado.emit(resumen)
        except Exception as e:
            log.exception("Fallo en el masterizado")
            self.fallo.emit(str(e))


class StemsWorker(QThread):
    """Procesa los stems del proyecto fuera del hilo de la UI."""

    progreso = Signal(str)
    terminado = Signal(dict)
    fallo = Signal(str)

    def __init__(self, proyecto: Project):
        super().__init__()
        self.proyecto = proyecto

    def run(self):
        """Corre el gain staging + highpass y emite el reporte o el error."""
        try:
            self.terminado.emit(procesar_stems(self.proyecto, progreso=self.progreso.emit))
        except Exception as e:
            log.exception("Fallo en el procesamiento de stems")
            self.fallo.emit(str(e))


class MainWindow(QMainWindow):
    """Asistente de 3 pasos: Fuente → Referencias → Master."""

    FILTRO_AUDIO = ("Audio (*.wav *.mp3 *.flac *.ogg *.aiff *.aif *.m4a *.wma);;"
                    "Todos los archivos (*.*)")

    GUIA = [
        "PASO 1 · FUENTE — Carga tu audio o stems.",
        "PASO 2 · REFERENCIAS — Añade 3–6 temas.",
        "PASO 3 · MASTER — Pulsa «Master final».",
    ]

    def __init__(self, settings: Settings):
        super().__init__()
        self.settings = settings
        self.proyecto: Project | None = None
        self.wav_activo: Path | None = None
        self.referencia: list[Path] | None = None
        self.diagnostico: dict | None = None
        self.etiqueta_sugerida: str = ""  # Etiqueta detectada de referencias
        self._chat: ChatDialog | None = None
        self._worker = None
        self._notificado = False  # evita reentrada en closeEvent

        # Icono de bandeja para notificaciones nativas (fiable en Win11)
        self._tray = QSystemTrayIcon(self)
        self._tray.setIcon(self.style().standardIcon(QStyle.SP_MediaVolume))
        self._tray.setToolTip("MixMaster")
        self._tray.show()

        self.setWindowTitle(f"MixMaster v{__version__}")
        self.resize(880, 680)
        self.setAcceptDrops(True)  # arrastrar audio/referencias a la app
        self._crear_menu()
        self._crear_ui()
        self._refrescar_estado()

        ultimo = settings.get("ultimo_proyecto", "")
        if ultimo and Path(ultimo).is_dir():
            try:
                self._set_proyecto(abrir_proyecto(Path(ultimo)))
            except Exception:
                log.exception("No se pudo reabrir el último proyecto")

    # -------------------------------------------------------- cierre de app

    def closeEvent(self, event):
        """Notificación nativa Qt al cerrar (fiable en Win11), luego cierra.

        Muestra el toast, da 600 ms para que el SO lo renderice y recién
        entonces cierra de verdad (si se cerrara al instante, el proceso
        muere antes de que la notificación aparezca).
        """
        if not self._notificado:
            self._notificado = True
            try:
                if QSystemTrayIcon.supportsMessages():
                    self._tray.showMessage(
                        "✓ MixMaster", "Datos guardados",
                        QSystemTrayIcon.MessageIcon.Information, 3000)
                    QTimer.singleShot(600, self.close)  # cierra tras mostrar
                    event.ignore()
                    return
            except Exception:
                log.debug("Notificación no disponible; cierre normal")
        event.accept()

    # ------------------------------------------------------------- menú y UI

    def _crear_menu(self):
        """Barra de menú: Archivo, Proyecto, Settings, Chat."""
        m_archivo = self.menuBar().addMenu("&Archivo")
        acc_log = QAction("Abrir registro (app.log)…", self)
        acc_log.triggered.connect(self._abrir_log)
        acc_salir = QAction("Salir", self)
        acc_salir.triggered.connect(self.close)
        m_archivo.addActions([acc_log, acc_salir])

        m_proyecto = self.menuBar().addMenu("&Proyecto")
        acc_nuevo = QAction("Nuevo proyecto…", self)
        acc_nuevo.triggered.connect(self._nuevo_proyecto)
        acc_abrir = QAction("Abrir proyecto…", self)
        acc_abrir.triggered.connect(self._abrir_proyecto)
        acc_carpeta = QAction("Abrir carpeta del proyecto", self)
        acc_carpeta.triggered.connect(self._abrir_carpeta)
        m_proyecto.addActions([acc_nuevo, acc_abrir, acc_carpeta])

        m_settings = self.menuBar().addMenu("&Settings")
        acc_settings = QAction("Configuración…", self)
        acc_settings.triggered.connect(self._abrir_settings)
        m_settings.addAction(acc_settings)

        m_hist = self.menuBar().addMenu("📋 &Historial")
        acc_decisiones = QAction("Decisiones (ver / editar / borrar)…", self)
        acc_decisiones.triggered.connect(self._abrir_historial)
        acc_masters = QAction("Masters anteriores…", self)
        acc_masters.triggered.connect(self._abrir_masters)
        m_hist.addActions([acc_decisiones, acc_masters])

        m_chat = self.menuBar().addMenu("💬 &Chat")
        acc_chat = QAction("Abrir chat con Claude…", self)
        acc_chat.triggered.connect(self._abrir_chat)
        m_chat.addAction(acc_chat)

    def _crear_ui(self):
        """Layout: proyecto → guía → paso actual → navegación → resultados."""
        central = QWidget()
        raiz = QVBoxLayout(central)

        self.lbl_proyecto = QLabel("Proyecto activo: (ninguno)")
        self.lbl_proyecto.setStyleSheet("font-weight: bold; padding: 4px;")
        raiz.addWidget(self.lbl_proyecto)

        self.lbl_guia = QLabel("")
        self.lbl_guia.setWordWrap(True)
        self.lbl_guia.setStyleSheet(
            "background: #2b3a55; color: white; padding: 8px; border-radius: 4px;")
        raiz.addWidget(self.lbl_guia)

        # --- pila de pasos ---
        self.pila = QStackedWidget()

        # PASO 1: fuente — una sola caja (clic o arrastre)
        pag1 = QWidget()
        lay1 = QVBoxLayout(pag1)
        self.lbl_fuente = _ZonaDrop()
        self.lbl_fuente.setMinimumHeight(150)
        self.lbl_fuente.clicked.connect(self._cargar_fuente_dialogo)
        lay1.addWidget(self.lbl_fuente)
        lay1.addStretch()
        self.pila.addWidget(pag1)

        # PASO 2: referencias — tarjetas (chips) + zona clicable
        pag2 = QWidget()
        lay2 = QVBoxLayout(pag2)
        self.zona_refs = _ZonaDrop()
        self.zona_refs.clicked.connect(self._elegir_referencia)
        lay2.addWidget(self.zona_refs)
        self.refs_contenedor = QWidget()
        self.refs_layout = QVBoxLayout(self.refs_contenedor)
        self.refs_layout.setContentsMargins(0, 0, 0, 0)
        lay2.addWidget(self.refs_contenedor)
        self.ed_marcadores = QLineEdit()
        self.ed_marcadores.setPlaceholderText(
            "Marcadores para el análisis (opcional): Intro: 0:00, Riff A: 0:23")
        lay2.addWidget(self.ed_marcadores)
        lay2.addStretch()
        self.pila.addWidget(pag2)

        # PASO 3: master
        pag3 = QWidget()
        lay3 = QVBoxLayout(pag3)
        fila3 = QHBoxLayout()
        self.btn_master = QPushButton("🎵 Master final")
        self.btn_master.setStyleSheet("font-weight: bold;")
        self.btn_master.setToolTip(
            "EQ 7 bandas + imagen estéreo hacia las referencias + densidad + "
            "loudness (-8.5 default) + limitador -1 dBTP.\n"
            "Config editable en config/master.json")
        self.btn_master.clicked.connect(self._masterizar)
        self.btn_regla = QPushButton("★ Regla del género")
        self.btn_regla.setToolTip(
            "Fija una regla aprendida en el género activo (versionado, reversible en Settings).")
        self.btn_regla.clicked.connect(self._promover_regla)
        fila3.addWidget(self.btn_master)
        fila3.addWidget(self.btn_regla)
        fila3.addStretch()
        lay3.addLayout(fila3)
        lay3.addStretch()
        self.pila.addWidget(pag3)

        raiz.addWidget(self.pila)

        # --- navegación ---
        nav = QHBoxLayout()
        self.btn_atras = QPushButton("← Atrás")
        self.btn_atras.clicked.connect(lambda: self._ir(self.pila.currentIndex() - 1))
        self.btn_siguiente = QPushButton("Siguiente →")
        self.btn_siguiente.setStyleSheet("font-weight: bold;")
        self.btn_siguiente.clicked.connect(lambda: self._ir(self.pila.currentIndex() + 1))
        nav.addWidget(self.btn_atras)
        nav.addStretch()
        nav.addWidget(self.btn_siguiente)
        raiz.addLayout(nav)

        # --- resultados ---
        self.txt_resultado = QTextEdit()
        self.txt_resultado.setReadOnly(True)
        self.txt_resultado.setPlaceholderText("Resultados de análisis, stems y master…")
        self.txt_resultado.setFontFamily("Consolas")
        raiz.addWidget(self.txt_resultado, stretch=1)

        self.barra = QProgressBar()
        self.barra.setTextVisible(False)
        self.barra.setMaximumHeight(8)
        self.barra.setVisible(False)
        raiz.addWidget(self.barra)

        self.lbl_estado = QLabel("")
        raiz.addWidget(self.lbl_estado)

        self.setCentralWidget(central)

    def _barra_activa(self, activa: bool):
        """Muestra/oculta la barra de progreso (modo actividad)."""
        if activa:
            self.barra.setRange(0, 0)  # indeterminada = "trabajando"
            self.barra.setVisible(True)
        else:
            self.barra.setVisible(False)

    # ---------------------------------------------------------- estado de UI

    def _fuente_lista(self) -> bool:
        """True si hay mezcla cargada o stems nivelados."""
        if self.wav_activo:
            return True
        return bool(self.proyecto and self.proyecto.dir_stems_niveladas.is_dir()
                    and any(self.proyecto.dir_stems_niveladas.glob("*.wav")))

    def _ir(self, idx: int):
        """Navega al paso idx (0-2) y refresca la guía."""
        self.pila.setCurrentIndex(max(0, min(2, idx)))
        self._refrescar_estado()

    def _refrescar_estado(self):
        """Habilita botones y actualiza guía según proyecto/paso."""
        hay_proyecto = self.proyecto is not None
        nombre = f'"{self.proyecto.nombre}"' if hay_proyecto else "(ninguno)"
        self.lbl_proyecto.setText(
            f"Proyecto activo: {nombre}   ·   Género: {self.settings.genero_activo()}")

        idx = self.pila.currentIndex()
        self.btn_master.setEnabled(hay_proyecto and self._fuente_lista())
        self.btn_atras.setEnabled(idx > 0)
        self.btn_siguiente.setEnabled(
            hay_proyecto and idx < 2 and (idx != 0 or self._fuente_lista()))

        if not hay_proyecto:
            self.lbl_guia.setText(
                "<b>EMPIEZA AQUÍ — Carga tu audio o stems:</b> arrastra los archivos "
                "a la caja o haz clic en ella. El proyecto toma el nombre del archivo.")
        else:
            self.lbl_guia.setText(f"<b>{self.GUIA[idx]}</b>")

        # zona de fuente
        if self.wav_activo:
            self.lbl_fuente.setText(f"🎵  Mezcla cargada\n«{self.wav_activo.name}»")
            self.lbl_fuente.setStyleSheet(_DROPZONE_LLENA)
        elif self._fuente_lista():
            n = len(list(self.proyecto.dir_stems_niveladas.glob('*.wav')))
            self.lbl_fuente.setText(f"🥁  {n} stems nivelados (suma virtual)")
            self.lbl_fuente.setStyleSheet(_DROPZONE_LLENA)
        else:
            self.lbl_fuente.setText("⬇  Cargar audio o stems\nArrastra aquí o haz clic")
            self.lbl_fuente.setStyleSheet(_DROPZONE_VACIA)

        self._refrescar_referencias()

    def _refrescar_referencias(self):
        """Reconstruye las tarjetas (chips) de referencias del PASO 2."""
        # limpia los chips actuales
        while self.refs_layout.count():
            item = self.refs_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self.referencia:
            self.zona_refs.setText("⬇  Cargar referencias\nArrastra aquí o haz clic (3–6 temas)")
            self.zona_refs.setStyleSheet(_DROPZONE_VACIA)
            self.refs_contenedor.setVisible(False)
            return

        self.zona_refs.setText(
            f"📀  {len(self.referencia)} referencia(s) — arrastra o haz clic para añadir")
        self.zona_refs.setStyleSheet(_DROPZONE_LLENA)
        self.refs_contenedor.setVisible(True)
        for i, ref in enumerate(self.referencia):
            self.refs_layout.addWidget(self._crear_chip(i, ref))

    def _crear_chip(self, indice: int, ref: Path) -> QFrame:
        """Una tarjeta de referencia: nombre + ✕ para quitarla."""
        chip = QFrame()
        chip.setStyleSheet(
            "QFrame { border: 1px solid #3a7d4f; border-radius: 8px;"
            " background: rgba(58,125,79,0.14); }")
        fila = QHBoxLayout(chip)
        fila.setContentsMargins(10, 4, 6, 4)
        lbl = QLabel(f"📀  {ref.name}")
        lbl.setStyleSheet("border: none; background: transparent;")
        btn = QPushButton("✕")
        btn.setFixedWidth(28)
        btn.setToolTip("Quitar esta referencia")
        btn.setStyleSheet("border: none; background: transparent; font-weight: bold;")
        btn.clicked.connect(lambda: self._quitar_referencia(indice))
        fila.addWidget(lbl, stretch=1)
        fila.addWidget(btn)
        return chip

    def _quitar_referencia(self, indice: int):
        """Quita la referencia #indice y refresca las tarjetas."""
        if self.referencia and 0 <= indice < len(self.referencia):
            quitada = self.referencia.pop(indice)
            if not self.referencia:
                self.referencia = None
            self._status(f"Referencia quitada: {quitada.name}")
            self._refrescar_referencias()

    def _status(self, msg: str):
        """Mensaje en la línea de estado inferior."""
        self.lbl_estado.setText(msg)

    def _set_proyecto(self, proyecto: Project):
        """Activa un proyecto y vuelve al paso 1."""
        self.proyecto = proyecto
        self.diagnostico = None
        self.wav_activo = None
        self.referencia = None
        self.settings.set("ultimo_proyecto", str(proyecto.root))

        ultimo = proyecto.ultimo_diagnostico()
        if ultimo:
            try:
                self.diagnostico = json.loads(ultimo.read_text(encoding="utf-8"))
                self.txt_resultado.setPlainText(reporte_legible(self.diagnostico))
                self._status(f"Diagnóstico previo cargado: {ultimo.name}")
            except Exception:
                log.exception("No se pudo cargar el diagnóstico previo")
        else:
            self.txt_resultado.clear()
        self._ir(0)

    # ------------------------------------------------------------- proyectos

    def _nuevo_proyecto(self):
        """Crea un proyecto con nombre manual (para stems o vacío).

        Para una mezcla no hace falta: «Cargar audio» ya crea el proyecto con
        el nombre del archivo.
        """
        nombre, ok = QInputDialog.getText(
            self, "Nuevo proyecto (stems)",
            "Nombre del proyecto (para stems escribe el nombre de la canción):")
        if not ok or not nombre.strip():
            return
        try:
            base = self.settings.ruta_proyectos
            base.mkdir(parents=True, exist_ok=True)
            self._set_proyecto(crear_proyecto(base, nombre.strip()))
            self._status(f"Proyecto creado en {self.proyecto.root}")
        except Exception as e:
            log.exception("Error creando proyecto")
            QMessageBox.critical(self, "Error", f"No se pudo crear el proyecto:\n{e}")

    def _abrir_proyecto(self):
        """Abre un proyecto existente (layouts nuevo y viejo)."""
        ruta = QFileDialog.getExistingDirectory(
            self, "Abrir proyecto", str(self.settings.ruta_proyectos))
        if not ruta:
            return
        try:
            self._set_proyecto(abrir_proyecto(Path(ruta)))
            self._status("Proyecto abierto.")
        except Exception as e:
            log.exception("Error abriendo proyecto")
            QMessageBox.critical(self, "Error", f"No se pudo abrir el proyecto:\n{e}")

    def _abrir_carpeta(self):
        """Abre la carpeta del proyecto en el explorador."""
        if self.proyecto:
            import os
            os.startfile(str(self.proyecto.root))  # noqa: S606 — abrir carpeta local

    def _abrir_settings(self):
        """Abre el diálogo de configuración."""
        dlg = SettingsDialog(self.settings, self)
        if dlg.exec():
            self._refrescar_estado()
            self._status("Settings guardados.")

    def _abrir_log(self):
        """Abre el archivo de log en el visor por defecto (para soporte)."""
        from ..app_paths import LOG_FILE
        if not LOG_FILE.exists():
            QMessageBox.information(self, "Registro", "Aún no hay registro (app.log).")
            return
        try:
            import os
            os.startfile(str(LOG_FILE))  # noqa: S606 — abrir log local
        except Exception:
            log.exception("No se pudo abrir el log")
            QMessageBox.information(self, "Registro", f"El log está en:\n{LOG_FILE}")

    def _abrir_historial(self):
        """Abre el historial de decisiones (ver / editar feedback / borrar)."""
        if not self.proyecto:
            QMessageBox.information(self, "Historial", "Abre o crea un proyecto primero.")
            return
        HistorialDialog(self.proyecto, self).exec()

    def _abrir_masters(self):
        """Lista los masters anteriores; abre el elegido o su carpeta."""
        if not self.proyecto:
            QMessageBox.information(self, "Masters", "Abre o crea un proyecto primero.")
            return
        masters = self.proyecto.listar_masters()
        if not masters:
            QMessageBox.information(
                self, "Masters",
                "Todavía no hay masters en este proyecto.\nGenera uno en el PASO 3.")
            return
        nombres = [m.name for m in masters]
        elegido, ok = QInputDialog.getItem(
            self, "Masters anteriores",
            f"{len(masters)} master(s) — el más nuevo arriba. Se abrirá el elegido:",
            nombres, 0, False)
        if not ok:
            return
        try:
            import os
            os.startfile(str(masters[nombres.index(elegido)]))  # noqa: S606
        except Exception:
            log.exception("No se pudo abrir el master")
            QMessageBox.critical(self, "Error", "No se pudo abrir el master (ver app.log).")

    def _abrir_chat(self):
        """Abre (o trae al frente) el diálogo de chat."""
        if self._chat is None:
            self._chat = ChatDialog(self)
        self._chat.show()
        self._chat.raise_()

    # ------------------------------------------------------- paso 1: fuente

    def _cargar_audio_desde_path(self, path: str):
        """Carga una mezcla (de diálogo o drag&drop) y crea/reabre el proyecto.

        El proyecto se nombra automáticamente como la canción (sin extensión).
        Si ya existe uno con ese nombre, lo reabre.
        """
        archivo = Path(path)
        try:
            base = self.settings.ruta_proyectos
            base.mkdir(parents=True, exist_ok=True)
            destino = base / nombre_seguro(archivo.stem)
            proyecto = (abrir_proyecto(destino) if destino.is_dir()
                        else crear_proyecto(base, archivo.stem))
            self._set_proyecto(proyecto)   # ¡ojo! esto resetea wav_activo
        except Exception as e:
            log.exception("Error creando proyecto desde el audio")
            QMessageBox.critical(self, "Error", f"No se pudo crear el proyecto:\n{e}")
            return
        self.wav_activo = archivo
        self._status(f"Proyecto «{self.proyecto.nombre}» — mezcla: {archivo.name}")
        self._ir(1)  # auto-avanza a referencias

    # ------------------------------------------------------- drag & drop

    def dragEnterEvent(self, event):
        """Acepta el arrastre si trae al menos un archivo de audio."""
        mime = event.mimeData()
        if mime.hasUrls() and any(_es_audio(u.toLocalFile())
                                  for u in mime.urls() if u.isLocalFile()):
            event.acceptProposedAction()
            zona = self.zona_refs if self.pila.currentIndex() == 1 else self.lbl_fuente
            zona.setStyleSheet(_DROPZONE_HOVER)
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        """Restaura el estilo de las zonas al salir el cursor."""
        self._refrescar_estado()

    def dropEvent(self, event):
        """Enruta los archivos soltados según el paso actual.

        PASO 2 → los añade como referencias. Otro paso → 1 archivo = mezcla,
        varios = stems (crea proyecto, copia y nivela).
        """
        audios = [u.toLocalFile() for u in event.mimeData().urls()
                  if u.isLocalFile() and _es_audio(u.toLocalFile())]
        if not audios:
            self._refrescar_estado()
            return
        if self.pila.currentIndex() == 1:
            self._set_referencias_desde_paths(audios)
        elif len(audios) == 1:
            self._cargar_audio_desde_path(audios[0])
        else:
            self._cargar_stems_desde_paths(audios)

    def _cargar_fuente_dialogo(self):
        """Clic en la caja: selector (multi). 1 archivo = mezcla, varios = stems."""
        inicio = str(self.proyecto.dir_originales) if self.proyecto else ""
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Cargar audio (1 archivo) o stems (varios)", inicio, self.FILTRO_AUDIO)
        if not paths:
            return
        if len(paths) == 1:
            self._cargar_audio_desde_path(paths[0])
        else:
            self._cargar_stems_desde_paths(paths)

    def _cargar_stems_desde_paths(self, paths):
        """Crea un proyecto con nombre derivado, copia los stems y los nivela."""
        import os
        import shutil
        archivos = [Path(p) for p in paths]
        # nombre del proyecto: prefijo común de los nombres, o carpeta padre
        prefijo = os.path.commonprefix([a.stem for a in archivos]).strip(" -_·")
        nombre = prefijo or archivos[0].parent.name or "stems"
        try:
            base = self.settings.ruta_proyectos
            base.mkdir(parents=True, exist_ok=True)
            destino = base / nombre_seguro(nombre)
            proyecto = (abrir_proyecto(destino) if destino.is_dir()
                        else crear_proyecto(base, nombre))
            self._set_proyecto(proyecto)
            proyecto.dir_stems.mkdir(parents=True, exist_ok=True)  # on-demand
            for a in archivos:
                shutil.copy2(str(a), str(proyecto.dir_stems / a.name))
        except Exception as e:
            log.exception("Error cargando stems")
            QMessageBox.critical(self, "Error", f"No se pudieron cargar los stems:\n{e}")
            return
        self._status(f"Proyecto «{self.proyecto.nombre}» — {len(archivos)} stems copiados")
        self._procesar_stems()  # nivela y avanza a referencias

    def _procesar_stems(self):
        """Gain staging + highpass de todos los stems de entrada/stems."""
        if not self.proyecto:
            return
        if not self.proyecto.dir_stems.is_dir() or not any(self.proyecto.dir_stems.glob("*")):
            QMessageBox.information(
                self, "Sin stems",
                "No hay stems que procesar. Arrastra varios archivos de audio a la "
                "caja del PASO 1 para cargarlos como stems.")
            return
        self._barra_activa(True)
        self._status("Procesando stems…")
        self._stems_worker = StemsWorker(self.proyecto)
        self._stems_worker.progreso.connect(self._status)
        self._stems_worker.terminado.connect(self._stems_ok)
        self._stems_worker.fallo.connect(self._stems_error)
        self._stems_worker.start()

    def _stems_ok(self, reporte: dict):
        """Muestra el reporte de gain staging."""
        self._barra_activa(False)
        self.txt_resultado.append("\n" + reporte_stems_legible(reporte))
        self._status(f"Stems listos: {len(reporte['stems'])} nivelados")
        if reporte["stems"]:
            self._ir(1)  # auto-avanza a referencias
        else:
            self._refrescar_estado()

    def _stems_error(self, msg: str):
        self._barra_activa(False)
        self._refrescar_estado()
        self._status("Procesamiento de stems fallido (ver app.log).")
        QMessageBox.critical(self, "Error", f"No se pudieron procesar los stems:\n{msg}")

    # -------------------------------------------------- paso 2: referencias

    def _elegir_referencia(self):
        """Biblioteca del género o archivos sueltos; varias = promedio."""
        if not self.proyecto:
            QMessageBox.information(self, "Referencias", "Carga primero tu audio o stems.")
            return
        genero = self.settings.genero_activo()
        biblioteca = listar_referencias_genero(genero)

        usar_biblioteca = False
        if biblioteca:
            opciones = [f"Biblioteca {genero} ({len(biblioteca)} temas)", "Elegir archivos…"]
            eleccion, ok = QInputDialog.getItem(
                self, "Referencias", "¿Qué referencias usamos?", opciones, 0, False)
            if not ok:
                return
            usar_biblioteca = eleccion.startswith("Biblioteca")

        if usar_biblioteca:
            if len(biblioteca) > 6:
                seguir = QMessageBox.question(
                    self, "Biblioteca grande",
                    f"La biblioteca tiene {len(biblioteca)} temas: el análisis será lento "
                    "y el promedio muy genérico (recomendado 3–6).\n\n¿Continuar igual?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                if seguir != QMessageBox.Yes:
                    return
            nuevas = list(biblioteca)
        else:
            inicio = str(self.proyecto.dir_referencias) if self.proyecto else ""
            paths, _ = QFileDialog.getOpenFileNames(
                self, "Elegir referencia(s) — puedes seleccionar varias (Ctrl+clic)",
                inicio, self.FILTRO_AUDIO)
            if not paths:
                return
            nuevas = [Path(p) for p in paths]

        self._set_referencias_desde_paths(nuevas)

    def _set_referencias_desde_paths(self, refs):
        """Añade referencias (acumula, sin duplicar), sugiere etiqueta y analiza."""
        existentes = self.referencia or []
        rutas = {str(p) for p in existentes}
        nuevas = [Path(p) for p in refs if str(Path(p)) not in rutas]
        self.referencia = existentes + nuevas
        self._status(f"{len(self.referencia)} referencia(s).")

        # Detectar etiqueta sugerida si hay mezcla cargada
        if self.wav_activo:
            resultado = detectar_etiqueta_sugerida(self.wav_activo)
            if resultado.get("exito") and resultado.get("etiqueta_sugerida"):
                etiqueta = resultado["etiqueta_sugerida"]
                confianza = int(resultado["confianza"] * 100)
                if confianza >= 50:
                    respuesta = QMessageBox.question(
                        self, "Etiqueta sugerida",
                        f"Detectamos similitud con «{etiqueta}» ({confianza}%).\n\n"
                        f"¿Usamos esta etiqueta?",
                        QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
                    if respuesta == QMessageBox.Yes:
                        self.etiqueta_sugerida = etiqueta
                        self._status(f"Etiqueta: {etiqueta} ({confianza}%)")

        if self.wav_activo:
            self._analizar_auto()  # analiza solo y luego salta al master
        else:
            self._refrescar_estado()
            self._ir(2)  # fuente = stems: no hay mezcla única que analizar

    def _version_auto(self) -> str:
        """V01, V02… según cuántos diagnósticos ya tenga el proyecto."""
        n = len(list(self.proyecto.dir_analisis.glob("diagnostico_v*.json"))) + 1
        return f"V{n:02d}"

    def _analizar_auto(self):
        """Análisis automático tras elegir referencias (sin diálogos)."""
        self._barra_activa(True)
        self.txt_resultado.setPlainText("Analizando automáticamente contra tus referencias…")
        _, umbrales = self.settings.leer_genero_activo()
        self._worker = AnalisisWorker(
            self.wav_activo, self.ed_marcadores.text(), self.referencia,
            self._version_auto(), umbrales)
        self._worker.progreso.connect(self._status)
        self._worker.terminado.connect(self._analisis_auto_ok)
        self._worker.fallo.connect(self._analisis_error)
        self._worker.start()

    def _analisis_auto_ok(self, diag: dict):
        """Como _analisis_ok pero avanzando solo al paso del master."""
        self._analisis_ok(diag)
        self._ir(2)

    def _analizar(self):
        """Análisis opcional de la mezcla (números, secciones, alertas)."""
        if not self.wav_activo or not self.proyecto:
            return
        version, ok = QInputDialog.getText(
            self, "Versión", "Etiqueta de versión para este análisis:", text="V01")
        if not ok:
            return
        self._barra_activa(True)
        self.txt_resultado.setPlainText("Analizando…")
        _, umbrales = self.settings.leer_genero_activo()
        self._worker = AnalisisWorker(
            self.wav_activo, self.ed_marcadores.text(), self.referencia,
            version.strip() or "V01", umbrales)
        self._worker.progreso.connect(self._status)
        self._worker.terminado.connect(self._analisis_ok)
        self._worker.fallo.connect(self._analisis_error)
        self._worker.start()

    def _analisis_ok(self, diag: dict):
        """Guarda y muestra el diagnóstico."""
        self._barra_activa(False)
        self.diagnostico = diag
        try:
            path_json, _ = guardar_diagnostico(self.proyecto, diag)
            self._status(f"Diagnóstico guardado: {path_json.name}")
        except Exception:
            log.exception("No se pudo guardar el diagnóstico")
            self._status("⚠ Análisis OK pero no se pudo guardar (ver app.log)")
        self.txt_resultado.setPlainText(reporte_legible(diag))
        self._refrescar_estado()

    def _analisis_error(self, msg: str):
        self._barra_activa(False)
        self.txt_resultado.setPlainText(
            f"Error en el análisis:\n{msg}\n\n(Detalles en logs/app.log)")
        self._refrescar_estado()
        self._status("Análisis fallido.")

    # ------------------------------------------------------ paso 3: master

    def _masterizar(self):
        """Masteriza la mezcla o los stems nivelados → WAV + MP3 en salida/."""
        if not self.proyecto:
            return
        dir_niveladas = self.proyecto.dir_stems_niveladas
        hay_stems = dir_niveladas.is_dir() and any(dir_niveladas.glob("*.wav"))
        carpeta_stems = None
        if hay_stems and self.wav_activo:
            fuente, ok = QInputDialog.getItem(
                self, "Fuente del master", "¿Desde dónde masterizamos?",
                ["Mezcla cargada", "Stems nivelados (suma virtual)"], 0, False)
            if not ok:
                return
            if fuente.startswith("Stems"):
                carpeta_stems = dir_niveladas
        elif hay_stems:
            carpeta_stems = dir_niveladas
        elif not self.wav_activo:
            QMessageBox.information(self, "Sin fuente", "Vuelve al PASO 1 y carga una fuente.")
            return

        cfg = cargar_config_master()
        target, ok = QInputDialog.getDouble(
            self, "Master final",
            "Loudness objetivo (LUFS integrado).\n"
            "-8.5 = competitivo · -8 / -7.5 = más loud (test) · -14 = streaming suave:",
            float(cfg.get("target_lufs_default", -8.5)), -20.0, -5.0, 1)
        if not ok:
            return
        if not self.referencia:
            QMessageBox.information(
                self, "Sin referencia",
                "Sin referencias el master sale solo con densidad, loudness y limitador\n"
                "(sin EQ correctivo ni imagen). Puedes elegirlas en el PASO 2.")

        version = self.diagnostico["version"] if self.diagnostico else "V01"
        self.btn_master.setEnabled(False)
        self._barra_activa(True)
        self._status("Masterizando…")
        self._master_worker = MasterWorker(
            self.wav_activo, self.referencia, target,
            self.proyecto.dir_masters, self.proyecto.dir_entregables,
            version, carpeta_stems)
        self._master_worker.progreso.connect(self._status)
        self._master_worker.terminado.connect(self._master_ok)
        self._master_worker.fallo.connect(self._master_error)
        self._master_worker.start()

    def _master_ok(self, resumen: dict):
        """Muestra el resultado y abre la carpeta de salida."""
        self._barra_activa(False)
        eq = resumen.get("eq_aplicado_db") or {}
        eq_txt = ("\n  EQ aplicado (dB): " + ", ".join(f"{b} {v:+.1f}" for b, v in eq.items())
                  if eq else "\n  (sin EQ: no había referencia)")
        ancho = resumen.get("ajuste_ancho_db") or {}
        ancho_txt = ("\n  Imagen estéreo (side dB): "
                     + ", ".join(f"{b} {v:+.1f}" for b, v in ancho.items())
                     if ancho else "")
        mbanda = resumen.get("multibanda_db") or {}
        mbanda_txt = ("\n  Multibanda (dB reducción): "
                      + ", ".join(f"{b} -{v:g}" for b, v in mbanda.items())
                      if mbanda else "")
        reso = resumen.get("resonancias_db") or []
        reso_txt = ("\n  Resonancias (notch): "
                    + ", ".join(f"{r['freq']:g}Hz {r['corte_db']:g}dB" for r in reso)
                    if reso else "")
        tr = resumen.get("transient_shaping")
        tr_txt = f"\n  Transient shaping: pegada +{tr:g}" if tr else ""
        den_txt = "\n  Densidad extra: sí (empuje de loudness alto)" \
            if resumen.get("densidad_aplicada") else ""
        mb_hz = resumen.get("mono_bass_hz")
        mb_txt = f"\n  Mono-bass: < {mb_hz:g} Hz (punch + compatibilidad)" if mb_hz else ""
        score = resumen.get("score")
        score_txt = (f"\n  ── SCORE vs referencias: {score['global']}% "
                     f"(tonal {score['tonal']}% · dinámica {score['dinamica']}% · "
                     f"imagen {score['imagen']}%)") if score else ""
        self.txt_resultado.append(
            f"\n══ MASTER LISTO ({resumen.get('fuente', 'mezcla')}) ══{score_txt}\n"
            f"  LUFS final: {resumen['lufs_final']} (objetivo {resumen['target_lufs']})\n"
            f"  True peak: {resumen['true_peak_final']} dBTP   "
            f"Crest: {resumen.get('crest_final', '?')} dB{eq_txt}{ancho_txt}{mbanda_txt}{reso_txt}{tr_txt}{den_txt}{mb_txt}\n"
            f"  WAV: {resumen['wav']}\n"
            f"  MP3 para subir: {resumen['mp3']}")
        self._refrescar_estado()
        self._status(f"Master listo → {Path(resumen['mp3']).name}")
        try:
            import os
            os.startfile(str(Path(resumen["mp3"]).parent))  # abre salida/ con el archivo
        except Exception:
            log.exception("No se pudo abrir la carpeta de salida")

    def _master_error(self, msg: str):
        self._barra_activa(False)
        self._refrescar_estado()
        self._status("Masterizado fallido (ver app.log).")
        QMessageBox.critical(self, "Error", f"No se pudo masterizar:\n{msg}")

    # -------------------------------------------------------- regla género

    def _promover_regla(self):
        """Fija una regla aprendida en el género activo (versionado)."""
        regla, ok = QInputDialog.getText(
            self, "Regla del género",
            f"Regla a fijar en «{self.settings.genero_activo()}»\n"
            "(el estado anterior queda versionado, reversible en Settings):")
        if not ok or not regla.strip():
            return
        cancion = self.diagnostico["archivo"] if self.diagnostico else ""
        try:
            agregar_regla_genero(self.settings.genero_activo(), regla.strip(), cancion)
            self._status(f"Regla guardada en generos/{self.settings.genero_activo()}.md")
        except Exception as e:
            log.exception("Error guardando regla del género")
            QMessageBox.critical(self, "Error", f"No se pudo guardar la regla:\n{e}")
