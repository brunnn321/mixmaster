# MixMaster v0.1

Asistente local de mezcla y mastering. La máquina **mide** (LUFS, espectro,
estéreo), Claude **interpreta** (vía API o copiar/pegar en claude.ai), y el
proyecto **recuerda** (perfil + decisiones en archivos locales).
El audio nunca sale del disco: solo se envían reportes de texto.

## Instalación

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

## Ejecutar

```
.venv\Scripts\python main.py
```

En la primera ejecución la app pregunta: carpeta de proyectos, modo de
conexión (API de Anthropic o manual/portapapeles), perfil de usuario y
género de trabajo. Todo se guarda en `config/settings.json` — editable
después desde el menú **Settings**.

**Perfiles híbridos**: el contexto que se envía a Claude combina dos capas —
`config/perfiles/<usuario>.md` (equipo, sala, nivel de explicación) y
`config/generos/<genero>.md` + `.json` (referencias, estética y umbrales de
alertas del género). Los géneros son presets portables: se editan como texto
y se comparten copiando los archivos. Ver `MANUAL.md`.

## Flujo de trabajo

1. **Proyecto → Nuevo proyecto** — crea la estructura de carpetas
   (`01_originales` … `07_entregables` + `decisiones-y-feedback.md`).
2. **Cargar audio** — elige la mezcla a analizar (WAV, MP3, FLAC, OGG, AIFF).
3. *(Opcional)* **vs Referencia** — elige una referencia (MP3 de alta
   calidad va perfecto); se compara nivelada en loudness.
4. *(Opcional)* Escribe marcadores de sección: `Intro: 0:00, Riff A: 0:23`.
5. **Analizar** — genera `04_analisis/diagnostico_<version>.json` (formato
   fijo) y `diagnostico_legible.txt`, y muestra el resumen con alertas.
6. **Chat** — cada mensaje incluye automáticamente perfil + diagnóstico +
   últimas decisiones. Modo API: botón *Enviar*. Modo manual: *Copiar
   contexto* y pegar en claude.ai.
7. **Guardar decisión** — pega la conclusión, elige feedback
   (aprobado/rechazado/ajustado) y se registra en `decisiones-y-feedback.md`.

## Estructura de archivos

```
MixMaster/
  main.py               entrada
  mixmaster/            código (análisis, chat, proyectos, UI)
  config/settings.json  API key, modelo, rutas (no versionar)
  config/perfiles/      perfiles de usuario (bruno.md, daniel.md)
  config/generos/       presets de género (math_rock.md/.json, funk…)
  logs/app.log          errores y actividad
  proyectos/            (por defecto) canciones
```

## Fuera de alcance v0.1

Sin procesamiento de audio, sin comparador visual de versiones, sin
detección automática de secciones. Ver brief para el backlog v0.2/v0.3.
