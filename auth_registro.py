"""Alta de usuarios por enlace: CUIT como usuario, contraseña elegida por el cliente."""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
import smtplib
import sys
import tempfile
import threading
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any
from urllib.parse import quote

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
    p.mkdir(parents=True, exist_ok=True)
    return p


def _path_solicitudes() -> Path:
    return dir_auth_servidor() / "solicitudes_pendientes.json"


def _path_usuarios_overlay() -> Path:
    return dir_auth_servidor() / "usuarios_registrados.json"


def _path_log_altas() -> Path:
    return dir_auth_servidor() / "altas_completadas.json"


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
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _read_store(name: str, default: Any, path: Path) -> Any:
    try:
        from auth_registro_db import enabled, read_json

        if enabled():
            return read_json(name, default)
    except Exception as exc:
        _LOG.warning("Lectura PostgreSQL falló (%s), usando disco: %s", name, exc)
    return _leer_json(path, default)


def _write_store(name: str, data: Any, path: Path) -> None:
    try:
        from auth_registro_db import enabled, write_json

        if enabled():
            write_json(name, data)
            return
    except Exception as exc:
        _LOG.error("Escritura PostgreSQL falló (%s): %s", name, exc)
        try:
            from auth_registro_db import enabled as db_on

            if db_on():
                raise RuntimeError(
                    "DATABASE_URL configurada pero no se pudo escribir en PostgreSQL. "
                    "Revisá la conexión Neon en Render."
                ) from exc
        except RuntimeError:
            raise
        except Exception:
            pass
        _LOG.warning("Escritura en disco local como respaldo (%s)", name)
    _escribir_json(path, data)


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
    data = _read_store("usuarios_registrados", {"users": {}}, _path_usuarios_overlay())
    users = data.get("users") if isinstance(data, dict) else {}
    return users if isinstance(users, dict) else {}


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


def _cargar_solicitudes() -> dict[str, Any]:
    data = _read_store("solicitudes_pendientes", {"solicitudes": {}}, _path_solicitudes())
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
    if usuario_existe(u):
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
        _write_store("solicitudes_pendientes", data, _path_solicitudes())

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


def activar_cuenta(token: str, password: str) -> dict[str, Any]:
    tok = (token or "").strip()
    pwd = password or ""
    if len(pwd) < _min_password_len():
        raise ValueError("password_corta")

    with _lock:
        sol = obtener_solicitud(tok)
        if not sol:
            raise ValueError("token_invalido")
        cuit = str(sol["cuit"])
        if usuario_existe(cuit):
            raise ValueError("cuit_duplicado")

        overlay_path = _path_usuarios_overlay()
        overlay = _read_store("usuarios_registrados", {"version": 1, "users": {}}, overlay_path)
        if not isinstance(overlay.get("users"), dict):
            overlay["users"] = {}
        overlay["users"][cuit] = {
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
        overlay["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        _write_store("usuarios_registrados", overlay, overlay_path)

        data = _cargar_solicitudes()
        if tok in data.get("solicitudes", {}):
            data["solicitudes"][tok]["usado"] = True
            data["solicitudes"][tok]["activado"] = datetime.now(timezone.utc).isoformat(
                timespec="seconds"
            )
            try:
                _write_store("solicitudes_pendientes", data, _path_solicitudes())
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
    if usuario_existe(u):
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
        path = _path_usuarios_overlay()
        overlay = _read_store("usuarios_registrados", {"version": 1, "users": {}}, path)
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
        }
        overlay["updated_at"] = ahora
        _write_store("usuarios_registrados", overlay, path)

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
    u = resolver_clave_overlay(cuit)
    if not u:
        return False
    dias = _dias_suscripcion()
    hoy = date.today()
    valido_hasta = hoy + timedelta(days=dias)
    with _lock:
        path = _path_usuarios_overlay()
        overlay = _read_store("usuarios_registrados", {"version": 1, "users": {}}, path)
        users = overlay.get("users")
        if not isinstance(users, dict) or u not in users:
            return False
        users[u]["activo"] = True
        users[u]["pendiente_aprobacion"] = False
        users[u]["valido_desde"] = hoy.isoformat()
        users[u]["valido_hasta"] = valido_hasta.isoformat()
        users[u]["aprobado_en"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        overlay["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        _write_store("usuarios_registrados", overlay, path)
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
        overlay["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        _write_store("usuarios_registrados", overlay, path)
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
    return {
        "valido_hasta": cuenta.valido_hasta,
        "valido_hasta_fmt": cuenta.valido_hasta.strftime("%d/%m/%Y"),
        "dias_restantes": dias,
    }


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
    data = _read_store("altas_completadas", {"altas": []}, _path_log_altas())
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
    flag = (os.environ.get("SMTP_USE_SSL") or "").strip().lower()
    if flag in ("1", "true", "yes", "on"):
        return True
    if flag in ("0", "false", "no", "off"):
        return False
    return port == 465


def _enviar_email(destino: str, asunto: str, cuerpo: str) -> bool:
    host = (os.environ.get("SMTP_HOST") or "").strip()
    user = (os.environ.get("SMTP_USER") or "").strip()
    # Gmail muestra la contraseña de aplicación con espacios; SMTP exige 16 caracteres seguidos.
    password = re.sub(r"\s+", "", (os.environ.get("SMTP_PASSWORD") or ""))
    port_raw = (os.environ.get("SMTP_PORT") or "587").strip()
    if not host:
        _LOG.warning("SMTP_HOST no configurado; email no enviado")
        return False
    if not destino:
        _LOG.warning("Destino de email vacío; no enviado")
        return False
    if not user or not password:
        _LOG.warning("SMTP_USER o SMTP_PASSWORD faltante; email a %s no enviado", destino)
        return False
    try:
        port = int(port_raw)
    except ValueError:
        port = 587
    remitente = (os.environ.get("SMTP_FROM") or user or f"noreply@{host}").strip()
    msg = EmailMessage()
    msg["Subject"] = asunto
    msg["From"] = remitente
    msg["To"] = destino
    msg.set_content(cuerpo)
    try:
        if _smtp_usar_ssl(port):
            with smtplib.SMTP_SSL(host, port, timeout=30) as smtp:
                smtp.login(user, password)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=30) as smtp:
                smtp.ehlo()
                if port != 25:
                    smtp.starttls()
                    smtp.ehlo()
                smtp.login(user, password)
                smtp.send_message(msg)
        _LOG.info("Email enviado a %s (asunto: %s)", destino, asunto)
        return True
    except Exception as exc:
        _LOG.error("No se pudo enviar email a %s: %s", destino, exc)
        return False


def _email_admin_configurado() -> str:
    return (os.environ.get("AUTH_ADMIN_NOTIFY_EMAIL") or "").strip()


def _avisar_admin_por_email(asunto: str, cuerpo: str, *, contexto: str) -> bool:
    admin_mail = _email_admin_configurado()
    if not admin_mail:
        _LOG.warning(
            "AUTH_ADMIN_NOTIFY_EMAIL no configurado; no se envía email (%s)",
            contexto,
        )
        return False
    ok = _enviar_email(admin_mail, asunto, cuerpo)
    if not ok:
        _LOG.error(
            "Falló el email (%s) hacia %s (revisá SMTP_* en Render)",
            contexto,
            admin_mail,
        )
    return ok


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
    )
    return {
        "email_enviado": email_ok,
        "whatsapp_url": whatsapp_solicitud_admin_url(cuit, email, nombre),
    }


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
    )
    return {
        "email_enviado": email_ok,
        "whatsapp_url": whatsapp_alta_admin_url(cuit, email, nombre),
    }
