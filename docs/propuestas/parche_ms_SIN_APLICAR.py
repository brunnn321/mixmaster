"""Matching mid/side sobre tramos fuertes + segunda pasada + avisos.

Veredicto del Consejo y del mentor (26/9/2026), sobre la base de Matchering.
"""
from pathlib import Path

RAIZ = Path(r"D:\PROYECTOS REPOSITORIOS\DAW IA\MixMaster\mixmaster")


def parchear(archivo, pares):
    p = RAIZ / archivo
    s = p.read_text(encoding="utf-8")
    for viejo, nuevo in pares:
        assert viejo in s, f"{archivo}: {viejo[:60]}"
        s = s.replace(viejo, nuevo, 1)
    p.write_text(s, encoding="utf-8")
    print(archivo, "ok")


# ======================================================== audio_analysis.py
parchear("audio_analysis.py", [
    ("ANALISIS_VERSION_REF = 2", "ANALISIS_VERSION_REF = 3  # v3: espectros mid/side de los tramos fuertes"),

    ('''def detectar_resonancias(audio: np.ndarray, sr: int, umbral_db: float = 6.0,''',
     '''def tramos_fuertes(audio: np.ndarray, sr: int, pieza_s: float = 15.0) -> np.ndarray:
    """Solo las partes fuertes del tema, concatenadas.

    Idea de Matchering: el timbre que importa igualar es el de los estribillos
    y partes llenas, no el de una intro callada o un final que se apaga, que
    arrastran el promedio. Se corta en piezas de `pieza_s` y se quedan las que
    tienen un RMS igual o mayor al RMS medio de las piezas. Con menos de dos
    piezas (temas cortos) devuelve el audio entero.
    """
    n = int(pieza_s * sr)
    if audio.shape[0] < 2 * n:
        return audio
    mono = audio.mean(axis=1) if audio.ndim > 1 else audio
    piezas = [(i, i + n) for i in range(0, audio.shape[0] - n + 1, n)]
    rms = np.array([np.sqrt(np.mean(mono[a:b] ** 2)) for a, b in piezas])
    elegidas = [p for p, r in zip(piezas, rms) if r >= rms.mean()]
    if not elegidas:
        return audio
    return np.concatenate([audio[a:b] for a, b in elegidas])


def espectro_ms(audio: np.ndarray, sr: int, n_puntos: int = 31):
    """Espectros suavizados del MID y del SIDE: (freqs, mid_db, side_db)."""
    if audio.ndim == 1 or audio.shape[1] == 1:
        mono = audio if audio.ndim == 1 else audio[:, 0]
        f, m = espectro_suavizado(mono, sr, n_puntos)
        return f, m, np.full_like(m, -200.0)
    mid = (audio[:, 0] + audio[:, 1]) / 2
    side = (audio[:, 0] - audio[:, 1]) / 2
    f, m = espectro_suavizado(mid, sr, n_puntos)
    _, s = espectro_suavizado(side, sr, n_puntos)
    return f, m, s


def corte_agudos_hz(freqs, esp_db) -> float:
    """Frecuencia donde el espectro cae 30 dB bajo su nivel de 2-8 kHz.

    Un MP3 de 128 kbps corta cerca de 16 kHz; un master sin pérdida llega a
    19-20 kHz. Sirve para avisar que la referencia no tiene agudos reales.
    """
    freqs, esp_db = np.asarray(freqs), np.asarray(esp_db)
    sel = (freqs >= 2000) & (freqs <= 8000)
    if not sel.any():
        return float(freqs[-1])
    base = float(np.mean(esp_db[sel]))
    arriba = np.where((freqs > 8000) & (esp_db < base - 30))[0]
    return float(freqs[arriba[0]]) if arriba.size else float(freqs[-1])


def detectar_resonancias(audio: np.ndarray, sr: int, umbral_db: float = 6.0,'''),

    ('''    audio, sr = cargar_audio(path)
    lufs = lufs_integrado(audio, sr)
    freqs, esp = espectro_suavizado(audio, sr)''',
     '''    audio, sr = cargar_audio(path)
    lufs = lufs_integrado(audio, sr)
    freqs, esp = espectro_suavizado(audio, sr)
    _, esp_mid, esp_side = espectro_ms(tramos_fuertes(audio, sr), sr)'''),

    ('''        "espectro_db": [float(x) for x in esp],''',
     '''        "espectro_db": [float(x) for x in esp],
        # v3: mid y side de los tramos fuertes (matching mid/side)
        "espectro_mid_db": [float(x) for x in esp_mid],
        "espectro_side_db": [float(x) for x in esp_side],
        "corte_agudos_hz": corte_agudos_hz(freqs, esp),'''),

    ('''    espectros, crests, crests_banda_acum = [], [], []
    freqs = None''',
     '''    espectros, crests, crests_banda_acum = [], [], []
    mids, sides, cortes = [], [], []
    freqs = None'''),

    ('''        espectros.append(np.asarray(e["espectro_db"]) + off)''',
     '''        espectros.append(np.asarray(e["espectro_db"]) + off)
        if e.get("espectro_mid_db"):
            mids.append(np.asarray(e["espectro_mid_db"]) + off)
            sides.append(np.asarray(e["espectro_side_db"]) + off)
        cortes.append(float(e.get("corte_agudos_hz") or freqs[-1]))'''),

    ('''        "espectro_db": np.mean(espectros, axis=0),
        "crest_db": round(float(np.mean(crests)), 1),''',
     '''        "espectro_db": np.mean(espectros, axis=0),
        "espectro_mid_db": np.mean(mids, axis=0) if len(mids) == len(espectros) else None,
        "espectro_side_db": np.mean(sides, axis=0) if len(sides) == len(espectros) else None,
        "corte_agudos_hz": min(cortes) if cortes else None,
        "crest_db": round(float(np.mean(crests)), 1),'''),
])

# ============================================================ processing.py
parchear("processing.py", [
    # imports
    ('''from .audio_analysis import (''',
     '''from .audio_analysis import espectro_ms, tramos_fuertes
from .audio_analysis import ('''),

    # helpers
    ('''def _clipper(audio: np.ndarray, umbral_dbfs: float) -> np.ndarray:''',
     '''def _aplicar_ms(audio: np.ndarray, fir_mid: np.ndarray, fir_side: np.ndarray) -> np.ndarray:
    """Filtra el MID y el SIDE con FIR distintos y vuelve a L/R."""
    mid = (audio[:, 0] + audio[:, 1]) / 2
    side = (audio[:, 0] - audio[:, 1]) / 2
    demora = len(fir_mid) // 2
    mid = signal.fftconvolve(mid, fir_mid, mode="full")[demora:demora + audio.shape[0]]
    side = signal.fftconvolve(side, fir_side, mode="full")[demora:demora + audio.shape[0]]
    return np.stack([mid + side, mid - side], axis=1)


F_SIDE_MIN_HZ = 150.0  # debajo de esto el side nunca se abre: el grave se desarma en mono


def _deltas_ms(audio: np.ndarray, sr: int, perfil: dict):
    """Corrección mid/side (dB, sin tope) para llevar `audio` a la referencia.

    MID: solo forma (se resta la media). SIDE: relativo a la media del MID de
    cada uno, así la corrección incluye cuánto ancho le falta o le sobra a
    cada banda. Mide sobre los tramos fuertes.
    """
    freqs, mid, side = espectro_ms(tramos_fuertes(audio, sr), sr)
    util = freqs <= F_MAX_MATCH_HZ
    ref_mid = np.asarray(perfil["espectro_mid_db"])
    ref_side = np.asarray(perfil["espectro_side_db"])
    base_mix, base_ref = float(np.mean(mid[util])), float(np.mean(ref_mid[util]))
    d_mid = (ref_mid - base_ref) - (mid - base_mix)
    d_side = (ref_side - base_ref) - (side - base_mix)
    d_mid[~util] = 0.0
    d_side[~util] = 0.0
    graves = freqs < F_SIDE_MIN_HZ
    d_side[graves] = np.minimum(d_side[graves], 0.0)   # graves: solo estrechar
    return freqs, d_mid, d_side, util


def _suavizar(delta: np.ndarray) -> np.ndarray:
    return np.convolve(delta, [0.25, 0.5, 0.25], mode="same")


def _clipper(audio: np.ndarray, umbral_dbfs: float) -> np.ndarray:'''),

    # score tonal sobre mid de tramos fuertes cuando hay datos
    ('''    freqs, esp_master = espectro_suavizado(audio, sr)
    esp_ref = np.asarray(perfil["espectro_db"])''',
     '''    if perfil.get("espectro_mid_db") is not None:
        # mismo criterio que el matching mid/side: MID de los tramos fuertes
        freqs, esp_master, _ = espectro_ms(tramos_fuertes(audio, sr), sr)
        esp_ref = np.asarray(perfil["espectro_mid_db"])
    else:
        freqs, esp_master = espectro_suavizado(audio, sr)
        esp_ref = np.asarray(perfil["espectro_db"])'''),

    # modo ms en el matching
    ('''        distancia_bandas_db = {}

        if cfg_eq.get("modo", "fino") == "fino":''',
     '''        distancia_bandas_db = {}
        modo_eq = cfg_eq.get("modo", "ms")
        if modo_eq == "ms" and perfil.get("espectro_mid_db") is None:
            modo_eq = "fino"   # caché de referencia sin datos mid/side

        if modo_eq == "ms":
            # Matching MID/SIDE sobre los tramos fuertes (Consejo 26/9, idea de
            # Matchering): el mid lleva el tono y el side el ancho por banda,
            # así la imagen estéreo también se acerca a la referencia.
            avisar(f"Matching mid/side sobre las partes fuertes (máx ±{tope:g} dB)…")
            freqs, d_mid, d_side, util = _deltas_ms(audio, sr, perfil)
            for b, (f_lo, f_hi) in BANDAS_HZ.items():
                sel = (freqs >= f_lo) & (freqs < f_hi) & util
                distancia_bandas_db[b] = round(float(np.abs(d_mid[sel]).mean()), 1) if sel.any() else 0.0
            grandes = [b for b, (f_lo, f_hi) in BANDAS_HZ.items()
                       if (sel := (freqs >= f_lo) & (freqs < f_hi) & util).any()
                       and float(np.abs(d_mid[sel]).max()) > 6.0]
            if grandes:
                aviso_eq_grande = (
                    f"La referencia pide más de 6 dB en: {', '.join(grandes)}. "
                    "Eso ya no es mastering, es arreglar la mezcla: conviene corregirlo "
                    "en la mezcla o elegir una referencia más parecida.")
                avisar(f"⚠ {aviso_eq_grande}")
            dm = _suavizar(np.clip(d_mid, -tope, tope))
            ds = _suavizar(np.clip(d_side, -tope, tope))
            fir_m = _curva_fir_fina(freqs, dm, sr)
            fir_s = _curva_fir_fina(freqs, ds, sr)
            aplicar_eq(lambda x: _aplicar_ms(x, fir_m, fir_s))
            correccion, correccion_side = {}, {}
            for b, (f_lo, f_hi) in BANDAS_HZ.items():
                sel = (freqs >= f_lo) & (freqs < f_hi)
                correccion[b] = round(float(dm[sel].mean()), 1) if sel.any() else 0.0
                correccion_side[b] = round(float(ds[sel].mean()), 1) if sel.any() else 0.0
        elif modo_eq == "fino":'''),

    # la imagen por bandas queda para los modos viejos (en ms ya la lleva el side)
    ('''        if cfg_eq.get("analizar_imagen_stereo", True):''',
     '''        if modo_eq != "ms" and cfg_eq.get("analizar_imagen_stereo", True):'''),

    # variables nuevas antes del bloque
    ('''    correccion, ajuste_ancho = {}, {}
    nombres_ref, perfil = [], None''',
     '''    correccion, ajuste_ancho, correccion_side = {}, {}, {}
    aviso_eq_grande = aviso_calidad_ref = None
    segunda_pasada = {}
    modo_eq = None
    nombres_ref, perfil = [], None'''),

    # aviso de calidad de referencia
    ('''        nombres_ref = perfil["nombres"]
        tope = float(cfg_eq.get("max_correccion_db", 4.0))''',
     '''        nombres_ref = perfil["nombres"]
        tope = float(cfg_eq.get("max_correccion_db", 4.0))
        corte = perfil.get("corte_agudos_hz")
        if corte and corte < 17000:
            aviso_calidad_ref = (
                f"La referencia se corta cerca de {corte / 1000:.1f} kHz (típico de un MP3 "
                "comprimido): arriba de eso no tiene agudos reales para copiar. "
                "Una versión WAV/FLAC o un MP3 de 320 kbps da un matching más fiel.")
            avisar(f"⚠ {aviso_calidad_ref}")'''),

    # segunda pasada: después de la dinámica macro, antes de medir el final
    ('''    lufs_final = lufs_integrado(audio, sr)
    tp_final = true_peak_db(audio, sr)
    crest_final = crest_factor_db(audio)''',
     '''    # Segunda pasada de matching (Consejo + mentor, 26/9): el clipper, la
    # densidad y el limitador cambian el agudo y dejan un residuo contra la
    # referencia. Una corrección suave (≤ max dB) lo cierra; después, limitador
    # y ajuste fino de loudness otra vez. No corre si el EQ se aplicó solo a
    # las guitarras: después del limitador la mezcla ya no se puede separar.
    max_2p = float(cfg_eq.get("segunda_pasada_max_db", 2.0))
    if (modo_eq == "ms" and grupo_eq is None and max_2p > 0
            and cfg_eq.get("segunda_pasada", True)):
        avisar(f"Segunda pasada de matching (residuo, máx ±{max_2p:g} dB)…")
        freqs2, r_mid, r_side, util2 = _deltas_ms(audio, sr, perfil)
        rm = _suavizar(np.clip(r_mid, -max_2p, max_2p))
        rs = _suavizar(np.clip(r_side, -max_2p, max_2p))
        audio = _aplicar_ms(audio, _curva_fir_fina(freqs2, rm, sr), _curva_fir_fina(freqs2, rs, sr))
        for b, (f_lo, f_hi) in BANDAS_HZ.items():
            sel = (freqs2 >= f_lo) & (freqs2 < f_hi)
            segunda_pasada[b] = round(float(rm[sel].mean()), 1) if sel.any() else 0.0
        audio = _limitador(audio, sr, cfg_lim)
        l2 = lufs_integrado(audio, sr)
        if np.isfinite(l2) and abs(target_lufs - l2) > tol_lufs:
            audio = _limitador(audio * 10 ** ((target_lufs - l2) / 20), sr, cfg_lim)

    lufs_final = lufs_integrado(audio, sr)
    tp_final = true_peak_db(audio, sr)
    crest_final = crest_factor_db(audio)'''),

    # resumen
    ('''        "eq_solo_en": stems_eq if grupo_eq is not None else [],''',
     '''        "eq_solo_en": stems_eq if grupo_eq is not None else [],
        "modo_eq": modo_eq,
        "eq_side_db": correccion_side,
        "segunda_pasada_db": segunda_pasada,
        "aviso_eq_grande": aviso_eq_grande,
        "aviso_referencia_calidad": aviso_calidad_ref,'''),
])
print("listo")
