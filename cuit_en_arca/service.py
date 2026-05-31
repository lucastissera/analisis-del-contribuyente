"""
Orquestación de la etapa «CUIT en ARCA» (antes de sumar_imp_total).

No importa ni modifica sumar_imp_total: el flujo termina en un archivo descargable
que el usuario puede volver a subir en «Procesador de Comprobantes», o procesarse
en cadena si lo solicita la interfaz.
"""

from __future__ import annotations

import io
import os
from datetime import date
from typing import Literal

from cuit_en_arca.certificados import (
    CredencialesCertificado,
    construir_credenciales_certificado,
    limpiar_temporales_certificado,
)
from cuit_en_arca.credenciales import leer_credenciales_xlsx
from cuit_en_arca.descarga import DescargaArcaResult
from cuit_en_arca.errores import AutomatizacionNoDisponibleError, FechaRangoInvalidaError
from cuit_en_arca.validacion import parsear_fecha_argentina, validar_rango_max_un_anio

TipoComprobantes = Literal["emitidos", "recibidos", "ambos"]


def automatizacion_cuit_arca_habilitada() -> bool:
    """Variable de entorno explícita (evita lanzar Chromium en Render sin deps)."""
    v = os.environ.get("CUIT_EN_ARCA_PLAYWRIGHT", "").strip().lower()
    return v in ("1", "true", "yes", "on")


def _resolver_fechas(
    cred_desde: str | None,
    cred_hasta: str | None,
    fecha_desde_texto: str | None,
    fecha_hasta_texto: str | None,
) -> tuple[date, date]:
    fd = (fecha_desde_texto or "").strip() or None
    fh = (fecha_hasta_texto or "").strip() or None
    if cred_desde and cred_hasta:
        fd, fh = cred_desde, cred_hasta
    if not fd or not fh:
        raise FechaRangoInvalidaError(
            "Indicá el rango en el formulario (dd/mm/yyyy) o en la columna D del Excel "
            "(Rango Fechas), por ejemplo: 01/01/2025 - 31/12/2025."
        )
    desde = parsear_fecha_argentina(fd)
    hasta = parsear_fecha_argentina(fh)
    validar_rango_max_un_anio(desde, hasta)
    return desde, hasta


def _requiere_playwright() -> None:
    import sys

    from cuit_en_arca.playwright_env import chromium_instalado_en_portable

    if getattr(sys, "frozen", False) and not chromium_instalado_en_portable():
        raise AutomatizacionNoDisponibleError(
            "Chromium no está instalado junto al ejecutable (carpeta ms-playwright). "
            "Recompilá el portable con build_windows.bat para incluir el navegador."
        )
    if not automatizacion_cuit_arca_habilitada():
        raise AutomatizacionNoDisponibleError(
            "La descarga automática desde AFIP está deshabilitada en este servidor. "
            "Para usarla en local: definí la variable de entorno CUIT_EN_ARCA_PLAYWRIGHT=1, "
            "instalá dependencias (pip install playwright) y ejecutá: playwright install chromium"
        )


def _headless_desde_env() -> bool:
    return os.environ.get("CUIT_EN_ARCA_HEADLESS", "1").strip().lower() not in (
        "0",
        "false",
        "no",
    )


def ejecutar_flujo_cuit_en_arca(
    archivo_credenciales: io.BytesIO,
    fecha_desde_texto: str | None = None,
    fecha_hasta_texto: str | None = None,
    *,
    tipo_comprobantes: TipoComprobantes = "emitidos",
) -> DescargaArcaResult:
    """Valida entradas y ejecuta Playwright con planilla Excel."""
    cred = leer_credenciales_xlsx(archivo_credenciales)
    desde, hasta = _resolver_fechas(
        cred.rango_fecha_desde,
        cred.rango_fecha_hasta,
        fecha_desde_texto,
        fecha_hasta_texto,
    )
    _requiere_playwright()
    from cuit_en_arca.automation_playwright import ejecutar_descarga_mis_comprobantes

    return ejecutar_descarga_mis_comprobantes(
        cred,
        desde,
        hasta,
        headless=_headless_desde_env(),
        tipo=tipo_comprobantes,
    )


def ejecutar_flujo_certificado_arca(
    *,
    archivo_pfx: io.BytesIO | None = None,
    nombre_pfx: str | None = None,
    archivo_cert: io.BytesIO | None = None,
    nombre_cert: str | None = None,
    archivo_key: io.BytesIO | None = None,
    nombre_key: str | None = None,
    passphrase: str | None = None,
    cuit_login_texto: str | None = None,
    cuit_representado_texto: str | None = None,
    fecha_desde_texto: str | None = None,
    fecha_hasta_texto: str | None = None,
    tipo_comprobantes: TipoComprobantes = "emitidos",
) -> DescargaArcaResult:
    """Descarga Mis Comprobantes autenticando con certificado digital."""
    fd = (fecha_desde_texto or "").strip() or None
    fh = (fecha_hasta_texto or "").strip() or None
    if not fd or not fh:
        raise FechaRangoInvalidaError(
            "Indicá fecha desde y hasta (dd/mm/yyyy). El rango máximo es un año."
        )
    desde = parsear_fecha_argentina(fd)
    hasta = parsear_fecha_argentina(fh)
    validar_rango_max_un_anio(desde, hasta)

    cred_cert = construir_credenciales_certificado(
        archivo_pfx=archivo_pfx,
        nombre_pfx=nombre_pfx,
        archivo_cert=archivo_cert,
        nombre_cert=nombre_cert,
        archivo_key=archivo_key,
        nombre_key=nombre_key,
        passphrase=passphrase,
        cuit_login_texto=cuit_login_texto,
        cuit_representado_texto=cuit_representado_texto,
    )
    _requiere_playwright()
    from cuit_en_arca.automation_playwright import (
        ejecutar_descarga_mis_comprobantes_certificado,
    )

    try:
        return ejecutar_descarga_mis_comprobantes_certificado(
            cred_cert,
            desde,
            hasta,
            headless=_headless_desde_env(),
            tipo=tipo_comprobantes,
        )
    finally:
        limpiar_temporales_certificado(cred_cert)
