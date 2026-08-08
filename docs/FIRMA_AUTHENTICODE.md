# Firma Authenticode del portable (P2.13)

Sin firma, Windows / SmartScreen suele advertir “editor desconocido” al abrir el `.exe` en PCs de clientes. La firma **no** reemplaza la licencia en servidor; solo acredita el origen del binario.

## Qué necesitás

1. **Certificado de code signing** (OV o EV) emitido a tu razón social / LevelUp.
   - Proveedores habituales: DigiCert, Sectigo, GlobalSign, SSL.com.
   - EV reduce más las advertencias de SmartScreen a medio plazo.
2. **Windows SDK** (incluye `signtool.exe`) o Visual Studio Build Tools.
3. El portable ya compilado:
   `dist\AnalisisIntegralContribuyente\AnalisisIntegralContribuyente.exe`

## Variables

| Variable | Uso |
|----------|-----|
| `AIC_SIGN_PFX` | Ruta al `.pfx` (no subir a Git) |
| `AIC_SIGN_PFX_PASSWORD` | Contraseña del `.pfx` |
| `AIC_SIGN_TIMESTAMP_URL` | Opcional (default DigiCert) |
| `AIC_SIGN_EXE` | Opcional; ruta al `.exe` |

## Firmar

```bat
set AIC_SIGN_PFX=C:\secreto\codesign.pfx
set AIC_SIGN_PFX_PASSWORD=********
powershell -ExecutionPolicy Bypass -File tools\firmar_portable.ps1
```

O, tras `build_windows.bat`, el build llama al script si `AIC_SIGN_PFX` está definida (`python tools/portable_build.py`).

## Verificar

```powershell
Get-AuthenticodeSignature .\dist\AnalisisIntegralContribuyente\AnalisisIntegralContribuyente.exe
```

Debe decir `Status : Valid`.

## Buenas prácticas

- Guardar el `.pfx` fuera del repo (USB cifrado / vault).
- Usar **timestamp** (el script ya lo hace) para que la firma siga válida al vencer el cert.
- Rotar el certificado antes del vencimiento y volver a firmar builds nuevos.
- Un `.exe` auto-firmado (certificado casero) **no** evita SmartScreen en clientes.

## Relación con el resto de la seguridad

| Capa | Qué cubre |
|------|-----------|
| Authenticode | Origen del `.exe` en Windows |
| `auth_remote` + device token + entitlement | Licencia / cupo en servidor |
| Neon + Render | Fuente de verdad comercial |
