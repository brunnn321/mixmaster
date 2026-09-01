"""Test de automezcla.py: clasificación de rol, detección de pares L/R,
plan de nivel+panning, y ley de panning. Sin pytest.

Uso:  .venv\\Scripts\\python tests\\test_automezcla.py
"""

import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mixmaster.automezcla import (
    aplicar_pan, calcular_plan, clasificar_rol, detectar_par,
)
from mixmaster.processing import sumar_stems

SR = 44100


def main() -> int:
    fallos = []

    def check(nombre: str, cond: bool, detalle: str = ""):
        estado = "OK " if cond else "FAIL"
        print(f"[{estado}] {nombre}" + (f" — {detalle}" if detalle else ""))
        if not cond:
            fallos.append(nombre)

    # --- detección de pares --- (detectar_par devuelve una CLAVE DE
    # AGRUPACIÓN, no necesariamente el nombre legible — ver docstring)
    check("par L/R: GTR L -> clave ('gtr',), lado A",
          detectar_par("GTR L") == (("gtr",), "A"))
    check("par L/R: GTR R -> clave ('gtr',), lado B",
          detectar_par("GTR R") == (("gtr",), "B"))
    check("par numérico: TROMP 1 -> clave ('tromp',), lado A",
          detectar_par("TROMP 1") == (("tromp",), "A"))
    check("par numérico: TROMP 2 -> clave ('tromp',), lado B",
          detectar_par("TROMP 2") == (("tromp",), "B"))
    check("sin par: KICK -> sin lado",
          detectar_par("KICK") == ("KICK", None))
    # nombre REAL (número de pista + timestamp DESPUÉS del canal) — bug
    # encontrado la primera vez: el número de pista (16 vs 18) rompía el
    # agrupamiento porque quedaba en la "base" comparada.
    base_a, lado_a = detectar_par("16-GTR L-260815_2214")
    base_b, lado_b = detectar_par("18-GTR R-260815_2214")
    check("par real con número de pista/timestamp: misma clave de agrupación",
          base_a == base_b, f"{base_a} vs {base_b}")
    check("par real: lados opuestos", lado_a == "A" and lado_b == "B")

    # --- clasificación de rol ---
    check("rol: 01-KICK -> kick", clasificar_rol("01-KICK-260815") == "kick")
    check("rol: 17-BASS -> bajo", clasificar_rol("17-BASS-260815") == "bajo")
    check("rol: 05-SNR UP -> snare", clasificar_rol("05-SNR UP-260815") == "snare")
    check("rol: 07-HH -> hats", clasificar_rol("07-HH-260815") == "hats")
    check("rol: 08-OVER -> overhead", clasificar_rol("08-OVER-260815") == "overhead")
    check("rol: 12-CONGA -> percusion_mayor", clasificar_rol("12-CONGA") == "percusion_mayor")
    check("rol: 14-BONGOES -> percusion_menor", clasificar_rol("14-BONGOES") == "percusion_menor")
    check("rol: 21-TROMP 1 -> vientos", clasificar_rol("21-TROMP 1") == "vientos")
    check("rol: 29-SAYMON -> generico (sin pista en el nombre)",
          clasificar_rol("29-SAYMON") == "generico")
    check("rol manual: 29-SAYMON con override -> voz_principal",
          clasificar_rol("29-SAYMON", {"29-SAYMON": "voz_principal"}) == "voz_principal")

    # --- ley de panning ---
    centro = aplicar_pan(np.array([1.0]), 0.0)
    check("pan centro: L=R aprox (-3dB cada uno)",
          abs(centro[0, 0] - centro[0, 1]) < 1e-9 and abs(centro[0, 0] - 0.7071) < 0.01,
          str(centro))
    hard_l = aplicar_pan(np.array([1.0]), -1.0)
    check("pan izq duro: R=0 aprox", abs(hard_l[0, 1]) < 1e-9, str(hard_l))
    hard_r = aplicar_pan(np.array([1.0]), 1.0)
    check("pan der duro: L=0 aprox", abs(hard_r[0, 0]) < 1e-9, str(hard_r))

    # --- plan completo sobre stems sintéticos con nombres reales ---
    tmp = Path(tempfile.mkdtemp(prefix="mixmaster_automezcla_"))
    try:
        carpeta = tmp / "stems"
        carpeta.mkdir()
        t = np.arange(int(SR * 0.5)) / SR
        nombres_reales = [
            "01-KICK-260815_2214", "17-BASS-260815_2214",
            "16-GTR L-260815_2214", "18-GTR R-260815_2214",
            "21-TROMP 1-260815_2214", "22-TROMP 2-260815_2214",
            "29-SAYMON-260815_2214",
        ]
        for idx, nombre in enumerate(nombres_reales):
            # frecuencia distinta por archivo: si L y R de un par llevaran
            # la MISMA señal, panearlos opuesto y sumar da un resultado
            # simétrico (L_total == R_total) por pura matemática — no
            # representa la realidad (cada mic capta algo distinto) y
            # esconde si el paneo se aplicó de verdad.
            señal = 0.3 * np.sin(2 * np.pi * (150 + idx * 37) * t)
            sf.write(str(carpeta / f"{nombre}.wav"), señal.reshape(-1, 1), SR)

        plan = calcular_plan(carpeta, roles_manual={"29-SAYMON-260815_2214": "voz_principal"})
        check("plan: KICK a nivel 0dB centro",
              plan["stems"]["01-KICK-260815_2214"]["ganancia_db"] == 0.0
              and plan["stems"]["01-KICK-260815_2214"]["pan"] == 0.0)
        check("plan: GTR L/R (nombre real, con nº de pista distinto) paneadas opuestas",
              plan["stems"]["16-GTR L-260815_2214"]["pan"] < 0
              < plan["stems"]["18-GTR R-260815_2214"]["pan"])
        check("plan: TROMP 1/2 (nombre real) paneadas opuestas",
              plan["stems"]["21-TROMP 1-260815_2214"]["pan"] < 0
              < plan["stems"]["22-TROMP 2-260815_2214"]["pan"])
        check("plan: SAYMON con override -> voz_principal, +2dB",
              plan["stems"]["29-SAYMON-260815_2214"]["rol"] == "voz_principal"
              and plan["stems"]["29-SAYMON-260815_2214"]["ganancia_db"] == 2.0)
        check("plan: sin_clasificar vacío (todo tuvo rol o override)",
              plan["sin_clasificar"] == [], str(plan["sin_clasificar"]))

        # --- integración: sumar_stems con plan_mezcla no rompe y produce
        # audio estéreo con diferencia L/R real (evidencia de que sí paneó) ---
        mezcla, sr = sumar_stems(carpeta, mejorar_percusion=False, plan_mezcla=plan)
        check("sumar_stems con plan: devuelve estéreo", mezcla.shape[1] == 2)
        dif_lr = float(np.mean(np.abs(mezcla[:, 0] - mezcla[:, 1])))
        check("sumar_stems con plan: L y R distintos (paneo real aplicado)",
              dif_lr > 1e-6, str(dif_lr))

        # sin plan -> comportamiento viejo intacto (todo centrado, L==R)
        mezcla_vieja, _ = sumar_stems(carpeta, mejorar_percusion=False)
        dif_lr_vieja = float(np.mean(np.abs(mezcla_vieja[:, 0] - mezcla_vieja[:, 1])))
        check("sumar_stems SIN plan: compatibilidad hacia atrás (L==R, todo centrado)",
              dif_lr_vieja < 1e-9, str(dif_lr_vieja))

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
