"""Curvas A/B: tu master contra la referencia, banda por banda.

Dos curvas suaves (Catmull-Rom) sobre eje logarítmico de frecuencia, con el
área entre ambas rellena: ámbar donde te falta energía, azul donde te sobra.
La brecha se lee de un vistazo, sin tener que interpretar números.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from . import tema

_FONDO = QColor("#0c141b")
_GRID = QColor("#1d2d3c")
_EJE = QColor("#2c4053")
_TEXTO = QColor("#54687c")
_MASTER = QColor("#39d98a")   # verde — tu master
_REF = QColor("#8fa4bb")      # gris azulado — la referencia
_FALTA = QColor(232, 163, 61, 70)    # ámbar translúcido — te falta
_SOBRA = QColor(95, 168, 255, 70)    # azul translúcido — te sobra

# centro de cada banda en Hz, en orden ascendente
_BANDAS: tuple[tuple[str, str, float], ...] = (
    ("sub",      "SUB",  40.0),
    ("low",      "LOW",  100.0),
    ("low_mid",  "L-MID", 300.0),
    ("mid",      "MID",  1000.0),
    ("high_mid", "H-MID", 3000.0),
    ("high",     "HIGH", 8000.0),
    ("air",      "AIR",  14000.0),
)


class CurvasAB(QWidget):
    """Comparación master vs referencia por banda, como dos curvas."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMinimumSize(340, 190)
        self.setAttribute(Qt.WA_StyledBackground, False)

        self._master: list[float] = []
        self._ref: list[float] = []
        self._etiquetas: list[str] = []
        self._freqs: list[float] = []
        self._nombre_ref = ""

    def actualizar(self, bandas_master: dict, delta_db: dict,
                   nombre_ref: str = "") -> None:
        """Carga datos reales del diagnóstico.

        `bandas_master`: nivel por banda del master, en dB.
        `delta_db`: master - referencia por banda (lo que ya calcula el
        pipeline), de donde se reconstruye la curva de la referencia.
        """
        m, r, et, fr = [], [], [], []
        for clave, etiqueta, hz in _BANDAS:
            if clave not in bandas_master or clave not in delta_db:
                continue
            nivel = float(bandas_master[clave])
            m.append(nivel)
            r.append(nivel - float(delta_db[clave]))
            et.append(etiqueta)
            fr.append(hz)
        self._master, self._ref, self._etiquetas, self._freqs = m, r, et, fr
        self._nombre_ref = nombre_ref
        self.update()

    # ------------------------------------------------------------ pintura

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        pad_l, pad_r, pad_t, pad_b = 42, 14, 14, 26
        gw, gh = w - pad_l - pad_r, h - pad_t - pad_b

        p.fillRect(0, 0, w, h, _FONDO)
        if gw <= 8 or gh <= 8:
            p.end()
            return

        if len(self._master) < 2:
            p.setPen(_TEXTO)
            p.setFont(QFont(tema.MONO, 9))
            p.drawText(0, h // 2 - 8, w, 16, Qt.AlignCenter, "SIN REFERENCIA")
            p.end()
            return

        # escala vertical común a las dos curvas, con margen
        todos = self._master + self._ref
        lo, hi = min(todos), max(todos)
        margen = max(3.0, (hi - lo) * 0.15)
        lo, hi = lo - margen, hi + margen
        rango = hi - lo

        def y_de(db: float) -> float:
            return pad_t + gh - ((db - lo) / rango) * gh

        n = len(self._master)
        xs = [pad_l + (i / (n - 1)) * gw for i in range(n)]
        y_m = [y_de(v) for v in self._master]
        y_r = [y_de(v) for v in self._ref]

        self._grid(p, pad_l, pad_t, gw, gh, xs, lo, hi, y_de)

        path_m = _spline(xs, y_m)
        path_r = _spline(xs, y_r)

        # relleno entre curvas, partido por tramo según quién va arriba
        self._rellenar(p, path_m, path_r, xs, y_m, y_r)

        # referencia primero, master encima (es lo que importa leer)
        p.setPen(QPen(_REF, 1.6, Qt.DashLine))
        p.drawPath(path_r)
        p.setPen(QPen(_MASTER, 2.2))
        p.drawPath(path_m)

        # puntos del master
        p.setBrush(_MASTER)
        p.setPen(Qt.NoPen)
        for x, y in zip(xs, y_m):
            p.drawEllipse(QPointF(x, y), 2.6, 2.6)
        p.setBrush(Qt.NoBrush)

        # etiquetas de banda
        p.setFont(QFont(tema.MONO, 7))
        p.setPen(_TEXTO)
        for x, et in zip(xs, self._etiquetas):
            p.drawText(int(x) - 24, pad_t + gh + 5, 48, 14, Qt.AlignCenter, et)

        p.setPen(QPen(_EJE, 1))
        p.drawRect(pad_l, pad_t, gw, gh)
        p.end()

    def _grid(self, p, pad_l, pad_t, gw, gh, xs, lo, hi, y_de):
        """Líneas horizontales cada 6 dB + verticales por banda."""
        p.setFont(QFont(tema.MONO, 7))
        paso = 6.0
        db = np.ceil(lo / paso) * paso
        while db <= hi:
            y = y_de(db)
            p.setPen(QPen(_GRID, 1))
            p.drawLine(pad_l, int(y), pad_l + gw, int(y))
            p.setPen(_TEXTO)
            p.drawText(0, int(y) - 7, pad_l - 6, 14,
                       Qt.AlignVCenter | Qt.AlignRight, f"{db:+.0f}")
            db += paso
        p.setPen(QPen(_GRID, 1, Qt.DotLine))
        for x in xs:
            p.drawLine(int(x), pad_t, int(x), pad_t + gh)

    def _rellenar(self, p, path_m, path_r, xs, y_m, y_r):
        """Área entre curvas: ámbar si el master va por debajo, azul si arriba."""
        # el signo puede cambiar entre bandas, así que se rellena por tramo
        p.setPen(Qt.NoPen)
        for i in range(len(xs) - 1):
            x0, x1 = xs[i], xs[i + 1]
            recorte = QPainterPath()
            recorte.addRect(x0, 0, x1 - x0, self.height())

            tramo = QPainterPath(path_m)
            tramo.connectPath(_invertir(path_r))
            tramo.closeSubpath()

            # el master por debajo de la referencia = falta energía (y mayor)
            falta = (y_m[i] + y_m[i + 1]) > (y_r[i] + y_r[i + 1])
            p.setBrush(_FALTA if falta else _SOBRA)
            p.drawPath(tramo.intersected(recorte))
        p.setBrush(Qt.NoBrush)


def _spline(xs: list[float], ys: list[float]) -> QPainterPath:
    """Curva suave Catmull-Rom convertida a Bézier cúbica."""
    path = QPainterPath()
    if not xs:
        return path
    pts = [QPointF(x, y) for x, y in zip(xs, ys)]
    path.moveTo(pts[0])
    for i in range(len(pts) - 1):
        p0 = pts[i - 1] if i > 0 else pts[0]
        p1, p2 = pts[i], pts[i + 1]
        p3 = pts[i + 2] if i + 2 < len(pts) else pts[-1]
        c1 = QPointF(p1.x() + (p2.x() - p0.x()) / 6.0,
                     p1.y() + (p2.y() - p0.y()) / 6.0)
        c2 = QPointF(p2.x() - (p3.x() - p1.x()) / 6.0,
                     p2.y() - (p3.y() - p1.y()) / 6.0)
        path.cubicTo(c1, c2, p2)
    return path


def _invertir(path: QPainterPath) -> QPainterPath:
    """La misma curva recorrida al revés, para cerrar el área entre dos."""
    return path.toReversed()
