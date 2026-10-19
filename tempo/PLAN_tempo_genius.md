# Plan: Tempo Genius perfecto (12/10/2026)

Pedido de Bruno: pasar cualquier tema (stems de Moises, multipista propia o un
solo audio en MP3, WAV o lo que sea) y recibirlo **a tempo fijo, con el pulso
perfecto**, listo para arrastrar al compás 1 de Studio One. Todo desde la app,
sin pasar por Claude. "Que esté perfecto, que esté bien y que no falle."

Decisiones de Bruno:
- El **compás lo decide él** en el DAW. A la app solo le importa el pulso.
- Si el tema sube o baja de tempo, **igual queda en un tempo estable**. Los
  cambios de tempo a propósito se ven más adelante.
- Lo que se hizo con los 8 temas le gusta: es la base.

Decisiones por defecto (se pueden cambiar cuando Bruno diga):
- Los resultados llegan a `A TEMPO/<Tema> - <BPM> BPM/` junto a lo que se importa.
- Formato FLAC de 24 bits (sin pérdida, Studio One lo abre).

---

## Fase 0 — Registro al día

1. Actualizar `tempo/REGISTRO_app_tempo.md` con lo que cambió en la PC (v0.5):
   Rubber Band en tiempo real (pylibrb), Beat This! para el "1", Demucs para
   temas sin stems, mapa de tempo MIDI, avisos, carpetas. Cada fase que se
   cierre se anota ahí en el momento, no al final.

## Fase 1 — Entrada: cualquier cosa

2. **Stems de Moises con metrónomo** (como ahora).
3. **Stems de Moises sin metrónomo, o multipista propia**: la batería se busca
   por nombre (drums, kick, snare, bombo, caja, overhead, batería…) y se suma
   como referencia. Si no hay batería, Demucs la separa de la suma.
4. **Un solo audio** (MP3, WAV, FLAC, M4A…): Demucs separa la batería; el audio
   se estira entero.
5. Pistas con distinto largo, sample rate o mono/estéreo: se llevan a 44.1 kHz
   y se alinean al inicio (una multipista se grabó junta).
6. Formatos que soundfile no lee (M4A, WMA): decodificar con lo mismo que usa
   el Convertidor de MixMaster (copiado, no importado).

## Fase 2 — Pulso perfecto en cualquier compás

7. **Guía de tiempos sin metrónomo**: usar los pulsos de Beat This! (funciona
   en cualquier compás) en lugar del detector de librosa. El metrónomo de
   Moises, cuando está, sigue siendo la guía.
8. **BPM automático**: si el nombre no lo trae, se estima con los pulsos y se
   propone redondeado; Bruno lo puede corregir antes de procesar.
9. **El pulso no depende del compás**: el ajuste fino (promedio de la batería
   por ventanas, método v0.4) trabaja tiempo a tiempo, sin suponer 4/4.
10. **Acento del click**: selector de compás en la ventana (4/4, 3/4, 6/8, 7/8…
    o "solo pulso"). Sin elegir, todos los clicks iguales. El "1" se ubica con
    Beat This! solo si Bruno elige compás.
11. Riesgo a vigilar: en 6/8 y 12/8 hay dos pulsos posibles (negra con punto o
    corchea). Se elige el más cercano al BPM indicado; si duda, aviso.

## Fase 3 — Tempo estable siempre

12. **Cambio de criterio**: hoy los tramos fuera de ±3 % (ritardando, intro
    libre) quedan naturales. Nuevo: **todo tramo con pulso se endereza** al
    tempo fijo. Solo queda libre lo que no tiene pulso (silencio, rubato sin
    golpes), y se avisa.
13. Si en algún tramo hay que estirar mucho (más de ~8 %), aviso de calidad:
    ahí el audio puede sonar estirado.
14. La opción "respetar finales libres" queda guardada para cuando se vean las
    variaciones.

## Fase 4 — Precisión y que no falle

15. **Segunda pasada**: hoy a veces empeora (Tengo Sed: 6.6 → 13.2 ms). Aplicar
    la mitad de la corrección y quedarse con ella solo si mejora.
16. Meta: secciones a **±3 ms con stems** y **±5 ms sin stems** (la variación
    natural del baterista ronda 2.6–5.2 ms).
17. Comprobar que los stems de salida siguen alineados entre sí (mismo mapa,
    comparación por correlación entre stems).
18. Temas largos (10 min) y multipistas grandes (30 pistas): procesar pista por
    pista, sin cargar todo a la vez; avisar la RAM estimada.
19. Errores: mensaje claro en la ventana, nunca colgarse; todo al log.
20. Volver a correr los **8 temas** y comparar con las cifras del registro: no
    puede empeorar ninguno.

## Fase 5 — Carpetas, importación y exportación

21. **Importar**: arrastrar una carpeta o uno o varios archivos a Tempo Genius.
    **Cola**: varios temas seguidos sin esperar uno por uno.
22. **Exportar** a `A TEMPO/<Tema> - <BPM> BPM/`:
    - cada pista con el BPM en el nombre: `Batería 128bpm.flac`, `Voz 128bpm.flac`…
    - `Mezcla 128bpm.flac`, `Click 128bpm.flac`, `Tempo 128bpm.mid`
    - `REPORTE.txt` en palabras (BPM, cuánto se estiró, peor sección, avisos)
    - `log.json` con las mediciones
23. Nunca pisar un resultado anterior: si existe, se agrega V2, V3…
24. Opción de carpeta de salida fija, para quien la prefiera.

## Fase 6 — Ventana de Tempo Genius

25. Cola con progreso por tema, resultado en una línea (BPM, peor sección,
    avisos), escuchar con click, mover el "1" (solo si hay compás elegido),
    abrir carpeta.
26. Campo de BPM con el detectado y selector de compás.
27. Probarla dentro de la app a 1920x1080, como la usa Bruno, antes de decir
    que está lista.

## Fase 7 — Pruebas

28. Los 8 temas de siempre (regresión).
29. 2–3 temas **sin stems**.
30. Temas en **3/4, 6/8 y 7/8** (los manda Bruno).
31. Un tema **en vivo sin click**, que sube y baja.
32. Test automático con señales sintéticas: pulso con deriva, acelerando y
    ritardando → la salida debe quedar a ±2 ms.

---

**Lo que falta de Bruno:** los temas de prueba de los puntos 29–31.

---

## Estado (13/10/2026)

- **Fase 0** ✅ registro con la sección 9 (v0.5).
- **Fase 1** ✅ multipista (batería por nombre: kick, bombo, caja, OH, room, perc…),
  M4A/WMA vía librosa + ffmpeg, pistas mono. Probado: multipista sin metrónomo de
  Te Doy Gloria, ±7 ms.
- **Fase 2** ✅ sin metrónomo, los pulsos salen de Beat This!; se rellenan pulsos
  saltados y se quitan dobles; BPM automático con ajuste lineal (la mediana daba
  143 en vez de 140 porque Beat This! marca en pasos de 20 ms). `--compas=N`
  (0 = solo pulso) para el acento y el "1"; la heurística de caja en 2 y 4 solo
  se usa en 4/4. MIDI con el compás elegido. Probado: Te Doy Gloria solo MP3, BPM
  detectado 140, ±2.8 ms.
- **Fase 3** ✅ con un cambio pedido por Bruno (13/10): enderezar lo que sube o
  baja es **opcional** ("solo si la presiono"): casilla "Enderezar todo" en la
  ventana / `--todo-a-tempo`. Apagada, los tramos libres quedan naturales como
  antes. Aviso si algún tramo se estira más de 8 %.
- **Fase 4** en curso: la 2.ª pasada aplica media corrección (Tengo Sed: 6.6 →
  5.7 ms, antes empeoraba a 13.2). Falta: alineación entre stems (17), temas
  largos y multipistas grandes (18), regresión de los 8 temas (20, corriendo).
- Ventana: casilla "Detectar" BPM, selector de compás, "Enderezar todo". Se
  arregló un error que impedía abrir la ventana (salto de línea dentro de un
  texto, desde el 7/10).
- **Fase 4** (13/10, más): stems alineados entre sí comprobado con la prueba
  sintética (bajo y batería: +0.00 ms de cambio). Falta: temas largos y
  multipistas grandes (18): ✅ 14/10, la batería de una multipista se suma de a una pista y hay aviso de RAM en temas muy largos.
- **Fase 5** ✅ nombres con el BPM (`Batería 128bpm.flac`, `Mezcla …`, `Click …`,
  `Tempo 128bpm.mid`; stems de Moises en castellano), `REPORTE.txt` en palabras,
  nunca se pisa un resultado (V2, V3…), carpeta de salida fija opcional
  (se recuerda entre sesiones).
- **Fase 6** ✅ ventana con cola: agregar carpetas o varios audios (o arrastrar),
  opciones por tema (BPM / Detectar, compás, Enderezar todo), procesa uno tras
  otro, resultado por tema en la lista, escuchar y mover el 1 del tema elegido.
  Probada sin pantalla con dos temas sintéticos y renderizada con el estilo de la app (14/10): se ve bien. Falta que Bruno la abra dentro de la app
  a 1920x1080** (avisar antes de abrir nada en la pantalla de Bruno).
- **Fase 7**: `tempo/tests/test_sintetico.py` (sin audios de Bruno): stems con
  metrónomo, compás de 3 y un audio solo con BPM automático. Faltan los temas
  reales difíciles, **cuando Bruno diga cuáles** (no usar sus audios sin permiso).

---

## Idea: Fase 8 con MuScriptor (19/10/2026, sin empezar)

Transcripción audio→MIDI de Kyutai/Mirelo (github.com/muscriptor/muscriptor; pesos
CC BY-NC en Hugging Face, hay que aceptar la licencia con una cuenta gratis y que
Bruno haga `hf auth login` él mismo, nunca pasar el token).

Lo que **sí** sirve (Bruno, 19/10):
1. Transcribir a MIDI el bajo y la voz de los stems ya a tempo, con el BPM en el nombre.
2. Que la mezcla automática reconozca el instrumento de cada stem cuando el nombre no lo dice.

Lo que **no** sirve (Bruno, 19/10): partituras/tablaturas en PDF (MuseScore) y la guía de
acordes desde teclas y guitarra.

Instalado (19/10): `tempo/.muscriptor` (uv + Python 3.12, muscriptor, PyTorch CPU: la PC tiene AMD Radeon integrada, sin CUDA → modelo small). Antes se pensaba: PyTorch
con CUDA y solo el modelo medium (~1.2 GB). Sin la web ni MuseScore.

Estado MuScriptor (19/10, al cerrar): Bruno ya inició sesión en Hugging Face (usuario
bruno321; el token quedó en `~/.cache/huggingface`, sirve para cualquier entorno). El
modelo **medium** ya está en la caché (lo bajó el proyecto CREATOR MIDI\transcribir), así
que no hace falta descargar otro. **Pendiente:** la primera prueba con un bajo sintético
salió con código 255 sin mensaje; revisar eso antes de integrarlo (correr con
`PYTHONIOENCODING=utf-8`, la consola de Windows rompe los caracteres de `rich`).
