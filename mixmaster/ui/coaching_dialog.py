"""Reporte coaching "sin maquillaje" (v0.9+): muestra el diagnóstico por stem
en lenguaje directo y accionable, para mejorar la MEZCLA (no el master).
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QFrame, QLabel, QScrollArea, QVBoxLayout, QWidget,
)

from ..logger import get_logger
from ..stem_diagnostico import checklist_pre_mezcla, diagnosticar_carpeta

log = get_logger("mixmaster.ui.coaching")

_TIPO_ICONO = {"bajo": "🎸", "bateria": "🥁", "guitarra": "🎸",
               "voz": "🎤", "generico": "🎚"}


class CoachingDialog(QDialog):
    """Ventana con el diagnóstico stem por stem del proyecto activo."""

    def __init__(self, carpeta_stems, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🔬 Diagnóstico de stems — sin maquillaje")
        self.resize(620, 640)
        self.setStyleSheet("QDialog { background: #0e1820; }")

        raiz = QVBoxLayout(self)
        intro = QLabel(
            "Esto mira cada stem por separado y te dice qué mejorar en tu MEZCLA "
            "(no en el master). Es el «sin maquillaje»: honesto y accionable.")
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #8598ab; font-family: Consolas; padding: 4px;")
        raiz.addWidget(intro)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: #0e1820; }")
        cont = QWidget()
        cont.setStyleSheet("background: #0e1820;")
        lay = QVBoxLayout(cont)

        diags = diagnosticar_carpeta(carpeta_stems)
        if not diags:
            lay.addWidget(QLabel("No hay stems para diagnosticar en este proyecto."))
        else:
            n_alertas = sum(1 for d in diags for ic, _ in d["observaciones"] if ic == "⚠")
            resumen = QLabel(f"📋 {len(diags)} stems analizados · "
                             f"{n_alertas} cosa(s) para mejorar")
            resumen.setStyleSheet("color: #43e08a; font-family: Consolas; font-weight: bold; padding: 4px;")
            lay.addWidget(resumen)

            choques = checklist_pre_mezcla(carpeta_stems)
            if choques:
                lay.addWidget(self._tarjeta_choques(choques))

            for d in diags:
                lay.addWidget(self._tarjeta_stem(d))
        lay.addStretch()

        scroll.setWidget(cont)
        raiz.addWidget(scroll)

    def _tarjeta_choques(self, choques: list[str]) -> QFrame:
        """Checklist pre-mezcla: cómo interactúan los stems ENTRE SÍ (choque
        de frecuencias + masking rítmico), a diferencia de las tarjetas de
        abajo que miran cada stem solo."""
        f = QFrame()
        f.setStyleSheet(
            "QFrame { background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            " stop:0 #2a1f14, stop:1 #1c150e); border:1px solid #7a5a1e;"
            " border-radius:10px; }")
        lay = QVBoxLayout(f)
        cab = QLabel("⚔️  CHECKLIST PRE-MEZCLA — choques entre stems")
        cab.setStyleSheet("border:none; color:#f0b447; font-family: Consolas; font-size: 13px; font-weight: bold;")
        lay.addWidget(cab)
        for texto in choques:
            o = QLabel(f"⚠  {texto}")
            o.setWordWrap(True)
            o.setStyleSheet("border:none; color:#f0b447; font-family: Consolas; font-size: 12px; padding-left: 6px;")
            lay.addWidget(o)
        return f

    def _tarjeta_stem(self, d: dict) -> QFrame:
        f = QFrame()
        tiene_alerta = any(ic == "⚠" for ic, _ in d["observaciones"])
        borde = "#7a5a1e" if tiene_alerta else "#2c4053"
        f.setStyleSheet(
            "QFrame { background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            " stop:0 #16222d, stop:1 #101a24); border:1px solid " + borde + ";"
            " border-radius:10px; }")
        lay = QVBoxLayout(f)

        icono = _TIPO_ICONO.get(d["tipo"], "🎚")
        cab = QLabel(f"{icono}  {d['nombre']}   "
                     f"<span style='color:#54687c'>· {d['tipo']} · crest {d['crest_db']} dB</span>")
        cab.setTextFormat(Qt.RichText)
        cab.setStyleSheet("border:none; color:#e6eef6; font-family: Consolas; font-size: 13px; font-weight: bold;")
        lay.addWidget(cab)

        for ic, txt in d["observaciones"]:
            color = "#f0b447" if ic == "⚠" else "#8598ab"
            o = QLabel(f"{ic}  {txt}")
            o.setWordWrap(True)
            o.setStyleSheet(f"border:none; color:{color}; font-family: Consolas; font-size: 12px; padding-left: 6px;")
            lay.addWidget(o)
        return f
