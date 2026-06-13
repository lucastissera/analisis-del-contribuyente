# Usuarios en la nube (portable + online)

Este documento describe cómo centralizar el listado de usuarios **fuera del repositorio Git**, para que vos lo actualices una sola vez y todas las instalaciones (portables y servidor web) tomen los cambios.

## Idea general

```mermaid
flowchart LR
    A[Variable AUTH_USERS_JSON en Render] --> B[Servidor online]
    B --> C[Login web]
    B -->|HTTPS + token| D[Portables .exe]
    D --> E[Caché en LOCALAPPDATA]
    E --> F[Login portable]
```

- **No commitear** `auth_users.json` con claves reales (está en `.gitignore`).
- En **Render**, el listado vive en la variable de entorno **`AUTH_USERS_JSON`**.
- Los **portables** pueden sincronizar desde **`GET /api/auth-users`** con token Bearer.

## Formato del JSON

Ejemplo con administrador, vencimiento y metadatos:

```json
{
  "version": 1,
  "updated_at": "2026-06-08T15:30:00+00:00",
  "users": {
    "Lucas": {
      "password": "Lucas1992.",
      "rol": "admin",
      "valido_hasta": "2027-06-08"
    },
    "juan": {
      "password": "clave-segura-2",
      "email": "juan@gmail.com",
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
AUTH_USERS_JSON={"version":1,"users":{"Lucas":{"password":"Lucas1992.","rol":"admin","valido_hasta":"2027-06-08"},"prueba":{"password":"prueba","valido_hasta":"2026-06-30"}}}
AUTH_USERS_REMOTE_TOKEN=un-token-largo-y-secreto
AUTH_ADMIN_USER=Lucas
```

Para editar usuarios: modificás `AUTH_USERS_JSON` en el dashboard y guardás (Render redeploya solo).

**Portables** — archivo `auth_remote.txt` junto al `.exe`:

```text
https://tu-app.onrender.com/api/auth-users
un-token-largo-y-secreto
```

O en `.env` local:

```env
AUTH_USERS_URL=https://tu-app.onrender.com/api/auth-users
AUTH_USERS_REMOTE_TOKEN=un-token-largo-y-secreto
AUTH_USERS_REFRESH_SEC=120
```

## Desarrollo local

1. Copiá `auth_users.example.json` → `auth_users.json` (ignorado por Git).
2. Editá usuarios ahí para probar en `python app.py` o el portable.

| Variable | Uso |
|----------|-----|
| `AUTH_USERS_PATH` | Fuerza un JSON local (ignora la nube). |
| `AUTH_ADMIN_USER` / `AUTH_ADMIN_PASSWORD` | Un solo usuario de respaldo. |

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
