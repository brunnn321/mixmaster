"""Tempo Genius: pone temas a tempo fijo y entrega un click exacto.

Acepta stems de Moises, una multipista o un solo audio, y varios temas en cola.
Llama a tempo/stems_fix.py como proceso aparte: el módulo de tempo no depende de
MixMaster. Al terminar se escucha la mezcla con el click; si el "1" quedó corrido,
se mueve un tiempo y ese tema se vuelve a procesar.
"""

import json
import re
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import soundfile as sf
from PySide6.QtCore import QProcess, QProcessEnvironment, QSettings, Qt, QTimer, QUrl
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QHBoxLayout,
    QLabel, QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton, QVBoxLayout,
)

from ..logger import get_logger

log = get_logger("mixmaster.ui.tempo")

SCRIPT = Path(__file__).resolve().parents[2] / "tempo" / "stems_fix.py"
SCRIPT_MIDI = SCRIPT.with_name("transcribir_midi.py")
ENV_MIDI = SCRIPT.parent / ".muscriptor" / "Scripts" / "python.exe"   # MuScriptor pide Python 3.12
RE_BPM = re.compile(r"(\d+(?:\.\d+)?)bpm", re.I)
RE_TEMA = re.compile(r"^(.*)-[A-G][b#]? (major|minor)-")
ESCUCHA = Path(tempfile.gettempdir()) / "mixmaster_tempo_escucha.wav"
AUDIO = (".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aiff", ".aif", ".wma", ".aac", ".mp4")
COMPASES = (("4/4", 4), ("3/4", 3), ("2/4", 2), ("5/4", 5), ("6 pulsos", 6), ("7 pulsos", 7),
            ("Solo pulso", 0))
ESTILO_BOTON = (
    "QPushButton { font-weight: 800; font-size: 16px; letter-spacing: 2px; color: white;"
    " border-radius: 10px; border: 1px solid #4fa76a;"
    " background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #4aa06a, stop:1 #2c6b46); }"
    " QPushButton:hover { background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #55b478, stop:1 #337a50); }"
    " QPushButton:pressed { background: #2a5f3e; }"
    " QPushButton:disabled { background: #2a3b31; color: #6f8579; border-color: #33463b; }")


def nombre_tema(ruta: Path) -> str:
    nombre = ruta.stem if ruta.is_file() else ruta.name
    m = RE_TEMA.match(nombre)
    return m.group(1).strip() if m else nombre


class TempoDialog(QDialog):
    """Cola de temas → PONER A TEMPO → escuchar con el click → mover el "1" si hace falta."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("⏱ Tempo Genius")
        self.resize(820, 680)
        self.setAcceptDrops(True)
        self._temas = []          # dicts: ruta, bpm (None = detectar), compas, enderezar, estado, salida, info
        self._proc = None
        self._actual = None       # tema que se está procesando
        self._cola = []
        self._ajustes = QSettings("MixMaster", "TempoGenius")

        self._player = QMediaPlayer(self)
        self._audio_out = QAudioOutput(self)
        self._player.setAudioOutput(self._audio_out)

        lay = QVBoxLayout(self)

        fila_agregar = QHBoxLayout()
        btn_carpeta = QPushButton("📁 Agregar carpeta…")
        btn_carpeta.setToolTip("Stems de Moises o una multipista (una carpeta por tema).")
        btn_carpeta.clicked.connect(self._agregar_carpeta)
        btn_audios = QPushButton("🎵 Agregar audios…")
        btn_audios.setToolTip("Uno o varios temas sin stems (MP3, WAV…): la batería se separa con Demucs.")
        btn_audios.clicked.connect(self._agregar_audios)
        btn_quitar = QPushButton("Quitar")
        btn_quitar.clicked.connect(self._quitar)
        for b in (btn_carpeta, btn_audios, btn_quitar):
            fila_agregar.addWidget(b)
        fila_agregar.addStretch()
        lay.addLayout(fila_agregar)

        self.lista = QListWidget()
        self.lista.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.lista.setAcceptDrops(False)   # el drop lo maneja la ventana entera
        self.lista.itemSelectionChanged.connect(self._seleccion)
        lay.addWidget(self.lista, 2)

        fila_op = QHBoxLayout()
        fila_op.addWidget(QLabel("BPM:"))
        self.spin_bpm = QDoubleSpinBox()
        self.spin_bpm.setRange(30, 300)
        self.spin_bpm.setDecimals(2)
        self.spin_bpm.setValue(120)
        self.spin_bpm.valueChanged.connect(self._opciones_cambiaron)
        fila_op.addWidget(self.spin_bpm)
        self.chk_auto = QCheckBox("Detectar")
        self.chk_auto.setToolTip("Detecta el BPM con los pulsos del tema (cuando el nombre no lo trae).")
        self.chk_auto.toggled.connect(self._opciones_cambiaron)
        fila_op.addWidget(self.chk_auto)
        fila_op.addWidget(QLabel("Compás:"))
        self.combo_compas = QComboBox()
        for texto, n in COMPASES:
            self.combo_compas.addItem(texto, n)
        self.combo_compas.setToolTip("Solo cambia el acento del click y dónde cae el 1.\n"
                                     "El pulso se ajusta igual en cualquier compás.")
        self.combo_compas.currentIndexChanged.connect(self._opciones_cambiaron)
        fila_op.addWidget(self.combo_compas)
        self.chk_enderezar = QCheckBox("Enderezar todo")
        self.chk_enderezar.setToolTip(
            "También lo que sube o baja de tempo (intro, final, rubatos) queda en el tempo fijo.\n"
            "Apagado: esos tramos quedan naturales y el click los sigue.")
        self.chk_enderezar.toggled.connect(self._opciones_cambiaron)
        fila_op.addWidget(self.chk_enderezar)
        fila_op.addStretch()
        lay.addLayout(fila_op)

        fila_salida = QHBoxLayout()
        self.lbl_salida = QLabel("")
        self.lbl_salida.setStyleSheet("color: #8a9bb5;")
        fila_salida.addWidget(self.lbl_salida, 1)
        btn_salida = QPushButton("Carpeta de salida…")
        btn_salida.setToolTip("Elegir una carpeta fija para todos los resultados.")
        btn_salida.clicked.connect(self._elegir_salida_fija)
        btn_junto = QPushButton("Junto a cada tema")
        btn_junto.clicked.connect(lambda: self._poner_salida_fija(None))
        fila_salida.addWidget(btn_salida)
        fila_salida.addWidget(btn_junto)
        lay.addLayout(fila_salida)
        self._mostrar_salida()

        self.btn_procesar = QPushButton("PONER A TEMPO")
        self.btn_procesar.setCursor(Qt.PointingHandCursor)
        self.btn_procesar.setMinimumHeight(48)
        self.btn_procesar.setStyleSheet(ESTILO_BOTON)
        self.btn_procesar.clicked.connect(self._procesar_cola)
        lay.addWidget(self.btn_procesar)

        self.txt_log = QPlainTextEdit()
        self.txt_log.setReadOnly(True)
        lay.addWidget(self.txt_log, 1)

        self.lbl_resumen = QLabel("Agrega carpetas de stems o audios (también se pueden arrastrar).")
        self.lbl_resumen.setWordWrap(True)
        self.lbl_resumen.setStyleSheet("color: #7fd99a; font-weight: bold;")
        lay.addWidget(self.lbl_resumen)

        fila_escucha = QHBoxLayout()
        self.btn_play = QPushButton("▶ Escuchar con click")
        self.btn_play.clicked.connect(self._toggle_play)
        self.btn_antes = QPushButton("◀ El 1 un tiempo antes")
        self.btn_antes.clicked.connect(lambda: self._mover_uno(-1))
        self.btn_despues = QPushButton("El 1 un tiempo después ▶")
        self.btn_despues.clicked.connect(lambda: self._mover_uno(+1))
        self.btn_abrir = QPushButton("📂 Abrir carpeta")
        self.btn_abrir.clicked.connect(self._abrir_salida)
        self.btn_midi = QPushButton("🎼 MIDI de bajo y voz")
        self.btn_midi.setToolTip("Transcribe con MuScriptor el bajo y la voz ya a tempo:\n"
                                 "«Bajo 128bpm.mid» y «Voz 128bpm.mid» en la misma carpeta.")
        self.btn_midi.clicked.connect(self._transcribir_midi)
        for b in (self.btn_play, self.btn_antes, self.btn_despues, self.btn_abrir, self.btn_midi):
            b.setEnabled(False)
            fila_escucha.addWidget(b)
        lay.addLayout(fila_escucha)
        self._actualizar_boton()

    # ---------- cola ----------

    def _agregar_carpeta(self):
        carpeta = QFileDialog.getExistingDirectory(self, "Carpeta de stems o multipista")
        if carpeta:
            self._agregar([Path(carpeta)])

    def _agregar_audios(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Temas sin stems", "", "Audio (" + " ".join(f"*{e}" for e in AUDIO) + ")")
        self._agregar([Path(p) for p in paths])

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and any(u.isLocalFile() for u in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        self._agregar([Path(u.toLocalFile()) for u in event.mimeData().urls() if u.isLocalFile()])

    def _agregar(self, rutas):
        for ruta in rutas:
            if not (ruta.is_dir() or ruta.suffix.lower() in AUDIO):
                continue
            if any(t["ruta"] == ruta for t in self._temas):
                continue
            m = RE_BPM.search(ruta.stem if ruta.is_file() else ruta.name)
            tema = {"ruta": ruta, "bpm": float(m.group(1)) if m else None,
                    "compas": self.combo_compas.currentData(), "enderezar": self.chk_enderezar.isChecked(),
                    "estado": "pendiente", "salida": None, "info": None}
            self._temas.append(tema)
            item = QListWidgetItem()
            self.lista.addItem(item)
            self._pintar(len(self._temas) - 1)
        if self.lista.count() and not self.lista.selectedItems():
            self.lista.setCurrentRow(self.lista.count() - 1)
        self._actualizar_boton()

    def _quitar(self):
        if self._proc is not None:
            return
        for fila in sorted((self.lista.row(i) for i in self.lista.selectedItems()), reverse=True):
            self.lista.takeItem(fila)
            del self._temas[fila]
        self._actualizar_boton()

    def _pintar(self, i):
        t = self._temas[i]
        bpm = "BPM auto" if t["bpm"] is None else f"{t['bpm']:g} BPM"
        comp = dict((n, x) for x, n in COMPASES)[t["compas"]]
        estado = {"pendiente": "·", "procesando": "⏳", "listo": "✓", "error": "✗"}[t["estado"]]
        detalle = ""
        if t["estado"] == "listo" and t["info"]:
            secs = [abs(v) for v in t["info"].get("verificacion_secciones_32_ms", []) if v is not None]
            detalle = f"  →  ±{max(secs):.1f} ms" if secs else "  →  listo"
            if t["info"].get("avisos"):
                detalle += f" · {len(t['info']['avisos'])} aviso(s)"
        elif t["estado"] == "error":
            detalle = "  →  falló (ver el detalle abajo)"
        extra = " · enderezar todo" if t["enderezar"] else ""
        self.lista.item(i).setText(f"{estado}  {nombre_tema(t['ruta'])}   [{bpm} · {comp}{extra}]{detalle}")

    def _seleccionados(self):
        return sorted(self.lista.row(i) for i in self.lista.selectedItems())

    def _seleccion(self):
        filas = self._seleccionados()
        if not filas:
            return
        t = self._temas[filas[0]]
        for w in (self.spin_bpm, self.chk_auto, self.combo_compas, self.chk_enderezar):
            w.blockSignals(True)
        self.chk_auto.setChecked(t["bpm"] is None)
        self.spin_bpm.setEnabled(t["bpm"] is not None)
        if t["bpm"] is not None:
            self.spin_bpm.setValue(t["bpm"])
        self.combo_compas.setCurrentIndex(self.combo_compas.findData(t["compas"]))
        self.chk_enderezar.setChecked(t["enderezar"])
        for w in (self.spin_bpm, self.chk_auto, self.combo_compas, self.chk_enderezar):
            w.blockSignals(False)
        self._mostrar_resultado(t)

    def _opciones_cambiaron(self, *_):
        self.spin_bpm.setEnabled(not self.chk_auto.isChecked())
        for i in self._seleccionados():
            t = self._temas[i]
            if t["estado"] == "procesando":
                continue
            t["bpm"] = None if self.chk_auto.isChecked() else self.spin_bpm.value()
            t["compas"] = self.combo_compas.currentData()
            t["enderezar"] = self.chk_enderezar.isChecked()
            if t["estado"] == "listo":
                t["estado"] = "pendiente"     # con otras opciones hay que volver a procesarlo
            self._pintar(i)
        self._actualizar_boton()

    def _actualizar_boton(self):
        n = sum(t["estado"] in ("pendiente", "error") for t in self._temas)
        self.btn_procesar.setText(f"PONER A TEMPO ({n})" if n > 1 else "PONER A TEMPO")
        self.btn_procesar.setEnabled(n > 0 and self._proc is None)

    # ---------- carpeta de salida ----------

    def _salida_fija(self):
        v = self._ajustes.value("salida_fija", "")
        return Path(v) if v else None

    def _elegir_salida_fija(self):
        carpeta = QFileDialog.getExistingDirectory(self, "Carpeta de salida para Tempo Genius")
        if carpeta:
            self._poner_salida_fija(Path(carpeta))

    def _poner_salida_fija(self, carpeta):
        self._ajustes.setValue("salida_fija", str(carpeta) if carpeta else "")
        self._mostrar_salida()

    def _mostrar_salida(self):
        fija = self._salida_fija()
        self.lbl_salida.setText(f"Salida: {fija}" if fija else
                                "Salida: carpeta «A TEMPO» junto a cada tema")

    def _carpeta_salida(self, t) -> Path:
        base = self._salida_fija() or t["ruta"].parent / "A TEMPO"
        bpm = "BPM auto" if t["bpm"] is None else f"{t['bpm']:g} BPM"
        destino = base / f"{nombre_tema(t['ruta'])} - {bpm}"
        v = 2
        while destino.exists():            # nunca se pisa un resultado anterior
            destino = base / f"{nombre_tema(t['ruta'])} - {bpm} V{v}"
            v += 1
        return destino

    # ---------- proceso ----------

    def _procesar_cola(self):
        self._cola = [i for i, t in enumerate(self._temas) if t["estado"] in ("pendiente", "error")]
        self._siguiente()

    def _siguiente(self, fase=None, rehacer=None):
        if rehacer is not None:
            i = rehacer
        elif self._cola:
            i = self._cola.pop(0)
        else:
            self._actual = None
            self._actualizar_boton()
            return
        t = self._temas[i]
        self._soltar_audio()
        if rehacer is None or t["salida"] is None:
            t["salida"] = self._carpeta_salida(t)
        args = ["-u", str(SCRIPT), str(t["ruta"]), str(t["salida"]),
                "0" if t["bpm"] is None else f"{t['bpm']:g}", f"--compas={t['compas']}"]
        if t["enderezar"]:
            args.append("--todo-a-tempo")
        if fase is not None:
            args.append(f"--fase={fase}")
        t["estado"] = "procesando"
        self._actual = i
        self._pintar(i)
        self.txt_log.clear()
        self.lbl_resumen.setText(f"Procesando {nombre_tema(t['ruta'])}…")
        for b in (self.btn_procesar, self.btn_play, self.btn_antes, self.btn_despues, self.btn_abrir,
                  self.btn_midi):
            b.setEnabled(False)

        self._proc = QProcess(self)
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONIOENCODING", "utf-8")
        self._proc.setProcessEnvironment(env)
        self._proc.setProcessChannelMode(QProcess.MergedChannels)
        self._proc.readyReadStandardOutput.connect(self._leer_salida)
        self._proc.finished.connect(self._terminado)
        self._proc.start(sys.executable, args)

    def _leer_salida(self):
        texto = bytes(self._proc.readAllStandardOutput()).decode("utf-8", errors="replace")
        self.txt_log.appendPlainText(texto.rstrip())

    def _terminado(self, codigo, _estado):
        self._proc = None
        i = self._actual
        t = self._temas[i]
        info = None
        if codigo == 0:
            try:
                info = json.loads((t["salida"] / "log.json").read_text(encoding="utf-8"))
            except Exception:
                log.exception("No se pudo leer log.json")
        if info is None:
            t["estado"] = "error"
        else:
            t["estado"], t["info"] = "listo", info
            if info.get("bpm_detectado"):
                # la carpeta se nombró "BPM auto": queda con el BPM detectado, y el tema también
                t["bpm"] = float(info["bpm"])
                nueva = t["salida"].with_name(t["salida"].name.replace("BPM auto", f"{info['bpm']:g} BPM"))
                if not nueva.exists():
                    try:
                        t["salida"] = t["salida"].rename(nueva)
                    except OSError:
                        log.exception("No se pudo renombrar la carpeta de salida")
        self._pintar(i)
        if self._seleccionados() == [i] or not self._cola:
            self.lista.setCurrentRow(i)
            self._mostrar_resultado(t)
        self._siguiente()

    def _mostrar_resultado(self, t):
        listo = t["estado"] == "listo" and t["info"] is not None
        for b in (self.btn_play, self.btn_antes, self.btn_despues, self.btn_abrir, self.btn_midi):
            b.setEnabled(False)
        if t["estado"] == "error":
            self.lbl_resumen.setText("Falló: el detalle está en el texto de arriba.")
            return
        if not listo:
            self.lbl_resumen.setText("Pendiente. Ajusta BPM, compás o «Enderezar todo» y pulsa PONER A TEMPO.")
            return
        info = t["info"]
        secs = [abs(v) for v in info.get("verificacion_secciones_32_ms", []) if v is not None]
        partes = [f"{info['bpm']:g} BPM" + (" (detectado)" if info.get("bpm_detectado") else ""),
                  "solo desplazado" if info["modo"] == "estudio" else "estirado",
                  f"peor sección ±{max(secs):.1f} ms" if secs else "sin batería para medir"]
        avisos = "".join(f"\n⚠ {a}" for a in info.get("avisos", []))
        cierre = ("\nEscucha el comienzo: el tono agudo del click debe caer en el 1."
                  if info.get("compas", 4) > 0 else "")
        self.lbl_resumen.setText(" · ".join(partes) + avisos + cierre)
        self.btn_abrir.setEnabled(True)
        self.btn_midi.setEnabled(self._proc is None and ENV_MIDI.exists())
        if self._proc is None:
            self._preparar_escucha(t)
            if info.get("compas", 4) > 0:
                self.btn_antes.setEnabled(True)
                self.btn_despues.setEnabled(True)

    # ---------- escucha ----------

    def _preparar_escucha(self, t):
        """Mezcla y click en un solo archivo, para que no se desfasen al reproducir."""
        self._soltar_audio()
        try:
            mezcla_p = next(t["salida"].glob("Mezcla *bpm.flac"))
            click_p = next(t["salida"].glob("Click *bpm.flac"))
            mezcla, sr = sf.read(str(mezcla_p), dtype="float32", always_2d=True)
            click, _ = sf.read(str(click_p), dtype="float32", always_2d=True)
            n = min(len(mezcla), len(click))
            escucha = np.clip(mezcla[:n] * 0.7 + click[:n, :mezcla.shape[1]] * 0.6, -1, 1)
            sf.write(str(ESCUCHA), escucha, sr, subtype="PCM_16")
        except Exception:
            log.exception("No se pudo preparar la escucha")
            self.lbl_resumen.setText(self.lbl_resumen.text() + "\nNo se pudo preparar la escucha.")
            return
        self._player.setSource(QUrl.fromLocalFile(str(ESCUCHA)))
        self.btn_play.setEnabled(True)

    def _toggle_play(self):
        if self._player.playbackState() == QMediaPlayer.PlayingState:
            self._player.pause()
            self.btn_play.setText("▶ Escuchar con click")
        else:
            self._player.play()
            self.btn_play.setText("⏸ Pausar")

    def _mover_uno(self, delta: int):
        filas = self._seleccionados()
        if len(filas) != 1 or self._proc is not None:
            return
        t = self._temas[filas[0]]
        n = t["compas"]
        if t["info"] is None or n <= 0:
            return
        self._siguiente(fase=(t["info"]["downbeat_fase"] + delta) % n, rehacer=filas[0])

    # ---------- MIDI de bajo y voz (MuScriptor, entorno aparte) ----------

    def _transcribir_midi(self):
        filas = self._seleccionados()
        if len(filas) != 1 or self._proc is not None:
            return
        t = self._temas[filas[0]]
        if t["salida"] is None:
            return
        self._soltar_audio()
        self.txt_log.clear()
        self.lbl_resumen.setText(f"MIDI de bajo y voz de {nombre_tema(t['ruta'])}…")
        for b in (self.btn_procesar, self.btn_play, self.btn_antes, self.btn_despues, self.btn_midi):
            b.setEnabled(False)
        self._proc = QProcess(self)
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONIOENCODING", "utf-8")
        self._proc.setProcessEnvironment(env)
        self._proc.setProcessChannelMode(QProcess.MergedChannels)
        self._proc.readyReadStandardOutput.connect(self._leer_salida_midi)
        self._proc.finished.connect(self._midi_terminado)
        # si pasan 3 minutos sin una línea nueva, se trabó: se corta y se avisa
        self._ultima_linea = time.monotonic()
        self._vigia = QTimer(self)
        self._vigia.timeout.connect(self._vigilar_midi)
        self._vigia.start(5000)
        self._proc.start(str(ENV_MIDI), ["-u", str(SCRIPT_MIDI), str(t["salida"])])

    def _leer_salida_midi(self):
        self._ultima_linea = time.monotonic()
        texto = bytes(self._proc.readAllStandardOutput()).decode("utf-8", errors="replace")
        lineas = [l for l in texto.splitlines() if not l.startswith("[muscriptor]")]
        if lineas:
            self.txt_log.appendPlainText("\n".join(lineas))

    def _vigilar_midi(self):
        if self._proc is not None and time.monotonic() - self._ultima_linea > 180:
            self._trabado = True
            self._proc.kill()

    def _midi_terminado(self, codigo, _estado):
        self._vigia.stop()
        self._proc = None
        trabado = getattr(self, "_trabado", False)
        self._trabado = False
        if trabado:
            self.lbl_resumen.setText("⚠ MuScriptor no avanzó en 3 minutos y se cortó. "
                                     "Si estaba descargando el modelo, revisa la conexión y vuelve a intentar.")
        elif codigo != 0:
            self.lbl_resumen.setText("⚠ El MIDI de bajo y voz falló: el detalle está en el texto de arriba.")
        else:
            self.lbl_resumen.setText("✓ MIDI listo: «Bajo …bpm.mid» y «Voz …bpm.mid» en la carpeta del tema.")
        self._actualizar_boton()
        filas = self._seleccionados()
        if filas:
            t = self._temas[filas[0]]
            self.btn_abrir.setEnabled(t["salida"] is not None)
            self.btn_midi.setEnabled(ENV_MIDI.exists())
            if t["info"] is not None:
                self._preparar_escucha(t)

    def _soltar_audio(self):
        """Libera el archivo de escucha (en Windows queda bloqueado mientras se reproduce)."""
        self._player.stop()
        self._player.setSource(QUrl())
        self.btn_play.setText("▶ Escuchar con click")

    def _abrir_salida(self):
        filas = self._seleccionados()
        if not filas or self._temas[filas[0]]["salida"] is None:
            return
        try:
            from .abrir import mostrar_en_carpeta
            mostrar_en_carpeta(self._temas[filas[0]]["salida"] / "REPORTE.txt")
        except Exception:
            log.exception("No se pudo abrir la carpeta de salida")

    def closeEvent(self, event):
        if self._proc and self._proc.state() != QProcess.NotRunning:
            self._proc.kill()
            self._proc.waitForFinished(2000)
        self._soltar_audio()
        super().closeEvent(event)
