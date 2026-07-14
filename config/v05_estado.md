# v0.5 Plan de Implementación (Referencias dinámicas)

## Status: CORE COMPLETADO, UI PENDIENTE

### ✅ Completado hoy (v0.5 CORE):

**Backend funcional:**
- ✅ PASO A: Subir referencias (archivo + etiqueta → config/referencias/{etiqueta}/)
- ✅ PASO B: Detector de etiqueta (analiza mezcla vs referencias, sugiere etiqueta + confianza)
- ✅ PASO C: Cepstral analysis (MFCC 13 coefs, fingerprint tímbrico)
- ✅ PASO D: Loudness range (LR, dinámica percibida por secciones)
- ✅ PASO E: Spectral flux (cambio tímbrico en el tiempo)
- ✅ PASO F: Imaging temporal (ancho estéreo por banda EN SECCIONES)
- ✅ PASO G: Headroom budget (picos vs referencias, alerta sobre-conservador)

**Archivos nuevos/modificados:**
- ✅ `mixmaster/references.py` (PASOS A-B, completo)
- ✅ `mixmaster/app_paths.py` (rutas dinámicas v0.5)
- ✅ `mixmaster/audio_analysis.py` (PASOS C-G + analizar_wav() actualizada)

**Estado de prueba:**
- PASOS A-G integrados en `analizar_wav()` → devuelve 6 análisis nuevos en el dict diagnóstico
- **NO PROBADO EN LA APP AÚN** — falta UI (PASO J) para ver los resultados

---

### ⏳ Pendiente (v0.5 UI INTEGRATION + POLISH):

**PASO H: Perfil global acumulativo**
- Actualizar `profiles.py`: sección "Reglas aprendidas" es global (no por género)
- Cada regla guardada lleva etiqueta: `[FECHA etiqueta] Tema | Regla | Estado`
- Al agregar regla con ★, se inserta versionada (snapshot automático)

**PASO I: Historial acumulativo v2**
- Mejorar `decisions.py`: cada entrada ahora guarda
  - `etiqueta_usada`: "prog", "djent", etc.
  - `referencias_usadas`: lista de archivos usados
  - Permite rastrear: "últimas 3 con prog = score 92-98 promedio"

**PASO J: Master con etiqueta (UI)**
- `main_window.py` PASO 2: mostrar sugerencia de etiqueta
  - Diálogo: "¿Usamos prog (70% similitud)?" con botones Confirmar/Cambiar
  - Guardar etiqueta_usada en historial

**PASO K: Tests (8 checks nuevos)**
- `tests/test_smoke.py`: agregar checks para PASOS A-G
  - Subir referencia, listar por etiqueta, detectar etiqueta sugerida
  - Cepstral (13 coefs), LR (rango de dinámica), Flux (cambio tímbrico)
  - Imaging temporal (anchos por sección), Headroom (picos)

**PASO L: UI + Reporte + Notificación**
- `report.py`: mostrar nuevas métricas en reporte legible
- `main_window.py`: agregar secciones a `txt_resultado` con los 6 análisis
- Notificación Windows (toast) al cerrar: "✓ MixMaster — Datos guardados"

---

### 📊 Commits:
1. ✅ v0.4.1 backup (main)
2. ✅ v0.5 PASOS A-B (Fable)
3. ✅ v0.5 PASOS C-G (Fable + Yo)

---

### 🎯 Siguientes pasos (mañana o ahora si continúas):
1. PASO H: Reescribir "Reglas aprendidas" en profiles.py (perfil global)
2. PASO I: Actualizar decisions.py (historial con etiqueta + referencias)
3. PASO J: Mostrar sugerencia de etiqueta en UI (main_window.py)
4. PASO K: Agregar 8 tests nuevos
5. PASO L: Reporte + Notificación Windows
6. **PROBAR END-TO-END**: subir referencia → elegir → ver sugerencia → master → ver 6 análisis nuevos
