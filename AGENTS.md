# Instrucciones para agentes (Cursor / IA)

## Build portable obligatorio tras cambios de código

Cada vez que modifiques archivos de la aplicación (`app.py`, `sumar_imp_total.py`, `templates/`, `cuit_en_arca/`, `i18n.py`, etc.), **debés actualizar el ejecutable** en:

`dist/MisComprobantesAnalisis/MisComprobantesAnalisis.exe`

### Comando (siempre al finalizar una tarea con cambios)

Desde la raíz del proyecto:

```powershell
python tools/portable_build.py
```

O en Windows, doble clic / consola:

```bat
build_windows.bat
```

### Vigilancia automática (recomendado en desarrollo)

Dejá abierto en una terminal (recompila ~3,5 s después del último guardado):

```bat
watch_portable.bat
```

### Hook de Cursor (automático)

El proyecto incluye `.cursor/hooks.json`:

- **`afterFileEdit`**: tras guardar cambios relevantes (`.py`, `templates/`, etc.), programa un rebuild con debounce (~3,5 s) vía `tools/hook_schedule_build.py`.
- **`stop`**: al terminar el agente, lanza un rebuild inmediato.

Log del hook: `build/hook-rebuild.log`. Si el `.exe` está en ejecución, cerralo antes del build para evitar archivos bloqueados.

### Regla del agente

`.cursor/rules/rebuild-portable.mdc` obliga a recompilar el portable al finalizar cualquier tarea con cambios de código, sin pedírselo al usuario.

### Qué no versionar

`dist/` y `build/` están en `.gitignore`; el `.exe` se genera localmente, no se sube a Git.
