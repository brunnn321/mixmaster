"""Ventana principal de MixMaster v0.4 — asistente por pantallas.

Flujo: PASO 1 Fuente (mezcla o stems) → PASO 2 Referencias (+análisis
opcional) → PASO 3 Master final. El chat vive en el menú 💬 (ChatDialog).
"""

import json
from pathlib import Path

from PySide6.QtCore import QThread, QTimer, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QPushButton, QStackedWidget, QStyle, QSystemTrayIcon,
    QTextEdit, QVBoxLayout, QWidget,
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
from .settings_dialog import SettingsDialog

log = get_logger("mixmaster.ui")


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
        "PASO 1 de 3 — FUENTE: carga tu mezcla («Cargar audio») o copia tus stems "
        "a entrada/stems y pulsa «Procesar stems». Luego «Siguiente →».",
        "PASO 2 de 3 — REFERENCIAS: elige 3–6 temas (biblioteca del género o archivos). "
        "Opcional: «Analizar» para ver números y alertas. Luego «Siguiente →».",
        "PASO 3 de 3 — MASTER: pulsa «🎵 Master final», elige el loudness (-8.5 default) "
        "y en salida/ tendrás el WAV y el MP3 listos para subir.",
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
        acc_salir = QAction("Salir", self)
        acc_salir.triggered.connect(self.close)
        m_archivo.addAction(acc_salir)

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

        m_chat = self.menuBar().addMenu("💬 &Chat")
        acc_chat = QAction("Abrir chat con Claude…", self)
        acc_chat.triggered.connect(self._abrir_chat)
        m_chat.addAction(acc_chat)

    def _crear_ui(self):
        """Layout: proyecto → guía → paso actual → navegación → resultados."""
        central = QWidget()
        raiz = QVBoxLayout(central)

        fila_proj = QHBoxLayout()
        self.lbl_proyecto = QLabel("Proyecto activo: (ninguno)")
        self.lbl_proyecto.setStyleSheet("font-weight: bold; padding: 4px;")
        self.btn_nuevo_proj = QPushButton("➕ Nuevo proyecto")
        self.btn_nuevo_proj.clicked.connect(self._nuevo_proyecto)
        fila_proj.addWidget(self.lbl_proyecto, stretch=1)
        fila_proj.addWidget(self.btn_nuevo_proj)
        raiz.addLayout(fila_proj)

        self.lbl_guia = QLabel("")
        self.lbl_guia.setWordWrap(True)
        self.lbl_guia.setStyleSheet(
            "background: #2b3a55; color: white; padding: 8px; border-radius: 4px;")
        raiz.addWidget(self.lbl_guia)

        # --- pila de pasos ---
        self.pila = QStackedWidget()

        # PASO 1: fuente
        pag1 = QWidget()
        lay1 = QVBoxLayout(pag1)
        fila1 = QHBoxLayout()
        self.btn_cargar = QPushButton("Cargar audio")
        self.btn_cargar.clicked.connect(self._cargar_audio)
        self.btn_stems = QPushButton("Procesar stems")
        self.btn_stems.setToolTip(
            "Gain staging (picos a -6 dBFS) + highpass por tipo de pista.\n"
            "Lee entrada/stems y escribe en salida/stems_niveladas (originales intactos).")
        self.btn_stems.clicked.connect(self._procesar_stems)
        fila1.addWidget(self.btn_cargar)
        fila1.addWidget(self.btn_stems)
        fila1.addStretch()
        lay1.addLayout(fila1)
        self.lbl_fuente = QLabel("Fuente: (ninguna)")
        lay1.addWidget(self.lbl_fuente)
        lay1.addStretch()
        self.pila.addWidget(pag1)

        # PASO 2: referencias + análisis opcional
        pag2 = QWidget()
        lay2 = QVBoxLayout(pag2)
        fila2 = QHBoxLayout()
        self.btn_ref = QPushButton("Elegir referencias…")
        self.btn_ref.clicked.connect(self._elegir_referencia)
        self.btn_analizar = QPushButton("Analizar (opcional)")
        self.btn_analizar.clicked.connect(self._analizar)
        fila2.addWidget(self.btn_ref)
        fila2.addWidget(self.btn_analizar)
        fila2.addStretch()
        lay2.addLayout(fila2)
        self.lbl_refs = QLabel("Referencias: (ninguna)")
        lay2.addWidget(self.lbl_refs)
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

        self.lbl_estado = QLabel("")
        raiz.addWidget(self.lbl_estado)

        self.setCentralWidget(central)

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
        self.btn_cargar.setEnabled(True)  # crea el proyecto desde el archivo
        self.btn_stems.setEnabled(hay_proyecto)
        self.btn_ref.setEnabled(hay_proyecto)
        self.btn_analizar.setEnabled(hay_proyecto and self.wav_activo is not None)
        self.btn_master.setEnabled(hay_proyecto and self._fuente_lista())
        self.btn_atras.setEnabled(idx > 0)
        self.btn_siguiente.setEnabled(
            hay_proyecto and idx < 2 and (idx != 0 or self._fuente_lista()))

        if not hay_proyecto:
            self.lbl_guia.setText(
                "<b>EMPIEZA AQUÍ:</b> pulsa «Cargar audio» y elige tu mezcla — el "
                "proyecto tomará el nombre del archivo. Para stems, usa «➕ Nuevo "
                "proyecto» y ponle nombre.")
        else:
            self.lbl_guia.setText(f"<b>{self.GUIA[idx]}</b>")

        # etiquetas de estado de fuente y referencias
        if self.wav_activo:
            self.lbl_fuente.setText(f"Fuente: mezcla «{self.wav_activo.name}»")
        elif self._fuente_lista():
            n = len(list(self.proyecto.dir_stems_niveladas.glob('*.wav')))
            self.lbl_fuente.setText(f"Fuente: {n} stems nivelados (suma virtual)")
        else:
            self.lbl_fuente.setText("Fuente: (ninguna)")
        if not self.referencia:
            self.lbl_refs.setText("Referencias: (ninguna — el master saldrá sin EQ correctivo)")
        elif len(self.referencia) == 1:
            self.lbl_refs.setText(f"Referencias: {self.referencia[0].name}")
        else:
            self.lbl_refs.setText(
                f"Referencias: {len(self.referencia)} temas (promedio/consenso)")

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

    def _abrir_chat(self):
        """Abre (o trae al frente) el diálogo de chat."""
        if self._chat is None:
            self._chat = ChatDialog(self)
        self._chat.show()
        self._chat.raise_()

    # ------------------------------------------------------- paso 1: fuente

    def _cargar_audio(self):
        """Carga una mezcla y crea el proyecto con el NOMBRE del archivo.

        El proyecto se nombra automáticamente como la canción (sin extensión).
        Si ya existe uno con ese nombre, lo reabre. Para stems se usa «Nuevo
        proyecto» (nombre manual).
        """
        inicio = str(self.proyecto.dir_originales) if self.proyecto else ""
        path, _ = QFileDialog.getOpenFileName(
            self, "Cargar audio", inicio, self.FILTRO_AUDIO)
        if not path:
            return
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

    def _procesar_stems(self):
        """Gain staging + highpass de todos los stems de entrada/stems."""
        if not self.proyecto:
            return
        if not any(self.proyecto.dir_stems.glob("*")):
            QMessageBox.information(
                self, "Sin stems",
                f"No hay archivos en:\n{self.proyecto.dir_stems}\n\n"
                "Exporta tus pistas del DAW (WAV 48k/24) a esa carpeta y vuelve a pulsar.")
            return
        self.btn_stems.setEnabled(False)
        self._status("Procesando stems…")
        self._stems_worker = StemsWorker(self.proyecto)
        self._stems_worker.progreso.connect(self._status)
        self._stems_worker.terminado.connect(self._stems_ok)
        self._stems_worker.fallo.connect(self._stems_error)
        self._stems_worker.start()

    def _stems_ok(self, reporte: dict):
        """Muestra el reporte de gain staging."""
        self.txt_resultado.append("\n" + reporte_stems_legible(reporte))
        self._status(f"Stems listos: {len(reporte['stems'])} nivelados")
        if reporte["stems"]:
            self._ir(1)  # auto-avanza a referencias
        else:
            self._refrescar_estado()

    def _stems_error(self, msg: str):
        self._refrescar_estado()
        self._status("Procesamiento de stems fallido (ver app.log).")
        QMessageBox.critical(self, "Error", f"No se pudieron procesar los stems:\n{msg}")

    # -------------------------------------------------- paso 2: referencias

    def _elegir_referencia(self):
        """Biblioteca del género o archivos sueltos; varias = promedio."""
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
            self.referencia = biblioteca
        else:
            inicio = str(self.proyecto.dir_referencias) if self.proyecto else ""
            paths, _ = QFileDialog.getOpenFileNames(
                self, "Elegir referencia(s) — puedes seleccionar varias (Ctrl+clic)",
                inicio, self.FILTRO_AUDIO)
            if not paths:
                return
            self.referencia = [Path(p) for p in paths]

        self._status(f"{len(self.referencia)} referencia(s) elegidas.")

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
            self._ir(2)  # fuente = stems: no hay mezcla única que analizar

    def _version_auto(self) -> str:
        """V01, V02… según cuántos diagnósticos ya tenga el proyecto."""
        n = len(list(self.proyecto.dir_analisis.glob("diagnostico_v*.json"))) + 1
        return f"V{n:02d}"

    def _analizar_auto(self):
        """Análisis automático tras elegir referencias (sin diálogos)."""
        self.btn_analizar.setEnabled(False)
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
        self.btn_analizar.setEnabled(False)
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
        eq = resumen.get("eq_aplicado_db") or {}
        eq_txt = ("\n  EQ aplicado (dB): " + ", ".join(f"{b} {v:+.1f}" for b, v in eq.items())
                  if eq else "\n  (sin EQ: no había referencia)")
        ancho = resumen.get("ajuste_ancho_db") or {}
        ancho_txt = ("\n  Imagen estéreo (side dB): "
                     + ", ".join(f"{b} {v:+.1f}" for b, v in ancho.items())
                     if ancho else "")
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
            f"Crest: {resumen.get('crest_final', '?')} dB{eq_txt}{ancho_txt}{den_txt}{mb_txt}\n"
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
