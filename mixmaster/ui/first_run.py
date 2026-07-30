"""Configuración inicial (primera ejecución): carpeta de proyectos y perfil."""

from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox, QWidget

from ..app_paths import PERFILES_DIR
from ..logger import get_logger
from ..profiles import asegurar_perfiles_default, listar_perfiles_usuario
from ..settings import Settings

log = get_logger("mixmaster.first_run")


def ejecutar_primera_configuracion(parent: QWidget, settings: Settings) -> None:
    """Asistente simple de primera ejecución. Todo tiene default seguro."""
    QMessageBox.information(
        parent, "Bienvenido a MixMaster",
        "Primera ejecución: vamos a configurar lo básico.\n\n"
        "1) Dónde guardar los proyectos\n"
        "2) Perfil de usuario",
    )

    # 1) Ruta de proyectos
    ruta = QFileDialog.getExistingDirectory(
        parent, "Elige la carpeta donde guardar los proyectos",
        settings.get("ruta_proyectos"),
    )
    if ruta:
        settings.set("ruta_proyectos", ruta)
    Path(settings.get("ruta_proyectos")).mkdir(parents=True, exist_ok=True)

    # 2) Perfil de usuario
    asegurar_perfiles_default()

    perfiles = [p.stem for p in listar_perfiles_usuario()] or ["bruno"]
    quien, ok = QInputDialog.getItem(
        parent, "Perfil de usuario",
        "¿Quién usa esta instalación?\n(equipo, sala y nivel de explicación propios)",
        perfiles, perfiles.index("bruno") if "bruno" in perfiles else 0, False)
    if ok and quien:
        settings.set("perfil_usuario", str(PERFILES_DIR / f"{quien}.md"))

    settings.set("primera_ejecucion", False)
    QMessageBox.information(parent, "Listo", "Configuración inicial completada.")
