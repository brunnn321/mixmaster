"""Configuración inicial (primera ejecución): ruta, modo API/manual, perfil."""

from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox, QWidget

from ..app_paths import PERFILES_DIR
from ..logger import get_logger
from ..profiles import asegurar_perfiles_default, listar_generos, listar_perfiles_usuario
from ..settings import Settings

log = get_logger("mixmaster.first_run")


def ejecutar_primera_configuracion(parent: QWidget, settings: Settings) -> None:
    """Asistente simple de primera ejecución. Todo tiene default seguro."""
    QMessageBox.information(
        parent, "Bienvenido a MixMaster",
        "Primera ejecución: vamos a configurar lo básico.\n\n"
        "1) Dónde guardar los proyectos\n"
        "2) Modo de conexión con Claude (API o manual)\n"
        "3) Perfil de usuario y género de trabajo",
    )

    # 1) Ruta de proyectos
    ruta = QFileDialog.getExistingDirectory(
        parent, "Elige la carpeta donde guardar los proyectos",
        settings.get("ruta_proyectos"),
    )
    if ruta:
        settings.set("ruta_proyectos", ruta)
    Path(settings.get("ruta_proyectos")).mkdir(parents=True, exist_ok=True)

    # 2) Modo de conexión
    usar_api = QMessageBox.question(
        parent, "Conexión con Claude",
        "¿Usar la API de Anthropic?\n\n"
        "Sí → las consultas se envían automáticamente (requiere API key).\n"
        "No → modo manual: botón 'Copiar contexto' para pegar en claude.ai (costo cero).",
        QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
    )
    if usar_api == QMessageBox.Yes:
        settings.set("modo", "api")
        key, ok = QInputDialog.getText(
            parent, "API key",
            "Pega tu API key de Anthropic (console.anthropic.com).\n"
            "Se guarda en config/settings.json, nunca en el código:",
        )
        if ok and key.strip():
            settings.set("api_key", key.strip())
        else:
            QMessageBox.information(
                parent, "Sin API key",
                "Sin key la app queda en modo manual. Puedes añadirla luego en Settings.",
            )
            settings.set("modo", "manual")
    else:
        settings.set("modo", "manual")

    # 3) Perfil de usuario + género inicial
    asegurar_perfiles_default()

    perfiles = [p.stem for p in listar_perfiles_usuario()] or ["bruno"]
    quien, ok = QInputDialog.getItem(
        parent, "Perfil de usuario",
        "¿Quién usa esta instalación?\n(equipo, sala y nivel de explicación propios)",
        perfiles, perfiles.index("bruno") if "bruno" in perfiles else 0, False)
    if ok and quien:
        settings.set("perfil_usuario", str(PERFILES_DIR / f"{quien}.md"))

    generos = listar_generos() or ["math_rock"]
    genero, ok = QInputDialog.getItem(
        parent, "Género de trabajo",
        "Género inicial (define referencias y umbrales de alertas;\n"
        "puedes cambiarlo en Settings o crear más en config/generos/):",
        generos, generos.index("math_rock") if "math_rock" in generos else 0, False)
    if ok and genero:
        settings.set("genero_activo", genero)

    settings.set("primera_ejecucion", False)
    QMessageBox.information(parent, "Listo", "Configuración inicial completada.")
