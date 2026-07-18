"""Cifrado del almacenamiento local (portable y caché en disco).

Los blobs ``.enc`` usan Fernet (cifrado + integridad). Si alguien modifica
un byte, la descifrado falla y la app debe bloquearse (``AuthStoreCorruptError``).
"""

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


class AuthStoreCorruptError(RuntimeError):
    """Datos locales dañados o alterados manualmente."""


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
            data = descifrar_bytes(path.read_bytes())
            if data is None:
                raise AuthStoreCorruptError(
                    f"No se pudo verificar la integridad de {path.name}. "
                    "El archivo fue modificado o está dañado."
                )
            return data
        with open(path, encoding="utf-8-sig") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else None
    except AuthStoreCorruptError:
        raise
    except (OSError, json.JSONDecodeError):
        return None


def escribir_archivo_cifrado(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(cifrar_payload(data))
    tmp.replace(path)


def ruta_store_cifrado(ruta_json: Path) -> Path:
    """Par ``usuarios_registrados.json`` → ``usuarios_registrados.enc``."""
    return ruta_json.with_suffix(".enc")


def leer_store_secreto(
    ruta_enc: Path,
    ruta_json_legacy: Path | None,
    default: Any,
) -> Any:
    """Lee un store cifrado; migra JSON legacy una sola vez si hace falta."""
    if ruta_enc.is_file():
        data = descifrar_bytes(ruta_enc.read_bytes())
        if data is None:
            raise AuthStoreCorruptError(
                f"Datos locales alterados o corruptos ({ruta_enc.name}). "
                "Reinstalá el portable o contactá al administrador."
            )
        return data

    if ruta_json_legacy and ruta_json_legacy.is_file():
        try:
            legacy = json.loads(ruta_json_legacy.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise AuthStoreCorruptError(
                f"No se pudo leer {ruta_json_legacy.name}: {exc}"
            ) from exc
        escribir_archivo_cifrado(ruta_enc, legacy if isinstance(legacy, dict) else {"data": legacy})
        try:
            ruta_json_legacy.unlink()
        except OSError:
            pass
        return legacy

    return default


def escribir_store_secreto(ruta_enc: Path, data: Any) -> None:
    if not isinstance(data, dict):
        raise TypeError("store_secreto requiere un dict")
    escribir_archivo_cifrado(ruta_enc, data)
    legacy = ruta_enc.with_suffix(".json")
    if legacy.is_file() and legacy != ruta_enc:
        try:
            legacy.unlink()
        except OSError:
            pass


def verificar_integridad_archivo(ruta_enc: Path) -> bool:
    if not ruta_enc.is_file():
        return True
    try:
        return descifrar_bytes(ruta_enc.read_bytes()) is not None
    except OSError:
        return False
