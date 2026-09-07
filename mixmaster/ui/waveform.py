"""Waveform display: forma de onda estéreo (L/R) con peaks resaltados.

Dibuja las muestras del audio en tiempo real, color azul (izquierda) y
verde (derecha) sobre fondo oscuro con grid temporal.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

_FONDO = QColor("#0f1c1e")
_GRID = QColor("#1f3b34")
_TEXTO = QColor("#7f9a9c")
_CH_L = QColor("#78b0ff")  # Azul para canal izquierdo
_CH_R = QColor("#43e08a")  # Verde para canal derecho
_PEAK = QColor("#e8a33d")  # Ámbar para peaks


class Waveform(QWidget):
    """Visualizador de forma de onda estéreo."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMinimumSize(600, 200)
        self.setAttribute(Qt.WA_StyledBackground, False)

        # Audio: shape (n_samples, 2) para L/R
        self._audio = np.array([])
        self._sr = 44100

    def actualizar_audio(self, audio: np.ndarray, sr: int = 44100) -> None:
        """Actualiza con datos de audio real (shape: (n_samples,) o (n_samples, 2))."""
        if audio.ndim == 1:
            audio = np.column_stack([audio, audio])  # Mono → estéreo
        self._audio = np.asarray(audio, dtype=np.float32)
        self._sr = sr
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        pad_l, pad_r = 60, 20
        pad_t, pad_b = 20, 40
        gw = w - pad_l - pad_r
        gh = h - pad_t - pad_b

        # Fondo
        p.fillRect(0, 0, w, h, _FONDO)

        if len(self._audio) == 0:
            p.setPen(_TEXTO)
            p.setFont(QFont("IBM Plex Mono", 10))
            p.drawText(w // 2 - 100, h // 2, 200, 20, Qt.AlignCenter, "Sin audio")
            p.end()
            return

        # Grid temporal: cada segundo
        duracion_s = len(self._audio) / self._sr
        n_marcas = max(2, int(duracion_s))
        p.setPen(QPen(_GRID, 0.5))
        p.setFont(QFont("IBM Plex Mono", 8))
        p.setPen(_TEXTO)

        for i in range(n_marcas + 1):
            tiempo = (duracion_s * i) / n_marcas if n_marcas > 0 else 0
            frac = i / (n_marcas + 1) if n_marcas > 0 else 0
            x = pad_l + frac * gw
            p.setPen(QPen(_GRID, 0.5))
            p.drawLine(int(x), pad_t, int(x), pad_t + gh))
            p.setPen(_TEXTO)
            p.drawText(int(x) - 20, pad_t + gh + 15, 40, 15, Qt.AlignCenter, f"{tiempo:.1f}s")

        # Línea central
        cy = pad_t + gh // 2
        p.setPen(QPen(_GRID, 0.5))
        p.drawLine(pad_l, int(cy), pad_l + gw, int(cy))

        # Dibujar waveform: submuestreo para que no sea tan denso
        n_pixels = gw
        step = max(1, len(self._audio) // n_pixels)

        # Canal L (azul)
        if self._audio.shape[1] >= 1:
            p.setPen(QPen(_CH_L, 1.2))
            for i in range(0, len(self._audio) - step, step):
                chunk = self._audio[i:i+step, 0]
                if len(chunk) == 0:
                    continue
                sample_normalized = np.mean(np.abs(chunk))

                x = pad_l + (i / len(self._audio)) * gw
                y_offset = sample_normalized * (gh // 2)

                y_top = cy - y_offset
                y_bottom = cy + y_offset

                p.drawLine(int(x), int(y_top), int(x), int(y_bottom))

        # Canal R (verde)
        if self._audio.shape[1] >= 2:
            p.setPen(QPen(_CH_R, 1.2))
            for i in range(0, len(self._audio) - step, step):
                chunk = self._audio[i:i+step, 1]
                if len(chunk) == 0:
                    continue
                sample_normalized = np.mean(np.abs(chunk))

                x = pad_l + (i / len(self._audio)) * gw
                y_offset = sample_normalized * (gh // 2)

                y_top = cy - y_offset
                y_bottom = cy + y_offset

                p.drawLine(int(x) + 1, int(y_top), int(x) + 1, int(y_bottom))

        # Peaks: buscar puntos donde |sample| > 0.95
        peaks_l = np.where(np.abs(self._audio[:, 0]) > 0.95)[0]
        if len(peaks_l) > 0:
            p.setPen(QPen(_PEAK, 2))
            for peak_idx in peaks_l[::max(1, len(peaks_l) // 20)]:  # Mostrar solo 20 peaks
                x = pad_l + (peak_idx / len(self._audio)) * gw
                p.drawPoint(int(x), int(cy) - 3)

        # Marco
        p.setPen(QPen(_GRID, 1))
        p.drawRect(pad_l, pad_t, gw, gh)

        p.end()
