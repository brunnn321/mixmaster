"""Tempo Genius: pone los stems de Moises a tempo fijo y entrega un click exacto.

Llama a tempo/stems_fix.py como proceso aparte: el módulo de tempo no depende de MixMaster.
Al terminar se escucha la mezcla con el click; si el "1" quedó corrido, se mueve un tiempo
y se vuelve a procesar.
"""

import json
import re
import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf
from PySide6.QtCore import QProcess, QProcessEnvironment, Qt, QUrl
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QDialog, QDoubleSpinBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QPlainTextEdit, QPushButton, QVBoxLayout,
)

from ..logger import get_logger

log = get_logger("mixmaster.ui.tempo")

SCRIPT = Path(__file__).resolve().parents[2] / "tempo" / "stems_fix.py"
RE_BPM = re.compile(r"(\d+(?:\.\d+)?)bpm")
RE_TEMA = re.compile(r"^(.*)-[A-G][b#]? (major|minor)-")
ESCUCHA = Path(tempfile.gettempdir()) / "mixmaster_tempo_escucha.wav"


class TempoDialog(QDialog):
    """Carpeta de stems de Moises → PROCESAR → escuchar con el click → mover el "1" si hace falta."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("⏱ Tempo Genius")
        self.resize(680, 600)
        self.setAcceptDrops(True)
        self._proc = None
        self._fase = None
        self._salida = None

        self._player = QMediaPlayer(self)
        self._audio_out = QAudioOutput(self)
        self._player.setAudioOutput(self._audio_out)

        lay = QVBoxLayout(self)

        fila_carpeta = QHBoxLayout()
        self.txt_carpeta = QLineEdit()
        self.txt_carpeta.setReadOnly(True)
        self.txt_carpeta.setPlaceholderText("Carpeta de stems de Moises (con metrónomo)")
        btn_carpeta = QPushButton("📁 Elegir carpeta…")
        btn_carpeta.clicked.connect(self._elegir_carpeta)
        fila_carpeta.addWidget(self.txt_carpeta, 1)
        fila_carpeta.addWidget(btn_carpeta)
        lay.addLayout(fila_carpeta)

        fila_bpm = QHBoxLayout()
        fila_bpm.addWidget(QLabel("BPM:"))
        self.spin_bpm = QDoubleSpinBox()
        self.spin_bpm.setRange(30, 300)
        self.spin_bpm.setDecimals(2)
        self.spin_bpm.setValue(120)
        fila_bpm.addWidget(self.spin_bpm)
        self.lbl_salida = QLabel("")
        self.lbl_salida.setStyleSheet("color: #8a9bb5;")
        fila_bpm.addWidget(self.lbl_salida, 1)
        lay.addLayout(fila_bpm)

        self.btn_procesar = QPushButton("PONER A TEMPO")
        self.btn_procesar.setCursor(Qt.PointingHandCursor)
        self.btn_procesar.setMinimumHeight(48)
        self.btn_procesar.setStyleSheet(
            "QPushButton { font-weight: 800; font-size: 16px; letter-spacing: 2px; color: white;"
            " border-radius: 10px; border: 1px solid #4fa76a;"
            " background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #4aa06a, stop:1 #2c6b46); }"
            " QPushButton:hover { background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #55b478, stop:1 #337a50); }"
            " QPushButton:pressed { background: #2a5f3e; }"
            " QPushButton:disabled { background: #2a3b31; color: #6f8579; border-color: #33463b; }")
        self.btn_procesar.clicked.connect(lambda: self._procesar())
        lay.addWidget(self.btn_procesar)

        self.txt_log = QPlainTextEdit()
        self.txt_log.setReadOnly(True)
        lay.addWidget(self.txt_log, 1)

        self.lbl_resumen = QLabel("")
        self.lbl_resumen.setWordWrap(True)
        self.lbl_resumen.setStyleSheet("color: #7fd99a; font-weight: bold;")
        lay.addWidget(self.lbl_resumen)

        fila_escucha = QHBoxLayout()
        self.btn_play = QPushButton("▶ Escuchar con click")
        self.btn_play.clicked.connect(self._toggle_play)
        self.btn_antes = QPushButton("◀ El 1 un tiempo antes")
        self.btn_antes.clicked.connect(lambda: self._mover_uno(-1))
        self.btn_despues = QPushButton("El 1 un tiempo después ▶")
        self.btn_despues.clicked.connect(lambda: self._mover_uno(+1))
        self.btn_abrir = QPushButton("📂 Abrir carpeta")
        self.btn_abrir.clicked.connect(self._abrir_salida)
        for b in (self.btn_play, self.btn_antes, self.btn_despues, self.btn_abrir):
            b.setEnabled(False)
            fila_escucha.addWidget(b)
        lay.addLayout(fila_escucha)

    # ---------- entrada ----------

    def _elegir_carpeta(self):
        carpeta = QFileDialog.getExistingDirectory(self, "Carpeta de stems de Moises")
        if carpeta:
            self._usar_carpeta(Path(carpeta))

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and any(Path(u.toLocalFile()).is_dir()
                                              for u in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        for u in event.mimeData().urls():
            if Path(u.toLocalFile()).is_dir():
                self._usar_carpeta(Path(u.toLocalFile()))
                break

    def _usar_carpeta(self, carpeta: Path):
        self.txt_carpeta.setText(str(carpeta))
        m = RE_BPM.search(carpeta.name)
        if m:
            self.spin_bpm.setValue(float(m.group(1)))
        self._fase = None
        self.lbl_salida.setText(f"→ {self._carpeta_salida()}")

    def _carpeta_salida(self) -> Path:
        carpeta = Path(self.txt_carpeta.text())
        m = RE_TEMA.match(carpeta.name)
        tema = m.group(1).strip() if m else carpeta.name
        return carpeta.parent / "A TEMPO" / f"{tema} - {self.spin_bpm.value():g} BPM"

    # ---------- proceso ----------

    def _procesar(self, fase=None):
        if not self.txt_carpeta.text():
            self.lbl_resumen.setText("Elige primero la carpeta de stems.")
            return
        self._soltar_audio()
        self._salida = self._carpeta_salida()
        args = ["-u", str(SCRIPT), self.txt_carpeta.text(), str(self._salida), f"{self.spin_bpm.value():g}"]
        if fase is not None:
            args.append(f"--fase={fase}")
        self.txt_log.clear()
        self.lbl_resumen.setText("Procesando…")
        for b in (self.btn_procesar, self.btn_play, self.btn_antes, self.btn_despues, self.btn_abrir):
            b.setEnabled(False)

        self._proc = QProcess(self)
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONIOENCODING", "utf-8")
        self._proc.setProcessEnvironment(env)
        self._proc.setProcessChannelMode(QProcess.MergedChannels)
        self._proc.readyReadStandardOutput.connect(self._leer_salida)
        self._proc.finished.connect(self._terminado)
        self._proc.start(sys.executable, args)

    def _leer_salida(self):
        texto = bytes(self._proc.readAllStandardOutput()).decode("utf-8", errors="replace")
        self.txt_log.appendPlainText(texto.rstrip())

    def _terminado(self, codigo, _estado):
        self.btn_procesar.setEnabled(True)
        if codigo != 0:
            self.lbl_resumen.setText("Falló: el detalle está arriba.")
            return
        try:
            info = json.loads((self._salida / "log.json").read_text(encoding="utf-8"))
        except Exception:
            log.exception("No se pudo leer log.json")
            self.lbl_resumen.setText("Terminó, pero no se pudo leer log.json.")
            return
        self._fase = info["downbeat_fase"]
        secs = [abs(v) for v in info.get("verificacion_secciones_32_ms", []) if v is not None]
        partes = [f"Modo {info['modo']}", f"ajuste {info['bpm_ajuste']} BPM",
                  f"peor sección {max(secs):.1f} ms" if secs else "sin secciones con batería"]
        if info.get("final_libre"):
            partes.append(f"final libre desde {info['tramo_a_tempo']['hasta_s']:.0f} s")
        self.lbl_resumen.setText(" · ".join(partes) + "\nEscucha el comienzo: el tono agudo del click debe caer en el 1.")
        self._preparar_escucha()
        self.btn_abrir.setEnabled(True)

    # ---------- escucha ----------

    def _preparar_escucha(self):
        """Mezcla y click en un solo archivo, para que no se desfasen al reproducir."""
        try:
            mezcla_p = next(self._salida.glob("* - MEZCLA.flac"))
            click_p = next(self._salida.glob("* - CLICK.flac"))
            mezcla, sr = sf.read(str(mezcla_p), dtype="float32", always_2d=True)
            click, _ = sf.read(str(click_p), dtype="float32", always_2d=True)
            n = min(len(mezcla), len(click))
            escucha = np.clip(mezcla[:n] * 0.7 + click[:n, :mezcla.shape[1]] * 0.6, -1, 1)
            sf.write(str(ESCUCHA), escucha, sr, subtype="PCM_16")
        except Exception:
            log.exception("No se pudo preparar la escucha")
            self.lbl_resumen.setText(self.lbl_resumen.text() + "\nNo se pudo preparar la escucha.")
            return
        self._player.setSource(QUrl.fromLocalFile(str(ESCUCHA)))
        for b in (self.btn_play, self.btn_antes, self.btn_despues):
            b.setEnabled(True)

    def _toggle_play(self):
        if self._player.playbackState() == QMediaPlayer.PlayingState:
            self._player.pause()
            self.btn_play.setText("▶ Escuchar con click")
        else:
            self._player.play()
            self.btn_play.setText("⏸ Pausar")

    def _mover_uno(self, delta: int):
        if self._fase is not None:
            self._procesar(fase=(self._fase + delta) % 4)

    def _soltar_audio(self):
        """Libera el archivo de escucha (en Windows queda bloqueado mientras se reproduce)."""
        self._player.stop()
        self._player.setSource(QUrl())
        self.btn_play.setText("▶ Escuchar con click")

    def _abrir_salida(self):
        try:
            from .abrir import mostrar_en_carpeta
            mostrar_en_carpeta(next(self._salida.glob("*.flac")))
        except Exception:
            log.exception("No se pudo abrir la carpeta de salida")

    def closeEvent(self, event):
        if self._proc and self._proc.state() != QProcess.NotRunning:
            self._proc.kill()
            self._proc.waitForFinished(2000)
        self._soltar_audio()
        super().closeEvent(event)
