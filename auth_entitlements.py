"""Entitlements firmados Ed25519 (P2.12) para portable con sync.

El servidor firma un JSON de vida corta (vigencia/cupo/servicios). El portable
verifica con la clave pública embebida. Sin red, si el entitlement es válido
se usa como tope de cupo/vigencia; el consumo sigue yendo al servidor cuando hay red.

Clave privada solo en el servidor:

  AUTH_ENTITLEMENT_PRIVATE_KEY=<32 bytes urlsafe-base64>

Generar par: ``python tools/generar_entitlement_keys.py``
"""

from __future__ import annotations

import base64
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

_LOG = logging.getLogger(__name__)
_lock = threading.Lock()

# Clave pública Ed25519 (32 bytes, urlsafe-base64). Debe coincidir con la privada de Render.
# Regenerar con tools/generar_entitlement_keys.py si rotás el par.
_PUBLIC_KEY_B64 = "nrT2mKEAKRizxMdi1eHfQAqkAtbcg1ropzRLpR9TY0Y"

_TTL_DEFAULT = 48 * 3600  # 48 h


def _b64_decode(raw: str) -> bytes:
    s = (raw or "").strip()
    pad = "=" * ((4 - len(s) % 4) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _b64_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _ttl_sec() -> int:
    raw = (os.environ.get("AUTH_ENTITLEMENT_TTL_SEC") or "").strip()
    try:
        return max(300, min(int(raw), 30 * 24 * 3600))
    except ValueError:
        return _TTL_DEFAULT


def _public_key_bytes() -> bytes:
    env = (os.environ.get("AUTH_ENTITLEMENT_PUBLIC_KEY") or "").strip()
    return _b64_decode(env or _PUBLIC_KEY_B64)


def _private_key_bytes() -> bytes | None:
    raw = (os.environ.get("AUTH_ENTITLEMENT_PRIVATE_KEY") or "").strip()
    if not raw:
        # Dev local: archivo gitignored junto al repo
        path = Path(__file__).resolve().parent / ".entitlement_private.key"
        if path.is_file():
            raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return None
    try:
        return _b64_decode(raw)
    except Exception:
        _LOG.warning("AUTH_ENTITLEMENT_PRIVATE_KEY inválida")
        return None


def _canonical(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )


def firmar_entitlement(claims: dict[str, Any]) -> dict[str, Any] | None:
    """Firma claims y devuelve {entitlement, signature} o None si no hay clave privada."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    seed = _private_key_bytes()
    if not seed or len(seed) != 32:
        return None
    ahora = int(time.time())
    body = dict(claims)
    body["iat"] = ahora
    body["exp"] = ahora + _ttl_sec()
    body["v"] = 1
    msg = _canonical(body)
    try:
        priv = Ed25519PrivateKey.from_private_bytes(seed)
        sig = priv.sign(msg)
    except Exception:
        _LOG.exception("No se pudo firmar entitlement")
        return None
    return {"entitlement": body, "signature": _b64_encode(sig)}


def verificar_entitlement_firmado(blob: dict[str, Any] | None) -> dict[str, Any] | None:
    """Valida firma + exp. Devuelve el dict entitlement o None."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    if not isinstance(blob, dict):
        return None
    ent = blob.get("entitlement")
    sig_b64 = blob.get("signature")
    if not isinstance(ent, dict) or not sig_b64:
        return None
    try:
        exp = int(ent.get("exp") or 0)
    except (TypeError, ValueError):
        return None
    if exp < int(time.time()):
        return None
    try:
        pub = Ed25519PublicKey.from_public_bytes(_public_key_bytes())
        pub.verify(_b64_decode(str(sig_b64)), _canonical(ent))
    except (InvalidSignature, ValueError, TypeError):
        return None
    except Exception:
        _LOG.debug("Verificación entitlement falló", exc_info=True)
        return None
    return ent


def emitir_entitlement_usuario(
    usuario: str, *, device_id: str = ""
) -> dict[str, Any] | None:
    """Arma y firma entitlement desde overlay/cupo del servidor."""
    u = (usuario or "").strip()
    if not u:
        return None
    try:
        from auth import es_administrador
        from auth_registro import info_cupo_cuit, info_suscripcion_usuario, servicios_usuario
    except Exception:
        return None

    claims: dict[str, Any] = {
        "usuario": u,
        "es_admin": bool(es_administrador(u)),
        "sub": u,
    }
    did = (device_id or "").strip()
    if did:
        claims["device_id"] = did
    try:
        claims["servicios"] = servicios_usuario(u) or {}
    except Exception:
        claims["servicios"] = {}
    sus = None
    try:
        sus = info_suscripcion_usuario(u)
    except Exception:
        sus = None
    if isinstance(sus, dict):
        vh = sus.get("valido_hasta")
        if hasattr(vh, "isoformat"):
            claims["valido_hasta"] = vh.isoformat()
        else:
            claims["valido_hasta"] = sus.get("valido_hasta_fmt") or vh
        claims["dias_restantes"] = sus.get("dias_restantes")
    cupo = None
    try:
        cupo = info_cupo_cuit(u)
    except Exception:
        cupo = None
    if cupo is None and claims["es_admin"]:
        claims["cuit_ilimitado"] = True
        claims["cuit_disponibles"] = 1_000_000_000
    elif isinstance(cupo, dict):
        claims["cuit_limite"] = cupo.get("cuit_limite")
        claims["cuit_usados"] = cupo.get("cuit_usados")
        claims["cuit_disponibles"] = cupo.get("cuit_disponibles")
        claims["cuit_ilimitado"] = bool(cupo.get("cuit_ilimitado"))
    return firmar_entitlement(claims)


def _ruta_cache_entitlements() -> Path:
    try:
        from auth import _dir_datos_usuario

        base = _dir_datos_usuario() / "auth"
    except Exception:
        base = Path(__file__).resolve().parent / "data_local_auth" / "auth"
    base.mkdir(parents=True, exist_ok=True)
    return base / "entitlements_cache.enc"


def guardar_entitlement_local(usuario: str, blob: dict[str, Any]) -> None:
    u = (usuario or "").strip()
    if not u or not isinstance(blob, dict):
        return
    if verificar_entitlement_firmado(blob) is None:
        return
    path = _ruta_cache_entitlements()
    with _lock:
        data: dict[str, Any] = {"version": 1, "users": {}}
        try:
            from auth_crypto import leer_archivo_usuarios

            if path.is_file():
                prev = leer_archivo_usuarios(path)
                if isinstance(prev, dict) and isinstance(prev.get("users"), dict):
                    data["users"] = dict(prev["users"])
        except Exception:
            data = {"version": 1, "users": {}}
        data["users"][u] = blob
        try:
            from auth_crypto import escribir_archivo_cifrado

            escribir_archivo_cifrado(path, data)
        except Exception:
            _LOG.debug("No se pudo guardar entitlement local", exc_info=True)


def cargar_entitlement_local(usuario: str) -> dict[str, Any] | None:
    u = (usuario or "").strip()
    if not u:
        return None
    path = _ruta_cache_entitlements()
    if not path.is_file():
        return None
    try:
        from auth_crypto import leer_archivo_usuarios

        data = leer_archivo_usuarios(path)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    users = data.get("users")
    if not isinstance(users, dict):
        return None
    blob = users.get(u)
    return verificar_entitlement_firmado(blob if isinstance(blob, dict) else None)


def cupo_desde_entitlement(usuario: str) -> int | None:
    """CUIT disponibles según entitlement local válido, o None si no hay."""
    ent = cargar_entitlement_local(usuario)
    if not ent:
        return None
    if ent.get("cuit_ilimitado") or ent.get("es_admin"):
        return 1_000_000_000
    try:
        return max(0, int(ent.get("cuit_disponibles") or 0))
    except (TypeError, ValueError):
        return 0


def entitlement_vigente_para_login(usuario: str) -> bool:
    """True si hay entitlement firmado no vencido (offline con sync)."""
    ent = cargar_entitlement_local(usuario)
    if not ent:
        return False
    claim_did = (ent.get("device_id") or "").strip()
    if claim_did:
        try:
            from auth_instalacion import identidad_instalacion

            local_did = (identidad_instalacion().get("device_id") or "").strip()
            if local_did and local_did != claim_did:
                return False
        except Exception:
            return False
    if ent.get("es_admin"):
        return True
    if ent.get("activo") is False:
        return False
    return True
