"""Monitor tipo estación de mastering (v0.9+): al terminar un master se muestra
la comparación visual pre-master vs master, en estilo hardware (chasis oscuro,
pantallas con bisel, medidores de LEDs, glow verde fósforo).

Qt no tiene box-shadow ni texturas como el HTML; el look se aproxima con
gradientes QSS + QGraphicsDropShadowEffect + pintura propia (QPainter).

Panel:
  - Espectro (1/3 oct.) mezcla original (azul) vs master (verde).
  - Goniómetro del master (nube mid/side).
  - Medidores de LEDs: LUFS, True Peak, Crest.
  - Readouts antes → después + cadena de proceso aplicada.
"""

import numpy as np
from PySide6.QtCharts import QChart, QChartView, QLineSeries, QLogValueAxis, QValueAxis
from PySide6.QtCore import QMargins, QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame, QGraphicsDropShadowEffect, QGridLayout, QHBoxLayout, QLabel,
    QVBoxLayout, QWidget,
)

from ..audio_analysis import cargar_audio, espectro_suavizado
from ..logger import get_logger

log = get_logger("mixmaster.ui.graficas")

# Paleta (misma del mockup aprobado)
_VERDE = "#43e08a"
_VERDE_GLOW = QColor(67, 224, 138, 180)
_AZUL = "#78b0ff"
_AMBAR = "#f0b447"
_ROJO = "#f2593a"
_INK = "#cddbe8"
_INK_DIM = "#8598ab"
_MONO = "Consolas"

_COL_PRE = QColor(_AZUL)
_COL_MASTER = QColor(_VERDE)
_COL_GLASS = QColor("#070b0d")

_MAX_PUNTOS_GONIO = 5000


def _glow(widget, color=_VERDE_GLOW, radio=14):
    """Aplica un halo (drop-shadow sin desplazamiento) para simular fósforo/LED."""
    ef = QGraphicsDropShadowEffect(widget)
    ef.setBlurRadius(radio)
    ef.setColor(color)
    ef.setOffset(0, 0)
    widget.setGraphicsEffect(ef)
    return widget


# ------------------------------------------------------- barras visuales

class _BarraComparativa(QWidget):
    """Barra horizontal: punto azul (antes) → punto verde (después) en un rango."""

    def __init__(self, antes, despues, vmin, vmax, parent=None):
        super().__init__(parent)
        self.antes, self.despues = antes, despues
        self.vmin, self.vmax = vmin, vmax
        self.setFixedHeight(14)
        self.setMinimumWidth(90)

    def _x(self, v, w, pad):
        v = max(self.vmin, min(self.vmax, v))
        return pad + (v - self.vmin) / (self.vmax - self.vmin) * (w - 2 * pad)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        cy, pad = h / 2, 6
        p.setPen(QPen(QColor("#22303c"), 4))
        p.drawLine(int(pad), int(cy), int(w - pad), int(cy))
        if self.despues is None:
            return
        xd = self._x(self.despues, w, pad)
        if self.antes is not None:
            xa = self._x(self.antes, w, pad)
            p.setPen(QPen(QColor(_VERDE), 4))
            p.drawLine(int(xa), int(cy), int(xd), int(cy))
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(_AZUL))
            p.drawEllipse(QPointF(xa, cy), 4, 4)
        else:
            p.setPen(QPen(QColor(_VERDE), 4))
            p.drawLine(int(pad), int(cy), int(xd), int(cy))
            p.setPen(Qt.NoPen)
        p.setBrush(QColor(_VERDE))
        p.drawEllipse(QPointF(xd, cy), 4, 4)


class _BarrasEQ(QWidget):
    """Mini gráfico de barras: ganancia aplicada por banda (boost verde / corte azul)."""

    ORDEN = ["sub", "low", "low_mid", "mid", "high_mid", "high", "air"]

    def __init__(self, eq: dict, parent=None):
        super().__init__(parent)
        self.eq = eq
        self.setMinimumHeight(96)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        cy = h * 0.46
        p.setPen(QPen(QColor("#2b3d4d"), 1))
        p.drawLine(0, int(cy), w, int(cy))
        bandas = [b for b in self.ORDEN if b in self.eq] or list(self.eq.keys())
        if not bandas:
            return
        maxabs = max(2.0, max(abs(self.eq[b]) for b in bandas))
        n = len(bandas)
        bw = w / n
        p.setFont(QFont(_MONO, 7))
        for i, b in enumerate(bandas):
            v = self.eq[b]
            cx = i * bw + bw / 2
            alto = (v / maxabs) * (h * 0.34)
            col = QColor(_VERDE) if v >= 0 else QColor(_AZUL)
            p.setPen(Qt.NoPen)
            p.setBrush(col)
            x0 = cx - bw * 0.28
            bar_w = bw * 0.56
            if v >= 0:
                p.drawRect(int(x0), int(cy - alto), int(bar_w), int(alto))
            else:
                p.drawRect(int(x0), int(cy), int(bar_w), int(-alto))
            p.setPen(QColor(_INK_DIM))
            p.drawText(int(cx - bw / 2), int(h - 10), int(bw), 10,
                       Qt.AlignHCenter, b.replace("_", "\n") if False else b[:4])
            p.setPen(QColor(_VERDE) if v >= 0 else QColor(_AZUL))
            p.drawText(int(cx - bw / 2), int(h - 1), int(bw), 10,
                       Qt.AlignHCenter, f"{v:+.1f}")


class _BarrasDelta(QWidget):
    """Delta por banda vs referencia: barra hacia abajo = TE FALTA, arriba = TE SOBRA.

    El dato es (mezcla - referencia) en dB. Negativo = tu mezcla tiene menos que
    la referencia en esa banda (te falta). Positivo = tiene de más (te sobra).
    """

    ORDEN = ["sub", "low", "low_mid", "mid", "high_mid", "high", "air"]
    ETIQ = {"sub": "SUB", "low": "GRAVE", "low_mid": "L-MID", "mid": "MEDIO",
            "high_mid": "H-MID", "high": "AGUDO", "air": "AIRE"}

    def __init__(self, delta: dict, parent=None):
        super().__init__(parent)
        self.delta = delta
        self.setMinimumHeight(170)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        cy = h * 0.5
        bandas = [b for b in self.ORDEN if b in self.delta] or list(self.delta.keys())
        if not bandas:
            return
        maxabs = max(6.0, max(abs(self.delta[b]) for b in bandas))
        n = len(bandas)
        bw = w / n
        alto_max = h * 0.32

        # línea de referencia (0 = igual a la referencia)
        p.setPen(QPen(QColor("#5a6b8c"), 1, Qt.DashLine))
        p.drawLine(0, int(cy), w, int(cy))
        p.setFont(QFont(_MONO, 7))
        p.setPen(QColor("#54687c"))
        p.drawText(4, int(cy - 3), "= referencia")

        for i, b in enumerate(bandas):
            v = self.delta[b]
            cx = i * bw + bw / 2
            alto = (v / maxabs) * alto_max
            # negativo (te falta) = ámbar hacia abajo · positivo (te sobra) = azul hacia arriba
            col = QColor(_AZUL) if v >= 0 else QColor(_AMBAR)
            p.setPen(Qt.NoPen)
            p.setBrush(col)
            x0 = cx - bw * 0.30
            bar_w = bw * 0.60
            if v >= 0:
                p.drawRect(int(x0), int(cy - alto), int(bar_w), int(alto))
            else:
                p.drawRect(int(x0), int(cy), int(bar_w), int(-alto))
            # etiqueta de banda
            p.setFont(QFont(_MONO, 7))
            p.setPen(QColor(_INK_DIM))
            p.drawText(int(cx - bw / 2), int(h - 22), int(bw), 12,
                       Qt.AlignHCenter, self.ETIQ.get(b, b[:4]))
            # valor en dB
            p.setPen(col)
            p.setFont(QFont(_MONO, 8, QFont.Bold))
            p.drawText(int(cx - bw / 2), int(h - 9), int(bw), 12,
                       Qt.AlignHCenter, f"{v:+.0f}")


# ------------------------------------------------------- loudness war score

class _LoudnessWarScore(QWidget):
    """Mapa LUFS (loudness) x Crest (dinámica): dónde cae tu master respecto
    de la zona sana. Eje X: -20..-4 LUFS. Eje Y: 0..20 dB crest.

    'Zona sana' = banda diagonal donde a más loudness corresponde algo menos
    de crest, pero sin caer en aplastamiento (crest muy bajo + muy loud).
    """

    def __init__(self, lufs: float, crest: float, parent=None):
        super().__init__(parent)
        self.lufs, self.crest = lufs, crest
        self.setMinimumHeight(200)

    def _pos(self, lufs, crest, w, h, pad=36):
        x = pad + (lufs - (-20)) / (( -4) - (-20)) * (w - 2 * pad)
        y = (h - pad) - (crest - 0) / (20 - 0) * (h - 2 * pad)
        return x, y

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        pad = 36
        p.fillRect(self.rect(), QColor("#070b0d"))

        # zona sana: banda diagonal (crest razonable incluso siendo loud)
        zona = [(-20, 8), (-9, 8), (-9, 20), (-20, 20)]
        zona_ok = [(-9, 8), (-4, 6), (-4, 20), (-9, 20)]
        for poly, alpha in ((zona, 40), (zona_ok, 25)):
            pts = [self._pos(x, y, w, h, pad) for x, y in poly]
            path_pts = [self._pos(x, y, w, h, pad) for x, y in
                       [(poly[0][0], 0)] + poly + [(poly[-1][0], 0)]]
            p.setBrush(QColor(67, 224, 138, alpha))
            p.setPen(Qt.NoPen)
            from PySide6.QtGui import QPolygonF
            p.drawPolygon(QPolygonF([QPointF(*pt) for pt in pts]))

        # zona de peligro (crest muy bajo = sobre-comprimido)
        peligro = [(-20, 0), (-4, 0), (-4, 6), (-20, 8)]
        pts = [self._pos(x, y, w, h, pad) for x, y in peligro]
        p.setBrush(QColor(242, 89, 58, 35))
        p.setPen(Qt.NoPen)
        from PySide6.QtGui import QPolygonF
        p.drawPolygon(QPolygonF([QPointF(*pt) for pt in pts]))

        # ejes
        p.setPen(QPen(QColor(40, 55, 68), 1))
        p.drawLine(pad, h - pad, w - pad, h - pad)
        p.drawLine(pad, pad, pad, h - pad)
        p.setFont(QFont(_MONO, 8))
        p.setPen(QColor(_INK_DIM))
        for lu in (-20, -14, -9, -4):
            x, _ = self._pos(lu, 0, w, h, pad)
            p.drawText(int(x - 12), h - pad + 16, f"{lu}")
        for cr in (0, 6, 12, 20):
            _, y = self._pos(-20, cr, w, h, pad)
            p.drawText(4, int(y + 4), f"{cr}")
        p.drawText(w // 2 - 30, h - 6, "LUFS integrado")
        p.save()
        p.translate(12, h // 2 + 20)
        p.rotate(-90)
        p.drawText(0, 0, "Crest (dB)")
        p.restore()

        # tu master
        if self.lufs is not None and self.crest is not None:
            x, y = self._pos(self.lufs, self.crest, w, h, pad)
            p.setPen(QPen(QColor(_VERDE), 2))
            p.setBrush(QColor(_VERDE))
            p.drawEllipse(QPointF(x, y), 6, 6)
            p.setFont(QFont(_MONO, 9, QFont.Bold))
            p.setPen(QColor(_VERDE))
            p.drawText(int(x + 10), int(y - 6), f"{self.lufs:g} LUFS · {self.crest:g} dB")


def _leyenda_lws() -> QLabel:
    l = QLabel(
        f"<span style='color:{_VERDE}'>■ zona sana</span>  "
        f"<span style='color:{_ROJO}'>■ zona de riesgo (sobre-comprimido)</span>")
    l.setTextFormat(Qt.RichText)
    l.setStyleSheet(f"border:none; color:#54687c; font-family:{_MONO}; font-size:10px;")
    return l


# --------------------------------------------------------------- espectro

def _serie(freqs, dbs, color: QColor, nombre: str) -> QLineSeries:
    s = QLineSeries()
    s.setName(nombre)
    s.setPen(QPen(color, 2))
    for f, d in zip(freqs, dbs):
        if f > 0:
            s.append(float(f), float(d))
    return s


def _grafica_espectro(freqs_pre, db_pre, freqs_master, db_master) -> QChartView:
    chart = QChart()
    chart.setBackgroundBrush(_COL_GLASS)
    chart.setPlotAreaBackgroundBrush(_COL_GLASS)
    chart.setPlotAreaBackgroundVisible(True)
    chart.setMargins(QMargins(4, 4, 4, 4))
    chart.legend().setVisible(True)
    chart.legend().setLabelColor(QColor(_INK_DIM))
    chart.legend().setAlignment(Qt.AlignBottom)

    todos = list(db_master) + (list(db_pre) if db_pre is not None else [])
    if todos:
        centro = np.median(todos)
        y_min, y_max = centro - 40, max(todos) + 6
    else:
        y_min, y_max = -80, 0

    ex = QLogValueAxis()
    ex.setBase(10)
    ex.setRange(20, 20000)
    ex.setLabelFormat("%g")
    ex.setTitleText("Hz")
    ex.setTitleBrush(QColor(_INK_DIM))
    ex.setLabelsColor(QColor(_INK_DIM))
    ex.setGridLineColor(QColor(30, 42, 52))
    ex.setLinePenColor(QColor(40, 55, 68))

    ey = QValueAxis()
    ey.setRange(y_min, y_max)
    ey.setTitleText("dB")
    ey.setTitleBrush(QColor(_INK_DIM))
    ey.setLabelsColor(QColor(_INK_DIM))
    ey.setGridLineColor(QColor(30, 42, 52))
    ey.setLinePenColor(QColor(40, 55, 68))

    chart.addAxis(ex, Qt.AlignBottom)
    chart.addAxis(ey, Qt.AlignLeft)

    if freqs_pre is not None and db_pre is not None:
        sp = _serie(freqs_pre, db_pre, _COL_PRE, "Mezcla original")
        chart.addSeries(sp)
        sp.attachAxis(ex)
        sp.attachAxis(ey)

    sm = _serie(freqs_master, db_master, _COL_MASTER, "Master")
    chart.addSeries(sm)
    sm.attachAxis(ex)
    sm.attachAxis(ey)

    vista = QChartView(chart)
    vista.setRenderHint(QPainter.Antialiasing)
    vista.setMinimumHeight(240)
    vista.setStyleSheet("background: transparent; border: none;")
    return vista


# ------------------------------------------------------------- goniómetro

class _LienzoGonio(QWidget):
    """Nube mid/side del master (estilo goniómetro)."""

    def __init__(self, mid, side, parent=None):
        super().__init__(parent)
        self.mid, self.side = mid, side
        self.setMinimumHeight(240)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        r = min(w, h) / 2 - 14
        p.fillRect(self.rect(), _COL_GLASS)
        p.setPen(QPen(QColor(40, 55, 68), 1))
        p.drawLine(int(cx), 12, int(cx), int(h - 12))
        p.drawLine(12, int(cy), int(w - 12), int(cy))
        p.setPen(QPen(QColor(45, 62, 78), 1, Qt.DashLine))
        p.drawEllipse(int(cx - r), int(cy - r), int(r * 2), int(r * 2))
        p.setPen(QPen(QColor(67, 224, 138, 120), 1))
        for s, m in zip(self.side, self.mid):
            p.drawPoint(int(cx + s * r), int(cy - m * r))
        p.setPen(QColor(_INK_DIM))
        p.drawText(int(cx) - 10, 14, "M")
        p.drawText(int(w - 20), int(cy) + 4, "S")


def _panel_gonio(wav_master):
    try:
        audio, sr = cargar_audio(wav_master)
    except Exception:
        log.exception("No se pudo cargar el master para el goniómetro")
        return None
    if audio.shape[1] < 2:
        return None
    paso = max(1, audio.shape[0] // _MAX_PUNTOS_GONIO)
    m = audio[::paso]
    L, R = m[:, 0], m[:, 1]
    mid = (L + R) / np.sqrt(2)
    side = (L - R) / np.sqrt(2)
    pico = max(np.max(np.abs(mid)), np.max(np.abs(side)), 1e-9)
    return _LienzoGonio(mid / pico, side / pico)


# ------------------------------------------------------------- LED meters

class _MedidorLED(QFrame):
    """Columna de LEDs (verde→ámbar→rojo) que se ENCIENDE progresivamente (animado)."""

    def __init__(self, titulo, valor, vmin, vmax, amb_frac=0.82, red_frac=0.92, n=18, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            "QFrame { background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            " stop:0 #0c141b, stop:1 #16222d); border:1px solid #33495b;"
            " border-radius:10px; }")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(5)
        lay.setAlignment(Qt.AlignHCenter)

        lbl = QLabel(titulo)
        lbl.setStyleSheet(f"border:none; color:{_INK_DIM}; font-family:{_MONO}; font-size:9px;")
        lbl.setAlignment(Qt.AlignHCenter)
        lay.addWidget(lbl)

        frac = 0.0 if valor is None else max(0.0, min(1.0, (valor - vmin) / (vmax - vmin)))
        self._objetivo = round(frac * n)
        self._n = n
        self._amb, self._red = amb_frac, red_frac
        self._segs = []  # de abajo (i=0) hacia arriba
        escalera = QVBoxLayout()
        escalera.setSpacing(2)
        for i in range(n - 1, -1, -1):
            seg = QFrame()
            seg.setFixedSize(18, 6)
            seg.setStyleSheet("background:#101a20; border-radius:2px;")
            escalera.addWidget(seg, alignment=Qt.AlignHCenter)
            self._segs.append((i, seg))
        self._segs.sort(key=lambda x: x[0])  # ordenar por índice ascendente
        lay.addLayout(escalera)

        val = QLabel("—" if valor is None else f"{valor:g}")
        val.setStyleSheet(f"border:none; color:{_VERDE}; font-family:{_MONO}; font-size:12px;")
        val.setAlignment(Qt.AlignHCenter)
        _glow(val, radio=10)
        lay.addWidget(val)

        # enciende un LED cada 45 ms, de abajo hacia arriba
        self._cur = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._encender_siguiente)
        QTimer.singleShot(120, lambda: self._timer.start(45))

    def _color(self, i):
        if i >= self._red * self._n:
            return _ROJO
        if i >= self._amb * self._n:
            return _AMBAR
        return _VERDE

    def _encender_siguiente(self):
        if self._cur >= self._objetivo:
            self._timer.stop()
            return
        i, seg = self._segs[self._cur]
        seg.setStyleSheet(f"background:{self._color(i)}; border-radius:2px;")
        self._cur += 1


def _medidor_led(titulo, valor, vmin, vmax, amb_frac=0.82, red_frac=0.92, n=18):
    return _MedidorLED(titulo, valor, vmin, vmax, amb_frac, red_frac, n)


# ------------------------------------------------------------- readouts

def _tarjeta_metrica(titulo: str, antes, despues, unidad: str = "",
                     rango: tuple | None = None) -> QFrame:
    f = QFrame()
    f.setStyleSheet(
        "QFrame { background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
        " stop:0 #1f2e3a, stop:1 #141f28); border:1px solid #314658;"
        " border-radius:10px; }")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(10, 8, 10, 8)
    lay.setSpacing(4)
    t = QLabel(titulo.upper())
    t.setStyleSheet(f"border:none; color:#54687c; font-family:{_MONO}; font-size:9px;")
    lay.addWidget(t)
    txt = (f"{antes:g} → {despues:g} {unidad}" if antes is not None
           else f"{despues:g} {unidad}")
    v = QLabel(txt.strip())
    v.setStyleSheet(f"border:none; color:{_INK}; font-family:{_MONO}; font-size:14px;")
    lay.addWidget(v)
    if rango is not None and despues is not None:
        lay.addWidget(_BarraComparativa(antes, despues, rango[0], rango[1]))
    return f


def _bloque_proceso(resumen: dict) -> QFrame:
    f = QFrame()
    f.setStyleSheet(
        "QFrame { background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
        " stop:0 #111c25, stop:1 #0c151c); border:1px solid #2c4053;"
        " border-radius:12px; }")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(14, 12, 14, 12)
    titulo = QLabel("🔧 CADENA DE PROCESO APLICADA")
    titulo.setStyleSheet(f"border:none; color:{_INK_DIM}; font-family:{_MONO}; font-size:10px; letter-spacing:2px;")
    lay.addWidget(titulo)

    eq = resumen.get("eq_aplicado_db") or {}
    if eq:
        eq_lbl = QLabel("EQ aplicado (dB por banda)")
        eq_lbl.setStyleSheet(f"border:none; color:#54687c; font-family:{_MONO}; font-size:9px;")
        lay.addWidget(eq_lbl)
        lay.addWidget(_BarrasEQ(eq))

    mods = []
    if eq:
        mods.append(("EQ", ", ".join(f"{b} {v:+.1f}" for b, v in eq.items())))
    mb = resumen.get("multibanda_db") or {}
    if mb:
        mods.append(("Multibanda", ", ".join(f"{b} -{v:g}" for b, v in mb.items())))
    reso = resumen.get("resonancias_db") or []
    if reso:
        mods.append(("Resonancia", ", ".join(f"{r['freq']:g}Hz {r['corte_db']:g}dB" for r in reso)))
    if resumen.get("transient_shaping"):
        mods.append(("Transient", f"+{resumen['transient_shaping']:g}"))
    if resumen.get("mono_bass_hz"):
        mods.append(("Mono-bass", f"<{resumen['mono_bass_hz']:g} Hz"))
    ancho = resumen.get("ajuste_ancho_db") or {}
    if ancho:
        mods.append(("Imagen", ", ".join(f"{b} {v:+.1f}" for b, v in ancho.items())))
    if resumen.get("densidad_aplicada"):
        mods.append(("Densidad", "sí"))
    if not mods:
        mods.append(("Sin proceso correctivo", "no había referencia o no hizo falta"))

    grid = QGridLayout()
    grid.setSpacing(8)
    for i, (nombre, det) in enumerate(mods):
        chip = QLabel(f"{nombre}  <span style='color:{_VERDE}'>{det}</span>")
        chip.setTextFormat(Qt.RichText)
        chip.setStyleSheet(
            "QLabel { background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            " stop:0 #20313f, stop:1 #131f28); border:1px solid #3a556b;"
            f" border-radius:8px; padding:6px 11px; color:{_INK}; font-family:{_MONO}; font-size:11px; }}")
        grid.addWidget(chip, i // 3, i % 3)
    lay.addLayout(grid)
    return f


def _pantalla(titulo: str, extra: str, contenido: QWidget) -> QFrame:
    """Envuelve un widget en una 'pantalla' con bisel oscuro y encabezado."""
    bisel = QFrame()
    bisel.setStyleSheet(
        "QFrame { background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
        " stop:0 #0c141b, stop:1 #182430); border:1px solid #33495b;"
        " border-radius:12px; }")
    lay = QVBoxLayout(bisel)
    lay.setContentsMargins(10, 8, 10, 8)
    cab = QLabel(f"{titulo}   <span style='color:{_VERDE}'>{extra}</span>")
    cab.setTextFormat(Qt.RichText)
    cab.setStyleSheet(f"border:none; color:{_INK_DIM}; font-family:{_MONO}; font-size:10px; letter-spacing:2px;")
    lay.addWidget(cab)
    lay.addWidget(contenido)
    return bisel


# ------------------------------------------------------------- panel raíz

def construir_panel_mastering(resumen: dict, diagnostico: dict | None,
                              wav_premaster) -> QWidget:
    """Panel completo del monitor (estilo estación de mastering)."""
    panel = QFrame()
    panel.setStyleSheet(
        "QFrame#chasis { background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
        " stop:0 #243441, stop:0.5 #16222c, stop:1 #0e1820);"
        " border:1px solid #34495b; border-radius:16px; }")
    panel.setObjectName("chasis")
    lay = QVBoxLayout(panel)
    lay.setContentsMargins(16, 16, 16, 16)
    lay.setSpacing(14)

    # cabecera
    cab = QLabel("🎛  MIXMASTER · MONITOR")
    cab.setStyleSheet(f"border:none; color:#e6eef6; font-family:{_MONO}; font-size:13px; letter-spacing:3px;")
    lay.addWidget(cab)

    # fila de pantallas: espectro | goniómetro | medidores
    fila = QHBoxLayout()
    fila.setSpacing(14)

    esp_m = resumen.get("espectro_master") or {}
    freqs_master, db_master = esp_m.get("freqs"), esp_m.get("db")
    freqs_pre = db_pre = None
    if wav_premaster is not None:
        try:
            audio, sr = cargar_audio(wav_premaster)
            fp, dp = espectro_suavizado(audio, sr, n_puntos=200)
            freqs_pre, db_pre = list(fp), list(dp)
        except Exception:
            log.exception("No se pudo calcular el espectro de la mezcla original")

    if freqs_master:
        esp = _grafica_espectro(freqs_pre, db_pre, freqs_master, db_master)
        fila.addWidget(_pantalla("ESPECTRO", "1/3 OCT", esp), stretch=3)

    gonio = _panel_gonio(Path_wav(resumen))
    est = (diagnostico or {}).get("estereo", {})
    corr = est.get("correlacion_global")
    if gonio is not None:
        fila.addWidget(_pantalla("IMAGEN ESTÉREO",
                                 f"CORR {corr:.2f}" if corr is not None else "", gonio), stretch=3)

    # medidores LED
    g = (diagnostico or {}).get("global", {})
    med = QHBoxLayout()
    med.setSpacing(8)
    med.addWidget(_medidor_led("LUFS", resumen.get("lufs_final"), -30, 0))
    med.addWidget(_medidor_led("PEAK", resumen.get("true_peak_final"), -30, 0))
    med.addWidget(_medidor_led("CREST", resumen.get("crest_final"), 0, 20, amb_frac=2, red_frac=2))
    med_cont = QWidget()
    med_cont.setLayout(med)
    fila.addWidget(med_cont, stretch=2)

    lay.addLayout(fila)

    # readouts antes → después
    grid = QGridLayout()
    grid.setSpacing(10)
    grid.addWidget(_tarjeta_metrica("LUFS integrado", g.get("lufs_i"), resumen.get("lufs_final"), "LUFS", (-30, 0)), 0, 0)
    grid.addWidget(_tarjeta_metrica("True peak", g.get("true_peak_db"), resumen.get("true_peak_final"), "dBTP", (-12, 0)), 0, 1)
    grid.addWidget(_tarjeta_metrica("Crest", g.get("crest_factor_db"), resumen.get("crest_final"), "dB", (0, 20)), 0, 2)
    if g.get("lra") is not None:
        grid.addWidget(_tarjeta_metrica("LRA", None, g.get("lra"), "LU", (0, 20)), 0, 3)
    col = 0
    if est.get("correlacion_global") is not None:
        grid.addWidget(_tarjeta_metrica("Correlación estéreo", None, est.get("correlacion_global"), "", (-1, 1)), 1, col); col += 1
    if est.get("perdida_mono_db") is not None:
        grid.addWidget(_tarjeta_metrica("Pérdida mono", None, est.get("perdida_mono_db"), "dB", (-6, 0)), 1, col); col += 1
    score = resumen.get("score") or {}
    if score:
        grid.addWidget(_tarjeta_metrica("Score vs ref", None, score.get("global"), "%", (0, 100)), 1, col)
    lay.addLayout(grid)

    # gráfica estrella: qué corregir en tu mezcla (delta vs referencia)
    vs = (diagnostico or {}).get("vs_referencia") or {}
    delta = vs.get("delta_bandas_db")
    if delta:
        caja = QFrame()
        caja.setStyleSheet(
            "QFrame { background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            " stop:0 #111c25, stop:1 #0c151c); border:1px solid #2c4053;"
            " border-radius:12px; }")
        cl = QVBoxLayout(caja)
        cl.setContentsMargins(14, 12, 14, 12)
        tit = QLabel(f"🎯 VS REFERENCIA — qué corregir en tu mezcla   "
                     f"<span style='color:{_INK_DIM}'>({vs.get('referencia', '')})</span>")
        tit.setTextFormat(Qt.RichText)
        tit.setStyleSheet(f"border:none; color:{_INK_DIM}; font-family:{_MONO}; font-size:10px; letter-spacing:2px;")
        cl.addWidget(tit)
        ley = QLabel(f"<span style='color:{_AMBAR}'>▼ te falta</span>   "
                     f"<span style='color:{_AZUL}'>▲ te sobra</span>   ·   respecto de la referencia, por banda")
        ley.setTextFormat(Qt.RichText)
        ley.setStyleSheet(f"border:none; color:#54687c; font-family:{_MONO}; font-size:10px;")
        cl.addWidget(ley)
        cl.addWidget(_BarrasDelta(delta))
        lay.addWidget(caja)

    # loudness war score: ¿zona sana o sobre-comprimido?
    if resumen.get("lufs_final") is not None and resumen.get("crest_final") is not None:
        caja_lws = QFrame()
        caja_lws.setStyleSheet(
            "QFrame { background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            " stop:0 #111c25, stop:1 #0c151c); border:1px solid #2c4053;"
            " border-radius:12px; }")
        cl2 = QVBoxLayout(caja_lws)
        cl2.setContentsMargins(14, 12, 14, 12)
        tit2 = QLabel("📊 LOUDNESS WAR SCORE")
        tit2.setStyleSheet(f"border:none; color:{_INK_DIM}; font-family:{_MONO}; font-size:10px; letter-spacing:2px;")
        cl2.addWidget(tit2)
        cl2.addWidget(_leyenda_lws())
        cl2.addWidget(_LoudnessWarScore(resumen["lufs_final"], resumen["crest_final"]))
        lay.addWidget(caja_lws)

    lay.addWidget(_bloque_proceso(resumen))

    nota = QLabel("Azul = mezcla original · Verde = master · Las tarjetas comparan antes → después.")
    nota.setWordWrap(True)
    nota.setStyleSheet(f"border:none; color:#54687c; font-family:{_MONO}; font-size:10px;")
    lay.addWidget(nota)

    envoltura = QWidget()
    ev = QVBoxLayout(envoltura)
    ev.setContentsMargins(0, 0, 0, 0)
    ev.addWidget(panel)
    return envoltura


def Path_wav(resumen: dict):
    """Ruta del WAV del master desde el resumen (o None)."""
    from pathlib import Path
    w = resumen.get("wav")
    return Path(w) if w else None
