"""Resultado de una o dos descargas desde Mis Comprobantes."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DescargaArcaResult:
    """Un archivo (emitidos o recibidos) o ambos en la misma sesión AFIP."""

    emitidos: tuple[bytes, str] | None = None
    recibidos: tuple[bytes, str] | None = None

    @classmethod
    def simple(cls, data: bytes, nombre: str, *, emitidos: bool) -> DescargaArcaResult:
        par = (data, nombre)
        if emitidos:
            return cls(emitidos=par)
        return cls(recibidos=par)

    @property
    def es_dual(self) -> bool:
        return self.emitidos is not None and self.recibidos is not None

    @property
    def simple_par(self) -> tuple[bytes, str] | None:
        if self.es_dual:
            return None
        return self.emitidos or self.recibidos
