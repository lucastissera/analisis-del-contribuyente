# Cómo obtener el certificado digital de ARCA (AFIP)

Guía paso a paso para tramitar el certificado que usás en **Administración de Certificados Digitales** y en esta aplicación (archivo `.pfx` / `.p12` o par `.crt` + `.key`).

> El certificado del **portal** no es lo mismo que el de **webservices** (WSAA) para desarrolladores SOAP; para login en AFIP y Mis Comprobantes necesitás el del portal / clave fiscal asociada al certificado.

## Requisitos previos

1. **Clave fiscal** activa con nivel adecuado (persona física que representa o es el contribuyente).
2. Servicio **Administrador de Relaciones de Clave Fiscal** habilitado (para delegar servicios si representás a otros CUIT).
3. Navegador actualizado (Chrome o Edge recomendados).

## Paso 1 — Ingresar a ARCA / AFIP

1. Abrí [https://www.arca.gob.ar](https://www.arca.gob.ar) o [https://www.afip.gob.ar](https://www.afip.gob.ar).
2. Clic en **Iniciar sesión**.
3. Ingresá tu **CUIT/CUIL/CDI** y **clave fiscal**.

## Paso 2 — Habilitar «Administración de Certificados Digitales»

Si ya ves el servicio en el panel, pasá al **Paso 3**.

1. En el listado de servicios, entrá a **Administrador de Relaciones de Clave Fiscal**.
2. Elegí el **contribuyente** (tu CUIT o el que representás).
3. **Nueva relación** → buscá el servicio **Administración de Certificados Digitales**.
4. Confirmá la relación. Si te lo pide, aceptá la designación en **Aceptación de Designación**.
5. **Cerrá sesión y volvé a entrar** para que aparezca el servicio en el menú principal.

## Paso 3 — Generar clave y solicitud (CSR)

1. Abrí **Administración de Certificados Digitales**.
2. Seleccioná el **CUIT** para el que operás.
3. **Agregar alias** (nombre interno, por ejemplo `MisComprobantes2026`).
4. Generá una **clave privada** y un **CSR** (Certificate Signing Request):
   - ARCA publica instrucciones en la ayuda del mismo servicio.
   - También podés seguir la guía oficial: [Generación de certificados para webservices](https://www.afip.gob.ar/ws/documentacion/certificados.asp) (el CSR es el mismo concepto).
5. Subí el **CSR** en el formulario del alias y confirmá.

## Paso 4 — Descargar el certificado emitido

1. En la lista de alias, clic en **Ver** junto al alias creado.
2. Descargá el **certificado** (`.crt` / `.cer`) cuando el estado figure como emitido/activo.
3. Guardá en lugar seguro la **clave privada** que generaste al crear el CSR (`.key`). **Sin la clave, el certificado no sirve.**

## Paso 5 — Armar el archivo para esta aplicación

Elegí **una** de estas opciones:

| Opción | Qué subir en la app |
|--------|---------------------|
| **A — Contenedor PKCS#12** | Exportá o generá un `.pfx` o `.p12` que incluya certificado + clave (muchas herramientas lo crean al exportar desde el navegador o OpenSSL). |
| **B — Par de archivos** | El `.crt`/`.cer` descargado de ARCA + el `.key` de la clave privada. |

Si el `.pfx` tiene contraseña, completá el campo **Contraseña del certificado** en el formulario.

## Paso 6 — Usar el certificado en «Enlace ARCA»

1. En la app: panel **Enlace ARCA — descarga automática**.
2. Subí el `.pfx` **o** certificado + clave.
3. **CUIT representado**: el contribuyente cuyos comprobantes querés (11 dígitos).
4. **CUIT de login** (opcional): si no lo completás, la app intenta leerlo del certificado.
5. Período **desde / hasta** (máximo un año).
6. Tipo **Emitidos y recibidos** para descargar ambos en una sola ejecución.
7. Dejá marcado **Procesar automáticamente** si querés el Excel ajustado al terminar.

## Homologación (pruebas)

Para pruebas de desarrollo, ARCA ofrece el entorno **WSASS** y certificados de homologación. El trámite es similar pero en servidores de testing. Ver [Certificados — documentación ARCA](https://www.afip.gob.ar/ws/documentacion/certificados.asp).

## Seguridad

- No compartas el `.pfx`, la `.key` ni la contraseña por correo o chat.
- No subas certificados a repositorios Git.
- Renová el certificado antes del vencimiento (ARCA suele avisar en el panel del alias).

## Referencias oficiales

- [Certificados digitales (ARCA)](https://www.afip.gob.ar/ws/documentacion/certificados.asp)
- PDF: *¿Cómo obtener el Certificado Digital para entorno de producción?* en la misma sección de documentación WSAA/ARCA.
