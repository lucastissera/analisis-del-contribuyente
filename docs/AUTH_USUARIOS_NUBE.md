# Usuarios en la nube (portable + online)

Este documento describe cómo centralizar el listado de usuarios **fuera del repositorio Git**, para que vos lo actualices una sola vez y todas las instalaciones (portables y servidor web) tomen los cambios.

## ¿El compilado (.exe) está enlazado a Neon?

**No automáticamente.** Hay dos formas de usuarios en el portable:

| Modo | Configuración | Origen de usuarios |
|------|---------------|-------------------|
| **Recomendado (Neon vía web)** | `auth_remote.txt` junto al `.exe` con URL `https://analisisdelcontribuyente.onrender.com/api/auth-users` y el token Bearer | PostgreSQL **Neon** (altas aprobadas + admin), exportadas por la web en Render |
| **Local cifrado** | `auth_users.enc` junto al `.exe` (sin JSON en claro) | Archivo generado al compilar o con `python tools/encrypt_auth_users.py` |

La caché remota en `%LOCALAPPDATA%` se guarda **cifrada** (`auth_users_cache.enc`).

**No incluyas** en la carpeta del portable: `auth_users.json`, `auth_users.example.json` (solo plantilla de desarrollo en el repo).

## Idea general

```mermaid
flowchart LR
    A[Neon PostgreSQL] --> B[Servidor Render]
    B --> C[Login web]
    B -->|GET /api/auth-users + token| D[Portables .exe]
    D --> E[Caché cifrada LOCALAPPDATA]
    E --> F[Login portable]
```

- En **Render + Neon**, los usuarios viven en la base (`usuarios_registrados`); ver `docs/AUTH_DATABASE_NEON.md`.
- Los **portables** sincronizan desde **`GET /api/auth-users`** (no leen Neon directo).
- **No commitear** `auth_users.json` ni `auth_users.enc` con claves reales.

## Formato del JSON

Ejemplo con administrador, vencimiento y metadatos:

```json
{
  "version": 1,
  "updated_at": "2026-06-08T15:30:00+00:00",
  "users": {
    "Lucas": {
      "password": "CAMBIAR_POR_UN_SECRETO_UNICO",
      "rol": "admin",
      "valido_hasta": "2027-06-08"
    },
    "juan": {
      "password": "CAMBIAR_POR_OTRO_SECRETO",
      "email": "juan@example.com",
      "valido_desde": "2026-01-01",
      "valido_hasta": "2027-06-08",
      "activo": true
    }
  }
}
```

- **`rol": "admin"`** — usuario administrador (Lucas). También acepta `"es_admin": true`.
- Usuario con `"activo": false` **no puede ingresar**.
- **`valido_desde`** / **`valido_hasta`**: fechas inclusive (`YYYY-MM-DD` o `DD/MM/YYYY`).
- El campo `email` es informativo (preparado para futuras altas).

## Configuración en Render (gratis)

En el dashboard de Render → **Environment** (como *Secret*):

```env
# Preferido: Neon (DATABASE_URL) + AUTH_ADMIN_USER / AUTH_ADMIN_PASSWORD de respaldo.
# AUTH_USERS_JSON es legacy; si existe, usá placeholders (nunca contraseñas reales).
AUTH_USERS_REMOTE_TOKEN=un-token-largo-y-secreto
AUTH_ADMIN_USER=Lucas
AUTH_CUPO_REQUIRE_DEVICE=1
```

Los usuarios viven en Neon. No exportes el directorio completo a portables: `/api/auth-users` responde **410** salvo escape `AUTH_EXPORT_AUTH_USERS=1`.

**Portables** — `auth_remote.enc` (o `.txt`) junto al `.exe` con URL + token. El login usa `POST /api/auth/verificar` (la URL de sync puede seguir apuntando a `/api/auth-users` solo para derivar la base):

```text
https://analisisdelcontribuyente.onrender.com/api/auth-users
un-token-largo-y-secreto
```

O en `.env` local:

```env
AUTH_USERS_URL=https://analisisdelcontribuyente.onrender.com/api/auth-users
AUTH_USERS_REMOTE_TOKEN=un-token-largo-y-secreto
AUTH_USERS_REFRESH_SEC=120
```

**Importante (portable):** si existen **`auth_remote`** y **`auth_users.enc`** juntos, el `.enc` **no se ignora** del todo: sirve para un **admin de fábrica** que no esté en Neon. Para el **mismo usuario** que ya viene del servidor, manda la ficha remota (vigencia, cupo, rol). El cupo se consulta y descuenta solo en el servidor; sin conexión el portable **no** procesa CUITs (no se confía en el contador local).

**Token en `auth_remote.txt` / `.enc`:** bootstrap para `POST /api/auth/verificar` (y escape legacy de `/api/auth-users`). No commitear; rotar en Render si se expone. El directorio global de usuarios **ya no se exporta** por defecto (HTTP 410).

**Token de dispositivo (`dev_…`):** tras login OK se emite un Bearer ligado a usuario + `device_id` de instalación. Cupo/uso **exigen** ese token (el Bearer global ya no sirve para cupo). Panel admin → Altas → sección Dispositivos (revocar / renombrar).

**Entitlement firmado (Ed25519):** el mismo login puede devolver un JSON firmado de vida corta (cupo/vigencia). El portable lo guarda cifrado y, sin red, lo usa como tope confiable (no el contador local editable). Requiere `AUTH_ENTITLEMENT_PRIVATE_KEY` en Render (`python tools/generar_entitlement_keys.py`). TTL default 48 h (`AUTH_ENTITLEMENT_TTL_SEC`).

**Authenticode:** firma digital del `.exe` en Windows (SmartScreen). Ver `docs/FIRMA_AUTHENTICODE.md` y `tools/firmar_portable.ps1`.

**Rotación segura:** `python tools/rotar_auth_remote_token.py` genera un token nuevo. En Render poné el nuevo en `AUTH_USERS_REMOTE_TOKEN` y el viejo en `AUTH_USERS_REMOTE_TOKEN_PREVIOUS` (ambos válidos hasta redistribuir portables). Luego `--aplicar` en local y, cuando no queden copias viejas, borrá `PREVIOUS`. Alternativa más cerrada: solo `auth_users.enc` sin sync remota (sin clientes Neon automáticos).

## Desarrollo local y build portable

1. Copiá `auth_users.example.json` → `auth_users.json` (ignorado por Git).
2. Editá usuarios para probar en `python app.py`.
3. Al compilar: `python tools/portable_build.py` genera **`auth_users.enc`** en `dist/…` (cifrado).  
   O manualmente: `python tools/encrypt_auth_users.py`.

| Variable | Uso |
|----------|-----|
| `AUTH_USERS_PATH` | Fuerza un archivo local (`.json` o `.enc`). |
| `AUTH_STORE_KEY` | Clave Fernet opcional (avanzado; por defecto usa cifrado embebido). |
| `AUTH_ADMIN_USER` / `AUTH_ADMIN_PASSWORD` | Un solo usuario de respaldo. |

## Protección en portables (cupo y licencia)

Con **`auth_remote.txt`** configurado:

| Capa | Qué hace |
|------|-----------|
| **Stores `.enc`** | Cupo y altas locales en `%LOCALAPPDATA%\DepuracionExcelComprobantes\` se guardan cifrados (`usuarios_registrados.enc`, etc.). Si alguien edita el archivo, la app **deja de funcionar** y muestra error en el login. |
| **Servidor autoritativo** | Consulta y descuento de cupo solo vía Render/Neon. Sin red → cupo 0 (no se procesa). Editar archivos locales no engaña al panel. |
| **Ficha remota** | Vigencia/rol del servidor pisan `auth_users.enc` para el mismo usuario. |
| **Caché login** | `auth_users_cache.enc` también verifica integridad al descifrar. |

**Importante:** el cifrado embebido impide cambios casuales (Bloc de notas), pero **no** es DRM absoluto: un atacante avanzado podría extraer la clave del `.exe`. La defensa comercial fuerte es el **servidor + Neon** como fuente de verdad del cupo.

Para forzar cifrado también en desarrollo: `AUTH_STORE_ENCRYPT=1`.

## Protección mínima

1. Solo **HTTPS**.
2. Token **`AUTH_USERS_REMOTE_TOKEN`** en `/api/auth-users`.
3. **Nunca** subir claves al repo Git.
4. A medio plazo: migrar contraseñas a hash (`bcrypt`).

## Flujo de trabajo (admin)

1. Entrás con **Lucas** (rol admin).
2. Para cambiar usuarios en producción: editás **`AUTH_USERS_JSON`** en Render.
3. Los portables actualizan en **≤ 2 minutos** si usan sync remoto.
4. Para dar de baja: quitás el usuario o ponés `"activo": false`.

## Diagnóstico

```python
from auth import estado_auth, load_users, es_administrador
print(estado_auth())
print(len(load_users()), "usuarios cargados")
print(es_administrador("Lucas"))
```

## Próximos pasos

- Panel web de administración (solo usuario con `rol: admin`).
- Contraseñas hasheadas.
- Login con Google para usuarios finales.
