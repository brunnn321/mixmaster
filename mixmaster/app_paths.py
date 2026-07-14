"""Rutas base de la aplicación (config, logs) y utilidades de disco."""

from pathlib import Path

# Raíz de la app = carpeta que contiene main.py (MixMaster/)
APP_ROOT = Path(__file__).resolve().parent.parent

CONFIG_DIR = APP_ROOT / "config"
LOGS_DIR = APP_ROOT / "logs"

SETTINGS_FILE = CONFIG_DIR / "settings.json"
PERFIL_FILE = CONFIG_DIR / "perfil_bruno.md"  # perfil antiguo (v0.1), se conserva
PERFILES_DIR = CONFIG_DIR / "perfiles"        # perfiles de usuario (v0.1.1)
GENEROS_DIR = CONFIG_DIR / "generos"          # presets de género (v0.1.1)
LOG_FILE = LOGS_DIR / "app.log"


def ensure_app_dirs() -> None:
    """Crea las carpetas config/, perfiles/, generos/ y logs/ si no existen."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    PERFILES_DIR.mkdir(parents=True, exist_ok=True)
    GENEROS_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
