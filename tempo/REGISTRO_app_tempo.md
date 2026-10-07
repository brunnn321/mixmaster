# Registro: poner temas a tempo fijo con click exacto (base para la app)

**Estado (2 oct 2026):** **8 de 8 temas procesados** (método v0.4).
**Resultado:** la batería cae a **±0–4 ms del click** en promedio general, y cada sección de 32 tiempos queda dentro de ±7 ms. Todo listo para arrastrar al compás 1 de Studio Pro.

---

## 1. Objetivo

Tomar un tema y dejarlo **exactamente** sobre la grilla de un tempo fijo, sin cambiar el tono, sin cortes ni huecos y sin arruinar la musicalidad. Junto con el tema, entregar un **click exacto**, para grabar encima en el DAW.

---

## 2. Cómo llegamos a esto (la historia, paso a paso)

| # | Intento | Resultado | Qué aprendimos |
|---|---|---|---|
| 1 | Studio Pro: *Detectar tempo → Extraer a pista de tempo* sobre la mezcla completa | Tempo entre 127 y 130, **no exacto** | Analizar la mezcla completa confunde la detección: guitarras y voces tapan los golpes |
| 2 | Click de Moises como referencia | **No cuadraba** | Moises **redondea su click en pasos de 20 ms**: intervalos de 420, 440, 460 ms… El error llega a ±20–30 ms |
| 3 | Golpes reales del **stem de batería** + estirar beat a beat (Rubber Band) | **3.7 ms** (Levántate) | La batería separada da posiciones exactas. Motor R3 → 9 ms; motor R2 `crisp 6` → 3.7 ms |
| 4 | Lo mismo, pero desde la **mezcla completa** (HPSS + beat tracker) | ~10 ms | Sin stems no llega a la precisión buscada. Hay que separar la batería primero |
| 5 | Tengo Sed: el final se va frenando (ritardando) | Forzarlo arruinaría el final | **Detectar tramos libres** (tempo fuera de ±3 %) y dejarlos naturales; el click los sigue |
| 6 | Creo en ti / Tengo Sed: medición del tempo global | 70.002 y 98.01 BPM **constantes** | **Ya estaban grabados con click.** El problema era el click de Moises y la posición del "1" |
| 7 | Te Doy Gloria: estirar daba 7.3 ms y sin tocar 5.6 ms | Estirar **empeoraba** | Nace el **modo estudio**: si el tema ya está a click, no se estira, solo se desplaza |
| 8 | Glorioso Día: el residuo (8.3 ms) superaba el umbral → estiró → 11–13 ms | Regla mal calibrada | Decidir por *tempo exacto y sin deriva entre tercios*, no por el residuo |
| 9 | **Glorioso Día "se siente movido"** (lo detectó el usuario de oído) | La canción quedó **~50 ms adelantada** respecto al click | El offset click↔batería se medía golpe por golpe y **se enganchó en un golpe falso** (dio 40 ms; el real era ~5 ms). Las métricas internas no lo vieron porque comparaban contra esa misma detección. Es una grabación en vivo (Passion), con secciones que se adelantan o atrasan 10–25 ms |
| 10 | **v0.4:** medir **promediando la batería** (ERP) en ventanas de 17 tiempos + **chequeo final independiente** contra el click de salida | Glorioso Día: secciones dentro de **±2 ms**. De Gloria En Gloria: de −10/+27 ms a **±3 ms** (una sección a −7) | Promediar muchos golpes es mucho más robusto que buscar golpe por golpe. **Siempre verificar contra el resultado final, no contra la propia detección** |

---

## 3. Método final (v0.3), automático

Script: `_app/stems_fix.py`
Uso: `python stems_fix.py "<carpeta stems Moises>" "<carpeta salida>" [BPM] [--forzar-estirar]`

1. **Decodificar** todos los stems a WAV de 44.1 kHz (ffmpeg).
2. **Clicks de Moises** = guía aproximada de dónde cae cada tiempo.
3. **Offset click↔batería (v0.4):** se **promedia |batería|** alrededor de todos los clicks (ERP) y se toma el ataque (50 % del pico). Ya no se busca golpe por golpe, porque podía engancharse en un golpe falso (caso Glorioso Día).
4. **Posición de cada tiempo (v0.4):** guía = click de Moises suavizado + corrección medida **promediando la batería en una ventana de 17 tiempos** alrededor de cada tiempo. Así se corrigen las secciones adelantadas o atrasadas sin meter ruido y se respeta el "feel" golpe a golpe del baterista.
5. **Tramos a tempo y tramos libres:** se endereza solo donde el tempo local está a ±3 % del BPM. El inicio y el final libres quedan naturales.
6. **Downbeat ("1"):** la caja cae en 2 y 4, y el bombo decide entre las dos fases posibles.
7. **Decisión de modo:**
   - **MODO ESTUDIO** (no toca el audio): ajuste lineal = BPM objetivo con un margen de ±0.05 %, cada tercio del tema a ±0.1 % **y ninguna sección de 24 tiempos corrida más de 8 ms**. Solo se **desplaza** el audio para que el "1" caiga al inicio de compás.
   - **MODO ESTIRAR**: mapa tiempo a tiempo (muestra real → muestra en la grilla) + Rubber Band R2 `--crisp 6` + 2.ª pasada. La 2.ª pasada mide el resultado con el mismo método robusto (ERP por ventanas) y corrige lo que queda. Se usa la pasada con menor error máximo por sección.
   - **CHEQUEO FINAL (v0.4):** se mide el ataque promedio de la batería **de salida** contra el **click de salida**. Si está a más de 3 ms, se corren todos los stems para dejarlo en 0. Este control es independiente de la detección.
8. **Entrada:** como máximo ~1 compás de click antes de la música.
9. **Salida:** cada stem + **MEZCLA** (suma de stems) + **CLICK** (1500 Hz en el 1, 1000 Hz en los demás; sigue los tramos libres) + `log.json` con todas las mediciones.
10. **Nunca se cambia el tono.** La afinación queda igual que el original (440 o 441 Hz, según el tema).

Fórmulas: duración del tiempo = 60 / BPM · muestra = segundos × 44 100 · factor local = duración en la grilla / duración real.

---

## 4. Resultados de los 8 temas

| Tema | BPM | Ajuste lineal | Modo | Final libre | Error final |
|---|---|---|---|---|---|
| Levántate y sálvame | 128 | 123–133 (varía) | estirar (v0.1, MP3) | — | 3.7 ms |
| Tengo Sed | 98 | 98.01 | estirar | sí (desde 5:45) | 3.6 ms |
| Creo en ti | 70 | 70.002 | estirar (v0.2) | — | 6.3 ms |
| Te Doy Gloria | 140 | 139.994 | **estudio** | sí (desde 4:35) | 5.6 ms |
| Está Cayendo | 65 | 65.000 | **estudio** | — | 7.6 ms |
| Tu Amor Por Mí | 160 | 159.9995 | **estudio** | — | 2.6 ms |
| Glorioso Día | 110 | 109.999 (en vivo, secciones ±25 ms) | estirar (v0.4) | — | secciones ±2 ms |
| De Gloria En Gloria | 128 | 127.999 (secciones ±24 ms) | estirar (v0.4) | — | secciones ±3 ms (máx. 7) |

- Variación natural del baterista: 2.6–5.2 ms. **Bajar de ahí no tiene sentido musical.**
- En baladas (65–70 BPM) la cifra de error es mayor porque la batería es suave y la medición tiene más ruido, no porque el tema esté corrido.
- **Verificación independiente (v0.4):** promedio de la batería de salida alrededor del click de salida, por secciones de 32 tiempos:
  - Tengo Sed: ±2 ms · Creo en ti: ±1 ms (una sección a −12) · Te Doy Gloria: +2…+7 ms · Tu Amor Por Mí: +2…+7 ms · Levántate: global +0.5 ms
  - Glorioso Día: ±2 ms · De Gloria En Gloria: ±3 ms (máx. 7) · Está Cayendo (versión entregada, v0.3): −9…+11 ms. Con v0.4 queda en ±3 ms; se puede reemplazar si hace falta.
- Downbeats detectados (fases 0–2): **pendiente confirmar de oído en el DAW.**

---

## 5. ¿Qué tanto se puede replicar? (evaluación honesta)

**Lección clave (Glorioso Día):** el oído del usuario detectó un error que las métricas internas no vieron. **Toda versión tiene que pasar un chequeo independiente contra el resultado final**, y la app debe mostrar ese chequeo.

**Funciona muy bien en temas como estos:**
- Grabaciones **de estudio, hechas con click**: 6 de 7 temas. Ahí el modo estudio deja el audio intacto y solo lo acomoda.
- Temas **repetitivos y sencillos**, con tempo **estable y "a tierra"** (sin cambios bruscos) y **con batería** clara.
- Finales con ritardando: se detectan y se respetan.

**Todavía NO está probado (riesgos reales):**
- **Grabaciones en vivo de verdad**, sin click y con el tempo moviéndose todo el tema. Solo Levántate se parecía a eso.
- **Baladas sin batería**, o tramos largos solo de piano o voz. Sin golpes de batería no hay referencia.
- **Cambios de compás** (6/8, 3/4), cambios de tempo a mitad del tema, rubatos en medio, silencios largos.
- **Temas sin stems:** desde la mezcla completa se llega a ~10 ms. Para mejorar, separar la batería con Demucs/UVR en la PC.
- **El "1" del compás** se adivina con una heurística y puede fallar. Hace falta poder corregirlo con un clic.

**Conclusión:** en este tipo de repertorio (alabanza de estudio, tempo estable) el proceso es **confiable y repetible**. Para temas más difíciles hay que probar y ajustar antes de confiar.

---

## 6. Cómo replicarlo (Windows)

**Instalar una vez:**
1. Python 3 (python.org), con "Add Python to PATH" marcado.
2. `pip install numpy scipy soundfile`
3. ffmpeg (build de gyan.dev) → agregar `bin` al PATH.
4. Rubber Band CLI (breakfastquay.com/rubberband) → al PATH. Solo se usa en modo estirar.

**Por cada tema:**
1. Moises → separar los stems **con metrónomo** → descargarlos en una carpeta. Dejar el nombre que pone Moises, que trae el BPM.
2. `python stems_fix.py "C:\...\Tema-A minor-140bpm-440hz" "C:\...\A TEMPO\Tema - 140 BPM"`
3. Revisar `log.json`: modo, error y downbeat.
4. Studio Pro: tempo = BPM del nombre → arrastrar todo al compás 1 → escuchar el "1".

---

## 7. Problemas técnicos encontrados (y su solución)

| Problema | Solución |
|---|---|
| Click de Moises redondeado a 20 ms; la mediana del BPM sale mal (Te Doy Gloria daba 142.8) | Usar siempre el **ajuste lineal** de los golpes de batería |
| Rubber Band R3 no respeta bien el mapa | R2 `--crisp 6` + segunda pasada |
| Falta de memoria con HPSS en paralelo | Procesar de a uno y en bloques de 30 s |
| Envío a la PC: límite de 30 MB por archivo y "HTTP 400" en archivos de ~27 MB | FLAC (sin pérdida) en **pedazos de 20 MB**, unidos en la PC y verificados con **MD5** |
| El envío agrega una etiqueta ID3 (C2PA) de 5822 bytes al inicio del primer pedazo | Quitarla antes de unir; verificar con MD5 |
| MP3 agrega un silencio inicial (riesgo de desfase) | Entregar en FLAC/WAV |
| Copiar entre carpetas conectadas por separado es lento (~6 MB/s) | Guardar directo en `A TEMPO` |
| Archivos bloqueados mientras están abiertos en Studio Pro | Borrar cuando el proyecto esté cerrado |
| Offset mal medido golpe por golpe (Glorioso Día, −50 ms) | Medir promediando la batería (ERP) + chequeo final contra el click de salida |
| Nombres de stems mal leídos cuando el título tiene mayúsculas ("LETRA") | Regex: `-(nombre)-[A-G][b#]? (major|minor)`, sin ignorar mayúsculas |

---

## 8. Próximos pasos para la app

1. **Botón "mover el 1"** (±1 tiempo) y elección del BPM.
2. **Exportar el mapa de tempo como MIDI** (.mid), para que el metrónomo de Studio Pro siga también los finales libres.
3. **Integrar Demucs** (separar batería) para temas sin stems → objetivo ≤ 5 ms.
4. **Modelo de downbeat entrenado** (madmom / Beat This!) en lugar de la heurística.
5. **Reporte por tema:** modo, tramos libres, error y avisos ("sin batería en 0:00–0:40", etc.).
6. Opción de **afinar a 440 Hz exactos** (por ejemplo −3.9 cents para los temas en 441).
7. **Probar con temas difíciles:** en vivo sin click, 6/8, baladas sin batería, cambios de tempo.

Herramientas: Python, numpy, scipy, soundfile, librosa (pruebas sin stems), ffmpeg, Rubber Band 3.3, Demucs/UVR (pendiente).
