# Qué hacen las mejores herramientas y qué le falta a MixMaster (audio)

> 06/10/2026. Solo investigación: nada implementado. Bruno elige.
> Comparado contra lo que MixMaster ya tiene después de las tandas 1–8.

## Lista para elegir (orden por impacto esperado)

| # | Idea | Quién lo hace | Qué le falta hoy a MixMaster | Esfuerzo |
|---|---|---|---|---|
| 1 | **Limitador multibanda** (4 bandas, cada una con su envolvente; ataca primero la banda que causa el pico) | Ozone 12 IRC 5, Waves L3 (hasta 5 bandas) | El limitador es de banda completa: cuando pega el bombo baja todo. La prueba del 2/10 midió bombeo con el grave y −20 dB de distorsión | medio |
| 2 | **Separar también las mezclas estéreo** y ajustar balance/EQ por instrumento (las partes separadas tienen que volver a sumar el original: lo que no separa bien se devuelve tal cual) | Ozone 12 Stem EQ, Moises, Tunee | La separación hoy solo mide la referencia y solo actúa con stems. La mayoría de tus temas entran como mezcla estéreo | medio |
| 3 | **Des-limitador**: recupera transitorios de una mezcla ya aplastada | Ozone 12 Unlimiter (red neuronal basada en "Music De-Limiter Networks via Sample-Wise Gain Inversion", Jeon y Lee, 2023, con código abierto) | Hoy solo avisa "fuente machacada"; no lo repara | medio (hay que verificar la licencia del modelo) |
| 4 | **Separador de 6 instrumentos** (guitarra y piano aparte) | Moises (guitarra rítmica/solista, teclas, bombo/caja) | Demucs de 4: guitarras, teclas y todo lo demás caen en "resto". El modelo `htdemucs_6s` separa guitarra y piano | chico |
| 5 | **Desenmascarado por jerarquía** (adelante / medio / atrás) entre todas las pistas, en todo el espectro | sonible smart:EQ 4 (modo grupo, hasta 10 pistas) | Solo la voz se abre paso, y solo entre 1 y 4 kHz | medio |
| 6 | **Perillas de revisión**: "más brillo", "menos fuerte", "más grave" para repetir el master con esa corrección | LANDR (Revisions), MasteringBOX | Hay que tocar el config a mano | chico |
| 7 | **Control dinámico del grave** (bombo y bajo no se pisan en el sub; el grave pega igual en cualquier equipo) | Ozone 12 Bass Control | Hay mono en graves, bajo dividido y exciter, pero nada que controle el grave en el tiempo | medio |
| 8 | **Parámetros que cambian por sección** (estrofa/estribillo): EQ y compresión adaptadas cuadro a cuadro | LANDR Synapse | La cadena es casi fija para todo el tema (solo la dinámica entre secciones se preserva) | medio |
| 9 | **Limpieza de ruido de stems** (hiss, zumbido de 50/60 Hz, ruido de fondo) antes de mezclar | RoEx Automix (TonnSDK, investigación de Queen Mary, C4DM) | No hay reducción de ruido; con 30 micrófonos en vivo se suma el ruido de todos | medio |
| 10 | **Modelos de equipos reales**: compresor SSL G (con su release automático), consola EMI TG12345, cinta J37 | UAD (SSL G, Unison), Waves Abbey Road | La saturación y el bus son curvas genéricas (tanh) | grande; diferencia sutil |
| 11 | **Detección de estilo** para elegir curva y cadena cuando no hay referencia | LANDR (micro-género), Ozone Master Assistant (modificadores de género) | Sin referencia, el matching no actúa | medio |
| 12 | **Exportar WAV de 32 bits flotante** | MasteringBOX 2.0 | Sale en 24 bits | chico |

## Qué NO vale la pena copiar

- **Suno v5 / Tunee**: su "mastering" es normalizar volumen y limitar, o elegir entre presets y una referencia. MixMaster ya hace más que eso.
- **Unison de UAD**: modela el preamplificador mientras se graba. No aplica a una app que recibe audio ya grabado.

## Fuentes

- iZotope, novedades de Ozone 12 — https://www.izotope.com/community/blog/ozone-12
- iZotope, detalles técnicos de Ozone 12 (Unlimiter, IRC 5, Stem EQ) — https://www.izotope.com/community/blog/inside-ozone-12
- LANDR, motor Synapse — https://blog.landr.com/synapse-engine-update/ · https://support.landr.com/hc/en-us/articles/115009725688-What-is-LANDR-Mastering
- MasteringBOX 2.0 — https://www.masteringbox.com/learn/masteringbox-2
- Moises, novedades 2025 — https://moises.ai/blog/latest/improvements-latest-releases/
- sonible smart:EQ 4 — https://www.sonible.com/blog/everything-new-smarteq4/
- RoEx Automix — https://www.roexaudio.com/blog/automix-ai-powered-mixing-for-musicians-and-producers
- Universal Audio, SSL 4000 G Bus Compressor — https://www.uaudio.com/products/ssl-4000-g-series-bus-compressor
- Waves L3 Multimaximizer — https://www.waves.com/plugins/l3-multimaximizer · plugins de mastering — https://www.waves.com/plugins/mastering
- Suno v5 — https://aiwiki.ai/wiki/suno_v5
- Tunee, Smart Mastering — https://www.musicseed.ai/reviews/tunee-ai-reviews
