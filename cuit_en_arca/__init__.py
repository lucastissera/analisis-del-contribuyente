"""
CUIT en ARCA — descarga masiva Mis Comprobantes desde planilla Excel.
"""

from cuit_en_arca.errores import (
    ArcaProcesoError,
    AutomatizacionArcaError,
    AutomatizacionNoDisponibleError,
    CredencialesArchivoError,
    CuitRepresentadoNoEncontradoError,
    FechaRangoInvalidaError,
    LoginArcaError,
)
from cuit_en_arca.lote import ResultadoLoteArca, ejecutar_lote_planilla_arca
from cuit_en_arca.service import automatizacion_cuit_arca_habilitada

__all__ = [
    "ArcaProcesoError",
    "AutomatizacionArcaError",
    "AutomatizacionNoDisponibleError",
    "CredencialesArchivoError",
    "CuitRepresentadoNoEncontradoError",
    "FechaRangoInvalidaError",
    "LoginArcaError",
    "ResultadoLoteArca",
    "automatizacion_cuit_arca_habilitada",
    "ejecutar_lote_planilla_arca",
]
