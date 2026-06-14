# Persistencia de altas con PostgreSQL (Neon)

En Render **gratis** el disco del contenedor se borra en cada redeploy. Las altas de clientes (CUIT, contraseña, vencimiento, suspensiones) deben guardarse **fuera** del servidor.

**Recomendación:** [Neon](https://neon.tech) — PostgreSQL administrado, plan gratuito generoso, sin tarjeta para empezar, datos persistentes independientes de Render.

Alternativa similar: [Supabase](https://supabase.com) (también PostgreSQL gratis).

## Qué se guarda en la base

Con `DATABASE_URL` configurada, la app guarda en PostgreSQL (equivalente a los JSON anteriores):

| Dato | Contenido |
|------|-----------|
| `usuarios_registrados` | Clientes dados de alta, bcrypt, vencimiento, suspendido, **y el admin Lucas** (`rol: admin`) |
| `solicitudes_pendientes` | Enlaces de activación vigentes |
| `altas_completadas` | Historial reciente del panel admin |

**Lucas (admin)** puede vivir en la misma fila `usuarios_registrados` de Neon (recomendado). Ya no hace falta `AUTH_USERS_JSON` en Render si el admin está en la base.

Sin `DATABASE_URL`, la app sigue usando archivos JSON locales (portables y desarrollo).

---

## Paso a paso: Neon + Render

### 1. Crear proyecto en Neon

1. Entrá a [https://neon.tech](https://neon.tech) y creá una cuenta (GitHub sirve).
2. **New project** → elegí región cercana (ej. `US East` o la más próxima a Render).
3. En el dashboard, copiá la **Connection string** (modo **Pooled** recomendado para Render).
   - Formato: `postgresql://usuario:clave@ep-xxx.region.aws.neon.tech/neondb?sslmode=require`

### 2. Agregar en Render

1. Dashboard Render → tu **Web Service** → **Environment**.
2. Nueva variable:
   ```env
   DATABASE_URL=postgresql://... (pegá la URL completa de Neon)
   ```
3. Marcala como **Secret** y guardá (Render redeploya solo).

4. **Administrador Lucas** — en el primer deploy (o manualmente):

```bash
set AUTH_ADMIN_USER=Lucas
set AUTH_ADMIN_PASSWORD=Lucas1992.
set DATABASE_URL=postgresql://...
python tools/init_admin_neon.py
```

O dejá `AUTH_ADMIN_USER` y `AUTH_ADMIN_PASSWORD` en Render: al arrancar, la app crea a Lucas en Neon si aún no existe.

5. Probá login como **Lucas**. Si funciona, **borrá `AUTH_USERS_JSON`** de Render.

6. Opcional: quitá `AUTH_ADMIN_PASSWORD` de Render (la clave queda hasheada en Neon). Mantené `AUTH_ADMIN_USER=Lucas`.

No hace falta `AUTH_REGISTRATIONS_DIR` si usás Neon.

### 3. Verificar

1. Tras el deploy, hacé un alta de prueba completa (solicitud → contraseña → aprobar).
2. Forzá un **Manual Deploy** en Render.
3. El cliente de prueba debe **seguir pudiendo ingresar** con el mismo CUIT y contraseña.

Opcional en local (con Neon):

```bash
pip install psycopg2-binary
set DATABASE_URL=postgresql://...
python tools/verificar_alta_usuarios.py
```

---

## Plan gratuito Neon (referencia)

- Almacenamiento suficiente para miles de usuarios de texto/JSON.
- La base **no se borra** cuando Render redeploya.
- Límites de uso (compute/storage) — para decenas o cientos de clientes suele alcanzar sobrado.
- Revisá la página de pricing de Neon por cambios de cupo.

---

## Respaldo

Desde Neon podés exportar/dumpear la base periódicamente desde el dashboard o con `pg_dump` si más adelante querés backups formales.

---

## Desarrollo local / portables

- **Local sin `DATABASE_URL`:** archivos en `%TEMP%/aic_auth_data` o `AUTH_REGISTRATIONS_DIR`.
- **Portable (.exe):** sincroniza usuarios aprobados vía `/api/auth-users`; las altas nuevas se gestionan en el servidor web con Neon.

---

## Si el usuario desaparece tras un deploy

1. **`DATABASE_URL` no estaba activa cuando aprobaste** → quedó en disco temporal de Render y se borró. Configurá Neon y volvé a dar de alta al cliente.
2. **Connection string incorrecta** → revisá logs en Render: `Persistencia altas (PostgreSQL)` o errores `No se pudo escribir ... PostgreSQL`.
3. **Datos viejos** → usuarios aprobados antes de configurar Neon no están en la base. Solo persisten los nuevos tras tener `DATABASE_URL` bien configurada.
4. En Neon → **Tables** → `auth_registro_blob` → fila `usuarios_registrados` debe contener el JSON de clientes.

Usá la URL **Pooled** de Neon. La app agrega `sslmode=require` si falta en la URL.

---

## Email de alta al administrador

El correo **solo se envía cuando el cliente elige contraseña**, no al completar el formulario inicial.

En Render → **Logs**, después de una activación, buscá:

- `Email enviado a ...` → enviado (revisá spam)
- `AUTH_ADMIN_NOTIFY_EMAIL no configurado`
- `SMTP_USER o SMTP_PASSWORD faltante`
- `No se pudo enviar email` → revisar contraseña de aplicación de Gmail

Variables: `AUTH_ADMIN_NOTIFY_EMAIL`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`.

---

## Respaldo con JSON vs pg_dump

### ¿Alcanza exportar `auth_registro_blob` en JSON?

**Sí, como respaldo parcial y legible**, si guardás las **tres filas** (`usuarios_registrados`, `solicitudes_pendientes`, `altas_completadas`) con su columna `data` completa. Eso permite restaurar clientes y altas.

**Limitación:** restaurar desde JSON exige un `INSERT ... ON CONFLICT` manual por blob. Un error al pegar el JSON puede dejar la base inconsistente.

**Recomendación:** usá **pg_dump** como backup principal y JSON como copia de consulta rápida.

### Exportar JSON desde Neon (SQL Editor)

```sql
SELECT name, data, updated_at
FROM auth_registro_blob
ORDER BY name;
```

Exportá el resultado como JSON y guardalo con fecha en el nombre (ej. `neon_auth_backup_2026-06-08.json`).

### pg_dump — paso a paso (Windows)

1. **Instalar cliente PostgreSQL** (solo herramientas): [https://www.postgresql.org/download/windows/](https://www.postgresql.org/download/windows/) — incluye `pg_dump` y `pg_restore`.
2. En Neon → **Connection details** → copiá la URL (modo **Direct** o **Pooled**; marcala como secreto).
3. Abrí **PowerShell** y ejecutá (reemplazá la URL por la tuya; no la compartas):

```powershell
pg_dump "postgresql://USUARIO:CLAVE@HOST/neondb?sslmode=require" -t auth_registro_blob -F c -f "D:\Backups\neon_auth_2026-06-08.dump"
```

4. Verificá que el archivo `.dump` exista y tenga tamaño > 0.
5. Repetí cada semana o antes de cambios grandes.

### Restaurar desde pg_dump

```powershell
pg_restore -d "postgresql://USUARIO:CLAVE@HOST/neondb?sslmode=require" --clean --if-exists "D:\Backups\neon_auth_2026-06-08.dump"
```

`--clean` borra la tabla anterior antes de recrearla. Usalo solo si querés **reemplazar** lo que hay en Neon.

### Restaurar solo clientes desde JSON guardado

Si tenés el contenido de `data` de la fila `usuarios_registrados`:

```sql
INSERT INTO auth_registro_blob (name, data, updated_at)
VALUES (
  'usuarios_registrados',
  '{"version":1,"users":{ ... }}'::jsonb,
  NOW()
)
ON CONFLICT (name) DO UPDATE
SET data = EXCLUDED.data,
    updated_at = NOW();
```

No pegues un JSON incompleto: sobrescribiría todos los clientes con lo que incluya ese archivo.
