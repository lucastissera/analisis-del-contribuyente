# Persistencia de altas con PostgreSQL (Neon)

En Render **gratis** el disco del contenedor se borra en cada redeploy. Las altas de clientes (CUIT, contraseña, vencimiento, suspensiones) deben guardarse **fuera** del servidor.

**Recomendación:** [Neon](https://neon.tech) — PostgreSQL administrado, plan gratuito generoso, sin tarjeta para empezar, datos persistentes independientes de Render.

Alternativa similar: [Supabase](https://supabase.com) (también PostgreSQL gratis).

## Qué se guarda en la base

Con `DATABASE_URL` configurada, la app guarda en PostgreSQL (equivalente a los JSON anteriores):

| Dato | Contenido |
|------|-----------|
| `usuarios_registrados` | Clientes dados de alta, bcrypt, vencimiento, suspendido, etc. |
| `solicitudes_pendientes` | Enlaces de activación vigentes |
| `altas_completadas` | Historial reciente del panel admin |

**Lucas (admin)** sigue en `AUTH_USERS_JSON` de Render — no hace falta moverlo.

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
