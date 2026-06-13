# Cursor Cloud — chat de administración

Panel web **solo para usuarios con rol admin** (`"rol": "admin"` en `AUTH_USERS_JSON` o `AUTH_ADMIN_USER`).

Permite chatear con un **Cloud Agent de Cursor** para pedir cambios de código. La clave API **nunca** llega al navegador: la app actúa como proxy en el servidor.

## Flujo automático (objetivo)

```mermaid
flowchart LR
    A[Admin escribe pedido] --> B[Cursor Cloud Agent]
    B --> C[Edita código en VM]
    C --> D[Commit + push GitHub]
    D --> E[PR automático]
    E --> F[Merge a main]
    F --> G[Render despliega]
```

1. Pedís el cambio en la web (admin).
2. El agente recibe instrucciones de **implementar, commitear y pushear** (automático en cada mensaje).
3. Cursor sube a una rama (`cursor/…`) o directo a la rama base si activás `CURSOR_PUSH_DIRECT=1`.
4. Con `CURSOR_AUTO_CREATE_PR=1` (default) se abre un **PR**.
5. **Mergeás el PR a `main`** → Render despliega solo (si Auto Deploy está activo).

## Configuración en Render

Variables de entorno (Secret):

| Variable | Obligatoria | Descripción |
|----------|-------------|-------------|
| `CURSOR_API_KEY` | Sí | API key desde [Cursor Dashboard](https://cursor.com) → Integrations / API Keys |
| `CURSOR_REPO_URL` | Sí* | `https://github.com/usuario/repo` autorizado en la app GitHub de Cursor |
| `CURSOR_REPO_BRANCH` | No | Rama base (default `main`) |
| `CURSOR_MODEL` | No | Modelo explícito (ej. `composer-2`) |
| `CURSOR_AUTO_CREATE_PR` | No | `1` (default) abre PR al terminar |
| `CURSOR_PUSH_DIRECT` | No | `1` pushea directo a `CURSOR_REPO_BRANCH` (sin rama cursor/) |
| `CURSOR_REQUIERE_REPO` | No | `1` (default) bloquea envío sin repo |
| `CURSOR_PROMPT_PREFIX` | No | Texto extra prepended al prompt del agente |

\* Obligatoria si `CURSOR_REQUIERE_REPO=1`.

### Checklist en la web

En **Cursor Cloud (admin)** ves el estado del enlace (API key, repo, URL válida). Botón **Probar conexión** llama a `GET /v1/models` de Cursor.

## Verificación local

```bash
python tools/verificar_cursor_cloud.py
```

**Importante:** ese script lee el entorno de **tu PC** (archivo `.env` o `cursor.env` local).  
Si las variables están **solo en Render**, el script local mostrará FAIL aunque producción esté bien.

Para validar **Render**, entrá como admin → **Cursor Cloud** → **Probar conexión** (lee el entorno del servidor desplegado).

```bash
# Con prueba de API real (requiere CURSOR_API_KEY en el entorno local):
set CURSOR_PROBAR_API=1
python tools/verificar_cursor_cloud.py
```

## Requisitos de cuenta Cursor

Los **Cloud Agents** (Background Agent) usan la API de Cursor con **facturación por uso**. Si aparece `usage_limit_exceeded`:

1. Entrá a [Cursor Dashboard → Settings](https://www.cursor.com/dashboard?tab=settings).
2. Activá **Usage-based pricing**.
3. Definí un **Spend Limit** (límite de gasto).
4. Verificá tener al menos **USD 2** disponibles hasta tu hard limit.

Esto es un requisito de **Cursor**, no de esta aplicación. El repo GitHub puede estar bien vinculado y aun así fallar el agente por billing.

## Solución de problemas

| Síntoma | Causa habitual |
|---------|----------------|
| FAIL en PC pero vars en Render | Normal: el script local no ve el dashboard de Render |
| FAIL en la web admin (Render) | Variables mal nombradas, sin redeploy, o URL de repo inválida |
| Repo «tiene valor» pero inválido | URL sin `https://`, comillas incluidas, o formato no GitHub |
| Vars solo en `render.yaml` como comentario | **No alcanza**: hay que cargarlas en **Environment** del dashboard |

### Formato correcto

```env
CURSOR_API_KEY=sk-...   # sin comillas
CURSOR_REPO_URL=https://github.com/usuario/analisismiscomprobantes
# También acepta .git al final o git@github.com:usuario/repo.git
```

Tras agregar o cambiar variables en Render: **guardar** y esperar el redeploy del servicio.

## Uso

1. Entrá con usuario admin (ej. Lucas).
2. Inicio → **Cursor Cloud (admin)**.
3. Confirmá checklist en verde → **Probar conexión** (opcional).
4. Escribí el cambio y enviá.
5. Seguí el flujo visual: agente → push → PR.
6. Abrí el PR, revisá y mergeá a `main` para que Render actualice producción.

## Seguridad

- Rutas bajo `/admin/cursor/*` → **403** si no sos admin.
- Usuarios normales no ven el botón en el inicio.
- No subas `CURSOR_API_KEY` al repositorio Git.

## Referencia API

[Cloud Agents API v1](https://cursor.com/docs/cloud-agent/api/endpoints)
