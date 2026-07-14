# MixMaster v0.4 — Manual rápido

## Arrancar

Doble clic en **`MixMaster.bat`**. La primera vez pregunta: carpeta de
proyectos, modo de conexión (manual/API), perfil y género. Todo cambiable
en **Settings**.

## El asistente de 3 pasos (pantalla principal)

La barra azul te dice siempre en qué paso estás y qué botón tocar.
Navegas con **← Atrás / Siguiente →**.

**PASO 1 — FUENTE**
- Mezcla estéreo: **Cargar audio** (WAV/MP3/FLAC/OGG/AIFF), o
- Stems: copia tus pistas (WAV 48k/24) a `entrada\stems\` del proyecto y
  pulsa **Procesar stems** → nivela picos a -6 dBFS + highpass conservador
  por tipo (`gtr` 80 Hz · `vox` 90 Hz · `oh` 150 Hz · `bass/kick` sin filtro;
  editable en `config\stems.json`). Los originales no se tocan.

**PASO 2 — REFERENCIAS**
- **Elegir referencias…**: usa la **biblioteca del género**
  (`config\generos\referencias\math_rock\` — recomendado 3–6 temas) o
  archivos sueltos (Ctrl+clic para varios). Varias = promedio/consenso.
- **Analizar (opcional)**: LUFS, true peak, crest, 7 bandas, estéreo,
  secciones por marcadores y alertas del género. Se guarda en `analisis\`.

**PASO 3 — MASTER**
- **🎵 Master final** → eliges el loudness (-8.5 competitivo por defecto;
  -8/-7.5 más loud; el limitador siempre protege a -1 dBTP).
- Cadena: **matching espectral fino** (curva de 1/3 de octava hacia tus
  referencias, máx ±4 dB — solo forma tonal, no clona) + imagen estéreo por
  banda + **clipper de picos** (recorta solo transitorios → el limitador
  trabaja poco y no suena "a tope") + convergencia de loudness.
- Al terminar muestra el **SCORE vs referencias**: `91% (tonal · dinámica ·
  imagen)` — tu medidor de "suena como disco".
- Salida: **WAV 24-bit y MP3 320** en `salida\` — la carpeta se abre sola.
- Ajustes en `config\master.json`: si el matching fino suena raro, baja
  `max_correccion_db` a 3 o vuelve a `"modo": "bandas"`.
- **★ Regla del género**: fija algo aprendido ("correlación baja en mid OK
  si mono no pierde") — queda versionado, reversible en Settings.

## Carpetas del proyecto (v0.4, simple)

```
MiCancion/
  entrada/          ← tu mezcla y referencias del proyecto
  entrada/stems/    ← stems exportados del DAW
  salida/           ← masters WAV+MP3 y stems nivelados
  analisis/         ← diagnósticos y reportes
```

Los proyectos viejos (carpetas numeradas 01–07) siguen abriendo normal.

## Chat con Claude (menú 💬)

Fuera de la pantalla principal. Menú **💬 Chat**: cada mensaje lleva tu
perfil + género + diagnóstico + decisiones. Modo manual: **Copiar
contexto** → pegar en claude.ai. Ahí también se guardan decisiones.

## Perfiles y géneros

```
config/
  perfiles/bruno.md               ← tu equipo, sala, plugins, nivel
  generos/math_rock.md/.json      ← estética + umbrales de alertas
  generos/referencias/math_rock/  ← biblioteca de temas de referencia
  generos/versiones/              ← snapshots (revertibles en Settings)
```

- **Settings → 🎓 Añadir canción al perfil…**: registra un tema tuyo
  terminado (medidas + tu nota) como referencia propia del género.
- **Settings → ↩ Revertir género…**: vuelve a cualquier versión anterior.

## Si algo falla

Los errores quedan en `logs\app.log` — mándalo al chat y lo revisamos.
