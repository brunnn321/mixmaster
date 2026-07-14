# v0.5 Plan de Implementación (Referencias dinámicas)

## Status: EN PROGRESO

### ✅ Completado (v0.4.1):
- ✅ Matching espectral fino (1/3 octava)
- ✅ Clipper pre-limitador
- ✅ Score A/B (tonal/dinámica/imagen)
- ✅ Auto-análisis al elegir referencias
- ✅ Auto-avance entre pasos
- ✅ **PASOS A-B (Fable)**: Subir referencias + Detector de etiqueta
- ✅ **PASOS C-G (Fable)**: Cepstral, LR, Flux, Imaging temporal, Headroom budget

### 🔄 EN PROGRESO (v0.5 — Yo ahora):
- [ ] H: Perfil global acumulativo
- [ ] I: Historial acumulativo v2
- [ ] J: Master con etiqueta (UI reporte)
- [ ] K: Tests (8 checks nuevos)
- [ ] L: UI + Reporte + Toast notification

### Nuevos archivos creados:
- ✅ `mixmaster/references.py` (Fable — PASOS A-B)

### Archivos modificados:
- ✅ `app_paths.py` (Fable — nuevas rutas)
- ✅ `audio_analysis.py` (Fable — PASOS C-G: 5 funciones nuevas + analizar_wav actualizada)
- ⏳ `profiles.py` (pendiente — perfil global)
- ⏳ `decisions.py` (pendiente — historial v2)
- ⏳ `ui/main_window.py` (pendiente — PASO 2 sugerencia)
- ⏳ `report.py` (pendiente — mostrar nuevas métricas)
- ⏳ `tests/test_smoke.py` (pendiente — 8 checks nuevos)

### Próximo paso:
Yo (Claude Opus) continúo PASOS H-L: perfil global + historial + UI + tests + notificación Windows.

### Cronograma:
- ✅ 14:45-16:45 — Fable implementa PASOS A-G
- ⏳ 16:45-17:30 — Yo implemento PASOS H-L
- ⏳ 17:30+ — Tests, debugging, app lanzada
