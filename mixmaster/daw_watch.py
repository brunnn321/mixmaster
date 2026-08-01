"""Detección de bounces nuevos en la carpeta de exportación del DAW.

Lógica pura (sin Qt) para poder testearla sin levantar la UI. El cableado
al timer y al aviso de la ventana vive en `ui/main_window.py`.

El problema real que resuelve: el DAW escribe el archivo DE A POCO. Si se
carga apenas aparece en el directorio, se lee un WAV incompleto (o de 0
bytes) y el análisis sale mal o revienta. Por eso un archivo nuevo no se
reporta hasta que su tamaño se mantiene igual entre dos revisiones
seguidas — recién ahí se asume que el DAW terminó de escribirlo.
"""

from pathlib import Path

from .logger import get_logger

log = get_logger("mixmaster.daw_watch")

EXTS_BOUNCE = (".wav", ".mp3", ".flac", ".aiff", ".aif")


def listar_audios(carpeta: Path) -> dict[str, int]:
    """Devuelve {nombre: tamaño_en_bytes} de los audios de la carpeta.

    Si la carpeta no existe o no se puede leer, devuelve {} (no explota:
    el usuario puede haber desconectado un disco o borrado la carpeta).
    """
    carpeta = Path(carpeta)
    if not carpeta.is_dir():
        return {}
    encontrados = {}
    try:
        for p in carpeta.iterdir():
            if p.is_file() and p.suffix.lower() in EXTS_BOUNCE:
                try:
                    encontrados[p.name] = p.stat().st_size
                except OSError:
                    continue  # archivo justo borrado/bloqueado: se ve en la próxima
    except OSError:
        log.warning("No se pudo leer la carpeta vigilada: %s", carpeta)
    return encontrados


class DetectorBounces:
    """Vigila una carpeta y avisa de audios nuevos ya terminados de escribir.

    Uso: crear apuntando a la carpeta (lo que ya existe se toma como
    "conocido", no se reporta) y llamar a `revisar()` cada 1-2 segundos.
    """

    def __init__(self, carpeta: Path):
        self.carpeta = Path(carpeta)
        # lo que ya estaba al empezar a vigilar NO es un bounce nuevo
        self.conocidos: set[str] = set(listar_audios(self.carpeta))
        self._en_curso: dict[str, int] = {}   # nombre → tamaño de la revisión anterior

    def revisar(self) -> list[Path]:
        """Devuelve los bounces nuevos que ya están completos.

        Un archivo se reporta recién cuando su tamaño no cambió respecto de
        la revisión anterior y es > 0 — señal de que el DAW terminó.
        """
        actuales = listar_audios(self.carpeta)

        # si un archivo desapareció, dejar de considerarlo conocido: si el
        # usuario lo re-exporta con el mismo nombre, tiene que volver a avisar
        self.conocidos &= set(actuales)
        self._en_curso = {n: t for n, t in self._en_curso.items() if n in actuales}

        listos = []
        for nombre, tamano in actuales.items():
            if nombre in self.conocidos:
                continue
            previo = self._en_curso.get(nombre)
            if previo is not None and previo == tamano and tamano > 0:
                self.conocidos.add(nombre)
                self._en_curso.pop(nombre, None)
                listos.append(self.carpeta / nombre)
                log.info("Bounce nuevo detectado: %s (%d bytes)", nombre, tamano)
            else:
                self._en_curso[nombre] = tamano  # todavía escribiéndose
        return listos

    def cambiar_carpeta(self, carpeta: Path) -> None:
        """Apunta a otra carpeta y reinicia el estado."""
        self.carpeta = Path(carpeta)
        self.conocidos = set(listar_audios(self.carpeta))
        self._en_curso = {}
