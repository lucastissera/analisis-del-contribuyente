"""Registro de acciones de administración (P1.10)."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any

_LOG = logging.getLogger(__name__)
_lock = threading.Lock()
_STORE = "auditoria_admin"
_MAX = 500


def _ahora_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def registrar_accion_admin(
    actor: str,
    accion: str,
    *,
    objetivo: str = "",
    detalle: str = "",
    ip: str = "",
) -> None:
    """Append-only (con tope) de acciones sensibles del panel admin."""
    entrada = {
        "ts": _ahora_iso(),
        "actor": (actor or "").strip()[:80],
        "accion": (accion or "").strip()[:80],
        "objetivo": (objetivo or "").strip()[:120],
        "detalle": (detalle or "").strip()[:240],
        "ip": (ip or "").strip()[:64],
    }
    if not entrada["accion"]:
        return
    try:
        from auth_registro import _read_store, _write_store

        with _lock:
            data = _read_store(_STORE, {"version": 1, "eventos": []})
            if not isinstance(data, dict):
                data = {"version": 1, "eventos": []}
            eventos = data.get("eventos")
            if not isinstance(eventos, list):
                eventos = []
            eventos.append(entrada)
            if len(eventos) > _MAX:
                eventos = eventos[-_MAX:]
            data["eventos"] = eventos
            data["version"] = 1
            _write_store(_STORE, data)
    except Exception:
        _LOG.exception("No se pudo registrar auditoría admin: %s", entrada.get("accion"))


def listar_acciones_admin(limite: int = 40) -> list[dict[str, Any]]:
    try:
        from auth_registro import _read_store

        data = _read_store(_STORE, {"version": 1, "eventos": []})
        eventos = data.get("eventos") if isinstance(data, dict) else []
        if not isinstance(eventos, list):
            return []
        n = max(1, min(int(limite), 200))
        return list(reversed(eventos[-n:]))
    except Exception:
        _LOG.debug("No se pudo leer auditoría admin", exc_info=True)
        return []
