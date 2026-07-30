"""Ficha rica de una referencia (v0.9+): visualiza TODO el análisis profundo
que ya se calcula y cachea (audio_analysis.analizar_referencia_cacheada) —
antes solo quedaba guardado en JSON, invisible para el usuario.

Reusa el estilo "estación de mastering" de graficas.py (mismos colores,
pantallas con bisel, medidores). Es de lectura, no procesa nada.
"""

import numpy as np
from PySide6.QtCharts import QChart, QChartView, QLineSeries, QLogValueAxis, QValueAxis
from PySide6.QtCore import QMargins, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QDialog, QFrame, QGridLayout, QLabel, QScrollArea, QVBoxLayout, QWidget,
)

from ..audio_analysis import analizar_referencia_cacheada
from ..logger import get_logger
from .graficas import _AMBAR, _AZUL, _INK, _INK_DIM, _MONO, _VERDE, _tarjeta_metrica

log = get_logger("mixmaster.ui.ficha_referencia")

_COL_GLASS = QColor("#070b0d")


def _pantalla(titulo: str, contenido: QWidget) -> QFrame:
    bisel = QFrame()
    bisel.setStyleSheet(
        "QFrame { background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
        " stop:0 #0c141b, stop:1 #182430); border:1px solid #33495b;"
        " border-radius:12px; }")
    lay = QVBoxLayout(bisel)
    lay.setContentsMargins(10, 8, 10, 8)
    cab = QLabel(titulo)
    cab.setStyleSheet(f"border:none; color:{_INK_DIM}; font-family:{_MONO}; font-size:10px; letter-spacing:2px;")
    lay.addWidget(cab)
    lay.addWidget(contenido)
    return bisel


def _grafica_espectro_solo(freqs, db) -> QChartView:
    chart = QChart()
    chart.setBackgroundBrush(_COL_GLASS)
    chart.setPlotAreaBackgroundBrush(_COL_GLASS)
    chart.setPlotAreaBackgroundVisible(True)
    chart.setMargins(QMargins(4, 4, 4, 4))
    chart.legend().setVisible(False)

    ex = QLogValueAxis()
    ex.setBase(10)
    ex.setRange(20, 20000)
    ex.setLabelFormat("%g")
    ex.setTitleText("Hz")
    ex.setTitleBrush(QColor(_INK_DIM))
    ex.setLabelsColor(QColor(_INK_DIM))
    ex.setGridLineColor(QColor(30, 42, 52))

    y_min, y_max = (min(db) - 6, max(db) + 6) if db else (-80, 0)
    ey = QValueAxis()
    ey.setRange(y_min, y_max)
    ey.setTitleText("dB")
    ey.setTitleBrush(QColor(_INK_DIM))
    ey.setLabelsColor(QColor(_INK_DIM))
    ey.setGridLineColor(QColor(30, 42, 52))

    chart.addAxis(ex, Qt.AlignBottom)
    chart.addAxis(ey, Qt.AlignLeft)

    s = QLineSeries()
    s.setPen(QPen(QColor(_VERDE), 2))
    for f, d in zip(freqs, db):
        if f > 0:
            s.append(float(f), float(d))
    chart.addSeries(s)
    s.attachAxis(ex)
    s.attachAxis(ey)

    vista = QChartView(chart)
    vista.setRenderHint(QPainter.Antialiasing)
    vista.setMinimumHeight(200)
    vista.setStyleSheet("background: transparent; border: none;")
    return vista


class _BarrasAncho(QWidget):
    """Ancho estéreo por banda: 0 = mono, 1 = todo side. Barras horizontales."""

    ORDEN = ["sub", "low", "low_mid", "mid", "high_mid", "high", "air"]
    ETIQ = {"sub": "SUB", "low": "GRAVE", "low_mid": "L-MID", "mid": "MEDIO",
            "high_mid": "H-MID", "high": "AGUDO", "air": "AIRE"}

    def __init__(self, ancho: dict, parent=None):
        super().__init__(parent)
        self.ancho = ancho
        self.setMinimumHeight(140)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        bandas = [b for b in self.ORDEN if b in self.ancho] or list(self.ancho.keys())
        if not bandas:
            return
        n = len(bandas)
        fila_h = h / n
        p.setFont(QFont(_MONO, 8))
        for i, b in enumerate(bandas):
            v = max(0.0, min(1.0, self.ancho[b]))
            y = i * fila_h + fila_h * 0.2
            bh = fila_h * 0.6
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#101a20"))
            p.drawRect(70, int(y), int(w - 90), int(bh))
            p.setBrush(QColor(_AZUL))
            p.drawRect(70, int(y), int((w - 90) * v), int(bh))
            p.setPen(QColor(_INK_DIM))
            p.drawText(4, int(y + bh - 2), self.ETIQ.get(b, b[:5]))
            p.setPen(QColor(_INK))
            p.drawText(int(w - 16), int(y + bh - 2), f"{v:.2f}")


def _tarjeta_texto(titulo: str, valor: str, nota: str = "") -> QFrame:
    f = QFrame()
    f.setStyleSheet(
        "QFrame { background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
        " stop:0 #1f2e3a, stop:1 #141f28); border:1px solid #314658;"
        " border-radius:10px; }")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(10, 8, 10, 8)
    lay.setSpacing(2)
    t = QLabel(titulo.upper())
    t.setStyleSheet(f"border:none; color:#54687c; font-family:{_MONO}; font-size:9px;")
    lay.addWidget(t)
    v = QLabel(valor)
    v.setStyleSheet(f"border:none; color:{_INK}; font-family:{_MONO}; font-size:15px;")
    lay.addWidget(v)
    if nota:
        n = QLabel(nota)
        n.setWordWrap(True)
        n.setStyleSheet(f"border:none; color:{_VERDE}; font-family:{_MONO}; font-size:10px;")
        lay.addWidget(n)
    return f


def _interpretar_tilt(tilt: float) -> str:
    if tilt <= -4:
        return "muy oscura"
    if tilt <= -1.5:
        return "cálida/oscura"
    if tilt <= 1.0:
        return "balanceada"
    return "brillante"


def _interpretar_graves(d: float) -> str:
    if d >= 6:
        return "bajo bien definido"
    if d >= -2:
        return "equilibrado"
    return "pesado, poco definido ('bola')"


def _interpretar_punch(p: float) -> str:
    if p >= 3.5:
        return "muy percusivo"
    if p >= 1.8:
        return "pegada normal"
    return "sostenido/suave"


def construir_ficha(path) -> QWidget:
    """Panel con TODO el análisis profundo de una referencia, visual."""
    from pathlib import Path
    path = Path(path)
    panel = QWidget()
    lay = QVBoxLayout(panel)
    lay.setContentsMargins(14, 14, 14, 14)
    lay.setSpacing(12)

    try:
        e = analizar_referencia_cacheada(path)
    except Exception:
        log.exception("No se pudo analizar la referencia para la ficha")
        lay.addWidget(QLabel("No se pudo analizar este archivo."))
        return panel

    cab = QLabel(f"📀  {path.name}")
    cab.setStyleSheet(f"color:#e6eef6; font-family:{_MONO}; font-size:14px; font-weight:bold;")
    lay.addWidget(cab)

    # --- espectro ---
    if e.get("espectro_freqs"):
        lay.addWidget(_pantalla("ESPECTRO — 1/3 OCT",
                                _grafica_espectro_solo(e["espectro_freqs"], e["espectro_db"])))

    # --- métricas de carácter (las nuevas, con interpretación) ---
    grid = QGridLayout()
    grid.setSpacing(10)
    tilt = e.get("inclinacion_db_oct")
    if tilt is not None:
        grid.addWidget(_tarjeta_texto("Inclinación espectral", f"{tilt:+.1f} dB/oct",
                                      _interpretar_tilt(tilt)), 0, 0)
    dg = e.get("definicion_graves_db")
    if dg is not None:
        grid.addWidget(_tarjeta_texto("Definición de graves", f"{dg:+.1f} dB",
                                      _interpretar_graves(dg)), 0, 1)
    punch = e.get("punch")
    if punch is not None:
        grid.addWidget(_tarjeta_texto("Punch (pegada)", f"{punch:.2f}",
                                      _interpretar_punch(punch)), 0, 2)
    if e.get("plr_db") is not None:
        grid.addWidget(_tarjeta_metrica("PLR (headroom)", None, e["plr_db"], "dB", (0, 20)), 1, 0)
    if e.get("crest_db") is not None:
        grid.addWidget(_tarjeta_metrica("Crest global", None, e["crest_db"], "dB", (0, 20)), 1, 1)
    if e.get("lufs") is not None:
        grid.addWidget(_tarjeta_metrica("LUFS integrado", None, e["lufs"], "LUFS", (-30, 0)), 1, 2)
    if e.get("centroide_hz") is not None:
        grid.addWidget(_tarjeta_texto("Centroide espectral", f"{e['centroide_hz']:.0f} Hz",
                                      "centro de brillo"), 2, 0)
    if e.get("rolloff_hz") is not None:
        grid.addWidget(_tarjeta_texto("Rolloff 85%", f"{e['rolloff_hz']:.0f} Hz",
                                      "dónde muere el agudo"), 2, 1)
    lay.addLayout(grid)

    # --- ancho estéreo por banda ---
    if e.get("ancho_por_banda"):
        lay.addWidget(_pantalla("ANCHO ESTÉREO POR BANDA", _BarrasAncho(e["ancho_por_banda"])))

    nota = QLabel(
        "Este es el sonido que persigue el master cuando uses esta referencia. "
        "Análisis cacheado — instantáneo salvo que cambie el archivo.")
    nota.setWordWrap(True)
    nota.setStyleSheet(f"color:#54687c; font-family:{_MONO}; font-size:10px;")
    lay.addWidget(nota)
    lay.addStretch()
    return panel


class FichaReferenciaDialog(QDialog):
    """Ventana con la ficha rica de una referencia."""

    def __init__(self, path, parent=None):
        super().__init__(parent)
        from pathlib import Path
        self.setWindowTitle(f"🔍 Ficha — {Path(path).name}")
        self.resize(560, 700)
        self.setStyleSheet("QDialog { background: #0e1820; }")
        lay = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: #0e1820; }")
        scroll.setWidget(construir_ficha(path))
        lay.addWidget(scroll)
