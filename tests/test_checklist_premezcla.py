"""Test del checklist pre-mezcla (sin UI, sin pytest).

Uso:  .venv\\Scripts\\python tests\\test_checklist_premezcla.py
"""

import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mixmaster.stem_diagnostico import checklist_pre_mezcla

SR = 44100
DUR_S = 2.0


def _tono(freq_hz: float, envolvente: np.ndarray | None = None, sr: int = SR) -> np.ndarray:
    t = np.arange(int(sr * DUR_S)) / sr
    señal = 0.5 * np.sin(2 * np.pi * freq_hz * t)
    if envolvente is not None:
        señal = señal * envolvente
    return np.repeat(señal.reshape(-1, 1), 2, axis=1)


def _pulsos(periodo_s: float, ancho_s: float = 0.05) -> np.ndarray:
    """Envolvente de pulsos periódicos — simula "pegar" a un ritmo dado."""
    t = np.arange(int(SR * DUR_S)) / SR
    fase = np.mod(t, periodo_s)
    return (fase < ancho_s).astype(np.float64)


def main() -> int:
    fallos = []

    def check(nombre: str, cond: bool, detalle: str = ""):
        estado = "OK " if cond else "FAIL"
        print(f"[{estado}] {nombre}" + (f" — {detalle}" if detalle else ""))
        if not cond:
            fallos.append(nombre)

    tmp = Path(tempfile.mkdtemp(prefix="mixmaster_checklist_"))
    try:
        # --- caso 1: 1 solo stem -> sin avisos ---
        solo = tmp / "solo"
        solo.mkdir()
        sf.write(str(solo / "bajo.wav"), _tono(100), SR)
        check("1 solo stem: sin avisos", checklist_pre_mezcla(solo) == [])

        # --- caso 2: dos instrumentos en bandas separadas -> sin choque ---
        separados = tmp / "separados"
        separados.mkdir()
        sf.write(str(separados / "bajo.wav"), _tono(80), SR)       # sub/low
        sf.write(str(separados / "aire.wav"), _tono(12000), SR)    # air
        avisos_sep = checklist_pre_mezcla(separados)
        check("bandas separadas: sin choque de frecuencia", avisos_sep == [], str(avisos_sep))

        # --- caso 3: mismo tono (mismo pico de banda) en dos stems, pegando
        # AL MISMO TIEMPO -> choque + masking rítmico detectado ---
        mismo_ritmo = tmp / "mismo_ritmo"
        mismo_ritmo.mkdir()
        pulso = _pulsos(periodo_s=0.5)
        sf.write(str(mismo_ritmo / "bajo.wav"), _tono(150, pulso), SR)
        sf.write(str(mismo_ritmo / "guitarra.wav"), _tono(180, pulso), SR)
        avisos_mr = checklist_pre_mezcla(mismo_ritmo)
        check("choque de frecuencia detectado", len(avisos_mr) >= 1, str(avisos_mr))
        check("masking rítmico detectado (mismo pulso)",
              any("MISMO TIEMPO" in a for a in avisos_mr), str(avisos_mr))

        # --- caso 4: mismo choque de banda pero pulsos DESFASADOS -> avisa
        # el choque pero marca que se turnan, no masking real ---
        turnos = tmp / "turnos"
        turnos.mkdir()
        pulso_a = _pulsos(periodo_s=0.5, ancho_s=0.05)
        t = np.arange(int(SR * DUR_S)) / SR
        pulso_b = (np.mod(t + 0.25, 0.5) < 0.05).astype(np.float64)  # desfasado 180°
        sf.write(str(turnos / "bajo.wav"), _tono(150, pulso_a), SR)
        sf.write(str(turnos / "guitarra.wav"), _tono(180, pulso_b), SR)
        avisos_t = checklist_pre_mezcla(turnos)
        check("choque de banda con pulsos desfasados: avisa igual", len(avisos_t) >= 1, str(avisos_t))
        check("pero marca que se turnan (no masking real)",
              any("se turnan" in a for a in avisos_t), str(avisos_t))

        # --- caso 5: sample rate inconsistente entre stems -> avisa ---
        distinto_sr = tmp / "distinto_sr"
        distinto_sr.mkdir()
        sf.write(str(distinto_sr / "bajo.wav"), _tono(100, sr=44100), 44100)
        sf.write(str(distinto_sr / "guitarra.wav"), _tono(100, sr=48000), 48000)
        avisos_sr = checklist_pre_mezcla(distinto_sr)
        check("sample rate distinto: avisa",
              any("sample rate" in a.lower() for a in avisos_sr), str(avisos_sr))
        check("sample rate distinto: menciona ambos stems",
              any("bajo" in a and "guitarra" in a for a in avisos_sr), str(avisos_sr))

        # --- caso 6: EQ complementario — bajo.wav vs guitarra.wav chocan en
        # "low" (60-200 Hz): _PRIORIDAD_BANDA dice bajo > guitarra ahí, así
        # que debe sugerir cortar la guitarra, no el bajo ---
        eq = tmp / "eq"
        eq.mkdir()
        pulso = _pulsos(periodo_s=0.5)
        sf.write(str(eq / "bajo.wav"), _tono(150, pulso), SR)
        sf.write(str(eq / "guitarra.wav"), _tono(180, pulso), SR)
        avisos_eq = checklist_pre_mezcla(eq)
        check("EQ complementario: sugiere cortar guitarra (bajo manda en low)",
              any("cortá «guitarra»" in a for a in avisos_eq), str(avisos_eq))
        check("EQ complementario: no sugiere cortar el bajo",
              not any("cortá «bajo»" in a for a in avisos_eq), str(avisos_eq))

        # --- caso 7: mismo tipo en ambos lados -> sin convención clara ---
        empate = tmp / "empate"
        empate.mkdir()
        sf.write(str(empate / "guitarra1.wav"), _tono(150, pulso), SR)
        sf.write(str(empate / "guitarra2.wav"), _tono(180, pulso), SR)
        avisos_empate = checklist_pre_mezcla(empate)
        check("EQ complementario: mismo tipo -> sin convención clara",
              any("mismo tipo, no hay convención clara" in a for a in avisos_empate),
              str(avisos_empate))

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
