# Cursor Cloud — chat de administración

Panel web **solo para usuarios con rol admin** (`"rol": "admin"` en `AUTH_USERS_JSON` o `AUTH_ADMIN_USER`).

Permite chatear con un **Cloud Agent de Cursor** para pedir cambios de código. La clave API **nunca** llega al navegador: la app actúa como proxy en el servidor.

## Configuración en Render

Variables de entorno (Secret):

| Variable | Obligatoria | Descripción |
|----------|-------------|-------------|
| `CURSOR_API_KEY` | Sí | API key desde [Cursor Dashboard](https://cursor.com) → Integrations / API Keys |
| `CURSOR_REPO_URL` | Recomendada | URL del repo GitHub (debe estar autorizado en la app GitHub de Cursor) |
| `CURSOR_REPO_BRANCH` | No | Rama base (default `main`) |
| `CURSOR_MODEL` | No | Modelo explícito (ej. `composer-2`); si se omite, usa el default de tu cuenta |
| `CURSOR_AUTO_CREATE_PR` | No | `1` (default) abre PR al terminar cuando hay repo |

## Uso

1. Entrá con usuario admin (ej. Lucas).
2. En el inicio aparece **Cursor Cloud (admin)**.
3. Escribí el cambio que necesitás y enviá.
4. El agente responde en tiempo real; si hay repo, puede editar archivos y mostrar rama/PR.
5. **Abrir en Cursor** lleva a la sesión completa en cursor.com.
6. **Nueva conversación** reinicia el hilo (nuevo agente en el próximo mensaje).

## Seguridad

- Rutas bajo `/admin/cursor/*` devuelven **403** si no sos admin.
- Usuarios normales no ven el botón en el inicio.
- No subas `CURSOR_API_KEY` al repositorio Git.

## Referencia API

[Cloud Agents API v1](https://cursor.com/docs/cloud-agent/api/endpoints)
