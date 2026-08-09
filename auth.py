"""Usuarios y contraseñas: variable de entorno, archivo local, URL remota o respaldo.

Modos (por prioridad):

1. **Render / servidor:** ``AUTH_USERS_JSON`` con el listado completo (fuera del repo).

2. **Remoto (portables):** ``AUTH_USERS_URL`` o ``auth_remote.enc`` / ``auth_remote.txt`` junto al .exe.
   Descarga el JSON por HTTPS, lo guarda en caché fuera de la carpeta del sistema.

3. **Archivo local externo:** ``AUTH_USERS_PATH`` apunta a un JSON fuera del proyecto.

4. **Archivo local cifrado (portable):** ``auth_users.enc`` junto al .exe (generado con
   ``python tools/encrypt_auth_users.py``). No incluir JSON en claro en la distribución.

5. **Desarrollo:** ``auth_users.json`` en la raíz (no commitear; ver ``auth_users.example.json``).

6. **Respaldo:** ``AUTH_ADMIN_USER`` y ``AUTH_ADMIN_PASSWORD`` en el entorno.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from app_branding import APP_NAME, RENDER_PUBLIC_URL

_AUTH_DIR = Path(__file__).resolve().parent
_LOG = logging.getLogger(__name__)

_lock = threading.Lock()
_cache_usuarios: dict[str, "CuentaUsuario"] | None = None
_cache_obtenido_en: float = 0.0
_sync_iniciado = False

_DEFAULT_REFRESH_SEC = 120


@dataclass
class CuentaUsuario:
    password: str
    valido_desde: date | None = None
    valido_hasta: date | None = None
    es_admin: bool = False

    def a_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"password": self.password}
        if self.es_admin:
            d["rol"] = "admin"
        if self.valido_desde:
            d["valido_desde"] = self.valido_desde.isoformat()
        if self.valido_hasta:
            d["valido_hasta"] = self.valido_hasta.isoformat()
        return d


def _parse_fecha(val: Any) -> date | None:
    if val is None:
        return None
    if isinstance(val, date) and not isinstance(val, datetime):
        return val
    s = str(val).strip()
    if not s:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _motivo_vigencia(cuenta: CuentaUsuario, hoy: date | None = None) -> str | None:
    """None = vigente; si no, 'not_yet' o 'expired'."""
    hoy = hoy or date.today()
    if cuenta.valido_desde and hoy < cuenta.valido_desde:
        return "not_yet"
    if cuenta.valido_hasta and hoy > cuenta.valido_hasta:
        return "expired"
    return None


def _parse_cuentas(raw: dict) -> dict[str, CuentaUsuario]:
    out: dict[str, CuentaUsuario] = {}
    for k, v in (raw or {}).items():
        ks = str(k).strip()
        if not ks:
            continue
        if isinstance(v, dict):
            if v.get("activo") is False:
                continue
            pwd = str(v.get("password") or v.get("clave") or "").strip()
            if not pwd:
                continue
            rol = str(v.get("rol") or "").strip().lower()
            es_admin = (
                rol == "admin"
                or v.get("es_admin") is True
                or v.get("admin") is True
            )
            out[ks] = CuentaUsuario(
                password=pwd,
                valido_desde=_parse_fecha(v.get("valido_desde")),
                valido_hasta=_parse_fecha(v.get("valido_hasta")),
                es_admin=es_admin,
            )
        else:
            pwd = str(v).strip() if v is not None else ""
            if pwd:
                out[ks] = CuentaUsuario(password=pwd)
    return out


def _parse_users_payload(data: Any) -> dict[str, CuentaUsuario]:
    if not isinstance(data, dict):
        return {}
    users = data.get("users") if "users" in data else data
    if not isinstance(users, dict):
        return {}
    return _parse_cuentas(users)


def _cuentas_a_dict(cuentas: dict[str, CuentaUsuario]) -> dict[str, Any]:
    return {u: c.a_dict() for u, c in cuentas.items()}


def _dir_datos_usuario() -> Path:
    override = (os.environ.get("AUTH_DATA_DIR") or "").strip()
    if override:
        return Path(override)
    if getattr(sys, "frozen", False):
        red = _ruta_remota_desde_archivo_junto_exe()
        if red is not None:
            return red
        local = os.environ.get("LOCALAPPDATA")
        if local:
            return Path(local) / "DepuracionExcelComprobantes"
        return Path.home() / "AppData" / "Local" / "DepuracionExcelComprobantes"
    return _AUTH_DIR / "data_local_auth"


def _ruta_remota_desde_archivo_junto_exe() -> Path | None:
    """``auth_data_dir.txt`` al lado del .exe: carpeta base para la caché de usuarios."""
    if not getattr(sys, "frozen", False):
        return None
    p = Path(sys.executable).resolve().parent / "auth_data_dir.txt"
    if not p.is_file():
        return None
    try:
        for raw in p.read_text(encoding="utf-8").splitlines():
            s = raw.strip()
            if s and not s.startswith("#"):
                return Path(s)
    except OSError:
        return None
    return None


def _dir_exe_portable() -> Path | None:
    if not getattr(sys, "frozen", False):
        return None
    return Path(sys.executable).resolve().parent


def _candidatos_auth_remote(nombre: str) -> list[Path]:
    """Rutas posibles de auth_remote (.enc / .txt): junto al .exe y raíz del proyecto."""
    out: list[Path] = []
    exe_dir = _dir_exe_portable()
    if exe_dir is not None:
        out.append(exe_dir / nombre)
    out.append(_AUTH_DIR / nombre)
    # Deduplicar conservando orden
    vistos: set[str] = set()
    unicos: list[Path] = []
    for p in out:
        key = str(p.resolve()) if p.exists() else str(p)
        if key in vistos:
            continue
        vistos.add(key)
        unicos.append(p)
    return unicos


def _auth_remote_txt() -> Path | None:
    for p in _candidatos_auth_remote("auth_remote.txt"):
        if p.is_file():
            return p
    return None


def _auth_remote_enc() -> Path | None:
    for p in _candidatos_auth_remote("auth_remote.enc"):
        if p.is_file():
            return p
    return None


def _leer_auth_remote_desde_txt(path: Path) -> tuple[str, str]:
    """Primera línea = URL; segunda línea opcional = token Bearer."""
    if not path.is_file():
        return "", ""
    try:
        lineas = [
            ln.strip()
            for ln in path.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.strip().startswith("#")
        ]
    except OSError:
        return "", ""
    url = lineas[0] if lineas else ""
    token = lineas[1] if len(lineas) > 1 else ""
    return url, token


def _leer_auth_remote_config() -> tuple[str, str]:
    """URL + token: preferir ``auth_remote.enc``; respaldo ``auth_remote.txt``."""
    enc_path = _auth_remote_enc()
    if enc_path is not None:
        from auth_crypto import AuthStoreCorruptError, descifrar_bytes

        try:
            blob = enc_path.read_bytes()
        except OSError:
            return "", ""
        data = descifrar_bytes(blob)
        if data is None:
            raise AuthStoreCorruptError(
                "No se pudo verificar auth_remote.enc (alterado o dañado)."
            )
        return (
            str(data.get("url") or "").strip(),
            str(data.get("token") or "").strip(),
        )
    txt_path = _auth_remote_txt()
    if txt_path is not None:
        return _leer_auth_remote_desde_txt(txt_path)
    return "", ""


def _leer_auth_remote_txt() -> tuple[str, str]:
    return _leer_auth_remote_config()


def _remote_url() -> str:
    url = (os.environ.get("AUTH_USERS_URL") or "").strip()
    if url:
        return url
    url_txt, _ = _leer_auth_remote_txt()
    return url_txt


def _normalizar_token_remoto(token: str) -> str:
    t = (token or "").strip()
    if t.lower().startswith("bearer "):
        t = t[7:].strip()
    return t


def _remote_token() -> str:
    """Token actual (el primero de ``_remote_tokens``)."""
    tokens = _remote_tokens()
    return tokens[0] if tokens else ""


def _remote_tokens() -> list[str]:
    """Tokens Bearer válidos: actual + opcional ``AUTH_USERS_REMOTE_TOKEN_PREVIOUS``.

    Durante una rotación, en Render poné el nuevo en ``AUTH_USERS_REMOTE_TOKEN``
    y el viejo en ``AUTH_USERS_REMOTE_TOKEN_PREVIOUS`` hasta redistribuir portables.
    """
    vistos: list[str] = []
    for raw in (
        os.environ.get("AUTH_USERS_REMOTE_TOKEN") or "",
        os.environ.get("AUTH_USERS_REMOTE_TOKEN_PREVIOUS") or "",
    ):
        t = _normalizar_token_remoto(raw)
        if t and t not in vistos:
            vistos.append(t)
    if not vistos:
        _, token_txt = _leer_auth_remote_txt()
        t = _normalizar_token_remoto(token_txt)
        if t:
            vistos.append(t)
    return vistos


def _refresh_sec() -> int:
    raw = (os.environ.get("AUTH_USERS_REFRESH_SEC") or "").strip()
    try:
        sec = int(raw)
        return max(30, sec)
    except ValueError:
        return _DEFAULT_REFRESH_SEC


def _hosts_este_servidor() -> set[str]:
    hosts: set[str] = set()
    for raw in (
        os.environ.get("RENDER_EXTERNAL_URL") or "",
        os.environ.get("RENDER_EXTERNAL_HOSTNAME") or "",
        RENDER_PUBLIC_URL,
    ):
        v = (raw or "").strip()
        if not v:
            continue
        if "://" not in v:
            v = "https://" + v
        host = (urlparse(v).hostname or "").strip().lower()
        if host:
            hosts.add(host)
    return hosts


def _url_remota_apunta_a_este_servidor(url: str) -> bool:
    """True si AUTH_USERS_URL es este mismo Render (evitar deadlock 1-worker)."""
    host = (urlparse((url or "").strip()).hostname or "").strip().lower()
    if not host:
        return False
    if host in _hosts_este_servidor():
        return True
    # Heurística: hostname típico de este servicio en Render.
    return host.endswith(".onrender.com") and "analisisdelcontribuyente" in host


def _modo_remoto_activo() -> bool:
    """Remoto para portables/clientes locales.

    En Render el servidor es la fuente (Neon): no sincroniza desde AUTH_USERS_URL.
    Importante: NO desactivar solo porque la URL sea *.onrender.com — eso rompe el
    login local/portable de usuarios Estudio DyC y demás altas en Neon.
    """
    url = _remote_url()
    if not url:
        return False
    # Solo cuando este proceso ES el servidor web en Render.
    if (os.environ.get("RENDER") or "").strip():
        return False
    return True


def _auth_users_file() -> Path:
    override = (os.environ.get("AUTH_USERS_PATH") or "").strip()
    if override:
        return Path(override)
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        for name in ("auth_users.enc", "auth_users.json"):
            portable = exe_dir / name
            if portable.is_file():
                return portable
        return exe_dir / "auth_users.enc"
    for name in ("auth_users.enc", "auth_users.json"):
        local = _AUTH_DIR / name
        if local.is_file():
            return local
    return _AUTH_DIR / "auth_users.json"


def _cache_path() -> Path:
    override = (os.environ.get("AUTH_USERS_CACHE_PATH") or "").strip()
    if override:
        return Path(override)
    return _dir_datos_usuario() / "auth" / "auth_users_cache.enc"


def _normalizar_usuarios(raw: dict) -> dict[str, str]:
    """Compatibilidad: usuario -> contraseña (solo cuentas vigentes)."""
    cuentas = _parse_cuentas(raw)
    return {
        u: c.password
        for u, c in cuentas.items()
        if _motivo_vigencia(c) is None
    }


def _leer_json_archivo(path: Path) -> dict[str, CuentaUsuario]:
    if not path.is_file():
        return {}
    try:
        from auth_crypto import leer_archivo_usuarios

        data = leer_archivo_usuarios(path)
        if not data:
            _LOG.warning("No se pudo leer usuarios en %s", path)
            return {}
        return _parse_users_payload(data)
    except Exception as exc:
        _LOG.warning("Error al leer usuarios en %s: %s", path, exc)
    return {}


def _guardar_cache(cuentas: dict[str, CuentaUsuario], *, origen: str, meta: dict[str, Any] | None = None) -> None:
    from auth_crypto import escribir_archivo_cifrado

    path = _cache_path()
    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "origen": origen,
        "users": _cuentas_a_dict(cuentas),
    }
    if meta:
        payload["meta"] = meta
    escribir_archivo_cifrado(path, payload)


def _leer_cache() -> tuple[dict[str, CuentaUsuario], float]:
    from auth_crypto import leer_archivo_usuarios

    path = _cache_path()
    legacy = path.with_name("auth_users_cache.json")
    for candidato in (path, legacy):
        if not candidato.is_file():
            continue
        try:
            data = leer_archivo_usuarios(candidato)
            if not data:
                continue
            cuentas = _parse_users_payload(data)
            fetched_at = 0.0
            raw_ts = data.get("fetched_at")
            if raw_ts:
                try:
                    dt = datetime.fromisoformat(str(raw_ts).replace("Z", "+00:00"))
                    fetched_at = dt.timestamp()
                except ValueError:
                    fetched_at = candidato.stat().st_mtime
            else:
                fetched_at = candidato.stat().st_mtime
            return cuentas, fetched_at
        except Exception as exc:
            from auth_crypto import AuthStoreCorruptError

            if isinstance(exc, AuthStoreCorruptError):
                try:
                    from auth_registro import _marcar_integridad_fallida

                    _marcar_integridad_fallida(str(exc))
                except Exception:
                    pass
                return {}, 0.0
            if isinstance(exc, OSError):
                _LOG.warning("Caché de usuarios inválida en %s: %s", candidato, exc)
    return {}, 0.0


def _fetch_remoto() -> tuple[dict[str, CuentaUsuario], dict[str, Any] | None]:
    url = _remote_url()
    if not url:
        return {}, None
    if not url.lower().startswith("https://"):
        _LOG.warning("AUTH_USERS_URL debe usar HTTPS: %s", url)
        return {}, None

    headers = {"User-Agent": f"{APP_NAME}/auth-sync", "Accept": "application/json"}
    token = _remote_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = Request(url, headers=headers, method="GET")
    try:
        with urlopen(req, timeout=20) as resp:
            raw = resp.read()
        data = json.loads(raw.decode("utf-8-sig"))
        if isinstance(data, dict) and data.get("error") in ("gone", "disabled"):
            _LOG.info(
                "Sync /api/auth-users deshabilitado en servidor; login vía /api/auth/verificar."
            )
            return {}, None
        cuentas = _parse_users_payload(data)
        if not cuentas:
            _LOG.debug("Listado remoto de usuarios vacío (%s)", url)
            return {}, data if isinstance(data, dict) else None
        meta = data if isinstance(data, dict) else None
        return cuentas, meta
    except HTTPError as exc:
        if exc.code in (404, 410):
            _LOG.info(
                "HTTP %s en listado remoto (deshabilitado); usar /api/auth/verificar.",
                exc.code,
            )
        else:
            _LOG.warning("HTTP %s al descargar usuarios remotos: %s", exc.code, url)
    except URLError as exc:
        _LOG.warning("Sin conexión al listado remoto de usuarios: %s", exc.reason)
    except (json.JSONDecodeError, TimeoutError, OSError, ValueError) as exc:
        _LOG.warning("Error al descargar usuarios remotos: %s", exc)
    return {}, None


_OVERLAY_SYNC_KEYS = (
    "password",
    "email",
    "nombre",
    "telefono_area",
    "telefono_numero",
    "valido_desde",
    "valido_hasta",
    "activo",
    "pendiente_aprobacion",
    "cuit_limite",
    "cuit_usados",
    "rol",
    "es_admin",
    "admin",
    "uso_mce_comprobantes",
    "uso_mcr_comprobantes",
    "uso_dfe_notificaciones",
    "uso_vl_cuits",
    "uso_np_cuits",
    "uso_por_mes",
    "servicios",
    "grupo",
    "legal_aceptacion",
)


def _sync_overlay_cupo_desde_remoto(payload: dict[str, Any] | None) -> None:
    """Portable: refleja cupo y suscripción del servidor en usuarios_registrados local."""
    if not isinstance(payload, dict):
        return
    remoto = payload.get("users")
    if not isinstance(remoto, dict) or not remoto:
        return
    try:
        from auth_registro import (
            _cargar_overlay_completo,
            _guardar_overlay_completo,
            _inicializar_cupo_meta,
            _lock,
            meta_es_admin,
        )
    except Exception:
        _LOG.debug("Sync overlay cupo omitido (auth_registro no disponible)", exc_info=True)
        return

    with _lock:
        overlay = _cargar_overlay_completo()
        users = overlay.get("users")
        if not isinstance(users, dict):
            overlay["users"] = {}
            users = overlay["users"]
        changed = False
        for clave, meta in remoto.items():
            if not isinstance(meta, dict):
                continue
            if meta.get("pendiente_aprobacion") or meta.get("activo") is False:
                if not meta_es_admin(meta):
                    continue
            dest = users.get(clave)
            if not isinstance(dest, dict):
                dest = {}
                users[clave] = dest
            for key in _OVERLAY_SYNC_KEYS:
                if key in meta:
                    dest[key] = meta[key]
            _inicializar_cupo_meta(dest)
            changed = True
        if changed:
            _guardar_overlay_completo(overlay)
            _LOG.info(
                "Overlay de cupo sincronizado desde servidor (%d usuario(s)).",
                len(remoto),
            )


def _leer_payload_env_json() -> dict[str, Any] | None:
    raw = (os.environ.get("AUTH_USERS_JSON") or "").strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        _LOG.warning("AUTH_USERS_JSON inválido: %s", exc)
        return None
    return data if isinstance(data, dict) else None


def _usuarios_desde_env_json() -> dict[str, CuentaUsuario]:
    data = _leer_payload_env_json()
    if not data:
        return {}
    return _parse_users_payload(data)


def _modo_env_json_activo() -> bool:
    return bool((os.environ.get("AUTH_USERS_JSON") or "").strip())


_CAMPOS_SECRETOS_USUARIO = frozenset(
    {"password", "clave", "password_hash", "pwd", "password_definida"}
)


def _meta_sin_secretos(meta: dict[str, Any]) -> dict[str, Any]:
    """Copia pública para sync portable: sin material de contraseña."""
    return {k: v for k, v in meta.items() if k not in _CAMPOS_SECRETOS_USUARIO}


def export_users_payload() -> dict[str, Any]:
    """Metadatos de usuarios para sync de portables (sin passwords/hashes)."""
    data = _leer_payload_env_json()
    if data:
        payload = json.loads(json.dumps(data))  # copia profunda simple
    else:
        cuentas = _load_cuentas_sin_env_json()
        payload = {
            "version": 1,
            "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "users": {u: c.a_dict() for u, c in cuentas.items()},
        }
    try:
        from auth_registro import cargar_usuarios_overlay, meta_es_admin

        overlay = cargar_usuarios_overlay()
        if overlay:
            users = payload.setdefault("users", {})
            if isinstance(users, dict):
                for u, meta in overlay.items():
                    if not isinstance(meta, dict):
                        continue
                    if meta.get("pendiente_aprobacion") or meta.get("activo") is False:
                        if not meta_es_admin(meta):
                            continue
                    # Neon es fuente de verdad: siempre pisa AUTH_USERS_JSON legacy.
                    users[u] = meta
    except Exception:
        pass
    users = payload.get("users")
    if isinstance(users, dict):
        payload["users"] = {
            u: _meta_sin_secretos(m) if isinstance(m, dict) else m for u, m in users.items()
        }
    payload["credentials_omitted"] = True
    return payload


def verificar_token_remoto(auth_header: str | None) -> bool:
    """True si el Bearer es el token global de sync o un token de dispositivo."""
    try:
        from auth_dispositivos import resolver_autorizacion_api

        return resolver_autorizacion_api(auth_header) is not None
    except Exception:
        import hmac

        tokens = _remote_tokens()
        if not tokens or not auth_header:
            return False
        header = auth_header.strip()
        for expected in tokens:
            if hmac.compare_digest(header, f"Bearer {expected}"):
                return True
        return False


# Tokens de dispositivo emitidos por /api/auth/verificar (portable → cupo/uso).
_device_tokens_sesion: dict[str, str] = {}


def recordar_device_token(usuario: str, token: str) -> None:
    u = (usuario or "").strip()
    t = (token or "").strip()
    if u and t:
        _device_tokens_sesion[u] = t


def token_api_para_usuario(usuario: str | None = None) -> str:
    """Preferir token de dispositivo del usuario; si no, Bearer global de sync."""
    u = (usuario or "").strip()
    if u:
        t = (_device_tokens_sesion.get(u) or "").strip()
        if t:
            return t
    return _remote_token()


def _url_api_auth_verificar() -> str:
    """Deriva /api/auth/verificar desde AUTH_USERS_URL (.../api/auth-users)."""
    base = (_remote_url() or "").rstrip("/")
    if not base:
        return ""
    if base.endswith("/api/auth-users"):
        return base[: -len("/auth-users")] + "/auth/verificar"
    if base.endswith("/auth-users"):
        return base[: -len("/auth-users")] + "/auth/verificar"
    return base.rsplit("/", 1)[0] + "/auth/verificar"


def _intentar_verificar_remoto(
    username: str, password: str
) -> tuple[bool, str | None] | None:
    """Verifica credenciales contra el servidor.

    Returns:
        (True, None) acceso OK;
        (False, motivo) rechazado;
        None si no hay red / endpoint no disponible (usar fallback local).
    """
    verify_url = _url_api_auth_verificar()
    if not verify_url.lower().startswith("https://"):
        return None
    token = _remote_token()
    if not token:
        return None
    device_id = ""
    public_key = ""
    etiqueta = "portable"
    try:
        from auth_instalacion import etiqueta_instalacion, identidad_instalacion

        ident = identidad_instalacion()
        device_id = ident.get("device_id") or ""
        public_key = ident.get("public_key") or ""
        etiqueta = etiqueta_instalacion()
    except Exception:
        _LOG.debug("Sin identidad de instalación local", exc_info=True)
    integridad: dict[str, Any] = {}
    try:
        from auth_manifest import payload_telemetria

        integridad = payload_telemetria()
    except Exception:
        _LOG.debug("Sin telemetría de manifiesto", exc_info=True)
    body = json.dumps(
        {
            "usuario": (username or "").strip(),
            "password": password or "",
            "device_id": device_id,
            "public_key": public_key,
            "etiqueta": etiqueta,
            "integridad": integridad,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    headers = {
        "User-Agent": f"{APP_NAME}/auth-verify",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    req = Request(verify_url, data=body, headers=headers, method="POST")
    try:
        with urlopen(req, timeout=20) as resp:
            raw = resp.read()
        data = json.loads(raw.decode("utf-8-sig"))
    except HTTPError as exc:
        payload: dict[str, Any] | None = None
        try:
            payload = json.loads(exc.read().decode("utf-8-sig"))
            if not isinstance(payload, dict):
                payload = None
        except Exception:
            payload = None
        # Rate-limit del servidor: no hacer fallback local (el bloqueo debe valer en portable).
        if exc.code == 429 or (payload and payload.get("error") == "rate_limit"):
            return False, "rate_limit"
        if exc.code == 404:
            _LOG.warning("Servidor sin /api/auth/verificar; usar caché local si existe")
            return None
        # 401 con cuerpo de verificación = credencial/estado rechazado (no es fallo de red).
        if exc.code in (401, 403) and payload is not None:
            if payload.get("error") == "unauthorized":
                _LOG.warning(
                    "Token remoto rechazado en /api/auth/verificar (%s)", exc.code
                )
                return None
            return False, str(payload.get("motivo") or "invalid")
        if exc.code in (401, 403):
            _LOG.warning("Token remoto rechazado en /api/auth/verificar (%s)", exc.code)
            return None
        if payload and payload.get("motivo"):
            return False, str(payload.get("motivo") or "invalid")
        return False, "invalid"
    except (URLError, TimeoutError, OSError, json.JSONDecodeError, ValueError) as exc:
        _LOG.warning("No se pudo verificar acceso remoto: %s", exc)
        return None
    if not isinstance(data, dict):
        return False, "invalid"
    if data.get("error") == "rate_limit":
        return False, "rate_limit"
    if data.get("ok") is True:
        clave = (data.get("usuario") or username or "").strip()
        device = (data.get("device_token") or "").strip()
        if device and clave:
            recordar_device_token(clave, device)
        ent_blob = data.get("entitlement_signed")
        if isinstance(ent_blob, dict) and clave:
            try:
                from auth_entitlements import guardar_entitlement_local

                guardar_entitlement_local(clave, ent_blob)
            except Exception:
                _LOG.debug("No se pudo guardar entitlement del login remoto", exc_info=True)
        perfil = data.get("perfil")
        if isinstance(perfil, dict) and clave:
            try:
                _sync_overlay_cupo_desde_remoto({"users": {clave: perfil}})
            except Exception:
                _LOG.debug("No se pudo sync perfil post-login", exc_info=True)
        return True, None
    return False, str(data.get("motivo") or "invalid")


def es_administrador(username: str) -> bool:
    u = (username or "").strip()
    if not u:
        return False
    cuenta = _load_cuentas().get(u)
    if cuenta and cuenta.es_admin:
        return True
    admin_env = (os.environ.get("AUTH_ADMIN_USER") or "").strip()
    return bool(admin_env and u == admin_env)


def _usuarios_desde_entorno() -> dict[str, CuentaUsuario]:
    u = (os.environ.get("AUTH_ADMIN_USER") or "").strip()
    p = (os.environ.get("AUTH_ADMIN_PASSWORD") or "").strip()
    if u and p:
        return {u: CuentaUsuario(password=p, es_admin=True)}
    return {}


def _cuentas_archivo_local() -> dict[str, CuentaUsuario]:
    """Usuarios en auth_users.enc / .json (junto al .exe en portable o raíz en dev)."""
    path = _auth_users_file()
    if not path.is_file():
        return {}
    return _leer_json_archivo(path)


def _fusionar_cuentas(
    preferente: dict[str, CuentaUsuario],
    base: dict[str, CuentaUsuario],
) -> dict[str, CuentaUsuario]:
    """Combina listados; ``preferente`` pisa las claves de ``base``.

    Con sync remoto activo el servidor (caché) es preferente frente a
    ``auth_users.enc`` local, para vigencia/rol/cupo.
    """
    if not preferente:
        return dict(base)
    if not base:
        return dict(preferente)
    return {**base, **preferente}


def _load_cuentas_sin_env_json() -> dict[str, CuentaUsuario]:
    global _cache_usuarios

    locales = _cuentas_archivo_local()

    if _modo_remoto_activo():
        with _lock:
            if _cache_usuarios:
                # Servidor/caché pisa auth_users.enc local.
                return _fusionar_cuentas(_cache_usuarios, locales)
        remotos = _actualizar_cache_remota()
        if remotos:
            return _fusionar_cuentas(remotos, locales)
        if locales:
            return dict(locales)
        fallback = _usuarios_desde_entorno()
        if fallback:
            return _fusionar_cuentas(fallback, locales)
        return {}

    if locales:
        return locales
    return _usuarios_desde_entorno()


def _actualizar_cache_remota(*, forzar: bool = False) -> dict[str, CuentaUsuario]:
    global _cache_usuarios, _cache_obtenido_en

    if not _modo_remoto_activo():
        return {}

    ahora = time.time()
    with _lock:
        if (
            not forzar
            and _cache_usuarios
            and (ahora - _cache_obtenido_en) < _refresh_sec()
        ):
            return dict(_cache_usuarios)

    cuentas, meta = _fetch_remoto()
    locales = _cuentas_archivo_local()
    if cuentas:
        merged = _fusionar_cuentas(cuentas, locales)
        _guardar_cache(merged, origen=_remote_url(), meta=meta)
        _sync_overlay_cupo_desde_remoto(meta)
        with _lock:
            _cache_usuarios = merged
            _cache_obtenido_en = time.time()
        _LOG.info(
            "Usuarios remotos actualizados (%d remoto(s), %d local(es), %d total)",
            len(cuentas),
            len(locales),
            len(merged),
        )
        return dict(merged)

    cache, fetched_at = _leer_cache()
    if cache:
        merged = _fusionar_cuentas(cache, locales)
        with _lock:
            _cache_usuarios = merged
            _cache_obtenido_en = fetched_at or time.time()
        _LOG.info("Usando caché local de usuarios (%d cuenta(s))", len(merged))
        return dict(merged)

    if locales:
        with _lock:
            _cache_usuarios = dict(locales)
            _cache_obtenido_en = time.time()
        _LOG.info(
            "Sin sync remoto; login con auth_users.enc junto al .exe (%d cuenta(s))",
            len(locales),
        )
        return dict(locales)

    return {}


def _loop_sincronizacion() -> None:
    while True:
        try:
            if _modo_remoto_activo():
                _actualizar_cache_remota(forzar=True)
        except Exception:
            _LOG.exception("Error en sincronización de usuarios")
        time.sleep(_refresh_sec())


def forzar_sync_usuarios_remoto() -> bool:
    """Sincroniza usuarios + overlay de cupo desde el servidor (portables)."""
    if not _modo_remoto_activo():
        return False
    return bool(_actualizar_cache_remota(forzar=True))


def iniciar_sincronizacion_usuarios() -> None:
    """Arranca la actualización periódica del listado remoto (idempotente)."""
    global _sync_iniciado
    if _sync_iniciado or not _modo_remoto_activo():
        return
    _sync_iniciado = True
    _actualizar_cache_remota(forzar=True)
    t = threading.Thread(
        target=_loop_sincronizacion,
        daemon=True,
        name="auth-users-sync",
    )
    t.start()


def estado_auth() -> dict[str, Any]:
    """Resumen del origen de credenciales (útil para diagnóstico)."""
    remoto = _modo_remoto_activo()
    env_json = _modo_env_json_activo()
    cache_users, cache_ts = _leer_cache()
    with _lock:
        memoria = len(_cache_usuarios or {})
    return {
        "modo_env_json": env_json,
        "modo_remoto": remoto,
        "url_remota": _remote_url() if remoto else "",
        "archivo_local": str(_auth_users_file()) if _auth_users_file().is_file() else "",
        "archivo_local_cuentas": len(_cuentas_archivo_local()),
        "archivo_cifrado": _auth_users_file().suffix.lower() == ".enc",
        "cache_path": str(_cache_path()),
        "cache_cuentas": len(cache_users),
        "cache_actualizado": (
            datetime.fromtimestamp(cache_ts, tz=timezone.utc).isoformat(timespec="seconds")
            if cache_ts
            else None
        ),
        "memoria_cuentas": memoria,
        "refresh_sec": _refresh_sec(),
    }


def _load_cuentas() -> dict[str, CuentaUsuario]:
    env_cuentas = _usuarios_desde_env_json()
    base = env_cuentas if env_cuentas else _load_cuentas_sin_env_json()
    locales = _cuentas_archivo_local()
    remoto = _modo_remoto_activo()
    try:
        from auth_registro import cargar_usuarios_overlay, meta_es_admin

        overlay = cargar_usuarios_overlay()
        if overlay:
            for u, meta in overlay.items():
                if not isinstance(meta, dict):
                    continue
                parsed = _parse_cuentas({u: meta})
                cuenta = parsed.get(u)
                if not cuenta:
                    continue
                # Con sync: overlay (reflejo del servidor) manda. Sin sync: admin o altas nuevas.
                if remoto or u not in base or meta_es_admin(meta):
                    base[u] = cuenta
    except Exception:
        _LOG.debug("Overlay de usuarios registrados no disponible", exc_info=True)
    if locales:
        if remoto:
            # Solo cuentas exclusivas del .enc local (p. ej. admin de fábrica no en Neon).
            for u, cuenta in locales.items():
                if u not in base:
                    base[u] = cuenta
        else:
            for u, cuenta in locales.items():
                base[u] = cuenta
    return base


def load_users() -> dict[str, str]:
    """Devuelve mapa usuario -> contraseña (solo cuentas vigentes)."""
    return {
        u: c.password
        for u, c in _load_cuentas().items()
        if _motivo_vigencia(c) is None
    }


def _resolver_clave_usuario(username: str) -> str:
    u = (username or "").strip()
    if not u:
        return u
    # Primero sin Neon (AUTH_USERS_JSON / admin / archivo): evita colgar el login.
    try:
        env = _usuarios_desde_env_json()
        base = env if env else _load_cuentas_sin_env_json()
        if u in base:
            return u
        ul = u.lower()
        for k in base:
            if k.lower() == ul:
                return k
        from auth_registro import normalizar_cuit

        nu = normalizar_cuit(u)
        if nu and nu in base:
            return nu
    except Exception:
        pass
    try:
        from auth_registro import normalizar_cuit, resolver_clave_overlay

        clave = resolver_clave_overlay(u)
        if clave:
            return clave
        nu = normalizar_cuit(u)
        if nu:
            return nu
    except Exception:
        pass
    return u


def verificar_acceso(username: str, password: str) -> str | None:
    """Devuelve None si válido; si no: invalid, expired, not_yet, pending_approval."""
    from auth_registro import verificar_acceso_overlay, verificar_password, verificar_suspendido

    try:
        u = _resolver_clave_usuario(username)
        pwd = (password or "").strip()
        if not u:
            return "invalid"

        # Portable/local con sync: validar en el servidor (ya no viajan hashes en /api/auth-users).
        if _modo_remoto_activo() and not (os.environ.get("RENDER") or "").strip():
            remoto = _intentar_verificar_remoto(u, pwd)
            if remoto is not None:
                ok, motivo = remoto
                return None if ok else (motivo or "invalid")
            # Sin red: permitir login local solo con entitlement firmado vigente (o admin).
            # Se valida la clave más abajo; acá solo marcamos el requisito.
            _offline_requiere_entitlement = True
        else:
            _offline_requiere_entitlement = False

        # En Render: primero AUTH_USERS_JSON / admin (sin Neon). Si valida, listo.
        if (os.environ.get("RENDER") or "").strip():
            try:
                env = _usuarios_desde_env_json()
                base = env if env else _load_cuentas_sin_env_json()
                locales = _cuentas_archivo_local()
                if locales:
                    base = {**base, **locales}
                cuenta_rapida = base.get(u)
                if (
                    cuenta_rapida is not None
                    and (cuenta_rapida.password or "").strip()
                    and verificar_password(cuenta_rapida.password, pwd)
                ):
                    vigencia = _motivo_vigencia(cuenta_rapida)
                    if vigencia is None:
                        _intentar_migrar_password_legacy(u, pwd)
                    return vigencia
            except Exception:
                _LOG.debug("Login rápido sin Neon falló", exc_info=True)

        try:
            pendiente = verificar_acceso_overlay(u, pwd)
        except Exception:
            pendiente = None
        if pendiente == "pending_approval":
            return "pending_approval"
        if pendiente == "invalid":
            return "invalid"
        try:
            suspendido = verificar_suspendido(u, pwd)
        except Exception:
            suspendido = None
        if suspendido == "suspended":
            return "suspended"
        if suspendido == "invalid":
            return "invalid"
        cuenta = _load_cuentas().get(u)
        if (
            cuenta is None
            or not (cuenta.password or "").strip()
            or not verificar_password(cuenta.password, pwd)
        ):
            return "invalid"
        vigencia = _motivo_vigencia(cuenta)
        if vigencia is None:
            _intentar_migrar_password_legacy(u, pwd)
        if vigencia is None and _offline_requiere_entitlement and not es_administrador(u):
            try:
                from auth_entitlements import entitlement_vigente_para_login

                if not entitlement_vigente_para_login(u):
                    return "expired"
            except Exception:
                return "expired"
        return vigencia
    except Exception:
        _LOG.exception("verificar_acceso falló para usuario %r", (username or "")[:64])
        return "invalid"


def _intentar_migrar_password_legacy(clave: str, password_plano: str) -> None:
    """Tras login OK en el servidor, convierte passwords en claro a bcrypt."""
    if not (os.environ.get("RENDER") or "").strip() and not (
        os.environ.get("DATABASE_URL") or os.environ.get("AUTH_DATABASE_URL") or ""
    ).strip():
        # Solo migrar donde hay persistencia de altas (web/Neon), no en caché portable.
        try:
            from auth_registro_db import enabled

            if not enabled():
                return
        except Exception:
            return
    try:
        from auth_registro import migrar_password_si_legacy

        if migrar_password_si_legacy(clave, password_plano):
            _LOG.info("Migración bcrypt aplicada post-login (%s)", clave)
    except Exception:
        _LOG.debug("Migración bcrypt omitida para %s", clave, exc_info=True)


def verify_credentials(username: str, password: str) -> bool:
    return verificar_acceso(username, password) is None


def whatsapp_new_user_url() -> str:
    msg = f"Buen día! Quisiera información acerca del sistema de {APP_NAME}"
    return f"https://wa.me/5493513132914?text={quote(msg)}"
