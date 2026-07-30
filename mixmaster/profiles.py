"""Perfiles híbridos: perfil de USUARIO (equipo, sala, nivel) + preset de GÉNERO
(referencias, targets, umbrales de alertas).

Ambos son archivos de texto en config/: portables, editables y "entrenables"
con el feedback de cada canción. Un género se define por un par:
  generos/<nombre>.md    → texto que se envía a Claude
  generos/<nombre>.json  → umbrales numéricos para las alertas automáticas
"""

import json
import re
from datetime import datetime
from pathlib import Path

from .app_paths import GENEROS_DIR, PERFIL_FILE, PERFILES_DIR, ensure_app_dirs
from .logger import get_logger

log = get_logger("mixmaster.profiles")

VERSIONES_DIR = GENEROS_DIR / "versiones"
REFERENCIAS_DIR = GENEROS_DIR / "referencias"

# Mismos formatos que acepta el selector de referencias de la UI
FORMATOS_REFERENCIA = (".wav", ".mp3", ".flac", ".ogg", ".aiff", ".aif")

# Umbrales de alertas si el género no define los suyos (valores v0.1 = math rock)
UMBRALES_DEFAULT = {
    "low_mid_delta_max_db": 2.0,   # delta low-mid vs referencia
    "crest_min_db": 12.0,          # crest factor mínimo
    "sub_min_db": -30.0,           # nivel mínimo de sub-graves
    "correlacion_min": 0.7,        # correlación mínima en mid/high-mid
    "lufs_max": -8.0,              # LUFS integrado máximo para el género
    "nota_low_mid": "revisar acumulación de guitarras en 200–500 Hz",
    "nota_crest": "transientes comprimidos — vigilar",
    "nota_sub": "bajo muy suave para este género",
    "nota_correlacion": "imagen estéreo inestable",
    "nota_lufs": "muy fuerte para math rock — riesgo de fatiga",
}

# ---------------------------------------------------------------- plantillas

PLANTILLA_BRUNO = """# Perfil de usuario — Bruno · v1
> Contexto personal (equipo, sala, gustos). El género activo se elige aparte.

## Nivel de explicación
- Técnico: directo, con valores concretos (dB, Hz, ratios). Sin explicaciones básicas.

## Contexto técnico
- **DAWs**: Studio One Pro, Fender Studio, Ableton Live
- **Plugins habituales**:
  - Guitarras: Neural DSP — Archetype Tim Henson y Archetype Plini (comps, amps, delay, chorus integrados)
  - Compresión de carácter: Shadow Hills Mastering Compressor
  - Brillo/aire: Slate Digital Fresh Air
  - Mix bus: limitador en 0 dB solo como seguridad anti-picos (no para loudness)
- **Monitores**: ADAM Audio D3V (campo cercano, drivers pequeños → punto ciego en sub-graves <50 Hz)
- **Auriculares**: Audio-Technica ATH-M50x (graves algo realzados, medios-altos con pico suave → vigilar decisiones de low-end y brillo tomadas solo en ellos)
- **Interfaz**: Steinberg UR44
- **Sala**: sin tratamiento acústico → reforzar alertas en sub-graves, low-mid (200–500 Hz) y decisiones de reverb/cola
- **Técnica de grabación**: guitarras en mono, FX procesados en estéreo después
- **Destinos**: Spotify/streaming, YouTube, y clips de 30 s para TikTok/Instagram/Shorts

"""

PLANTILLA_DANIEL = """# Perfil de usuario — Daniel · v0 (esqueleto)
> Contexto personal. Pendiente de completar por Daniel.

## Nivel de explicación
- En aprendizaje → **modo didáctico**: cada recomendación explica el porqué y el cómo en su DAW.

## Contexto técnico
- DAW: (pendiente)
- Monitores/auriculares: (pendiente)
- Sala: (pendiente)

## Diccionario de Daniel
(vacío)

## Reglas aprendidas personales
(Hereda las reglas básicas de Bruno como punto de partida; se independiza con su propio feedback)
"""

PLANTILLA_MATH_ROCK_MD = """# Género — Math Rock / Prog instrumental · v1
> Preset de género: referencias, estética y targets. Portable entre usuarios.

## Identidad sonora
- **Elemento central**: la guitarra — su articulación, dinámica y detalle deben leerse siempre
- **Carácter buscado**: mezclas limpias, dinámicas y con aire; modernas pero orgánicas, nunca aplastadas

## Referencias
| Referencia | Usar por | Escuchar específicamente |
|---|---|---|
| CHON — Perfect Pillow | Guitarras limpias / dulzura | Brillo sin dureza, tapping legible, sensación relajada |
| Polyphia — Euphoria | Modernidad / low-end | Guitarra técnica conviviendo con graves y ritmo de producción moderna |
| Plini — Every Piece Matters | Espacio / profundidad | Capas, reverbs musicales, mezcla amplia sin perder foco |
| Owane — Born in Space | Energía fusión / teclados+guitarra | Balance entre elementos densos manteniendo groove |
| Jack Gardiner ft. Mariko Muranaka — Eightfold Fence | Dinámica / expresividad | Matices de interpretación que la mezcla respeta, no aplana |

**Regla**: referencias orientan, no se clonan. Se comparan siempre a volumen igualado.

## Prioridades estéticas
1. **Transientes vivos**: el ataque de púa, tapping y batería no se sacrifica por loudness
2. **Guitarras**: claridad de nota individual incluso en pasajes rápidos; capas anchas en estéreo sin trucos falsos
3. **Batería**: pegada natural, platos con aire sin fatiga; nada de sonido sobre-comprimido de radio
4. **Bajo**: define el low-end junto al kick; debe leerse la nota, no solo sentirse el peso
5. **Dinámica de arreglo**: las secciones crecen por arreglo y automatización, no solo por volumen
6. **Master**: competitivo pero respetando el género — punto de partida -11 a -9 LUFS según densidad, decisión final por canción

## Qué evitar
- Sobrecompresión que mate la interpretación
- Dureza en 2–5 kHz por acumulación de guitarras brillantes
- Low-mid embarrado (200–500 Hz) por capas de guitarra sin limpiar
- Anchura estéreo falsa que rompa la compatibilidad mono
- Reverbs que emborronan pasajes técnicos rápidos

## Reglas aprendidas del género
(Se alimenta con el feedback. Formato: fecha · canción origen · regla · estado)
"""

PLANTILLA_MATH_ROCK_JSON = {
    "nombre": "Math Rock",
    "low_mid_delta_max_db": 2.0,
    "crest_min_db": 12.0,
    "sub_min_db": -30.0,
    "correlacion_min": 0.7,
    "lufs_max": -8.0,
    "nota_low_mid": "revisar acumulación de guitarras en 200–500 Hz",
    "nota_crest": "transientes comprimidos — vigilar",
    "nota_sub": "bajo muy suave para este género",
    "nota_correlacion": "imagen estéreo inestable",
    "nota_lufs": "muy fuerte para math rock — riesgo de fatiga",
}


# ------------------------------------------------------------------ gestión

def asegurar_perfiles_default() -> None:
    """Crea la estructura de perfiles/géneros con plantillas si no existe.

    Migración v0.1 → v0.1.1: el viejo config/perfil_bruno.md se conserva
    intacto; las plantillas nuevas ya contienen su contenido separado en capas.
    """
    ensure_app_dirs()
    defaults = {
        PERFILES_DIR / "bruno.md": PLANTILLA_BRUNO,
        PERFILES_DIR / "daniel.md": PLANTILLA_DANIEL,
        GENEROS_DIR / "math_rock.md": PLANTILLA_MATH_ROCK_MD,
    }
    for path, contenido in defaults.items():
        if not path.exists():
            path.write_text(contenido, encoding="utf-8")
            log.info("Plantilla creada: %s", path)

    for path, datos in {
        GENEROS_DIR / "math_rock.json": PLANTILLA_MATH_ROCK_JSON,
    }.items():
        if not path.exists():
            path.write_text(json.dumps(datos, indent=2, ensure_ascii=False), encoding="utf-8")
            log.info("Umbrales creados: %s", path)

    if PERFIL_FILE.exists():
        log.info("Perfil v0.1 (%s) conservado; la app usa perfiles/ y generos/", PERFIL_FILE.name)

    # Biblioteca de referencias: una carpeta por género existente
    for genero in listar_generos():
        (REFERENCIAS_DIR / genero).mkdir(parents=True, exist_ok=True)


PLANTILLA_GENERO_VACIO = """# Género — {titulo} · v0
> Preset nuevo, creado desde la app. Rellenar según se vaya afinando de oído.

## Identidad sonora
- (pendiente)

## Referencias
| Referencia | Usar por | Escuchar específicamente |
|---|---|---|
| (pendiente) | | |

## Prioridades estéticas
1. (pendiente)

## Qué evitar
- (pendiente)

## Reglas aprendidas del género
(vacío)
"""


def crear_genero(nombre: str) -> str:
    """Crea un género nuevo (slug + .md + .json con umbrales default). Idempotente.

    Devuelve el slug final (nombre normalizado usado como nombre de archivo).
    """
    ensure_app_dirs()
    slug = re.sub(r"[^a-z0-9_]+", "_", nombre.strip().lower()).strip("_")
    if not slug:
        raise ValueError("Nombre de género vacío")

    md = GENEROS_DIR / f"{slug}.md"
    js = GENEROS_DIR / f"{slug}.json"
    if not md.exists():
        md.write_text(PLANTILLA_GENERO_VACIO.format(titulo=nombre.strip()), encoding="utf-8")
    if not js.exists():
        datos = dict(UMBRALES_DEFAULT)
        datos["nombre"] = nombre.strip()
        js.write_text(json.dumps(datos, indent=2, ensure_ascii=False), encoding="utf-8")

    (REFERENCIAS_DIR / slug).mkdir(parents=True, exist_ok=True)
    log.info("Género creado: %s", slug)
    return slug


def listar_generos() -> list[str]:
    """Nombres de géneros disponibles (archivos .md en config/generos/)."""
    return sorted(p.stem for p in GENEROS_DIR.glob("*.md"))


def dir_referencias_genero(nombre: str) -> Path:
    """Carpeta de la biblioteca de referencias del género (autocreada)."""
    carpeta = REFERENCIAS_DIR / nombre
    carpeta.mkdir(parents=True, exist_ok=True)
    return carpeta


def listar_referencias_genero(nombre: str) -> list[Path]:
    """Audios de la biblioteca del género, ordenados por nombre."""
    return sorted(p for p in dir_referencias_genero(nombre).iterdir()
                  if p.is_file() and p.suffix.lower() in FORMATOS_REFERENCIA)


def listar_perfiles_usuario() -> list[Path]:
    """Rutas de perfiles de usuario disponibles (config/perfiles/*.md)."""
    return sorted(PERFILES_DIR.glob("*.md"))


# --------------------------------------------- perfil acumulativo versionado

def listar_versiones_genero(nombre: str) -> list[Path]:
    """Snapshots guardados del género, del más nuevo al más viejo."""
    VERSIONES_DIR.mkdir(parents=True, exist_ok=True)
    return sorted(VERSIONES_DIR.glob(f"{nombre}_v*.md"), reverse=True)


def snapshot_genero(nombre: str) -> Path | None:
    """Guarda una copia versionada del género ANTES de modificarlo.

    Nombre: <genero>_vN_<fecha>.md (N autoincremental). Devuelve la ruta.
    """
    md = GENEROS_DIR / f"{nombre}.md"
    if not md.exists():
        return None
    VERSIONES_DIR.mkdir(parents=True, exist_ok=True)
    numeros = [int(m.group(1)) for p in VERSIONES_DIR.glob(f"{nombre}_v*.md")
               if (m := re.search(r"_v(\d+)_", p.name))]
    n = max(numeros, default=0) + 1
    destino = VERSIONES_DIR / f"{nombre}_v{n}_{datetime.now():%Y%m%d-%H%M%S}.md"
    destino.write_text(md.read_text(encoding="utf-8"), encoding="utf-8")
    log.info("Snapshot del género: %s", destino.name)
    return destino


def _agregar_en_seccion(nombre: str, titulo_seccion: str, linea: str) -> None:
    """Añade una línea al final de una sección del md del género (snapshot antes)."""
    md = GENEROS_DIR / f"{nombre}.md"
    texto = md.read_text(encoding="utf-8") if md.exists() else f"# Género — {nombre}\n"
    snapshot_genero(nombre)

    if titulo_seccion not in texto:
        texto = texto.rstrip() + f"\n\n{titulo_seccion}\n"

    lineas = texto.splitlines()
    # busca el fin de la sección (próximo encabezado ## o fin de archivo)
    idx_seccion = next(i for i, l in enumerate(lineas) if l.strip() == titulo_seccion)
    fin = len(lineas)
    for i in range(idx_seccion + 1, len(lineas)):
        if lineas[i].startswith("## "):
            fin = i
            break
    lineas.insert(fin, linea)
    md.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    log.info("Género %s actualizado: %s", nombre, linea)


def agregar_regla_genero(nombre: str, regla: str, cancion: str = "") -> None:
    """Registra una regla aprendida en el género (versionando el estado previo)."""
    fecha = datetime.now().strftime("%Y-%m-%d")
    origen = f" · {cancion}" if cancion else ""
    _agregar_en_seccion(nombre, "## Reglas aprendidas del género",
                        f"- [{fecha}]{origen} · {regla.strip()} · estado: activa")


def agregar_regla_global(regla: str, etiqueta: str = "", cancion: str = "") -> None:
    """Registra una regla aprendida GLOBAL en el perfil activo (snapshot antes)."""
    perfil = PERFIL_FILE  # config/perfil_bruno.md
    if not perfil.exists():
        return

    fecha = datetime.now().strftime("%Y-%m-%d")
    etiqueta_txt = f" [{etiqueta}]" if etiqueta else ""
    origen = f" · {cancion}" if cancion else ""
    linea = f"- {fecha}{etiqueta_txt}{origen} | {regla.strip()} | estado: activa"

    # snapshot antes de modificar
    texto = perfil.read_text(encoding="utf-8")
    lineas = texto.splitlines()

    # busca o crea la sección
    idx_seccion = -1
    for i, l in enumerate(lineas):
        if l.strip() == "## Reglas aprendidas":
            idx_seccion = i
            break

    if idx_seccion == -1:
        lineas.append("\n## Reglas aprendidas")
        idx_seccion = len(lineas)

    # busca el fin de la sección (próximo encabezado o fin)
    fin = len(lineas)
    for i in range(idx_seccion + 1, len(lineas)):
        if lineas[i].startswith("## "):
            fin = i
            break

    lineas.insert(fin, linea)
    perfil.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    log.info("Regla global guardada: %s", linea)


def agregar_cancion_entrenamiento(nombre: str, titulo: str, resumen: str) -> None:
    """Registra un tema propio como referencia de entrenamiento del género."""
    fecha = datetime.now().strftime("%Y-%m-%d")
    _agregar_en_seccion(nombre, "## Temas de entrenamiento (referencia propia)",
                        f"- {titulo} ({fecha}): {resumen.strip()}")


def revertir_genero(nombre: str, path_version: Path) -> None:
    """Restaura el género a un snapshot anterior (guardando el actual antes)."""
    snapshot_genero(nombre)
    contenido = Path(path_version).read_text(encoding="utf-8")
    (GENEROS_DIR / f"{nombre}.md").write_text(contenido, encoding="utf-8")
    log.info("Género %s revertido a %s", nombre, Path(path_version).name)


def leer_genero(nombre: str) -> tuple[str, dict]:
    """Devuelve (texto_md, umbrales) del género. Umbrales default si falta el json."""
    md = GENEROS_DIR / f"{nombre}.md"
    js = GENEROS_DIR / f"{nombre}.json"
    try:
        texto = md.read_text(encoding="utf-8")
    except Exception:
        log.warning("Género '%s' sin .md — se usa texto vacío", nombre)
        texto = f"(Preset de género '{nombre}' no encontrado)"

    umbrales = dict(UMBRALES_DEFAULT)
    if js.exists():
        try:
            umbrales.update(json.loads(js.read_text(encoding="utf-8")))
        except Exception:
            log.exception("Umbrales ilegibles en %s; se usan defaults", js)
    return texto, umbrales
