"""Primitivas de hardware dibujadas con QPainter.

El resto de la app pinta rectángulos con borde de 1 px y por eso nunca se vio
como un equipo de rack: un panel real tiene volumen, y el volumen se dibuja
—no se declara en una hoja de estilo—. Acá viven las piezas reutilizables:
placa metálica, textura cepillada, bisel fresado, tornillo y LED con lente.

Todas reciben un QPainter ya configurado y pintan en coordenadas del widget,
para poder componerlas dentro de cualquier paintEvent.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush, QColor, QImage, QLinearGradient, QPainter, QPainterPath,
    QPen, QRadialGradient,
)

from . import tema

# La textura se genera una sola vez por (tamaño, intensidad) y se reutiliza:
# recalcular ruido en cada paintEvent haría que el panel "hierva" al repintar.
_CACHE_TEXTURA: dict[tuple[int, int, int], QImage] = {}


def textura_cepillada(w: int = 192, h: int = 192, intensidad: int = 11) -> QImage:
    """Aluminio cepillado: vetas horizontales finas, listas para usar de brush.

    Se construye con una componente por fila (la veta larga) más un grano fino,
    que es exactamente cómo se ve el metal lijado en una dirección. Semilla fija
    para que la textura no cambie entre repintados.
    """
    clave = (w, h, intensidad)
    if clave in _CACHE_TEXTURA:
        return _CACHE_TEXTURA[clave]

    rng = np.random.default_rng(7)
    veta = rng.normal(0.0, 1.0, (h, 1))        # cada fila, un brillo distinto
    grano = rng.normal(0.0, 0.42, (h, w))      # rugosidad dentro de la fila
    v = veta + grano

    alfa = np.clip(np.abs(v) * intensidad, 0, 255).astype(np.uint8)
    luz = np.where(v > 0, 235, 0).astype(np.uint8)   # blanco realza, negro hunde
    bgra = np.dstack([luz, luz, luz, alfa]).astype(np.uint8)

    img = QImage(bgra.tobytes(), w, h, QImage.Format_ARGB32).copy()
    _CACHE_TEXTURA[clave] = img
    return img


def dibujar_bisel(p: QPainter, rect: QRectF, radio: float = 8.0,
                  hundido: bool = False, fuerza: int = 70) -> None:
    """Canto fresado: una línea de luz y una de sombra, desplazadas 1 px.

    Es el truco que da relieve. `hundido=True` invierte la luz, de modo que el
    marco parezca una ranura mecanizada en vez de una placa sobrepuesta.
    """
    luz = QColor(255, 244, 222, fuerza)
    sombra = QColor(0, 0, 0, min(255, fuerza + 60))
    arriba, abajo = (sombra, luz) if not hundido else (luz, sombra)

    p.setBrush(Qt.NoBrush)
    p.setPen(QPen(abajo, 1))
    p.drawRoundedRect(rect.adjusted(0.5, 1.5, -0.5, -0.5), radio, radio)
    p.setPen(QPen(arriba, 1))
    p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -1.5), radio, radio)


def dibujar_placa(p: QPainter, rect: QRectF, radio: float = 10.0,
                  hundido: bool = False, borde: QColor | None = None) -> None:
    """Placa de chasis: degradado vertical + metal cepillado + canto fresado."""
    camino = QPainterPath()
    camino.addRoundedRect(rect, radio, radio)

    g = QLinearGradient(rect.left(), rect.top(), rect.left(), rect.bottom())
    if hundido:
        g.setColorAt(0.0, QColor(tema.CHASIS_BAJO))
        g.setColorAt(0.35, QColor(tema.CHASIS))
        g.setColorAt(1.0, QColor(tema.PANEL))
    else:
        g.setColorAt(0.0, QColor(tema.CHASIS_ALTO))
        g.setColorAt(0.55, QColor(tema.PANEL))
        g.setColorAt(1.0, QColor(tema.CHASIS_BAJO))
    p.fillPath(camino, QBrush(g))

    p.save()
    p.setClipPath(camino)
    p.fillRect(rect, QBrush(textura_cepillada()))
    p.restore()

    dibujar_bisel(p, rect, radio, hundido=hundido)
    if borde is not None:
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(borde, 1.4))
        p.drawRoundedRect(rect.adjusted(0.7, 0.7, -0.7, -0.7), radio, radio)


def dibujar_tornillo(p: QPainter, cx: float, cy: float, r: float = 5.0,
                     angulo: float = 35.0) -> None:
    """Tornillo de panel: sombra, cabeza abombada, avellanado y ranura."""
    p.save()
    p.setPen(Qt.NoPen)

    # sombra proyectada sobre la placa
    p.setBrush(QColor(0, 0, 0, 95))
    p.drawEllipse(QPointF(cx, cy + 1.2), r, r)

    # avellanado: el hueco donde se asienta la cabeza
    hueco = QRadialGradient(cx, cy + r * 0.3, r * 1.25)
    hueco.setColorAt(0.0, QColor(0, 0, 0, 120))
    hueco.setColorAt(1.0, QColor(120, 112, 96, 60))
    p.setBrush(QBrush(hueco))
    p.drawEllipse(QPointF(cx, cy), r * 1.18, r * 1.18)

    # cabeza metálica, luz desde arriba a la izquierda
    cabeza = QRadialGradient(cx - r * 0.38, cy - r * 0.42, r * 1.7)
    cabeza.setColorAt(0.0, QColor(214, 206, 188))
    cabeza.setColorAt(0.45, QColor(tema.METAL))
    cabeza.setColorAt(1.0, QColor(58, 53, 44))
    p.setBrush(QBrush(cabeza))
    p.drawEllipse(QPointF(cx, cy), r, r)

    # ranura: corte oscuro con un filo iluminado en el borde inferior
    p.translate(cx, cy)
    p.rotate(angulo)
    largo = r * 1.32
    p.setPen(QPen(QColor(24, 20, 15, 220), max(1.2, r * 0.30), Qt.SolidLine, Qt.RoundCap))
    p.drawLine(QPointF(-largo, 0), QPointF(largo, 0))
    p.setPen(QPen(QColor(235, 226, 205, 90), 0.8, Qt.SolidLine, Qt.RoundCap))
    p.drawLine(QPointF(-largo, r * 0.22), QPointF(largo, r * 0.22))
    p.restore()


def dibujar_led(p: QPainter, cx: float, cy: float, r: float,
                color: QColor, encendido: bool = True) -> None:
    """LED con lente: halo difuso, cuerpo abombado y reflejo especular."""
    p.save()
    p.setPen(Qt.NoPen)

    if encendido:
        halo = QRadialGradient(cx, cy, r * 3.4)
        c0 = QColor(color)
        c0.setAlpha(150)
        c1 = QColor(color)
        c1.setAlpha(0)
        halo.setColorAt(0.0, c0)
        halo.setColorAt(1.0, c1)
        p.setBrush(QBrush(halo))
        p.drawEllipse(QPointF(cx, cy), r * 3.4, r * 3.4)

    # engaste metálico
    p.setBrush(QColor(28, 24, 19))
    p.drawEllipse(QPointF(cx, cy), r * 1.45, r * 1.45)

    cuerpo = QRadialGradient(cx - r * 0.3, cy - r * 0.35, r * 1.9)
    if encendido:
        cuerpo.setColorAt(0.0, color.lighter(165))
        cuerpo.setColorAt(0.55, color)
        cuerpo.setColorAt(1.0, color.darker(220))
    else:
        base = QColor(color).darker(340)
        cuerpo.setColorAt(0.0, base.lighter(125))
        cuerpo.setColorAt(1.0, base)
    p.setBrush(QBrush(cuerpo))
    p.drawEllipse(QPointF(cx, cy), r, r)

    # reflejo de la lente
    p.setBrush(QColor(255, 255, 255, 130 if encendido else 60))
    p.drawEllipse(QPointF(cx - r * 0.32, cy - r * 0.38), r * 0.30, r * 0.22)
    p.restore()


def dibujar_ranura(p: QPainter, rect: QRectF, radio: float = 8.0) -> None:
    """Hueco fresado en el chasis (donde se aloja algo): oscuro y hundido."""
    camino = QPainterPath()
    camino.addRoundedRect(rect, radio, radio)
    g = QLinearGradient(rect.left(), rect.top(), rect.left(), rect.bottom())
    g.setColorAt(0.0, QColor(tema.SURCO))
    g.setColorAt(1.0, QColor(tema.CHASIS))
    p.fillPath(camino, QBrush(g))
    dibujar_bisel(p, rect, radio, hundido=True, fuerza=85)
