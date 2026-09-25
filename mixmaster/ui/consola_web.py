"""Interfaz MM-01: el mockup aprobado, como ventana real de la app.

Bruno aprobó un diseño en HTML (mockup_hardware_v5, 4/9/2026: panel metálico
petróleo, laterales de madera, carretes de cinta, VU crema) y los intentos de
reproducirlo con QPainter/QSS nunca se le parecieron. Acá no se reproduce: se
USA el mismo HTML (ui/web/consola.html) dentro de un QWebEngineView, y un
QWebChannel lo conecta al motor de siempre.

La ventana clásica (MainWindow) se crea oculta y sirve de motor para lo que ya
existe: carga de audio y proyectos, diálogos de herramientas. Así no se
reescribe nada que ya funciona y la interfaz anterior sigue disponible.
"""

import json
import re
from pathlib import Path

from PySide6.QtCore import QObject, QUrl, Slot
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QFileDialog, QMainWindow

from ..learning import preferencias, registrar_aprobado, registrar_rechazado
from ..logger import get_logger
from ..processing import cargar_config_master
from ..project import abrir_proyecto, crear_proyecto, nombre_seguro
from .main_window import MainWindow, MasterWorker, ParecidasWorker

log = get_logger("mixmaster.ui.consola")

HTML = Path(__file__).parent / "web" / "consola.html"
FORMATOS = "Audio (*.wav *.mp3 *.flac *.aiff *.aif *.ogg *.m4a *.wma)"
FORMATOS_STEM = (".wav", ".flac", ".aiff", ".aif")


class Puente(QObject):
    """Lo que el HTML puede pedirle a Python (window.puente en JS)."""

    def __init__(self, consola: "ConsolaWeb"):
        super().__init__(consola)
        self.c = consola

    @Slot()
    def listo(self):
        self.c.enviar_inicio()

    @Slot()
    def cargarMezcla(self):
        self.c.cargar_mezcla()

    @Slot()
    def cargarStems(self):
        self.c.cargar_stems()

    @Slot()
    def elegirReferencia(self):
        self.c.elegir_referencia()

    @Slot(str)
    def usarReferencia(self, ruta):
        self.c.usar_referencia(ruta)

    @Slot()
    def quitarReferencia(self):
        self.c.quitar_referencia()

    @Slot(float)
    def masterizar(self, target):
        self.c.masterizar(target)

    @Slot(bool)
    def votar(self, bueno):
        self.c.votar(bueno)

    @Slot()
    def abrirSalida(self):
        self.c.abrir_salida()

    @Slot(str)
    def abrirHerramienta(self, nombre):
        self.c.abrir_herramienta(nombre)


class ConsolaWeb(QMainWindow):
    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self.setWindowTitle("MixMaster — MM-01")
        icono = Path(__file__).resolve().parents[2] / "assets" / "icon.ico"
        if icono.exists():
            self.setWindowIcon(QIcon(str(icono)))

        # Motor: la ventana clásica, oculta. Guarda proyecto, fuente y
        # referencia, y abre los diálogos de herramientas tal como siempre.
        self.clasica = MainWindow(settings)

        self.carpeta_stems: Path | None = None
        self.referencia: Path | None = None
        self.distancias: dict[str, float] = {}   # ruta -> distancia de las sugeridas
        self.ultimo: dict | None = None
        self._worker = None
        self._parecidas = None

        self.vista = QWebEngineView(self)
        self.vista.page().setBackgroundColor(QColor("#060606"))  # sin destello blanco
        self.canal = QWebChannel(self.vista.page())
        self.puente = Puente(self)
        self.canal.registerObject("puente", self.puente)
        self.vista.page().setWebChannel(self.canal)
        self.vista.load(QUrl.fromLocalFile(str(HTML)))
        self.setCentralWidget(self.vista)

    # ------------------------------------------------------------ utilidades

    def js(self, funcion: str, *args):
        """Llama a MM.<funcion>(...) en la página."""
        params = ", ".join(json.dumps(a, ensure_ascii=False, default=str) for a in args)
        self.vista.page().runJavaScript(f"MM.{funcion}({params})")

    @property
    def genero(self) -> str:
        return self.settings.genero_activo()

    def _target_default(self) -> float:
        pref = preferencias(self.genero) or {}
        if pref.get("target_lufs") is not None:
            return float(pref["target_lufs"])
        return float(cargar_config_master(self.genero).get("target_lufs_default", -9.0))

    def enviar_inicio(self):
        from ..loudness_targets import TARGETS_PLATAFORMA
        destinos = [{"nombre": re.sub(r"\s*\(.*\)$", "", n).upper(), "lufs": d["lufs"]}
                    for n, d in TARGETS_PLATAFORMA.items()]
        proyecto = self.clasica.proyecto.nombre if self.clasica.proyecto else None
        self.js("init", {"target": self._target_default(), "destinos": destinos,
                         "proyecto": proyecto,
                         "mensaje": f"Género activo: {self.genero}. Carga una mezcla o una carpeta de stems."})

    # ------------------------------------------------------------ 01 fuente

    def cargar_mezcla(self):
        ruta, _ = QFileDialog.getOpenFileName(self, "Cargar mezcla", "", FORMATOS)
        if not ruta:
            return
        # La clásica crea o reabre el proyecto y pregunta si es música o voz.
        self.clasica._cargar_audio_desde_path(ruta)
        if not self.clasica.wav_activo:
            return
        self.carpeta_stems = None
        self.referencia = None
        archivo = Path(self.clasica.wav_activo)
        self.js("fuente", {"titulo": archivo.stem.upper(), "detalle": self._detalle(archivo),
                           "proyecto": self.clasica.proyecto.nombre})
        self.js("referencia", None)
        # la clásica ya arrancó la búsqueda de parecidas al cargar: se reusa
        w = getattr(self.clasica, "_parecidas_worker", None)
        if w is not None and w.isRunning() and w.wav == str(archivo):
            self.js("parecidas", None)
            w.terminado.connect(self._parecidas_listas)
        else:
            self._buscar_parecidas(archivo)

    def cargar_stems(self):
        carpeta = QFileDialog.getExistingDirectory(self, "Carpeta de stems")
        if not carpeta:
            return
        carpeta = Path(carpeta)
        stems = [p for p in carpeta.iterdir() if p.suffix.lower() in FORMATOS_STEM]
        if not stems:
            self.js("error", "Esa carpeta no tiene stems WAV/FLAC/AIFF.")
            return
        try:
            base = self.settings.ruta_proyectos
            base.mkdir(parents=True, exist_ok=True)
            destino = base / nombre_seguro(carpeta.name)
            proyecto = abrir_proyecto(destino) if destino.is_dir() else crear_proyecto(base, carpeta.name)
            self.clasica._set_proyecto(proyecto)
        except Exception as e:
            log.exception("No se pudo crear el proyecto para los stems")
            self.js("error", f"No se pudo crear el proyecto: {e}")
            return
        self.carpeta_stems = carpeta
        self.referencia = None
        guitarras = [p for p in stems if any(k in p.name.lower() for k in ("gtr", "guit"))]
        self.js("fuente", {
            "titulo": f"{len(stems)} STEMS CARGADOS",
            "detalle": f"{carpeta.name} · {self._detalle(stems[0], corto=True)} · "
                       f"{len(guitarras)} de guitarra",
            "proyecto": proyecto.nombre})
        self.js("referencia", None)
        self.js("parecidas", [])  # sin mezcla única no hay con qué comparar

    @staticmethod
    def _detalle(archivo: Path, corto: bool = False) -> str:
        try:
            import soundfile as sf
            info = sf.info(str(archivo))
            bits = {"PCM_16": "16bit", "PCM_24": "24bit", "PCM_32": "32bit", "FLOAT": "32bit float"}
            partes = [f"{info.samplerate / 1000:g}kHz/{bits.get(info.subtype, info.subtype)}"]
            if not corto:
                m, s = divmod(int(info.duration), 60)
                partes.insert(0, archivo.suffix.upper().lstrip("."))
                partes.append(f"{m}:{s:02d}")
            return " · ".join(partes)
        except Exception:
            return archivo.suffix.upper().lstrip(".")

    def _buscar_parecidas(self, archivo: Path):
        self.js("parecidas", None)
        self._parecidas = ParecidasWorker(archivo)
        self._parecidas.setParent(self)
        self._parecidas.terminado.connect(self._parecidas_listas)
        self._parecidas.start()

    def _parecidas_listas(self, wav: str, lista: list):
        if not self.clasica.wav_activo or str(self.clasica.wav_activo) != wav:
            return
        self.distancias = {c["ruta"]: c["distancia_db"] for c in lista}
        self.js("parecidas", lista)

    # ------------------------------------------------------------ 02 referencia

    def elegir_referencia(self):
        ruta, _ = QFileDialog.getOpenFileName(self, "Elegir referencia", "", FORMATOS)
        if ruta:
            self.usar_referencia(ruta)

    def usar_referencia(self, ruta: str):
        self.referencia = Path(ruta)
        self.clasica.referencia = [self.referencia]
        self.js("referencia", {"nombre": self.referencia.name,
                               "distancia": self.distancias.get(str(self.referencia))})

    def quitar_referencia(self):
        self.referencia = None
        self.clasica.referencia = None
        self.js("referencia", None)

    # ------------------------------------------------------------ 03 master

    def _siguiente_version(self) -> str:
        dir_m = self.clasica.proyecto.dir_masters
        nums = [int(m.group(1)) for p in dir_m.glob("master_v*")
                if (m := re.match(r"master_v(\d+)_", p.name))] if dir_m.is_dir() else []
        return f"V{(max(nums) + 1) if nums else 1:02d}"

    def masterizar(self, target: float):
        if self._worker and self._worker.isRunning():
            return
        proyecto = self.clasica.proyecto
        mezcla = self.clasica.wav_activo if not self.carpeta_stems else None
        if not proyecto or (not mezcla and not self.carpeta_stems):
            self.js("error", "Primero carga una mezcla o una carpeta de stems (01 · Fuente).")
            return
        if not self.referencia:
            self.js("aviso", "Sin referencia: el master sale sin EQ de matching. "
                             "Puedes elegir una en 02 · Referencias.")
        self.ultimo = None
        self.js("ocupado", True, "Preparando…")
        self._worker = MasterWorker(
            mezcla, [self.referencia] if self.referencia else None, float(target),
            proyecto.dir_masters, proyecto.dir_entregables, self._siguiente_version(),
            self.carpeta_stems, self.genero)
        self._worker.setParent(self)
        self._worker.progreso.connect(lambda m: self.js("progreso", m))
        self._worker.terminado.connect(self._master_ok)
        self._worker.fallo.connect(self._master_error)
        self._worker.start()

    def _master_ok(self, resumen: dict):
        self.ultimo = resumen
        datos = dict(resumen)
        datos["eq_tope_db"] = cargar_config_master(self.genero)["eq_correctivo"].get("max_correccion_db")
        self.js("resultado", datos)
        log.info("Master MM-01 listo: %s", resumen.get("wav"))

    def _master_error(self, msg: str):
        log.error("Master MM-01 falló: %s", msg)
        self.js("error", f"El master falló: {msg}")

    def votar(self, bueno: bool):
        if not self.ultimo:
            return
        try:
            n = (registrar_aprobado if bueno else registrar_rechazado)(self.genero, self.ultimo)
            self.js("votado", f"Voto guardado ({'me gusta' if bueno else 'no me gusta'}). "
                              f"La app ya aprendió de {n} master(s) de {self.genero}.")
        except Exception as e:
            log.exception("No se pudo registrar el voto")
            self.js("error", f"No se pudo guardar el voto: {e}")

    def abrir_salida(self):
        if self.ultimo and self.ultimo.get("wav"):
            from .abrir import mostrar_en_carpeta
            mostrar_en_carpeta(self.ultimo["wav"])

    # ------------------------------------------------------------ 04 herramientas

    def abrir_herramienta(self, nombre: str):
        if nombre == "clasica":
            self.clasica.showMaximized()
            self.clasica.raise_()
            return
        metodos = {
            "historial": "_abrir_historial", "masters": "_abrir_masters",
            "notas": "_abrir_notas", "null": "_abrir_null_test",
            "ab": "_abrir_ab_ciego", "coaching": "_abrir_coaching",
            "convertidor": "_abrir_convertidor", "settings": "_abrir_settings",
        }
        metodo = getattr(self.clasica, metodos.get(nombre, ""), None)
        if metodo is None:
            self.js("error", f"Herramienta desconocida: {nombre}")
            return
        try:
            metodo()
        except Exception as e:
            log.exception("Falló la herramienta %s", nombre)
            self.js("error", f"No se pudo abrir {nombre}: {e}")
        if nombre == "settings":
            self.enviar_inicio()  # el género o el target pueden haber cambiado

    def closeEvent(self, event):
        self.clasica.close()
        super().closeEvent(event)
