#!/usr/bin/env python3
"""Verificación integral del flujo de alta de usuarios (local, sin tocar datos reales)."""

from __future__ import annotations

import os
import re
import shutil
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Evitar arranque lento de Playwright al importar app
os.environ.setdefault("CUIT_EN_ARCA_PLAYWRIGHT", "0")

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:
    pass

# Directorio aislado para la prueba
_TEST_DIR = Path(tempfile.mkdtemp(prefix="aic_alta_test_"))
os.environ["AUTH_REGISTRATIONS_DIR"] = str(_TEST_DIR)
os.environ.setdefault("AUTH_ALTA_PUBLICA", "1")
os.environ.setdefault("AUTH_SUBSCRIPTION_DAYS", "30")

# Admin mínimo si no hay AUTH_USERS_JSON
if not (os.environ.get("AUTH_USERS_JSON") or "").strip():
    os.environ["AUTH_USERS_JSON"] = (
        '{"version":1,"users":{"admin_test":{"password":"AdminTest123!","rol":"admin","valido_hasta":"2099-12-31"}}}'
    )
    _ADMIN_USER = "admin_test"
    _ADMIN_PASS = "AdminTest123!"
else:
    import json as _json

    try:
        data = _json.loads(os.environ["AUTH_USERS_JSON"])
        users = data.get("users") or {}
        _ADMIN_USER = next(
            (
                k
                for k, v in users.items()
                if isinstance(v, dict)
                and (
                    str(v.get("rol") or "").lower() == "admin"
                    or v.get("es_admin") is True
                )
            ),
            next(iter(users), "Lucas"),
        )
        meta = users.get(_ADMIN_USER) or {}
        _ADMIN_PASS = str(meta.get("password") or meta.get("clave") or "")
    except Exception:
        _ADMIN_USER = os.environ.get("AUTH_ADMIN_USER") or "Lucas"
        _ADMIN_PASS = os.environ.get("AUTH_ADMIN_PASSWORD") or ""

# CUIT de prueba (válido checksum AFIP simplificado: 20-00000000-0 no válido)
# Usar 20-10432984-7 — ejemplo común de test
_TEST_CUIT = "20104329847"
_TEST_CUIT_FMT = "20-10432984-7"
_TEST_EMAIL = "alta.test@example.com"
_TEST_PASS = "ClaveSegura123!"


def _ok(msg: str) -> None:
    print(f"  OK  {msg}")


def _fail(msg: str) -> None:
    print(f"  FAIL  {msg}")
    raise SystemExit(1)


def _warn(msg: str) -> None:
    print(f"  WARN  {msg}")


def verificar_variables() -> dict[str, bool]:
    print("\n=== Variables de entorno ===")
    checks = {
        "AUTH_REGISTRATIONS_DIR (test)": bool(os.environ.get("AUTH_REGISTRATIONS_DIR")),
        "AUTH_ALTA_PUBLICA": os.environ.get("AUTH_ALTA_PUBLICA", "1") in ("1", "true", "yes"),
        "AUTH_SUBSCRIPTION_DAYS": bool(os.environ.get("AUTH_SUBSCRIPTION_DAYS", "30")),
        "AUTH_USERS_JSON o admin": bool(
            (os.environ.get("AUTH_USERS_JSON") or "").strip() or _ADMIN_PASS
        ),
    }
    smtp_vars = ["SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "AUTH_ADMIN_NOTIFY_EMAIL"]
    smtp_ok = all((os.environ.get(k) or "").strip() for k in smtp_vars)
    checks["SMTP completo (notificación email)"] = smtp_ok
    for k, v in checks.items():
        print(f"  {'OK' if v else 'WARN'}  {k}")
    if not smtp_ok:
        _warn("SMTP incompleto: el alta funciona, pero no llegará email al admin.")
    return checks


def verificar_smtp_conexion() -> bool:
    host = (os.environ.get("SMTP_HOST") or "").strip()
    user = (os.environ.get("SMTP_USER") or "").strip()
    password = (os.environ.get("SMTP_PASSWORD") or "").strip()
    if not (host and user and password):
        return False
    try:
        import smtplib

        port = int((os.environ.get("SMTP_PORT") or "587").strip())
        with smtplib.SMTP(host, port, timeout=15) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(user, password)
        _ok(f"Conexión SMTP a {host}:{port}")
        return True
    except OSError as exc:
        _warn(f"SMTP no conectó: {exc}")
        return False


def verificar_flujo_integrado() -> None:
    print("\n=== Flujo integral (Flask test client) ===")
    from app import app
    from auth import verificar_acceso
    from auth_registro import (
        _dias_suscripcion,
        _path_usuarios_overlay,
        info_suscripcion_usuario,
        listar_pendientes_aprobacion,
        listar_usuarios_suscripcion,
        obtener_solicitud,
    )

    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["SECRET_KEY"] = "test-secret"

    client = app.test_client()

    # 1. Página solicitar acceso
    r = client.get("/solicitar-acceso")
    if r.status_code != 200:
        _fail(f"GET /solicitar-acceso status {r.status_code}")
    _ok("GET /solicitar-acceso accesible")

    # 2. Crear solicitud
    r = client.post(
        "/solicitar-acceso",
        data={
            "cuit": _TEST_CUIT_FMT,
            "email": _TEST_EMAIL,
            "nombre": "Contribuyente Test",
            "telefono_area": "351",
            "telefono_numero": "1234567",
        },
        follow_redirects=True,
    )
    if r.status_code != 200:
        _fail(f"POST /solicitar-acceso status {r.status_code}")
    html = r.get_data(as_text=True)
    m = re.search(r"/activar-cuenta/([A-Za-z0-9_-]+)", html)
    if not m:
        _fail("No se generó enlace de activación en la respuesta")
    token = m.group(1)
    sol = obtener_solicitud(token)
    if not sol or sol.get("cuit") != _TEST_CUIT:
        _fail("Token de solicitud inválido o CUIT incorrecto")
    _ok(f"Solicitud creada, token válido ({token[:12]}…)")

    # 3. Activar cuenta (contraseña)
    r = client.get(f"/activar-cuenta/{token}")
    if r.status_code != 200:
        _fail(f"GET /activar-cuenta status {r.status_code}")
    r = client.post(
        f"/activar-cuenta/{token}",
        data={"password": _TEST_PASS, "password2": _TEST_PASS},
        follow_redirects=True,
    )
    if r.status_code != 200:
        _fail(f"POST /activar-cuenta status {r.status_code}")
    body = r.get_data(as_text=True)
    if "administrador" not in body.lower() and "apruebe" not in body.lower():
        _warn("Pantalla post-activacion: no se detecto aviso de aprobacion pendiente")
    _ok("Contraseña definida, cuenta pendiente de aprobación")

    # 4. Login bloqueado hasta aprobar
    motivo = verificar_acceso(_TEST_CUIT, _TEST_PASS)
    if motivo != "pending_approval":
        _fail(f"Se esperaba pending_approval, obtuvo: {motivo!r}")
    _ok("Login bloqueado con pending_approval")

    pendientes = listar_pendientes_aprobacion()
    if not any(p.get("cuit") == _TEST_CUIT for p in pendientes):
        _fail("El CUIT no aparece en pendientes de aprobación")
    _ok("CUIT listado en pendientes de aprobación")

    # 5. Admin login + panel
    if not _ADMIN_PASS:
        _fail("No hay contraseña de admin para probar el panel")
    r = client.post(
        "/login",
        data={"usuario": _ADMIN_USER, "password": _ADMIN_PASS},
        follow_redirects=True,
    )
    if r.status_code != 200:
        _fail(f"Login admin status {r.status_code}")
    _ok(f"Login admin ({_ADMIN_USER})")

    r = client.get("/admin/altas-usuarios")
    if r.status_code != 200:
        _fail(f"GET /admin/altas-usuarios status {r.status_code}")
    if _TEST_CUIT_FMT not in r.get_data(as_text=True) and _TEST_CUIT not in r.get_data(as_text=True):
        _fail("Panel admin no muestra el CUIT pendiente")
    _ok("Panel admin accesible con pendiente visible")

    # 6. Aprobar
    r = client.post(
        "/admin/altas-usuarios",
        data={"accion": "aprobar", "cuit": _TEST_CUIT},
        follow_redirects=True,
    )
    if r.status_code != 200:
        _fail(f"Aprobar cuenta status {r.status_code}")
    motivo = verificar_acceso(_TEST_CUIT, _TEST_PASS)
    if motivo is not None:
        _fail(f"Tras aprobar, login debería ser válido; obtuvo: {motivo!r}")
    _ok("Cuenta aprobada, login permitido")

    overlay = _path_usuarios_overlay()
    if not overlay.is_file():
        _fail(f"No existe {overlay}")
    _ok(f"Overlay guardado en {overlay.parent}")

    info = info_suscripcion_usuario(_TEST_CUIT)
    dias_cfg = _dias_suscripcion()
    if not info or info.get("dias_restantes") is None:
        _fail("info_suscripcion_usuario sin datos tras aprobar")
    if abs(info["dias_restantes"] - dias_cfg) > 1:
        _fail(f"Días restantes esperados ~{dias_cfg}, obtuvo {info['dias_restantes']}")
    _ok(f"Suscripción: {info['dias_restantes']} días restantes (vence {info['valido_hasta_fmt']})")

    subs = listar_usuarios_suscripcion()
    if not any(s.get("cuit") == _TEST_CUIT for s in subs):
        _fail("CUIT no aparece en suscripciones activas")
    _ok("CUIT en panel de suscripciones activas")

    # 7. Login cliente + barra suscripción
    client.get("/logout", follow_redirects=True)
    r = client.post(
        "/login",
        data={"usuario": _TEST_CUIT_FMT, "password": _TEST_PASS},
        follow_redirects=True,
    )
    if r.status_code != 200:
        _fail(f"Login cliente status {r.status_code}")
    html = r.get_data(as_text=True)
    if "suscripcion" not in html.lower() and "días" not in html and "dias" not in html:
        _warn("No se detectó texto de días de suscripción en inicio (revisar barra superior)")
    else:
        _ok("Login cliente OK, indicador de suscripción en UI")

    # 8. Renovar suscripción (como admin)
    client.get("/logout", follow_redirects=True)
    client.post("/login", data={"usuario": _ADMIN_USER, "password": _ADMIN_PASS})
    r = client.post(
        "/admin/altas-usuarios",
        data={"accion": "renovar", "cuit": _TEST_CUIT},
        follow_redirects=True,
    )
    if r.status_code != 200:
        _fail(f"Renovar suscripcion status {r.status_code}")
    info2 = info_suscripcion_usuario(_TEST_CUIT)
    if not info2 or info2["dias_restantes"] < info["dias_restantes"]:
        _fail("Renovación no extendió la suscripción")
    _ok(f"Renovación OK ({info2['dias_restantes']} días restantes)")

    # 9. Rutas públicas login
    client.get("/logout", follow_redirects=True)
    r = client.get("/login")
    if r.status_code != 200:
        _fail(f"GET /login status {r.status_code}")
    html = r.get_data(as_text=True)
    if "Alta de Usuario" not in html:
        _warn("Enlace «Alta de Usuario» no detectado en login (i18n/FORZAR_IDIOMA)")
    else:
        _ok("Login con enlaces de alta y WhatsApp")
    print("\n=== Persistencia ===")
    for name in ("solicitudes_pendientes.json", "usuarios_registrados.json", "altas_completadas.json"):
        p = _TEST_DIR / name
        print(f"  {'OK' if p.is_file() else 'WARN'}  {name}")


def main() -> None:
    print("Verificación integral — Alta de usuarios")
    print(f"Datos de prueba en: {_TEST_DIR}")
    try:
        verificar_variables()
        verificar_smtp_conexion()
        verificar_flujo_integrado()
        print("\n=== RESULTADO: TODO OPERATIVO ===\n")
    finally:
        shutil.rmtree(_TEST_DIR, ignore_errors=True)


if __name__ == "__main__":
    main()
