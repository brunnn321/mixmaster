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

from pathlib import Path

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGraphicsDropShadowEffect

# Imágenes de los botones (generadas por Bruno, recortadas de una sola hoja)
_BOTONES = (Path(__file__).resolve().parents[2] / "assets" / "botones").as_posix()
_FONDOS = (Path(__file__).resolve().parents[2] / "assets" / "fondos").as_posix()

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
QDialog {{
    border-image: url('{_FONDOS}/fondo_dialogo.jpg') 0 0 0 0 stretch stretch;
}}
QWidget {{ color: {INK}; }}
QMenuBar {{
    border-image: url('{_FONDOS}/barra_menu.png') 40 40 12 40 stretch stretch;
    border-width: 2px 4px 3px 4px; color: {CREMA};
}}
QMenuBar::item {{ background: transparent; padding: 6px 10px; }}
QMenuBar::item:selected {{ background: {AMBAR}; color: {CHASIS}; }}
QMenu {{
    border-image: url('{_FONDOS}/menu_panel.png') 30 30 30 30 stretch stretch;
    border-width: 4px; color: {INK};
}}
QMenu::item {{ padding: 6px 20px; }}
QMenu::item:selected {{ background: {AMBAR}; color: {CHASIS}; }}
QPushButton {{
    border-image: url('{_BOTONES}/boton_normal.png') 14 14 14 14 stretch stretch;
    border-width: 6px 8px;
    color: {CREMA}; padding: 3px 8px;
    font-family: {MONO}; letter-spacing: 1px;
}}
QPushButton:hover {{
    border-image: url('{_BOTONES}/boton_hover.png') 14 14 14 14 stretch stretch;
    color: {AMBAR_CLARO};
}}
QPushButton:pressed {{
    border-image: url('{_BOTONES}/boton_pressed.png') 14 14 14 14 stretch stretch;
}}
QPushButton:disabled {{
    border-image: url('{_BOTONES}/boton_disabled.png') 14 14 14 14 stretch stretch;
    color: #5c564b;
}}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    border-image: url('{_BOTONES}/campo.png') 50 60 50 60 stretch stretch;
    border-width: 6px 8px;
    color: {INK}; padding: 1px 4px; selection-background-color: {AMBAR};
    selection-color: {CHASIS};
}}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox::down-arrow {{ image: url('{_BOTONES}/combo_flecha.png'); width: 10px; height: 10px; }}
QTextEdit, QPlainTextEdit,
QListWidget, QTreeWidget, QTableWidget {{
    background: {VIDRIO}; color: {INK}; border: 1px solid {METAL_DIM};
    border-radius: 3px; padding: 4px; selection-background-color: {AMBAR};
    selection-color: {CHASIS};
}}
QTextEdit:focus, QPlainTextEdit:focus {{ border-color: {AMBAR}; }}
QTabWidget::pane {{
    border-image: url('{_FONDOS}/panel_resultados.png') 76 74 52 74 stretch stretch;
    border-width: 18px 18px 14px 18px;
}}
QTabBar::tab {{
    border-image: url('{_BOTONES}/pestana_inactiva.png') 40 40 40 40 stretch stretch;
    border-width: 6px 10px;
    color: {INK_DIM}; padding: 2px 8px;
    font-family: {MONO}; letter-spacing: 1px;
}}
QTabBar::tab:selected {{
    border-image: url('{_BOTONES}/pestana_activa.png') 40 40 40 40 stretch stretch;
    color: {AMBAR_CLARO};
}}
QTabBar::tab:hover:!selected {{ color: {CREMA}; }}
QProgressBar {{
    border-image: url('{_BOTONES}/barra_vacia.png') 30 120 30 120 stretch stretch;
    border-width: 5px 18px;
    text-align: center; color: {CREMA}; font-family: {MONO}; font-weight: bold;
}}
QProgressBar::chunk {{
    border-image: url('{_BOTONES}/barra_llena.png') 0 8 0 8 stretch stretch;
}}
QScrollBar:vertical {{
    border-image: url('{_BOTONES}/scroll_pista.png') 10 20 40 20 stretch stretch;
    border-width: 2px 0px; width: 12px; margin: 0;
}}
QScrollBar::handle:vertical {{
    border-image: url('{_BOTONES}/scroll_mango.png') 38 0 38 0 stretch stretch;
    min-height: 24px;
}}
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
QRadioButton::indicator {{
    width: 13px; height: 13px;
    background: {SURCO}; border: 1px solid {METAL_DIM};
}}
QRadioButton::indicator:checked {{
    background: {AMBAR}; border-color: {AMBAR_CLARO};
}}
QCheckBox::indicator {{
    width: 18px; height: 18px;
    image: url('{_BOTONES}/casilla_off.png');
}}
QCheckBox::indicator:checked {{ image: url('{_BOTONES}/casilla_on.png'); }}
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
