"""Nombres de carpetas de salida con fecha y hora (evita colisiones el mismo día)."""

from __future__ import annotations

from datetime import datetime

from cuit_en_arca.hora_log import ahora_ar


def stamp_carpeta_ejecucion(momento: datetime | None = None) -> str:
    """``yyyy-mm-dd HH-MM`` (sin ``:`` por compatibilidad en Windows)."""
    m = momento or ahora_ar()
    return m.strftime("%Y-%m-%d %H-%M")
