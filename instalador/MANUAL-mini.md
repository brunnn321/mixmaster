# MixMaster — manual

MixMaster masteriza tus temas en tu PC, sin internet y sin cuentas. Le das tu mezcla (y si quieres, un tema de referencia que suene como te gustaría) y te devuelve el master listo para subir.

---

## 1. Instalar

1. Abre **MixMaster-Instalador.exe**.
2. Si Windows muestra "Windows protegió su PC", haz clic en **Más información** y después en **Ejecutar de todas formas** (pasa con cualquier programa que no venga de una tienda).
3. Deja la carpeta que propone y haz clic en **Siguiente** hasta **Instalar**.
4. Al terminar, marca **Abrir MixMaster** y haz clic en **Finalizar**.

No necesitas instalar Python ni nada más: todo viene dentro.

---

## 2. Usar

La app va en 4 pasos, de arriba hacia abajo.

**PASO 1 · Carga tu audio**
- Arrastra tu mezcla (WAV, MP3, FLAC, M4A…) a la zona grande, o haz clic en ella para buscarla.
- También puedes cargar varios stems a la vez; la app los suma.
- La primera vez te pide crear un proyecto: ponle el nombre del tema.

**PASO 2 · Elige referencias**
- Carga un tema que suene como quieres que suene el tuyo: la app copia su tono.
- Si no tienes una referencia parecida, haz clic en **Sin referencia** y pasa directo al paso 3.

**PASO 3 · Masteriza**
- Haz clic en **MASTER** y elige el volumen final. Lo normal para subir a plataformas está alrededor de −10 LUFS; puedes elegir el de Spotify, YouTube, etc.

**PASO 4 · Resultados**
- **Escucha comparada:** reproduce tu mezcla y el master al mismo volumen, para que compares el sonido y no cuál suena más fuerte.
- **VU y espectro:** se mueven mientras suena.
- **Revisión:** si quieres más o menos brillo, grave o volumen, toca los botones y haz clic en **Rehacer master con estos cambios**.
- **Gráficas:** espectro antes y después, forma de onda, imagen estéreo y comparación contra la referencia.
- **Volver al PASO 1** para empezar otro tema.

**Qué entrega:** dos archivos en la carpeta `salida` del proyecto (se abre sola al terminar):
- `master_….wav` — WAV 48 kHz / 24 bits, para distribuir.
- `master_….mp3` — MP3 320 kbps, para escuchar o mandar.

Cada proyecto recuerda su mezcla y su referencia: al volver a abrirlo puedes seguir desde donde estabas.

---

## 3. Recibir mejoras

Cuando te manden un archivo `mejoras_mixmaster.json`:

1. En MixMaster, abre el menú **Archivo**.
2. Haz clic en **Importar mejoras (.json)…**.
3. Elige el archivo y haz clic en **Abrir**.
4. Aparece un aviso con lo que se actualizó. Los próximos masters ya salen con los ajustes nuevos.

No hace falta reinstalar.

---

## 4. Modificar la app

El código viene abierto y se puede editar con cualquier editor (VS Code, Notepad++…). Está en la carpeta donde se instaló:

`C:\Users\<tu usuario>\AppData\Local\Programs\MixMaster`

| Qué quieres cambiar | Dónde |
|---|---|
| Ajustes del master sin tocar código (topes de EQ, limitador, volumen por defecto…) | `config\master.json` |
| La cadena de master (EQ, compresión, limitador, exportación) | `mixmaster\processing.py`, función `masterizar` |
| Análisis y mediciones (LUFS, true peak, espectro, estéreo) | `mixmaster\audio_analysis.py` |
| Pantallas y botones | `mixmaster\ui\main_window.py` |
| Gráficas de resultados | `mixmaster\ui\graficas.py` |
| VU y espectro en vivo | `mixmaster\ui\medidores.py` |
| Colores e imágenes de la interfaz | `mixmaster\ui\tema.py` y la carpeta `assets` |
| Referencias por género | `config\generos\referencias\<género>\` (pon ahí tus MP3/WAV) |

Para probar un cambio, cierra MixMaster y ábrelo de nuevo. Si algo falla al abrir, el detalle queda en `logs\app.log`.

Para correrlo desde una terminal (útil cuando editas):

```
cd "C:\Users\<tu usuario>\AppData\Local\Programs\MixMaster"
python\python.exe main.py
```

---

## 5. Desinstalar

Configuración de Windows → **Aplicaciones** → **Aplicaciones instaladas** → busca **MixMaster** → **⋯** → **Desinstalar**. Tus proyectos (carpeta `proyectos`) quedan en la carpeta de instalación hasta que la borres.
