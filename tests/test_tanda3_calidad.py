"""Tests de la tanda 2/10 b (investigación de calidad, ítems 3, 6 y 14):
fase/polaridad automática, pasa-altos por rol + EQ espejo, y medidores de
bombeo y distorsión. Sin pytest.

Uso:  .venv\\Scripts\\python tests\\test_tanda3_calidad.py
"""

import sys
from pathlib import Path

import numpy as np
from scipy import signal

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mixmaster.processing import (_alinear_fase, _desplazar, _filtros_por_rol,
                                  _medir_limitacion)

SR = 44100
rng = np.random.default_rng(3)


def _estereo(x: np.ndarray) -> np.ndarray:
    return np.repeat(x.reshape(-1, 1), 2, axis=1)


def _ruido_banda(dur_s: float, f_hi: float = 4000.0) -> np.ndarray:
    sos = signal.butter(4, f_hi, "lowpass", fs=SR, output="sos")
    return signal.sosfilt(sos, rng.standard_normal(int(SR * dur_s)))


def _corr(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.corrcoef(a, b)[0, 1])


def _nivel_db(x: np.ndarray, f: float) -> float:
    t = np.arange(len(x)) / SR
    return 20 * np.log10(abs(np.sum(x * np.exp(-2j * np.pi * f * t))) + 1e-12)


def main() -> int:
    fallos = []

    def check(nombre: str, cond: bool, detalle: str = ""):
        estado = "OK " if cond else "FAIL"
        print(f"[{estado}] {nombre}" + (f" - {detalle}" if detalle else ""))
        if not cond:
            fallos.append(nombre)

    # --- desplazamiento sub-muestra
    x = _estereo(_ruido_banda(1.0))
    ida_vuelta = _desplazar(_desplazar(x, 2.3), -2.3)
    sl = slice(100, -100)
    check("desplazar 2.3 y volver: recupera la señal",
          _corr(ida_vuelta[sl, 0], x[sl, 0]) > 0.999, f"{_corr(ida_vuelta[sl, 0], x[sl, 0]):.5f}")

    # --- 3. fase y polaridad
    fuente = _ruido_banda(12.0)
    kick = _estereo(fuente)
    retardo = 2.37e-3 * SR  # 104.5 muestras
    over = -0.7 * _desplazar(kick, retardo) + 0.05 * _estereo(_ruido_banda(12.0))
    guit = _estereo(_ruido_banda(12.0))
    pistas = [kick.copy(), over.copy(), guit.copy()]
    corr_antes = _corr(pistas[1][:, 0], kick[:, 0])
    hechos = _alinear_fase(pistas, ["kick", "overhead", "guitarra"], ["Kick", "OH", "GTR"], SR)
    corr_despues = _corr(pistas[1][2000:-2000, 0], kick[2000:-2000, 0])
    check("fase: overhead invertido y corrido queda alineado con el bombo",
          corr_despues > 0.98, f"{corr_antes:+.2f} -> {corr_despues:+.3f}")
    check("fase: informa la polaridad invertida", any("polaridad" in h for h in hechos), str(hechos))
    check("fase: el ancla (bombo) no se toca", np.array_equal(pistas[0], kick))
    check("fase: la guitarra (otra familia) no se toca", np.array_equal(pistas[2], guit))
    otro = [kick.copy(), _estereo(_ruido_banda(12.0))]
    copia = otro[1].copy()
    _alinear_fase(otro, ["kick", "snare"], ["Kick", "Snare"], SR)
    check("fase: micrófonos sin bleed no se tocan", np.array_equal(otro[1], copia))

    # --- 6. pasa-altos por rol y EQ espejo
    t = np.arange(SR * 2) / SR
    tono = lambda f: _estereo(0.3 * np.sin(2 * np.pi * f * t))
    g40 = _filtros_por_rol(tono(40), SR, "guitarra", False)[:, 0]
    check("pasa-altos guitarra: 40 Hz baja más de 6 dB",
          _nivel_db(g40, 40) < _nivel_db(tono(40)[:, 0], 40) - 6)
    g1k = _filtros_por_rol(tono(1000), SR, "guitarra", True)[:, 0]
    check("pasa-altos guitarra: 1 kHz casi intacto",
          abs(_nivel_db(g1k, 1000) - _nivel_db(tono(1000)[:, 0], 1000)) < 0.3)
    b80 = _filtros_por_rol(tono(80), SR, "bajo", True)[:, 0]
    g80 = _filtros_por_rol(tono(80), SR, "guitarra", True)[:, 0]
    g80_sin = _filtros_por_rol(tono(80), SR, "guitarra", False)[:, 0]
    ref80 = _nivel_db(tono(80)[:, 0], 80)
    check("EQ espejo: el bajo sube en 80 Hz", _nivel_db(b80, 80) - ref80 > 1.0,
          f"{_nivel_db(b80, 80) - ref80:+.2f} dB")
    check("EQ espejo: la guitarra baja en 80 Hz",
          _nivel_db(g80, 80) < _nivel_db(g80_sin, 80) - 1.0)
    check("roles sin filtro (bombo) no cambian",
          np.array_equal(_filtros_por_rol(tono(40), SR, "kick", True), tono(40)))

    # --- 14. medidores
    pre = _estereo(0.3 * _ruido_banda(4.0, 8000))
    limpio = _medir_limitacion(pre, 0.5 * pre, SR)
    check("medidor: solo bajar volumen no es distorsión", limpio["distorsion_db"] < -60,
          str(limpio))
    recortado = np.clip(pre * 3, -0.5, 0.5)
    sucio = _medir_limitacion(pre, recortado, SR)
    check("medidor: el recorte duro se ve como distorsión", sucio["distorsion_db"] > -30,
          str(sucio))
    n = SR * 4
    tt = np.arange(n) / SR
    golpes = np.zeros(n)
    for i in range(0, n - SR // 4, SR // 2):
        golpes[i: i + SR // 8] = np.sin(2 * np.pi * 60 * tt[: SR // 8]) * np.exp(-tt[: SR // 8] / 0.04)
    mezcla = _estereo(0.6 * golpes + 0.1 * np.sin(2 * np.pi * 1000 * tt))
    env = signal.sosfiltfilt(signal.butter(2, 20, fs=SR, output="sos"), np.abs(golpes))
    bombeada = mezcla * (10 ** (-6 * env / env.max() / 20))[:, None]
    check("medidor: detecta bombeo con el grave", _medir_limitacion(mezcla, bombeada, SR)["bombeo"])
    check("medidor: sin bombeo no avisa", not _medir_limitacion(mezcla, mezcla * 0.8, SR)["bombeo"])

    print()
    if fallos:
        print(f"RESULTADO: {len(fallos)} fallo(s): {fallos}")
        return 1
    print("RESULTADO: todos los checks pasaron")
    return 0


if __name__ == "__main__":
    sys.exit(main())
