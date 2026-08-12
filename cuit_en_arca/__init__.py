"""
CUIT en ARCA — descarga masiva Mis Comprobantes desde planilla Excel.

Imports pesados (lote / Playwright) se cargan bajo demanda para no demorar
el arranque del .exe hasta la pantalla de login.
"""

from __future__ import annotations

from typing import Any

from cuit_en_arca.errores import (
    ArcaProcesoError,
    AutomatizacionArcaError,
    AutomatizacionNoDisponibleError,
    CancelacionUsuarioError,
    CredencialesArchivoError,
    CuitRepresentadoNoEncontradoError,
    FechaRangoInvalidaError,
    LoginArcaError,
)

__all__ = [
    "ArcaProcesoError",
    "AutomatizacionArcaError",
    "AutomatizacionNoDisponibleError",
    "CredencialesArchivoError",
    "CuitRepresentadoNoEncontradoError",
    "FechaRangoInvalidaError",
    "LoginArcaError",
    "CancelacionUsuarioError",
    "ResultadoLoteArca",
    "automatizacion_cuit_arca_habilitada",
    "ejecutar_lote_arca",
    "ejecutar_lote_planilla_arca",
]


def __getattr__(name: str) -> Any:
    if name in ("ResultadoLoteArca", "ejecutar_lote_arca", "ejecutar_lote_planilla_arca"):
        from . import lote as _lote

        return getattr(_lote, name)
    if name == "automatizacion_cuit_arca_habilitada":
        from .service import automatizacion_cuit_arca_habilitada as _fn

        return _fn
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
