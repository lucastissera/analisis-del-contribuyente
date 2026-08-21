# Instrucciones para agentes (Cursor / IA)

## Nuevos servicios (parámetro de control)

Al establecer o extender servicios: **no pisar ni descalibrar** los que ya funcionan. Preferir adición aislada (clave/módulo/ruta propios) sobre reescritura de lógica compartida. Detalle en `.cursor/rules/acoplamiento-nuevos-servicios.mdc`.

## Build portable (solo cuando lo pida el usuario)

El ejecutable vive en:

`dist/AnalisisIntegralContribuyente/AnalisisIntegralContribuyente.exe`

**No lo recompiles automáticamente** al terminar cambios de código. Compilá **solo** si el usuario lo pide explícitamente.

### Comando

Desde la raíz del proyecto:

```powershell
python tools/portable_build.py
```

O en Windows:

```bat
build_windows.bat
```

### Vigilancia automática (opcional, manual del usuario)

Si el usuario quiere rebuilds mientras edita, puede dejar abierto en una terminal (recompila ~3,5 s después del último guardado):

```bat
watch_portable.bat
```

Eso es independiente del agente: no lo arranques vos salvo que te lo pidan.

### Hooks de Cursor

Los hooks de rebuild automático (`afterFileEdit` / `stop`) están **desactivados** en `.cursor/hooks.json`. La regla `.cursor/rules/rebuild-portable.mdc` también indica compilar solo a pedido.

### Actualizador (Inno) — solo cuando lo pida el usuario

No armes el instalador automáticamente al terminar cambios de código. El portable y el update son **dos comandos distintos**.

1. Portable (si hace falta): `python tools/portable_build.py`
2. Instalador: `python tools/portable_installer.py` o `build_installer.bat`  
   Paquete liviano (sin Chromium, si el destino ya lo tiene): `python tools/portable_installer.py --sin-playwright`

Salida: `dist/instalador/AIC-Update-<versión>.exe`

En Estudio DyC se actualiza **una carpeta por vez**. Lo unico que se ejecuta es:

```bat
aplicar_update.bat
```

Sin argumentos abre el asistente (elegí `D:\sistemas\juan`). Cuando termine, ejecutalo de nuevo para Diego.

```bat
aplicar_update.bat "D:\sistemas\juan"
```

Elige solo el paquete (completo o liviano) y no pisa `navegador-perfil` ni Chromium si ya esta. El ZIP de `dist\AnalisisIntegralContribuyente\` queda como rescate. Login y cupo van al servidor (no hace falta `auth_remote.enc` ni `auth_users.enc` junto al .exe).

### Qué no versionar

`dist/` y `build/` están en `.gitignore`; el `.exe` y el instalador se generan localmente, no se suben a Git.
