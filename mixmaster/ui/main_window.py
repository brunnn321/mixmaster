"""Ventana principal de MixMaster v0.4 — asistente por pantallas.

Flujo: PASO 1 Fuente (mezcla o stems) → PASO 2 Referencias (+análisis
opcional) → PASO 3 Master final.
"""

import json
from pathlib import Path

from PySide6.QtCore import (
    QEasingCurve, QEvent, QObject, QPropertyAnimation, QUrl, Qt, QThread, QTimer, Signal,
)
from PySide6.QtGui import QAction, QColor
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFileDialog, QFrame,
    QGraphicsDropShadowEffect, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QProgressBar, QPushButton, QScrollArea, QSlider,
    QStackedWidget, QStyle, QSystemTrayIcon, QTextEdit, QVBoxLayout, QWidget,
)

from .. import __version__
from ..app_paths import REFERENCIAS_DIR
from ..audio_analysis import analizar_wav
from ..daw_watch import DetectorBounces
from ..learning import consejo_mezcla, preferencias, registrar_aprobado, registrar_mezcla_propia
from ..logger import get_logger
from ..processing import cargar_config_master, masterizar
from ..profiles import listar_referencias_genero
from ..project import Project, abrir_proyecto, crear_proyecto, nombre_seguro
from ..references import detectar_etiqueta_sugerida
from ..report import comparar_progreso, guardar_diagnostico, reporte_legible
from ..settings import Settings
from ..stems import procesar_stems, reporte_stems_legible
from ..voice_processing import cargar_config_voz, procesar_voz
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


class _SliderClic(QSlider):
    """QSlider que salta directo a la posición clicada (no de a un page-step)."""

    saltar = Signal(int)  # nueva posición pedida por el usuario

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.maximum() > self.minimum():
            ratio = event.position().x() / max(1, self.width())
            valor = self.minimum() + round(ratio * (self.maximum() - self.minimum()))
            self.setValue(valor)
            self.saltar.emit(valor)
            event.accept()
        else:
            super().mousePressEvent(event)


class _HoverGlow(QObject):
    """Instala un halo animado que aparece al pasar el mouse por un botón.

    Reutilizable: `_HoverGlow.instalar(boton)`. El halo crece/decrece suave
    con QPropertyAnimation sobre el blurRadius del drop-shadow.
    """

    def __init__(self, boton, color=QColor(110, 168, 255, 180), maxblur=20):
        super().__init__(boton)
        self._efecto = QGraphicsDropShadowEffect(boton)
        self._efecto.setColor(color)
        self._efecto.setOffset(0, 0)
        self._efecto.setBlurRadius(0)
        boton.setGraphicsEffect(self._efecto)
        self._anim = QPropertyAnimation(self._efecto, b"blurRadius", self)
        self._anim.setDuration(160)
        self._maxblur = maxblur
        boton.installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Enter and obj.isEnabled():
            self._a(self._maxblur)
        elif event.type() == QEvent.Leave:
            self._a(0)
        return False

    def _a(self, destino):
        self._anim.stop()
        self._anim.setStartValue(self._efecto.blurRadius())
        self._anim.setEndValue(destino)
        self._anim.start()

    @staticmethod
    def instalar(boton, color=QColor(110, 168, 255, 180), maxblur=20):
        return _HoverGlow(boton, color, maxblur)


class _BotonMaster(QPushButton):
    """Botón con glow verde: late suave cuando está listo, se intensifica en hover.

    Demo de animación en Qt (QPropertyAnimation sobre el blurRadius del halo).
    """

    def __init__(self, texto: str, parent=None):
        super().__init__(texto, parent)
        self._glow = QGraphicsDropShadowEffect(self)
        self._glow.setColor(QColor(67, 224, 138, 200))
        self._glow.setOffset(0, 0)
        self._glow.setBlurRadius(0)
        self.setGraphicsEffect(self._glow)

        # pulso "respirando" (ida y vuelta, en bucle) para cuando está habilitado
        self._pulso = QPropertyAnimation(self._glow, b"blurRadius", self)
        self._pulso.setDuration(1600)
        self._pulso.setStartValue(8)
        self._pulso.setKeyValueAt(0.5, 26)
        self._pulso.setEndValue(8)
        self._pulso.setEasingCurve(QEasingCurve.InOutSine)
        self._pulso.setLoopCount(-1)

        # animación puntual para el hover
        self._hover = QPropertyAnimation(self._glow, b"blurRadius", self)
        self._hover.setDuration(180)

    def _anim_hover(self, destino: int):
        self._pulso.stop()
        self._hover.stop()
        self._hover.setStartValue(self._glow.blurRadius())
        self._hover.setEndValue(destino)
        self._hover.start()

    def enterEvent(self, event):
        if self.isEnabled():
            self._anim_hover(38)
        super().enterEvent(event)

    def leaveEvent(self, event):
        if self.isEnabled():
            self._hover.stop()
            self._pulso.start()
        super().leaveEvent(event)

    def setEnabled(self, on: bool):
        super().setEnabled(on)
        if on:
            self._pulso.start()
        else:
            self._pulso.stop()
            self._hover.stop()
            self._glow.setBlurRadius(0)


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


class VoiceWorker(QThread):
    """Ejecuta el pipeline de voz/podcast fuera del hilo de la UI."""

    progreso = Signal(str)
    terminado = Signal(dict)
    fallo = Signal(str)

    def __init__(self, entrada, salida, referencia=None, target_lufs=None, cfg=None):
        super().__init__()
        self.entrada, self.salida = entrada, salida
        self.referencia, self.target_lufs, self.cfg = referencia, target_lufs, cfg

    def run(self):
        """Corre la cadena de voz y emite el resumen o el error."""
        try:
            resumen = procesar_voz(
                self.entrada, self.salida, cfg=self.cfg,
                path_referencia=self.referencia, target_lufs=self.target_lufs,
                progreso=self.progreso.emit,
            )
            self.terminado.emit(resumen)
        except Exception as e:
            log.exception("Fallo en el procesamiento de voz")
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


class EscuchaWorker(QThread):
    """Genera la copia de escucha calibrada M50x fuera del hilo de la UI."""

    terminado = Signal(dict)
    fallo = Signal(str)

    def __init__(self, path_master: Path, dir_salida: Path):
        super().__init__()
        self.path_master, self.dir_salida = path_master, dir_salida

    def run(self):
        """Genera la copia M50x (nivel igualado) o emite el error."""
        try:
            from ..m50x_calibration import generar_copia_calibrada
            m50x = generar_copia_calibrada(self.path_master, self.dir_salida)
            self.terminado.emit({"m50x": m50x})
        except Exception as e:
            log.exception("Fallo generando la copia de escucha")
            self.fallo.emit(str(e))


class MainWindow(QMainWindow):
    """Asistente de 3 pasos: Fuente → Referencias → Master."""

    FILTRO_AUDIO = ("Audio (*.wav *.mp3 *.flac *.ogg *.aiff *.aif *.m4a *.wma);;"
                    "Todos los archivos (*.*)")

    GUIA = [
        "PASO 1 · Carga tu audio",
        "PASO 2 · Elige referencias",
        "PASO 3 · Masteriza",
    ]

    def __init__(self, settings: Settings):
        super().__init__()
        self.settings = settings
        self.proyecto: Project | None = None
        self.wav_activo: Path | None = None
        self.referencia: list[Path] | None = None
        self.diagnostico: dict | None = None
        self.etiqueta_sugerida: str = ""  # Etiqueta detectada de referencias
        self._worker = None
        self._modal = None  # ventana modal de progreso (bloquea la app mientras dura)
        self._notificado = False  # evita reentrada en closeEvent

        # Reproductor de escucha comparada: pre-master / master / M50x (v0.9)
        self._m50x_player = QMediaPlayer(self)
        self._m50x_audio_out = QAudioOutput(self)
        self._m50x_player.setAudioOutput(self._m50x_audio_out)
        self._m50x_player.positionChanged.connect(self._m50x_posicion_cambio)
        self._m50x_player.durationChanged.connect(self._m50x_duracion_cambio)
        self._m50x_path_premaster: Path | None = None
        self._m50x_path_master: Path | None = None
        self._m50x_path_calibrado: Path | None = None
        self._m50x_worker = None

        # "musica" | "voz" — se define al cargar, en `_preguntar_tipo_audio`
        self._modo_audio = "musica"

        # Vigilancia de la carpeta de bounces del DAW (ruta por proyecto).
        # Sondeo por timer en vez de QFileSystemWatcher: un listdir cada 2 s es
        # barato y evita los huecos conocidos del watcher nativo (eventos que
        # se pierden, rutas que hay que re-agregar tras cada cambio).
        self._detector_daw: DetectorBounces | None = None
        self._timer_daw = QTimer(self)
        self._timer_daw.timeout.connect(self._revisar_daw)

        # Aviso de cansancio auditivo — cada 90 min de sesión abierta
        self._timer_fatiga = QTimer(self)
        self._timer_fatiga.setInterval(90 * 60 * 1000)
        self._timer_fatiga.timeout.connect(self._avisar_fatiga)
        self._timer_fatiga.start()

        # Icono de bandeja para notificaciones nativas (fiable en Win11)
        from PySide6.QtGui import QIcon
        icono = Path(__file__).resolve().parents[2] / "assets" / "icon.ico"
        self._tray = QSystemTrayIcon(self)
        self._tray.setIcon(QIcon(str(icono)) if icono.exists()
                           else self.style().standardIcon(QStyle.SP_MediaVolume))
        self._tray.setToolTip("MixMaster")
        self._tray.show()

        self.setWindowTitle(f"MixMaster v{__version__}")
        self.resize(880, 680)
        self.setAcceptDrops(True)  # arrastrar audio/referencias a la app
        self._crear_menu()
        self._crear_ui()
        self._refrescar_estado()

        # Pantalla de inicio (elegir proyecto reciente o empezar nuevo)
        QTimer.singleShot(0, self._dialogo_inicio)

    def _dialogo_inicio(self):
        """Al abrir: proyectos recientes (doble clic abre) o «Nuevo» (vacío)."""
        from .inicio_dialog import InicioDialog
        base = self.settings.ruta_proyectos
        proys = []
        if base.is_dir():
            proys = sorted((p for p in base.iterdir() if p.is_dir()),
                           key=lambda p: p.stat().st_mtime, reverse=True)
        if not proys:
            return  # sin proyectos: directo al PASO 1 vacío
        dlg = InicioDialog(proys, self)
        if dlg.exec() and dlg.seleccionado:
            try:
                self._set_proyecto(abrir_proyecto(dlg.seleccionado))
            except Exception:
                log.exception("No se pudo abrir el proyecto elegido")

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
                        "MixMaster", "GUARDADO",
                        QSystemTrayIcon.MessageIcon.NoIcon, 2500)
                    QTimer.singleShot(600, self.close)  # cierra tras mostrar
                    event.ignore()
                    return
            except Exception:
                log.debug("Notificación no disponible; cierre normal")
        event.accept()

    # ------------------------------------------------------------- menú y UI

    def _crear_menu(self):
        """Barra de menú: Archivo, Proyecto, Settings, Herramientas."""
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
        acc_borrar = QAction("🗑 Borrar proyecto…", self)
        acc_borrar.triggered.connect(self._borrar_proyecto)
        self.acc_daw = QAction("📁 Carpeta del DAW…", self)
        self.acc_daw.setToolTip(
            "Elegí la carpeta donde tu DAW exporta los bounces de ESTA canción.\n"
            "Cuando aparezca un bounce nuevo, MixMaster te avisa para cargarlo\n"
            "sin que tengas que buscarlo a mano. Se guarda por proyecto.")
        self.acc_daw.triggered.connect(self._elegir_carpeta_daw)
        m_proyecto.addActions([acc_nuevo, acc_abrir, acc_carpeta, acc_borrar, self.acc_daw])

        m_settings = self.menuBar().addMenu("&Settings")
        acc_settings = QAction("Configuración…", self)
        acc_settings.triggered.connect(self._abrir_settings)
        m_settings.addAction(acc_settings)

        # Herramientas de uso ocasional, agrupadas en un solo menú (antes
        # competían por espacio como botones sueltos en la barra).
        m_herr = self.menuBar().addMenu("🛠 &Herramientas")
        acc_hist = QAction("📋 Historial", self)
        acc_hist.triggered.connect(self._abrir_historial)
        acc_masters = QAction("🎚 Masters", self)
        acc_masters.triggered.connect(self._abrir_masters)
        acc_notas = QAction("📝 Notas", self)
        acc_notas.triggered.connect(self._abrir_notas)
        acc_null = QAction("🔬 Null test", self)
        acc_null.triggered.connect(self._abrir_null_test)
        acc_ab_ciego = QAction("🙈 A/B ciego", self)
        acc_ab_ciego.triggered.connect(self._abrir_ab_ciego)
        m_herr.addActions([acc_hist, acc_masters, acc_notas, acc_null, acc_ab_ciego])

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

        # El tipo de audio (música / voz) NO se elige acá: se pregunta al
        # cargar, en `_preguntar_tipo_audio`. Un desplegable fijo se puede
        # ignorar sin querer y arrancás la cadena equivocada.
        self.lbl_modo = QLabel("")
        self.lbl_modo.setStyleSheet("color: #8a97b0;")
        lay1.addWidget(self.lbl_modo)

        self.chk_mi_mezcla = QCheckBox("Es una mezcla mía (aprender de mi sonido)")
        self.chk_mi_mezcla.setChecked(True)
        self.chk_mi_mezcla.setToolTip(
            "Si está marcado, la app guarda el carácter tonal de esta mezcla\n"
            "(graves, brillo, punch…) para encontrar patrones en cómo mezclás\n"
            "y aconsejarte con el tiempo. Desmarcalo si este audio no es tuyo\n"
            "(referencia externa, prueba, etc.) para no ensuciar ese aprendizaje.")
        lay1.addWidget(self.chk_mi_mezcla)
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
        self.btn_goniometro = QPushButton("📡 Ver imagen estéreo ▸")
        self.btn_goniometro.setToolTip(
            "Goniómetro: nube de puntos mid/side de la mezcla cargada (foto completa,\n"
            "no en vivo). Detecta problemas de fase o estéreo ANTES de masterizar.")
        self.btn_goniometro.clicked.connect(self._toggle_goniometro)
        self.btn_coaching = QPushButton("🔬 Diagnóstico de stems")
        self.btn_coaching.setToolTip(
            "Analiza cada stem por separado y te dice qué mejorar en tu MEZCLA\n"
            "(bajo sin definición, batería aplastada, guitarra embarrada…).\n"
            "Solo si cargaste stems (varios archivos).")
        self.btn_coaching.clicked.connect(self._abrir_coaching)
        fila_diag = QHBoxLayout()
        fila_diag.addWidget(self.btn_goniometro)
        fila_diag.addWidget(self.btn_coaching)
        lay2.addLayout(fila_diag)
        self.panel_goniometro = QWidget()
        self.panel_goniometro.setVisible(False)
        self._lay_goniometro = QVBoxLayout(self.panel_goniometro)
        lay2.addWidget(self.panel_goniometro)
        lay2.addStretch()
        self.pila.addWidget(pag2)

        # PASO 3: master
        pag3 = QWidget()
        lay3 = QVBoxLayout(pag3)
        self.lbl_tu_sonido = QLabel("")
        self.lbl_tu_sonido.setStyleSheet("color: #7fd99a; font-weight: bold;")
        self.lbl_tu_sonido.setVisible(False)
        lay3.addWidget(self.lbl_tu_sonido)
        self.btn_master = _BotonMaster("MASTER")
        self.btn_master.setMinimumHeight(64)
        self.btn_master.setCursor(Qt.PointingHandCursor)
        self.btn_master.setStyleSheet(
            "QPushButton { font-weight: 800; font-size: 20px; letter-spacing: 2px; color: white;"
            " border-radius: 10px; border: 1px solid #4fa76a;"
            " background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #4aa06a, stop:1 #2c6b46); }"
            " QPushButton:hover { background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #55b478, stop:1 #337a50); }"
            " QPushButton:pressed { background: #2a5f3e; }"
            " QPushButton:disabled { background: #2a3b31; color: #6f8579; border-color: #33463b; }")
        self.btn_master.setToolTip(
            "EQ 7 bandas + imagen estéreo hacia las referencias + densidad + "
            "loudness (-8.5 default) + limitador -1 dBTP.\n"
            "Config editable en config/master.json")
        self.btn_master.clicked.connect(self._masterizar)
        lay3.addWidget(self.btn_master)  # ancho completo — es el botón más importante

        # Panel de escucha comparada: original / master / M50x plano
        self.panel_m50x = QFrame()
        self.panel_m50x.setStyleSheet(
            "QFrame { border: 1px solid #5a6b8c; border-radius: 8px; padding: 4px; }")
        self.panel_m50x.setVisible(False)
        lay_m50x = QVBoxLayout(self.panel_m50x)
        lbl_m50x = QLabel("🎧 Escucha comparada")
        lbl_m50x.setStyleSheet("border: none; font-weight: bold;")
        lay_m50x.addWidget(lbl_m50x)

        fila_m50x = QHBoxLayout()
        self.btn_m50x_play = QPushButton("▶ Reproducir")
        self.btn_m50x_play.clicked.connect(self._m50x_toggle_play)
        self.combo_escucha = QComboBox()
        self.combo_escucha.addItems([
            "Mezcla original (sin masterizar)", "Master",
            "🎧 M50x plano (sin coloración)"])
        self.combo_escucha.setToolTip(
            "Cambia la fuente sin cortar: original antes de masterizar, el master,\n"
            "o la copia corregida para tus M50x.")
        self.combo_escucha.currentIndexChanged.connect(self._m50x_cambiar_fuente)
        fila_m50x.addWidget(self.btn_m50x_play)
        fila_m50x.addWidget(self.combo_escucha)
        fila_m50x.addStretch()
        lay_m50x.addLayout(fila_m50x)

        fila_seek = QHBoxLayout()
        self.lbl_tiempo = QLabel("0:00 / 0:00")
        self.lbl_tiempo.setStyleSheet("border: none;")
        self.slider_escucha = _SliderClic(Qt.Horizontal)
        self.slider_escucha.sliderMoved.connect(self._m50x_buscar_posicion)
        self.slider_escucha.saltar.connect(self._m50x_buscar_posicion)
        fila_seek.addWidget(self.slider_escucha, stretch=1)
        fila_seek.addWidget(self.lbl_tiempo)
        lay_m50x.addLayout(fila_seek)

        lay3.addWidget(self.panel_m50x)

        # Contenedor del panel A/B ciego embebido (se llena al pedirlo desde el menú)
        self.panel_ab_ciego_contenedor = QVBoxLayout()
        lay3.addLayout(self.panel_ab_ciego_contenedor)

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

        # --- resultados: pestañas Texto / Gráficas ---
        from PySide6.QtWidgets import QScrollArea, QTabWidget
        self.tabs_resultado = QTabWidget()
        self.txt_resultado = QTextEdit()
        self.txt_resultado.setReadOnly(True)
        self.txt_resultado.setPlaceholderText("Resultados de análisis, stems y master…")
        self.txt_resultado.setFontFamily("Consolas")
        self.tabs_resultado.addTab(self.txt_resultado, "📄 Texto")

        self._graficas_scroll = QScrollArea()
        self._graficas_scroll.setWidgetResizable(True)
        self._graficas_scroll.setStyleSheet(
            "QScrollArea { background: #0e1820; border: none; }"
            " QScrollArea > QWidget > QWidget { background: #0e1820; }")
        self._graficas_placeholder = QLabel(
            "Las gráficas (espectro pre/post + métricas) aparecen aquí al masterizar.")
        self._graficas_placeholder.setAlignment(Qt.AlignCenter)
        self._graficas_placeholder.setStyleSheet("color: #8a97b0; padding: 20px;")
        self._graficas_scroll.setWidget(self._graficas_placeholder)
        self.tabs_resultado.addTab(self._graficas_scroll, "📊 Gráficas")
        raiz.addWidget(self.tabs_resultado, stretch=1)

        self.barra = QProgressBar()
        self.barra.setTextVisible(True)
        self.barra.setFormat("%p% — %v/%m")
        self.barra.setFixedHeight(26)
        self.barra.setStyleSheet(
            "QProgressBar { border: 1px solid #3a7d4f; border-radius: 6px;"
            " background: #12161f; color: white; font-weight: bold; text-align: center; }"
            "QProgressBar::chunk { background: #3a7d4f; border-radius: 5px; }")
        self.barra.setVisible(False)
        raiz.addWidget(self.barra)

        self.lbl_estado = QLabel("")
        raiz.addWidget(self.lbl_estado)

        # Hover glow (animado) en los botones secundarios — reutilizable
        self._glows = [
            _HoverGlow.instalar(b) for b in (
                self.btn_goniometro, self.btn_coaching,
                self.btn_siguiente, self.btn_atras, self.btn_m50x_play)
        ]

        self.setCentralWidget(central)

    def _barra_activa(self, activa: bool, pasos: int = 14):
        """Barra con avance real + ventana emergente que bloquea la app mientras dura.

        Nota técnica: el bloqueo NO usa modalidad nativa de Qt/Windows (eso
        causó un deadlock real: QProgressDialog.setValue() dispara
        processEvents() internamente y, combinado con ApplicationModal
        creado ANTES de arrancar el QThread, el worker nunca llegaba a
        ejecutar). En su lugar: la ventana central se deshabilita entera
        (self.setEnabled(False)) — bloqueo garantizado, sin loops nativos
        ni reentrancia — y el popup es una ventana simple, no modal.
        """
        if activa:
            self._barra_valor = 0
            self.barra.setRange(0, pasos)
            self.barra.setValue(0)
            self.barra.setVisible(True)
            self.setEnabled(False)  # bloquea toda interacción con la app

            if self._modal is None:
                from PySide6.QtWidgets import QLabel, QProgressBar, QVBoxLayout, QWidget
                self._modal = QWidget(self, Qt.Window | Qt.FramelessWindowHint)
                self._modal.setWindowTitle("MixMaster")
                self._modal.setFixedSize(460, 130)
                self._modal.setStyleSheet(
                    "QWidget { background: #16202b; border: 1px solid #3a4a5c; border-radius: 8px; }"
                    " QLabel { color: #cddbe8; font-family: Consolas; font-size: 14px; background: transparent; border: none; }")
                lay = QVBoxLayout(self._modal)
                lay.setContentsMargins(20, 20, 20, 20)
                lay.setSpacing(12)
                self._modal_lbl = QLabel("Trabajando…")
                self._modal_bar = QProgressBar()
                self._modal_bar.setRange(0, pasos)
                self._modal_bar.setTextVisible(True)
                self._modal_bar.setFormat("%p% — %v/%m")
                self._modal_bar.setFixedHeight(26)
                self._modal_bar.setStyleSheet(
                    "QProgressBar { border: 1px solid #3a7d4f; border-radius: 6px;"
                    " background: #12161f; color: white; font-weight: bold; text-align: center; }"
                    "QProgressBar::chunk { background: #3a7d4f; border-radius: 5px; }")
                lay.addWidget(self._modal_lbl)
                lay.addWidget(self._modal_bar)
            else:
                self._modal_bar.setRange(0, pasos)
                self._modal_lbl.setText("Trabajando…")
            self._modal_bar.setValue(0)
            # centrado sobre la ventana principal
            geo = self.geometry()
            self._modal.move(
                geo.x() + (geo.width() - self._modal.width()) // 2,
                geo.y() + (geo.height() - self._modal.height()) // 2)
            self._modal.show()
        else:
            self.barra.setValue(self.barra.maximum())  # 100% al terminar
            self.barra.setVisible(False)
            if self._modal is not None:
                self._modal.hide()
            self.setEnabled(True)  # reactiva la app

    def _progreso(self, msg: str):
        """Estado + un paso más de barra/popup por cada aviso del motor."""
        self._status(msg)
        if self.barra.isVisible():
            self._barra_valor = min(self._barra_valor + 1, self.barra.maximum() - 1)
            self.barra.setValue(self._barra_valor)
        if self._modal is not None and self._modal.isVisible():
            self._modal_lbl.setText(msg)
            self._modal_bar.setValue(self._barra_valor)

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
        self.lbl_proyecto.setText(f"Proyecto activo: {nombre}")

        idx = self.pila.currentIndex()
        self.btn_master.setEnabled(hay_proyecto and self._fuente_lista())
        self.btn_atras.setEnabled(idx > 0)
        self.btn_siguiente.setEnabled(
            hay_proyecto and idx < 2 and (idx != 0 or self._fuente_lista()))

        if not hay_proyecto:
            self.lbl_guia.setText("<b>PASO 1 · Carga tu audio</b>")
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
            self.lbl_fuente.setText("Cargar audio / stems")
            self.lbl_fuente.setStyleSheet(_DROPZONE_VACIA)

        self._refrescar_referencias()
        self._refrescar_tu_sonido()

    UMBRAL_TU_SONIDO = 5  # masters aprobados desde los que se activa la sugerencia visible

    def _refrescar_tu_sonido(self):
        """Muestra «Tu sonido activado» cuando hay 5+ masters aprobados."""
        pref = preferencias(self.settings.genero_activo())
        n = pref.get("n", 0)
        if n >= self.UMBRAL_TU_SONIDO:
            extra = f" · crest típico {pref['crest_target']:g} dB" if pref.get("crest_target") else ""
            if pref.get("referencias_top"):
                top = pref["referencias_top"][0]
                extra += f" · tu referencia habitual: {top['nombre']} ({top['veces']}x)"
            self.lbl_tu_sonido.setText(
                f"✨ Tu sonido activado — {n} masters aprobados · "
                f"sugerimos {pref['target_lufs']:g} LUFS{extra}")
            self.lbl_tu_sonido.setVisible(True)
        else:
            self.lbl_tu_sonido.setVisible(False)

    def _refrescar_referencias(self):
        """Reconstruye las tarjetas (chips) de referencias del PASO 2."""
        # limpia los chips actuales
        while self.refs_layout.count():
            item = self.refs_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self.referencia:
            self.zona_refs.setText("Cargar 1 referencia")
            self.zona_refs.setStyleSheet(_DROPZONE_VACIA)
            self.refs_contenedor.setVisible(False)
            return

        self.zona_refs.setText("📀  Referencia — arrastra o haz clic para cambiarla")
        self.zona_refs.setStyleSheet(_DROPZONE_LLENA)
        self.refs_contenedor.setVisible(True)
        for i, ref in enumerate(self.referencia):
            self.refs_layout.addWidget(self._crear_chip(i, ref))

    def _crear_chip(self, indice: int, ref: Path) -> QFrame:
        """Una tarjeta de referencia: nombre + 🔍 ficha + ✕ para quitarla."""
        chip = QFrame()
        chip.setStyleSheet(
            "QFrame { border: 1px solid #3a7d4f; border-radius: 8px;"
            " background: rgba(58,125,79,0.14); }")
        fila = QHBoxLayout(chip)
        fila.setContentsMargins(10, 4, 6, 4)
        lbl = QLabel(f"📀  {ref.name}")
        lbl.setStyleSheet("border: none; background: transparent;")
        btn_ver = QPushButton("🔍")
        btn_ver.setFixedWidth(28)
        btn_ver.setToolTip("Ver ficha del análisis (espectro, carácter tonal, ancho estéreo)")
        btn_ver.setStyleSheet("border: none; background: transparent;")
        btn_ver.clicked.connect(lambda: self._ver_ficha_referencia(ref))
        btn = QPushButton("✕")
        btn.setFixedWidth(28)
        btn.setToolTip("Quitar esta referencia")
        btn.setStyleSheet("border: none; background: transparent; font-weight: bold;")
        btn.clicked.connect(lambda: self._quitar_referencia(indice))
        fila.addWidget(lbl, stretch=1)
        fila.addWidget(btn_ver)
        fila.addWidget(btn)
        return chip

    def _ver_ficha_referencia(self, ref: Path):
        """Abre la ficha rica (visual) del análisis de esta referencia."""
        from .ficha_referencia import FichaReferenciaDialog
        FichaReferenciaDialog(ref, self).exec()

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
        # el modo vuelve a música: se redefine al cargar audio (los stems
        # siempre son música, por eso no preguntan)
        self._aplicar_modo_audio("musica")
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
        self._arrancar_vigilancia_daw()
        self._ir(0)

    # -------------------------------------------------- carpeta del DAW

    def _elegir_carpeta_daw(self):
        """Elige la carpeta de bounces del DAW para el proyecto activo."""
        if not self.proyecto:
            QMessageBox.information(
                self, "Sin proyecto",
                "Abrí o creá un proyecto primero: la carpeta se guarda por proyecto.")
            return
        actual = self.proyecto.carpeta_daw
        elegida = QFileDialog.getExistingDirectory(
            self, "Carpeta donde tu DAW exporta los bounces",
            str(actual) if actual else "")
        if not elegida:
            return
        self.proyecto.set_config("carpeta_daw", elegida)
        self._arrancar_vigilancia_daw()
        self._status(f"Vigilando bounces en {Path(elegida).name}.")

    def _arrancar_vigilancia_daw(self):
        """Arranca (o detiene) la vigilancia según la config del proyecto."""
        carpeta = self.proyecto.carpeta_daw if self.proyecto else None
        if not carpeta or not Path(carpeta).is_dir():
            self._detector_daw = None
            self._timer_daw.stop()
            return
        self._detector_daw = DetectorBounces(carpeta)
        self._timer_daw.start(2000)   # sondeo liviano: un listdir cada 2 s
        log.info("Vigilando carpeta del DAW: %s", carpeta)

    def _revisar_daw(self):
        """Avisa de bounces nuevos ya terminados de escribir."""
        if not self._detector_daw:
            return
        nuevos = self._detector_daw.revisar()
        if not nuevos:
            return
        # si cayeron varios de una, el más reciente es el que interesa
        bounce = nuevos[-1]
        resp = QMessageBox.question(
            self, "Bounce nuevo del DAW",
            f"Apareció un bounce nuevo:\n\n{bounce.name}\n\n¿Lo cargo como mezcla activa?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if resp == QMessageBox.Yes:
            self._cargar_audio_desde_path(str(bounce))

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

    def _borrar_proyecto(self):
        """Elige y borra un proyecto entero de la carpeta proyectos/ (irreversible)."""
        base = self.settings.ruta_proyectos
        if not base.is_dir():
            QMessageBox.information(self, "Borrar proyecto", "No hay proyectos aún.")
            return
        proys = sorted((p for p in base.iterdir() if p.is_dir()),
                       key=lambda p: p.stat().st_mtime, reverse=True)
        if not proys:
            QMessageBox.information(self, "Borrar proyecto", "No hay proyectos aún.")
            return
        nombres = [p.name for p in proys]
        elegido, ok = QInputDialog.getItem(
            self, "Borrar proyecto", "Elige el proyecto a borrar (no se puede deshacer):",
            nombres, 0, False)
        if not ok:
            return
        objetivo = proys[nombres.index(elegido)]
        if QMessageBox.question(
                self, "Confirmar borrado",
                f"¿Borrar «{elegido}» y TODO su contenido (masters, análisis, referencias "
                "usadas, notas)?\nEsto no se puede deshacer.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            import shutil
            shutil.rmtree(objetivo)
            log.info("Proyecto borrado: %s", objetivo)
        except Exception as e:
            log.exception("Error borrando proyecto")
            QMessageBox.critical(self, "Error", f"No se pudo borrar:\n{e}")
            return
        if self.proyecto and self.proyecto.root == objetivo:
            self.proyecto = None
            self.wav_activo = None
            self.referencia = None
            self.diagnostico = None
            self.settings.set("ultimo_proyecto", "")
            self.txt_resultado.clear()
            self._ir(0)
        self._status(f"Proyecto «{elegido}» borrado.")

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

    def _abrir_null_test(self):
        """Resta 2 masters (fase invertida) → escuchás SOLO la diferencia."""
        if not self.proyecto:
            QMessageBox.information(self, "Null test", "Abre o crea un proyecto primero.")
            return
        masters = self.proyecto.listar_masters()
        if len(masters) < 2:
            QMessageBox.information(
                self, "Null test",
                "Necesitas al menos 2 masters de este proyecto para comparar.\n"
                "Genera otra versión en el PASO 3.")
            return
        nombres = [m.name for m in masters]
        a, ok = QInputDialog.getItem(self, "Null test", "Versión A:", nombres, 0, False)
        if not ok:
            return
        otros = [n for n in nombres if n != a]
        b, ok = QInputDialog.getItem(self, "Null test", "Versión B (se resta de A):", otros, 0, False)
        if not ok:
            return
        from PySide6.QtWidgets import QApplication
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            from ..null_test import generar_diferencia
            path_a = masters[nombres.index(a)]
            path_b = masters[nombres.index(b)]
            r = generar_diferencia(path_a, path_b, self.proyecto.dir_masters / "null_test")
        except Exception as e:
            log.exception("Fallo generando null test")
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "Null test", f"No se pudo generar:\n{e}")
            return
        QApplication.restoreOverrideCursor()
        try:
            import os
            os.startfile(str(Path(r["ruta"]).parent))
        except Exception:
            log.exception("No se pudo abrir la carpeta del null test")
        QMessageBox.information(
            self, "Null test listo",
            f"{r['nota']}\n\n"
            f"Nivel de la diferencia: {r['rms_diferencia_db']} dB RMS\n"
            f"(B se ajustó {r['gain_b_aplicado_db']:+.1f} dB para igualar loudness antes de restar)\n\n"
            f"Archivo: {Path(r['ruta']).name}")

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

    def _avisar_fatiga(self):
        """Aviso cada 90 min: el oído se cansa y las decisiones de agudos se sesgan."""
        try:
            if QSystemTrayIcon.supportsMessages():
                self._tray.showMessage(
                    "👂 Pausa recomendada",
                    "Llevas 90+ min escuchando — tu oído puede estar sesgado "
                    "(sobre todo en agudos). Considera un descanso.",
                    QSystemTrayIcon.MessageIcon.Information, 6000)
        except Exception:
            log.debug("No se pudo mostrar el aviso de fatiga auditiva")

    def _abrir_notas(self):
        """Abre el diario de sesión del proyecto activo."""
        if not self.proyecto:
            QMessageBox.information(self, "Notas", "Abre o crea un proyecto primero.")
            return
        from .notas_dialog import NotasDialog
        NotasDialog(self.proyecto, self).exec()

    def _abrir_ab_ciego(self):
        """Compara a ciegas los 2 masters más recientes — panel embebido en PASO 3."""
        if not self.proyecto:
            QMessageBox.information(self, "A/B ciego", "Abre o crea un proyecto primero.")
            return
        masters = self.proyecto.listar_masters()
        if not masters:
            QMessageBox.information(
                self, "A/B ciego",
                "Todavía no hay masters. Genera uno en el PASO 3 primero.")
            return

        # El master más nuevo (recién hecho) es siempre el fijo. Se elige contra qué.
        fijo = masters[0]
        candidatos = {}
        for m in masters[1:]:
            candidatos[f"Master anterior — {m.name}"] = m
        if self.wav_activo:
            candidatos[f"Mezcla original (sin masterizar) — {self.wav_activo.name}"] = self.wav_activo
        if not candidatos:
            QMessageBox.information(
                self, "A/B ciego",
                "Necesitas otra cosa para comparar: genera otra versión de master\n"
                "o carga una mezcla original en el PASO 1.")
            return

        etiqueta, ok = QInputDialog.getItem(
            self, "A/B ciego",
            f"Comparar el master nuevo ({fijo.name}) a ciegas contra:",
            list(candidatos.keys()), 0, False)
        if not ok:
            return
        contra = candidatos[etiqueta]

        while self.panel_ab_ciego_contenedor.count():
            item = self.panel_ab_ciego_contenedor.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        from .ab_ciego_dialog import PanelABCiego
        self.panel_ab_ciego_contenedor.addWidget(
            PanelABCiego(self.proyecto, fijo, contra, self))
        self._ir(2)  # asegura estar en PASO 3 para verlo

    # ------------------------------------------------------- paso 1: fuente

    def _cargar_audio_desde_path(self, path: str):
        """Carga una mezcla (de diálogo o drag&drop) y crea/reabre el proyecto.

        El proyecto se nombra automáticamente como la canción (sin extensión).
        Si ya existe uno con ese nombre, lo reabre.
        """
        archivo = Path(path)

        # Se pregunta ANTES de crear nada: si cancela, no queda un proyecto
        # a medio hacer ni saltamos de paso sin que haya elegido.
        modo = self._preguntar_tipo_audio(archivo)
        if modo is None:
            self._status("Carga cancelada.")
            return

        try:
            base = self.settings.ruta_proyectos
            base.mkdir(parents=True, exist_ok=True)
            nombre = nombre_seguro(archivo.stem) or self._nombre_proyecto_libre()
            destino = base / nombre
            proyecto = (abrir_proyecto(destino) if destino.is_dir()
                        else crear_proyecto(base, nombre))
            self._set_proyecto(proyecto)   # ¡ojo! esto resetea wav_activo
        except Exception as e:
            log.exception("Error creando proyecto desde el audio")
            QMessageBox.critical(self, "Error", f"No se pudo crear el proyecto:\n{e}")
            return
        self.wav_activo = archivo
        self._aplicar_modo_audio(modo)
        self._status(f"Proyecto «{self.proyecto.nombre}» — {archivo.name}")
        # Voz también pasa por PASO 2: ahí es donde se carga la referencia
        # (opcional en ambos modos, pero si no se pasa por la pantalla no hay
        # forma de agregarla).
        self._ir(1)

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

    def _nombre_proyecto_libre(self) -> str:
        """Siguiente 'proyecto NN' libre (fallback cuando no hay nombre útil)."""
        base = self.settings.ruta_proyectos
        n = 1
        while (base / f"proyecto {n:02d}").exists():
            n += 1
        return f"proyecto {n:02d}"

    def _cargar_stems_desde_paths(self, paths):
        """Crea un proyecto con nombre derivado, copia los stems y los nivela."""
        import os
        import shutil
        archivos = [Path(p) for p in paths]
        # nombre del proyecto: prefijo común de los nombres; si no hay, "proyecto NN"
        prefijo = os.path.commonprefix([a.stem for a in archivos]).strip(" -_·")
        nombre = prefijo or self._nombre_proyecto_libre()
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
        self._stems_worker.setParent(self)
        self._stems_worker.progreso.connect(self._progreso)
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

    def _abrir_coaching(self):
        """Diagnóstico por stem (coaching de mezcla). Requiere stems cargados."""
        if not self.proyecto:
            QMessageBox.information(self, "Diagnóstico", "Carga primero tu audio o stems.")
            return
        carpeta = self.proyecto.dir_stems
        if not carpeta.is_dir() or not any(carpeta.glob("*")):
            QMessageBox.information(
                self, "Diagnóstico de stems",
                "Esto analiza cada stem por separado.\n\n"
                "Cargá varios archivos (stems) en el PASO 1 para usarlo. "
                "Con una mezcla única (1 archivo) no aplica.")
            return
        from .coaching_dialog import CoachingDialog
        CoachingDialog(carpeta, self).exec()

    def _toggle_goniometro(self):
        """Muestra/oculta el goniómetro embebido (foto de la mezcla, no en vivo)."""
        if self.panel_goniometro.isVisible():
            self.panel_goniometro.setVisible(False)
            self.btn_goniometro.setText("📡 Ver imagen estéreo ▸")
            return
        if not self.wav_activo:
            QMessageBox.information(
                self, "Imagen estéreo", "Carga una mezcla (no stems) para verla.")
            return
        while self._lay_goniometro.count():
            item = self._lay_goniometro.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        from .goniometro_dialog import construir_panel_goniometro
        self._lay_goniometro.addWidget(construir_panel_goniometro(self.wav_activo))
        self.panel_goniometro.setVisible(True)
        self.btn_goniometro.setText("📡 Ocultar imagen estéreo ▾")

    def _elegir_referencia(self):
        """Elige UNA referencia de tu biblioteca (cada tema es un preset único)."""
        if not self.proyecto:
            QMessageBox.information(self, "Referencia", "Carga primero tu audio o stems.")
            return
        # Diálogo de 1 archivo, apuntando a tu biblioteca de referencias.
        dlg = QFileDialog(self, "Elegir 1 referencia")
        dlg.setFileMode(QFileDialog.ExistingFile)
        dlg.setNameFilter(self.FILTRO_AUDIO)
        dlg.setDirectory(str(REFERENCIAS_DIR))
        if dlg.exec():
            paths = dlg.selectedFiles()
            if paths:
                self._set_referencias_desde_paths([Path(paths[0])])

    def _set_referencias_desde_paths(self, refs):
        """Fija UNA sola referencia (cada tema es un preset único; no se promedia).

        Si sueltan varias, se toma la primera. Reemplaza la referencia anterior.
        """
        refs = [Path(p) for p in refs]
        if not refs:
            return
        if len(refs) > 1:
            self._status(f"Se usa 1 referencia: {refs[0].name} (el master no promedia varias).")
        self.referencia = [refs[0]]   # lista de 1 (el motor espera lista)

        if self._modo_voz():
            # Voz no usa el análisis de música (MFCC, imaging, spectral
            # flux…): es lento, irrelevante para voz, y encima registraba la
            # grabación como "mezcla propia" del género activo — ensuciaba
            # el aprendizaje de música con datos de voz. Directo al paso 3.
            self._refrescar_estado()
            self._ir(2)
            return

        from PySide6.QtWidgets import QApplication
        self._barra_activa(True)
        QApplication.processEvents()

        if self.wav_activo:
            self._analizar_auto()  # analiza solo y luego salta al master
        else:
            self._barra_activa(False)
            self._refrescar_estado()
            self._ir(2)  # fuente = stems: no hay mezcla única que analizar

    def _version_auto(self) -> str:
        """V01, V02… según cuántos diagnósticos ya tenga el proyecto."""
        n = len(list(self.proyecto.dir_analisis.glob("diagnostico_v*.json"))) + 1
        return f"V{n:02d}"

    def _analizar_auto(self):
        """Análisis automático tras elegir referencias (sin diálogos).

        Si ya hay un análisis en curso (p. ej. agregaste otra referencia antes
        de que termine el anterior) NO se lanza uno nuevo encima — eso pisaba
        el hilo previo y hacía crashear la app sin dejar rastro en el log.
        """
        if self._worker is not None and self._worker.isRunning():
            self._status("Ya hay un análisis en curso — espera a que termine.")
            return
        self._barra_activa(True)
        self.txt_resultado.setPlainText("Analizando automáticamente contra tus referencias…")
        _, umbrales = self.settings.leer_genero_activo()
        self._worker = AnalisisWorker(
            self.wav_activo, self.ed_marcadores.text(), self.referencia,
            self._version_auto(), umbrales)
        self._worker.setParent(self)  # evita que Python lo recolecte a medio correr
        self._worker.progreso.connect(self._progreso)
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
        self._worker.setParent(self)
        self._worker.progreso.connect(self._progreso)
        self._worker.terminado.connect(self._analisis_ok)
        self._worker.fallo.connect(self._analisis_error)
        self._worker.start()

    def _analisis_ok(self, diag: dict):
        """Guarda y muestra el diagnóstico — conecta con el anterior (progreso)."""
        self._barra_activa(False)
        self.diagnostico = diag

        progreso_txt = None
        anterior_path = self.proyecto.ultimo_diagnostico()  # ANTES de sobrescribir
        if anterior_path is not None:
            try:
                anterior = json.loads(anterior_path.read_text(encoding="utf-8"))
                if anterior.get("version") != diag.get("version"):  # no compararse consigo mismo
                    progreso_txt = comparar_progreso(diag, anterior)
            except Exception:
                log.exception("No se pudo comparar contra el diagnóstico anterior")

        try:
            path_json, _ = guardar_diagnostico(self.proyecto, diag)
            self._status(f"Diagnóstico guardado: {path_json.name}")
        except Exception:
            log.exception("No se pudo guardar el diagnóstico")
            self._status("⚠ Análisis OK pero no se pudo guardar (ver app.log)")

        consejo_txt = None
        caracter = diag.get("caracter")
        if caracter and self.chk_mi_mezcla.isChecked():
            genero = self.settings.genero_activo()
            try:
                consejo_txt = consejo_mezcla(genero, caracter)
                registrar_mezcla_propia(genero, caracter)
            except Exception:
                log.exception("No se pudo registrar la mezcla propia para aprendizaje")

        texto = reporte_legible(diag)
        if progreso_txt:
            texto = progreso_txt + "\n\n" + texto
        if consejo_txt:
            texto = consejo_txt + "\n\n" + texto
        self.txt_resultado.setPlainText(texto)
        self._refrescar_estado()

    def _analisis_error(self, msg: str):
        self._barra_activa(False)
        self.txt_resultado.setPlainText(
            f"Error en el análisis:\n{msg}\n\n(Detalles en logs/app.log)")
        self._refrescar_estado()
        self._status("Análisis fallido.")

    # ------------------------------------------------------ paso 3: master

    def _advertir_si_sobreprocesada(self) -> bool:
        """Avisa si la mezcla ya viene comprimida/limitada — el master no puede
        arreglar eso, solo empeorarlo (sin margen dinámico para trabajar).

        Devuelve False si el usuario elige volver atrás (cancela el master).
        """
        g = self.diagnostico.get("global", {})
        crest = g.get("crest_factor_db")
        tp = g.get("true_peak_db")
        clip = self.diagnostico.get("clipping_global")
        motivos = []
        if crest is not None and crest < 6.0:
            motivos.append(f"crest factor muy bajo ({crest:.1f} dB — ya está aplastada)")
        if tp is not None and tp > -0.3:
            motivos.append(f"true peak casi en 0 ({tp:.1f} dBTP — sin margen)")
        if clip:
            motivos.append("clipping detectado")
        if not motivos:
            return True

        r = QMessageBox.warning(
            self, "⚠ Esta mezcla ya parece comprimida/limitada",
            "Detectamos: " + ", ".join(motivos) + ".\n\n"
            "El master no puede recuperar dinámica que ya se perdió — "
            "en el mejor caso queda igual, en el peor suena peor (saturado).\n\n"
            "Recomendado: usar la mezcla SIN procesado del canal máster "
            "(sin limitador/compresor en el bus general) y dejar que el "
            "master haga ese trabajo.\n\n"
            "¿Masterizar de todos modos?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        return r == QMessageBox.Yes

    def _modo_voz(self) -> bool:
        """True si el audio cargado se marcó como voz/podcast."""
        return self._modo_audio == "voz"

    def _preguntar_tipo_audio(self, archivo: Path) -> str | None:
        """Popup al cargar: ¿música o voz? Devuelve 'musica'/'voz' o None.

        Se pregunta acá y no con un control fijo en PASO 1 porque cada cadena
        es distinta de punta a punta: elegir mal y darse cuenta al final
        significa rehacer todo.
        """
        # QDialog propio en vez de QMessageBox: el QMessageBox de Qt solo
        # habilita la X del título y Esc si le agregás un botón con
        # RejectRole, o sea un tercer botón "Cancelar" en pantalla. Acá van
        # DOS botones y la X / Esc cancelan igual. Sin explicaciones en
        # pantalla: el detalle de cada cadena está en el tooltip.
        dlg = QDialog(self)
        dlg.setWindowTitle("MixMaster")

        lay = QVBoxLayout(dlg)
        lbl = QLabel(f"<b>{archivo.name}</b>")
        lbl.setAlignment(Qt.AlignCenter)
        lay.addWidget(lbl)

        fila = QHBoxLayout()
        btn_musica = QPushButton("🎵  Música")
        btn_musica.setToolTip("EQ hacia tus referencias, multibanda, imagen "
                              "estéreo, densidad y loudness competitivo.")
        btn_musica.setMinimumHeight(44)
        btn_musica.setDefault(True)
        btn_voz = QPushButton("🎙️  Voz")
        btn_voz.setToolTip("Puerta de ruido, compresión suave, de-esser y "
                           "limitador. Loudness de plataformas de voz.")
        btn_voz.setMinimumHeight(44)
        fila.addWidget(btn_musica)
        fila.addWidget(btn_voz)
        lay.addLayout(fila)

        elegido = {"modo": None}
        btn_musica.clicked.connect(lambda: (elegido.update(modo="musica"), dlg.accept()))
        btn_voz.clicked.connect(lambda: (elegido.update(modo="voz"), dlg.accept()))

        dlg.exec()          # cerrar con la X o Esc deja 'modo' en None
        return elegido["modo"]

    def _aplicar_modo_audio(self, modo: str):
        """Fija el modo y adapta el botón principal y el aviso de PASO 1."""
        self._modo_audio = modo
        if modo == "voz":
            self.btn_master.setText("PROCESAR VOZ")
            self.lbl_modo.setText("🎙️ Voz / Podcast — gate, compresión, de-esser, limitador")
            self._status("Modo Voz/Podcast.")
        else:
            self.btn_master.setText("MASTER")
            self.lbl_modo.setText("🎵 Música — cadena de mastering completa")
            self._status("Modo Música.")

    def _procesar_voz(self):
        """Corre la cadena de voz/podcast sobre el audio cargado."""
        if not self.wav_activo:
            QMessageBox.information(self, "Sin fuente", "Vuelve al PASO 1 y carga un audio.")
            return

        cfg = cargar_config_voz()
        entrada = Path(self.wav_activo)
        # el default depende de mono/estéreo, que solo sabe el motor al cargar;
        # se ofrece el de mono como punto de partida y se aclara en el diálogo
        sugerido = float(cfg["target_lufs_mono"])
        target, ok = QInputDialog.getDouble(
            self, "Voz / Podcast",
            "LUFS integrado objetivo\n"
            "(-16 mono / -19 estéreo son los estándar de plataformas de podcast;\n"
            "subilo o bajalo según cuán potente quieras la voz):",
            sugerido, -30.0, -6.0, 1)
        if not ok:
            return

        ref = self.referencia
        if isinstance(ref, list):
            ref = ref[0] if ref else None
        if ref:
            self._status(f"Voz con matching tonal suave hacia {Path(ref).name}.")

        # Copia la grabación original y la referencia a salida/, junto al
        # resultado: para voz no hay biblioteca de referencias curada como
        # en música, suelen ser archivos sueltos (una descarga, una toma) —
        # si se borran de donde estaban, el proyecto los conserva igual.
        self.proyecto.dir_entregables.mkdir(parents=True, exist_ok=True)
        import shutil
        for origen in (entrada, Path(ref) if ref else None):
            if origen is None:
                continue
            destino = self.proyecto.dir_entregables / origen.name
            try:
                if origen.resolve() != destino.resolve():
                    shutil.copy2(str(origen), str(destino))
            except Exception:
                log.exception("No se pudo copiar %s a la carpeta del proyecto", origen)

        salida = self.proyecto.dir_entregables / f"{entrada.stem}_voz.wav"
        self.btn_master.setEnabled(False)
        self._barra_activa(True)
        self._status("Procesando voz…")
        self._voice_worker = VoiceWorker(entrada, salida, referencia=ref,
                                         target_lufs=target, cfg=cfg)
        self._voice_worker.setParent(self)
        self._voice_worker.progreso.connect(self._progreso)
        self._voice_worker.terminado.connect(self._voz_ok)
        self._voice_worker.fallo.connect(self._voz_error)
        self._voice_worker.start()

    def _voz_ok(self, resumen: dict):
        """Muestra el resultado del procesamiento de voz.

        No pasa por `_preguntar_aprobado`/`_generar_m50x`/gráficas: esas son
        del flujo musical (aprenden LUFS/EQ/crest por género y comparan contra
        referencias de música), meter voz ahí ensuciaría ese aprendizaje.
        """
        self._barra_activa(False)
        self._refrescar_estado()
        eq = resumen.get("eq_referencia_db") or {}
        eq_txt = ("\n  EQ hacia la referencia (dB): "
                  + ", ".join(f"{b} {v:+.1f}" for b, v in eq.items() if abs(v) >= 0.1)
                  + f"\n  Referencia: {resumen['referencia']}") if eq else ""
        canal = "mono" if resumen.get("mono") else "estéreo"
        self.txt_resultado.append(
            f"\n══ VOZ / PODCAST LISTO ({canal}) ══\n"
            f"  LUFS final: {resumen['lufs_final']} (objetivo {resumen['target_lufs']})\n"
            f"  True peak: {resumen['true_peak_final']} dBTP   "
            f"Crest: {resumen.get('crest_final', '?')} dB{eq_txt}\n"
            f"  WAV: {resumen['wav']}")
        self._status(f"Voz lista → {Path(resumen['wav']).name}")
        try:
            import os
            os.startfile(str(Path(resumen["wav"]).parent))
        except Exception:
            log.exception("No se pudo abrir la carpeta de salida")

    def _masterizar(self):
        """Masteriza la mezcla o los stems nivelados → WAV + MP3 en salida/."""
        if not self.proyecto:
            return
        if self._modo_voz():
            self._procesar_voz()
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

        if not carpeta_stems and self.diagnostico and not self._advertir_si_sobreprocesada():
            return  # el usuario decidió volver atrás

        cfg = cargar_config_master()
        # loudness por defecto: el aprendido del género si existe, si no el de config
        pref = preferencias(self.settings.genero_activo())
        default_lufs = pref.get("target_lufs", float(cfg.get("target_lufs_default", -9.0)))

        from ..loudness_targets import TARGETS_PLATAFORMA
        nota_aprendido = (f"Personalizado — tu aprendido ({default_lufs:g} LUFS, "
                          f"de {pref['n']} masters)") if pref else f"Personalizado ({default_lufs:g} LUFS)"
        opciones = [nota_aprendido] + list(TARGETS_PLATAFORMA.keys()) + ["Otro (elegir manual)…"]
        elegido, ok = QInputDialog.getItem(
            self, "Master final", "Loudness objetivo — destino:", opciones, 0, False)
        if not ok:
            return

        if elegido == nota_aprendido:
            target = default_lufs
        elif elegido in TARGETS_PLATAFORMA:
            info = TARGETS_PLATAFORMA[elegido]
            target = info["lufs"]
            self._status(f"{elegido}: {info['nota']}")
        else:
            target, ok = QInputDialog.getDouble(
                self, "Loudness manual", "LUFS integrado objetivo:", default_lufs, -20.0, -5.0, 1)
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
        self._master_worker.setParent(self)
        self._master_worker.progreso.connect(self._progreso)
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
        self._mostrar_graficas(resumen)
        self._generar_m50x(resumen)
        self._preguntar_aprobado(resumen)

    def _mostrar_graficas(self, resumen: dict):
        """Genera el panel de gráficas (espectro pre/post + métricas) y lo muestra."""
        try:
            from .graficas import construir_panel_mastering
            panel = construir_panel_mastering(resumen, self.diagnostico, self.wav_activo)
            self._graficas_scroll.setWidget(panel)
            self.tabs_resultado.setCurrentIndex(1)  # salta a la pestaña de gráficas
        except Exception:
            log.exception("No se pudieron generar las gráficas")

    # ------------------------------------------------------- escucha comparada

    def _generar_m50x(self, resumen: dict):
        """Lanza en segundo plano la copia de escucha calibrada M50x."""
        self.panel_m50x.setVisible(False)
        self._m50x_path_premaster = self.wav_activo  # None si viene de stems (sin "original" único)
        self._m50x_path_master = Path(resumen["wav"])
        self._m50x_path_calibrado = None
        self._m50x_worker = EscuchaWorker(self._m50x_path_master, self._m50x_path_master.parent)
        self._m50x_worker.setParent(self)
        self._m50x_worker.terminado.connect(self._m50x_listo)
        self._m50x_worker.fallo.connect(self._m50x_error)
        self._m50x_worker.start()

    def _m50x_listo(self, info: dict):
        """Copia generada: muestra el panel de escucha comparada."""
        self._m50x_path_calibrado = Path(info["m50x"]["ruta"])
        # sin mezcla pre-master única (master por stems): arranca directo en "Master"
        arranque = 1 if not self._m50x_path_premaster else 0
        self.combo_escucha.model().item(0).setEnabled(bool(self._m50x_path_premaster))
        self._m50x_player.setSource(QUrl.fromLocalFile(
            str(self._m50x_path_premaster or self._m50x_path_master)))
        self.combo_escucha.blockSignals(True)
        self.combo_escucha.setCurrentIndex(arranque)
        self.combo_escucha.blockSignals(False)
        self.btn_m50x_play.setText("▶ Reproducir")
        self.panel_m50x.setVisible(True)
        self._status("Copia de escucha M50x lista.")

    def _m50x_error(self, msg: str):
        """Falla la copia: no bloquea el flujo, solo se oculta el panel."""
        log.warning("No se pudo generar la copia de escucha: %s", msg)
        self.panel_m50x.setVisible(False)

    def _m50x_toggle_play(self):
        """Play/pausa del reproductor de escucha comparada."""
        if self._m50x_player.playbackState() == QMediaPlayer.PlayingState:
            self._m50x_player.pause()
            self.btn_m50x_play.setText("▶ Reproducir")
        else:
            self._m50x_player.play()
            self.btn_m50x_play.setText("⏸ Pausar")

    def _m50x_cambiar_fuente(self, indice: int):
        """Cambia entre pre-master / master / M50x, sin perder posición."""
        rutas = [self._m50x_path_premaster, self._m50x_path_master,
                  self._m50x_path_calibrado]
        if indice >= len(rutas) or not rutas[indice]:
            return
        sonando = self._m50x_player.playbackState() == QMediaPlayer.PlayingState
        pos = self._m50x_player.position()
        self._m50x_player.setSource(QUrl.fromLocalFile(str(rutas[indice])))
        self._m50x_player.setPosition(pos)
        if sonando:
            self._m50x_player.play()

    def _m50x_buscar_posicion(self, valor: int):
        """El usuario arrastró la barra de reproducción: salta a esa posición."""
        self._m50x_player.setPosition(valor)

    def _m50x_posicion_cambio(self, pos_ms: int):
        """Actualiza la barra y el tiempo mientras suena (sin pelear con el arrastre)."""
        if not self.slider_escucha.isSliderDown():
            self.slider_escucha.setValue(pos_ms)
        self.lbl_tiempo.setText(
            f"{self._m50x_fmt_tiempo(pos_ms)} / {self._m50x_fmt_tiempo(self._m50x_player.duration())}")

    def _m50x_duracion_cambio(self, dur_ms: int):
        """Ajusta el rango de la barra al largo del audio actual."""
        self.slider_escucha.setRange(0, dur_ms)

    @staticmethod
    def _m50x_fmt_tiempo(ms: int) -> str:
        s = max(0, ms // 1000)
        return f"{s // 60}:{s % 60:02d}"

    def _preguntar_aprobado(self, resumen: dict):
        """¿Master aprobado? Si sí, la app aprende tu preferencia de sonido.

        Antes avisa (no bloquea) si el score quedó por debajo de tu propio
        umbral histórico — tu piso real de calidad, no un número inventado.
        """
        genero = self.settings.genero_activo()
        pref = preferencias(genero)
        score = resumen.get("score") or {}
        umbral = pref.get("score_umbral")
        aviso = ""
        if umbral is not None and score.get("global") is not None and score["global"] < umbral:
            aviso = (f"\n\n⚠ Este master ({score['global']}%) quedó por debajo de tu "
                     f"estándar histórico (nunca aprobaste algo bajo {umbral}%).")
        r = QMessageBox.question(
            self, "¿Master aprobado?",
            "¿Te gusta este master?\n\nSi dices Sí, la app aprende tu preferencia "
            f"de loudness y crest (reversible en Settings → Olvidar lo aprendido).{aviso}",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if r == QMessageBox.Yes:
            try:
                n = registrar_aprobado(genero, resumen)
                self._status(f"✓ Aprendido — {n} master(s) aprobado(s)")
            except Exception:
                log.exception("No se pudo registrar el aprendizaje")

    def _master_error(self, msg: str):
        self._barra_activa(False)
        self._refrescar_estado()
        self._status("Masterizado fallido (ver app.log).")
        QMessageBox.critical(self, "Error", f"No se pudo masterizar:\n{msg}")

    def _voz_error(self, msg: str):
        self._barra_activa(False)
        self._refrescar_estado()
        self._status("Procesamiento de voz fallido (ver app.log).")
        QMessageBox.critical(self, "Error", f"No se pudo procesar la voz:\n{msg}")
