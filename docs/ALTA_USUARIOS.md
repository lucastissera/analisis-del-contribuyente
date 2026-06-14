# Alta de usuarios por enlace

Flujo para que un cliente **solicite acceso**, **elija su contraseña** por enlace y vos recibas aviso **sin enviarle la clave por WhatsApp**.

## Flujo recomendado (modo casero)

1. Cliente te contacta por **WhatsApp** y abona la suscripción.  
2. Vos en **Inicio → Altas de usuarios → Generar enlace** (CUIT + email).  
3. Le enviás el enlace por WhatsApp.  
4. El cliente elige contraseña → queda **pendiente de aprobación**.  
5. Verificás el pago y pulsás **Aprobar (pagó)** → recién ahí puede ingresar.

Si el cliente usa «Solicitar enlace» desde el login sin hablar contigo, igual queda pendiente hasta tu OK.

Para ocultar el alta público y dejar solo WhatsApp:

```env
AUTH_ALTA_PUBLICA=0
```

## Aprobación

- **Pendientes:** panel admin, botón «Aprobar (pagó)» o «Rechazar».  
- **Login bloqueado** con mensaje claro si la contraseña es correcta pero falta aprobación.  
- Los portables **no** reciben usuarios pendientes (solo aprobados).

## Flujo técnico

```mermaid
sequenceDiagram
    participant C as Cliente
    participant W as Web
    participant A as Admin

    C->>W: /solicitar-acceso (CUIT + email)
    W->>C: Enlace /activar-cuenta/TOKEN
    C->>W: Elige contraseña
    W->>A: Email (SMTP) + registro en panel admin
    C->>W: Login con CUIT + contraseña
```

1. Login → **Solicitar acceso (alta con CUIT)**  
2. CUIT (11 dígitos) = **usuario**  
3. Email de contacto (obligatorio)  
4. Sistema genera enlace válido **72 h** (configurable)  
5. Cliente abre enlace → define contraseña (mín. 8 caracteres, **bcrypt**)  
6. Vos recibís aviso por **email** (si configurás SMTP) y ves la alta en **Inicio → Altas de usuarios** (admin)

## Configuración en Render

### Notificación por email (recomendado)

```env
AUTH_ADMIN_NOTIFY_EMAIL=tu@gmail.com
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=tu@gmail.com
SMTP_PASSWORD=contraseña-de-aplicacion
SMTP_FROM=tu@gmail.com
```

### WhatsApp

No hay envío automático a WhatsApp (requeriría API de pago). En el panel **Altas de usuarios** hay un link **WhatsApp** con mensaje prearmado por cada alta.

```env
AUTH_ADMIN_WHATSAPP=5493513132914
```

### Persistencia (Render)

**Recomendado (plan gratis):** PostgreSQL en [Neon](https://neon.tech). Guía: `docs/AUTH_DATABASE_NEON.md`.

```env
DATABASE_URL=postgresql://usuario:clave@ep-xxxx.neon.tech/neondb?sslmode=require
```

Con `DATABASE_URL`, las altas **sobreviven redeploys** de Render.

**Alternativa de pago en Render:** disco persistente + `AUTH_REGISTRATIONS_DIR=/var/data/aic_auth`.

Sin ninguno de los dos, los datos van al disco temporal del contenedor y **se pierden** al redeployar.

### Opcionales

| Variable | Default | Uso |
|----------|---------|-----|
| `AUTH_ALTA_TOKEN_HORAS` | 72 | Validez del enlace |
| `AUTH_MIN_PASSWORD_LEN` | 8 | Longitud mínima contraseña |

## Usuarios admin vs altas

- **Lucas (admin)** con `DATABASE_URL` se guarda en Neon (`usuarios_registrados`, clave `Lucas`, `rol: admin`, contraseña bcrypt). Podés quitar `AUTH_USERS_JSON` de Render.
- **Clientes nuevos** quedan en el mismo blob con CUIT como clave y contraseña **hasheada**.
- **Alta directa (admin):** en **Inicio → Altas de usuarios**, sección «Alta directa (CUIT y contraseña)»: definís CUIT, contraseña y fecha de vencimiento; el usuario queda activo al instante y se guarda en Neon (igual que el resto).
- Los portables sincronizados reciben esos usuarios vía `/api/auth-users` (hashes bcrypt).

## Recuperación de contraseña

Todavía no hay “olvidé mi contraseña”. Si un cliente la pierde, generá un nuevo enlace desde **Solicitar acceso** (si el CUIT no está duplicado) o reset manual en `AUTH_USERS_JSON` / borrado del overlay.
