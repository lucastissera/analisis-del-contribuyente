"""Cifrado del archivo local de usuarios (portable y caché en disco)."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

# Pepper embebido: impide lectura casual del .enc; no reemplaza HTTPS ni token remoto.
_PEPPER = b"DepuracionExcelComprobantes-auth-store-v1"
_MAGIC = b"AICENC1"


def _fernet() -> Fernet:
    override = (os.environ.get("AUTH_STORE_KEY") or "").strip()
    if override:
        return Fernet(override.encode("ascii"))
    digest = hashlib.sha256(_PEPPER).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def cifrar_payload(data: dict[str, Any]) -> bytes:
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return _MAGIC + _fernet().encrypt(raw)


def descifrar_bytes(blob: bytes) -> dict[str, Any] | None:
    if not blob:
        return None
    token = blob[len(_MAGIC) :] if blob.startswith(_MAGIC) else blob
    try:
        raw = _fernet().decrypt(token)
        data = json.loads(raw.decode("utf-8"))
        return data if isinstance(data, dict) else None
    except (InvalidToken, json.JSONDecodeError, UnicodeDecodeError, ValueError):
        return None


def es_archivo_cifrado(path: Path) -> bool:
    name = path.name.lower()
    return name.endswith(".enc") or name == "auth_users_cache.enc"


def leer_archivo_usuarios(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        if es_archivo_cifrado(path):
            return descifrar_bytes(path.read_bytes())
        with open(path, encoding="utf-8-sig") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def escribir_archivo_cifrado(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(cifrar_payload(data))
