"""Goniómetro / vectorscopio (v0.9+): imagen estéreo en forma de nube de
puntos (Lissajous), como los medidores de sala de mastering.

Es una FOTO (snapshot) de la mezcla completa, no un medidor en vivo synced
al playback — honesto sobre esa limitación, pero el mismo dato que
importa: qué tan centrado/ancho está el estéreo. Embebido en PASO 2 (no
ventana aparte), vía construir_panel_goniometro().
"""

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ..audio_analysis import cargar_audio
from ..logger import get_logger

log = get_logger("mixmaster.ui.goniometro")

_MAX_PUNTOS = 6000


class _LienzoGoniometro(QWidget):
    """Dibuja la nube de puntos mid/side rotada 45° (estilo goniómetro clásico)."""

    def __init__(self, mid: np.ndarray, side: np.ndarray, parent=None):
        super().__init__(parent)
        self.mid, self.side = mid, side
        self.setMinimumSize(320, 320)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        radio = min(w, h) / 2 - 20

        # fondo + ejes
        p.fillRect(self.rect(), QColor("#12161f"))
        p.setPen(QPen(QColor("#333c50"), 1))
        p.drawLine(int(cx), 20, int(cx), int(h - 20))
        p.drawLine(20, int(cy), int(w - 20), int(cy))
        p.setPen(QPen(QColor("#5a6b8c"), 1, Qt.DashLine))
        p.drawEllipse(int(cx - radio), int(cy - radio), int(radio * 2), int(radio * 2))

        # nube de puntos (side = eje X, mid = eje Y invertido — mid arriba)
        p.setPen(QPen(QColor(110, 200, 140, 90), 1))
        for s, m in zip(self.side, self.mid):
            x = cx + s * radio
            y = cy - m * radio
            p.drawPoint(int(x), int(y))

        p.setPen(QColor("#8a97b0"))
        p.drawText(int(cx) - 10, 15, "M")
        p.drawText(int(w - 30), int(cy) + 4, "S")


def construir_panel_goniometro(path_audio) -> QWidget:
    """Widget listo para insertar (foto goniómetro + correlación) del audio dado."""
    panel = QWidget()
    lay = QVBoxLayout(panel)
    lay.setContentsMargins(0, 4, 0, 0)

    try:
        audio, sr = cargar_audio(path_audio)
    except Exception:
        log.exception("No se pudo cargar el audio para el goniómetro")
        lay.addWidget(QLabel("No se pudo cargar el audio."))
        return panel

    if audio.shape[1] < 2:
        lay.addWidget(QLabel("Audio mono: sin imagen estéreo que mostrar."))
        return panel

    paso = max(1, audio.shape[0] // _MAX_PUNTOS)
    muestra = audio[::paso]
    L, R = muestra[:, 0], muestra[:, 1]
    mid = (L + R) / np.sqrt(2)
    side = (L - R) / np.sqrt(2)
    pico = max(np.max(np.abs(mid)), np.max(np.abs(side)), 1e-9)
    mid, side = mid / pico, side / pico

    correlacion = float(np.corrcoef(L, R)[0, 1]) if len(L) > 1 else 1.0
    lbl_info = QLabel(
        f"Correlación L/R: {correlacion:.2f}  "
        f"({'buena compatibilidad mono' if correlacion > 0.5 else 'ancho o fuera de fase — revisar'})"
        "  · foto de toda la mezcla, no en vivo")
    lbl_info.setWordWrap(True)
    lbl_info.setStyleSheet("color: #cfe0ff; padding: 4px;")
    lay.addWidget(lbl_info)
    lay.addWidget(_LienzoGoniometro(mid, side))
    lay.addWidget(QLabel(
        "Nube vertical y estrecha = mono/centrado. Nube ancha horizontal = "
        "muy side o problema de fase. Círculo = referencia de ±1."))
    return panel
