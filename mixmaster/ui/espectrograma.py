"""Espectrograma en tiempo real: 20Hz-20kHz con energía real de audio.

Dibuja un gráfico FFT colorizado (azul=bajo, rojo=alto) con escala logarítmica
de frecuencia, actualizado con datos reales del audio procesado.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

_FONDO = QColor("#0f1c1e")
_GRID = QColor("#1f3b34")
_TEXTO = QColor("#7f9a9c")
_TICK = QColor("#4a4227")


class Espectrograma(QWidget):
    """Gráfico espectral real: frecuencias vs. energía, con colores gradientes."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMinimumSize(600, 200)
        self.setAttribute(Qt.WA_StyledBackground, False)

        # Datos: frecuencias (Hz) y magnitudes (dB)
        self._freqs = np.array([])  # shape: (n_bins,)
        self._mags = np.array([])   # shape: (n_bins,), en dB
        self._mags_animadas = np.array([])

    def actualizar_espectro(self, freqs: np.ndarray, mags: np.ndarray) -> None:
        """Actualiza el espectrograma con datos reales (devueltos de espectro_suavizado)."""
        self._freqs = np.asarray(freqs)
        self._mags = np.asarray(mags)
        self._mags_animadas = self._mags.copy()
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        pad_l, pad_r = 60, 20
        pad_t, pad_b = 20, 50
        gw = w - pad_l - pad_r
        gh = h - pad_t - pad_b

        # Fondo
        p.fillRect(0, 0, w, h, _FONDO)

        if len(self._freqs) == 0 or len(self._mags) == 0:
            p.drawText(w // 2 - 100, h // 2, 200, 20, Qt.AlignCenter, "Sin datos")
            p.end()
            return

        # Grid de frecuencia (escala logarítmica 20Hz → 20kHz)
        freqs_marcas = [20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000]
        p.setPen(QPen(_GRID, 0.5))
        p.setFont(QFont(self.font()))
        p.setFont(QFont("IBM Plex Mono", 8))

        for f_marca in freqs_marcas:
            if f_marca < self._freqs.min() or f_marca > self._freqs.max():
                continue
            # Posición logarítmica
            frac_log = np.log2(f_marca / self._freqs.min()) / np.log2(
                self._freqs.max() / self._freqs.min()
            )
            x = pad_l + frac_log * gw
            p.drawLine(int(x), pad_t, int(x), pad_t + gh)
            # Etiqueta
            label = (
                f"{f_marca // 1000:.0f}k" if f_marca >= 1000
                else f"{f_marca}"
            )
            p.setPen(_TEXTO)
            p.drawText(int(x) - 15, pad_t + gh + 15, 30, 15, Qt.AlignCenter, label)
            p.setPen(QPen(_GRID, 0.5))

        # Espectro: barras coloreadas por energía
        n_bins = len(self._freqs)
        for i in range(n_bins - 1):
            f1, f2 = self._freqs[i], self._freqs[i + 1]
            mag = self._mags_animadas[i]

            # Posición logarítmica (20Hz-20kHz)
            frac1 = np.log2(f1 / self._freqs.min()) / np.log2(
                self._freqs.max() / self._freqs.min()
            )
            frac2 = np.log2(f2 / self._freqs.min()) / np.log2(
                self._freqs.max() / self._freqs.min()
            )
            x1 = pad_l + frac1 * gw
            x2 = pad_l + frac2 * gw

            # Altura por magnitud (dB): -80dB abajo, 0dB arriba
            mag_norm = np.clip((mag + 80) / 80, 0, 1)  # 0..1
            bar_h = mag_norm * gh

            # Color: frío (azul) → caliente (rojo) por energía
            color = self._color_for_magnitude(mag_norm)

            p.fillRect(int(x1), pad_t + gh - int(bar_h), int(x2 - x1), int(bar_h), color)

        # Marco
        p.setPen(QPen(_GRID, 1))
        p.drawRect(pad_l, pad_t, gw, gh)

        p.end()

    def _color_for_magnitude(self, norm: float) -> QColor:
        """Color gradiente: azul (bajo) → verde → amarillo → rojo (alto)."""
        if norm < 0.25:
            # Azul → verde
            r = 0
            g = int(norm * 4 * 255)
            b = 255
        elif norm < 0.5:
            # Verde → amarillo
            r = int((norm - 0.25) * 4 * 255)
            g = 255
            b = 0
        elif norm < 0.75:
            # Amarillo → naranja/rojo
            r = 255
            g = int(255 * (1 - (norm - 0.5) * 4))
            b = 0
        else:
            # Rojo brillante
            r = 255
            g = 0
            b = 0

        return QColor(int(r), int(g), int(b))
