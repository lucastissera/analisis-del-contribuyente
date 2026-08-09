"""Identidad local de instalación del portable (P1.5).

Genera y persiste un ``device_id`` estable por PC/carpeta de datos.
Opcionalmente un par Ed25519: la clave privada no sale del equipo;
la pública se registra en el servidor al login.
"""

from __future__ import annotations

import logging
import secrets
import threading
from pathlib import Path
from typing import Any

_LOG = logging.getLogger(__name__)
_lock = threading.Lock()
_cache: dict[str, Any] | None = None


def _ruta() -> Path:
    try:
        from auth import _dir_datos_usuario

        base = _dir_datos_usuario() / "auth"
    except Exception:
        base = Path(__file__).resolve().parent / "data_local_auth" / "auth"
    base.mkdir(parents=True, exist_ok=True)
    return base / "instalacion.enc"


def _cargar() -> dict[str, Any]:
    global _cache
    with _lock:
        if _cache is not None:
            return dict(_cache)
        path = _ruta()
        data: dict[str, Any] = {"version": 1}
        try:
            from auth_crypto import leer_archivo_usuarios

            if path.is_file():
                loaded = leer_archivo_usuarios(path)
                if isinstance(loaded, dict):
                    data = loaded
        except Exception:
            _LOG.debug("No se pudo leer instalacion.enc", exc_info=True)
        _cache = data
        return dict(data)


def _guardar(data: dict[str, Any]) -> None:
    global _cache
    path = _ruta()
    with _lock:
        try:
            from auth_crypto import escribir_archivo_cifrado

            escribir_archivo_cifrado(path, data)
            _cache = dict(data)
        except Exception:
            _LOG.exception("No se pudo guardar instalacion.enc")


def _asegurar_par_ed25519(data: dict[str, Any]) -> dict[str, Any]:
    if (data.get("public_key") or "").strip() and (data.get("private_key") or "").strip():
        return data
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        import base64

        priv = Ed25519PrivateKey.generate()
        priv_b = priv.private_bytes_raw()
        pub_b = priv.public_key().public_bytes_raw()
        data["private_key"] = base64.urlsafe_b64encode(priv_b).decode("ascii").rstrip("=")
        data["public_key"] = base64.urlsafe_b64encode(pub_b).decode("ascii").rstrip("=")
    except Exception:
        _LOG.debug("No se pudo generar par Ed25519 de instalación", exc_info=True)
    return data


def identidad_instalacion() -> dict[str, str]:
    """Devuelve device_id y public_key (crea si faltan)."""
    data = _cargar()
    changed = False
    device_id = (data.get("device_id") or "").strip()
    if not device_id:
        data["device_id"] = "inst_" + secrets.token_urlsafe(24)
        changed = True
    before_pub = (data.get("public_key") or "").strip()
    data = _asegurar_par_ed25519(data)
    if (data.get("public_key") or "").strip() != before_pub:
        changed = True
    if changed:
        _guardar(data)
    return {
        "device_id": str(data.get("device_id") or "").strip(),
        "public_key": str(data.get("public_key") or "").strip(),
    }


def etiqueta_instalacion() -> str:
    """Nombre corto visible en el panel admin (hostname truncado)."""
    try:
        import socket

        host = (socket.gethostname() or "").strip() or "portable"
    except Exception:
        host = "portable"
    return host[:80]
