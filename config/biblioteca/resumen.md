# Resumen de la biblioteca — 21/11/2026 18:35

**21 temas analizados.** Detalle completo de cada uno en `analisis.jsonl`.

## 1. Dónde se equivoca la app

### Zonas: ¿cuántos masters profesionales marcaría como problema?
Un master profesional casi nunca debería saltar (lo esperable es menos del 5 %). Si una zona salta mucho, su norma está mal calibrada.

| Zona | Saltan | Norma actual (media ± desvío) | Norma medida en tu biblioteca | Veredicto |
|---|---|---|---|---|
| retumbe | 0 % | +4.2 ± 3.0 | -0.3 ± 6.0 | bien |
| embarrado | 33 % | -0.5 ± 1.9 | +2.1 ± 1.9 | mal calibrada: corrige de más |
| encajonado | 14 % | -0.3 ± 1.5 | -0.9 ± 2.9 | mal calibrada: corrige de más |
| aspero | 29 % | +3.2 ± 2.2 | +5.6 ± 5.4 | mal calibrada: corrige de más |
| sibilante | 10 % | +0.6 ± 1.7 | +0.3 ± 2.5 | revisar |

### Control de calidad: falsas alarmas en masters profesionales
Lo esperable en música publicada es verde casi siempre.

| Chequeo | Verde | Aviso | Mal |
|---|---|---|---|

### Volumen y dinámica reales (mediana, del 10 % al 90 %)

- **Volumen:** -11.4 LUFS (de -14.2 a -8.7)
- **Crest (dinámica):** 13.4 dB (de 11.3 a 17.0)
- **Pico real:** -0.1 dBTP (de -0.5 a 1.7)
- **Correlación estéreo:** 0.9  (de 0.7 a 1.0)
- La app usa por defecto: −10,5 LUFS (tu zona aprobada), techo −1 dBTP y crest objetivo ~10 dB.

## 2. Por carpeta (artista o género)

| Carpeta | Temas | LUFS | Crest | Pico | Correl. | Retumbe | Barro | Encajonado | Aspereza | Sibilancia |
|---|---|---|---|---|---|---|---|---|---|---|
| (sin carpeta) | 16 | -12.2 | 14.2 | -0.1 | 1.0 | -0.8 | +3.0 | -1.7 | +5.7 | -0.6 |
| Work 1 - Kazuki Isogai | 5 | -8.9 | 11.5 | 0.5 | 0.7 | +6.2 | +0.8 | +2.7 | +1.8 | +1.9 |

---
Normas sugeridas guardadas en `normas_sugeridas.json` (no se aplican solas: se revisan juntas antes de cambiar la app).