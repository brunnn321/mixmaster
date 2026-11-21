"""Control de calidad y diagnóstico de mezcla con las reglas de los skills de
mastering que trajo Daniel (21/11/2026):

- `control_calidad`: semáforo técnico, umbrales de bitwize-music-studio
  (tools/mastering/qc_tracks.py, CC0).
- `problemas_mezcla`: lo que oiría un ingeniero, reglas de mixer-doctor y
  mastering-prep (glincker/ableton-skills, MIT): cada zona se compara con lo
  que la curva propia de la mezcla dice que debería tener ahí.
"""

import numpy as np

from .audio_analysis import espectro_suavizado, true_peak_db

VERDE, AMARILLO, ROJO = "ok", "aviso", "mal"

# Zonas de mixer-doctor: (desde Hz, hasta Hz, corte central Hz, Q)
ZONAS = {
    "retumbe":    (40.0, 80.0, 60.0, 1.0),
    "embarrado":  (200.0, 400.0, 300.0, 1.0),
    "encajonado": (400.0, 800.0, 600.0, 1.2),
    "aspero":     (2000.0, 5000.0, 3500.0, 1.5),
    "sibilante":  (5000.0, 8000.0, 6500.0, 2.0),
}
# Nivel de cada zona respecto de sus vecinas (media de dB, desvío) en masters
# profesionales: las 11 referencias de la biblioteca de Bruno (math rock,
# grunge y Emotions Never Felt), medidas el 21/11/2026. Un master sano ya trae
# +4 dB de retumbe y +3 de aspereza sobre sus vecinas; problema es salirse de eso.
NORMAS = {"retumbe": (4.2, 3.0), "embarrado": (-0.5, 1.9), "encajonado": (-0.3, 1.5),
          "aspero": (3.2, 2.2), "sibilante": (0.6, 1.7)}
CORTE_MAX_DB = 3.0    # nunca más de -3 dB: un master corrige, no rehace la mezcla


def _estado(valor: float, bien: float, mal: float, mayor_es_peor: bool = True) -> str:
    if mayor_es_peor:
        return VERDE if valor < bien else (AMARILLO if valor < mal else ROJO)
    return VERDE if valor > bien else (AMARILLO if valor > mal else ROJO)


def _corridas_clip(x: np.ndarray, umbral: float = 0.99, largo: int = 3) -> int:
    """Cuántas regiones de `largo`+ muestras seguidas quedan en el techo."""
    pegado = np.abs(x) >= umbral
    if not pegado.any():
        return 0
    bordes = np.diff(np.concatenate(([0], pegado.astype(np.int8), [0])))
    inicios, fines = np.flatnonzero(bordes == 1), np.flatnonzero(bordes == -1)
    return int(np.sum((fines - inicios) >= largo))


def control_calidad(audio: np.ndarray, sr: int, techo_dbtp: float = -1.0) -> list[dict]:
    """Semáforo técnico. Cada chequeo: {nombre, estado, valor, texto}."""
    a = audio if audio.ndim == 2 and audio.shape[1] >= 2 else np.repeat(audio.reshape(-1, 1), 2, axis=1)
    l, r = a[:, 0], a[:, 1]
    mid = (l + r) / 2
    res = []

    # mono: energía que se pierde al sumar L+R (0 dB = mono perfecto, 3 dB = sin correlación)
    e_st, e_mid = (np.mean(l ** 2) + np.mean(r ** 2)) / 2, np.mean(mid ** 2)
    perdida = float(10 * np.log10(max(e_st, 1e-20) / max(e_mid, 1e-20)))
    res.append({"nombre": "Mono", "estado": _estado(perdida, 1.0, 3.0), "valor": round(perdida, 1),
                "texto": f"pierde {perdida:.1f} dB al sumarse a mono"})

    # fase: correlación media por ventanas de 500 ms, sin las silenciosas
    v = int(sr * 0.5)
    cors = []
    for i in range(0, len(l) - v, v):
        x, y = l[i:i + v], r[i:i + v]
        if np.sqrt(np.mean(x ** 2) + np.mean(y ** 2)) < 1e-3:
            continue
        sx, sy = x.std(), y.std()
        if sx > 0 and sy > 0:
            cors.append(float(np.mean((x - x.mean()) * (y - y.mean())) / (sx * sy)))
    corr = float(np.mean(cors)) if cors else 1.0
    res.append({"nombre": "Fase", "estado": _estado(corr, 0.5, 0.0, mayor_es_peor=False),
                "valor": round(corr, 2), "texto": f"correlación {corr:+.2f}"})

    # clipping: regiones de 3+ muestras pegadas en 0,99
    n_clip = _corridas_clip(l) + _corridas_clip(r)
    res.append({"nombre": "Saturación", "estado": VERDE if n_clip == 0 else (AMARILLO if n_clip <= 3 else ROJO),
                "valor": n_clip, "texto": f"{n_clip} zona(s) recortadas"})

    # true peak contra el techo
    tp = float(true_peak_db(a, sr))
    res.append({"nombre": "Pico real", "estado": VERDE if tp <= techo_dbtp + 0.1 else ROJO,
                "valor": round(tp, 1), "texto": f"{tp:+.1f} dBTP (techo {techo_dbtp:g})"})

    # clics: pico > 6 × RMS en ventanas de 10 ms
    w = max(int(sr * 0.01), 1)
    n = len(mid) // w
    bloques = mid[: n * w].reshape(n, w)
    rms = np.sqrt(np.mean(bloques ** 2, axis=1))
    pico = np.abs(bloques).max(axis=1)
    # bitwize usa 6 en general y 10 en géneros de golpes fuertes: con 6, el ataque
    # de una guitarra punteada ya cuenta como clic (weirdFishes v05 dio 6 falsos)
    n_clic = int(np.sum((rms > 1e-4) & (pico > 10.0 * rms)))
    res.append({"nombre": "Clics", "estado": VERDE if n_clic == 0 else (AMARILLO if n_clic <= 3 else ROJO),
                "valor": n_clic, "texto": f"{n_clic} posible(s) clic(s)"})

    # silencios: al inicio y huecos internos (aviso, nunca se recortan)
    vivo = np.abs(mid) > 10 ** (-60 / 20)
    inicio = float(np.argmax(vivo) / sr) if vivo.any() else 0.0
    res.append({"nombre": "Silencio inicial", "estado": VERDE if inicio <= 0.5 else AMARILLO,
                "valor": round(inicio, 1), "texto": f"{inicio:.1f} s antes del primer sonido"})

    # balance espectral (Welch con las bandas de bitwize)
    from scipy import signal
    f, p = signal.welch(mid, sr, nperseg=min(8192, len(mid)))
    total = float(p.sum()) or 1e-20
    def parte(lo, hi):
        return float(p[(f >= lo) & (f < hi)].sum()) / total
    sub, mid_b, hmid, agudos = parte(20, 60), parte(500, 2000), parte(2000, 6000), parte(6000, 20000)
    avisos = []
    if sub < 0.01:
        avisos.append("casi sin sub-graves")
    if mid_b > 0 and hmid / mid_b > 0.8:
        avisos.append("medios-agudos muy presentes")
    if agudos < 0.01:
        avisos.append("casi sin agudos")
    res.append({"nombre": "Balance", "estado": AMARILLO if avisos else VERDE, "valor": len(avisos),
                "texto": ", ".join(avisos) if avisos else "equilibrado"})
    return res


def nivel_zonas(audio: np.ndarray, sr: int) -> dict[str, float]:
    """Cuánto sobresale cada zona de sus vecinas (media de dB de la zona menos
    la de la octava de abajo y la de arriba), como lo escucharía mixer-doctor."""
    f, db = espectro_suavizado(audio, sr, n_puntos=200)
    f, db = np.asarray(f, float), np.asarray(db, float)
    out = {}
    for zona, (lo, hi, _fc, _q) in ZONAS.items():
        dentro = db[(f >= lo) & (f <= hi)]
        vecinas = np.concatenate([db[(f >= lo / 2) & (f < lo)], db[(f > hi) & (f <= hi * 2)]])
        if len(dentro) and len(vecinas):
            out[zona] = float(dentro.mean() - vecinas.mean())
    return out


def problemas_mezcla(audio: np.ndarray, sr: int) -> dict[str, dict]:
    """Zonas que se salen de lo que tiene un master profesional (NORMAS).

    Problema: la zona queda más de 2 desvíos por encima de la media profesional.
    Corte: lo que excede (media + 1 desvío), con tope de −3 dB y mínimo de 0,5.
    Devuelve {zona: {exceso_db, corte_db, freq, q}} solo con las zonas con problema.
    """
    out = {}
    for zona, valor in nivel_zonas(audio, sr).items():
        media, desv = NORMAS[zona]
        if valor > media + 2 * desv:
            corte = min(valor - (media + desv), CORTE_MAX_DB)
            _lo, _hi, fc, q = ZONAS[zona]
            out[zona] = {"exceso_db": round(valor - media, 1),
                         "corte_db": -round(max(corte, 0.5), 1), "freq": fc, "q": q}
    return out


if __name__ == "__main__":   # autocomprobación con señales sintéticas
    sr = 48000
    t = np.arange(sr * 4) / sr
    rng = np.random.default_rng(0)
    rosa = np.cumsum(rng.standard_normal(len(t))) * 0.0005
    rosa -= np.convolve(rosa, np.ones(2000) / 2000, mode="same")   # ruido de pendiente suave
    limpio = np.stack([rosa, rosa * 0.98], 1)
    from scipy import signal as _s
    b, a = _s.butter(2, [220 / (sr / 2), 380 / (sr / 2)], "band")
    barro = limpio + 4 * _s.lfilter(b, a, limpio, axis=0)
    assert "embarrado" in problemas_mezcla(barro, sr), problemas_mezcla(barro, sr)
    assert "embarrado" not in problemas_mezcla(limpio, sr), problemas_mezcla(limpio, sr)
    qc = {c["nombre"]: c["estado"] for c in control_calidad(np.stack([rosa, -rosa], 1), sr)}
    assert qc["Fase"] == ROJO and qc["Mono"] == ROJO, qc
    print("ok")
