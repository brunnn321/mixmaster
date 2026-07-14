"""Test de humo sin UI: genera WAVs sintéticos y corre el pipeline completo.

Uso:  .venv\\Scripts\\python tests\\test_smoke.py
No usa pytest para mantener las dependencias mínimas.
"""

import json
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mixmaster.audio_analysis import analizar_wav, generar_alertas, parse_marcadores, parse_tiempo
from mixmaster.context_builder import construir_contexto
from mixmaster.decisions import guardar_decision
from mixmaster.processing import cargar_config_master, masterizar, sumar_stems
from mixmaster.profiles import (
    agregar_regla_genero, asegurar_perfiles_default, dir_referencias_genero,
    leer_genero, listar_generos, listar_referencias_genero,
    listar_versiones_genero, revertir_genero,
)
from mixmaster.project import crear_proyecto
from mixmaster.report import guardar_diagnostico, reporte_legible
from mixmaster.settings import Settings
from mixmaster.stems import cargar_config_stems, detectar_tipo, procesar_stems

SR = 44100


def wav_sintetico(path: Path, dur_s: float = 30.0, gain: float = 0.3,
                  clip: bool = False) -> None:
    """Crea un WAV estéreo con contenido en varias bandas (ruido + tonos)."""
    n = int(dur_s * SR)
    t = np.arange(n) / SR
    rng = np.random.default_rng(42)

    señal = (
        0.30 * np.sin(2 * np.pi * 50 * t) +      # sub
        0.30 * np.sin(2 * np.pi * 120 * t) +     # low
        0.25 * np.sin(2 * np.pi * 350 * t) +     # low-mid
        0.25 * np.sin(2 * np.pi * 1000 * t) +    # mid
        0.15 * np.sin(2 * np.pi * 3500 * t) +    # high-mid
        0.10 * rng.standard_normal(n)            # ruido banda ancha (air incl.)
    )
    # Segunda mitad más fuerte, para que las secciones difieran
    señal[n // 2:] *= 1.8
    L = señal * gain
    R = señal * gain + 0.02 * rng.standard_normal(n)  # leve descorrelación
    audio = np.stack([L, R], axis=1)
    if clip:
        audio = np.clip(audio * 5, -1.0, 1.0)
    else:
        audio = np.clip(audio, -0.99, 0.99)
    sf.write(str(path), audio, SR)


def main() -> int:
    fallos = []

    def check(nombre: str, cond: bool, detalle: str = ""):
        estado = "OK " if cond else "FAIL"
        print(f"[{estado}] {nombre}" + (f" — {detalle}" if detalle else ""))
        if not cond:
            fallos.append(nombre)

    tmp = Path(tempfile.mkdtemp(prefix="mixmaster_test_"))
    try:
        # --- parseo de tiempos y marcadores ---
        check("parse_tiempo m:ss", parse_tiempo("1:23") == 83.0)
        check("parse_tiempo segundos", parse_tiempo("12.5") == 12.5)
        marcas = parse_marcadores("Intro: 0:00, Riff A: 0:10, Final: 0:20", 30.0)
        check("parse_marcadores", len(marcas) == 3 and marcas[1]["fin_s"] == 20.0)

        # --- proyecto ---
        proyecto = crear_proyecto(tmp, "Cancion De Prueba v01")
        check("estructura de carpetas (layout simple)",
              all((proyecto.root / d).is_dir() for d in
                  ["entrada", "entrada/stems", "salida", "analisis"]))
        check("decisiones-y-feedback.md creado", proyecto.decisiones_path.exists())
        # compatibilidad con proyectos viejos (carpetas numeradas)
        viejo_root = tmp / "proyecto_viejo"
        for d in ["01_originales", "02_stems", "03_referencias", "04_analisis"]:
            (viejo_root / d).mkdir(parents=True)
        from mixmaster.project import abrir_proyecto
        viejo = abrir_proyecto(viejo_root)
        check("layout viejo detectado y rutas correctas",
              viejo.es_layout_viejo and viejo.dir_stems.name == "02_stems"
              and viejo.dir_analisis.name == "04_analisis")

        # --- análisis completo con referencia y secciones ---
        wav_mix = proyecto.dir_originales / "mezcla.wav"
        wav_ref = proyecto.dir_referencias / "referencia.wav"
        wav_sintetico(wav_mix, gain=0.3)
        wav_sintetico(wav_ref, gain=0.15)  # referencia más baja: prueba la nivelación

        diag = analizar_wav(wav_mix, "Intro: 0:00, Riff A: 0:15", wav_ref, version="V01")

        g = diag["global"]
        check("LUFS integrado medido", g["lufs_i"] is not None and -40 < g["lufs_i"] < 0,
              f"lufs_i={g['lufs_i']}")
        check("true peak razonable", -10 < g["true_peak_db"] <= 1.0,
              f"tp={g['true_peak_db']}")
        check("crest factor > 0", g["crest_factor_db"] > 0, f"crest={g['crest_factor_db']}")
        check("7 bandas espectrales", set(diag["bandas_db"]) ==
              {"sub", "low", "low_mid", "mid", "high_mid", "high", "air"})
        check("correlación alta (casi mono)", diag["estereo"]["correlacion_global"] > 0.8,
              f"corr={diag['estereo']['correlacion_global']}")
        check("2 secciones analizadas", len(diag["secciones"]) == 2)
        check("sección 2 más fuerte que sección 1",
              diag["secciones"][1]["lufs_st"] > diag["secciones"][0]["lufs_st"],
              f"{diag['secciones'][0]['lufs_st']} vs {diag['secciones'][1]['lufs_st']}")
        vs = diag["vs_referencia"]
        check("vs_referencia presente", vs is not None and "delta_bandas_db" in vs)
        # Misma señal nivelada en loudness → deltas por banda cercanos a 0
        if vs and "delta_bandas_db" in vs:
            max_delta = max(abs(v) for v in vs["delta_bandas_db"].values())
            check("nivelación loudness (deltas ~0)", max_delta < 1.5,
                  f"max delta={max_delta}")
        check("sin clipping falso", not diag["clipping_global"])

        # --- referencia en MP3 (flujo real de Bruno) ---
        mp3_ref = proyecto.dir_referencias / "referencia.mp3"
        audio_ref, sr_ref = sf.read(str(wav_ref))
        sf.write(str(mp3_ref), audio_ref, sr_ref)
        diag_mp3 = analizar_wav(wav_mix, "", mp3_ref, version="V01b")
        vs_mp3 = diag_mp3["vs_referencia"]
        check("referencia MP3 analizada", vs_mp3 is not None
              and vs_mp3.get("referencia") == "referencia.mp3"
              and "delta_bandas_db" in vs_mp3)
        # --- mezcla en MP3 también ---
        mp3_mix = proyecto.dir_originales / "mezcla.mp3"
        audio_mix, sr_mix = sf.read(str(wav_mix))
        sf.write(str(mp3_mix), audio_mix, sr_mix)
        diag_mix_mp3 = analizar_wav(mp3_mix, version="V01c")
        check("mezcla MP3 analizada",
              abs(diag_mix_mp3["global"]["lufs_i"] - diag["global"]["lufs_i"]) < 1.0,
              f"lufs mp3={diag_mix_mp3['global']['lufs_i']} vs wav={diag['global']['lufs_i']}")

        # --- masterizado automático ---
        resumen = masterizar(
            wav_mix, wav_ref, -10.0,
            proyecto.root / "06_masters", proyecto.root / "07_entregables",
            version="V01")
        check("master WAV creado", Path(resumen["wav"]).exists())
        check("master MP3 creado", Path(resumen["mp3"]).exists())
        check("loudness en objetivo", abs(resumen["lufs_final"] - (-10.0)) < 1.0,
              f"lufs={resumen['lufs_final']}")
        check("true peak bajo techo", resumen["true_peak_final"] <= -0.8,
              f"tp={resumen['true_peak_final']}")
        check("EQ correctivo acotado",
              resumen["eq_aplicado_db"] and
              all(abs(v) <= 4.0 for v in resumen["eq_aplicado_db"].values()),
              str(resumen["eq_aplicado_db"]))
        # El master debe quedar más cerca de la referencia que la mezcla original
        diag_master = analizar_wav(Path(resumen["wav"]), "", wav_ref, version="V01m")
        d_orig = diag["vs_referencia"]["delta_bandas_db"]
        d_mast = diag_master["vs_referencia"]["delta_bandas_db"]
        mejora = sum(abs(d_mast[b]) for b in d_mast) <= sum(abs(d_orig[b]) for b in d_orig) + 0.5
        check("master más cerca de la referencia", mejora,
              f"orig={d_orig} master={d_mast}")

        # --- multi-referencia: promedio (consenso tonal) ---
        diag_multi = analizar_wav(wav_mix, "", [wav_ref, mp3_ref], version="V01r")
        vs_multi = diag_multi["vs_referencia"]
        check("análisis con 2 referencias", vs_multi.get("n_referencias") == 2
              and "referencia.wav" in vs_multi["referencia"]
              and "referencia.mp3" in vs_multi["referencia"])
        res_multi = masterizar(
            wav_mix, [wav_ref, mp3_ref], -10.0,
            proyecto.root / "06_masters", proyecto.root / "07_entregables",
            version="V02r")
        check("master con 2 referencias", Path(res_multi["wav"]).exists()
              and len(res_multi["referencias"]) == 2)

        # --- master competitivo (-8.5), matching fino, clipper y score ---
        cfg_m = cargar_config_master()
        check("config master.json con modo fino", cfg_m["eq_correctivo"]["modo"] == "fino"
              and cfg_m["clipper"]["activo"])
        res_loud = masterizar(
            wav_mix, wav_ref, -8.5,
            proyecto.root / "06_masters", proyecto.root / "07_entregables",
            version="V02")
        check("master competitivo en -8.5", abs(res_loud["lufs_final"] - (-8.5)) < 1.0,
              f"lufs={res_loud['lufs_final']}")
        check("competitivo bajo techo", res_loud["true_peak_final"] <= -0.8,
              f"tp={res_loud['true_peak_final']}")
        sc = res_loud.get("score")
        check("score A/B presente y en rango", sc is not None
              and all(0 <= sc[k] <= 100 for k in ("tonal", "dinamica", "imagen", "global")),
              str(sc))
        # Misma señal que la referencia → similitud tonal alta
        check("score tonal alto (misma señal)", sc["tonal"] >= 80, f"tonal={sc['tonal']}")
        # Clipper: codo suave, monótono y bajo el techo
        from mixmaster.processing import _clipper
        rampa = np.linspace(0, 1.5, 1000).reshape(-1, 1)
        clipeada = _clipper(rampa, -0.5)
        check("clipper monótono y bajo techo",
              float(np.max(clipeada)) <= 1.0 and bool(np.all(np.diff(clipeada[:, 0]) >= -1e-9)))
        check("clipper transparente bajo el umbral",
              bool(np.allclose(clipeada[rampa < 0.9], rampa[rampa < 0.9])))


        # --- procesamiento de stems (gain staging + highpass) ---
        cfg = cargar_config_stems()
        check("detección de tipo: guitarra", detectar_tipo("Gtr_L_v2.wav", cfg) == ("guitarra", 80.0))
        check("detección de tipo: bajo sin filtro", detectar_tipo("BASS_di.wav", cfg)[1] == 0.0)
        check("detección de tipo: kick gana a otras claves",
              detectar_tipo("kick_oh_bleed.wav", cfg)[1] == 0.0)
        check("detección de tipo: sin match", detectar_tipo("sinte_pad.wav", cfg) == ("otro", 0.0))

        dir_stems = proyecto.dir_stems
        n_s = int(5 * SR)
        t_s = np.arange(n_s) / SR
        rng2 = np.random.default_rng(7)
        # Guitarra con contenido sub (40 Hz) que el highpass debe atenuar
        gtr = (0.2 * np.sin(2 * np.pi * 40 * t_s) + 0.2 * np.sin(2 * np.pi * 800 * t_s))
        sf.write(str(dir_stems / "gtr_L.wav"), np.stack([gtr, gtr], axis=1) * 0.5, SR)
        # Bajo: solo graves, NO debe filtrarse
        bajo = 0.4 * np.sin(2 * np.pi * 55 * t_s)
        sf.write(str(dir_stems / "bass_di.wav"), np.stack([bajo, bajo], axis=1), SR)
        # OH: ruido, muy bajito (debe recibir mucha ganancia)
        oh = 0.02 * rng2.standard_normal((n_s, 2))
        sf.write(str(dir_stems / "OH_drums.wav"), oh, SR)

        hash_orig = (dir_stems / "gtr_L.wav").read_bytes()
        rep = procesar_stems(proyecto)
        check("3 stems procesados", len(rep["stems"]) == 3 and not rep["errores"])
        check("originales intactos", (dir_stems / "gtr_L.wav").read_bytes() == hash_orig)

        dir_out = proyecto.dir_stems_niveladas
        check("copias niveladas escritas",
              all((dir_out / f).exists() for f in ["gtr_L.wav", "bass_di.wav", "OH_drums.wav"]))
        check("reporte gain_staging.txt", (proyecto.dir_analisis / "gain_staging.txt").exists())

        for s in rep["stems"]:
            audio_out, _ = sf.read(str(dir_out / s["salida"]))
            pico = 20 * np.log10(np.max(np.abs(audio_out)))
            check(f"pico -6 dBFS en {s['archivo']}", abs(pico - (-6.0)) < 0.2,
                  f"pico={pico:.2f}")

        # Highpass: la gtr nivelada debe tener mucho menos 40 Hz relativo que el bajo
        from mixmaster.audio_analysis import balance_bandas_db as bandas
        g_out, _ = sf.read(str(dir_out / "gtr_L.wav"), always_2d=True)
        b_out, _ = sf.read(str(dir_out / "bass_di.wav"), always_2d=True)
        bandas_g = bandas(g_out, SR)
        bandas_b = bandas(b_out, SR)
        check("highpass aplicado a guitarra (sub atenuado)",
              bandas_g["sub"] < bandas_g["mid"] - 10, f"sub={bandas_g['sub']} mid={bandas_g['mid']}")
        check("bajo sin filtrar (sub dominante)", bandas_b["sub"] > -12,
              f"sub={bandas_b['sub']}")

        # --- master desde stems (suma virtual) ---
        mezcla_virtual, sr_v = sumar_stems(dir_out)
        check("suma de stems estéreo", mezcla_virtual.shape[1] == 2 and sr_v == SR)
        res_stems = masterizar(
            None, wav_ref, -8.5,
            proyecto.root / "06_masters", proyecto.root / "07_entregables",
            version="V03", carpeta_stems=dir_out)
        check("master desde stems creado", Path(res_stems["wav"]).exists()
              and res_stems["fuente"] == "stems")
        check("master de stems en objetivo", abs(res_stems["lufs_final"] - (-8.5)) < 1.0,
              f"lufs={res_stems['lufs_final']}")

        # --- biblioteca de referencias por género ---
        asegurar_perfiles_default()
        check("carpetas de biblioteca autocreadas",
              dir_referencias_genero("math_rock").is_dir()
              and dir_referencias_genero("funk").is_dir())
        # copia 2 referencias a la biblioteca y verifica listado + análisis
        import shutil as _sh
        _sh.copy(wav_ref, dir_referencias_genero("math_rock") / "ref_a.wav")
        _sh.copy(mp3_ref, dir_referencias_genero("math_rock") / "ref_b.mp3")
        biblio = listar_referencias_genero("math_rock")
        biblio_test = [p for p in biblio if p.name in ("ref_a.wav", "ref_b.mp3")]
        check("biblioteca lista WAV y MP3", len(biblio_test) == 2)
        diag_biblio = analizar_wav(wav_mix, "", biblio_test, version="V01b2")
        check("análisis contra biblioteca",
              diag_biblio["vs_referencia"].get("n_referencias") == 2)
        # limpieza para no contaminar la config real
        for p in biblio_test:
            p.unlink()

        # --- perfil acumulativo: reglas versionadas y revertir ---
        md_antes, _ = leer_genero("math_rock")
        agregar_regla_genero("math_rock", "correlación baja en mid OK si pérdida mono < 1.5 dB",
                             "wav mix.wav")
        md_con_regla, _ = leer_genero("math_rock")
        check("regla añadida al género", "pérdida mono < 1.5 dB" in md_con_regla)
        versiones = listar_versiones_genero("math_rock")
        check("snapshot creado al añadir regla", len(versiones) >= 1)
        revertir_genero("math_rock", versiones[-1])  # la más vieja = estado original
        md_revertido, _ = leer_genero("math_rock")
        check("revertir restaura el estado previo",
              "pérdida mono < 1.5 dB" not in md_revertido
              and md_revertido == md_antes)

        # --- clipping real detectado ---
        wav_clip = proyecto.dir_originales / "clipeado.wav"
        wav_sintetico(wav_clip, clip=True)
        diag_clip = analizar_wav(wav_clip, version="V02")
        check("clipping detectado", diag_clip["clipping_global"])
        check("alerta de clipping", any("Clipping" in a for a in diag_clip["alertas"]))
        check("alerta crest bajo (señal aplastada)",
              any("comprimidos" in a for a in diag_clip["alertas"]),
              f"crest={diag_clip['global']['crest_factor_db']}")

        # --- guardado de diagnóstico ---
        pj, pt = guardar_diagnostico(proyecto, diag)
        check("diagnostico_v01.json escrito", pj.exists() and pj.name == "diagnostico_v01.json")
        check("diagnostico_legible.txt escrito", pt.exists())
        releido = json.loads(pj.read_text(encoding="utf-8"))
        check("JSON con claves de contrato", all(
            k in releido for k in ["archivo", "fecha", "version", "global",
                                   "bandas_db", "estereo", "secciones",
                                   "vs_referencia", "alertas"]))
        check("reporte legible no vacío", len(reporte_legible(diag)) > 200)

        # --- decisiones ---
        guardar_decision(proyecto, "V01", "mezcla.wav", "Bajar 2 dB el low-mid", "aprobado")
        contenido = proyecto.decisiones_path.read_text(encoding="utf-8")
        check("decisión registrada", "Bajar 2 dB el low-mid" in contenido
              and "Feedback: aprobado" in contenido)

        # --- perfiles híbridos (usuario + género) ---
        asegurar_perfiles_default()
        generos = listar_generos()
        check("géneros disponibles", "math_rock" in generos and "funk" in generos,
              str(generos))
        md_genero, umbrales = leer_genero("math_rock")
        check("género math_rock legible", "Math Rock" in md_genero
              and umbrales["lufs_max"] == -8.0)
        _, umbrales_funk = leer_genero("funk")
        check("umbrales por género distintos",
              umbrales_funk["crest_min_db"] != umbrales["crest_min_db"])
        # Umbral custom estricto: la señal (-12.4 LUFS) debe disparar alerta
        alertas_estrictas = generar_alertas(diag, {"lufs_max": -20.0})
        check("alerta con umbral custom", any("LUFS integrado" in a for a in alertas_estrictas))
        # Con el default (-8) esa alerta NO debe saltar
        check("sin alerta con umbral default",
              not any("LUFS integrado" in a for a in generar_alertas(diag)))

        # --- contexto de chat ---
        settings = Settings()
        ctx = construir_contexto(settings, proyecto, diag, "¿Qué priorizo primero?")
        check("contexto incluye perfil de usuario", "PERFIL DE USUARIO" in ctx
              and "ADAM Audio D3V" in ctx)
        check("contexto incluye género", "PERFIL DE GÉNERO" in ctx and "CHON" in ctx)
        check("contexto incluye diagnóstico", "DIAGNÓSTICO" in ctx and diag["archivo"] in ctx)
        check("contexto incluye decisiones", "Bajar 2 dB el low-mid" in ctx)
        check("contexto incluye mensaje", "¿Qué priorizo primero?" in ctx)
        check("máx 2 secciones en contexto", ctx.count('"nombre"') <= 2)

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if fallos:
        print(f"RESULTADO: {len(fallos)} fallo(s): {fallos}")
        return 1
    print("RESULTADO: todos los checks pasaron")
    return 0


if __name__ == "__main__":
    sys.exit(main())
