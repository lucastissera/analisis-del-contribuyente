"""Tokens de API por instalación/usuario (P1.8).

El Bearer global (AUTH_USERS_REMOTE_TOKEN) sigue sirviendo para sync y login
bootstrap. Tras un login OK el servidor emite un token ``dev_…`` ligado a un
usuario; las APIs de cupo/uso pueden exigir esa identidad y no la del body.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import threading
from datetime import datetime, timezone
from typing import Any, Literal

_LOG = logging.getLogger(__name__)
_lock = threading.RLock()

_STORE = "dispositivos_api"
_MAX_TOKENS_POR_USUARIO = 8
_PREFIX = "dev_"

AuthTipo = Literal["global", "device"]


def _ahora_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _hash_token(token: str) -> str:
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def _cargar() -> dict[str, Any]:
    from auth_registro import _read_store

    data = _read_store(_STORE, {"version": 1, "tokens": {}})
    if not isinstance(data, dict):
        return {"version": 1, "tokens": {}}
    tokens = data.get("tokens")
    if not isinstance(tokens, dict):
        data["tokens"] = {}
    return data


def _guardar(data: dict[str, Any]) -> None:
    from auth_registro import _write_store

    _write_store(_STORE, data)


def emitir_token_dispositivo(usuario: str, *, etiqueta: str = "portable") -> str:
    """Crea un token en claro (solo se muestra una vez) ligado a ``usuario``."""
    u = (usuario or "").strip()
    if not u:
        raise ValueError("usuario vacío")
    plain = _PREFIX + secrets.token_urlsafe(32)
    digest = _hash_token(plain)
    with _lock:
        data = _cargar()
        tokens: dict[str, Any] = data.setdefault("tokens", {})
        del_usuario = [
            h
            for h, meta in tokens.items()
            if isinstance(meta, dict)
            and (meta.get("usuario") or "") == u
            and not meta.get("revocado")
        ]
        del_usuario.sort(
            key=lambda h: str((tokens.get(h) or {}).get("creado") or ""),
        )
        while len(del_usuario) >= _MAX_TOKENS_POR_USUARIO:
            viejo = del_usuario.pop(0)
            tokens.pop(viejo, None)
        tokens[digest] = {
            "usuario": u,
            "creado": _ahora_iso(),
            "ultimo_uso": _ahora_iso(),
            "etiqueta": (etiqueta or "portable")[:80],
            "revocado": False,
        }
        _guardar(data)
    _LOG.info("Token de dispositivo emitido para %s", u)
    return plain


def _buscar_device(token: str) -> dict[str, Any] | None:
    if not (token or "").startswith(_PREFIX):
        return None
    digest = _hash_token(token)
    with _lock:
        data = _cargar()
        meta = data.get("tokens", {}).get(digest)
        if not isinstance(meta, dict) or meta.get("revocado"):
            return None
        meta["ultimo_uso"] = _ahora_iso()
        data["tokens"][digest] = meta
        try:
            _guardar(data)
        except Exception:
            _LOG.debug("No se pudo actualizar ultimo_uso del device token", exc_info=True)
        return dict(meta)


def resolver_autorizacion_api(auth_header: str | None) -> tuple[AuthTipo, str | None] | None:
    """Devuelve (tipo, usuario|None) o None si no autorizado.

    - global: Bearer = AUTH_USERS_REMOTE_TOKEN (usuario no ligado)
    - device: Bearer = dev_… ligado a un usuario
    """
    if not auth_header:
        return None
    header = auth_header.strip()
    if not header.lower().startswith("bearer "):
        return None
    presented = header[7:].strip()
    if not presented:
        return None

    # Device primero (prefijo distinto del token global típico).
    meta = _buscar_device(presented)
    if meta is not None:
        return "device", str(meta.get("usuario") or "").strip() or None

    try:
        from auth import _remote_tokens
    except Exception:
        return None
    for expected in _remote_tokens():
        if expected and hmac.compare_digest(presented, expected):
            return "global", None
    return None


def cupo_exige_device_token() -> bool:
    v = (os.environ.get("AUTH_CUPO_REQUIRE_DEVICE") or "").strip().lower()
    return v in ("1", "true", "yes", "on", "si", "sí")
