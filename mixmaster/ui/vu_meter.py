"""Medidor de aguja VU física (rediseño "rack analógico", 2026-09-04).

Reemplaza el placeholder de barras de `_MedidorLED` en los sitios donde
tiene sentido un medidor real de estudio: fondo crema retroiluminado,
escala con ticks reales, aguja física con inercia (overshoot al asentar,
como un VU-metro de verdad — no un salto instantáneo).

Pintado 100% con QPainter (Qt no tiene box-shadow/textura como el mockup
HTML, pero SÍ puede dibujar esto con precisión). La aguja se anima con
`QPropertyAnimation` sobre la propiedad Qt `angulo`, con una curva
OutBack para el asentamiento con rebote leve, igual que un VU real.
"""

from __future__ import annotations

import math

from PySide6.QtCore import (
    Property, QEasingCurve, QPointF, QPropertyAnimation, QRectF, Qt,
)
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

_CREMA = QColor("#d6cba0")
_CREMA_BORDE = QColor("#8f8560")
_TICK = QColor("#4a4227")
_AGUJA = QColor("#2a2416")
_VERDE = QColor("#3a8f4f")
_ROJO = QColor("#e04b2e")


class VUMeter(QWidget):
    """Medidor de aguja física. `valor` en la escala real de `ticks`.

    `ticks`: lista de (fraccion 0..1, etiqueta) a lo largo del arco, ej.
        [(0.0,"4"), (0.25,"8"), (0.5,"11"), (0.75,"14"), (1.0,"18")]
    `frac_valor`: posición 0..1 de la aguja en esa misma escala (ya
        calculada por el caller con la fórmula real, ej. (crest-4)/(18-4)).
    `sano`: True/False/None — colorea el LED de estado (verde/rojo/apagado).
    """

    def __init__(self, titulo: str, ticks: list[tuple[float, str]],
                 frac_valor: float, sano: bool | None = None,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setMinimumSize(200, 130)
        self._titulo = titulo
        self._ticks = ticks
        self._sano = sano
        self._angulo = -90.0  # reposo, en grados (-90 izq .. +90 der)
        self.setAttribute(Qt.WA_StyledBackground, False)

        objetivo = -90.0 + max(0.0, min(1.0, frac_valor)) * 180.0
        self._anim = QPropertyAnimation(self, b"angulo", self)
        self._anim.setDuration(900)
        self._anim.setEasingCurve(QEasingCurve.OutBack)
        self._anim.setStartValue(-90.0)
        self._anim.setEndValue(objetivo)
        self._anim.start()

    def _get_angulo(self) -> float:
        return self._angulo

    def _set_angulo(self, v: float) -> None:
        self._angulo = v
        self.update()

    angulo = Property(float, _get_angulo, _set_angulo)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        pad = 6
        rect = QRectF(pad, pad, w - 2 * pad, h - 2 * pad)
        p.setPen(QPen(_CREMA_BORDE, 3))
        p.setBrush(_CREMA)
        p.drawRoundedRect(rect, 8, 8)

        cx = w / 2
        cy = h * 0.72
        r = min(w, h) * 0.42

        # arco de fondo
        p.setPen(QPen(_CREMA_BORDE, 2))
        p.setBrush(Qt.NoBrush)
        arc_rect = QRectF(cx - r - 8, cy - r - 8, 2 * (r + 8), 2 * (r + 8))
        p.drawArc(arc_rect, 0 * 16, 180 * 16)

        # ticks + etiquetas
        p.setPen(QPen(_TICK, 1.4))
        font = QFont(self.font())
        font.setPointSizeF(8)
        p.setFont(font)
        for frac, label in self._ticks:
            ang = math.radians(-90 + frac * 180)
            x1 = cx + math.sin(ang) * (r - 6)
            y1 = cy - math.cos(ang) * (r - 6)
            x2 = cx + math.sin(ang) * r
            y2 = cy - math.cos(ang) * r
            p.drawLine(QPointF(x1, y1), QPointF(x2, y2))
            lx = cx + math.sin(ang) * (r - 16)
            ly = cy - math.cos(ang) * (r - 16)
            p.drawText(QRectF(lx - 14, ly - 8, 28, 16), Qt.AlignCenter, label)

        # aguja (con inercia animada vía self._angulo)
        ang = math.radians(self._angulo)
        needle_len = r - 20
        nx = cx + math.sin(ang) * needle_len
        ny = cy - math.cos(ang) * needle_len
        pen_aguja = QPen(_AGUJA, 2.4)
        pen_aguja.setCapStyle(Qt.RoundCap)
        p.setPen(pen_aguja)
        p.drawLine(QPointF(cx, cy), QPointF(nx, ny))
        p.setPen(Qt.NoPen)
        p.setBrush(_AGUJA)
        p.drawEllipse(QPointF(cx, cy), 5, 5)

        # título
        font.setPointSizeF(9)
        font.setBold(True)
        p.setFont(font)
        p.setPen(QPen(_TICK))
        p.drawText(QRectF(pad, h - 24, w - 2 * pad, 18), Qt.AlignCenter, self._titulo)

        # LED de estado
        if self._sano is not None:
            p.setPen(Qt.NoPen)
            p.setBrush(_VERDE if self._sano else _ROJO)
            p.drawEllipse(QPointF(w - pad - 10, pad + 10), 5, 5)

        p.end()
