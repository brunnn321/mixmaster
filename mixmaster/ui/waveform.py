"""Waveform display: forma de onda estéreo (L/R) con peaks resaltados.

Dibuja las muestras reales del master en dos carriles (L arriba, R abajo),
con envolvente min/max por columna de píxel — el mismo método que usan los
editores de audio, que conserva la forma real en vez de aplanarla.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from . import tema

_FONDO = QColor("#0c141b")
_GRID = QColor("#233648")
_EJE = QColor("#2c4053")
_TEXTO = QColor("#54687c")
_CH_L = QColor("#5fa8ff")   # azul — canal izquierdo
_CH_R = QColor("#39d98a")   # verde — canal derecho
_PEAK = QColor("#e8a33d")   # ámbar — muestras cerca de 0 dBFS

_UMBRAL_PEAK = 0.97  # |muestra| por encima de esto se marca como peak


class Waveform(QWidget):
    """Visualizador de forma de onda estéreo con envolvente real."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMinimumSize(320, 180)
        self.setAttribute(Qt.WA_StyledBackground, False)

        self._audio = np.zeros((0, 2), dtype=np.float32)
        self._sr = 44100

    def actualizar_audio(self, audio: np.ndarray, sr: int = 44100) -> None:
        """Carga audio real. Acepta (n,) mono o (n, 2) estéreo."""
        a = np.asarray(audio, dtype=np.float32)
        if a.ndim == 1:
            a = np.column_stack([a, a])
        elif a.ndim == 2 and a.shape[0] < a.shape[1]:
            a = a.T                      # venía como (2, n)
        if a.shape[1] == 1:
            a = np.column_stack([a[:, 0], a[:, 0]])
        self._audio = a[:, :2]
        self._sr = sr or 44100
        self.update()

    # ------------------------------------------------------------ pintura

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        pad_l, pad_r, pad_t, pad_b = 34, 12, 10, 22
        gw, gh = w - pad_l - pad_r, h - pad_t - pad_b

        p.fillRect(0, 0, w, h, _FONDO)
        if gw <= 4 or gh <= 8:
            p.end()
            return

        if len(self._audio) == 0:
            p.setPen(_TEXTO)
            p.setFont(QFont(tema.MONO, 9))
            p.drawText(0, h // 2 - 8, w, 16, Qt.AlignCenter, "SIN AUDIO")
            p.end()
            return

        # dos carriles: L arriba, R abajo, con un respiro entre ellos
        gap = 6
        lane_h = (gh - gap) / 2
        cy_l = pad_t + lane_h / 2
        cy_r = pad_t + lane_h + gap + lane_h / 2

        self._grid_tiempo(p, pad_l, pad_t, gw, gh, pad_b)
        self._dibujar_canal(p, 0, _CH_L, pad_l, gw, cy_l, lane_h / 2)
        self._dibujar_canal(p, 1, _CH_R, pad_l, gw, cy_r, lane_h / 2)

        # etiquetas de canal
        p.setFont(QFont(tema.MONO, 8))
        p.setPen(_CH_L)
        p.drawText(4, int(cy_l) - 7, pad_l - 8, 14, Qt.AlignVCenter | Qt.AlignRight, "L")
        p.setPen(_CH_R)
        p.drawText(4, int(cy_r) - 7, pad_l - 8, 14, Qt.AlignVCenter | Qt.AlignRight, "R")

        p.setPen(QPen(_EJE, 1))
        p.drawRect(pad_l, pad_t, gw, gh)
        p.end()

    def _grid_tiempo(self, p, pad_l, pad_t, gw, gh, pad_b):
        """Marcas verticales de tiempo, en pasos redondos (1/5/10/30 s...)."""
        dur = len(self._audio) / self._sr
        if dur <= 0:
            return
        for paso in (1, 2, 5, 10, 15, 30, 60, 120, 300):
            if dur / paso <= 8:
                break
        p.setFont(QFont(tema.MONO, 7))
        t = 0.0
        while t <= dur:
            x = pad_l + (t / dur) * gw
            p.setPen(QPen(_GRID, 1, Qt.DotLine))
            p.drawLine(int(x), pad_t, int(x), pad_t + gh)
            p.setPen(_TEXTO)
            p.drawText(int(x) - 22, pad_t + gh + 4, 44, 14,
                       Qt.AlignCenter, f"{int(t // 60)}:{int(t % 60):02d}")
            t += paso

    def _dibujar_canal(self, p, ch: int, color: QColor,
                       pad_l: int, gw: int, cy: float, semi: float):
        """Envolvente min/max por columna + marcas de peak."""
        datos = self._audio[:, ch]
        n = len(datos)
        cols = int(gw)
        # bordes de cada columna de píxel sobre la señal
        bordes = np.linspace(0, n, cols + 1, dtype=np.int64)

        # eje del carril
        p.setPen(QPen(_EJE, 1))
        p.drawLine(pad_l, int(cy), pad_l + int(gw), int(cy))

        p.setPen(QPen(color, 1))
        for i in range(cols):
            a, b = bordes[i], bordes[i + 1]
            if b <= a:
                continue
            bloque = datos[a:b]
            lo, hi = float(bloque.min()), float(bloque.max())
            y1 = cy - np.clip(hi, -1.0, 1.0) * semi
            y2 = cy - np.clip(lo, -1.0, 1.0) * semi
            x = pad_l + i
            if abs(y2 - y1) < 1:          # silencio: al menos un píxel visible
                y1, y2 = cy - 0.5, cy + 0.5
            p.drawLine(x, int(y1), x, int(y2))

            # peak en esta columna: se pinta encima, en ámbar
            if max(abs(lo), abs(hi)) >= _UMBRAL_PEAK:
                p.setPen(QPen(_PEAK, 1))
                p.drawLine(x, int(y1), x, int(y2))
                p.setPen(QPen(color, 1))
