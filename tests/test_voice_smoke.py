"""Test de humo del motor de voz/podcast (sin UI, sin pytest).

Uso:  .venv\\Scripts\\python tests\\test_voice_smoke.py
"""

import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mixmaster.voice_processing import (
    _compresor_voz, _de_esser, _gate, cargar_config_voz, procesar_voz,
)

SR = 44100


def voz_sintetica(path: Path, dur_s: float = 4.0) -> None:
    """Habla sintética: 2 sílabas separadas por un hueco largo con ruido de
    fondo, más un tramo de sibilancia (ruido de banda alta, simula "sss").

    El hueco (0.3s a 3.0s, 2.7s) es deliberadamente largo: con release_ms=150
    del gate por defecto, la envolvente decae a ~4.3dB por cada 77.5ms (tau)
    — desde el pico de una sílaba (~-8dB) hasta el umbral (-45dB) hace falta
    más de medio segundo. Un gap corto nunca alcanzaría a cerrar el gate sin
    importar si el gate funciona bien, así que el margen es generoso a
    propósito para no confundir "el gate no cerró" con "no le di tiempo".
    """
    n = int(dur_s * SR)
    t = np.arange(n) / SR
    rng = np.random.default_rng(11)

    señal = np.zeros(n)
    # sílaba 1: ráfaga de tono 200 Hz, [0, 0.3s]
    L = int(0.3 * SR)
    env = np.hanning(L)
    señal[:L] += env * 0.5 * np.sin(2 * np.pi * 200 * t[:L])
    # sílaba 2: al final del clip, [3.0, 3.3s]
    c2 = int(3.0 * SR)
    señal[c2:c2 + L] += env * 0.5 * np.sin(2 * np.pi * 200 * t[c2:c2 + L])
    # ruido de fondo constante y bajo (~-50 dBFS, bajo el umbral del gate de
    # -45dB), en TODO el clip (lo que el gate debe atenuar)
    ruido_fondo = 0.003 * rng.standard_normal(n)
    señal += ruido_fondo
    # tramo de sibilancia: ruido de banda 6-8 kHz, justo tras la 1ª sílaba,
    # con margen (1.9s) para decaer antes de donde se chequea el gate (2.7s)
    c0 = int(0.35 * SR)
    L_s = int(0.3 * SR)
    ruido_s = rng.standard_normal(L_s)
    from scipy import signal as sp_signal
    sos = sp_signal.butter(4, [6000, 8000], btype="band", fs=SR, output="sos")
    sibilancia = sp_signal.sosfiltfilt(sos, ruido_s) * 1.5
    señal[c0:c0 + L_s] += sibilancia

    audio = np.clip(señal, -0.95, 0.95).reshape(-1, 1)  # mono
    sf.write(str(path), audio, SR)


def main() -> int:
    fallos = []

    def check(nombre: str, cond: bool, detalle: str = ""):
        estado = "OK " if cond else "FAIL"
        print(f"[{estado}] {nombre}" + (f" — {detalle}" if detalle else ""))
        if not cond:
            fallos.append(nombre)

    tmp = Path(tempfile.mkdtemp(prefix="mixmaster_voice_"))
    try:
        wav_in = tmp / "voz.wav"
        voz_sintetica(wav_in)
        audio_in, sr = sf.read(str(wav_in), always_2d=True)

        # --- gate: atenúa el ruido de fondo entre sílabas, no toca las sílabas ---
        cfg_g = cargar_config_voz()["gate"]
        out_g = _gate(audio_in, sr, cfg_g)
        # tramo de silencio puro: cerca del final del hueco largo (0.3-3.0s),
        # con tiempo de sobra para que la envolvente del gate haya decaído
        hueco = slice(int(2.7 * SR), int(2.85 * SR))
        rms_hueco_antes = float(np.sqrt(np.mean(audio_in[hueco] ** 2)))
        rms_hueco_despues = float(np.sqrt(np.mean(out_g[hueco] ** 2)))
        check("gate: reduce el ruido de fondo en los huecos",
              rms_hueco_despues < rms_hueco_antes * 0.7,
              f"{rms_hueco_antes:.4f} -> {rms_hueco_despues:.4f}")
        silaba = slice(int(0.05 * SR), int(0.30 * SR))
        rms_silaba_antes = float(np.sqrt(np.mean(audio_in[silaba] ** 2)))
        rms_silaba_despues = float(np.sqrt(np.mean(out_g[silaba] ** 2)))
        check("gate: no aplasta la sílaba (nivel similar)",
              rms_silaba_despues > rms_silaba_antes * 0.85,
              f"{rms_silaba_antes:.4f} -> {rms_silaba_despues:.4f}")

        # --- compresor: reduce el crest factor (achica el rango dinámico) ---
        from mixmaster.audio_analysis import crest_factor_db
        cfg_c = cargar_config_voz()["compresor"]
        # Señal dedicada (no la de arriba, que es mayormente silencio y no
        # sirve para medir compresión): bed continuo bajo + picos de voz
        # recurrentes, mismo patrón que el test de multibanda del motor
        # musical (test_smoke.py) — el compresor debe achicar los picos sin
        # mover apenas el bed, así el crest cae de forma medible.
        n_c = 3 * SR
        t_c = np.arange(n_c) / SR
        L_c = int(0.15 * SR)
        hann_c = np.hanning(L_c)
        bed = 0.05 * np.sin(2 * np.pi * 180 * t_c)
        picos = np.zeros(n_c)
        for c in (int(0.3 * SR), int(0.9 * SR), int(1.5 * SR), int(2.1 * SR), int(2.7 * SR)):
            if c + L_c < n_c:
                picos[c:c + L_c] += hann_c
        voz_comp = (bed + picos * 0.5 * np.sin(2 * np.pi * 220 * t_c)).reshape(-1, 1)
        crest_antes = crest_factor_db(voz_comp)
        out_c = _compresor_voz(voz_comp, sr, cfg_c)
        crest_despues = crest_factor_db(out_c)
        check("compresor: reduce el crest factor",
              crest_despues < crest_antes - 0.3,
              f"crest {crest_antes:.1f} -> {crest_despues:.1f}")

        # --- de-esser: atenúa la banda 6-8kHz sin tocar el resto ---
        from mixmaster.audio_analysis import _filtrar_banda
        cfg_d = cargar_config_voz()["de_esser"]
        out_d = _de_esser(audio_in, sr, cfg_d)
        c0 = int(0.35 * SR)
        tramo_s = slice(c0, c0 + int(0.3 * SR))
        e_antes = float(np.sqrt(np.mean(
            _filtrar_banda(audio_in[tramo_s, 0], sr, 6000, 8000) ** 2)))
        e_despues = float(np.sqrt(np.mean(
            _filtrar_banda(out_d[tramo_s, 0], sr, 6000, 8000) ** 2)))
        check("de-esser: atenúa la sibilancia (6-8kHz)",
              e_despues < e_antes * 0.85, f"{e_antes:.4f} -> {e_despues:.4f}")
        # una sílaba (200 Hz, fuera de la banda del de-esser) no debe cambiar
        e_silaba_antes = float(np.sqrt(np.mean(
            _filtrar_banda(audio_in[silaba, 0], sr, 150, 300) ** 2)))
        e_silaba_despues = float(np.sqrt(np.mean(
            _filtrar_banda(out_d[silaba, 0], sr, 150, 300) ** 2)))
        check("de-esser: no toca la voz fuera de la banda de sibilancia",
              abs(e_silaba_despues - e_silaba_antes) < e_silaba_antes * 0.05,
              f"{e_silaba_antes:.4f} vs {e_silaba_despues:.4f}")

        # --- matching de referencia: acerca el balance tonal, acotado ---
        # Referencia = la misma voz pero MÁS BRILLANTE (agudos +6dB): el
        # matching debe subir los agudos de la voz hacia ella, sin pasarse
        # del tope de ±2 dB.
        from mixmaster.voice_processing import _match_referencia
        from scipy import signal as sp2
        sos_hi = sp2.butter(2, 3000, "high", fs=SR, output="sos")
        ref_brillante = audio_in + sp2.sosfiltfilt(sos_hi, audio_in, axis=0) * 1.0
        wav_ref = tmp / "ref_brillante.wav"
        sf.write(str(wav_ref), np.clip(ref_brillante, -0.99, 0.99), SR)

        cfg_m = cargar_config_voz()["match_referencia"]
        out_m, corr = _match_referencia(audio_in, sr, wav_ref, cfg_m)
        check("match ref: devuelve corrección por banda", bool(corr), str(corr))
        check("match ref: respeta el tope de ±2 dB",
              all(abs(v) <= 2.0 + 1e-9 for v in corr.values()), str(corr))
        check("match ref: sube los agudos hacia la referencia brillante",
              corr.get("high", 0) > 0 or corr.get("air", 0) > 0, str(corr))
        check("match ref: NUNCA sube sub/low (solo corta)",
              corr.get("sub", 0) <= 0 and corr.get("low", 0) <= 0, str(corr))
        # El BRILLO RELATIVO (agudos/graves) debe subir tras aplicar el FIR.
        # Se mide la relación, no la energía absoluta de agudos: el matching
        # llega al brillo de la referencia sobre todo CORTANDO graves (ver la
        # corrección de arriba: low/low_mid -2.0, air +1.1), no subiendo todo
        # el tramo alto — medir solo agudos absolutos no captaría el cambio.
        def brillo(x):
            e_hi = float(np.sqrt(np.mean(_filtrar_banda(x[:, 0], sr, 6000, 16000) ** 2)))
            e_lo = float(np.sqrt(np.mean(_filtrar_banda(x[:, 0], sr, 60, 500) ** 2)))
            return e_hi / max(e_lo, 1e-12)

        b_antes, b_despues = brillo(audio_in), brillo(out_m)
        check("match ref: el brillo relativo sube hacia la referencia",
              b_despues > b_antes * 1.05, f"{b_antes:.4f} -> {b_despues:.4f}")
        # referencia idéntica a la voz → corrección ~nula (no inventa EQ)
        _, corr_igual = _match_referencia(audio_in, sr, wav_in, cfg_m)
        check("match ref: referencia idéntica no genera EQ", corr_igual == {},
              str(corr_igual))

        # --- pipeline completo, mono ---
        wav_out = tmp / "voz_procesada.wav"
        resumen = procesar_voz(wav_in, wav_out)
        check("procesar_voz: archivo de salida creado", Path(resumen["wav"]).exists())
        check("procesar_voz: detecta mono", resumen["mono"] is True)
        check("procesar_voz: target mono -16 LUFS", resumen["target_lufs"] == -16.0)
        check("procesar_voz: loudness en objetivo",
              abs(resumen["lufs_final"] - (-16.0)) < 1.0, f"lufs={resumen['lufs_final']}")
        check("procesar_voz: bajo el techo de true peak",
              resumen["true_peak_final"] <= -0.8, f"tp={resumen['true_peak_final']}")

        # --- pipeline completo, estéreo (duplicando el mono) ---
        wav_st = tmp / "voz_stereo.wav"
        sf.write(str(wav_st), np.repeat(audio_in, 2, axis=1), sr)
        wav_st_out = tmp / "voz_stereo_procesada.wav"
        resumen_st = procesar_voz(wav_st, wav_st_out)
        check("procesar_voz: detecta estéreo", resumen_st["mono"] is False)
        check("procesar_voz: target estéreo -19 LUFS", resumen_st["target_lufs"] == -19.0)
        check("procesar_voz: loudness estéreo en objetivo",
              abs(resumen_st["lufs_final"] - (-19.0)) < 1.0,
              f"lufs={resumen_st['lufs_final']}")

        # --- cfg custom (loudness distinto, etapas apagadas) ---
        cfg_custom = cargar_config_voz()
        cfg_custom["target_lufs_mono"] = -20.0
        cfg_custom["gate"]["activo"] = False
        wav_out2 = tmp / "voz_custom.wav"
        resumen2 = procesar_voz(wav_in, wav_out2, cfg=cfg_custom)
        check("procesar_voz: respeta target_lufs custom",
              abs(resumen2["lufs_final"] - (-20.0)) < 1.0, f"lufs={resumen2['lufs_final']}")

        # --- pipeline con referencia + target_lufs explícito (lo que usa la UI) ---
        wav_out3 = tmp / "voz_con_ref.wav"
        resumen3 = procesar_voz(wav_in, wav_out3, path_referencia=wav_ref,
                                target_lufs=-18.0)
        check("procesar_voz: acepta referencia y la reporta",
              resumen3["referencia"] == "ref_brillante.wav"
              and bool(resumen3["eq_referencia_db"]),
              f"ref={resumen3['referencia']} eq={resumen3['eq_referencia_db']}")
        check("procesar_voz: target_lufs explícito gana sobre el default",
              resumen3["target_lufs"] == -18.0
              and abs(resumen3["lufs_final"] - (-18.0)) < 1.0,
              f"lufs={resumen3['lufs_final']}")
        check("procesar_voz: sin referencia no reporta EQ",
              resumen["referencia"] is None and resumen["eq_referencia_db"] == {})

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
