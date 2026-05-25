"""
CUIT en ARCA — etapa previa opcional al procesamiento con sumar_imp_total.

- ``credenciales``: lectura del .xlsx de CUIT / clave / representado.
- ``certificados``: certificado digital (.pfx o .crt + .key).
- ``validacion``: rango de fechas <= 1 año.
- ``service``: orquestación + flag ``CUIT_EN_ARCA_PLAYWRIGHT``.
- ``automation_playwright``: navegador (selectores a mantener ante cambios AFIP).
"""

from cuit_en_arca.errores import (
    ArcaProcesoError,
    AutomatizacionArcaError,
    AutomatizacionNoDisponibleError,
    CertificadoArchivoError,
    CredencialesArchivoError,
    CuitRepresentadoNoEncontradoError,
    FechaRangoInvalidaError,
)
from cuit_en_arca.descarga import DescargaArcaResult
from cuit_en_arca.service import (
    automatizacion_cuit_arca_habilitada,
    ejecutar_flujo_certificado_arca,
    ejecutar_flujo_cuit_en_arca,
)

__all__ = [
    "DescargaArcaResult",
    "ArcaProcesoError",
    "AutomatizacionArcaError",
    "AutomatizacionNoDisponibleError",
    "CertificadoArchivoError",
    "CredencialesArchivoError",
    "CuitRepresentadoNoEncontradoError",
    "FechaRangoInvalidaError",
    "automatizacion_cuit_arca_habilitada",
    "ejecutar_flujo_certificado_arca",
    "ejecutar_flujo_cuit_en_arca",
]
