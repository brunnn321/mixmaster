"""Lenguaje visual único de MixMaster — rack analógico ámbar (outboard gear).

Un solo lugar con los colores, para que cualquier widget use exactamente lo
mismo. Sin esto cada widget queda como isla suelta.

Dirección visual (elegida sobre los mockups, opción A "rack analógico"):
chasis metálico negro cálido, paneles con serigrafía crema, acento ámbar de
lámpara de tungsteno, rojo sólo para el límite. Nada de azul frío: el azul
genérico era justo lo que hacía que la app se viera como cualquier otra.

Las pantallas (espectro, waveform, curvas) van sobre vidrio ahumado cálido y
pintan en escala de temperatura — ámbar/crema — no en arcoíris azul-rojo.
"""

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGraphicsDropShadowEffect

# ---- paleta: chasis --------------------------------------------------------
CHASIS = "#1b1815"         # negro cálido — cuerpo de la unidad
CHASIS_ALTO = "#2a251e"    # ceja superior del chasis (luz cenital)
CHASIS_BAJO = "#141110"    # base del chasis (sombra)
PANEL = "#232019"          # panel frontal, un punto más claro que el chasis
VIDRIO = "#12100c"         # fondo de pantalla: vidrio ahumado cálido
SURCO = "#0d0b09"          # hendiduras / separaciones fresadas

# ---- paleta: metal y serigrafía -------------------------------------------
METAL = "#8a8478"          # aluminio cepillado — bordes, tornillos
METAL_DIM = "#4a4438"      # metal en sombra — líneas de grid, marcos
CREMA = "#dcd3ad"          # serigrafía de panel (etiquetas impresas)
INK = "#ede6d9"            # texto principal
INK_DIM = "#9a9184"        # texto secundario

# ---- paleta: acentos (lámparas) -------------------------------------------
AMBAR = "#e8a33d"          # acento principal — tungsteno encendido
AMBAR_CLARO = "#f5c46b"    # ámbar al máximo (pico de energía)
AMBAR_GLOW = QColor(232, 163, 61, 180)
VERDE = "#8fb865"          # LED verde vintage — "en objetivo", oliva, no neón
VERDE_GLOW = QColor(143, 184, 101, 170)
ROJO = "#d64933"           # al límite / clipping
AZUL = "#8a8478"           # compat: "antes/original" ahora es metal, no azul

MONO = "Consolas"          # valores numéricos ("display digital")

# ---- panel (chasis) --------------------------------------------------------
PANEL_QSS = (
    f"background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
    f" stop:0 {PANEL}, stop:1 {CHASIS_BAJO}); border:1px solid {METAL_DIM};"
    f" border-radius:10px;"
)

# ---- pantallas -------------------------------------------------------------
PANTALLA_QSS = (
    f"background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
    f" stop:0 {VIDRIO}, stop:1 #1a1611); border:1px solid {METAL_DIM};"
    f" border-radius:8px;"
)


def glow(widget, color: QColor = AMBAR_GLOW, radio: int = 14):
    """Halo (drop-shadow sin desplazamiento): todo lo encendido brilla igual."""
    ef = QGraphicsDropShadowEffect(widget)
    ef.setBlurRadius(radio)
    ef.setColor(color)
    ef.setOffset(0, 0)
    widget.setGraphicsEffect(ef)
    return widget


def color_glow(hex_color: str, alpha: int = 180) -> QColor:
    """QColor con alpha para glow, a partir de un hex de la paleta."""
    c = QColor(hex_color)
    c.setAlpha(alpha)
    return c


def temperatura(norm: float) -> QColor:
    """Energía 0..1 → color de temperatura, como un filamento al calentarse.

    Reemplaza el degradado azul→verde→rojo (arcoíris genérico de librería) por
    la rampa real de un cuerpo incandescente: marrón apagado, rojo, ámbar,
    amarillo, blanco crema. Es lo que da el aspecto de instrumento con lámpara.
    """
    n = 0.0 if norm < 0 else (1.0 if norm > 1 else float(norm))
    paradas = (
        (0.00, (36, 28, 22)),      # apagado, apenas visible sobre el vidrio
        (0.25, (122, 48, 26)),     # rojo profundo
        (0.50, (208, 106, 38)),    # naranja
        (0.72, (232, 163, 61)),    # ámbar (el acento)
        (0.88, (245, 196, 107)),   # amarillo cálido
        (1.00, (247, 232, 200)),   # crema incandescente
    )
    for i in range(len(paradas) - 1):
        t0, c0 = paradas[i]
        t1, c1 = paradas[i + 1]
        if n <= t1:
            f = 0.0 if t1 == t0 else (n - t0) / (t1 - t0)
            return QColor(*[int(a + (b - a) * f) for a, b in zip(c0, c1)])
    return QColor(*paradas[-1][1])


# ---- QSS de app completa ---------------------------------------------------
# Se aplica a nivel QApplication (no sólo MainWindow) para que TODOS los
# diálogos existentes (Historial, Notas, Null test, A/B ciego, Convertidor,
# Settings, asistente de primera ejecución…) hereden el mismo lenguaje visual
# sin tocar el código de cada uno.
QSS_APP = f"""
QMainWindow, QDialog {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {CHASIS_ALTO}, stop:0.45 {CHASIS}, stop:1 {CHASIS_BAJO});
}}
QWidget {{ color: {INK}; }}
QMenuBar {{
    background: {CHASIS_BAJO}; color: {CREMA};
    border-bottom: 1px solid {METAL_DIM};
}}
QMenuBar::item {{ background: transparent; padding: 6px 10px; }}
QMenuBar::item:selected {{ background: {AMBAR}; color: {CHASIS}; }}
QMenu {{ background: {PANEL}; color: {INK}; border: 1px solid {METAL_DIM}; }}
QMenu::item {{ padding: 6px 20px; }}
QMenu::item:selected {{ background: {AMBAR}; color: {CHASIS}; }}
QPushButton {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #322c23, stop:1 #201c16);
    color: {CREMA}; border: 1px solid {METAL_DIM};
    border-radius: 4px; padding: 7px 14px;
    font-family: {MONO}; letter-spacing: 1px;
}}
QPushButton:hover {{ border-color: {AMBAR}; color: {AMBAR_CLARO}; }}
QPushButton:pressed {{
    background: {SURCO}; border-color: {AMBAR};
}}
QPushButton:disabled {{ color: #5c564b; border-color: #2e2921; }}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit, QPlainTextEdit,
QListWidget, QTreeWidget, QTableWidget {{
    background: {VIDRIO}; color: {INK}; border: 1px solid {METAL_DIM};
    border-radius: 3px; padding: 4px; selection-background-color: {AMBAR};
    selection-color: {CHASIS};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QTextEdit:focus, QPlainTextEdit:focus {{ border-color: {AMBAR}; }}
QTabWidget::pane {{ border: 1px solid {METAL_DIM}; background: {PANEL}; }}
QTabBar::tab {{
    background: #2a251e; color: {INK_DIM}; padding: 8px 16px;
    border: 1px solid {METAL_DIM}; border-bottom: none;
    font-family: {MONO}; letter-spacing: 1px;
}}
QTabBar::tab:selected {{ background: {AMBAR}; color: {CHASIS}; }}
QTabBar::tab:hover:!selected {{ color: {CREMA}; }}
QProgressBar {{
    background: {SURCO}; border: 1px solid {METAL_DIM}; border-radius: 3px;
    text-align: center; color: {CREMA}; font-family: {MONO};
}}
QProgressBar::chunk {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #c07a2a, stop:1 {AMBAR_CLARO});
}}
QScrollBar:vertical {{ background: {SURCO}; width: 12px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {METAL_DIM}; border-radius: 5px; min-height: 24px; }}
QScrollBar::handle:vertical:hover {{ background: {METAL}; }}
QScrollBar:horizontal {{ background: {SURCO}; height: 12px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: {METAL_DIM}; border-radius: 5px; min-width: 24px; }}
QScrollBar::handle:horizontal:hover {{ background: {METAL}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QGroupBox {{
    border: 1px solid {METAL_DIM}; border-radius: 5px; margin-top: 12px;
    color: {CREMA}; padding-top: 10px;
    font-family: {MONO}; letter-spacing: 2px;
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 8px; padding: 0 4px; }}
QCheckBox, QRadioButton {{ color: {INK}; }}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 13px; height: 13px;
    background: {SURCO}; border: 1px solid {METAL_DIM};
}}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background: {AMBAR}; border-color: {AMBAR_CLARO};
}}
QRadioButton::indicator {{ border-radius: 7px; }}
QLabel {{ color: {INK}; }}
QToolTip {{
    background: {PANEL}; color: {CREMA}; border: 1px solid {AMBAR};
    padding: 4px; font-family: {MONO};
}}
QSlider::groove:horizontal {{
    background: {SURCO}; height: 4px; border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {METAL}, stop:1 #5c5648);
    border: 1px solid {CHASIS_BAJO}; width: 12px;
    margin: -6px 0; border-radius: 3px;
}}
QSlider::handle:horizontal:hover {{ background: {AMBAR}; }}
QSlider::sub-page:horizontal {{ background: {AMBAR}; border-radius: 2px; }}
"""
