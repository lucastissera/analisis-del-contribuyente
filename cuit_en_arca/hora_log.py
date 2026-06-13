"""Marcas de tiempo para logs visibles al usuario (Argentina)."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

_TZ_AR = ZoneInfo("America/Argentina/Buenos_Aires")


def ahora_ar() -> datetime:
    return datetime.now(_TZ_AR)


def hora_log_ar() -> str:
    """``HH:MM:SS`` en hora de Argentina (independiente del TZ del servidor)."""
    return ahora_ar().strftime("%H:%M:%S")
