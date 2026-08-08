# Lockfile, SBOM y SCA (P2.14)

## Archivos

| Archivo | Rol |
|---------|-----|
| `requirements.in` | Dependencias de alto nivel (las que editás vos) |
| `requirements.txt` | **Lockfile** con versiones exactas (`paquete==x.y.z`) |
| `sbom/cyclonedx-requirements.json` | Inventario SBOM (CycloneDX), opcional en Git |

Render y `build_windows.bat` instalan desde **`requirements.txt`** (pineado).

## Actualizar dependencias

1. Editá `requirements.in` (agregar/subir rangos).
2. Regenerá el lock:

```bat
python tools\actualizar_lockfile.py
```

Ideal: regenerar con la **misma major de Python** que Render (`PYTHON_VERSION=3.12.x` en `render.yaml`). Si solo tenés 3.13/3.14 local, el lock suele servir igual, pero conviene validar el deploy.

3. Auditoría de vulnerabilidades (SCA):

```bat
python -m pip install pip-audit
python tools\auditar_dependencias.py
```

4. SBOM:

```bat
python tools\generar_sbom.py
```

Salida: `sbom/cyclonedx-requirements.json`

## Por qué importa

- Mismos builds en tu PC, Render y el portable (menos “funcionaba ayer”).
- `pip-audit` avisa CVEs conocidos antes de comercializar.
- El SBOM sirve para inventario / due diligence de clientes o auditorías.

## Nota Authenticode

La firma del `.exe` (certificado de pago) sigue pendiente; ver `docs/FIRMA_AUTHENTICODE.md`.
