# Manifiesto firmado del portable (Fase 2.1)

Cada build genera `manifest.signed.json` en la carpeta del portable: hashes SHA-256 de los archivos (excepto `ms-playwright/` y basura) firmados con Ed25519 (misma clave que entitlements).

## Build

Tras PyInstaller / Chromium / Authenticode opcional:

```bat
python tools/generar_manifest_portable.py
```

O automático en `python tools/portable_build.py` si hay `AUTH_ENTITLEMENT_PRIVATE_KEY` o `.entitlement_private.key`.

## Verificación

Al arrancar el `.exe`, la app verifica firma + hashes y guarda el resultado. En el login portable envía al servidor: `build_id`, `app_version`, `root_hash`, `integrity_ok`.

Panel admin → Altas → Dispositivos: columnas versión/build e integridad (OK / alterado / sin reporte).

## Límites

Un atacante con control total del PC puede falsear el reporte local. El manifiesto ayuda a soporte y a detectar alteraciones comunes; la autoridad comercial sigue siendo el servidor (cupo, device token, revocación).

Opcional estricto: `AUTH_MANIFEST_STRICT=1` (reservado para endurecer el arranque).
