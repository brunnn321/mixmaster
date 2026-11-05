"""Medidores en vivo del reproductor: dos VU con aguja (L/R) y analizador de
espectro (RTA) a 1/12 de octava, sincronizados con lo que está sonando.

No intercepta el audio de Qt: lee del mismo archivo, en la posición del
reproductor, un bloque corto 30 veces por segundo. Así funciona igual con WAV
y MP3 y no guarda el tema entero en memoria.
"""

import math
import time
from pathlib import Path

import numpy as np
import soundfile as sf
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import QWidget

from . import tema

BLOQUE = 8192
VU_REF_DBFS = -18.0          # 0 VU = −18 dBFS RMS (calibración habitual de estudio)
VU_MIN, VU_MAX = -20.0, 3.0
VU_TIEMPO_S = 0.3            # integración clásica del VU
RTA_MIN_DB, RTA_MAX_DB = -80.0, 0.0
RTA_CAIDA_DB_S = 24.0        # las barras bajan suave, suben al instante
CENTROS = [1000 * 2 ** (n / 12) for n in range(-68, 52)]   # 20 Hz … 20 kHz, 120 bandas de 1/12 oct


class MedidoresEnVivo(QWidget):
    """VU L/R + RTA de lo que reproduce `player`."""

    def __init__(self, player: QMediaPlayer, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(150)
        self._player = player
        self._archivo: sf.SoundFile | None = None
        self._vu = [VU_MIN, VU_MIN]
        self._pico = [0.0, 0.0]          # momento del último pico cerca de 0 dBFS
        self._rta = np.full(len(CENTROS), RTA_MIN_DB)
        self._t_prev = time.monotonic()
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)
        # el timer corre siempre y mira el estado del reproductor en cada tick: la
        # señal de cambio de estado no llegaba con el backend de Windows
        self._timer.start()

    def set_fuente(self, ruta: Path | None):
        """Abre el archivo que pasa a sonar (se llama en cada cambio de fuente)."""
        if self._archivo is not None:
            self._archivo.close()
            self._archivo = None
        if ruta:
            try:
                self._archivo = sf.SoundFile(str(ruta))
            except Exception:
                self._archivo = None

    def _bloque(self) -> np.ndarray | None:
        f = self._archivo
        if f is None:
            return None
        frame = int(self._player.position() / 1000 * f.samplerate)
        if frame >= f.frames:
            return None
        f.seek(max(frame - BLOQUE, 0))
        x = f.read(BLOQUE, dtype="float32", always_2d=True)
        if len(x) < 256:
            return None
        return x if x.shape[1] >= 2 else np.repeat(x, 2, axis=1)

    def _tick(self):
        if self._player.playbackState() != QMediaPlayer.PlayingState:
            if self._vu[0] > VU_MIN or self._rta.max() > RTA_MIN_DB:
                self._vu = [VU_MIN, VU_MIN]
                self._rta[:] = RTA_MIN_DB
                self.update()
            self._t_prev = time.monotonic()
            return
        ahora = time.monotonic()
        dt, self._t_prev = ahora - self._t_prev, ahora
        x = self._bloque()
        if x is None:
            return
        # VU: RMS por canal con la balística de 300 ms
        alfa = 1 - math.exp(-dt / VU_TIEMPO_S)
        for c in range(2):
            rms = float(np.sqrt(np.mean(x[:, c] ** 2)) + 1e-12)
            objetivo = min(max(20 * math.log10(rms) - VU_REF_DBFS, VU_MIN), VU_MAX)
            self._vu[c] += (objetivo - self._vu[c]) * alfa
            if float(np.abs(x[:, c]).max()) > 10 ** (-1 / 20):
                self._pico[c] = ahora
        # RTA: FFT con ventana de Hann sumada en bandas de 1/3 de octava
        mono = x.mean(axis=1)
        esp = np.abs(np.fft.rfft(mono * np.hanning(len(mono)))) ** 2
        freqs = np.fft.rfftfreq(len(mono), 1 / self._archivo.samplerate)
        norm = (np.hanning(len(mono)).sum() / 2) ** 2
        nuevo = np.empty(len(CENTROS))
        for i, fc in enumerate(CENTROS):
            sel = (freqs >= fc / 2 ** (1 / 24)) & (freqs < fc * 2 ** (1 / 24))
            energia = esp[sel].sum() if sel.any() else esp[np.argmin(np.abs(freqs - fc))]
            nuevo[i] = 10 * math.log10(energia / norm + 1e-12)
        nuevo = np.clip(nuevo, RTA_MIN_DB, RTA_MAX_DB)
        self._rta = np.maximum(nuevo, self._rta - RTA_CAIDA_DB_S * dt)
        self.update()

    # ------------------------------------------------------------------ dibujo

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        ancho_vu = min(190.0, (w - 24) / 4)
        for c in range(2):
            self._dibujar_vu(p, QRectF(8 + c * (ancho_vu + 8), 6, ancho_vu, h - 12),
                             self._vu[c], "L" if c == 0 else "R",
                             time.monotonic() - self._pico[c] < 0.4)
        x0 = 8 + 2 * (ancho_vu + 8) + 4
        self._dibujar_rta(p, QRectF(x0, 6, w - x0 - 8, h - 12))
        p.end()

    def _dibujar_vu(self, p: QPainter, r: QRectF, vu: float, canal: str, pico: bool):
        p.setPen(QPen(QColor(tema.METAL_DIM), 1))
        p.setBrush(QColor("#e9dfc0"))                 # cara crema
        p.drawRoundedRect(r, 6, 6)
        centro = QPointF(r.center().x(), r.bottom() - 10)
        radio = min(r.width() * 0.48, r.height() - 22)

        def angulo(v):   # −20 VU = −50°, +3 VU = +50°
            return math.radians(-50 + 100 * (v - VU_MIN) / (VU_MAX - VU_MIN))

        def punto(v, rr):
            a = angulo(v)
            return QPointF(centro.x() + rr * math.sin(a), centro.y() - rr * math.cos(a))

        p.setFont(QFont(tema.MONO, 7))
        for v in (-20, -10, -7, -5, -3, -2, -1, 0, 1, 2, 3):
            color = QColor(tema.ROJO) if v > 0 else QColor("#2a2520")
            p.setPen(QPen(color, 1.6 if v in (-20, -10, 0, 3) else 1))
            p.drawLine(punto(v, radio * 0.86), punto(v, radio))
            if v in (-20, -10, -5, 0, 3):
                t = punto(v, radio * 0.72)
                p.drawText(QRectF(t.x() - 12, t.y() - 6, 24, 12), Qt.AlignCenter, f"{v:+d}" if v else "0")
        p.setPen(QPen(QColor(tema.ROJO), 3))
        p.setBrush(Qt.NoBrush)
        arco = QRectF(centro.x() - radio, centro.y() - radio, 2 * radio, 2 * radio)
        a0 = 90 - math.degrees(angulo(0))
        p.drawArc(arco, int(a0 * 16), int(-(math.degrees(angulo(3)) - math.degrees(angulo(0))) * 16))
        # aguja
        p.setPen(QPen(QColor("#1b1815"), 2))
        p.drawLine(centro, punto(vu, radio * 0.98))
        p.setPen(QPen(QColor("#2a2520"), 1))
        p.setFont(QFont(tema.MONO, 8, QFont.Bold))
        p.drawText(QRectF(r.left() + 6, r.top() + 4, 30, 14), Qt.AlignLeft, f"VU {canal}")
        # LED de pico (−1 dBFS)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(tema.ROJO) if pico else QColor("#5a2a22"))
        p.drawEllipse(QPointF(r.right() - 12, r.top() + 11), 4, 4)

    def _dibujar_rta(self, p: QPainter, r: QRectF):
        p.setPen(QPen(QColor(tema.METAL_DIM), 1))
        p.setBrush(QColor(tema.VIDRIO))
        p.drawRoundedRect(r, 6, 6)
        zona = r.adjusted(8, 8, -8, -18)
        n = len(CENTROS)
        paso = zona.width() / n
        p.setPen(Qt.NoPen)
        for i, db in enumerate(self._rta):
            norm = (db - RTA_MIN_DB) / (RTA_MAX_DB - RTA_MIN_DB)
            alto = zona.height() * norm
            p.setBrush(tema.temperatura(norm))
            p.drawRect(QRectF(zona.left() + i * paso + 1, zona.bottom() - alto, paso - 2, alto))
        p.setPen(QColor(tema.INK_DIM))
        p.setFont(QFont(tema.MONO, 7))
        for fc, txt in ((31.5, "31"), (125, "125"), (500, "500"), (2000, "2k"), (8000, "8k"), (16000, "16k")):
            i = int(np.argmin([abs(c - fc) for c in CENTROS]))
            p.drawText(QRectF(zona.left() + i * paso - 10, zona.bottom() + 2, paso + 20, 12),
                       Qt.AlignCenter, txt)
