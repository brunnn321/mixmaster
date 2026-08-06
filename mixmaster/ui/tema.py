"""Lenguaje visual único de MixMaster (Paso 1 del rediseño, veredicto de El
Consejo 2026-08-05): un solo lugar con los colores y el efecto de glow, para
que cualquier widget nuevo — o reescrito — use exactamente lo mismo.

Sin esto, cada widget queda como isla suelta (fue el problema original:
2 verdes distintos para lo que debería ser el mismo acento). Con esto, el
"lenguaje" es: fondo tipo chasis oscuro con gradiente sutil, acento fósforo
verde con glow, ámbar/rojo para advertencia, tipografía monoespaciada para
valores numéricos (efecto "display digital").

Estos valores YA estaban en `graficas.py` (comentario "mockup aprobado" —
el panel de resultados post-master ya seguía este lenguaje). Se promueven
acá para que el resto de la UI (botones, medidores, controles) los reuse en
vez de tener su propia paleta hardcodeada.
"""

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGraphicsDropShadowEffect

# ---- paleta ---------------------------------------------------------------
VERDE = "#43e08a"          # acento principal — éxito, LED encendido, "en objetivo"
VERDE_GLOW = QColor(67, 224, 138, 180)
AZUL = "#78b0ff"           # referencia/comparación ("antes", "original")
AMBAR = "#f0b447"          # advertencia leve
ROJO = "#f2593a"           # advertencia fuerte / al límite
INK = "#cddbe8"            # texto principal sobre fondo oscuro
INK_DIM = "#8598ab"        # texto secundario/atenuado
MONO = "Consolas"          # tipografía de valores numéricos ("display digital")

# ---- panel (chasis) --------------------------------------------------------
PANEL_QSS = (
    "background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
    " stop:0 #0c141b, stop:1 #16222d); border:1px solid #33495b;"
    " border-radius:10px;"
)


def glow(widget, color: QColor = VERDE_GLOW, radio: int = 14):
    """Aplica un halo (drop-shadow sin desplazamiento) — el "control" del
    lenguaje visual: todo lo que está activo/encendido brilla así, siempre
    con la misma función, nunca un efecto distinto por widget."""
    ef = QGraphicsDropShadowEffect(widget)
    ef.setBlurRadius(radio)
    ef.setColor(color)
    ef.setOffset(0, 0)
    widget.setGraphicsEffect(ef)
    return widget


def color_glow(hex_color: str, alpha: int = 180) -> QColor:
    """QColor con alpha para glow, a partir de un hex de la paleta (ej. AMBAR)."""
    c = QColor(hex_color)
    c.setAlpha(alpha)
    return c
