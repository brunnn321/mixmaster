"""Gestión de proyectos de canción: crear, abrir, estructura de carpetas.

Layout nuevo (v0.4, simple):
    proyecto/
      entrada/          ← mezcla y referencias
      entrada/stems/    ← stems exportados del DAW
      salida/           ← masters WAV/MP3 y stems nivelados
      analisis/         ← diagnósticos y reportes
      decisiones-y-feedback.md

Los proyectos viejos (01_originales … 07_entregables) siguen abriendo:
las propiedades resuelven la carpeta correcta según el layout detectado.
"""

import json
import re
from pathlib import Path

from .logger import get_logger

log = get_logger("mixmaster.project")

DECISIONES_MD = "decisiones-y-feedback.md"
CONFIG_PROYECTO_JSON = "config-proyecto.json"

CABECERA_DECISIONES = """# Decisiones y feedback — {nombre}

> Registro de decisiones tomadas con el asistente. Formato:
> [TIMESTAMP] Versión | Canción | Decisión | Feedback

"""


def nombre_seguro(nombre: str) -> str:
    """Convierte un nombre de canción en nombre de carpeta válido en Windows."""
    limpio = re.sub(r'[<>:"/\\|?*]', "", nombre).strip()
    limpio = re.sub(r"\s+", "_", limpio)
    return limpio or "proyecto_sin_nombre"


class Project:
    """Un proyecto de canción; resuelve rutas para layout nuevo y viejo."""

    def __init__(self, root: Path):
        self.root = Path(root)

    @property
    def nombre(self) -> str:
        return self.root.name

    @property
    def es_layout_viejo(self) -> bool:
        """True si el proyecto usa las carpetas numeradas de v0.1–v0.3."""
        return (self.root / "01_originales").is_dir() and not (self.root / "entrada").is_dir()

    def _ruta(self, nueva: str, vieja: str) -> Path:
        return self.root / (vieja if self.es_layout_viejo else nueva)

    @property
    def dir_originales(self) -> Path:
        """Donde vive la mezcla (entrada/ o 01_originales/)."""
        return self._ruta("entrada", "01_originales")

    @property
    def dir_stems(self) -> Path:
        return self._ruta("entrada/stems", "02_stems")

    @property
    def dir_referencias(self) -> Path:
        return self._ruta("entrada", "03_referencias")

    @property
    def dir_analisis(self) -> Path:
        return self._ruta("analisis", "04_analisis")

    @property
    def dir_stems_niveladas(self) -> Path:
        return self._ruta("salida/stems_niveladas", "05_mezclas_revision/stems_niveladas")

    @property
    def dir_masters(self) -> Path:
        return self._ruta("salida", "06_masters")

    @property
    def dir_entregables(self) -> Path:
        return self._ruta("salida", "07_entregables")

    @property
    def decisiones_path(self) -> Path:
        return self.root / DECISIONES_MD

    # ------------------------------------------------ config del proyecto

    @property
    def config_path(self) -> Path:
        """Ajustes propios de ESTE proyecto (ej. la carpeta de bounces del DAW)."""
        return self.root / CONFIG_PROYECTO_JSON

    def leer_config(self) -> dict:
        """Config del proyecto; {} si no existe o está corrupta."""
        if not self.config_path.exists():
            return {}
        try:
            return json.loads(self.config_path.read_text(encoding="utf-8"))
        except Exception:
            log.exception("Config de proyecto ilegible: %s", self.config_path)
            return {}

    def set_config(self, clave: str, valor) -> None:
        """Setea y persiste un valor en la config del proyecto."""
        cfg = self.leer_config()
        cfg[clave] = valor
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            self.config_path.write_text(
                json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            log.exception("No se pudo guardar la config del proyecto")

    @property
    def carpeta_daw(self) -> Path | None:
        """Carpeta de exportación del DAW vigilada para este proyecto."""
        ruta = self.leer_config().get("carpeta_daw")
        return Path(ruta) if ruta else None

    def es_valido(self) -> bool:
        """Un proyecto es válido si existe su carpeta de análisis (cualquier layout)."""
        return self.root.is_dir() and self.dir_analisis.is_dir()

    def ultimo_diagnostico(self) -> Path | None:
        """Devuelve el diagnostico_*.json más reciente, o None."""
        if not self.dir_analisis.is_dir():
            return None
        candidatos = sorted(
            self.dir_analisis.glob("diagnostico*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        return candidatos[0] if candidatos else None

    def listar_masters(self) -> list[Path]:
        """Masters WAV generados (salida/), del más nuevo al más viejo."""
        d = self.dir_masters
        if not d.is_dir():
            return []
        return sorted(d.glob("master_*.wav"),
                      key=lambda p: p.stat().st_mtime, reverse=True)


def crear_proyecto(base: Path, nombre: str) -> Project:
    """Crea el proyecto vacío. Las subcarpetas se crean solo al escribir en
    ellas (nada de carpetas vacías): entrada/stems al copiar stems, analisis/
    al guardar diagnóstico, salida/ al masterizar."""
    root = Path(base) / nombre_seguro(nombre)
    root.mkdir(parents=True, exist_ok=True)

    # Único contenido garantizado: el registro de decisiones.
    decisiones = root / DECISIONES_MD
    if not decisiones.exists():
        decisiones.write_text(CABECERA_DECISIONES.format(nombre=nombre), encoding="utf-8")

    log.info("Proyecto creado: %s (subcarpetas on-demand)", root)
    return Project(root)


def abrir_proyecto(root: Path) -> Project:
    """Abre un proyecto existente. Las subcarpetas se crean al escribir en ellas."""
    proyecto = Project(root)
    if not proyecto.root.is_dir():
        raise FileNotFoundError(f"No existe la carpeta de proyecto: {root}")
    if proyecto.es_layout_viejo:
        log.info("Proyecto con layout v0.1 (carpetas numeradas): %s", root)
    log.info("Proyecto abierto: %s", root)
    return proyecto
