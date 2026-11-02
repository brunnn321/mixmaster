# Investigación 2 — EQ de mastering por tramos y detección de agudos molestos / sonido cálido

> Encargo para IAs de investigación. El resultado vuelve a Claude Code en un .md con el formato de la sección 6.
> Fecha: 2 de noviembre de 2026. **Prioridad: lo publicado o lanzado en los últimos 12–18 meses.**
> Continúa la "Investigación técnica de mezcla y mastering v3" (ya implementada en parte).

---

## 0. PRIMER PROMPT (pegar junto con este archivo)

```
Te adjunto un .md con un encargo de investigación técnica sobre ecualización de mastering.
Léelo completo antes de empezar. Es una app real en Python (offline, CPU) que ya masteriza;
quiero el estado del arte profesional y de investigación para dos problemas concretos:
(1) ecualizar por tramos de la canción (verso contra verso, estribillo contra estribillo) y
(2) detectar y corregir agudos molestos (ásperos, sibilantes, "fatiga") y medir la calidez,
de una forma que coincida con lo que oye un productor en monitores ADAM Audio D3V.

Reglas:
1. Investiga TODAS las áreas de la sección 4, en orden.
2. Para cada hallazgo usa EXACTAMENTE el formato de la sección 6.
3. Cita fuente de cada dato (paper con año, repo con fecha del último commit, norma,
   manual del fabricante). Lo dudoso va marcado [NO VERIFICADO]. No inventes.
4. Licencia y paquete pip de cada herramienta. Nada pago como solución (solo como
   referencia de cómo lo hacen).
5. Lenguaje técnico de ingeniería de audio: fórmulas, frecuencias, Q, constantes de tiempo,
   tamaños de FFT, umbrales en dB, ponderaciones.
6. Termina con "Plan de implementación" ordenado de lo más fácil a lo más difícil con el
   código de colores de la sección 6.
7. Responde en español, todo en un solo bloque Markdown descargable.
```

---

## 1. Contexto (qué hay hoy en MixMaster)

App de escritorio Windows en Python 3.14 + PySide6. Librerías: numpy, scipy, librosa, soundfile, pyloudnorm, soxr, torch CPU + demucs (htdemucs), matchering (solo para comparar).

**EQ de mastering actual:**
- Matching contra una o más referencias a 1/3 de octava, medido sobre los **tramos fuertes** del tema (función `tramos_fuertes`), con tope ±4 dB, curva suavizada y aplicada con FIR.
- De la referencia se copia **el tono, no la imagen estéreo** (decisión del usuario, 2/11/2026). La imagen solo se corrige si la correlación global cae por debajo de 0,3.
- Protección de bandas vacías: si la mezcla está más de 35 dB por debajo de su mediana en una zona, el EQ puede cortar pero nunca subir ahí.
- Resonancias: picos estrechos sobre el espectro suavizado a 1/3 de octava que además persisten en al menos la mitad de 8 tramos del tema; se cortan −3 dB.
- Existe una prueba de "EQ por sección" (`test_eq_por_seccion.py`), pero el matching sigue siendo una sola curva para todo el tema.
- Ya existe "control del grave" y un "EQ perceptual", ambos básicos.

**Usuario y escucha:** productor de rock/indie/math rock. Monitores **ADAM Audio D3V** (campo cercano, tweeter de cinta X-ART, woofers pequeños: poca extensión bajo 50 Hz) y auriculares **Audio-Technica ATH-M50x** (la app tiene su corrección AutoEQ). El usuario oye con claridad cuándo los agudos están "molestos" o "cálidos" en los D3V. El último master aprobado (weirdFishes v04) quedó en −10,6 LUFS, −1,9 dBTP, crest 11,5 dB.

---

## 2. Objetivo

1. Que el EQ de mastering compare y corrija **por tramos**: cada sección contra la sección equivalente de la referencia, con transiciones inaudibles.
2. Que la app **detecte, mida y corrija** agudos ásperos/molestos y falta o exceso de calidez **como los percibe una persona**, no solo como energía por banda.
3. Que el resultado coincida con lo que el usuario oye en sus ADAM D3V.

---

## 3. Lo que NO queremos

Consejos genéricos ("corta 3 kHz si suena áspero"), plugins pagos como solución, datos sin fuente, soluciones que exijan GPU o nube.

---

## 4. Áreas de investigación

### 4.1 🟢 Segmentación de la canción en tramos
- Detección de estructura musical (verso, estribillo, puente, intro, outro): métodos clásicos (matrices de autosimilitud, novelty de Foote, checkerboard kernel) y modelos recientes 2024–2026 (All-In-One de Kim & Kwon, SongFormer, MSAF, modelos de 2025–2026). Precisión en rock/indie, velocidad en CPU, licencia, pip.
- Cómo emparejar tramos entre la mezcla y una referencia que tiene otra estructura (etiquetas, energía, timbre; dynamic time warping).

### 4.2 🔵 EQ de mastering por tramos
- Cómo lo hacen los profesionales (automatización de EQ por sección en mastering; "dynamic EQ" vs EQ automatizado): cuánto cambian, con qué transiciones (crossfade de curvas, tiempos), cuándo NO conviene.
- Algoritmos: curva base global + desviación por tramo limitada; interpolación de filtros sin artefactos (interpolación de coeficientes SOS vs crossfade de FIR, zipper noise); cambios máximos razonables en dB entre secciones.
- Evidencia: estudios o pruebas de escucha sobre EQ variable en el tiempo en mastering.

### 4.3 🟡 Agudos molestos: medición perceptual
- Métricas de aspereza / sibilancia / fatiga auditiva: sharpness (Zwicker, Aures, DIN 45692), roughness (Daniel & Weber), loudness específica de Moore–Glasberg (ANSI S3.4-2007, ISO 532-1/532-2:2017), "harshness" en la literatura, modelos de 2024–2026.
- Zonas típicas de molestia (2–5 kHz, 6–10 kHz para sibilancia) con evidencia; cómo influye el nivel de escucha (contornos ISO 226:2023).
- Implementaciones abiertas en Python: MoSQITo, librosa, otras; su exactitud frente a la norma.
- Cómo detectar si la molestia es constante (EQ estático) o aparece en momentos (de-esser / EQ dinámico de banda ancha alta).

### 4.4 🟡 Calidez y balance tonal percibido
- Qué es "cálido" en términos medibles: relación 150–500 Hz vs 2–6 kHz, inclinación espectral, centroides perceptuales, curvas de balance tonal por género (estudios con mediciones de masters comerciales).
- Rangos objetivo con fuente, no opiniones.

### 4.5 🟠 Adaptar el análisis a los ADAM D3V y al cuarto
- Respuesta medida publicada de los ADAM D3V (anechoica o de terceros con método conocido: Erin's Audio Corner, Audio Science Review, mediciones del fabricante). Tweeter X-ART: qué hace en 3–20 kHz y cómo cambia la percepción de agudos.
- Cómo usar esa respuesta para predecir lo que el usuario oye (simulación de escucha) y si conviene corregir el análisis por la respuesta del monitor y del cuarto en campo cercano.
- Medición del cuarto con un micrófono barato (REW, curva de calibración) y si vale la pena para este caso.

### 4.6 🟠 EQ dinámico de mastering
- Algoritmos de EQ dinámico (detector por banda, sidechain, ratio/umbral relativos a la envolvente espectral) y supresión de resonancias dinámicas (soothe2, Gullfoss, Ozone Stabilizer como referencia). Parámetros típicos en mastering de rock: bandas, Q, ataque/release, máximo de reducción.
- Implementaciones abiertas en Python o C/C++ portables (licencias).

### 4.7 🔴 Aprender lo que el usuario oye
- Cómo calibrar las métricas de aspereza/calidez con pocas respuestas del usuario (comparaciones por pares, Bradley–Terry ya implementado en la app con 3 características: LUFS, crest, inclinación espectral). Qué características perceptuales conviene añadir y cómo evitar sobreajuste con pocos votos.

---

## 5. Preguntas que deben quedar respondidas

1. ¿Qué detector de estructura usar en CPU para rock/indie y con qué precisión?
2. ¿Cuántos dB puede variar el EQ entre tramos sin que se note el cambio, y con qué transición?
3. ¿Qué métrica perceptual predice mejor "agudos molestos" y con qué umbrales?
4. ¿Cómo se mide "calidez" de forma confiable?
5. ¿Conviene compensar el análisis por la respuesta de los ADAM D3V? ¿Con qué datos?
6. ¿Qué parámetros de EQ dinámico son seguros por defecto en mastering?

---

## 6. Formato de entrega obligatorio

```
### [Nombre del hallazgo]
- Área: (4.x)
- Qué resuelve en MixMaster: (ligado a la sección 1)
- Cómo funciona: (algoritmo, fórmulas, parámetros exactos, pseudocódigo)
- Fuente: (paper con autores y año / repo con URL y fecha del último commit / norma)
- Licencia y disponibilidad: (licencia; pip install …; CPU; tiempo estimado para 4 min de audio)
- Evidencia de calidad: (mediciones, pruebas de escucha)
- Riesgos: (qué puede salir mal en el sonido)
- Dificultad: 🟢 1 muy fácil · 🔵 2 fácil · 🟡 3 media · 🟠 4 difícil · 🔴 5 muy difícil
- Impacto en el sonido: alto / medio / bajo
- Estado: [VERIFICADO] o [NO VERIFICADO]
```

Al final:

```
## Plan de implementación
(De lo más fácil a lo más difícil, cada punto con color, número 1–5, impacto y en qué parte de la sección 1 entra.)

## Fuentes
```
