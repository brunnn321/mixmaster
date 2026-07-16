"""Procesamiento de primera pasada de stems (v0.3 adelantada).

- Gain staging: copias niveladas con picos a -6 dBFS (headroom sano).
- Highpass conservador (12 dB/oct) según tipo de pista detectado por nombre.

Los originales de 02_stems/ NUNCA se tocan: todo se escribe en
05_mezclas_revision/stems_niveladas/. El mapeo nombre→tipo y las frecuencias
viven en config/stems.json (editable).
"""

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy import signal

from .app_paths import CONFIG_DIR
from .audio_analysis import cargar_audio, db
from .logger import get_logger
from .project import Project

log = get_logger("mixmaster.stems")

STEMS_CONFIG_FILE = CONFIG_DIR / "stems.json"

# Config por defecto: primera regla que matchea gana (bajo/kick va primero
# para que "kick" nunca reciba highpass aunque el nombre contenga otra clave)
CONFIG_DEFAULT = {
    "pico_objetivo_dbfs": -6.0,
    "orden_filtro": 2,
    "tipos": [
        {"tipo": "bajo/kick", "claves": ["bass", "bajo", "kick", "bombo", "sub"],
         "highpass_hz": 0},
        {"tipo": "guitarra", "claves": ["gtr", "guitar", "guitarra"],
         "highpass_hz": 80},
        {"tipo": "voz", "claves": ["vox", "voz", "voice", "vocal"],
         "highpass_hz": 90},
        {"tipo": "platos/OH", "claves": ["oh", "overhead", "platos", "cymbal",
                                          "crash", "ride", "hihat", "hat"],
         "highpass_hz": 150},
    ],
}

FORMATOS_STEM = (".wav", ".flac", ".aiff", ".aif")


def cargar_config_stems() -> dict:
    """Lee config/stems.json; lo crea con defaults si no existe."""
    if not STEMS_CONFIG_FILE.exists():
        try:
            STEMS_CONFIG_FILE.write_text(
                json.dumps(CONFIG_DEFAULT, indent=2, ensure_ascii=False), encoding="utf-8")
            log.info("Config de stems creada: %s", STEMS_CONFIG_FILE)
        except Exception:
            log.exception("No se pudo crear stems.json; se usan defaults")
        return dict(CONFIG_DEFAULT)
    try:
        cfg = json.loads(STEMS_CONFIG_FILE.read_text(encoding="utf-8"))
        # Completa claves faltantes con defaults
        for k, v in CONFIG_DEFAULT.items():
            cfg.setdefault(k, v)
        return cfg
    except Exception:
        log.exception("stems.json ilegible; se usan defaults")
        return dict(CONFIG_DEFAULT)


def detectar_tipo(nombre: str, cfg: dict) -> tuple[str, float]:
    """Devuelve (tipo, highpass_hz) según el nombre del archivo.

    Primera regla cuyo alguna clave aparezca en el nombre (minúsculas) gana;
    sin match → sin filtro.
    """
    nombre = nombre.lower()
    for regla in cfg.get("tipos", []):
        if any(clave in nombre for clave in regla.get("claves", [])):
            return regla.get("tipo", "?"), float(regla.get("highpass_hz", 0))
    return "otro", 0.0


def _procesar_stem(path: Path, destino: Path, cfg: dict) -> dict:
    """Procesa un stem: highpass según tipo + nivelación de pico. Devuelve reporte."""
    audio, sr = cargar_audio(path)
    tipo, hp_hz = detectar_tipo(path.name, cfg)

    pico_in = float(np.max(np.abs(audio)))
    rms_in = float(np.sqrt(np.mean(audio ** 2)))

    # Highpass conservador (orden 2 = 12 dB/oct)
    if hp_hz > 0:
        sos = signal.butter(int(cfg.get("orden_filtro", 2)), hp_hz / (sr / 2),
                            btype="highpass", output="sos")
        audio = signal.sosfilt(sos, audio, axis=0)

    # Gain staging: pico al objetivo (por defecto -6 dBFS)
    objetivo = 10 ** (float(cfg.get("pico_objetivo_dbfs", -6.0)) / 20)
    pico_filtrado = float(np.max(np.abs(audio)))
    ganancia_db = 0.0
    if pico_filtrado > 1e-9:
        ganancia = objetivo / pico_filtrado
        ganancia_db = 20 * float(np.log10(ganancia))
        audio = audio * ganancia

    sf.write(str(destino), audio, sr, subtype="PCM_24")

    return {
        "archivo": path.name,
        "tipo": tipo,
        "highpass_hz": hp_hz,
        "pico_in_db": round(db(pico_in), 1),
        "rms_in_db": round(db(rms_in), 1),
        "ganancia_db": round(ganancia_db, 1),
        "pico_out_db": round(db(float(np.max(np.abs(audio)))), 1),
        "salida": destino.name,
    }


def reporte_stems_legible(reporte: dict) -> str:
    """Convierte el reporte de procesamiento en texto legible."""
    lineas = [
        "══ GAIN STAGING + HIGHPASS DE STEMS ══",
        f"Fecha: {reporte['fecha']}   Stems procesados: {len(reporte['stems'])}",
        f"Objetivo de pico: {reporte['pico_objetivo_dbfs']} dBFS   Filtro: {reporte['orden_filtro'] * 6} dB/oct",
        f"Salida: {reporte['carpeta_salida']}",
        "",
    ]
    for s in reporte["stems"]:
        hp = f"HP {s['highpass_hz']:g} Hz" if s["highpass_hz"] > 0 else "sin filtro"
        lineas.append(
            f"  {s['archivo']:<28} [{s['tipo']:<10}] {hp:<12} "
            f"pico {s['pico_in_db']:>6} → {s['pico_out_db']:>6} dB  "
            f"(ganancia {s['ganancia_db']:+.1f} dB)"
        )
    if reporte.get("errores"):
        lineas += ["", "— ERRORES —"]
        for e in reporte["errores"]:
            lineas.append(f"  ⚠ {e}")
    if not reporte["stems"] and not reporte.get("errores"):
        lineas.append("  (no se encontraron stems en 02_stems/)")
    return "\n".join(lineas)


def procesar_stems(proyecto: Project, progreso=None) -> dict:
    """Procesa todos los stems de 02_stems/ del proyecto. Devuelve reporte.

    Escribe las copias en 05_mezclas_revision/stems_niveladas/ y el reporte
    legible en 04_analisis/gain_staging.txt. Los originales no se modifican.
    """
    def avisar(msg):
        log.info(msg)
        if progreso:
            progreso(msg)

    cfg = cargar_config_stems()
    dir_stems = proyecto.dir_stems
    dir_salida = proyecto.dir_stems_niveladas
    dir_salida.mkdir(parents=True, exist_ok=True)

    archivos = sorted(p for p in dir_stems.iterdir()
                      if p.is_file() and p.suffix.lower() in FORMATOS_STEM)

    reporte = {
        "fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "pico_objetivo_dbfs": cfg.get("pico_objetivo_dbfs", -6.0),
        "orden_filtro": int(cfg.get("orden_filtro", 2)),
        "carpeta_salida": str(dir_salida),
        "stems": [],
        "errores": [],
    }

    for i, path in enumerate(archivos, 1):
        avisar(f"Procesando stem {i}/{len(archivos)}: {path.name}…")
        try:
            reporte["stems"].append(_procesar_stem(path, dir_salida / path.name, cfg))
        except Exception as e:
            log.exception("Fallo procesando stem %s", path.name)
            reporte["errores"].append(f"{path.name}: {e}")

    texto = reporte_stems_legible(reporte)
    try:
        proyecto.dir_analisis.mkdir(parents=True, exist_ok=True)  # on-demand
        (proyecto.dir_analisis / "gain_staging.txt").write_text(texto, encoding="utf-8")
    except Exception:
        log.exception("No se pudo escribir gain_staging.txt")

    avisar(f"Stems listos: {len(reporte['stems'])} procesados, "
           f"{len(reporte['errores'])} errores.")
    return reporte
