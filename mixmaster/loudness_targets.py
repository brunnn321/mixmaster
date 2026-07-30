"""Targets de loudness por plataforma (v0.9+): números públicos, no
inventados, para elegir a qué LUFS masterizar según destino.

Fuentes (publicadas por cada plataforma / documentación técnica pública):
  - Spotify: Loudness Normalization — spotify.com/loudness (target -14 LUFS)
  - YouTube: usa normalización similar a EBU R128, target ~ -14 LUFS
  - Apple Music: Sound Check, target -16 LUFS (histórico Apple Mastered for iTunes)
  - Tidal: -14 LUFS (declarado en su documentación de normalización)
  - CD / sin normalización de plataforma: convención de industria -9 a -12 LUFS
    (NO es norma oficial — no hay estándar AES para loudness de mastering musical,
    a diferencia de broadcast donde sí rige EBU R128 / ITU-R BS.1770-4).

Nota honesta: masterizar EXACTO al target de la plataforma evita que te bajen
el volumen (turn-down), pero muchos ingenieros masterizan un poco más fuerte
a propósito por el carácter que da el limitador — es una decisión de gusto,
no solo de norma.
"""

TARGETS_PLATAFORMA = {
    "Spotify (-14 LUFS)": {
        "lufs": -14.0,
        "nota": "Normaliza a -14 LUFS. Masterizar más fuerte solo baja el volumen.",
    },
    "YouTube (-14 LUFS)": {
        "lufs": -14.0,
        "nota": "Normalización similar a broadcast (EBU R128).",
    },
    "Apple Music (-16 LUFS)": {
        "lufs": -16.0,
        "nota": "Sound Check — target más conservador que Spotify/YouTube.",
    },
    "Tidal (-14 LUFS)": {
        "lufs": -14.0,
        "nota": "Documentado en su normalización de loudness.",
    },
    "CD / competitivo (-9 LUFS)": {
        "lufs": -9.0,
        "nota": "Convención de industria (no norma oficial) — sin normalización de plataforma.",
    },
    "Streaming suave (-11 LUFS)": {
        "lufs": -11.0,
        "nota": "Punto medio — dinámico pero competitivo.",
    },
}
