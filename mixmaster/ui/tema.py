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


# ---- QSS de app completa (rediseño "rack analógico", 2026-09-04) ----------
# Se aplica a nivel QApplication (no solo MainWindow) para que TODOS los
# diálogos existentes (Historial, Notas, Null test, A/B ciego, Convertidor,
# Settings, asistente de primera ejecución, etc.) hereden el mismo lenguaje
# visual automáticamente, sin tocar el código de cada diálogo uno por uno.
# Reemplaza el chasis oscuro genérico (negro + un solo verde) por el look de
# unidad de rack analógica (chasis cálido + acento ámbar/tungsteno) acordado
# con Bruno tras rechazar las direcciones anteriores por "genéricas".
QSS_APP = f"""
QMainWindow, QDialog {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #2c4a52, stop:0.45 #1c333a, stop:1 #142027);
}}
QWidget {{ color: {INK}; }}
QMenuBar {{
    background: #0f1c1e; color: {INK};
    border-bottom: 1px solid #2c4048;
}}
QMenuBar::item {{ background: transparent; padding: 6px 10px; }}
QMenuBar::item:selected {{ background: {AMBAR}; color: #1c2a2c; }}
QMenu {{ background: #101c1f; color: {INK}; border: 1px solid #2c4048; }}
QMenu::item {{ padding: 6px 20px; }}
QMenu::item:selected {{ background: {AMBAR}; color: #1c2a2c; }}
QPushButton {{
    background: #1a262b; color: {INK}; border: 1px solid #2c4048;
    border-radius: 5px; padding: 7px 14px;
}}
QPushButton:hover {{ border-color: {AMBAR}; }}
QPushButton:pressed {{ background: #12191d; }}
QPushButton:disabled {{ color: {INK_DIM}; border-color: #223229; }}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit, QPlainTextEdit,
QListWidget, QTreeWidget, QTableWidget {{
    background: #0f1c1e; color: {INK}; border: 1px solid #2c4048;
    border-radius: 4px; padding: 4px; selection-background-color: {AMBAR};
    selection-color: #1c2a2c;
}}
QTabWidget::pane {{ border: 1px solid #2c4048; background: #101c1f; }}
QTabBar::tab {{
    background: #1a262b; color: {INK_DIM}; padding: 8px 16px;
    border: 1px solid #2c4048; border-bottom: none;
}}
QTabBar::tab:selected {{ background: {AMBAR}; color: #1c2a2c; }}
QProgressBar {{
    background: #0f1c1e; border: 1px solid #2c4048; border-radius: 4px;
    text-align: center; color: {INK};
}}
QProgressBar::chunk {{ background: {AMBAR}; }}
QScrollBar:vertical {{ background: #101c1f; width: 12px; margin: 0; }}
QScrollBar::handle:vertical {{ background: #2c4048; border-radius: 5px; min-height: 24px; }}
QScrollBar:horizontal {{ background: #101c1f; height: 12px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: #2c4048; border-radius: 5px; min-width: 24px; }}
QGroupBox {{
    border: 1px solid #2c4048; border-radius: 6px; margin-top: 12px;
    color: {AMBAR}; padding-top: 10px;
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 8px; padding: 0 4px; }}
QCheckBox, QRadioButton {{ color: {INK}; }}
QLabel {{ color: {INK}; }}
QToolTip {{
    background: #101c1f; color: {INK}; border: 1px solid {AMBAR};
    padding: 4px;
}}
"""
