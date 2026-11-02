# Investigación profunda — mastering y mezcla de nivel profesional para MixMaster

> Encargo para IAs de investigación (ChatGPT Deep Research, Gemini Deep Research, Perplexity, Grok, Claude.ai).
> El resultado vuelve a Claude Code en un .md con el formato de la sección 6, para implementarlo sin gastar tokens investigando.
> Fecha del encargo: 2 de noviembre de 2026. **Prioridad absoluta: lo publicado o lanzado en los últimos 12–18 meses.**

---

## 0. PRIMER PROMPT (pegar junto con este archivo)

```
Te adjunto un archivo .md con un encargo de investigación técnica sobre mastering y mezcla de audio.
Léelo completo antes de empezar. Es una app real en Python que ya funciona; no quiero teoría general
ni consejos para principiantes: quiero el estado del arte profesional y de investigación, con
algoritmos, parámetros, papers, repositorios y herramientas concretas, priorizando lo publicado o
lanzado en los últimos 12–18 meses (2025–2026).

Reglas:
1. Investiga TODAS las áreas de la sección 4, en orden. Si una área es enorme, prioriza lo que más
   mejora el sonido final y lo que se puede implementar en Python en CPU.
2. Para cada hallazgo usa EXACTAMENTE el formato de la sección 6. Sin ese formato no me sirve.
3. Cita la fuente de cada dato (paper con año, repo con fecha del último commit, documentación,
   manual, AES/ITU/EBU). Si no estás seguro de algo, márcalo como [NO VERIFICADO]. No inventes
   nombres de papers, versiones ni parámetros.
4. Indica licencia y si existe paquete pip o código abierto reutilizable. Nada de herramientas
   pagas como solución: las pagas solo como referencia de "cómo lo hacen los profesionales".
5. Lenguaje técnico de ingeniería de audio, sin simplificar: fórmulas, constantes de tiempo, tipos
   de filtro, órdenes, pendientes, ventanas, tamaños de FFT, oversampling, latencias.
6. Al final, entrega la sección "Plan de implementación" ordenada de lo más fácil a lo más difícil
   con el código de colores de la sección 6.
7. Responde en español. Entrega todo en un solo bloque Markdown descargable.
```

---

## 1. Qué es MixMaster (contexto para el investigador)

App de escritorio para Windows, en **Python 3.14**, con interfaz **PySide6 (Qt 6)**. La usa un músico/productor que mezcla en su DAW y quiere un master de nivel comercial sin pagar servicios. Trabaja offline en CPU.

**Librerías actuales:** numpy, scipy (signal), librosa, soundfile (libsndfile, incluye MP3), pyloudnorm (BS.1770), torch CPU + demucs 4.1 (`htdemucs`) para separar fuentes, beat_this (pulso), MuScriptor (transcripción a MIDI).

**Flujo:** PASO 1 cargar mezcla estéreo o carpeta de stems → PASO 2 elegir 1 o más referencias (o "Sin referencia") → PASO 3 masterizar → escuchar, votar "me gusta / no", y la app aprende por género.

**Pipeline de master actual (en este orden aproximado):**
1. Declip ligero por interpolación (clipping corto de la fuente).
2. Análisis: LUFS integrado / short-term, true peak, LRA, crest factor, PLR, centroide, rolloff, inclinación espectral, balance por 7 bandas (sub, low, low_mid, mid, high_mid, high, air), espectro fino 1/3 de octava (40 bandas), correlación estéreo global y por banda, ancho por banda, fase fina en ventanas de 0,5 s, MFCC, spectral flux.
3. Perfil de las referencias (nivelado en loudness) y, con demucs, balance de la referencia por instrumento.
4. EQ correctivo por "matching" contra la referencia (por bandas), con límites; EQ en lado (side) aparte; segunda pasada.
5. Detección y corte de resonancias (cortes de −3 dB con Q estrecho en picos detectados).
6. Multibanda (compresión por banda), ajuste de ancho estéreo por banda (M/S), mono por debajo de ~100 Hz.
7. Transient shaping, "dinámica macro" (respetar secciones fuertes/suaves), densidad.
8. Etapa de volumen: limitador con techo true-peak; objetivo de LUFS elegido por el usuario o automático por crest (~10 dB).
9. Mide bombeo (correlación entre grave y reducción de ganancia), distorsión agregada por la limitación, y el true peak del MP3 decodificado (vista previa de códec).
10. Exporta **WAV 48 kHz / 24 bits** y **MP3 320 kbps CBR** (remuestreo con `scipy.signal.resample_poly` DESPUÉS del limitador; sin dither todavía).
11. Score de similitud A/B contra las referencias. Aprendizaje: guarda LUFS, crest, true peak, EQ aplicado, multibanda, mono bass de cada master aprobado o rechazado por género, y promedia.

**Problemas reales observados (pistas para investigar):**
- Un master anterior fue rechazado por el usuario: "no me sirve" — las mejoras se hicieron midiendo, sin escuchar. Necesitamos métricas que predigan lo que un oído profesional aprueba.
- Una mezcla llegó sin agudos (nada por encima de ~4–8 kHz). El EQ por referencia no puede crear contenido: hay que detectarlo y, si es posible, **reconstruir ancho de banda** (excitadores, SBR, IA de bandwidth extension).
- Remuestreo después del limitador puede crear picos entre muestras; falta dither al pasar a 24 bits.
- El aprendizaje tiene muy pocas muestras por género (1–10). Necesita un método que aprenda bien con pocos votos.
- Pocas referencias por género (solo math rock y grunge tienen biblioteca).

---

## 2. Objetivo

Llegar al **mejor audio posible**: masters que compitan con los de ingenieros de primer nivel (Bob Katz, Bernie Grundman, Emily Lazar, Ted Jensen, Howie Weinberg, Chris Gehringer, Mandy Parnell, Joe LaPorta, Greg Calbi) y con los mejores sistemas automáticos (iZotope Ozone 11/12, LANDR, Masterchannel, RoEx, BandLab Mastering, Matchering, CloudBounce, eMastered), y mezclas automáticas de stems de nivel profesional. Todo en Python, CPU, offline, gratis.

---

## 3. Lo que NO queremos

- Listas genéricas de "10 consejos de mastering".
- Plugins pagos como respuesta (sí como referencia de cómo funcionan por dentro).
- Información sin fuente o anterior a 2020 presentada como novedad.
- Soluciones que necesiten GPU obligatoria, nube, cuenta o tarjeta.

---

## 4. Áreas de investigación (todas, en orden)

### 4.1 🟢 Formato, dither, remuestreo y orden de la cadena final
- Orden correcto: remuestreo → limitador true-peak → dither → exportación. Qué hacen los profesionales cuando la mezcla viene a 44,1 kHz y se entrega a 48 kHz.
- Dither TPDF vs noise-shaped (curvas: F-weighted, Wannamaker, POW-r 1/2/3, MBIT+, iZotope MBIT+ por dentro) al pasar de flotante a 24 bits. ¿Tiene sentido a 24 bits? Evidencia medible.
- Calidad de remuestreadores: soxr (VHQ, fase lineal / intermedia / mínima, ancho de banda 95–99 %), r8brain, libsamplerate, `resample_poly` con Kaiser. Comparativas (Infinite Wave SRC), aliasing, pre-ringing.
- True peak: oversampling 4×/8×/16× según BS.1770-5, picos entre muestras tras remuestreo y tras códec (MP3/AAC/Opus). Margen recomendado por plataforma (−1 dBTP, −2 dBTP) con evidencia.
- MP3 320 vs AAC 256 vs Opus para vistas previas; codificadores (LAME settings exactos: `-V0`, `-b 320 -q 0`, lowpass, joint stereo).

### 4.2 🟢 Estándares y normalización de plataformas (estado a 2026)
- ITU-R BS.1770-5, EBU R128 (y s1/s2), AES TD1008, AES77 si existe, recomendaciones de "loudness wars" recientes.
- Normalización actual de Spotify, Apple Music (Sound Check, Apple Digital Masters), YouTube, Tidal, Amazon, Deezer, SoundCloud, TikTok/Instagram, WhatsApp. Si normalizan hacia arriba, con limitador o no; modo álbum.
- Qué LUFS integrados y PLR tienen los masters comerciales actuales por género (datos medidos, no opiniones). Bases de datos de mediciones si existen.

### 4.3 🔵 Limitación, clipping y etapa de volumen (lo que hacen los mejores)
- Arquitectura de limitadores modernos: look-ahead, ventana de suavizado, release dependiente del programa, multi-etapa (2–3 limitadores en serie con tiempos distintos), limitación multibanda vs banda ancha, "transient vs sustain" separados (como Pro-L 2, Ozone Maximizer IRC IV/V, Weiss DS1, Sonnox Oxford, Elephant, Kotelnikov, LoudMax).
- Clipper antes del limitador (soft clip, hard clip con oversampling, clippers tipo StandardCLIP / KClip / Gold Clip): cuándo suena mejor que limitar.
- Medidas objetivas de "daño" por limitación: distorsión de intermodulación, bombeo, pérdida de transitorios, "crest por banda". Cómo detectar automáticamente que se pasó de limitación.
- Algoritmos abiertos con código: x42-dpl, LSP Limiter, Calf, Airwindows (ClipOnly2, ADClip, Pressure), Matchering 2.0 (su limitador "Hyrax"). Pseudocódigo y parámetros.

### 4.4 🔵 EQ de mastering y matching contra referencia
- Matching espectral bien hecho: suavizado (1/3 oct, 1/6 oct, ERB, Bark), ponderación por sonoridad (ISO 226:2023), límite de boost donde la fuente no tiene energía (por encima del piso de ruido), tilt vs curvas finas, cuántos dB máximo.
- Fase: lineal vs mínima vs mixta; pre-ringing en graves; cuándo usar cada una en mastering.
- EQ dinámico y EQ por M/S en mastering: casos y parámetros típicos.
- "Tonal balance" por género: curvas objetivo (como iZotope Tonal Balance Control, Sonible, "target curves" de investigaciones). ¿Hay datasets públicos de espectros promedio por género?
- Matchering 2.0 por dentro (algoritmo exacto, licencia GPL) y alternativas más nuevas.

### 4.5 🟡 Resonancias, dinámica espectral y procesamiento perceptual
- Supresión de resonancias tipo soothe2, Gullfoss, smartEQ 4, Ozone Clarity / Stabilizer: qué hacen por dentro (STFT, detección relativa a una envolvente suavizada, ganancias por bin con suavizado temporal, sidechain). Papers o descripciones técnicas.
- Compresión multibanda en mastering: crossovers Linkwitz-Riley vs fase lineal, número de bandas, ratios y tiempos típicos, compresión hacia arriba (upward), "parallel".
- Transient shaping y dinámica macro (micro vs macro dinámica): algoritmos y cómo no destruir la expresión.
- Modelos de sonoridad perceptual: Moore-Glasberg (loudness específica), sharpness (Zwicker/Aures), roughness, para decidir EQ y compresión "como oye una persona".

### 4.6 🟡 Imagen estéreo y fase
- M/S en mastering, filtro elíptico (mono bass), ensanchadores que no rompen la compatibilidad mono, decorrelación, corrección de fase entre canales, alineación.
- Métricas profesionales: correlación por banda, goniómetro, "stereo width" perceptual. Qué rangos tienen los masters comerciales por género.

### 4.7 🟡 Saturación, excitadores y reconstrucción de ancho de banda (IMPORTANTE)
- Saturación de cinta y válvula para mastering: modelos (Jiles-Atherton para cinta, waveshapers con oversampling), qué armónicos agregan, cuándo ayudan.
- Excitadores armónicos (Aphex, BBE, "Exciter" de Ozone): algoritmo y parámetros.
- **Reconstrucción de agudos ausentes**: Spectral Band Replication (SBR de HE-AAC), y modelos de IA de bandwidth extension / super-resolución de audio para música: AudioSR, NU-Wave 2, Apollo (restauración de música comprimida), FlowHigh, HiFi-GAN-BWE, y lo más nuevo de 2025–2026. Calidad real en música (no solo voz), velocidad en CPU, licencia, pip.

### 4.8 🟠 Restauración previa al master
- Declip de verdad: A-SPADE / S-SPADE, Janssen, métodos con IA; comparación con interpolación simple.
- Reducción de ruido, hum, clicks, de-esser de mastering; restauración por IA de música (Apollo, modelos de "music restoration" 2025–2026).

### 4.9 🟠 Separación de fuentes de última generación
- Estado del arte actual (tabla de SDR en MUSDB18-HQ y Multisong): BS-RoFormer, Mel-RoFormer, SCNet, MDX23C, htdemucs_ft, y modelos de 2025–2026. Herramientas: python-audio-separator, UVR5, ZFTurbo/Music-Source-Separation-Training. Velocidad en CPU.
- Usos en mastering: "stem mastering" desde una mezcla estéreo (Ozone Master Rebalance / Stem EQ), EQ solo en la voz o la batería, balance contra la referencia por instrumento.

### 4.10 🟠 Mezcla automática de stems (nivel profesional)
- Investigación en mezcla inteligente: Josh Reiss, Brecht De Man ("Intelligent Music Production"), Christian Steinmetz (dasp-pytorch, automix, "differentiable mixing console"), Diff-MST (2024), FxNorm-Automix, MixGraph, y lo nuevo de 2025–2026.
- Ganancia automática por loudness percibido, enmascaramiento espectral entre stems (detección y EQ complementaria), paneo automático, compresión por tipo de instrumento, reverb/espacio, bus processing.
- Transferencia de estilo de mezcla desde una referencia (mixing style transfer).

### 4.11 🔴 IA de mastering de última generación (2025–2026)
- Qué usan hoy LANDR, Ozone 12 (Master Assistant), RoEx, Masterchannel, BandLab, Sonible, Waves Online Mastering, y los papers/patentes que lo explican.
- Mastering diferenciable / aprendido: DSP diferenciable (dasp-pytorch, DDSP), "neural audio effects", modelos que predicen parámetros de una cadena de mastering a partir de la mezcla y una referencia, transferencia de estilo de mastering (ST-ITO, "Mastering style transfer"), modelos de difusión o LLM de audio aplicados a producción.
- Repos abiertos y modelos descargables que corran en CPU.

### 4.12 🔴 Evaluar un master como lo haría un oído profesional
- Métricas objetivas que correlacionan con preferencia humana en música: FAD con embeddings CLAP / MERT / PANNs / VGGish, ViSQOL v3 (modo audio), PEAQ, métricas de distancia de estilo; estudios de correlación con oyentes.
- Preferencias con pocos datos: Bradley-Terry, comparaciones por pares, optimización bayesiana de los parámetros de la cadena con votos del usuario, aprendizaje activo (qué versión mostrar para aprender más rápido).
- Selección automática de referencias por similitud (embeddings CLAP / MERT / MusicFM), tonalidad y tempo.
- Simulación de traducción: cómo suena en celular, auriculares, auto, Bluetooth (respuestas de impulso de dispositivos, AutoEQ / oratory1990). Escucha nivelada en loudness para comparar sin engañarse por el volumen.

### 4.13 🔴 Rendimiento
- Cómo procesar en CPU rápido: vectorización, numba, torch en CPU, procesamiento por bloques, FFT por overlap-add, paralelismo. Ejemplos medidos.

---

## 5. Preguntas concretas que deben quedar respondidas

1. ¿Cuál es la cadena de mastering (orden y parámetros iniciales) que usaría hoy un ingeniero de primer nivel para rock/indie, metal, pop, electrónica y acústico?
2. ¿Qué limitador abierto (algoritmo) suena más transparente a −9/−10 LUFS, y con qué parámetros?
3. ¿Cómo evitar que el EQ por referencia suba ruido donde la mezcla no tiene contenido?
4. ¿Qué modelo de IA reconstruye agudos en música con la mejor calidad en CPU hoy?
5. ¿Qué modelo de separación conviene reemplazar por htdemucs y cuánto mejora?
6. ¿Qué métrica objetiva predice mejor si al usuario le va a gustar un master?
7. ¿Cómo aprender sus gustos con 5–10 votos por género?
8. ¿Qué cambió en mastering con IA en los últimos 12–18 meses que todavía no está en ningún tutorial?

---

## 6. Formato de entrega obligatorio

Cada hallazgo, así:

```
### [Nombre del hallazgo]
- Área: (4.x)
- Qué resuelve en MixMaster: (una o dos frases, ligado al pipeline de la sección 1)
- Cómo funciona: (algoritmo, fórmulas, parámetros exactos, pseudocódigo si aplica)
- Fuente: (paper con autores y año / repo con URL y fecha del último commit / documentación)
- Licencia y disponibilidad: (MIT/GPL/…; pip install …; ¿corre en CPU? tiempo estimado para 4 min de audio)
- Evidencia de calidad: (mediciones, pruebas de escucha, comparativas)
- Riesgos: (qué puede salir mal en el sonido)
- Dificultad: 🟢 1 muy fácil · 🔵 2 fácil · 🟡 3 media · 🟠 4 difícil · 🔴 5 muy difícil
- Impacto en el sonido: alto / medio / bajo
- Estado: [VERIFICADO] o [NO VERIFICADO]
```

Al final:

```
## Plan de implementación
(Lista ordenada de lo más fácil a lo más difícil, cada punto con su color, su número 1–5,
su impacto y en qué paso del pipeline de la sección 1 entra.)

## Fuentes
(Lista completa de enlaces y referencias.)
```
