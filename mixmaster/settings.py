"""Carga y guardado de config/settings.json."""

import json
from pathlib import Path

from .app_paths import SETTINGS_FILE, PERFILES_DIR, APP_ROOT, ensure_app_dirs
from .logger import get_logger
from .profiles import asegurar_perfiles_default, leer_genero

log = get_logger("mixmaster.settings")

DEFAULTS = {
    "ruta_proyectos": str(APP_ROOT / "proyectos"),
    "perfil_usuario": str(PERFILES_DIR / "bruno.md"),
    "genero_activo": "math_rock",
    "primera_ejecucion": True,
    "ultimo_proyecto": "",
}


class Settings:
    """Acceso tipo diccionario a settings.json, con defaults y autoguardado."""

    def __init__(self):
        ensure_app_dirs()
        asegurar_perfiles_default()
        self.data = dict(DEFAULTS)
        self.load()

    def load(self) -> None:
        """Lee settings.json si existe; ante error usa defaults y loguea."""
        if SETTINGS_FILE.exists():
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    self.data.update(json.load(f))
            except Exception:
                log.exception("No se pudo leer settings.json; se usan defaults")

    def save(self) -> None:
        """Escribe settings.json de forma legible."""
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
        except Exception:
            log.exception("No se pudo guardar settings.json")

    def get(self, key, default=None):
        """Devuelve un valor de configuración."""
        return self.data.get(key, default)

    def set(self, key, value) -> None:
        """Setea y persiste un valor de configuración."""
        self.data[key] = value
        self.save()

    @property
    def ruta_proyectos(self) -> Path:
        return Path(self.data["ruta_proyectos"])

    @property
    def ruta_perfil_usuario(self) -> Path:
        return Path(self.data["perfil_usuario"])

    def leer_perfil_usuario(self) -> str:
        """Devuelve el texto del perfil de usuario, o aviso si falta."""
        try:
            return self.ruta_perfil_usuario.read_text(encoding="utf-8")
        except Exception:
            log.warning("Perfil de usuario no encontrado en %s", self.ruta_perfil_usuario)
            return "(Perfil de usuario no configurado)"

    def genero_activo(self) -> str:
        """Nombre del género activo (ej. 'math_rock')."""
        return self.data.get("genero_activo", "math_rock")

    def leer_genero_activo(self) -> tuple[str, dict]:
        """Devuelve (texto_md, umbrales) del género activo."""
        return leer_genero(self.genero_activo())
