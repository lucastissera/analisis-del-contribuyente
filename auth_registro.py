"""Alta de usuarios por enlace: CUIT como usuario, contraseña elegida por el cliente."""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
import smtplib
import ssl
import sys
import tempfile
import threading
from datetime import date, datetime, timedelta, timezone
from email.header import Header
from email.message import EmailMessage
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

import bcrypt

from app_branding import APP_NAME

_LOG = logging.getLogger(__name__)
_lock = threading.Lock()

_CUIT_RE = re.compile(r"^\d{11}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_USUARIO_ADMIN_RE = re.compile(r"^[A-Za-z0-9]{3,40}$")


def dir_auth_servidor() -> Path:
    override = (os.environ.get("AUTH_REGISTRATIONS_DIR") or "").strip()
    if override:
        p = Path(override)
    elif (os.environ.get("AUTH_DATA_DIR") or "").strip():
        p = Path(os.environ["AUTH_DATA_DIR"].strip()) / "auth"
    elif getattr(sys, "frozen", False):
        from auth import _dir_datos_usuario

        p = _dir_datos_usuario()
    else:
        p = Path(tempfile.gettempdir()) / "aic_auth_data"
    return p


def _path_solicitudes() -> Path:
    return dir_auth_servidor() / "solicitudes_pendientes.json"


def _path_usuarios_overlay() -> Path:
    return dir_auth_servidor() / "usuarios_registrados.json"


def _path_log_altas() -> Path:
    return dir_auth_servidor() / "altas_completadas.json"


_STORE_FILES: dict[str, str] = {
    "usuarios_registrados": "usuarios_registrados.json",
    "solicitudes_pendientes": "solicitudes_pendientes.json",
    "altas_completadas": "altas_completadas.json",
}

_integridad_store_ok: bool | None = None
_integridad_store_motivo: str = ""
_ultimo_error_cupo: str = ""


def ultimo_error_cupo() -> str:
    return _ultimo_error_cupo


def _set_error_cupo(msg: str) -> None:
    global _ultimo_error_cupo
    _ultimo_error_cupo = (msg or "").strip()


def _portable_store_cifrado() -> bool:
    """Portable sin PostgreSQL local: stores en ``.enc`` (integridad + ofuscación)."""
    if (os.environ.get("AUTH_STORE_ENCRYPT") or "").strip().lower() in (
        "1",
        "true",
        "si",
        "sí",
        "yes",
    ):
        return True
    if not getattr(sys, "frozen", False):
        return False
    try:
        from auth_registro_db import enabled

        return not enabled()
    except Exception:
        return True


def motivo_integridad_store() -> str:
    return _integridad_store_motivo


def integridad_store_local_ok() -> bool:
    global _integridad_store_ok
    if _integridad_store_ok is None:
        _integridad_store_ok = verificar_integridad_stores_locales()
    return bool(_integridad_store_ok)


def _marcar_integridad_fallida(motivo: str) -> None:
    global _integridad_store_ok, _integridad_store_motivo
    _integridad_store_ok = False
    _integridad_store_motivo = (motivo or "").strip()


def verificar_integridad_stores_locales() -> bool:
    """True si los ``.enc`` locales existentes son íntegros (portable)."""
    if not _portable_store_cifrado():
        return True
    from auth_crypto import AuthStoreCorruptError, ruta_store_cifrado, verificar_integridad_archivo

    for name in _STORE_FILES:
        json_path = _disk_path(name)
        enc_path = ruta_store_cifrado(json_path)
        if enc_path.is_file() and not verificar_integridad_archivo(enc_path):
            _marcar_integridad_fallida(
                f"Archivo local alterado o dañado: {enc_path.name}. "
                "El sistema no puede continuar."
            )
            return False
    return True


def _disk_path(name: str) -> Path:
    filename = _STORE_FILES.get(name)
    if not filename:
        raise ValueError(f"store desconocido: {name}")
    base = dir_auth_servidor()
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        _LOG.warning("No se pudo crear directorio auth %s: %s", base, exc)
    return base / filename


def _resolve_store_path(name: str, path: Path | None) -> Path:
    return path if path is not None else _disk_path(name)


def _token_horas() -> int:
    raw = (os.environ.get("AUTH_ALTA_TOKEN_HORAS") or "72").strip()
    try:
        return max(1, min(int(raw), 168))
    except ValueError:
        return 72


def _min_password_len() -> int:
    raw = (os.environ.get("AUTH_MIN_PASSWORD_LEN") or "8").strip()
    try:
        return max(6, min(int(raw), 128))
    except ValueError:
        return 8


def _dias_suscripcion() -> int:
    raw = (os.environ.get("AUTH_SUBSCRIPTION_DAYS") or "30").strip()
    try:
        return max(1, min(int(raw), 3660))
    except ValueError:
        return 30


def _cuit_limite_default() -> int:
    raw = (os.environ.get("AUTH_CUIT_LIMITE") or "100").strip()
    try:
        return max(0, min(int(raw), 1_000_000))
    except ValueError:
        return 100


def _leer_cupo_meta(meta: dict[str, Any]) -> tuple[int, int]:
    raw_limite = meta.get("cuit_limite")
    if raw_limite is None:
        limite = _cuit_limite_default()
    else:
        try:
            limite = max(0, min(int(raw_limite), 1_000_000))
        except (TypeError, ValueError):
            limite = _cuit_limite_default()
    try:
        usados = max(0, min(int(meta.get("cuit_usados") or 0), 1_000_000))
    except (TypeError, ValueError):
        usados = 0
    return limite, usados


def _inicializar_cupo_meta(meta: dict[str, Any]) -> None:
    if meta.get("cuit_limite") is None:
        meta["cuit_limite"] = _cuit_limite_default()
    if meta.get("cuit_usados") is None:
        meta["cuit_usados"] = 0


def _reset_cupo_meta(meta: dict[str, Any]) -> None:
    _inicializar_cupo_meta(meta)
    meta["cuit_usados"] = 0
    from auth_uso_valor import reset_uso_periodo_meta

    reset_uso_periodo_meta(meta)


SERVICIOS_IDS: tuple[str, ...] = (
    "procesador",
    "dfe",
    "vl",
    "np",
    "facturador",
    "ap",
    "inv",
)

_SERVICIOS_DEFAULT: dict[str, bool] = {
    "procesador": True,
    "dfe": True,
    "vl": True,
    "np": True,
    "facturador": False,
    "ap": False,
    "inv": False,
}


def servicios_default() -> dict[str, bool]:
    return dict(_SERVICIOS_DEFAULT)


def _normalizar_servicios_meta(raw: Any) -> dict[str, bool]:
    out = servicios_default()
    if isinstance(raw, dict):
        for clave in SERVICIOS_IDS:
            if clave in raw:
                out[clave] = bool(raw[clave])
    return out


def _inicializar_servicios_meta(meta: dict[str, Any]) -> None:
    meta["servicios"] = _normalizar_servicios_meta(meta.get("servicios"))


def servicios_usuario(username: str) -> dict[str, bool]:
    from auth import es_administrador

    if es_administrador(username):
        return {k: True for k in SERVICIOS_IDS}
    u = resolver_clave_usuario_overlay(username) or normalizar_cuit(username)
    if not u:
        return servicios_default()
    meta = cargar_usuarios_overlay().get(u)
    if not isinstance(meta, dict) or meta_es_admin(meta):
        return {k: True for k in SERVICIOS_IDS}
    return _normalizar_servicios_meta(meta.get("servicios"))


def usuario_tiene_servicio(username: str, clave: str) -> bool:
    if clave not in SERVICIOS_IDS:
        return False
    return bool(servicios_usuario(username).get(clave))


def actualizar_servicios_usuario(cuit: str, servicios: dict[str, bool]) -> bool:
    u = resolver_clave_overlay(cuit)
    if not u:
        return False
    with _lock:
        overlay = _cargar_overlay_completo()
        users = overlay.get("users")
        if not isinstance(users, dict) or u not in users:
            return False
        meta = users[u]
        if meta.get("pendiente_aprobacion"):
            return False
        meta["servicios"] = _normalizar_servicios_meta(servicios)
        _guardar_overlay_completo(overlay)
    return True

    """Cupo compartido entre servicios. Admin / sin overlay = ilimitado (None)."""
    from auth import es_administrador

    u_raw = (username or "").strip()
    if not u_raw or es_administrador(u_raw):
        return None
    u = resolver_clave_usuario_overlay(u_raw)
    if not u:
        return None
    meta = cargar_usuarios_overlay().get(u)
    if not isinstance(meta, dict) or meta_es_admin(meta):
        return None
    if meta.get("pendiente_aprobacion"):
        return None
    limite, usados = _leer_cupo_meta(meta)
    disponibles = max(0, limite - usados)
    return {
        "cuit_limite": limite,
        "cuit_usados": usados,
        "cuit_disponibles": disponibles,
        "cuit_ilimitado": False,
    }


def cupo_cuit_disponible(username: str) -> int:
    u_raw = (username or "").strip()
    if not u_raw:
        return 0
    u = resolver_clave_usuario_overlay(u_raw) or u_raw
    try:
        from auth_registro_db import enabled

        db = enabled()
    except Exception:
        db = False
    if not db:
        try:
            from auth import _modo_remoto_activo

            if _modo_remoto_activo():
                remoto = info_cupo_cuit_remoto(u)
                if remoto is not None:
                    return int(remoto.get("cuit_disponibles", 0))
        except Exception as exc:
            _LOG.debug("Cupo remoto no disponible para %s: %s", u, exc)
    info = info_cupo_cuit(u)
    if info is None:
        return 1_000_000_000
    return int(info["cuit_disponibles"])


def refrescar_cupo_usuario_remoto(username: str) -> dict[str, Any] | None:
    """Portable: consulta cupo en el servidor y actualiza caché local."""
    u = resolver_clave_usuario_overlay((username or "").strip())
    if not u:
        return None
    try:
        from auth import _modo_remoto_activo

        if _modo_remoto_activo():
            remoto = info_cupo_cuit_remoto(u)
            if remoto is not None:
                return remoto
    except Exception:
        pass
    return info_cupo_cuit(u)


def consumir_cuit_exitoso(username: str, cantidad: int = 1) -> bool:
    from auth import es_administrador

    _set_error_cupo("")
    if cantidad < 1:
        return True
    u_raw = (username or "").strip()
    if not u_raw or es_administrador(u_raw):
        return True
    u = resolver_clave_usuario_overlay(u_raw) or u_raw

    try:
        from auth_registro_db import enabled
    except Exception:
        enabled = lambda: False  # type: ignore[misc, assignment]

    if enabled():
        return _consumir_cuit_overlay_local(u, cantidad)

    try:
        from auth import _modo_remoto_activo

        remoto = _modo_remoto_activo()
    except Exception:
        remoto = False

    if remoto:
        ok = _consumir_cuit_remoto(u, cantidad)
        if not ok and not _ultimo_error_cupo:
            _set_error_cupo(
                "No se pudo registrar el cupo en el servidor. "
                "Revise auth_remote.txt (URL + token) y la conexión a Internet."
            )
        return ok

    ok = _consumir_cuit_overlay_local(u, cantidad)
    if not ok:
        _set_error_cupo(
            f"No se encontró el usuario {u!r} en datos locales de cupo. "
            "Configure auth_remote.txt junto al .exe para sincronizar con el servidor."
        )
    return ok


def _consumir_cuit_overlay_local(username: str, cantidad: int = 1) -> bool:
    """Incrementa ``cuit_usados`` en usuarios_registrados (PostgreSQL o JSON local)."""
    from auth import es_administrador

    u_raw = (username or "").strip()
    if not u_raw or es_administrador(u_raw):
        return True
    u = resolver_clave_usuario_overlay(u_raw)
    if not u:
        _LOG.warning(
            "Cupo no actualizado: no se encontró %r en usuarios_registrados.",
            u_raw,
        )
        return False
    with _lock:
        overlay = _cargar_overlay_completo()
        users = overlay.get("users")
        if not isinstance(users, dict) or u not in users:
            _LOG.warning(
                "Cupo no actualizado: clave overlay %r (desde %r) ausente en el store.",
                u,
                u_raw,
            )
            return False
        meta = users[u]
        if not isinstance(meta, dict) or meta_es_admin(meta):
            return True
        limite, usados = _leer_cupo_meta(meta)
        if usados + cantidad > limite:
            return False
        meta["cuit_usados"] = usados + cantidad
        meta["cuit_limite"] = limite
        from auth_uso_valor import registrar_uso_cuit_mes_en_meta

        registrar_uso_cuit_mes_en_meta(meta, cantidad)
        _guardar_overlay_completo(overlay)
    _LOG.info(
        "Cupo CUIT actualizado: %s → %d/%d usados.",
        u,
        usados + cantidad,
        limite,
    )
    return True


def _base_api_remota() -> str:
    try:
        from auth import _remote_url

        raw = (_remote_url() or "").strip().rstrip("/")
    except Exception:
        return ""
    if not raw:
        return ""
    if raw.endswith("/api/auth-users"):
        return raw[: -len("/api/auth-users")]
    if "/api/" in raw:
        return raw.rsplit("/api/", 1)[0]
    return raw


def _url_api_cupo_remota() -> str:
    base = _base_api_remota()
    return f"{base}/api/cupo/consumir" if base else ""


def _url_api_cupo_info_remota() -> str:
    base = _base_api_remota()
    return f"{base}/api/cupo/info" if base else ""


def info_cupo_cuit_remoto(username: str) -> dict[str, Any] | None:
    """Consulta cupo autoritativo en Render/Neon (portables con token)."""
    import json
    from urllib.error import HTTPError, URLError
    from urllib.parse import quote
    from urllib.request import Request, urlopen

    try:
        from auth import _remote_token
    except Exception:
        return None

    url_base = _url_api_cupo_info_remota()
    token = (_remote_token() or "").strip()
    u_raw = (username or "").strip()
    u = resolver_clave_usuario_overlay(u_raw) or u_raw
    if not url_base or not token or not u:
        return None
    url = f"{url_base}?usuario={quote(u)}"
    req = Request(
        url,
        method="GET",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    import ssl

    ctx = ssl.create_default_context()
    try:
        with urlopen(req, timeout=20, context=ctx) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        if not payload.get("ok"):
            return None
        info = {
            "cuit_limite": payload.get("cuit_limite"),
            "cuit_usados": payload.get("cuit_usados"),
            "cuit_disponibles": payload.get("cuit_disponibles"),
            "cuit_ilimitado": payload.get("cuit_ilimitado", False),
        }
        if info.get("cuit_disponibles") is not None:
            _aplicar_cupo_local_desde_servidor(
                u,
                int(payload.get("cuit_usados") or 0),
            )
        return info
    except HTTPError as exc:
        _LOG.warning("Cupo info remoto HTTP %s para %s", exc.code, u)
        return None
    except (URLError, OSError, ValueError, json.JSONDecodeError) as exc:
        _LOG.debug("Cupo info remoto no disponible para %s: %s", u, exc)
        return None


def _aplicar_cupo_local_desde_servidor(username: str, cuit_usados: int) -> None:
    """Refleja en overlay local el contador devuelto por /api/cupo/consumir."""
    u = resolver_clave_usuario_overlay(username)
    if not u:
        return
    try:
        usados = max(0, min(int(cuit_usados), 1_000_000))
    except (TypeError, ValueError):
        return
    with _lock:
        overlay = _cargar_overlay_completo()
        users = overlay.get("users")
        if not isinstance(users, dict) or u not in users:
            return
        meta = users[u]
        if not isinstance(meta, dict):
            return
        limite, _ = _leer_cupo_meta(meta)
        meta["cuit_usados"] = usados
        meta["cuit_limite"] = limite
        _guardar_overlay_completo(overlay)


def _consumir_cuit_remoto(username: str, cantidad: int = 1) -> bool:
    """Portable sin DATABASE_URL: registra el consumo en el servidor (Neon vía Render)."""
    import json
    import ssl
    from urllib.error import HTTPError, URLError
    from urllib.request import Request, urlopen

    try:
        from auth import _remote_token
    except Exception:
        _set_error_cupo("Sync remoto no configurado.")
        return False

    url = _url_api_cupo_remota()
    token = (_remote_token() or "").strip()
    u_raw = (username or "").strip()
    if not url:
        _set_error_cupo("Falta la URL del servidor en auth_remote.enc / auth_remote.txt.")
        return False
    if not token:
        _set_error_cupo("Falta el token remoto (auth_remote.enc o 2.ª línea de auth_remote.txt).")
        return False
    if not u_raw:
        _set_error_cupo("Usuario de cupo vacío.")
        return False
    body = json.dumps(
        {"usuario": u_raw, "cantidad": max(1, int(cantidad))},
        ensure_ascii=False,
    ).encode("utf-8")
    req = Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    ctx = ssl.create_default_context()
    try:
        with urlopen(req, timeout=25, context=ctx) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
            if payload.get("ok"):
                _LOG.info("Cupo CUIT registrado en servidor para %s.", u_raw)
                usados = payload.get("cuit_usados")
                if usados is not None:
                    _aplicar_cupo_local_desde_servidor(u_raw, int(usados))
                return True
            det = str(payload.get("error") or "respuesta_invalida")
            _set_error_cupo(f"Servidor rechazó el cupo: {det}")
            return False
    except HTTPError as exc:
        det = ""
        try:
            det = exc.read().decode("utf-8", errors="replace")[:240]
        except Exception:
            pass
        msg = det or exc.reason or str(exc.code)
        _set_error_cupo(f"HTTP {exc.code} al registrar cupo: {msg}")
        _LOG.warning(
            "Cupo remoto HTTP %s para %s (%s): %s",
            exc.code,
            u_raw,
            url,
            msg,
        )
        return False
    except (URLError, OSError, ValueError, json.JSONDecodeError) as exc:
        _set_error_cupo(f"Sin conexión al servidor de cupo: {exc}")
        _LOG.warning("Cupo remoto no disponible para %s: %s", u_raw, exc)
        return False


def _url_api_uso_remota() -> str:
    base = _base_api_remota()
    return f"{base}/api/uso/registrar" if base else ""


def registrar_uso_remoto(username: str, incrementos: dict[str, int]) -> bool:
    """Portable: envía métricas de uso al servidor para el dashboard admin."""
    import ssl
    from urllib.error import HTTPError, URLError
    from urllib.request import Request, urlopen

    if not incrementos:
        return True
    try:
        from auth import _remote_token
    except Exception:
        return False

    url = _url_api_uso_remota()
    token = (_remote_token() or "").strip()
    u_raw = (username or "").strip()
    if not url or not token or not u_raw:
        return False

    payload: dict[str, object] = {"usuario": u_raw}
    for key, val in incrementos.items():
        if val > 0:
            payload[key] = int(val)
    if len(payload) <= 1:
        return True

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    ctx = ssl.create_default_context()
    try:
        with urlopen(req, timeout=20, context=ctx) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return bool(data.get("ok"))
    except (HTTPError, URLError, OSError, ValueError, json.JSONDecodeError) as exc:
        _LOG.debug("Uso remoto no registrado para %s: %s", u_raw, exc)
        return False


def control_cupo_cuit(username: str | None):
    """Devuelve (hay_cupo, on_exitoso) o (None, None) si no aplica cupo.

    El consumo se confirma al cerrar cada CUIT con éxito. Si el usuario cancela
    durante ese CUIT, no se descuenta; los ya confirmados en el mismo lote sí.
    """
    u = (username or "").strip()
    if not u:
        return None, None
    from auth import es_administrador

    if es_administrador(u):
        return None, None
    if info_cupo_cuit(u) is None:
        return None, None

    def hay_cupo() -> bool:
        return cupo_cuit_disponible(u) > 0

    def on_exitoso() -> None:
        if not consumir_cuit_exitoso(u):
            _LOG.warning(
                "Cupo no actualizado para %s: límite alcanzado o persistencia fallida.",
                u,
            )

    return hay_cupo, on_exitoso


def _parse_fecha_local(val: Any) -> date | None:
    from auth import _parse_fecha

    return _parse_fecha(val)


_CUIT_MULTIPLIERS = (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)


def cuit_digito_verificador_valido(digits: str) -> bool:
    if not _CUIT_RE.match(digits):
        return False
    total = sum(int(digits[i]) * _CUIT_MULTIPLIERS[i] for i in range(10))
    mod = 11 - (total % 11)
    if mod == 11:
        esperado = 0
    elif mod == 10:
        esperado = 9
    else:
        esperado = mod
    return int(digits[10]) == esperado


def normalizar_cuit(val: str, *, validar_digito: bool = False) -> str | None:
    digits = re.sub(r"\D", "", (val or "").strip())
    if not _CUIT_RE.match(digits):
        return None
    if validar_digito and not cuit_digito_verificador_valido(digits):
        return None
    return digits


def normalizar_usuario_admin(val: str) -> str | None:
    """Usuario de alta directa admin: letras y números (3–40), sin validar CUIT."""
    s = (val or "").strip()
    if not _USUARIO_ADMIN_RE.match(s):
        return None
    return s


def resolver_clave_overlay(val: str) -> str | None:
    """Clave en usuarios_registrados (usuario libre o CUIT normalizado)."""
    raw = (val or "").strip()
    if not raw:
        return None
    overlay = cargar_usuarios_overlay()
    if raw in overlay:
        return raw
    u = normalizar_cuit(raw)
    if u and u in overlay:
        return u
    raw_lower = raw.lower()
    for clave in overlay:
        if clave.lower() == raw_lower:
            return clave
    return None


def resolver_clave_usuario_overlay(val: str) -> str | None:
    """Clave overlay para cupo/uso (misma resolución que lectura y consumo)."""
    raw = (val or "").strip()
    if not raw:
        return None
    clave = resolver_clave_overlay(raw)
    if clave:
        return clave
    overlay = cargar_usuarios_overlay()
    nu = normalizar_cuit(raw)
    if nu and nu in overlay:
        return nu
    if raw in overlay:
        return raw
    return None


def formatear_cuit(cuit: str) -> str:
    d = normalizar_cuit(cuit) or cuit
    if len(d) == 11:
        return f"{d[:2]}-{d[2:10]}-{d[10]}"
    return d


def meta_es_admin(meta: dict[str, Any] | None) -> bool:
    if not isinstance(meta, dict):
        return False
    rol = str(meta.get("rol") or "").strip().lower()
    return rol == "admin" or meta.get("es_admin") is True or meta.get("admin") is True


def admin_en_overlay(username: str | None = None) -> dict[str, Any] | None:
    buscado = (username or os.environ.get("AUTH_ADMIN_USER") or "Lucas").strip()
    for clave, meta in cargar_usuarios_overlay().items():
        if not isinstance(meta, dict) or not meta_es_admin(meta):
            continue
        if not buscado or clave == buscado:
            return meta
    return None


def _admin_valido_hasta_default() -> date:
    raw = (os.environ.get("AUTH_ADMIN_VALIDO_HASTA") or "").strip()
    parsed = _parse_fecha_local(raw) if raw else None
    if parsed:
        return parsed
    return date.today() + timedelta(days=365 * 100 + 25)


def guardar_admin_sistema(
    username: str,
    password: str,
    *,
    valido_hasta: date | None = None,
) -> None:
    u = (username or "").strip()
    pwd = password or ""
    if not u or not pwd:
        raise ValueError("admin_invalido")
    vh = valido_hasta or _admin_valido_hasta_default()
    with _lock:
        path = _path_usuarios_overlay()
        overlay = _read_store("usuarios_registrados", {"version": 1, "users": {}}, path)
        users = overlay.get("users")
        if not isinstance(users, dict):
            overlay["users"] = {}
            users = overlay["users"]
        users[u] = {
            "password": hash_password(pwd),
            "rol": "admin",
            "activo": True,
            "pendiente_aprobacion": False,
            "valido_hasta": vh.isoformat(),
            "creado_en": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        overlay["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        _write_store("usuarios_registrados", overlay, path)


def asegurar_admin_en_db() -> bool:
    """Crea el admin en PostgreSQL si falta (usa AUTH_ADMIN_USER / AUTH_ADMIN_PASSWORD)."""
    try:
        from auth_registro_db import enabled

        if not enabled():
            return False
    except Exception:
        return False
    user = (os.environ.get("AUTH_ADMIN_USER") or "Lucas").strip()
    if admin_en_overlay(user):
        return False
    pwd = (os.environ.get("AUTH_ADMIN_PASSWORD") or "").strip()
    if not pwd:
        _LOG.warning(
            "Administrador %s no está en PostgreSQL y AUTH_ADMIN_PASSWORD está vacío; "
            "definilo en Render o ejecutá tools/init_admin_neon.py",
            user,
        )
        return False
    guardar_admin_sistema(user, pwd)
    _LOG.info("Administrador %s guardado en PostgreSQL (usuarios_registrados)", user)
    return True


def normalizar_telefono(area: str, numero: str) -> tuple[str, str] | None:
    """Código de área sin 0 inicial; número móvil sin prefijo 15."""
    a = re.sub(r"\D", "", (area or "").strip())
    n = re.sub(r"\D", "", (numero or "").strip())
    while a.startswith("0"):
        a = a[1:]
    if n.startswith("15") and len(n) > 6:
        n = n[2:]
    if len(a) < 2 or len(a) > 4:
        return None
    if len(n) < 6 or len(n) > 8:
        return None
    return a, n


def formatear_telefono(area: str, numero: str) -> str:
    a, n = normalizar_telefono(area, numero) or (area, numero)
    if a and n:
        return f"{a} {n}"
    return ""


def url_whatsapp_cliente(area: str, numero: str) -> str:
    par = normalizar_telefono(area, numero)
    if not par:
        return ""
    a, n = par
    return f"https://wa.me/549{a}{n}"


def _telefono_desde_meta(meta: dict[str, Any] | None) -> dict[str, str]:
    if not isinstance(meta, dict):
        return {"fmt": "", "url": ""}
    area = str(meta.get("telefono_area") or "")
    numero = str(meta.get("telefono_numero") or "")
    fmt = formatear_telefono(area, numero)
    url = url_whatsapp_cliente(area, numero) if fmt else ""
    return {"fmt": fmt, "url": url}


def _leer_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        _LOG.warning("No se pudo leer %s: %s", path, exc)
        return default


def _escribir_json(path: Path, data: Any) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        raise RuntimeError(f"No se pudo guardar en {path}: {exc}") from exc


def _read_store(name: str, default: Any, path: Path | None = None) -> Any:
    db = False
    try:
        from auth_registro_db import enabled, read_json

        db = enabled()
        if db:
            return read_json(name, default)
    except Exception as exc:
        _LOG.warning("Lectura PostgreSQL falló (%s): %s", name, exc)
        if db:
            return default
    json_path = _resolve_store_path(name, path)
    if _portable_store_cifrado():
        from auth_crypto import AuthStoreCorruptError, leer_store_secreto, ruta_store_cifrado

        enc_path = ruta_store_cifrado(json_path)
        try:
            return leer_store_secreto(enc_path, json_path, default)
        except AuthStoreCorruptError as exc:
            _marcar_integridad_fallida(str(exc))
            raise
    return _leer_json(json_path, default)


def _write_store(name: str, data: Any, path: Path | None = None) -> None:
    db = False
    try:
        from auth_registro_db import enabled, write_json

        db = enabled()
        if db:
            write_json(name, data)
            return
    except Exception as exc:
        _LOG.error("Escritura PostgreSQL falló (%s): %s", name, exc)
        if db:
            raise RuntimeError(
                "DATABASE_URL configurada pero no se pudo escribir en PostgreSQL. "
                "Revisá la conexión Neon en Render."
            ) from exc
        _LOG.warning("Escritura en disco local como respaldo (%s)", name)
    json_path = _resolve_store_path(name, path)
    if _portable_store_cifrado():
        from auth_crypto import escribir_store_secreto, ruta_store_cifrado

        if not isinstance(data, dict):
            raise TypeError(f"store {name} debe ser dict")
        escribir_store_secreto(ruta_store_cifrado(json_path), data)
        return
    _escribir_json(json_path, data)


def hash_password(password: str) -> str:
    pwd = (password or "").encode("utf-8")
    return bcrypt.hashpw(pwd, bcrypt.gensalt(rounds=12)).decode("ascii")


def verificar_password(stored: str, password: str) -> bool:
    s = (stored or "").strip()
    pwd = (password or "").encode("utf-8")
    if s.startswith("$2"):
        try:
            return bcrypt.checkpw(pwd, s.encode("ascii"))
        except ValueError:
            return False
    return s == (password or "")


def cargar_usuarios_overlay() -> dict[str, dict[str, Any]]:
    users = _cargar_overlay_completo().get("users")
    return users if isinstance(users, dict) else {}


def _cargar_overlay_completo() -> dict[str, Any]:
    """Blob usuarios_registrados con clave users (tolera JSON mal migrado)."""
    data = _read_store("usuarios_registrados", {"version": 1, "users": {}})
    if not isinstance(data, dict):
        return {"version": 1, "users": {}}
    users = data.get("users")
    if isinstance(users, dict):
        return data
    flat = {
        k: v
        for k, v in data.items()
        if isinstance(v, dict) and k not in ("version", "updated_at", "users")
    }
    if flat:
        return {
            "version": data.get("version", 1),
            "users": flat,
            "updated_at": data.get("updated_at"),
        }
    data["users"] = {}
    return data


def _guardar_overlay_completo(overlay: dict[str, Any]) -> None:
    if not isinstance(overlay.get("users"), dict):
        overlay["users"] = {}
    overlay["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _write_store("usuarios_registrados", overlay)


def cuenta_en_registro_altas(cuit: str) -> bool:
    """True si ya hay fila en usuarios_registrados (Neon). No usa AUTH_USERS_JSON legacy."""
    raw = (cuit or "").strip()
    if not raw:
        return False
    try:
        overlay = cargar_usuarios_overlay()
        if raw in overlay:
            return True
        u = normalizar_cuit(raw)
        return bool(u and u in overlay)
    except Exception as exc:
        _LOG.warning("No se pudo verificar registro de %s: %s", raw, exc)
        return False


def _meta_overlay(cuit: str) -> dict[str, Any] | None:
    clave = resolver_clave_overlay(cuit)
    if not clave:
        return None
    meta = cargar_usuarios_overlay().get(clave)
    return meta if isinstance(meta, dict) else None


def cuenta_pendiente_aprobacion(cuit: str) -> dict[str, Any] | None:
    meta = _meta_overlay(cuit)
    if not meta:
        return None
    if meta.get("pendiente_aprobacion"):
        return meta
    return None


def cuenta_suspendida(cuit: str) -> bool:
    meta = _meta_overlay(cuit)
    if not meta:
        return False
    return meta.get("activo") is False and not meta.get("pendiente_aprobacion")


def verificar_acceso_overlay(cuit: str, password: str) -> str | None:
    """None = ok; 'pending_approval' | 'invalid'."""
    meta = cuenta_pendiente_aprobacion(cuit)
    if not meta:
        return None
    if verificar_password(str(meta.get("password") or ""), password):
        return "pending_approval"
    return "invalid"


def verificar_suspendido(cuit: str, password: str) -> str | None:
    """None = no suspendida; 'suspended' | 'invalid'."""
    if not cuenta_suspendida(cuit):
        return None
    meta = _meta_overlay(cuit)
    if not meta:
        return None
    if verificar_password(str(meta.get("password") or ""), password):
        return "suspended"
    return "invalid"


def alta_publica_habilitada() -> bool:
    v = (os.environ.get("AUTH_ALTA_PUBLICA") or "1").strip().lower()
    return v in ("1", "true", "yes", "on")


def usuario_existe(cuit: str) -> bool:
    raw = (cuit or "").strip()
    if not raw:
        return False
    try:
        overlay = cargar_usuarios_overlay()
        if raw in overlay:
            return True
        u = normalizar_cuit(raw)
        if u and u in overlay:
            return True
        from auth import _load_cuentas_sin_env_json, _usuarios_desde_env_json

        env = _usuarios_desde_env_json()
        base = env if env else _load_cuentas_sin_env_json()
        if raw in base:
            return True
        return bool(u and u in base)
    except Exception as exc:
        _LOG.warning("No se pudo verificar si existe el usuario %s: %s", raw, exc)
        return False


def _cargar_solicitudes() -> dict[str, Any]:
    data = _read_store("solicitudes_pendientes", {"solicitudes": {}})
    if not isinstance(data, dict):
        return {"solicitudes": {}}
    if "solicitudes" not in data or not isinstance(data["solicitudes"], dict):
        data["solicitudes"] = {}
    return data


def crear_solicitud(
    *,
    cuit: str,
    email: str,
    nombre: str = "",
    telefono_area: str = "",
    telefono_numero: str = "",
) -> tuple[str, dict[str, Any]]:
    u = normalizar_cuit(cuit, validar_digito=True)
    if not u:
        raise ValueError("cuit_invalido")
    em = (email or "").strip().lower()
    if not _EMAIL_RE.match(em):
        raise ValueError("email_invalido")
    tel = normalizar_telefono(telefono_area, telefono_numero)
    if not tel:
        raise ValueError("telefono_invalido")
    if cuenta_en_registro_altas(u):
        raise ValueError("cuit_duplicado")

    tel_area, tel_numero = tel
    token = secrets.token_urlsafe(32)
    ahora = datetime.now(timezone.utc)
    expira = ahora + timedelta(hours=_token_horas())
    registro = {
        "cuit": u,
        "email": em,
        "nombre": (nombre or "").strip(),
        "telefono_area": tel_area,
        "telefono_numero": tel_numero,
        "creado": ahora.isoformat(timespec="seconds"),
        "expira": expira.isoformat(timespec="seconds"),
        "usado": False,
    }

    with _lock:
        data = _cargar_solicitudes()
        # Una solicitud activa por CUIT
        for tok, sol in list(data["solicitudes"].items()):
            if not isinstance(sol, dict):
                continue
            if sol.get("cuit") == u and not sol.get("usado"):
                try:
                    exp = datetime.fromisoformat(str(sol["expira"]).replace("Z", "+00:00"))
                    if exp > ahora:
                        del data["solicitudes"][tok]
                except ValueError:
                    del data["solicitudes"][tok]
        data["solicitudes"][token] = registro
        _write_store("solicitudes_pendientes", data)

    return token, registro


def obtener_solicitud(token: str) -> dict[str, Any] | None:
    tok = (token or "").strip()
    if not tok:
        return None
    data = _cargar_solicitudes()
    sol = data.get("solicitudes", {}).get(tok)
    if not isinstance(sol, dict) or sol.get("usado"):
        return None
    try:
        exp = datetime.fromisoformat(str(sol["expira"]).replace("Z", "+00:00"))
    except ValueError:
        return None
    if exp <= datetime.now(timezone.utc):
        return None
    return sol


def activar_cuenta(
    token: str,
    password: str,
    *,
    aceptacion_legal: dict[str, str] | None = None,
) -> dict[str, Any]:
    tok = (token or "").strip()
    pwd = password or ""
    if len(pwd) < _min_password_len():
        raise ValueError("password_corta")

    with _lock:
        sol = obtener_solicitud(tok)
        if not sol:
            raise ValueError("token_invalido")
        cuit = str(sol["cuit"])
        if cuenta_en_registro_altas(cuit):
            raise ValueError("cuit_duplicado")

        overlay = _cargar_overlay_completo()
        users = overlay["users"]
        if not isinstance(users, dict):
            overlay["users"] = {}
            users = overlay["users"]
        users[cuit] = {
            "password": hash_password(pwd),
            "email": sol.get("email"),
            "nombre": sol.get("nombre") or "",
            "telefono_area": sol.get("telefono_area") or "",
            "telefono_numero": sol.get("telefono_numero") or "",
            "valido_desde": date.today().isoformat(),
            "activo": False,
            "pendiente_aprobacion": True,
            "password_definida": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        if aceptacion_legal:
            from legal_aceptacion import aplicar_aceptacion_a_meta

            aplicar_aceptacion_a_meta(
                users[cuit],
                version=aceptacion_legal.get("version"),
                metodo=aceptacion_legal.get("metodo") or "digital_clickwrap",
                ip=aceptacion_legal.get("ip") or "",
                user_agent=aceptacion_legal.get("user_agent") or "",
            )
        _guardar_overlay_completo(overlay)
        datos_legal = (
            _datos_notificacion_aceptacion_legal(cuit, users[cuit])
            if aceptacion_legal
            else None
        )

    if datos_legal:
        notificar_aceptacion_legal_async(**datos_legal)

        data = _cargar_solicitudes()
        if tok in data.get("solicitudes", {}):
            data["solicitudes"][tok]["usado"] = True
            data["solicitudes"][tok]["activado"] = datetime.now(timezone.utc).isoformat(
                timespec="seconds"
            )
            try:
                _write_store("solicitudes_pendientes", data)
            except RuntimeError as exc:
                _LOG.error(
                    "Contraseña de %s guardada, pero no se pudo marcar el enlace como usado: %s",
                    cuit,
                    exc,
                )

    registro_alta = {
        "cuit": cuit,
        "email": sol.get("email"),
        "nombre": sol.get("nombre") or "",
        "activado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "estado": "pendiente_aprobacion",
    }
    _registrar_alta_log(registro_alta)
    return registro_alta


def crear_usuario_admin(
    *,
    cuit: str,
    password: str,
    valido_hasta: str,
    email: str = "",
    nombre: str = "",
    telefono_area: str = "",
    telefono_numero: str = "",
) -> dict[str, Any]:
    """Alta manual desde el panel admin: usuario, clave y vencimiento definidos por el administrador."""
    u = normalizar_usuario_admin(cuit)
    if not u:
        raise ValueError("usuario_invalido")
    pwd = password or ""
    if len(pwd) < _min_password_len():
        raise ValueError("password_corta")
    vh = _parse_fecha_local(valido_hasta)
    if not vh:
        raise ValueError("vencimiento_invalido")
    hoy = date.today()
    if vh < hoy:
        raise ValueError("vencimiento_pasado")
    if cuenta_en_registro_altas(u):
        raise ValueError("usuario_duplicado")

    em = (email or "").strip().lower()
    if em and not _EMAIL_RE.match(em):
        raise ValueError("email_invalido")

    tel_area = ""
    tel_numero = ""
    if (telefono_area or "").strip() or (telefono_numero or "").strip():
        tel = normalizar_telefono(telefono_area, telefono_numero)
        if not tel:
            raise ValueError("telefono_invalido")
        tel_area, tel_numero = tel

    ahora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _lock:
        overlay = _cargar_overlay_completo()
        users = overlay.get("users")
        if not isinstance(users, dict):
            overlay["users"] = {}
            users = overlay["users"]
        users[u] = {
            "password": hash_password(pwd),
            "email": em,
            "nombre": (nombre or "").strip(),
            "telefono_area": tel_area,
            "telefono_numero": tel_numero,
            "valido_desde": hoy.isoformat(),
            "valido_hasta": vh.isoformat(),
            "activo": True,
            "pendiente_aprobacion": False,
            "alta_admin": ahora,
            "aprobado_en": ahora,
            "cuit_limite": _cuit_limite_default(),
            "cuit_usados": 0,
            "servicios": servicios_default(),
        }
        _guardar_overlay_completo(overlay)

    return {
        "cuit": u,
        "cuit_fmt": formatear_cuit(u),
        "valido_hasta": vh.isoformat(),
        "valido_hasta_fmt": vh.strftime("%d/%m/%Y"),
    }


def listar_pendientes_aprobacion() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for cuit, meta in cargar_usuarios_overlay().items():
        if not isinstance(meta, dict):
            continue
        if meta_es_admin(meta):
            continue
        if not meta.get("pendiente_aprobacion"):
            continue
        out.append(
            {
                "cuit": cuit,
                "cuit_fmt": formatear_cuit(cuit),
                "email": meta.get("email") or "",
                "nombre": meta.get("nombre") or "",
                "password_definida": meta.get("password_definida") or "",
                **_telefono_desde_meta(meta),
            }
        )
    out.sort(key=lambda x: x.get("password_definida") or "", reverse=True)
    return out


def aprobar_cuenta(cuit: str) -> bool:
    with _lock:
        u = resolver_clave_overlay(cuit)
        if not u:
            return False
        dias = _dias_suscripcion()
        hoy = date.today()
        valido_hasta = hoy + timedelta(days=dias)
        overlay = _cargar_overlay_completo()
        users = overlay.get("users")
        if not isinstance(users, dict) or u not in users:
            return False
        users[u]["activo"] = True
        users[u]["pendiente_aprobacion"] = False
        users[u]["valido_desde"] = hoy.isoformat()
        users[u]["valido_hasta"] = valido_hasta.isoformat()
        users[u]["aprobado_en"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        _inicializar_servicios_meta(users[u])
        _reset_cupo_meta(users[u])
        _guardar_overlay_completo(overlay)
    return True


def listar_usuarios_suscripcion() -> list[dict[str, Any]]:
    hoy = date.today()
    out: list[dict[str, Any]] = []
    for cuit, meta in cargar_usuarios_overlay().items():
        if not isinstance(meta, dict):
            continue
        if meta_es_admin(meta):
            continue
        if meta.get("pendiente_aprobacion"):
            continue
        suspendida = meta.get("activo") is False
        vh = _parse_fecha_local(meta.get("valido_hasta"))
        dias = (vh - hoy).days if vh else None
        limite, usados = _leer_cupo_meta(meta)
        legal = {}
        try:
            from legal_aceptacion import resumen_aceptacion

            legal = resumen_aceptacion(meta)
        except Exception:
            pass
        out.append(
            {
                "cuit": cuit,
                "cuit_fmt": formatear_cuit(cuit),
                "email": meta.get("email") or "",
                "nombre": meta.get("nombre") or "",
                "valido_hasta": vh.isoformat() if vh else "",
                "valido_hasta_fmt": vh.strftime("%d/%m/%Y") if vh else "—",
                "valido_hasta_input": vh.isoformat() if vh else "",
                "dias_restantes": dias,
                "vencida": not suspendida and dias is not None and dias < 0,
                "suspendida": suspendida,
                "cuit_limite": limite,
                "cuit_usados": usados,
                "cuit_disponibles": max(0, limite - usados),
                "servicios": _normalizar_servicios_meta(meta.get("servicios")),
                "legal_version": legal.get("version") or "",
                "legal_aceptada_en": legal.get("aceptada_en") or "",
                "legal_metodo": legal.get("metodo") or "",
                "legal_ip": legal.get("ip") or "",
                "legal_user_agent": meta.get("legal_aceptacion", {}).get("user_agent", "")
                if isinstance(meta.get("legal_aceptacion"), dict)
                else "",
                **_telefono_desde_meta(meta),
            }
        )
    out.sort(
        key=lambda x: (
            not x.get("suspendida"),
            x.get("dias_restantes") is None,
            x.get("dias_restantes") or 0,
        )
    )
    return out


def suspender_cuenta(cuit: str) -> bool:
    u = resolver_clave_overlay(cuit)
    if not u:
        return False
    with _lock:
        path = _path_usuarios_overlay()
        overlay = _read_store("usuarios_registrados", {"version": 1, "users": {}}, path)
        users = overlay.get("users")
        if not isinstance(users, dict) or u not in users:
            return False
        meta = users[u]
        if meta.get("pendiente_aprobacion") or meta.get("activo") is False:
            return False
        meta["activo"] = False
        meta["suspendido_en"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        overlay["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        _write_store("usuarios_registrados", overlay, path)
    return True


def reactivar_cuenta(cuit: str) -> bool:
    u = resolver_clave_overlay(cuit)
    if not u:
        return False
    with _lock:
        path = _path_usuarios_overlay()
        overlay = _read_store("usuarios_registrados", {"version": 1, "users": {}}, path)
        users = overlay.get("users")
        if not isinstance(users, dict) or u not in users:
            return False
        meta = users[u]
        if meta.get("pendiente_aprobacion") or meta.get("activo") is not False:
            return False
        meta["activo"] = True
        meta.pop("suspendido_en", None)
        meta["reactivado_en"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        overlay["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        _write_store("usuarios_registrados", overlay, path)
    return True


def eliminar_cuenta(cuit: str) -> bool:
    u = resolver_clave_overlay(cuit)
    if not u:
        return False
    with _lock:
        path = _path_usuarios_overlay()
        overlay = _read_store("usuarios_registrados", {"version": 1, "users": {}}, path)
        users = overlay.get("users")
        if not isinstance(users, dict) or u not in users:
            return False
        meta = users[u]
        if not isinstance(meta, dict):
            return False
        if meta_es_admin(meta):
            return False
        if meta.get("pendiente_aprobacion"):
            return False
        if meta.get("activo") is not False:
            return False
        del users[u]
        overlay["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        _write_store("usuarios_registrados", overlay, path)
        sol_data = _cargar_solicitudes()
        sols = sol_data.get("solicitudes")
        if isinstance(sols, dict) and u in sols:
            del sols[u]
            _write_store("solicitudes_pendientes", sol_data, _path_solicitudes())
    _registrar_alta_log(
        {
            "cuit": formatear_cuit(u),
            "email": meta.get("email") or "",
            "activado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "estado": "eliminada",
        }
    )
    return True


def actualizar_email_usuario(cuit: str, email: str) -> None:
    """Actualiza el email de registro (solo admin). Afecta recuperación de contraseña."""
    u = resolver_clave_overlay(cuit)
    if not u:
        raise ValueError("no_encontrada")
    em = (email or "").strip().lower()
    if em and not _EMAIL_RE.match(em):
        raise ValueError("email_invalido")
    with _lock:
        path = _path_usuarios_overlay()
        overlay = _read_store("usuarios_registrados", {"version": 1, "users": {}}, path)
        users = overlay.get("users")
        if not isinstance(users, dict) or u not in users:
            raise ValueError("no_encontrada")
        meta = users[u]
        if not isinstance(meta, dict):
            raise ValueError("no_encontrada")
        if meta_es_admin(meta):
            raise ValueError("no_encontrada")
        anterior = str(meta.get("email") or "").strip().lower()
        if anterior == em:
            return
        meta["email"] = em
        meta["email_cambiado_admin"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        historial = meta.get("email_historial")
        if not isinstance(historial, list):
            historial = []
        historial.insert(
            0,
            {
                "anterior": anterior,
                "nuevo": em,
                "en": meta["email_cambiado_admin"],
            },
        )
        meta["email_historial"] = historial[:20]
        overlay["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        _write_store("usuarios_registrados", overlay, path)


def actualizar_vencimiento(cuit: str, valido_hasta: str) -> bool:
    u = resolver_clave_overlay(cuit)
    if not u:
        return False
    vh = _parse_fecha_local(valido_hasta)
    if not vh:
        return False
    with _lock:
        path = _path_usuarios_overlay()
        overlay = _read_store("usuarios_registrados", {"version": 1, "users": {}}, path)
        users = overlay.get("users")
        if not isinstance(users, dict) or u not in users:
            return False
        meta = users[u]
        if meta.get("pendiente_aprobacion"):
            return False
        meta["valido_hasta"] = vh.isoformat()
        overlay["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        _write_store("usuarios_registrados", overlay, path)
    return True


def cambiar_contrasena_usuario(cuit: str, nueva_password: str) -> None:
    u = resolver_clave_overlay(cuit)
    if not u:
        raise ValueError("no_encontrada")
    pwd = nueva_password or ""
    if len(pwd) < _min_password_len():
        raise ValueError("password_corta")
    with _lock:
        path = _path_usuarios_overlay()
        overlay = _read_store("usuarios_registrados", {"version": 1, "users": {}}, path)
        users = overlay.get("users")
        if not isinstance(users, dict) or u not in users:
            raise ValueError("no_encontrada")
        meta = users[u]
        if not isinstance(meta, dict):
            raise ValueError("no_encontrada")
        if meta_es_admin(meta):
            raise ValueError("no_encontrada")
        if meta.get("pendiente_aprobacion"):
            raise ValueError("no_encontrada")
        meta["password"] = hash_password(pwd)
        meta["password_cambiada_admin"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        overlay["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        _write_store("usuarios_registrados", overlay, path)


def renovar_suscripcion(cuit: str, dias: int | None = None) -> bool:
    u = resolver_clave_overlay(cuit)
    if not u:
        return False
    duracion = dias if dias is not None else _dias_suscripcion()
    if duracion < 1:
        return False
    hoy = date.today()
    with _lock:
        path = _path_usuarios_overlay()
        overlay = _read_store("usuarios_registrados", {"version": 1, "users": {}}, path)
        users = overlay.get("users")
        if not isinstance(users, dict) or u not in users:
            return False
        meta = users[u]
        if meta.get("pendiente_aprobacion"):
            return False
        if meta.get("activo") is False:
            return False
        vh_actual = _parse_fecha_local(meta.get("valido_hasta"))
        base = max(hoy, vh_actual) if vh_actual else hoy
        nueva_hasta = base + timedelta(days=duracion)
        if not meta.get("valido_desde") or (vh_actual and hoy > vh_actual):
            meta["valido_desde"] = hoy.isoformat()
        meta["valido_hasta"] = nueva_hasta.isoformat()
        meta["renovado_en"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        _reset_cupo_meta(meta)
        overlay["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        _write_store("usuarios_registrados", overlay, path)
    return True


def actualizar_cuit_limite(cuit: str, limite: int) -> bool:
    u = resolver_clave_overlay(cuit)
    if not u:
        return False
    try:
        nuevo_limite = max(0, min(int(limite), 1_000_000))
    except (TypeError, ValueError):
        return False
    with _lock:
        overlay = _cargar_overlay_completo()
        users = overlay.get("users")
        if not isinstance(users, dict) or u not in users:
            return False
        meta = users[u]
        if meta.get("pendiente_aprobacion"):
            return False
        meta["cuit_limite"] = nuevo_limite
        _inicializar_cupo_meta(meta)
        _guardar_overlay_completo(overlay)
    return True


def registrar_aceptacion_legal_usuario(
    cuit: str,
    *,
    version: str = "",
    metodo: str = "digital_clickwrap",
    ip: str = "",
    user_agent: str = "",
) -> bool:
    u = resolver_clave_overlay(cuit)
    if not u:
        return False
    with _lock:
        overlay = _cargar_overlay_completo()
        users = overlay.get("users")
        if not isinstance(users, dict) or u not in users:
            return False
        from legal_aceptacion import aplicar_aceptacion_a_meta

        aplicar_aceptacion_a_meta(
            users[u],
            version=version,
            metodo=metodo,
            ip=ip,
            user_agent=user_agent,
        )
        _guardar_overlay_completo(overlay)
        datos_legal = _datos_notificacion_aceptacion_legal(u, users[u])
    notificar_aceptacion_legal_async(**datos_legal)
    return True


def info_suscripcion_usuario(username: str) -> dict[str, Any] | None:
    from auth import _load_cuentas, es_administrador

    u_raw = (username or "").strip()
    if not u_raw or es_administrador(u_raw):
        return None
    u = normalizar_cuit(u_raw) or u_raw
    cuenta = _load_cuentas().get(u) or _load_cuentas().get(u_raw)
    if not cuenta or not cuenta.valido_hasta:
        return None
    hoy = date.today()
    dias = (cuenta.valido_hasta - hoy).days
    out: dict[str, Any] = {
        "valido_hasta": cuenta.valido_hasta,
        "valido_hasta_fmt": cuenta.valido_hasta.strftime("%d/%m/%Y"),
        "dias_restantes": dias,
    }
    cupo = info_cupo_cuit(u)
    if cupo:
        out.update(cupo)
    return out


def verificar_identidad_recuperacion(cuit: str, email: str) -> bool:
    u = normalizar_cuit(cuit)
    em = (email or "").strip().lower()
    if not u or not _EMAIL_RE.match(em):
        return False
    meta = cargar_usuarios_overlay().get(u)
    if not isinstance(meta, dict):
        return False
    stored = str(meta.get("email") or "").strip().lower()
    return bool(stored and stored == em)


def restablecer_contrasena(cuit: str, email: str, nueva_password: str) -> bool:
    u = normalizar_cuit(cuit)
    em = (email or "").strip().lower()
    pwd = nueva_password or ""
    if not u or not _EMAIL_RE.match(em):
        raise ValueError("reset_no_coincide")
    if len(pwd) < _min_password_len():
        raise ValueError("password_corta")
    with _lock:
        path = _path_usuarios_overlay()
        overlay = _read_store("usuarios_registrados", {"version": 1, "users": {}}, path)
        users = overlay.get("users")
        if not isinstance(users, dict) or u not in users:
            raise ValueError("reset_no_coincide")
        meta = users[u]
        if not isinstance(meta, dict):
            raise ValueError("reset_no_coincide")
        stored = str(meta.get("email") or "").strip().lower()
        if stored != em:
            raise ValueError("reset_no_coincide")
        meta["password"] = hash_password(pwd)
        meta["password_restablecida"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        overlay["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        _write_store("usuarios_registrados", overlay, path)
    return True


def rechazar_cuenta(cuit: str) -> bool:
    u = resolver_clave_overlay(cuit)
    if not u:
        return False
    with _lock:
        path = _path_usuarios_overlay()
        overlay = _read_store("usuarios_registrados", {"version": 1, "users": {}}, path)
        users = overlay.get("users")
        if not isinstance(users, dict) or u not in users:
            return False
        meta = users[u]
        if not meta.get("pendiente_aprobacion"):
            return False
        del users[u]
        overlay["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        _write_store("usuarios_registrados", overlay, path)
    return True


def _registrar_alta_log(entry: dict[str, Any]) -> None:
    try:
        path = _path_log_altas()
        data = _read_store("altas_completadas", {"altas": []}, path)
        if not isinstance(data.get("altas"), list):
            data["altas"] = []
        data["altas"].insert(0, entry)
        data["altas"] = data["altas"][:200]
        _write_store("altas_completadas", data, path)
    except RuntimeError as exc:
        _LOG.error("No se pudo registrar alta en historial (la contraseña sí se guardó): %s", exc)


def listar_altas_recientes(limit: int = 30) -> list[dict[str, Any]]:
    data = _read_store("altas_completadas", {"altas": []})
    altas = data.get("altas") if isinstance(data, dict) else []
    if not isinstance(altas, list):
        return []
    return [a for a in altas[:limit] if isinstance(a, dict)]


def whatsapp_alta_admin_url(cuit: str, email: str, nombre: str = "") -> str:
    tel = (os.environ.get("AUTH_ADMIN_WHATSAPP") or "5493513132914").strip()
    cuit_fmt = formatear_cuit(cuit)
    nom = f" ({nombre})" if nombre else ""
    msg = (
        f"Solicitud de alta en {APP_NAME}: CUIT {cuit_fmt}{nom}, "
        f"email {email}. Ya se ha generado Usuario/Contraseña"
    )
    return f"https://wa.me/{tel}?text={quote(msg)}"


def whatsapp_solicitud_admin_url(cuit: str, email: str, nombre: str = "") -> str:
    tel = (os.environ.get("AUTH_ADMIN_WHATSAPP") or "5493513132914").strip()
    cuit_fmt = formatear_cuit(cuit)
    nom = f" ({nombre})" if nombre else ""
    msg = (
        f"Nueva solicitud de acceso en {APP_NAME}: CUIT {cuit_fmt}{nom}, "
        f"email {email}. El cliente aún debe elegir contraseña por enlace."
    )
    return f"https://wa.me/{tel}?text={quote(msg)}"


def _smtp_usar_ssl(port: int) -> bool:
    """True = conexión SMTP_SSL (típico puerto 465). False = SMTP + STARTTLS (587)."""
    if port == 465:
        return True
    if port in (587, 25):
        return False
    flag = (os.environ.get("SMTP_USE_SSL") or "").strip().lower()
    if flag in ("1", "true", "yes", "on"):
        return True
    if flag in ("0", "false", "no", "off"):
        return False
    return port == 465


def _smtp_credenciales() -> tuple[str, str, str, int, bool, str]:
    host = (os.environ.get("SMTP_HOST") or "").strip()
    user = (os.environ.get("SMTP_USER") or "").strip()
    password = re.sub(r"\s+", "", (os.environ.get("SMTP_PASSWORD") or ""))
    port_raw = (os.environ.get("SMTP_PORT") or "587").strip()
    try:
        port = int(port_raw)
    except ValueError:
        port = 587
    use_ssl = _smtp_usar_ssl(port)
    remitente = (os.environ.get("SMTP_FROM") or user or f"noreply@{host}").strip()
    return host, user, password, port, use_ssl, remitente


def _smtp_error_legible(exc: BaseException) -> str:
    raw = str(exc).strip() or exc.__class__.__name__
    lower = raw.lower()
    if "535" in raw or "username and password not accepted" in lower:
        return (
            "Gmail rechazó usuario o contraseña. Usá contraseña de aplicación "
            "(16 caracteres), no la clave normal. Detalle: " + raw
        )
    if "534" in raw or "application-specific password" in lower:
        return "Gmail exige contraseña de aplicación. Detalle: " + raw
    if "timed out" in lower or "timeout" in lower:
        return (
            "Tiempo de espera agotado al conectar con SMTP. "
            "Probá SMTP_PORT=465 y SMTP_USE_SSL=1. Detalle: " + raw
        )
    if "connection refused" in lower or "connect error" in lower:
        return (
            "No se pudo conectar al servidor SMTP (host/puerto). "
            "En Render probá 465+SSL. Detalle: " + raw
        )
    if "network is unreachable" in lower or "errno 101" in lower:
        return (
            "Render plan gratis bloquea SMTP (puertos 25, 465 y 587). "
            "Configurá RESEND_API_KEY + RESEND_FROM (https://resend.com, envío por HTTPS) "
            "o actualizá a un plan pago de Render. Detalle: " + raw
        )
    if "550" in raw or "553" in raw or "sender" in lower:
        return (
            "Problema con el remitente (SMTP_FROM debe coincidir con SMTP_USER en Gmail). "
            "Detalle: " + raw
        )
    return raw


def _smtp_ejecutar(
    *,
    host: str,
    user: str,
    password: str,
    port: int,
    use_ssl: bool,
    timeout: int,
    enviar: EmailMessage | None = None,
) -> tuple[bool, str | None]:
    try:
        if use_ssl:
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, port, timeout=timeout, context=ctx) as smtp:
                smtp.login(user, password)
                if enviar is not None:
                    smtp.send_message(enviar)
        else:
            with smtplib.SMTP(host, port, timeout=timeout) as smtp:
                smtp.ehlo()
                if port != 25:
                    smtp.starttls(context=ssl.create_default_context())
                    smtp.ehlo()
                smtp.login(user, password)
                if enviar is not None:
                    smtp.send_message(enviar)
        return True, None
    except Exception as exc:
        msg = _smtp_error_legible(exc)
        _LOG.error("SMTP falló (%s:%s ssl=%s): %s", host, port, use_ssl, msg)
        return False, msg


def _en_render_host() -> bool:
    return (os.environ.get("RENDER") or "").strip().lower() in ("true", "1", "yes", "on")


def _resend_api_key() -> str:
    return (os.environ.get("RESEND_API_KEY") or "").strip()


def _resend_from() -> str:
    return (
        (os.environ.get("RESEND_FROM") or "").strip()
        or (os.environ.get("SMTP_FROM") or "").strip()
        or (os.environ.get("SMTP_USER") or "").strip()
    )


def _email_transport() -> str:
    if _resend_api_key():
        return "resend"
    host, user, password, *_ = _smtp_credenciales()
    if host and user and password:
        return "smtp"
    return "none"


def _enviar_email_resend(
    destino: str,
    asunto: str,
    cuerpo: str,
    *,
    timeout: int = 20,
) -> tuple[bool, str | None]:
    api_key = _resend_api_key()
    if not api_key:
        return False, "RESEND_API_KEY no configurado"
    remitente = _resend_from()
    if not remitente:
        return False, "RESEND_FROM (o SMTP_FROM) no configurado"
    payload = json.dumps(
        {
            "from": remitente,
            "to": [destino],
            "subject": asunto,
            "text": cuerpo,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    req = Request(
        "https://api.resend.com/emails",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": f"{APP_NAME}/email",
        },
        method="POST",
    )
    try:
        with urlopen(req, timeout=timeout) as resp:
            if 200 <= resp.status < 300:
                _LOG.info("Email enviado vía Resend a %s", destino)
                return True, None
            body = resp.read().decode("utf-8", errors="replace")
            return False, f"Resend HTTP {resp.status}: {body[:350]}"
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else str(exc)
        return False, f"Resend HTTP {exc.code}: {body[:350]}"
    except URLError as exc:
        return False, _smtp_error_legible(exc.reason if exc.reason else exc)
    except Exception as exc:
        return False, _smtp_error_legible(exc)


def _resend_probar_api(timeout: int = 15) -> tuple[bool, str | None]:
    api_key = _resend_api_key()
    if not api_key:
        return False, "RESEND_API_KEY no configurado"
    req = Request(
        "https://api.resend.com/domains",
        headers={
            "Authorization": f"Bearer {api_key}",
            "User-Agent": f"{APP_NAME}/email",
        },
        method="GET",
    )
    try:
        with urlopen(req, timeout=timeout) as resp:
            if 200 <= resp.status < 300:
                return True, None
            body = resp.read().decode("utf-8", errors="replace")
            return False, f"Resend HTTP {resp.status}: {body[:350]}"
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else str(exc)
        return False, f"Resend HTTP {exc.code}: {body[:350]}"
    except Exception as exc:
        return False, _smtp_error_legible(exc)


def _smtp_timeout_sec() -> int:
    raw = (os.environ.get("SMTP_TIMEOUT_SEC") or "8").strip()
    try:
        return max(3, min(int(raw), 30))
    except ValueError:
        return 8


def _smtp_timeout_background() -> int:
    raw = (os.environ.get("SMTP_TIMEOUT_BACKGROUND_SEC") or "25").strip()
    try:
        return max(8, min(int(raw), 60))
    except ValueError:
        return 25


def _enviar_email(
    destino: str,
    asunto: str,
    cuerpo: str,
    *,
    timeout: int | None = None,
) -> tuple[bool, str | None]:
    if not destino:
        return False, "Destino de email vacío"
    wait = timeout if timeout is not None else _smtp_timeout_sec()
    if _resend_api_key():
        return _enviar_email_resend(destino, asunto, cuerpo, timeout=max(wait, 15))

    host, user, password, port, use_ssl, remitente = _smtp_credenciales()
    if not host:
        hint = (
            "Configurá RESEND_API_KEY + RESEND_FROM (Render gratis bloquea SMTP) "
            "o SMTP_HOST + SMTP_USER + SMTP_PASSWORD."
        )
        if _en_render_host():
            return False, hint
        return False, "SMTP_HOST no configurado"
    if not user or not password:
        return False, "SMTP_USER o SMTP_PASSWORD faltante"
    if (
        "gmail.com" in host.lower()
        and (os.environ.get("SMTP_FROM") or user).strip().lower() != user.lower()
    ):
        return (
            False,
            "Con Gmail, SMTP_FROM debe ser igual a SMTP_USER "
            f"(ahora FROM={(os.environ.get('SMTP_FROM') or '').strip() or '—'}, USER={user}).",
        )
    msg = EmailMessage()
    msg["Subject"] = str(Header(asunto, "utf-8"))
    msg["From"] = remitente
    msg["To"] = destino
    msg.set_content(cuerpo, charset="utf-8")
    ok, err = _smtp_ejecutar(
        host=host,
        user=user,
        password=password,
        port=port,
        use_ssl=use_ssl,
        timeout=wait,
        enviar=msg,
    )
    if ok:
        _LOG.info("Email enviado a %s (asunto: %s)", destino, asunto)
    return ok, err


def _email_admin_configurado() -> str:
    return (os.environ.get("AUTH_ADMIN_NOTIFY_EMAIL") or "").strip()


def _datos_notificacion_aceptacion_legal(cuit: str, meta: dict[str, Any]) -> dict[str, str]:
    reg = meta.get("legal_aceptacion")
    if not isinstance(reg, dict):
        reg = {}
    return {
        "cuit": cuit,
        "email": str(meta.get("email") or ""),
        "nombre": str(meta.get("nombre") or ""),
        "version": str(reg.get("version") or ""),
        "metodo": str(reg.get("metodo") or ""),
        "ip": str(reg.get("ip") or ""),
        "aceptada_en": str(reg.get("aceptada_en") or ""),
        "user_agent": str(reg.get("user_agent") or ""),
    }


def _avisar_admin_por_email(
    asunto: str,
    cuerpo: str,
    *,
    contexto: str,
    timeout: int | None = None,
) -> bool:
    admin_mail = _email_admin_configurado()
    if not admin_mail:
        _LOG.warning(
            "AUTH_ADMIN_NOTIFY_EMAIL no configurado; no se envía email (%s)",
            contexto,
        )
        return False
    ok, err = _enviar_email(admin_mail, asunto, cuerpo, timeout=timeout)
    if not ok:
        _LOG.error(
            "Falló el email (%s) hacia %s: %s",
            contexto,
            admin_mail,
            err or "error desconocido",
        )
    return ok


def estado_smtp(*, probar_conexion: bool = False) -> dict[str, Any]:
    """Diagnóstico de email (SMTP o Resend HTTPS), sin exponer secretos."""
    host, user, password, port, use_ssl, smtp_from = _smtp_credenciales()
    notify = _email_admin_configurado()
    resend_key = _resend_api_key()
    resend_from = _resend_from()
    transport = _email_transport()
    gmail_from_ok = True
    gmail_from_nota = None
    if host and "gmail.com" in host.lower() and user:
        gmail_from_ok = smtp_from.lower() == user.lower()
        if not gmail_from_ok:
            gmail_from_nota = "SMTP_FROM debe ser igual a SMTP_USER para Gmail."

    if transport == "resend":
        vars_presentes = {
            "AUTH_ADMIN_NOTIFY_EMAIL": bool(notify),
            "RESEND_API_KEY": bool(resend_key),
            "RESEND_FROM": bool(resend_from),
        }
        vars_completas = all(vars_presentes.values())
    else:
        vars_presentes = {
            "AUTH_ADMIN_NOTIFY_EMAIL": bool(notify),
            "SMTP_HOST": bool(host),
            "SMTP_USER": bool(user),
            "SMTP_PASSWORD": bool(password),
            "SMTP_FROM": bool(smtp_from),
        }
        vars_completas = all(vars_presentes.values())

    avisos = [
        "Render plan gratis: SMTP (puertos 465/587) bloqueado → usá RESEND_API_KEY.",
        "Resend: https://resend.com — prueba con FROM=onboarding@resend.dev (solo a tu email).",
        "Alternativa: plan pago Render (SMTP Gmail vuelve a funcionar).",
        "Revisá spam en AUTH_ADMIN_NOTIFY_EMAIL.",
    ]
    if transport == "smtp":
        avisos = [
            "Gmail SMTP: contraseña de aplicación (16 caracteres).",
            "En Render gratis SMTP no funciona (Network unreachable).",
            "SMTP_FROM = SMTP_USER en Gmail.",
            "Revisá spam en AUTH_ADMIN_NOTIFY_EMAIL.",
        ]

    out: dict[str, Any] = {
        "transporte": transport,
        "vars_completas": vars_completas,
        "vars_presentes": vars_presentes,
        "host": host or None,
        "puerto": port if transport == "smtp" else None,
        "use_ssl": use_ssl if transport == "smtp" else None,
        "modo": "HTTPS (Resend)" if transport == "resend" else ("SSL" if use_ssl else "STARTTLS"),
        "notify_email": notify or None,
        "smtp_from": resend_from if transport == "resend" else (smtp_from or None),
        "gmail_from_ok": gmail_from_ok,
        "gmail_from_nota": gmail_from_nota,
        "render_host": _en_render_host(),
        "render_smtp_bloqueado": _en_render_host() and transport == "smtp",
        "avisos": avisos,
    }
    if probar_conexion:
        if not vars_completas:
            faltan = [k for k, v in vars_presentes.items() if not v]
            out["conexion_ok"] = False
            out["conexion_error"] = f"Faltan variables: {', '.join(faltan)}"
        elif transport == "resend":
            ok, err = _resend_probar_api(timeout=20)
            out["conexion_ok"] = ok
            if err:
                out["conexion_error"] = err
        elif not gmail_from_ok:
            out["conexion_ok"] = False
            out["conexion_error"] = gmail_from_nota
        else:
            ok, err = _smtp_ejecutar(
                host=host,
                user=user,
                password=password,
                port=port,
                use_ssl=use_ssl,
                timeout=20,
                enviar=None,
            )
            out["conexion_ok"] = ok
            if err:
                out["conexion_error"] = err
    return out


def _notificar_en_segundo_plano(fn, *args, **kwargs) -> None:
    """No bloquea la respuesta HTTP (evita timeout en Render si SMTP tarda)."""

    def _run() -> None:
        try:
            _LOG.info("Iniciando notificación por email en segundo plano (%s)", fn.__name__)
            resultado = fn(*args, **kwargs)
            if isinstance(resultado, dict) and not resultado.get("email_enviado"):
                _LOG.error(
                    "Notificación %s: email no enviado (revisá SMTP_* y AUTH_ADMIN_NOTIFY_EMAIL)",
                    fn.__name__,
                )
            else:
                _LOG.info("Notificación %s completada", fn.__name__)
        except Exception as exc:
            _LOG.exception("Notificación en segundo plano falló (%s): %s", fn.__name__, exc)

    threading.Thread(target=_run, daemon=False, name="auth-notify").start()


def probar_email_admin() -> dict[str, Any]:
    """Envía un correo de prueba al admin (panel de diagnóstico)."""
    admin_mail = _email_admin_configurado()
    if not admin_mail:
        return {"ok": False, "error": "AUTH_ADMIN_NOTIFY_EMAIL no configurado"}
    asunto = f"[{APP_NAME}] Prueba de notificación de altas"
    cuerpo = (
        f"Correo de prueba desde {APP_NAME}.\n\n"
        "Si lo recibís, la notificación por email está bien configurada.\n"
        "Revisá también la carpeta de spam."
    )
    ok, err = _enviar_email(
        admin_mail,
        asunto,
        cuerpo,
        timeout=_smtp_timeout_background(),
    )
    if ok:
        return {"ok": True, "destino": admin_mail}
    return {
        "ok": False,
        "destino": admin_mail,
        "error": err or "No se pudo enviar. Revisá SMTP_* en Render y los logs del servicio.",
    }


def notificar_admin_nueva_solicitud(
    cuit: str,
    email: str,
    nombre: str = "",
    *,
    telefono_area: str = "",
    telefono_numero: str = "",
    enlace_activacion: str = "",
) -> dict[str, Any]:
    cuit_fmt = formatear_cuit(cuit)
    nom_line = f"Nombre: {nombre}\n" if nombre else ""
    tel_fmt = formatear_telefono(telefono_area, telefono_numero)
    tel_line = f"Teléfono: {tel_fmt}\n" if tel_fmt else ""
    enlace_line = f"\nEnlace de activación (para el cliente):\n{enlace_activacion}\n" if enlace_activacion else ""
    cuerpo = (
        f"Nueva solicitud de acceso en {APP_NAME}.\n\n"
        f"CUIT (usuario): {cuit_fmt}\n"
        f"{nom_line}"
        f"Email de contacto: {email}\n"
        f"{tel_line}\n"
        f"El cliente completó el formulario inicial y debe elegir contraseña con el enlace.\n"
        f"Cuando lo haga, recibirás otro aviso para aprobarlo en el panel «Altas de usuarios»."
        f"{enlace_line}"
    )
    email_ok = _avisar_admin_por_email(
        f"[{APP_NAME}] Nueva solicitud de acceso {cuit_fmt}",
        cuerpo,
        contexto=f"solicitud {cuit_fmt}",
        timeout=_smtp_timeout_background(),
    )
    return {
        "email_enviado": email_ok,
        "whatsapp_url": whatsapp_solicitud_admin_url(cuit, email, nombre),
    }


def notificar_admin_nueva_solicitud_async(**kwargs) -> None:
    _notificar_en_segundo_plano(notificar_admin_nueva_solicitud, **kwargs)


def notificar_admin_alta(cuit: str, email: str, nombre: str = "") -> dict[str, Any]:
    cuit_fmt = formatear_cuit(cuit)
    nom_line = f"Nombre: {nombre}\n" if nombre else ""
    cuerpo = (
        f"Nueva solicitud de alta en {APP_NAME}.\n\n"
        f"CUIT (usuario): {cuit_fmt}\n"
        f"{nom_line}"
        f"Email de contacto: {email}\n\n"
        f"El usuario ya eligió contraseña por enlace.\n"
        f"La cuenta queda PENDIENTE hasta que la apruebes en el panel "
        f"«Altas de usuarios» (después de confirmar el pago).\n"
    )
    email_ok = _avisar_admin_por_email(
        f"[{APP_NAME}] Alta de usuario {cuit_fmt}",
        cuerpo,
        contexto=f"contraseña definida {cuit_fmt}",
        timeout=_smtp_timeout_background(),
    )
    return {
        "email_enviado": email_ok,
        "whatsapp_url": whatsapp_alta_admin_url(cuit, email, nombre),
    }


def notificar_admin_alta_async(cuit: str, email: str, nombre: str = "") -> None:
    _notificar_en_segundo_plano(notificar_admin_alta, cuit, email, nombre)


def notificar_aceptacion_legal(
    cuit: str,
    *,
    email: str = "",
    nombre: str = "",
    version: str = "",
    metodo: str = "",
    ip: str = "",
    aceptada_en: str = "",
    user_agent: str = "",
) -> dict[str, Any]:
    cuit_fmt = formatear_cuit(cuit)
    nom_line = f"Nombre: {nombre}\n" if nombre else ""
    ua_line = f"Navegador: {user_agent[:200]}\n" if user_agent else ""
    cuerpo_admin = (
        f"Aceptación legal registrada en {APP_NAME}.\n\n"
        f"CUIT (usuario): {cuit_fmt}\n"
        f"{nom_line}"
        f"Email de contacto: {email or '—'}\n"
        f"Versión legal: {version or '—'}\n"
        f"Fecha/hora (UTC): {aceptada_en or '—'}\n"
        f"Método: {metodo or '—'}\n"
        f"IP: {ip or '—'}\n"
        f"{ua_line}\n"
        f"Documentos: Términos y condiciones + Política de privacidad.\n"
    )
    admin_ok = _avisar_admin_por_email(
        f"[{APP_NAME}] Aceptación legal {cuit_fmt} (v{version})",
        cuerpo_admin,
        contexto=f"aceptación legal {cuit_fmt}",
        timeout=_smtp_timeout_background(),
    )
    user_ok = False
    destino = (email or "").strip()
    if destino and "@" in destino:
        saludo = f"Hola {nombre},\n\n" if nombre else "Hola,\n\n"
        cuerpo_user = (
            f"{saludo}"
            f"Registramos tu aceptación de los Términos y condiciones y la Política de "
            f"privacidad de {APP_NAME}.\n\n"
            f"Versión: {version or '—'}\n"
            f"Fecha/hora (UTC): {aceptada_en or '—'}\n\n"
            f"Conservá este correo como comprobante de tu consentimiento.\n"
        )
        user_ok, err = _enviar_email(
            destino,
            f"[{APP_NAME}] Confirmación de aceptación legal",
            cuerpo_user,
            timeout=_smtp_timeout_background(),
        )
        if not user_ok:
            _LOG.error(
                "Falló el email de confirmación legal al usuario %s (%s): %s",
                cuit_fmt,
                destino,
                err or "error desconocido",
            )
    return {
        "email_enviado": admin_ok,
        "email_usuario_enviado": user_ok,
    }


def notificar_aceptacion_legal_async(**kwargs) -> None:
    _notificar_en_segundo_plano(notificar_aceptacion_legal, **kwargs)
