"""Manifiesto firmado del portable (Fase 2.1).

El build genera ``manifest.signed.json`` (hashes + firma Ed25519).
El portable verifica al inicio y reporta ``integrity_ok`` / ``build_id`` al servidor.

La clave privada es la misma que entitlements (solo servidor / máquina de build).
La pública ya viaja en el cliente (``auth_entitlements``).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_LOG = logging.getLogger(__name__)

_MANIFEST_NAME = "manifest.signed.json"
_EXCLUDE_DIR_NAMES = frozenset(
    {
        "ms-playwright",
        "__pycache__",
        ".git",
        "logs",
    }
)
_EXCLUDE_SUFFIXES = frozenset({".log", ".tmp", ".pyc"})

# Estado en memoria tras verificar_al_inicio()
_ultimo: dict[str, Any] | None = None


def _b64_encode(data: bytes) -> str:
    import base64

    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64_decode(raw: str) -> bytes:
    import base64

    s = (raw or "").strip()
    pad = "=" * ((4 - len(s) % 4) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _canonical(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _debe_excluir(rel: Path) -> bool:
    parts = set(rel.parts)
    if parts & _EXCLUDE_DIR_NAMES:
        return True
    if rel.suffix.lower() in _EXCLUDE_SUFFIXES:
        return True
    if rel.name == _MANIFEST_NAME:
        return True
    return False


def directorio_portable() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def recolectar_hashes(base: Path) -> dict[str, str]:
    """sha256 relativos a ``base`` (posix)."""
    base = base.resolve()
    out: dict[str, str] = {}
    for path in sorted(base.rglob("*")):
        if not path.is_file():
            continue
        try:
            rel = path.relative_to(base)
        except ValueError:
            continue
        if _debe_excluir(rel):
            continue
        try:
            out[rel.as_posix()] = _sha256_file(path)
        except OSError as exc:
            _LOG.warning("No se pudo hashear %s: %s", rel, exc)
    return out


def root_hash_de(files: dict[str, str]) -> str:
    material = _canonical({"files": files})
    return hashlib.sha256(material).hexdigest()


def generar_manifest(
    base: Path,
    *,
    build_id: str = "",
    app_version: str = "",
) -> dict[str, Any]:
    from app_branding import APP_EXE_BASENAME, APP_NAME, APP_VERSION

    files = recolectar_hashes(base)
    rh = root_hash_de(files)
    bid = (build_id or "").strip() or (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + "-"
        + rh[:8]
    )
    body = {
        "v": 1,
        "kind": "portable_manifest",
        "app_name": APP_NAME,
        "exe": f"{APP_EXE_BASENAME}.exe",
        "app_version": (app_version or APP_VERSION).strip(),
        "build_id": bid,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "file_count": len(files),
        "root_hash": rh,
        "files": files,
    }
    return body


def firmar_manifest(body: dict[str, Any]) -> dict[str, Any] | None:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from auth_entitlements import _private_key_bytes

    seed = _private_key_bytes()
    if not seed or len(seed) != 32:
        return None
    msg = _canonical(body)
    try:
        priv = Ed25519PrivateKey.from_private_bytes(seed)
        sig = priv.sign(msg)
    except Exception:
        _LOG.exception("No se pudo firmar manifiesto")
        return None
    return {"manifest": body, "signature": _b64_encode(sig)}


def verificar_blob_firmado(blob: dict[str, Any] | None) -> dict[str, Any] | None:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    from auth_entitlements import _public_key_bytes

    if not isinstance(blob, dict):
        return None
    body = blob.get("manifest")
    sig_b64 = blob.get("signature")
    if not isinstance(body, dict) or not sig_b64:
        return None
    if body.get("kind") != "portable_manifest":
        return None
    try:
        pub = Ed25519PublicKey.from_public_bytes(_public_key_bytes())
        pub.verify(_b64_decode(str(sig_b64)), _canonical(body))
    except (InvalidSignature, ValueError, TypeError):
        return None
    except Exception:
        _LOG.debug("Verificación de manifiesto falló", exc_info=True)
        return None
    return body


def verificar_contra_disco(base: Path, body: dict[str, Any]) -> tuple[bool, str]:
    """Compara hashes del manifiesto con archivos actuales."""
    files = body.get("files")
    if not isinstance(files, dict) or not files:
        return False, "manifest_sin_files"
    expected_root = (body.get("root_hash") or "").strip()
    if expected_root and expected_root != root_hash_de({k: str(v) for k, v in files.items()}):
        return False, "root_hash_inconsistente"
    base = base.resolve()
    for rel, expect in files.items():
        path = base / str(rel)
        if not path.is_file():
            return False, f"faltante:{rel}"
        try:
            got = _sha256_file(path)
        except OSError:
            return False, f"lectura:{rel}"
        if got != str(expect):
            return False, f"alterado:{rel}"
    return True, "ok"


def cargar_manifest_firmado(base: Path | None = None) -> dict[str, Any] | None:
    root = base or directorio_portable()
    path = root / _MANIFEST_NAME
    if not path.is_file():
        return None
    try:
        blob = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return blob if isinstance(blob, dict) else None


def verificar_al_inicio(base: Path | None = None) -> dict[str, Any]:
    """Verifica manifiesto del portable. En modo no-frozen (dev) no es bloqueante."""
    global _ultimo
    root = base or directorio_portable()
    frozen = bool(getattr(sys, "frozen", False))
    strict = (os.environ.get("AUTH_MANIFEST_STRICT") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    resultado: dict[str, Any] = {
        "checked_at": int(time.time()),
        "frozen": frozen,
        "integrity_ok": None,
        "build_id": "",
        "app_version": "",
        "root_hash": "",
        "detail": "no_manifest",
        "strict": strict,
    }
    blob = cargar_manifest_firmado(root)
    if blob is None:
        if frozen:
            resultado["integrity_ok"] = False
            resultado["detail"] = "manifest_ausente"
        _ultimo = resultado
        return resultado
    body = verificar_blob_firmado(blob)
    if body is None:
        resultado["integrity_ok"] = False
        resultado["detail"] = "firma_invalida"
        _ultimo = resultado
        return resultado
    resultado["build_id"] = str(body.get("build_id") or "")
    resultado["app_version"] = str(body.get("app_version") or "")
    resultado["root_hash"] = str(body.get("root_hash") or "")
    ok, detail = verificar_contra_disco(root, body)
    resultado["integrity_ok"] = bool(ok)
    resultado["detail"] = detail
    _ultimo = resultado
    if not ok:
        _LOG.warning("Integridad portable: %s (build_id=%s)", detail, resultado["build_id"])
    return resultado


def estado_integridad() -> dict[str, Any]:
    """Último resultado (o verificación perezosa)."""
    global _ultimo
    if _ultimo is None:
        return verificar_al_inicio()
    return dict(_ultimo)


def payload_telemetria() -> dict[str, Any]:
    st = estado_integridad()
    return {
        "build_id": st.get("build_id") or "",
        "app_version": st.get("app_version") or "",
        "root_hash": st.get("root_hash") or "",
        "integrity_ok": st.get("integrity_ok"),
        "detail": st.get("detail") or "",
    }


def escribir_manifest_firmado(base: Path, blob: dict[str, Any]) -> Path:
    path = base / _MANIFEST_NAME
    path.write_text(json.dumps(blob, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
