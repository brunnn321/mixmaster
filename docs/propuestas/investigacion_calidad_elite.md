# Investigación: calidad de sonido nivel élite

> 30/09/2026. **Solo investigación: nada implementado.** Bruno elige qué se hace.
> Armado con el mentor (expansión técnica) y El Consejo (orden por impacto).
>
> Sustento de cada afirmación (regla del mentor):
> **[F]** física o psicoacústica · **[E]** práctica de un estilo o escuela ·
> **[C]** convención de oficio, se rompe cuando conviene.

---

## 1. Lista para elegir (orden recomendado por El Consejo)

Esfuerzo: 🟢 chico · 🟡 medio · 🔴 grande. Etapa: MZ = mezcla desde stems, MA = master.

| # | Mejora | Qué se oye | Esf. | Etapa |
|---|---|---|---|---|
| 1 | Comparar siempre a igual sonoridad | Deja de engañar el "más fuerte suena mejor" | 🟢 | todo |
| 2 | Separar la referencia en instrumentos (demucs) y medir su balance | Voz, batería, bajo y guitarras al nivel de un disco real | 🟡 | MZ/MA |
| 3 | Fase y polaridad automáticas, con precisión sub-muestra | Bombo y bajo con golpe; el grave deja de desaparecer | 🟡 | MZ |
| 4 | Gate/expansor de toms, bombo y caja en vivo | Batería limpia, sin la bola de ruido del bleed | 🟡 | MZ |
| 5 | Rider de voz + compresión en serie | Voz siempre adelante, pareja, sin saltos | 🟡 | MZ |
| 6 | Pasa-altos por rol + desenmascarado dinámico | Claridad: cada instrumento en su lugar | 🟡 | MZ |
| 7 | Compresión paralela y bus de batería | Batería grande y con pegada, estilo metal moderno | 🟢 | MZ |
| 8 | Bajo dividido (limpio abajo, saturado arriba) | Bajo que se escucha en celular sin embarrar | 🟢 | MZ |
| 9 | Matching dinámico por banda (no solo espectro) | El master "se mueve" como la referencia | 🟡 | MA |
| 10 | Clipper + limitador multietapa sensible a transitorios | Más volumen sin aplastar ni bombear | 🟡 | MA |
| 11 | Supresión de resonancias (tipo soothe) | Se van los pitidos y la aspereza de guitarras | 🟡 | MZ/MA |
| 12 | Vista previa de códec (MP3/AAC) | El master no se rompe en Spotify/YouTube | 🟢 | MA |
| 13 | Saturación (cinta/válvula) con sobremuestreo + bus 2:1 | Pegamento y calidez, sin ruido digital | 🟡 | MZ/MA |
| 14 | Medidores de artefactos (bombeo, distorsión del limitador) | La app avisa cuando el master empeoró | 🟡 | QA |
| 15 | Refuerzo de batería con samples | Bombo y caja de disco Sumerian | 🔴 | MZ |
| 16 | Exciter de graves (fundamental faltante) | Graves audibles en parlantes chicos | 🟢 | MA |
| 17 | EQ de fase mínima / lineal según la banda | Graves firmes sin pre-eco en los golpes | 🟡 | MA |
| 18 | Procesar internamente a 2× la frecuencia de muestreo | Agudos más limpios en todo lo no lineal | 🟢 | MZ/MA |
| 19 | Automatización por secciones en la mezcla | Estribillos que levantan de verdad | 🟡 | MZ |
| 20 | Espacio: reverb/delay con pre-delay y profundidad por rol | Mezcla con fondo, no plana | 🟡 | MZ |
| 21 | Ancho estéreo para fuentes mono (Haas / doble toma artificial) | Guitarras abiertas sin romper el mono | 🟡 | MZ |
| 22 | Mastering por grupos (batería/bajo/guitarras/voz) | Arreglar el balance dentro del master | 🟡 | MA |
| 23 | Mezcla por ML diferenciable (estilo de la referencia) | Investigación: aprende la cadena de un disco | 🔴 | MZ |

Los 15 puntos que ya estaban en el roadmap quedan cubiertos por esta lista
(fase → 3, pasa-altos y desenmascarado → 6, compresión por stem → 5 y 7,
sidechain → 6, bus de batería → 7, de-esser → 5, reverb → 20, A/B → 1,
volumen por crest → 10, clipper → 10, glue → 13, EQ dinámica → 11,
ensanchador → 21, saturación → 13).

---

## 2. Detalle técnico

### A. Medir bien antes de tocar

**1. Igual sonoridad en toda comparación.** El oído percibe más graves y agudos
cuando el volumen sube (curvas de igual sonoridad, ISO 226) **[F]**. Todo A/B,
todo matching espectral y todo score se hacen con ambas señales llevadas al
mismo LUFS integrado (ITU-R BS.1770). Automatizable: normalizar antes de medir
y antes de reproducir en el comparador. Barato y cambia todas las decisiones
que vienen después.

**2. Separar la referencia en instrumentos.** Con un separador (HT Demucs,
Rouard, Massa y Défossez, ICASSP 2023) la referencia se divide en voz, batería,
bajo y resto. **Solo se mide, no se usa ese audio**, así que los artefactos de
la separación no importan. Se obtienen objetivos concretos:
- relación voz / instrumental en LU por sección;
- nivel de batería y de bajo respecto del total;
- espectro y crest de cada grupo (cuánto pega la caja del disco);
- ancho estéreo por grupo.
La auto-mezcla deja de usar la jerarquía fija por rol y apunta a esos números.
Con una mezcla estéreo sin stems, la misma separación permite retocar el
balance por instrumento ("remezcla-master") con cuidado de artefactos.
Costo: dependencia pesada (PyTorch, ~2 GB) y 1–3 min por tema en CPU.

### B. Fuente y stems

**3. Fase y polaridad.** Correlación cruzada (GCC-PHAT) entre pares que captan
la misma fuente; retardo con **precisión sub-muestra** (interpolación
parabólica del pico + retardo fraccional con filtro sinc/all-pass). Corrige
polaridad si la correlación es negativa. Paso extra de élite: **rotación de fase**
del bajo respecto del bombo con un all-pass de 2º orden, buscando el ángulo que
maximiza la energía sumada en 40–120 Hz **[F]** (suma de ondas; con fase opuesta
se cancelan).

**4. Gate/expansor para batería en vivo.** Detección de golpes por flujo
espectral en la banda propia del tambor (tom de piso 80–150 Hz, caja 150–250 Hz
+ 2–5 kHz) usando el propio stem **y** los demás como llave (sidechain
filtrado), para que el bleed de la caja no abra el tom. Expansión 1:4 a 1:8 en
lugar de gate duro, apertura con look-ahead de 1–2 ms, hold según el tempo.
**[C]** los valores son de oficio; el principio de no cortar la cola es **[F]**
(la cola del tambor es parte del timbre).

**5. Voz: rider + compresión en serie.** Primero se nivela la voz con ganancia
lenta (ventanas de ~50–400 ms) contra la sonoridad del instrumental, como un
rider automático; recién después se comprime. Dos compresores en serie con
~3 dB cada uno suenan más naturales que uno con 6 dB **[C]**: uno rápido
(ataque ~1 ms, estilo 1176) para picos, uno óptico lento (release programa-
dependiente, estilo LA-2A) para cuerpo. Después de-esser en 5–9 kHz (ya existe
en el modo voz). Opcional: saturación paralela suave para que corte en la mezcla.

**6. Pasa-altos por rol + desenmascarado dinámico.** Pasa-altos de 12–24 dB/oct
en lo que no necesita grave (guitarras ~80–100 Hz en metal, voz ~80–120 Hz,
overheads ~150–300 Hz) **[E]** en metal moderno, discutible en grunge.
Desenmascarado: por cada bin (STFT, bandas Bark) se atenúa el instrumento de
acompañamiento **solo cuando** el principal tiene energía ahí y solo lo justo
(tipo trackspacer). Voz → guitarras/teclas en 1–4 kHz; bombo → bajo en su
fundamental. Tope 3–6 dB para que no se note el bombeo.

**7. Batería: paralela y bus.** Copia de la batería comprimida muy fuerte
(ratio 8–20:1, ataque rápido, 10–20 dB de reducción) mezclada 15–30 % bajo la
original: suma cuerpo y sustain sin perder el golpe **[E]** ("New York
compression"). Bus de batería 2:1–4:1 con ataque 10–30 ms que deja pasar el
transitorio **[C]**.

**8. Bajo dividido.** Crossover Linkwitz-Riley de 4º orden en ~150–250 Hz:
debajo, señal limpia, comprimida y mono; arriba, saturada (amp/fuzz simulado)
para que el bajo se oiga en parlantes chicos **[E]**, práctica extendida en el
metal moderno (difundida por productores como Nolly Getgood). Los dos caminos
alineados en fase (el LR4 suma plano en amplitud **[F]**).

**11. Supresión de resonancias.** Espectro suavizado (1/3 de octava) contra el
espectro instantáneo; los picos que sobresalen más de X dB se atenúan
dinámicamente con ataque/release cortos. Es EQ dinámica por bin. En guitarras
de metal saca la aspereza de 2–5 kHz y el "fizz" de 6–10 kHz solo cuando aparece.

**15. Refuerzo con samples.** Detectar cada golpe de bombo/caja (onsets con
look-ahead), estimar su intensidad y disparar un sample a esa intensidad,
**alineado en fase** con el original, mezclado por debajo o reemplazándolo.
Es la base del sonido de batería de la escena metal moderna **[E]**. Requiere
biblioteca de samples propia y cuidar que no suene a "ametralladora"
(round-robin: alternar 3–5 variantes).

### C. Mezcla general

**13. Saturación con sobremuestreo.** Toda no linealidad crea armónicos; los
que superan Nyquist se reflejan como ruido inarmónico (aliasing) **[F]**. Por
eso: sobremuestrear 4–8× → saturar → filtrar → volver a la frecuencia original.
Cinta: curva simétrica suave + leve realce de graves ("head bump") y caída de
agudos. Válvula: curva asimétrica (armónicos pares). Bus de mezcla estilo SSL:
2:1, ataque 30 ms, release auto, 1–3 dB de reducción **[C]**.

**18. Procesar a 2×.** Subir internamente a 88.2/96 kHz solo en la cadena no
lineal (compresores rápidos, saturación, clipper, limitador) reduce aliasing
**[F]**; lo lineal (EQ) no lo necesita.

**19. Automatización por secciones.** Detectar secciones (ya existe algo en
`dinamica_secciones`) y en la mezcla levantar el estribillo 0.5–1.5 dB, abrir
el ancho, subir los envíos de reverb **[C]**. Hoy se hace en el master; en la
mezcla es más potente porque puede mover solo guitarras o solo voz.

**20. Espacio y profundidad.** Pre-delay más largo = la fuente se siente más
cerca; menos agudos en la cola = más lejos **[F]** (absorción del aire y
efecto de precedencia). Envíos por rol: sala corta para batería, plate para
voz y caja, delay a tempo en la voz.

**21. Ancho para fuentes mono.** Doble toma artificial: copia con retardo
variable de 10–30 ms y leve cambio de afinación, como el ADT que Ken Townsend
inventó en Abbey Road (1966) **[E]**. Efecto Haas (<30 ms) **[F]**. Siempre con
control de correlación y chequeo en mono, porque el retardo produce filtro
peine al sumar **[F]**.

### D. Master

**9. Matching dinámico por banda.** Hoy se iguala el espectro medio. Falta
igualar **cómo se mueve** cada banda: crest, rango de sonoridad (LRA) y la
distribución de la envolvente por banda de la referencia. Se ajustan
automáticamente el umbral y el ratio del multibanda hasta que las estadísticas
coinciden. Es lo que hace que un master "respire" como el disco de referencia.

**10. Clipper + limitador multietapa.** Cadena: clipper suave oversampleado
(recorta 1–3 dB solo de transitorios de batería, inaudible por su corta
duración **[F]**, enmascaramiento temporal) → limitador de 2 etapas (ya existe)
→ techo true peak. Variante sensible a transitorios: separar transitorio y
sustain, limitar sobre todo el sustain. El LUFS objetivo se elige para que el
crest final caiga en la zona de Bruno (~10).

**12. Vista previa de códec.** Codificar el master a MP3/AAC, decodificar y
medir true peak y clipping: los códecs pueden subir picos más de 1 dB. Por eso
la recomendación de −1 dBTP para distribución (EBU R128, AES TD1004).
Herramienta de referencia: afclip de Apple Digital Masters.

**16. Exciter de graves.** El oído reconstruye una fundamental ausente a partir
de sus armónicos (tono residual, Schouten) **[F]**. Generar 2º y 3º armónicos
de 40–100 Hz hace que el grave se "oiga" en celulares sin subir la energía real.

**17. Fase mínima vs lineal.** EQ de fase lineal: sin distorsión de fase pero
con pre-eco antes de los golpes; fase mínima: sin pre-eco, con corrimiento de
fase **[F]**. Élite: fase lineal para cambios suaves y anchos, fase mínima para
cortes en graves y cerca de transitorios; o fase mixta.

**22. Mastering por grupos.** Como MixMaster ya recibe stems, puede masterizar
desde 4 grupos (batería, bajo, guitarras, voz): el matching del punto 2 corrige
el balance de cada grupo antes de la cadena final **[C]**, práctica de "stem
mastering" en estudios de mastering.

### E. Control de calidad

**14. Medidores de artefactos.**
- Bombeo: correlación entre la reducción de ganancia y el bombo; si la
  sonoridad de las guitarras baja con cada golpe, avisar.
- Distorsión del limitador: diferencia entre entrada y salida del limitador a
  igual nivel; si tiene mucha energía armónica, sobra limitación.
- Nulo contra la mezcla a igual sonoridad para oír qué cambió (ya existe el
  null test).

### F. Aprendizaje automático (lo más ambicioso)

**23. Mezcla diferenciable.** Consolas de efectos diferenciables que aprenden
los parámetros para acercar una mezcla a un estilo: Steinmetz, Pons, Pascual y
Serrà, ICASSP 2021 (mezcla multipista automática); DeepAFx-ST, Steinmetz,
Bryan y Reiss, JAES 2022 (transferencia de estilo de efectos). Libro base del
campo: De Man, Stables y Reiss, *Intelligent Music Production* (Focal Press,
2019). Es investigación; conviene recién cuando lo clásico esté hecho.

---

## 3. El Consejo — resumen del debate

- **Escéptico:** varias mejoras pueden empeorar el sonido sin que el score lo
  note (gate que corta colas, desenmascarado que bombea). Sin comparar a igual
  sonoridad (1) no se sabe si algo mejoró.
- **Pragmático:** lo más barato con mayor efecto es 1, 7, 8, 12 y 16. Demucs
  (2) y samples (15) son caros en dependencias o en material.
- **Visionario:** 2 es la llave: convierte "suena parecido" en objetivos
  medibles por instrumento, y habilita 22 y 23 más adelante.
- **Abogado del diablo:** el techo lo pone la grabación y la interpretación;
  el master ya está bastante completo. Pulir el master es la trampa: la
  distancia con Sumerian está en la **mezcla** (batería, fase, balance).
- **Experto técnico:** en metal moderno, el sonido de disco sale de la batería
  (gate + paralela + samples), el bajo dividido y guitarras con pasa-altos y
  control de resonancias. Fase primero: sin eso, todo lo demás se construye
  sobre un grave que se cancela.

**Veredicto del Presidente:** el esfuerzo va a la **mezcla**, no al master.
Orden: primero medir bien (1) y tener objetivos reales (2); después la base
física de la mezcla (3 fase, 4 gate, 6 limpieza); después el carácter del
género (7 batería, 8 bajo, 5 voz). El master se toca al final (9, 10, 12), y
cada paso se valida de oído en A/B a igual sonoridad antes del siguiente.
Pesó más el Abogado del diablo y el Experto: la brecha audible con los
discos de referencia está en la batería y el grave, no en el limitador.

---

## 4. Fuentes verificables

- ITU-R BS.1770 (medición de sonoridad y true peak) · EBU R128.
- AES TD1004.1.15-10, recomendación de sonoridad para streaming.
- ISO 226, curvas de igual sonoridad.
- Giannoulis, Massberg, Reiss, *Digital Dynamic Range Compressor Design — A
  Tutorial and Analysis*, JAES, 2012.
- Rouard, Massa, Défossez, *Hybrid Transformers for Music Source Separation*,
  ICASSP 2023 (HT Demucs).
- Steinmetz, Pons, Pascual, Serrà, *Automatic Multitrack Mixing with a
  Differentiable Mixing Console of Neural Audio Effects*, ICASSP 2021.
- Steinmetz, Bryan, Reiss, *Style Transfer of Audio Effects with
  Differentiable Signal Processing*, JAES, 2022.
- De Man, Stables, Reiss, *Intelligent Music Production*, Focal Press, 2019.
- Bob Katz, *Mastering Audio: The Art and the Science* (dither, sonoridad).
- Los valores de ataque, ratio y frecuencias marcados **[C]** o **[E]** son
  práctica de oficio: no se atribuyen a una fuente única.
