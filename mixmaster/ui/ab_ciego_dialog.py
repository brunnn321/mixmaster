"""A/B ciego (v0.9+): compara 2 masters sin saber cuál es cuál, para evitar
el sesgo de "el último que escuché me gustó más". Se revela al elegir
(ambos, no solo el elegido) y la decisión queda registrada en el proyecto.

Embebido como panel dentro de la app (no ventana aparte), estilo Ableton.
"""

import random
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from ..decisions import guardar_decision
from ..logger import get_logger

log = get_logger("mixmaster.ui.ab_ciego")


class PanelABCiego(QFrame):
    """Panel embebido: reproduce A/B a ciegas, revela y registra al elegir."""

    def __init__(self, proyecto, path1: Path, path2: Path, parent=None):
        super().__init__(parent)
        self.proyecto = proyecto
        self.setStyleSheet(
            "QFrame { border: 1px solid #5a6b8c; border-radius: 8px; padding: 4px; }")

        pares = [Path(path1), Path(path2)]
        random.shuffle(pares)
        self._rutas = {"A": pares[0], "B": pares[1]}
        self._revelado = False
        self._actual = "A"

        self._player = QMediaPlayer(self)
        self._audio_out = QAudioOutput(self)
        self._player.setAudioOutput(self._audio_out)
        self._fragmento_puesto = False
        self._player.durationChanged.connect(self._ir_a_fragmento)
        self._player.setSource(QUrl.fromLocalFile(str(self._rutas["A"])))

        lay = QVBoxLayout(self)
        titulo = QLabel("🙈 A/B ciego")
        titulo.setStyleSheet("border: none; font-weight: bold;")
        lay.addWidget(titulo)
        lay.addWidget(QLabel(
            "Empieza en un fragmento del tema (no desde el inicio) para comparar\n"
            "donde suele estar el groove. Elige A o B; recién ahí se revela cuál era."))

        fila = QHBoxLayout()
        self.btn_a = QPushButton("🔘 Escuchar A")
        self.btn_a.clicked.connect(lambda: self._cambiar("A"))
        self.btn_b = QPushButton("⚪ Escuchar B")
        self.btn_b.clicked.connect(lambda: self._cambiar("B"))
        self.btn_play = QPushButton("▶ Reproducir")
        self.btn_play.clicked.connect(self._toggle_play)
        fila.addWidget(self.btn_a)
        fila.addWidget(self.btn_b)
        fila.addWidget(self.btn_play)
        fila.addStretch()
        lay.addLayout(fila)

        self.lbl_resultado = QLabel("")
        self.lbl_resultado.setWordWrap(True)
        self.lbl_resultado.setStyleSheet("border: none; color: #7fd99a; font-weight: bold;")
        lay.addWidget(self.lbl_resultado)

        fila_elegir = QHBoxLayout()
        self.btn_elegir_a = QPushButton("Prefiero A")
        self.btn_elegir_a.clicked.connect(lambda: self._elegir("A"))
        self.btn_elegir_b = QPushButton("Prefiero B")
        self.btn_elegir_b.clicked.connect(lambda: self._elegir("B"))
        fila_elegir.addWidget(self.btn_elegir_a)
        fila_elegir.addWidget(self.btn_elegir_b)
        lay.addLayout(fila_elegir)

    def _ir_a_fragmento(self, dur_ms: int):
        """Al conocer la duración, salta a un fragmento representativo (una sola vez).

        ~2 min si el tema es largo; si es corto (short de 30 s), al 40 % del tema.
        """
        if self._fragmento_puesto or dur_ms <= 0:
            return
        self._fragmento_puesto = True
        objetivo = min(120_000, int(dur_ms * 0.40))
        self._player.setPosition(objetivo)

    def _cambiar(self, letra: str):
        if self._actual == letra:
            return
        sonando = self._player.playbackState() == QMediaPlayer.PlayingState
        pos = self._player.position()
        self._actual = letra
        self._player.setSource(QUrl.fromLocalFile(str(self._rutas[letra])))
        self._player.setPosition(pos)
        if sonando:
            self._player.play()

    def _toggle_play(self):
        if self._player.playbackState() == QMediaPlayer.PlayingState:
            self._player.pause()
            self.btn_play.setText("▶ Reproducir")
        else:
            self._player.play()
            self.btn_play.setText("⏸ Pausar")

    def _elegir(self, letra: str):
        if self._revelado:
            return
        self._revelado = True
        self.btn_elegir_a.setEnabled(False)
        self.btn_elegir_b.setEnabled(False)
        a_nombre, b_nombre = self._rutas["A"].name, self._rutas["B"].name
        self.lbl_resultado.setText(
            f"✓ Elegiste «{letra}»\n  A era: {a_nombre}\n  B era: {b_nombre}")
        try:
            guardar_decision(
                self.proyecto, "A/B", self.proyecto.nombre,
                f"A/B ciego: eligió {self._rutas[letra].name} sobre "
                f"{self._rutas['B' if letra == 'A' else 'A'].name}",
                "aprobado")
            log.info("A/B ciego registrado: preferencia %s", self._rutas[letra].name)
        except Exception:
            log.exception("No se pudo registrar la decisión del A/B ciego")
