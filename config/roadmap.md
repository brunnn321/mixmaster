# MixMaster — Roadmap v1.0+

> Actualizado: 2026-07-30. Estado real, no aspiracional — se marca ✅ solo cuando
> está codeado Y probado. Objetivo: app robusta, profesional, que no se vuelva
> obsoleta — motor propio + aprendizaje continuo del sonido del usuario.
>
> **AUDITORÍA 2026-07-30:** se verificó con grep + `git log --all` cada ítem `[x]`
> de v0.9.x en adelante contra el código real. Se encontraron **2 fantasmas**
> (marcados hechos, inexistentes): "Altavoz pequeño" (`small_speaker_sim.py`,
> nunca commiteado) y "Dithering TPDF" (vivía en `export_destinos.py`, borrado
> con el ítem 3 sin portarlo). Todo el resto verificó OK. Ambos corregidos a
> `[~]` abajo con su explicación.

## ⏭️ PRÓXIMA SESIÓN (actualizado 2026-07-31, en este orden)

1. ~~Commitear el trabajo del 2026-07-30~~ ✅ hecho (`73974d3`, `8ca33e5`,
   `eb6762a` en `feature/modo-voz-podcast`).
2. ~~Limpiar el tracking de `logs/`, `proyectos/` y el cache~~ ✅ hecho
   (`8ca33e5`). Las referencias MP3 comerciales se **dejan trackeadas a
   pedido explícito de Bruno** (2026-07-30) — no es un pendiente, es decisión.
3. ~~Probar de oído el modo Voz y la vigilancia del DAW~~ ✅ hecho — Bruno
   confirmó (2026-08-05). Mergeado a `master` (`604da1f`).
4. **Rediseño visual — DESPUÉS del punto 3, acotado a lo que sigue** (2º
   veredicto de El Consejo, 2026-08-05, actualiza el del 2026-07-31 abajo).
   Bruno mostró referencias tipo iZotope Ozone/consola de mastering física
   y preguntó si se puede llegar a ESE nivel — respuesta honesta del
   Consejo: NO tal cual (son equipos de diseño dedicados / hardware de
   $200k), pero "que se sienta instrumento, no formulario oscuro" SÍ es
   alcanzable. Causa raíz identificada: hoy todo es QSS sobre widgets
   NATIVOS de Qt (QPushButton, QProgressBar, QSlider) — el QSS solo cambia
   color/borde/fuente, no la forma. Para el salto real hacen falta widgets
   CUSTOM (QWidget + `paintEvent()` propio con QPainter). Orden acordado:
   - Paso 1: definir el lenguaje visual UNA vez antes de construir nada —
     un estilo de "panel" (fondo, borde, radio, tipografía de valores tipo
     display digital/mono) y un estilo de "control" (mismo tratamiento de
     glow/gradiente) que se repite en TODO. Sin esto cada widget nuevo
     queda como isla.
   - Paso 2: PRIMER widget real construido = el medidor LED (`_MedidorLED`,
     ya existe, hoy QSS sobre QProgressBar) reescrito con QPainter propio,
     glow por celda (`QRadialGradient`/`QGraphicsDropShadowEffect`, ya
     disponibles en PySide6, sin librería nueva). Es el más chico y barato,
     valida el patrón completo antes de extender a algo más grande.
   - Paso 3: con el patrón validado, un knob circular custom reusable
     (QWidget + QPainter, arco con `QPainterPath` + `QConicalGradient`)
     en vez de QSlider nativo, mismo lenguaje visual del paso 1.
   - Paso 4 (opcional, el más caro): migrar gráficas de matplotlib a
     pyqtgraph (curvas con relleno degradado, más fluido) — librería nueva,
     migra `graficas.py` entero. Queda de último a propósito.
   - Techo explícito: estos 4 puntos y PARAR. No reemplaza el roadmap real
     (checklist pre-mezcla, export de stems, siguen abiertos abajo).
5. Si queda tiempo: cualquiera de los `[ ]` abiertos de abajo (ninguno urgente).

## 🎙️ Modo Voz/Podcast — validado de oído (2026-08-01)

Probado con audio real de Bruno (AT2020 + antipop, referencia Radiolab). 3 rondas de ajuste con datos medidos, no a ciegas:

- [x] **Matching tonal FINO** (1/3 de octava, no 7 bandas) — con 7 bandas el resultado quedaba "distinto" a la referencia aunque el EQ estuviera dentro de tope; medido: 5-6 de 7 bandas topeaban en ±2 dB, faltaba resolución. Ahora reusa `espectro_suavizado`/`_curva_fir_fina` del motor musical (que YA usa este modo por defecto — voz se puso al día, no es una mejora nueva para música).
- [x] **Tope subido a ±6 dB** (era ±2) — el gap real entre una toma cruda con antipop (menos efecto de proximidad) y una referencia ya masterizada puede ser de +7 dB en graves. Medido con audio real, no estimado.
- [x] **`solo_cortar` reducido a solo "sub"** (era sub+low) — "low" (60-200 Hz) es el cuerpo/calidez de la voz, no rumble; impedir que suba privaba de la corrección más necesaria. "sub" (20-60 Hz) sigue sin poder subir: ahí sí es solo ruido de manejo.
- [x] **Bug: cargar referencia en modo Voz corría el análisis de MÚSICA** (`_analizar_auto`, ~10s: MFCC, imaging, spectral flux…) y encima registraba la grabación como "mezcla propia" del género activo (`math_rock`), contaminando el aprendizaje de música con datos de voz. `_set_referencias_desde_paths` ahora corta directo a PASO 3 si el modo es voz.
- [x] **Grabación + referencia se copian a `salida/` del proyecto** junto al resultado — para voz no hay biblioteca curada como en música, suelen ser archivos sueltos (una descarga, una toma) que se pueden perder si se borran de donde estaban.
- [ ] Al terminar el proceso, `os.startfile` no siempre parece abrir la carpeta visiblemente — sin excepción en el log, sospecha de que la abre detrás de la ventana (mismo problema de foco de Windows que tuvo la ventana principal). Sin confirmar si es un bug real; pendiente que Bruno confirme si la carpeta aparece en la barra de tareas.
- Config de voz sigue SIN persistir a disco (a diferencia de música con `config/master.json`) — cada apertura usa los defaults del código. Suficiente por ahora.

## 🧭 RUTA ACTIVA (acordada 2026-07-23)

### A · Referencias como presets
- [x] Análisis profundo por referencia — tilt, definición de graves, punch, centroide, rolloff, PLR + caché VERSIONADO (`ANALISIS_VERSION_REF`). `audio_analysis.py`.
- [x] Colapsado "género" → sacado de TODA la UI (top bar, Settings, chat, botones "regla del género"). El motor interno sigue usando un bucket único, pero el usuario ya no ve la palabra "género" en ningún lado.
- [x] 1 referencia por master — `_set_referencias_desde_paths` ahora reemplaza (no acumula); si sueltan varias usa la primera y avisa. Selector de archivo también es de 1 solo.
- [x] Ficha rica visible por referencia — `ui/ficha_referencia.py`, botón "🔍" en cada chip. Espectro (gráfico), inclinación tonal + interpretación, definición de graves + interpretación, punch, PLR, crest, LUFS, centroide/rolloff, ancho estéreo por banda (barras). Todo visual, reusa estilo de graficas.py.
- [ ] Sugerencia: "de tu biblioteca, estas 3 se parecen a tu mezcla".

### B · Tempo Detective — DESCARTADO POR EL USUARIO (2026-07-23)
BPM/tempo tool eliminado por completo a pedido del usuario (`tempo_tool.py` borrado, menú "🥁 BPM" sacado, madmom no se pudo instalar en Python 3.14/numpy 2.x — confirmado, no reintentar sin cambiar de entorno). No retomar salvo que el usuario lo pida explícitamente de nuevo.

## 🔧 Fixes de UX pedidos tras primera prueba en vivo (2026-07-22)

- [x] Crash al agregar referencias rápido — causa raíz: hilo de análisis se pisaba con uno nuevo antes de terminar, Python lo destruía a medio correr. Fix: guard contra análisis concurrente + `setParent(self)` en todos los workers.
- [x] `logs/crash.log` — `faulthandler` captura crashes nativos que no pasan por el log normal.
- [x] Botón Proyecto → 🗑 Borrar proyecto (con confirmación, irreversible).
- [x] Barra de progreso más visible (26px, texto %, color contrastado).
- [x] Botón "MASTER FINAL" grande y notorio (antes se perdía).
- [x] Espectro fino de 40 bandas (1/3 octava) en el reporte, además del resumen de 7 bandas — reusa `espectro_suavizado()` ya existente para matching.
- [x] Goniómetro embebido en PASO 2 (antes ventana aparte) — sigue siendo foto de la mezcla completa, no en vivo (documentado como limitación honesta).
- [x] Reproductor de escucha comparada: 4 fuentes reales (pre-master / master / M50x / altavoz) + barra de reproducción con seek, antes solo tenía 3 y sin control de posición.
- [x] A/B ciego embebido en PASO 3 (antes ventana aparte) — al elegir revela AMBAS (A y B), no solo la elegida, y la decisión se registra en `decisiones-y-feedback.md`.
- [~] Altavoz pequeño: DESCARTADO (2026-07-29) — se había marcado `[x]` pero `small_speaker_sim.py` nunca existió en el repo (ni en git history), el combo real solo tiene pre-master/master/M50x. Al revisar, sin curva medida real de un modelo específico no vale la pena inventar una aproximación genérica. No retomar salvo pedido explícito.
- [ ] Simulación de más dispositivos (TV, otros audífonos): DESCARTADO para TV/parlantes (no existen mediciones reales publicadas, sería inventado). Abierto a sumar más audífonos SI existen en la base AutoEQ real.

## ✅ COMPLETADO (v0.9.x)

- [x] Limpieza UX — caja única, chips referencias con ✕, nombres export con LUFS, carpetas perezosas
- [x] M50x calibration + bypass A/B (`m50x_calibration.py`, curva real AutoEq/oratory1990)
- [x] Learning "Tu sonido" — sugerencia LUFS + badge ✨ activación a 5+ masters aprobados
- [ ] Reference caching — test manual de speedup pendiente de correr

---

## TIER 2 — Próximo en cola (estándar profesional real)

Orden de trabajo: 1 y 2 primero (gap técnico de estándar broadcast/streaming),
luego el resto según se vaya confirmando.

1. [x] **True-peak con oversampling 4x** — ya estaba implementado (`audio_analysis.py::true_peak_db`, `resample_poly` 4x) — verificado 2026-07-21
2. [~] **Dithering TPDF en exports 16-bit** — marcado `[x]` pero vivía en `export_destinos.py::_dither_tpdf`, módulo eliminado al descartar el ítem 3 (multi-destino) sin portar el dithering a ningún lado. Corregido 2026-07-30 (auditoría tras encontrar el fantasma de "Altavoz pequeño"): HOY no hay exports de 16-bit en ningún lado del pipeline (todo sale 24-bit WAV + MP3), así que en la práctica no hace falta — pero si algún día se agrega un export de 16-bit, el dithering hay que reconstruirlo, no está.
3. [~] **Exportación multi-destino** — DESCARTADO 2026-07-21 (Bruno: nadie usa CD, no pidió YouTube; con el WAV+MP3 del master alcanza). Módulo eliminado.
4. [x] **Feedback hacia la mezcla (pre-master)** — ya existía: `_analizar_auto()` corre en PASO 2 contra referencias, ANTES de llegar a PASO 3 (master) — verificado 2026-07-21
5. [ ] **Checklist de arreglo pre-mezcla** — texto generado según diagnóstico + género (choque de frecuencias, masking rítmico)
6. [x] **Goniómetro (imagen estéreo)** — `ui/goniometro_dialog.py`, snapshot mid/side + correlación, botón en PASO 2 — 2026-07-21 (nota: es foto de la mezcla completa, no en vivo sincronizado al playback)
7. [~] **Simulación "escucha en auto/celular"** — marcado `[x]` por error, el archivo nunca existió (ver nota en "Fixes de UX"). Corregido 2026-07-29, descartado.
8. [x] **Session notes / diario de sesión** — `ui/notas_dialog.py`, guarda en `notas-sesion.md` por proyecto, menú "📝 Notas" — 2026-07-21
9. [x] **Contraste entre secciones marcadas** (generalizado, no solo verso/coro — sirve para shorts) — `report.py`, línea "Mayor contraste" en el reporte — 2026-07-21
10. [x] **Detección de fatiga auditiva por sesión** — timer 90 min, aviso por bandeja — 2026-07-21
11. [x] **Gráfica VS REFERENCIA (delta por banda)** — `graficas.py::_BarrasDelta`, barra ▼ te falta (ámbar) / ▲ te sobra (azul) por banda vs la referencia. Sección estrella del monitor. — 2026-07-22
12. [x] **Diagnóstico por stem (coaching)** — `stem_diagnostico.py` + `ui/coaching_dialog.py`, botón "🔬 Diagnóstico de stems" en PASO 2. Reglas por tipo (bajo/batería/guitarra/voz) → observaciones accionables ("tu bajo no tiene growl en 150-400 Hz"). — 2026-07-22
13. [x] **Animaciones extendidas** — `_HoverGlow` reutilizable (halo animado en hover de botones secundarios) + `_MedidorLED` que se enciende progresivamente (LED por LED) al mostrar el monitor. Menú superior: hover nativo (Qt no anima items de menubar — limitación honesta). — 2026-07-22
14. [x] **Loudness War Score** — `graficas.py::_LoudnessWarScore`, mapa LUFS×Crest con zona sana (verde) y zona de riesgo/sobre-comprimido (roja), tu master marcado con punto. En el monitor, tras cada master.
12. [ ] **Export de stems de mastering** (bandas/M-S procesadas) — permite re-balance sin re-masterizar
13. [x] **Null test** — `null_test.py::generar_diferencia` (resta de fase, iguala loudness antes de restar, normaliza a -3dBFS) + menú "🔬 Null test". Probado: idénticos → silencio; con diferencia real → la detecta.
14. [x] **Integración DAW vía carpeta watched** — `daw_watch.py::DetectorBounces` + menú Proyecto → "📁 Carpeta del DAW…". **La ruta se guarda POR PROYECTO** (pedido de Bruno: poner la carpeta de exportación de cada canción del DAW), en `config-proyecto.json` dentro del proyecto — `Project.leer_config/set_config/carpeta_daw`, nuevo. Al aparecer un bounce nuevo avisa y lo carga con 1 clic (elegido sobre carga automática: no pisa lo que estés comparando). **Detalle clave:** el DAW escribe el archivo de a poco, así que un bounce NO se reporta hasta que su tamaño se mantiene igual entre dos revisiones — si no, se cargaba un WAV incompleto. Sondeo por QTimer cada 2 s en vez de QFileSystemWatcher (un listdir es barato y el watcher nativo pierde eventos). Test: `tests/test_daw_watch.py`, 16 checks. — 2026-07-30
15. [x] **A/B ciego** — `ui/ab_ciego_dialog.py`, compara los 2 masters más recientes del proyecto sin revelar cuál es cuál hasta elegir, menú "🙈 A/B ciego" — 2026-07-21

---

## Métricas aprendibles (extensión de "Tu sonido")

Backlog aparte, mismo mecanismo que LUFS (`learning.py` → `preferencias()`):

- [x] Crest factor objetivo por género — `preferencias()["crest_target"]`, mostrado en el badge ✨ — 2026-07-21
- [x] EQ "firma" — bandas que sistemáticamente subes/bajas — `preferencias()["eq_signature"]` (promedio por banda) — 2026-07-21
- [x] Ancho estéreo preferido por banda — `preferencias()["ancho_signature"]` — 2026-07-23
- [x] Ratio de compresión multibanda preferido — `preferencias()["multibanda_signature"]` — 2026-07-23
- [x] True peak margin habitual — `preferencias()["true_peak_margin"]` — 2026-07-23
- [x] Mono-bass crossover preferido — `preferencias()["mono_bass_hz"]` — 2026-07-23
- [x] Score mínimo aceptable (umbral personal) — `preferencias()["score_umbral"]` = el más bajo que SÍ aprobaste (piso real, no promedio). Avisa en `_preguntar_aprobado` si un master nuevo queda por debajo. — 2026-07-23
- [x] Referencias "ganadoras" — `preferencias()["referencias_top"]`, mostrado en el badge ✨ ("tu referencia habitual") — 2026-07-23
- [~] Transient shaping / correlación de fase / densidad-loudness: DESCARTADO por el user ("esto algún día, por ahora no sirve") — mismo destino que export de stems de mastering.
- [~] Resonancias recurrentes en mezclas propias / tiempo entre versiones: fuera de alcance (necesitan analizar pre-master, no guardado hoy) — no priorizado.

---

## Targets de loudness por plataforma (2026-07-23)

- [x] Selector de destino al masterizar — `loudness_targets.py` (Spotify -14, YouTube -14, Apple Music -16, Tidal -14, CD -9, streaming suave -11 — todos números públicos citados en el módulo) + opción "Personalizado" (tu aprendido) y "Otro" (manual). Reemplaza el input directo de LUFS en `_masterizar`.

## Reglas de trabajo

- No se pasa al siguiente ítem sin: código completo + test (unit o smoke) + prueba manual en la app
- Cada ítem terminado se mueve a "✅ COMPLETADO" con fecha
- El motor de audio (DSP ya validado de oído) no se toca salvo que el ítem lo requiera explícitamente
- **Antes de retomar un ítem marcado `[x]`, verificar que el código exista** (grep del
  archivo/función que dice haber creado + `git log --all` si no aparece). Se marcaron
  2 ítems como hechos sin estar — ver auditoría del 2026-07-30 arriba.
- **Al reusar un patrón de DSP de un módulo en otro, revisar si el contexto cambia el
  supuesto.** Caso real (2026-07-29, motor de voz): se copió el detector de envolvente
  con `filtfilt` (fase cero) desde `_comprimir_banda`, donde es CORRECTO a propósito
  (en mastering offline equivale a look-ahead perfecto y ayuda a cazar el pico), hacia
  el gate de voz, donde ROMPE el propósito — un gate debe reaccionar a lo que ya pasó,
  y al mirar "hacia adelante" la envolvente de la sílaba siguiente se filtraba hacia
  atrás en el tiempo y el gate nunca cerraba en los huecos. Fix: `lfilter` (causal).
  El patrón no era malo; estaba mal trasplantado. Aplica igual a causal vs. no-causal,
  offline vs. streaming, y por-banda vs. banda-ancha.

## Fixes reportados en prueba real (2026-07-29)

- [x] Modal bloqueante durante stems/análisis/master — v1 con `QProgressDialog` + `Qt.ApplicationModal` causó DEADLOCK REAL (confirmado en log: el worker nunca arrancaba). Causa: `QProgressDialog.setValue()` dispara `processEvents()` internamente, y se creaba/mostraba ANTES de arrancar el QThread → interbloqueo. Fix v2: sin modalidad nativa — `self.setEnabled(False)` en la ventana principal (bloqueo garantizado, sin loops nativos) + popup simple no-modal (QWidget con label+barra) solo informativo. Probado offscreen: enable/disable + progreso sin crash.
- [x] Bug real: export MP3 fallaba con `LibsndfileError: MPEG-1/2/2.5 only supports sample rates of 8000...48000` cuando el audio fuente tenía un sample rate no estándar (ej. 96000). Fix en `processing.py::masterizar`: si `sr` no está en la lista válida, resamplea SOLO la copia MP3 (el WAV master queda intacto en el sample rate original). Probado con sr=96000 → OK.
- [x] Popup de progreso más visible — mismo estilo que la barra verde de abajo (460×130, formato "%p% — %v/%m").
- [x] Protección contra mezclas ya comprimidas/limitadas — `_advertir_si_sobreprocesada()` en main_window, chequea crest<6dB / true peak>-0.3dBTP / clipping del diagnóstico previo, avisa ANTES de masterizar con motivo y opción de cancelar.
- [x] Carácter tonal (tilt, definición de graves, punch, centroide/rolloff, PLR) ahora también se calcula para LA MEZCLA (antes solo para referencias) — `audio_analysis.py::analizar_wav` sección `caracter`, visible en el reporte de texto. Mismos ejes que la ficha de referencias → comparable directo.
- [~] Documentado (sin código nuevo): formatos soportados (WAV/MP3/FLAC/OGG/AIFF directo; M4A/WMA necesitan ffmpeg, hoy fallan), sin límite de duración por código (memoria RAM es el límite real, todo se carga completo, no hay streaming/chunks). Cálculo real: 1 hora estéreo ≈ 2.5GB de audio base, pico ~20-30GB con las copias intermedias del pipeline → NO seguro hoy para audio de 1h+ (concierto/entrevista larga).
- [x] Limitador de 2 etapas con rodilla suave (soft-knee) — `processing.py::_limitador`. Etapa MACRO (lookahead 20ms) absorbe pasajes sostenidos por adelantado; etapa RÁPIDA (lookahead 5ms) atrapa picos puntuales. Rodilla suave (fórmula estándar Giannoulis/Massberg/Reiss, JAES/DAFx 2012) en vez de escalón duro → menos distorsión audible al empujar fuerte.
  - **Bug real encontrado y arreglado durante el testeo:** la primera versión (release macro = 80ms, rodilla doble ancho) actuaba como un TECHO PERMANENTE de loudness — por más ganancia que se metiera antes, convergía asintóticamente ~1 dB por debajo del target y no subía más (confirmado reproduciendo la convergencia paso a paso: se achataba en -9.2 LUFS con target -8.5, sin importar cuántas iteraciones). Causa: release demasiado lento mantenía la reducción activa incluso en pasajes más silenciosos, capando el promedio. Fix: release macro bajado a 1.5x el lookahead (30ms) y rodilla sin duplicar — converge correctamente (-8.5 objetivo → -8.82 real, dentro de tolerancia). Bucle de convergencia en `masterizar()` subido de 4 a 6 iteraciones como margen extra.
  - Probado: techo real (-1.0 dBTP) respetado tras el ajuste, sin NaN/clipping duro, test suite 100% verde (incluye el test que había detectado la regresión).
- [x] Detección de fase FINA — `audio_analysis.py::detectar_problemas_fase`. Antes solo había un promedio global de correlación L/R (podía esconder un tramo puntual fuera de fase). Ahora analiza por ventanas de 0.5s y aísla EXACTAMENTE cuándo hay problema (timestamp + correlación), no solo si en promedio lo hay. Alerta nueva + sección en el reporte de texto. Probado: detecta un tramo de 1s totalmente fuera de fase en medio de una señal correlacionada, con timestamp exacto.

## Aprendizaje de mezclas propias (2026-07-29)

- [x] Checkbox "Es una mezcla mía" en PASO 1 (marcado por defecto) — permite distinguir tus mezclas de audios de prueba/ajenos para no ensuciar el aprendizaje.
- [x] `learning.py::registrar_mezcla_propia()` — guarda el carácter tonal (inclinación, definición de graves, punch, centroide/rolloff, PLR) de cada mezcla marcada como propia, ANTES de masterizar (a diferencia de `registrar_aprobado()` que solo guarda el resultado final).
- [x] `learning.py::consejo_mezcla()` — a partir de 3 mezclas propias registradas, compara la mezcla actual contra el promedio histórico y muestra un bloque "— TU PATRÓN COMO MEZCLADOR —" arriba del reporte (ej. "tus graves suelen venir poco definidos", "tu inclinación tonal promedio es oscura"). Pedido explícito del user: que la app "aconseje o guíe" con datos, no solo mida el resultado final.
- Primera versión: comparaciones simples de 3 métricas. Ampliable con más historial (crest, ancho estéreo) siguiendo el mismo mecanismo.

## 🎙️ Modo "Voz / Podcast" — CONSTRUIDO (2026-07-30)

Feature grande, confirmada por el user ("me sirve, quiero hacerlo, es útil, incluso para limpiar voces solo"). Diseño acordado (corregido 2 veces por el user, sus correcciones eran válidas) e implementado:

- [x] **Selector manual al cargar** (PASO 1): "🎵 Música" (default) vs "🎙️ Voz / Podcast" — `main_window.py::_modo_cambiado`, combo `combo_modo`. NO detección automática (no confiable). El botón principal cambia de "MASTER" a "PROCESAR VOZ" según el modo.
- [x] **Motor propio** — `mixmaster/voice_processing.py`: gate (expansor descendente), compresor suave con makeup por RMS, de-esser (banda 5-9 kHz comprimida, resto intacto), limitador (reusa el de 2 etapas del motor musical), normalización LUFS con convergencia. Config en `CONFIG_VOZ_DEFAULT`.
- [x] **SÍ admite referencia** (corrección del user) — opcional. `_match_referencia()`: matching tonal SUAVE de 7 bandas, tope ±2 dB (vs ±4 en música) y por bandas, NO 1/3 de octava — en voz una curva fina copia el timbre de otra persona y suena artificial. sub/low solo se pueden CORTAR, nunca subir (si la ref trae música o una voz más grave, subir el grave mete retumbe). Nivela la ref por LUFS antes de comparar.
- [x] **Loudness NO fijo** (corrección del user) — default -16 mono / -19 estéreo (estándar de plataformas de podcast) pero el diálogo lo deja ajustar de -30 a -6.
- [x] **Caso de uso mínimo sin referencia** — sin referencia el motor solo limpia/nivela (gate + comp + de-esser + limitador), sin nada de matching. Funciona, testeado.
- [~] **Motor liviano "por bloques"** — CORREGIDO respecto al diseño: NO se hizo streaming por bloques desde disco, y está documentado por qué en el docstring del módulo. La cadena de voz no tiene los stages pesados del motor musical (sin FIR de matching fino, sin copias multibanda, sin split de bandas), así que cargar completo en memoria ya es seguro para 1h+ — el riesgo de memoria documentado arriba era del motor MUSICAL, no de este. Si algún día hace falta audio de varias horas, ahí sí conviene streaming real.
- Test propio: `tests/test_voice_smoke.py`, 22 checks (gate cierra en los huecos pero no aplasta la sílaba, compresor baja el crest, de-esser ataca solo su banda, matching acotado y direccional, pipeline mono/estéreo/con-ref/target-custom). Todos verdes + `test_smoke.py` general sigue 100%.
- **Bug real encontrado y arreglado durante el testeo:** el gate no cerraba nunca. Causa: se había copiado el detector de envolvente con `filtfilt` (fase cero) desde `_comprimir_banda` del motor musical, donde es correcto A PROPÓSITO (en mastering offline equivale a look-ahead perfecto y ayuda a cazar el pico). En un gate eso ROMPE el propósito: la envolvente de la sílaba siguiente se filtra hacia atrás en el tiempo y mantiene la puerta abierta en el silencio. Fix: `lfilter` (causal). Ver la regla de trabajo que quedó de esto en "Reglas de trabajo".

**PENDIENTE (siguiente vuelta):** probar de oído con voz real de Bruno y afinar los defaults del gate/compresor/de-esser (hoy son conservadores y validados solo con señal sintética). El `_match_referencia` en particular nunca se escuchó, solo se midió.

## Limpieza UX pedida y hecha en el momento (2026-07-29, "ahora ya es después")

- [x] Botón MASTER rediseñado — antes chico, mal proporcionado, ícono "🎵" sin relación. Ahora: ancho completo (era el botón más importante y estaba metido en una esquina), altura 64px, sin ícono, texto "MASTER" con letter-spacing, más peso visual.
- [x] Chat ELIMINADO por completo — `ui/chat_dialog.py` borrado, menú y método `_abrir_chat` sacados. Razón del user: no conecta a ninguna IA de verdad, solo arma texto para copiar/pegar a mano — "es un paso extra sin automatizar", menos útil que las Notas. `chat_context.py` (el que arma el texto) se queda intacto por si se conecta a una API de verdad más adelante.
- [x] Menú consolidado — Historial/Masters/Notas/Null test/A-B ciego (antes 5 botones sueltos compitiendo por espacio en la barra) ahora agrupados en un solo menú desplegable "🛠 Herramientas".
- [x] Diagnósticos CONECTADOS a algo útil — antes quedaban guardados sin usarse para nada (el user cuestionó por qué guardar algo que no sirve). Ahora `report.py::comparar_progreso()`: cada nuevo análisis se compara automático contra el anterior del proyecto (crest, LUFS, definición de graves, distancia promedio a la referencia, nº de alertas) y se muestra arriba del reporte como "— PROGRESO vs. tu análisis anterior —". Decidido explícitamente NO borrar `decisiones-y-feedback.md`/Historial — a diferencia de los diagnósticos, esa función SÍ se usa activamente (ver/editar/borrar desde el menú), solo no alimenta aprendizaje automático — no es lo mismo que "guardado sin usar".
- [x] Settings limpio de restos del chat eliminado — el user notó que quedaron colgados "Modo de conexión / API key / Modelo" en Settings sin ningún uso real (ese modo "api" nunca se conectó a nada, era código muerto desde antes). Sacados de `settings_dialog.py`, `settings.py` (DEFAULTS) y `ui/first_run.py` (paso completo de "elegir modo de conexión + pegar API key" en el asistente inicial, ahora solo pide carpeta de proyectos + perfil). `claude_client.py` borrado (archivo 100% muerto, nada lo importaba ni siquiera antes de esta limpieza).
- [x] "Olvidar lo aprendido" ELIMINADO del menú Settings — a pedido explícito del user (confirmado vía pregunta directa: "sacarla del todo"). Aclarado antes de sacarla que solo reseteaba preferencias aprendidas (LUFS/crest/EQ/umbral de calidad), nunca borraba masters ni proyectos — pero el user prefirió sacarla igual. La función `learning.olvidar()` se queda en el backend (usada por tests), solo se sacó el acceso desde la UI.
- [x] Caché de referencias migrado de clave=RUTA a clave=HASH DE CONTENIDO — `audio_analysis.py::_hash_archivo` (blake2b sobre los bytes del archivo, rápido — solo I/O, sin decodificar audio). Ahora el mismo archivo de referencia se reconoce sin importar en qué carpeta/proyecto esté o si se renombró — antes solo funcionaba si era literalmente la misma ruta. Migración automática y sin pérdida: si existe una entrada vieja (clave=ruta) con mismo mtime+size, se reusa su análisis ya hecho en vez de recalcular — probado con una referencia real de la biblioteca: migró en 0.1s en vez de re-analizar el audio completo. Los 52 análisis ya guardados en `cache_referencias.json` se migran solos la primera vez que se vuelven a usar, no se pierden.
