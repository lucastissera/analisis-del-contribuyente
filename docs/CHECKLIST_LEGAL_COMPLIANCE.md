# Checklist de cumplimiento legal (Argentina) — Análisis Integral del Contribuyente

Documento interno para preparar la salida comercial del SaaS. **No sustituye asesoramiento legal.** Revisar con abogado y contador antes de operar.

Referencia de datos personales: [Estudio Nunes — Protección de datos sensibles](https://estudionunes.com.ar/proteccion-de-datos-sensibles-lo-que-las-empresas-deben-saber/)

---

## 1. Implementado en el sistema (v2026-08-02)

| Ítem | Estado | Detalle |
|------|--------|---------|
| TyC publicados | ✅ | `/legal/terminos` (base LevelUp + cláusulas tipo Axoft adaptadas; §4 PI y §7 Garantía-Plazo en rojo para revisión) |
| Política de privacidad | ✅ | `/legal/privacidad` |
| Aceptación digital en alta | ✅ | Checkbox obligatorio en activación de cuenta |
| Re-aceptación al cambiar versión | ✅ | `LEGAL_VERSION` en `legal_config.py`; pantalla `/legal/aceptar` |
| Registro de prueba de consentimiento | ✅ | Campo `legal_aceptacion` en meta de usuario (Neon / JSON local) |
| Export admin CSV/JSON | ✅ | `/admin/legal/exportar-aceptaciones` |
| Email automático al aceptar legal | ✅ | Aviso al admin + confirmación al usuario |
| Transferencia internacional documentada | ✅ | Render, Neon, Resend en TyC y privacidad |
| No almacenamiento persistente de claves/CUIT de terceros | ✅ | TyC §3.2 y privacidad §2 |
| Tope responsabilidad 12 meses | ✅ | TyC §9 |
| Cláusulas de baja | ✅ | TyC §7 |
| Links legales en footer | ✅ | `partials/pie_legal.html` |

### Dónde se almacena la aceptación

- **Primario:** blob `usuarios_registrados` (PostgreSQL Neon o archivo JSON cifrado local).
- **Campos:** `version`, `aceptada_en` (UTC), `documentos`, `metodo`, `ip`, `user_agent`.
- **Resguardo recomendado:** exportar CSV/JSON desde el panel admin **mensualmente** y archivar en servidor/backups externos (no depende solo de Neon).

### ⚠️ Revisar TyC si se almacena data del licenciatario

Hoy los TyC (§4.4 y §20) afirman que el Servicio **no almacena de forma persistente** datos operativos del licenciatario y que los **backups diarios / resguardo ante fallos de hardware** recaen **penal y administrativamente** sobre el licenciatario.

**Si a futuro se implementa** almacenamiento de archivos, resultados, historiales de contribuyentes, backups en la nube, bases de datos de trabajo del usuario, etc.:

1. Revisar y actualizar TyC §4.4 y §20 (y privacidad).
2. Definir quién responde por backups y pérdida de datos.
3. Evaluar impacto RNBD / AAIP y transferencia internacional.
4. **Pendiente — período de gracia para exportar:** agregar en TyC un plazo claro (p. ej. 30 o 60 días) tras baja o falta de pago para que el usuario descargue/migre sus bases **antes** de eliminar definitivamente su información de los servidores. Hoy no aplica porque no se almacenan datos operativos del licenciatario.

---

## 2. Antes de lanzar al mercado (pendiente / externo al código)

### 2.1 Protección de datos personales (Ley 25.326 / AAIP)

- [ ] Inscribir bases de datos en **RNBD** (TAD / AAIP).
- [ ] Designar responsable interno de datos personales.
- [ ] Revisar TyC y privacidad con abogado (textos actuales son **borrador**).
- [ ] Completar variables de entorno: `LEGAL_TITULAR_RAZON_SOCIAL`, `LEGAL_TITULAR_CUIT`, `LEGAL_TITULAR_EMAIL`, `LEGAL_TITULAR_DOMICILIO`, `LEGAL_JURISDICCION`, `LEGAL_RNBD_NUMERO` (oculta aviso rojo en privacidad).
- [ ] Definir plazo de conservación post-baja (privacidad sugiere mínimo legal + defensa de reclamos).
- [ ] Procedimiento de respuesta a derechos ARCO (acceso, rectificación, supresión) vía email del titular.
- [ ] Evaluar si requiere **DPD** (delegado de protección de datos) según volumen/riesgo.

### 2.2 Transferencia internacional

- [ ] Firmar / verificar DPA (Data Processing Agreement) con Render, Neon y Resend.
- [ ] Documentar cláusulas contractuales tipo con encargados (privacidad §9).
- [ ] Mantener lista de subencargados actualizada si se agregan proveedores.

### 2.3 Facturación y relación comercial B2B

- [ ] Emitir factura por cada cobro (monotributo / RI según corresponda).
- [ ] Conservar comprobantes de transferencia / Mercado Pago / etc. (prueba de pago ante reclamos).
- [ ] Acordar por escrito (email o contrato) precio, periodicidad y condiciones de renovación.
- [ ] Política de reembolsos explícita (TyC §7.2: no reembolso salvo acuerdo).

### 2.4 Consumidor / defensa del consumidor

- [ ] Si vende a consumidor final (no solo estudios contables B2B), evaluar Ley 24.240 y plazos de arrepentimiento.
- [ ] Para B2B puro, documentar carácter profesional del cliente en onboarding.

### 2.5 Sitio y comunicaciones

- [ ] Links visibles a TyC y privacidad en login, alta y footer (hecho).
- [ ] Email transaccional con identificación del remitente y link a privacidad.
- [ ] Página de contacto / soporte con domicilio y CUIT del titular.

### 2.6 Seguridad operativa

- [ ] HTTPS obligatorio en producción (Render).
- [ ] Rotación de secretos (`AUTH_SECRET`, claves API).
- [ ] Plan de respuesta a incidentes de seguridad (notificación si aplica).

---

## 3. Procedimiento de baja de membresía

Para reducir reclamos del tipo «seguían cobrándome / seguía activo»:

1. **Confirmar solicitud** por email (dejar constancia escrita).
2. **Suspender acceso** inmediato o al vencimiento del período abonado (según lo acordado).
3. **No renovar** automáticamente sin nuevo pago.
4. **Conservar:** comprobantes de pago, fecha de baja, registro `legal_aceptacion`, logs de suspensión.
5. **Datos personales:** suprimir o anonimizar cuando no haya obligación legal de conservación (privacidad §6).
6. **Comunicar al usuario** fecha efectiva de fin de servicio por email.

---

## 4. Tope de responsabilidad (12 meses) — cómo opera

Cláusula estándar SaaS B2B en TyC §9:

> La responsabilidad total del proveedor no excede el **monto efectivamente abonado por el usuario en los 12 meses calendario anteriores** al reclamo.

- Si el usuario pagó $0 en ese período → tope $0 (salvo dolo/culpa grave).
- Si pagó $120.000 en total en 12 meses → máximo indemnizable por daños directos vinculados al servicio: $120.000.
- No cubre daños indirectos, multas AFIP/ARCA por datos mal cargados, etc.

**Importante:** las normas imperativas argentinas pueden limitar esta cláusula en ciertos supuestos; validar con abogado.

---

## 5. Cambios futuros en el código

Al publicar nueva versión legal:

1. Editar `legal_config.py` → incrementar `LEGAL_VERSION`.
2. Actualizar textos en `templates/legal/terminos.html` y `privacidad.html`.
3. Usuarios con versión distinta serán redirigidos a `/legal/aceptar` al iniciar sesión.
4. Exportar aceptaciones antes y después del cambio para auditoría.

---

## 6. Variables de entorno sugeridas

```env
LEGAL_TITULAR_RAZON_SOCIAL=Lucas Tissera Laplagne
LEGAL_TITULAR_CUIT=
LEGAL_TITULAR_EMAIL=
LEGAL_TITULAR_DOMICILIO=República Argentina
LEGAL_JURISDICCION=Tribunales Ordinarios de la Ciudad de Córdoba, Provincia de Córdoba
```

---

*Última actualización: 2026-08-02*
