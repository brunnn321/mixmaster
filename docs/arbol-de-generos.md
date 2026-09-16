# Árbol de géneros y detección automática — propuesta

> Redactado 2026-09-16 a pedido de Bruno, a partir del caso them_bones2.
> Estado: **propuesta, nada de esto está implementado** salvo lo que se marca
> como "ya existe". No hay compromiso de hacerlo: es material para decidir.

## De dónde sale esto

them_bones2 se masterizó como math rock porque era el único género que
existía. El preset de master por género (commit `7463807`) arregla la mitad
del problema: cada género ya masteriza con sus propios parámetros. Queda la
otra mitad, que es la que Bruno planteó:

1. Que exista una biblioteca con los géneros que uno realmente trabaja.
2. Que la app reconozca sola de qué género es el tema cargado.
3. Que elija las referencias parecidas sin que uno las busque a mano.
4. Que todo eso no explote en miles de géneros y combinaciones.

## ¿Va en MixMaster o es otra app?

**Va en MixMaster.** El árbol no es una enciclopedia musical: es una tabla de
decisiones de mastering. Cada nodo existe únicamente porque cambia algún
parámetro del pipeline. Un explorador de géneros con historia, artistas y
audio de ejemplo sí sería otra app, y no aportaría nada al master.

Esa distinción es la que evita los millones de combinaciones:

> **Regla de corte**: un género merece nodo propio solo si su preset de master
> difiere del padre en al menos un parámetro. Si dos estilos se masterizan
> igual, son **un nodo con dos alias**, no dos nodos.

Con esa regla el árbol útil tiene entre 30 y 40 nodos, no miles. La cumbia
villera y la santafesina se masterizan prácticamente igual: un nodo, dos
alias. El grunge y el math rock no: dos nodos bajo el mismo padre.

## Qué ya existe (no hay que construirlo)

| Pieza | Dónde | Estado |
|---|---|---|
| Detector de género por audio | `references.py::detectar_etiqueta_sugerida` | **Funciona, nunca se llama** |
| Fingerprint tímbrico (13 MFCC) | `audio_analysis.py::cepstral_fingerprint` | En uso en el diagnóstico |
| Análisis de referencias cacheado | `audio_analysis.py::analizar_referencia_cacheada` | En uso |
| Biblioteca por género | `config/generos/referencias/<slug>/` | math_rock 9 · grunge 1 |
| Preset de master por género | bloque `master` del `.json` | Hecho (`7463807`) |
| Merge de configs | `processing.py::_merge_cfg` | Hecho |

El detector está **importado en `main_window.py:35` y jamás invocado**. Es el
trabajo muerto más grande del proyecto en esta área: el motor está hecho y
desconectado.

## El árbol propuesto

Nivel 1 = familias que se masterizan distinto. Entre paréntesis, el eje que
las diferencia de verdad en el master.

```
MÚSICA
├── Guitarras / banda        (medios con cuerpo, crest ~10, grave controlado)
│   ├── grunge                 · notches suaves, mono-bass 80, -10.5 LUFS
│   ├── math rock / prog       · transientes vivos, aire, -9 LUFS
│   ├── indie / alternativo    · menos densidad, más dinámica
│   ├── punk / garage          · crudo, matching mínimo
│   ├── hard rock / clásico    · medios densos, poco brillo
│   └── stoner / doom          · low-mid protegido, sin limpiar el barro
├── Metal                    (densidad alta, crest bajo, low-mid quirúrgico)
│   ├── thrash / death         · claridad de púa, 3-5 kHz vigilado
│   ├── djent / moderno        · sub controlado, mono-bass estricto
│   └── black / atmosférico    · no aplastar el ruido de fondo
├── Pop                      (brillo alto, sub presente, loud)
│   ├── pop moderno            · -8 LUFS, aire generoso
│   ├── synth pop              · ancho estéreo alto
│   └── balada / pop rock      · dinámica de arreglo respetada
├── Urbano                   (sub dominante, crest bajo, mono-bass estricto)
│   ├── trap                   · sub por encima de todo
│   ├── boom bap               · crest medio, carácter de sampler
│   ├── reggaetón              · dembow con pegada, -7 LUFS
│   └── drill                  · sub largo, medios vacíos a propósito
├── Electrónica              (sub + ancho, loud, transientes de club)
│   ├── house / techno         · groove sostenido, sin bombeo
│   ├── drum & bass            · transientes extremos, sub limpio
│   └── ambient / downtempo    · crest alto, casi sin limitar
├── Latino / tropical        (percusión con pegada, medios densos)
│   ├── cumbia                 · bajo y güira legibles, medios llenos
│   ├── salsa / timba          · bronces sin dureza, crest medio-alto
│   └── bachata / merengue     · guitarra y percusión al frente
├── Folclore                 (dinámica alta, poco procesamiento)
│   ├── andino / boliviano     · morenada, caporal, saya, tinku, huayño
│   ├── folk / cantautor       · voz y guitarra, crest 12+
│   └── acústico de cámara     · matching mínimo, sin densidad
├── Jazz / clásico           (crest muy alto, limitador solo de seguridad)
│   ├── combo / trío           · nada de multibanda
│   ├── big band               · bronces con aire
│   └── orquesta / coral       · -14 LUFS o menos, sin densidad
└── Voz hablada              (ya cubierto por voice_processing.py)
    ├── podcast
    └── locución / audiolibro
```

Sobre la rama **andina/boliviana**: no hay referencias comerciales modernas
bien masterizadas de morenada o caporal con la disponibilidad que hay de rock.
Esa rama va a depender de material propio o de masters que Bruno considere
buenos, y probablemente sea la que más valor le dé, justamente porque nadie
más la tiene armada.

## Cómo funciona la herencia

Un hijo hereda el preset del padre y solo declara lo que cambia. Es
exactamente el `_merge_cfg` que ya existe, con un paso más en la cadena:

```
CONFIG_MASTER_DEFAULT  →  config/master.json  →  ancestros del género  →  género
```

Ejemplo, con el formato que ya está en el repo:

```json
// guitarras.json (padre)
"master": {
  "target_lufs_default": -9.0,
  "eq_correctivo":     { "max_correccion_db": 8.0 },
  "mono_bass":         { "freq_hz": 90.0 },
  "transient_shaping": { "cantidad": 0.25 }
}

// grunge.json (hijo) — solo declara la diferencia
"padre": "guitarras",
"master": {
  "target_lufs_default": -10.5,
  "eq_correctivo": { "max_correccion_db": 10.0 },
  "resonancias":   { "umbral_db": 8.0, "max_cut_db": 2.0, "max_n": 2 },
  "mono_bass":     { "freq_hz": 80.0 }
}
```

Ventaja concreta: cuando se aprende algo que vale para toda la familia —por
ejemplo "en guitarras nunca pasar de 8 dB de matching"— se corrige el padre y
baja a los seis hijos, en vez de repetirlo seis veces.

## Detección: qué le falta al detector que ya existe

`detectar_etiqueta_sugerida()` compara MFCC + espectro contra cada carpeta y
devuelve la ganadora con confianza. Lo que le falta:

1. **Que alguien la llame.** Al cargar audio en el PASO 1, mostrar "Suena a
   grunge (confianza 0.78) — ¿lo uso?" con opción de corregir. La corrección
   del usuario es dato de entrenamiento y se registra en `aprendizaje.json`,
   que ya existe.
2. **Fallback al padre.** Si la confianza es baja pero todos los candidatos
   cuelgan de la misma rama, usar el preset del **padre**. Distinguir grunge de
   hard rock es difícil; saber que es rock de guitarras y no trap es fácil. El
   árbol convierte una duda en una respuesta segura, y ese es su valor real
   más allá de la organización.
3. **Más features.** Hoy usa MFCC + espectro. Están medidos y sin usar: crest,
   PLR, punch, inclinación espectral, centroide y ancho estéreo por banda. Con
   esos ejes, trap y jazz dejan de poder confundirse.
4. **Umbral honesto.** Con menos de 5 temas por género la confianza no
   significa nada. Debajo de ese piso la app debería sugerir sin insistir.

## Selección de referencias por similitud

Hoy se eligen las referencias de una carpeta. La propuesta es elegir **las N
más parecidas de toda la biblioteca**, sin importar en qué carpeta estén.

Esto ataca el problema de fondo de them_bones2: la referencia elegida estaba a
14 dB de distancia en aire y el matching persiguió toda la sesión algo
inalcanzable. Un selector por similitud habría avisado que ninguna referencia
de la biblioteca estaba cerca, en lugar de dejar que el pipeline lo intentara.

El aviso de `distancia_referencia_db` ya detecta esto después del hecho
(`processing.py`, umbral 4.6 dB/banda). Con el selector, el aviso pasa a ser
previo: "la referencia más cercana que tienes está a 6.2 dB — el matching no
va a sonar a nada".

## Fases

| Fase | Qué | Tamaño |
|---|---|---|
| 1 | `arbol.json` + herencia en `cargar_config_master` | Chica — reusa `_merge_cfg` |
| 2 | Conectar el detector al PASO 1 con confirmación del usuario | Chica — el motor existe |
| 3 | Selector de referencias por similitud + aviso previo | Media |
| 4 | **Poblar la biblioteca** (3-6 temas por género que se trabaje) | Sin código, decide todo |

Las fases 1-3 son de código y son chicas. La fase 4 no tiene código y es la
única que determina si esto funciona: un árbol de 40 nodos con una referencia
cada uno es peor que dos géneros bien poblados.

## La objeción que corresponde hacer

El roadmap tiene un veredicto de El Consejo del 2026-08-05 que sigue vigente:
el cuello de botella de Bruno no son más features de la app, es volumen de
trabajo real y feedback externo. Este documento propone features.

La parte que **sí** escapa a esa objeción es la fase 4: juntar y escuchar
referencias por género no es programar la app, es entrenar el oído y armar el
criterio. Es exactamente el trabajo que El Consejo pedía. Las fases 1-3 se
justifican solo como consecuencia de la 4, no antes.

Orden recomendado: **4 → 1 → 2 → 3**. Poblar primero, automatizar después.
