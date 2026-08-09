"""Tokens de API por instalación/usuario (P1.8 / Fase 1).

El Bearer global (AUTH_USERS_REMOTE_TOKEN) solo sirve para bootstrap de login
(``/api/auth/verificar``). Cupo/uso exigen token ``dev_…`` ligado a usuario y
``device_id`` de instalación. El admin puede listar, renombrar y revocar.
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


def emitir_token_dispositivo(
    usuario: str,
    *,
    etiqueta: str = "portable",
    device_id: str = "",
    public_key: str = "",
) -> str:
    """Crea un token en claro (solo se muestra una vez) ligado a ``usuario``."""
    u = (usuario or "").strip()
    if not u:
        raise ValueError("usuario vacío")
    did = (device_id or "").strip()[:120]
    plain = _PREFIX + secrets.token_urlsafe(32)
    digest = _hash_token(plain)
    with _lock:
        data = _cargar()
        tokens: dict[str, Any] = data.setdefault("tokens", {})
        # Misma instalación: revocar tokens previos de ese device_id.
        if did:
            for h, meta in list(tokens.items()):
                if (
                    isinstance(meta, dict)
                    and (meta.get("usuario") or "") == u
                    and (meta.get("device_id") or "") == did
                    and not meta.get("revocado")
                ):
                    meta["revocado"] = True
                    meta["revocado_en"] = _ahora_iso()
                    meta["revocado_por"] = "reemplazo_mismo_device"
                    tokens[h] = meta
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
            meta_v = tokens.get(viejo)
            if isinstance(meta_v, dict):
                meta_v["revocado"] = True
                meta_v["revocado_en"] = _ahora_iso()
                meta_v["revocado_por"] = "limite_por_usuario"
                tokens[viejo] = meta_v
            else:
                tokens.pop(viejo, None)
        tokens[digest] = {
            "usuario": u,
            "creado": _ahora_iso(),
            "ultimo_uso": _ahora_iso(),
            "etiqueta": (etiqueta or "portable")[:80],
            "device_id": did,
            "public_key": (public_key or "").strip()[:200],
            "revocado": False,
            "build_id": "",
            "app_version": "",
            "root_hash": "",
            "integrity_ok": None,
            "integrity_detail": "",
            "integrity_at": "",
        }
        _guardar(data)
    _LOG.info("Token de dispositivo emitido para %s device_id=%s", u, did or "-")
    return plain


def registrar_integridad(
    *,
    token_hash: str = "",
    device_id: str = "",
    usuario: str = "",
    build_id: str = "",
    app_version: str = "",
    root_hash: str = "",
    integrity_ok: bool | None = None,
    detail: str = "",
) -> bool:
    """Actualiza telemetría de integridad en el token de dispositivo."""
    h = (token_hash or "").strip()
    did = (device_id or "").strip()
    u = (usuario or "").strip()
    with _lock:
        data = _cargar()
        tokens = data.get("tokens") or {}
        target_h = h
        if not target_h and (did or u):
            for digest, meta in tokens.items():
                if not isinstance(meta, dict) or meta.get("revocado"):
                    continue
                if did and (meta.get("device_id") or "") == did:
                    if u and (meta.get("usuario") or "") != u:
                        continue
                    target_h = digest
                    break
                if not did and u and (meta.get("usuario") or "") == u:
                    target_h = digest
        meta = tokens.get(target_h) if target_h else None
        if not isinstance(meta, dict):
            return False
        meta["build_id"] = (build_id or "")[:80]
        meta["app_version"] = (app_version or "")[:40]
        meta["root_hash"] = (root_hash or "")[:80]
        meta["integrity_ok"] = integrity_ok
        meta["integrity_detail"] = (detail or "")[:120]
        meta["integrity_at"] = _ahora_iso()
        meta["ultimo_uso"] = _ahora_iso()
        tokens[target_h] = meta
        data["tokens"] = tokens
        _guardar(data)
    return True


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


def resolver_device_meta(auth_header: str | None) -> dict[str, Any] | None:
    """Meta del device token si el Bearer es ``dev_…`` válido."""
    if not auth_header:
        return None
    header = auth_header.strip()
    if not header.lower().startswith("bearer "):
        return None
    return _buscar_device(header[7:].strip())


def cupo_exige_device_token() -> bool:
    """Cupo/uso siempre exigen device token (Fase 1.3).

    ``AUTH_CUPO_REQUIRE_DEVICE=0`` solo se respeta si se define explícitamente
    para emergencias de compatibilidad.
    """
    v = (os.environ.get("AUTH_CUPO_REQUIRE_DEVICE") or "1").strip().lower()
    if v in ("0", "false", "no", "off"):
        return False
    return True


def listar_dispositivos(*, incluir_revocados: bool = True) -> list[dict[str, Any]]:
    with _lock:
        data = _cargar()
        tokens = data.get("tokens") or {}
    filas: list[dict[str, Any]] = []
    for digest, meta in tokens.items():
        if not isinstance(meta, dict):
            continue
        if not incluir_revocados and meta.get("revocado"):
            continue
        filas.append(
            {
                "id": digest[:16],
                "token_hash": digest,
                "usuario": meta.get("usuario") or "",
                "etiqueta": meta.get("etiqueta") or "",
                "device_id": meta.get("device_id") or "",
                "creado": meta.get("creado") or "",
                "ultimo_uso": meta.get("ultimo_uso") or "",
                "revocado": bool(meta.get("revocado")),
                "revocado_en": meta.get("revocado_en") or "",
                "revocado_por": meta.get("revocado_por") or "",
                "tiene_public_key": bool((meta.get("public_key") or "").strip()),
                "build_id": meta.get("build_id") or "",
                "app_version": meta.get("app_version") or "",
                "root_hash": meta.get("root_hash") or "",
                "integrity_ok": meta.get("integrity_ok"),
                "integrity_detail": meta.get("integrity_detail") or "",
                "integrity_at": meta.get("integrity_at") or "",
            }
        )
    filas.sort(key=lambda r: str(r.get("ultimo_uso") or r.get("creado") or ""), reverse=True)
    return filas


def renombrar_dispositivo(token_hash: str, etiqueta: str) -> bool:
    h = (token_hash or "").strip()
    if not h:
        return False
    with _lock:
        data = _cargar()
        meta = data.get("tokens", {}).get(h)
        if not isinstance(meta, dict):
            return False
        meta["etiqueta"] = (etiqueta or "").strip()[:80] or meta.get("etiqueta") or "portable"
        data["tokens"][h] = meta
        _guardar(data)
    return True


def revocar_dispositivo(token_hash: str, *, por: str = "admin") -> bool:
    h = (token_hash or "").strip()
    if not h:
        return False
    with _lock:
        data = _cargar()
        meta = data.get("tokens", {}).get(h)
        if not isinstance(meta, dict):
            return False
        if meta.get("revocado"):
            return True
        meta["revocado"] = True
        meta["revocado_en"] = _ahora_iso()
        meta["revocado_por"] = (por or "admin")[:80]
        data["tokens"][h] = meta
        _guardar(data)
    _LOG.info("Device token revocado %s… por %s", h[:12], por)
    return True


def revocar_dispositivos_usuario(usuario: str, *, por: str = "admin") -> int:
    u = (usuario or "").strip()
    if not u:
        return 0
    n = 0
    with _lock:
        data = _cargar()
        for h, meta in list((data.get("tokens") or {}).items()):
            if not isinstance(meta, dict):
                continue
            if (meta.get("usuario") or "") != u or meta.get("revocado"):
                continue
            meta["revocado"] = True
            meta["revocado_en"] = _ahora_iso()
            meta["revocado_por"] = (por or "admin")[:80]
            data["tokens"][h] = meta
            n += 1
        if n:
            _guardar(data)
    return n
