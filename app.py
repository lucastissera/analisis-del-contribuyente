import io
import json
import logging
import os
import sys
import threading
import time
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from app_branding import APP_NAME

_APP_ROOT = Path(__file__).resolve().parent
try:
    from dotenv import load_dotenv

    load_dotenv(_APP_ROOT / ".env")
    if getattr(sys, "frozen", False):
        load_dotenv(Path(sys.executable).resolve().parent / ".env")
except ImportError:
    pass

# Habilitar descarga ARCA por defecto (local, portable y servidor web).
# Desactivar solo con CUIT_EN_ARCA_PLAYWRIGHT=0
os.environ.setdefault("CUIT_EN_ARCA_PLAYWRIGHT", "1")
os.environ.setdefault("CUIT_EN_ARCA_UI", "1")

_LOG_APP = logging.getLogger(__name__)


def _arranque_en_background() -> None:
    """Playwright / Neon / sync: no deben bloquear el bind de gunicorn en Render."""
    # Dar tiempo a que el primer /login use Neon sin pelear con el arranque.
    time.sleep(3)

    try:
        from auth_registro import integridad_store_local_ok, verificar_integridad_stores_locales

        verificar_integridad_stores_locales()
    except Exception as exc:
        _LOG_APP.warning("Verificación de stores locales: %s", exc)

    try:
        from auth_registro import asegurar_admin_en_db, asegurar_grupos_registrados
        from auth_registro_db import enabled, migrar_disco_a_db_si_vacio

        if enabled():
            migrar_disco_a_db_si_vacio()
            asegurar_admin_en_db()
            asegurar_grupos_registrados()
            _LOG_APP.info("Persistencia altas (PostgreSQL): init diferido OK")
    except Exception as exc:
        _LOG_APP.warning("No se pudo inicializar PostgreSQL de altas: %s", exc)

    # En Render el servidor es fuente de verdad (Neon); no sincronizar desde AUTH_USERS_URL.
    if not (os.environ.get("RENDER") or "").strip():
        try:
            iniciar_sincronizacion_usuarios()
        except Exception as exc:
            _LOG_APP.warning("Sync usuarios en background: %s", exc)

    if not getattr(sys, "frozen", False):
        try:
            from cuit_en_arca.ensure_playwright import asegurar_chromium_playwright

            asegurar_chromium_playwright()
        except Exception as exc:
            _LOG_APP.warning("Playwright/Chromium en background: %s", exc)


if getattr(sys, "frozen", False):
    from cuit_en_arca.playwright_env import aplicar_entorno_playwright_portable

    aplicar_entorno_playwright_portable()

from flask import (
    Flask,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
    Response,
)

if getattr(sys, "frozen", False):
    _bundle = Path(getattr(sys, "_MEIPASS", _APP_ROOT))
    _tpl = _bundle / "templates"
    _static = _bundle / "static"
    app = Flask(
        __name__,
        root_path=str(_bundle),
        template_folder=str(_tpl),
        static_folder=str(_static),
    )
else:
    app = Flask(__name__)

from auth import (
    es_administrador,
    export_users_payload,
    iniciar_sincronizacion_usuarios,
    verificar_acceso,
    whatsapp_new_user_url,
)
from cursor_cloud import (
    CursorCloudError,
    cancelar_run as cursor_cancelar_run,
    crear_agente as cursor_crear_agente,
    crear_run as cursor_crear_run,
    obtener_run as cursor_obtener_run,
    requiere_repo as cursor_requiere_repo,
    run_publico as cursor_run_publico,
    stream_run as cursor_stream_run,
    verificar_enlace as cursor_verificar_enlace,
)

# Diferir init pesado: en Render el port scan / health check no espera Playwright ni Neon.
threading.Thread(
    target=_arranque_en_background,
    name="arranque-diferido",
    daemon=True,
).start()
from cuit_en_arca import ArcaProcesoError, CancelacionUsuarioError, ejecutar_lote_arca
from cuit_en_arca.planilla_lote import (
    leer_planilla_lote_con_errores,
    parsear_entrada_manual,
    parsear_entradas_manuales,
)
from cuit_en_arca.progreso_lote import (
    agregar_archivo_lote,
    callback_log_lote,
    callback_paso,
    callback_progreso,
    crear_job,
    marcar_error,
    marcar_cancelado,
    marcar_ok,
    obtener_job,
    reiniciar_pasos,
)
from cuit_en_arca.progreso_dfe import (
    agregar_archivo_dfe,
    agregar_resumen_cuit_dfe,
    callback_log_dfe,
    callback_paso_dfe,
    crear_job_dfe,
    marcar_error_dfe,
    marcar_cancelado_dfe,
    marcar_ok_dfe,
    obtener_job_dfe,
    progreso_cuit_dfe,
    reiniciar_pasos_dfe,
)
from cuit_en_arca.progreso_vl import (
    agregar_archivo_vl,
    agregar_resumen_cuit_vl,
    callback_log_vl,
    callback_paso_vl,
    crear_job_vl,
    marcar_error_vl,
    marcar_cancelado_vl,
    marcar_ok_vl,
    obtener_job_vl,
    progreso_cuit_vl,
    reiniciar_pasos_vl,
)
from cuit_en_arca.planilla_nuestra_parte import (
    leer_planilla_np_con_errores,
    parsear_entradas_manuales_np,
)
from cuit_en_arca.progreso_nuestra_parte import (
    agregar_archivo_np,
    agregar_resumen_cuit_np,
    callback_log_np,
    callback_paso_np,
    crear_job_np,
    marcar_error_np,
    marcar_cancelado_np,
    marcar_ok_np,
    obtener_job_np,
    progreso_cuit_np,
    reiniciar_pasos_np,
)
from i18n import (
    LANG_LABELS,
    MESES,
    SUPPORTED_LANGS,
    normalize_lang,
    tr,
    tr_js_bundle,
)
from plantillas_imputacion import (
    agregar_plantilla,
    eliminar_plantilla,
    leer_bytes_plantilla,
    listar_plantillas,
    plantillas_imputacion_disponibles,
    renombrar_plantilla,
    reemplazar_archivo_plantilla,
)

from sumar_imp_total import (
    COLUMNAS_A_AJUSTAR,
    COLUMNAS_DETALLE_SIN_RESUMEN,
    COLUMNAS_TOTAL_RESUMEN,
    enriquecer_contrapartes_con_imputacion,
    escribir_excel_informe_completo,
    escribir_excel_informe_dual,
    leer_mapa_imputaciones_desde_archivo,
    periodos_orden_crono,
    procesar_archivo,
    resumen_totales_por_imputacion,
    total_resumen_pantalla,
    totales_resumen_por_periodo,
)

def _secret_key_aplicacion() -> str:
    """En producción (Render) exige SECRET_KEY aleatoria; en local permite fallback de desarrollo."""
    secret = (os.environ.get("SECRET_KEY") or "").strip()
    en_produccion = bool((os.environ.get("RENDER") or "").strip()) or (
        (os.environ.get("FLASK_ENV") or "").strip().lower() == "production"
    )
    if en_produccion:
        if len(secret) < 32:
            raise RuntimeError(
                "SECRET_KEY de producción no configurada o demasiado corta "
                "(mínimo 32 caracteres aleatorios). "
                "Definila en Render → Environment y redeployá."
            )
        return secret
    if secret:
        return secret
    logging.getLogger(__name__).warning(
        "SECRET_KEY no definida: usando valor de desarrollo (solo local)."
    )
    return "dev-secret-cambiar-en-produccion"


app.secret_key = _secret_key_aplicacion()

# Portable: verificar manifiesto firmado al arrancar (telemetría / soporte).
if getattr(sys, "frozen", False):
    try:
        from auth_manifest import verificar_al_inicio

        verificar_al_inicio()
    except Exception as exc:
        _LOG_APP.warning("Verificación de manifiesto portable: %s", exc)

app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(minutes=30)
app.config["SESSION_REFRESH_EACH_REQUEST"] = True
# Cookies de sesión: en Render solo HTTPS; HttpOnly evita JS; SameSite reduce CSRF básico.
_en_prod_cookies = bool((os.environ.get("RENDER") or "").strip()) or (
    (os.environ.get("FLASK_ENV") or "").strip().lower() == "production"
)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = _en_prod_cookies
# CSRF en POST de formularios / fetch (sesión). APIs Bearer y desktop localhost: exempt.
app.config.setdefault("WTF_CSRF_TIME_LIMIT", None)
app.config.setdefault("WTF_CSRF_CHECK_DEFAULT", True)
from flask_wtf.csrf import CSRFProtect  # noqa: E402

csrf = CSRFProtect(app)
# download_id -> (bytes, nombre_archivo, mimetype)
DESCARGAS: dict[str, tuple[bytes, str, str]] = {}

# CSP básica compatible con scripts/estilos inline actuales y SheetJS (inversiones).
_SECURITY_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdn.sheetjs.com; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; "
    "font-src 'self' data:; "
    "connect-src 'self' https://api.bluelytics.com.ar; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)


@app.after_request
def _cabeceras_seguridad(resp: Response):
    """Cabeceras HTTP defensivas (punto 7 auditoría): nosniff, anti-clickjacking, CSP."""
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    resp.headers.setdefault(
        "Permissions-Policy",
        "camera=(), microphone=(), geolocation=(), payment=()",
    )
    resp.headers.setdefault("Content-Security-Policy", _SECURITY_CSP)
    if _en_prod_cookies:
        resp.headers.setdefault(
            "Strict-Transport-Security",
            "max-age=31536000; includeSubDomains",
        )
    return resp


from cuit_en_arca.entrega_web import init_descargas  # noqa: E402

init_descargas(DESCARGAS)


def _bootstrap_analisis_programado_scheduler() -> None:
    """Gunicorn/Render no ejecutan ``if __name__ == '__main__'``; el hilo va acá."""
    try:
        from cuit_en_arca.analisis_programado import iniciar_scheduler

        iniciar_scheduler()
    except Exception:
        import logging

        logging.getLogger(__name__).exception(
            "No se pudo iniciar el scheduler de análisis programado"
        )


_bootstrap_analisis_programado_scheduler()

# Inactividad: sin peticiones al servidor durante este tiempo → cerrar sesión.
# Cada petición (refresco, nueva pestaña con la misma app, navegación) renueva el plazo.
_SESSION_IDLE_SEC = 30 * 60

# Escritorio (.exe): sin latido visible durante este tiempo → apagar el proceso.
_DESKTOP_GRACE_SEC = 25
_desktop_ultima_ui = time.time()
_desktop_ventana_visible = True
_desktop_watchdog_armado = False
_desktop_cerrando = False


def _es_app_escritorio() -> bool:
    return getattr(sys, "frozen", False)


def _peticion_desde_localhost() -> bool:
    ra = (request.remote_addr or "").replace("::ffff:", "")
    return ra in ("127.0.0.1", "::1")


def _registrar_ui_desktop_viva(*, ventana_visible: bool | None = None) -> None:
    """Marca la ventana del navegador como activa (latido o navegación)."""
    global _desktop_ultima_ui, _desktop_watchdog_armado, _desktop_ventana_visible

    if not _es_app_escritorio() or not _peticion_desde_localhost():
        return
    if ventana_visible is False:
        _desktop_ventana_visible = False
        return
    if ventana_visible is True:
        _desktop_ventana_visible = True
    elif not _desktop_ventana_visible:
        return
    _desktop_ultima_ui = time.time()
    if not _desktop_watchdog_armado:
        _desktop_watchdog_armado = True
        _iniciar_watchdog_desktop()


def _iniciar_watchdog_desktop() -> None:
    """Cierra el .exe si la ventana visible dejó de enviar latidos (p. ej. tocó la X)."""

    def _loop() -> None:
        global _desktop_cerrando
        while True:
            time.sleep(4)
            if _desktop_cerrando or not _es_app_escritorio():
                return
            if not _desktop_ventana_visible:
                continue
            try:
                from cuit_en_arca.trabajos_activos import hay_trabajos_arca_en_curso

                if hay_trabajos_arca_en_curso():
                    continue
            except Exception:
                pass
            if time.time() - _desktop_ultima_ui > _DESKTOP_GRACE_SEC:
                _desktop_cerrando = True
                logging.getLogger(__name__).info(
                    "Aplicación de escritorio sin ventana activa; cerrando proceso."
                )
                _iniciar_cierre_proceso_desktop()
                return

    threading.Thread(
        target=_loop, daemon=True, name="desktop-watchdog"
    ).start()


def _nombre_carpeta_web_sesion(prefijo: str, raw: str | None = None) -> str | None:
    """Nombre de subcarpeta acordado con el navegador (web), p. ej. «Mis Comprobantes 2026-06-12 23-05»."""
    if _es_app_escritorio():
        return None
    if raw is None:
        raw = (request.form.get("web_carpeta_sesion") or "").strip()
    if not raw or not raw.startswith(f"{prefijo} "):
        return None
    if any(c in raw for c in "/\\") or ".." in raw:
        return None
    if len(raw) > 120:
        return None
    return raw


def _fabricar_entrega(
    job_id: str,
    carpeta_form: str | None,
    agregar_estado,
):
    from cuit_en_arca.entrega_web import EntregaWeb, carpeta_trabajo_web, make_registrar

    if _es_app_escritorio():
        p = (carpeta_form or "").strip()
        if not p:
            return None, None
        return Path(p), None
    base = carpeta_trabajo_web(job_id)
    return base, EntregaWeb(base, make_registrar(agregar_estado))


def _wrap_progreso_con_entrega(on_prog, entrega):
    if entrega is None or on_prog is None:
        return on_prog

    def _cb(actual, total, mensaje, fila_terminada=False):
        on_prog(actual, total, mensaje, fila_terminada)
        if fila_terminada:
            entrega.escanear()

    return _cb


def _safe_internal_path(target: str | None) -> str:
    if not target or not isinstance(target, str):
        return url_for("index")
    t = target.strip()
    if t.startswith("/") and not t.startswith("//"):
        return t
    return url_for("index")


def _requiere_admin():
    if not session.get("es_admin"):
        abort(403)


_RUTAS_POR_SERVICIO: tuple[tuple[str, str], ...] = (
    ("/procesador", "procesador"),
    ("/arca-descarga-lote", "procesador"),
    ("/domicilio-fiscal", "dfe"),
    ("/dfe-descargar", "dfe"),
    ("/dfe-estado", "dfe"),
    ("/ventas-liquidaciones", "vl"),
    ("/vl-descargar", "vl"),
    ("/vl-estado", "vl"),
    ("/nuestra-parte", "np"),
    ("/np-descargar", "np"),
    ("/np-estado", "np"),
    ("/facturador", "facturador"),
    ("/inversiones-financieras", "inv"),
    ("/analisis-programado", "ap"),
)


def _servicio_requerido_por_ruta(path: str) -> str | None:
    p = (path or "").split("?", 1)[0]
    for prefijo, clave in _RUTAS_POR_SERVICIO:
        if p == prefijo or p.startswith(prefijo + "/"):
            return clave
    return None


def _requiere_servicio(clave: str) -> None:
    if session.get("es_admin"):
        return
    from auth_registro import usuario_tiene_servicio

    user = (session.get("user") or "").strip()
    if not user or not usuario_tiene_servicio(user, clave):
        abort(403)


def _headless_desde_peticion() -> bool:
    """Navegador visible solo para administrador (portable); resto siempre headless."""
    from cuit_en_arca.service import headless_desde_form

    if not session.get("es_admin"):
        return True
    return headless_desde_form(request.form.get("ver_navegador"))


def _mensaje_error_cursor(lg: str, exc: CursorCloudError) -> str:
    if exc.code == "usage_limit_exceeded":
        return tr(
            lg,
            "admin_cursor_err_usage_limit",
            url="https://www.cursor.com/dashboard?tab=settings",
        )
    return str(exc)


@app.before_request
def _session_idle_and_login():
    if request.endpoint == "static" or (
        request.path and request.path.startswith("/static")
    ):
        return None

    try:
        from auth_registro import integridad_store_local_ok, motivo_integridad_store

        if not integridad_store_local_ok():
            lg = normalize_lang(session.get("lang"))
            msg = motivo_integridad_store() or tr(lg, "err_store_corrupt")
            if request.endpoint in ("login", "logout", "set_lang", "desktop_alive", "desktop_quit"):
                return None
            if request.headers.get("X-Requested-With") == "fetch":
                return jsonify({"error": msg}), 503
            return render_template("login.html", login_error_msg=msg), 503
    except Exception:
        pass

    if request.endpoint not in ("desktop_alive", "desktop_quit", "logout"):
        _registrar_ui_desktop_viva()

    now = time.time()
    username = session.get("user")
    if username:
        last = session.get("last_activity")
        if last is None:
            session["last_activity"] = now
            session.modified = True
        elif (now - float(last)) > _SESSION_IDLE_SEC:
            session.pop("user", None)
            session.pop("last_activity", None)
        else:
            session["last_activity"] = now
            session.modified = True

    if request.endpoint in (
        "login",
        "set_lang",
        "desktop_alive",
        "desktop_quit",
        "logout",
        "api_auth_users",
        "api_auth_verificar",
        "api_cupo_info",
        "api_cupo_consumir",
        "api_uso_registrar",
        "api_estado_altas",
        "solicitar_acceso",
        "activar_cuenta",
        "legal_terminos",
        "legal_privacidad",
        "legal_aceptar",
        "olvide_contrasena",
        "guia_usuario",
        "health",
        None,
    ):
        return None
    if session.get("user"):
        return None
    return redirect(url_for("login", next=request.path))


@app.before_request
def _verificar_servicio_habilitado():
    if request.endpoint == "static" or (
        request.path and request.path.startswith("/static")
    ):
        return None
    user = session.get("user")
    if not user or session.get("es_admin"):
        return None
    clave = _servicio_requerido_por_ruta(request.path)
    if not clave:
        return None
    from auth_registro import usuario_tiene_servicio

    if usuario_tiene_servicio(user, clave):
        return None
    lg = normalize_lang(session.get("lang"))
    msg = tr(lg, "err_servicio_no_habilitado")
    if request.headers.get("X-Requested-With") == "fetch":
        return jsonify({"error": msg}), 403
    flash(msg, "warning")
    return redirect(url_for("index"))


@app.before_request
def _verificar_aceptacion_legal_pendiente():
    if request.endpoint == "static" or (
        request.path and request.path.startswith("/static")
    ):
        return None
    user = session.get("user")
    if not user or session.get("es_admin"):
        return None
    if request.endpoint in (
        "login",
        "logout",
        "set_lang",
        "desktop_alive",
        "desktop_quit",
        "legal_terminos",
        "legal_privacidad",
        "legal_aceptar",
        "api_auth_users",
        "api_auth_verificar",
        "api_cupo_info",
        "api_cupo_consumir",
        "api_uso_registrar",
        "api_estado_altas",
        "health",
        None,
    ):
        return None
    try:
        from legal_aceptacion import usuario_requiere_aceptacion_legal

        if not usuario_requiere_aceptacion_legal(user):
            return None
    except Exception:
        return None
    if request.headers.get("X-Requested-With") == "fetch":
        lg = normalize_lang(session.get("lang"))
        return jsonify({"error": tr(lg, "legal_err_aceptacion_pendiente")}), 403
    return redirect(url_for("legal_aceptar"))


def _entero_miles_punto(n: int) -> str:
    s = str(abs(int(n)))
    if len(s) <= 3:
        return s if n >= 0 else "-" + s
    partes = []
    while s:
        partes.append(s[-3:])
        s = s[:-3]
    out = ".".join(reversed(partes))
    return out if n >= 0 else "-" + out


@app.template_filter("fmt_ar")
def fmt_num_ar_argentina(value: object) -> str:
    """Miles con punto, decimales con coma (visualización en pantalla)."""
    try:
        x = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return str(value)
    neg = x < 0
    x = abs(x)
    centavos = int(round(x * 100 + 1e-9))
    ent = centavos // 100
    dec = centavos % 100
    body = f"{_entero_miles_punto(ent)},{dec:02d}"
    return f"-{body}" if neg else body


def _mostrar_ui_cuit_arca() -> bool:
    v = os.environ.get("CUIT_EN_ARCA_UI", "").strip().lower()
    return v in ("1", "true", "yes", "on")


@app.context_processor
def _inject_ui_flags():
    return {
        "mostrar_cuit_arca_ui": _mostrar_ui_cuit_arca(),
        "ejecutable_escritorio_frozen": getattr(sys, "frozen", False),
        "modo_escritorio": getattr(sys, "frozen", False),
    }


@app.context_processor
def _inject_i18n():
    lg = normalize_lang(session.get("lang"))

    def t(key: str, **kwargs):
        return tr(lg, key, **kwargs)

    return {
        "t": t,
        "current_lang": lg,
        "current_user": session.get("user"),
        "es_administrador": bool(session.get("es_admin")),
        "nombres_meses": MESES[lg],
        "langs": SUPPORTED_LANGS,
        "lang_labels": LANG_LABELS,
        "i18n_js": tr_js_bundle(lg),
    }


@app.context_processor
def _inject_servicios():
    user = session.get("user")
    if not user:
        return {"servicios_habilitados": {}}
    try:
        from auth_registro import servicios_usuario

        return {"servicios_habilitados": servicios_usuario(user)}
    except Exception:
        return {"servicios_habilitados": {}}


@app.context_processor
def _inject_legal_links():
    from legal_config import LEGAL_VERSION

    return {"legal_version_actual": LEGAL_VERSION}


@app.context_processor
def _inject_suscripcion():
    user = session.get("user")
    if not user or session.get("es_admin"):
        return {
            "suscripcion_dias_restantes": None,
            "suscripcion_vencimiento_fmt": None,
            "suscripcion_cuit_fmt": None,
            "suscripcion_cuit_disponibles": None,
        }
    try:
        from auth_registro import formatear_cuit, info_suscripcion_usuario

        info = info_suscripcion_usuario(user)
        if not info:
            return {
                "suscripcion_dias_restantes": None,
                "suscripcion_vencimiento_fmt": None,
                "suscripcion_cuit_fmt": None,
                "suscripcion_cuit_disponibles": None,
            }
        return {
            "suscripcion_dias_restantes": info["dias_restantes"],
            "suscripcion_vencimiento_fmt": info["valido_hasta_fmt"],
            "suscripcion_cuit_fmt": formatear_cuit(str(user)),
            "suscripcion_cuit_disponibles": info.get("cuit_disponibles"),
        }
    except Exception:
        return {
            "suscripcion_dias_restantes": None,
            "suscripcion_vencimiento_fmt": None,
            "suscripcion_cuit_fmt": None,
            "suscripcion_cuit_disponibles": None,
        }


def _usuario_cupo_web() -> str | None:
    if session.get("es_admin"):
        return None
    u = (session.get("user") or "").strip()
    return u or None


def _mensaje_cupo_agotado(lg: str) -> str:
    return tr(lg, "err_cupo_cuit_agotado")


def _verificar_cupo_inicio(lg: str) -> str | None:
    user = _usuario_cupo_web()
    if not user:
        return None
    if getattr(sys, "frozen", False):
        from auth import _modo_remoto_activo, _remote_token, forzar_sync_usuarios_remoto

        if not _modo_remoto_activo() or not _remote_token():
            return tr(lg, "err_cupo_portable_sin_remoto")
        forzar_sync_usuarios_remoto()
    from auth_registro import (
        cupo_cuit_disponible,
        refrescar_cupo_usuario_remoto,
        ultimo_error_cupo,
    )

    if getattr(sys, "frozen", False):
        refrescar_cupo_usuario_remoto(user)
    if cupo_cuit_disponible(user) > 0:
        return None
    err = ultimo_error_cupo()
    if err and getattr(sys, "frozen", False):
        return err
    return _mensaje_cupo_agotado(lg)


def _control_cupo_sesion():
    from auth_registro import control_cupo_cuit

    return control_cupo_cuit(_usuario_cupo_web())


def _registro_valor_sesion():
    from auth_uso_valor import fabricar_registro_valor

    return fabricar_registro_valor(_usuario_cupo_web())


def _mapa_imputaciones_desde_peticion(
    lg: str,
) -> tuple[dict[str, tuple[str, str]] | None, str | None, bytes | None, str | None]:
    """
    Devuelve (mapa_cuit_imputacion | None, mensaje_error | None, bytes_archivo_si_subido, nombre_orig_archivo).
    """
    f_imp = request.files.get("excel_imputaciones")
    has_file = bool(
        f_imp and getattr(f_imp, "filename", None) and str(f_imp.filename).strip()
    )
    plantilla_id = (request.form.get("plantilla_imputacion_id") or "").strip()

    if has_file and plantilla_id and plantillas_imputacion_disponibles():
        return None, tr(lg, "err_imputacion_archivo_y_plantilla"), None, None

    if plantillas_imputacion_disponibles() and plantilla_id and not has_file:
        try:
            raw, nombre = leer_bytes_plantilla(plantilla_id)
            buf = io.BytesIO(raw)
            mapa = leer_mapa_imputaciones_desde_archivo(
                buf, nombre_archivo=nombre, ui_lang=lg
            )
            return mapa, None, None, None
        except FileNotFoundError:
            return None, tr(lg, "err_plantilla_imputacion_no_encontrada"), None, None
        except ValueError as exc:
            return None, str(exc), None, None

    if has_file:
        nombre_imp = Path(f_imp.filename).name
        nl = nombre_imp.lower()
        if not (nl.endswith(".xlsx") or nl.endswith(".csv")):
            return None, tr(lg, "err_only_xlsx_csv"), None, None
        datos = f_imp.read()
        buf_imp = io.BytesIO(datos)
        try:
            mapa = leer_mapa_imputaciones_desde_archivo(
                buf_imp, nombre_archivo=nombre_imp, ui_lang=lg
            )
            return mapa, None, datos, nombre_imp
        except ValueError as exc:
            return None, str(exc), None, None

    return None, None, None, None


MIME_TXT = "text/plain; charset=latin-1"


def _listado_apoc_para_mcr_recibidos(
    lg: str,
) -> tuple[set[str], bytes | None, str, str | None]:
    """
    Descarga el listado APOC de AFIP para cruzar con comprobantes recibidos.
    Devuelve (cuits, bytes_txt, nombre_txt, advertencia_si_fallo).
    """
    from apoc_listado import NOMBRE_TXT_APOC, obtener_listado_apoc

    try:
        cuits, txt_bytes, nombre_txt = obtener_listado_apoc()
        return cuits, txt_bytes, nombre_txt, None
    except Exception as exc:
        app.logger.warning("Listado APOC no disponible: %s", exc)
        return (
            set(),
            None,
            NOMBRE_TXT_APOC,
            tr(lg, "apoc_advertencia_descarga"),
        )


@app.context_processor
def _inject_plantillas_imputacion():
    if plantillas_imputacion_disponibles():
        try:
            lista = listar_plantillas()
        except OSError:
            lista = []
    else:
        lista = []
    return {
        "plantillas_imputacion_ui": plantillas_imputacion_disponibles(),
        "plantillas_imputacion_lista": lista,
    }


@app.get("/set-lang/<code>")
def set_lang(code: str):
    session["lang"] = normalize_lang(code)
    nxt = request.args.get("next") or "/"
    if isinstance(nxt, str) and nxt.startswith("/") and not nxt.startswith("//"):
        return redirect(nxt)
    return redirect(url_for("index"))


_GUIA_USUARIO_SECCIONES: tuple[dict[str, object], ...] = (
    {
        "num": 1,
        "titulo_key": "guia_sec1_title",
        "cuerpo_key": "guia_sec1_body",
        "imagen": "1-menu-principal.jpg",
    },
    {
        "num": 2,
        "titulo_key": "guia_sec2_title",
        "cuerpo_key": "guia_sec2_body",
        "imagen": "2-imputacion-contable.jpg",
    },
    {
        "num": 3,
        "titulo_key": "guia_sec3_title",
        "cuerpo_key": "guia_sec3_body",
        "imagen": "3-descarga-procesamiento-automatico.jpg",
    },
    {
        "num": 4,
        "titulo_key": "guia_sec4_title",
        "cuerpo_key": "guia_sec4_body",
        "imagen": "4-procesamiento-comprobantes.jpg",
    },
    {
        "num": 5,
        "titulo_key": "guia_sec5_title",
        "cuerpo_key": "guia_sec5_body",
        "imagen": "5-dfe.jpg",
    },
    {
        "num": 6,
        "titulo_key": "guia_sec6_title",
        "cuerpo_key": "guia_sec6_body",
        "imagen": "5-1-nuestra-parte.jpg",
    },
    {
        "num": 7,
        "titulo_key": "guia_sec7_title",
        "cuerpo_key": "guia_sec7_body",
        "imagen": "6-analisis-programado.jpg",
    },
)


@app.route("/guia-usuario")
def guia_usuario():
    return render_template(
        "guia_usuario.html",
        secciones=_GUIA_USUARIO_SECCIONES,
    )


def _contexto_legal_template() -> dict:
    from legal_config import (
        LEGAL_VERSION,
        PROVEEDORES_TRANSFERENCIA_INTERNACIONAL,
        jurisdiccion,
        rnbd_inscripto,
        rnbd_numero,
        titular_cuit,
        titular_domicilio,
        titular_email,
        titular_nombre_comercial,
        titular_razon_social,
    )

    razon = titular_razon_social()
    comercial = titular_nombre_comercial()
    return {
        "legal_version": LEGAL_VERSION,
        "app_name": APP_NAME,
        "titular_nombre": razon,
        "titular_razon_social": razon,
        "nombre_comercial": comercial,
        "titular_cuit": titular_cuit(),
        "titular_domicilio": titular_domicilio(),
        "titular_email": titular_email(),
        "jurisdiccion": jurisdiccion(),
        "proveedores_transferencia": PROVEEDORES_TRANSFERENCIA_INTERNACIONAL,
        "rnbd_numero": rnbd_numero(),
        "rnbd_inscripto": rnbd_inscripto(),
    }


def _client_ip() -> str:
    """IP del cliente (respeta X-Forwarded-For de Render/Cloudflare)."""
    xff = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
    if xff:
        return xff[:64]
    return ((request.remote_addr or "").replace("::ffff:", "") or "anon")[:64]


def _rate_limit_bloqueado(bucket: str, *claves: str):
    """Si alguna clave supera el límite, devuelve (retry_after_sec); si no, None."""
    from auth_rate_limit import comprobar_limite

    keys = [k.strip() for k in claves if (k or "").strip()]
    if not keys:
        keys = [_client_ip()]
    peor = 0
    for k in keys:
        ok, retry = comprobar_limite(bucket, k, registrar=False)
        if not ok:
            peor = max(peor, retry)
    if peor > 0:
        return peor
    for k in keys:
        comprobar_limite(bucket, k, registrar=True)
    return None


def _clave_rl_por_usuario(usuario: str) -> str:
    """Clave de rate-limit por cuenta (no por IP)."""
    u = (usuario or "").strip().lower()
    return f"user:{u}" if u else "user:anon"


def _rate_limit_usuario_consulta(bucket: str, usuario: str):
    """Consulta bloqueo por usuario sin registrar intento. None = permitido."""
    from auth_rate_limit import comprobar_limite

    ok, retry = comprobar_limite(bucket, _clave_rl_por_usuario(usuario), registrar=False)
    return None if ok else retry


def _rate_limit_usuario_fallo(bucket: str, usuario: str) -> None:
    """Suma un intento fallido solo para esa cuenta."""
    from auth_rate_limit import comprobar_limite

    comprobar_limite(bucket, _clave_rl_por_usuario(usuario), registrar=True)


def _rate_limit_usuario_ok(bucket: str, usuario: str) -> None:
    """Limpia el contador tras login correcto de esa cuenta."""
    from auth_rate_limit import limpiar_limite

    limpiar_limite(bucket, _clave_rl_por_usuario(usuario))


def _respuesta_rate_limit(retry_after: int, *, api: bool = False):
    lg = normalize_lang(session.get("lang"))
    msg = tr(lg, "err_rate_limit", minutos=max(1, (int(retry_after) + 59) // 60))
    if api:
        resp = jsonify(
            {"error": "rate_limit", "retry_after": int(retry_after), "mensaje": msg}
        )
        resp.status_code = 429
    else:
        resp = Response(msg, status=429, mimetype="text/plain; charset=utf-8")
    resp.headers["Retry-After"] = str(max(1, int(retry_after)))
    return resp


@app.get("/legal/terminos")
def legal_terminos():
    return render_template("legal/terminos.html", **_contexto_legal_template())


@app.get("/legal/privacidad")
def legal_privacidad():
    return render_template("legal/privacidad.html", **_contexto_legal_template())


@app.route("/legal/aceptar", methods=["GET", "POST"])
def legal_aceptar():
    from auth_registro import registrar_aceptacion_legal_usuario, resolver_clave_usuario_overlay
    from legal_aceptacion import datos_peticion_aceptacion, usuario_requiere_aceptacion_legal
    from legal_config import LEGAL_VERSION

    lg = normalize_lang(session.get("lang"))
    user = (session.get("user") or "").strip()
    if not user:
        return redirect(url_for("login", next=url_for("legal_aceptar")))
    if not usuario_requiere_aceptacion_legal(user):
        return redirect(url_for("index"))

    error_msg = None
    if request.method == "POST":
        if request.form.get("acepto_legal") != "1":
            error_msg = tr(lg, "legal_err_aceptacion_requerida")
        else:
            pet = datos_peticion_aceptacion()
            clave = resolver_clave_usuario_overlay(user) or user
            if registrar_aceptacion_legal_usuario(
                clave,
                version=LEGAL_VERSION,
                metodo="digital_clickwrap",
                ip=pet["ip"],
                user_agent=pet["user_agent"],
            ):
                flash(tr(lg, "legal_ok_aceptacion"), "success")
                return redirect(url_for("index"))
            error_msg = tr(lg, "legal_err_aceptacion_guardado")

    ctx = _contexto_legal_template()
    ctx["error_msg"] = error_msg
    return render_template("legal/aceptar.html", **ctx)


@app.route("/solicitar-acceso", methods=["GET", "POST"])
def solicitar_acceso():
    from auth_registro import _token_horas, alta_publica_habilitada

    lg = normalize_lang(session.get("lang"))
    enlace_activacion = None
    error_msg = None
    try:
        if not alta_publica_habilitada():
            return redirect(url_for("login"))
        if session.get("user"):
            return redirect(url_for("index"))
        if request.method == "POST":
            from auth_registro import (
                crear_solicitud,
                formatear_cuit,
                normalizar_cuit,
                notificar_admin_nueva_solicitud_async,
            )

            rl = _rate_limit_bloqueado("alta", _client_ip())
            if rl is not None:
                return _respuesta_rate_limit(rl)

            cuit = (request.form.get("cuit") or "").strip()
            email = (request.form.get("email") or "").strip()
            nombre = (request.form.get("nombre") or "").strip()
            telefono_area = (request.form.get("telefono_area") or "").strip()
            telefono_numero = (request.form.get("telefono_numero") or "").strip()
            try:
                token, _reg = crear_solicitud(
                    cuit=cuit,
                    email=email,
                    nombre=nombre,
                    telefono_area=telefono_area,
                    telefono_numero=telefono_numero,
                )
                enlace_activacion = url_for("activar_cuenta", token=token, _external=True)
                cuit_ok = formatear_cuit(normalizar_cuit(cuit) or cuit)
                notificar_admin_nueva_solicitud_async(
                    cuit=cuit,
                    email=email,
                    nombre=nombre,
                    telefono_area=telefono_area,
                    telefono_numero=telefono_numero,
                    enlace_activacion=enlace_activacion,
                )
                flash(
                    tr(
                        lg,
                        "alta_ok_solicitud",
                        cuit=cuit_ok,
                        horas=_token_horas(),
                    ),
                    "success",
                )
            except ValueError as exc:
                key = f"alta_err_{exc}"
                error_msg = tr(lg, key) if tr(lg, key) != key else str(exc)
            except RuntimeError:
                error_msg = tr(lg, "alta_err_solicitud_guardado")
            except Exception as exc:
                logging.getLogger(__name__).exception(
                    "Error inesperado al crear solicitud de alta (CUIT=%s): %s",
                    cuit,
                    exc,
                )
                error_msg = tr(lg, "alta_err_solicitud_guardado")
        return render_template(
            "solicitar_acceso.html",
            enlace_activacion=enlace_activacion,
            error_msg=error_msg,
            token_horas=_token_horas(),
            whatsapp_url=whatsapp_new_user_url(),
        )
    except Exception as exc:
        logging.getLogger(__name__).exception("solicitar_acceso falló por completo: %s", exc)
        try:
            horas = _token_horas()
        except Exception:
            horas = 72
        return (
            render_template(
                "solicitar_acceso.html",
                enlace_activacion=None,
                error_msg=tr(lg, "alta_err_solicitud_guardado"),
                token_horas=horas,
                whatsapp_url=whatsapp_new_user_url(),
            ),
            200,
        )


@app.route("/api/estado-altas")
def api_estado_altas():
    """Diagnóstico rápido de persistencia de altas y SMTP (Render / Neon)."""
    from auth_registro import estado_smtp
    from auth_registro_db import enabled, estado_db

    probar_smtp = (request.args.get("probar_smtp") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    out: dict[str, object] = {
        "alta_publica": (os.environ.get("AUTH_ALTA_PUBLICA") or "1").strip().lower()
        in ("1", "true", "yes", "on"),
        "database_url_configurada": enabled(),
        "auth_registrations_dir": (os.environ.get("AUTH_REGISTRATIONS_DIR") or "").strip()
        or None,
        "smtp": estado_smtp(probar_conexion=probar_smtp),
    }
    if enabled():
        out["postgresql"] = estado_db()
    try:
        from auth_registro import _cargar_solicitudes, listar_pendientes_aprobacion

        sols = _cargar_solicitudes().get("solicitudes")
        out["solicitudes_pendientes"] = len(sols) if isinstance(sols, dict) else 0
        out["usuarios_pendientes_aprobacion"] = len(listar_pendientes_aprobacion())
        out["ok"] = True
    except Exception as exc:
        out["ok"] = False
        out["error"] = str(exc)
    return jsonify(out)


@app.route("/activar-cuenta/<token>", methods=["GET", "POST"])
def activar_cuenta(token: str):
    from auth_registro import (
        activar_cuenta as registro_activar,
        formatear_cuit,
        notificar_admin_alta_async,
        obtener_solicitud,
        _min_password_len,
    )

    lg = normalize_lang(session.get("lang"))
    min_len = _min_password_len()
    try:
        if session.get("user"):
            return redirect(url_for("index"))

        sol = obtener_solicitud(token)
        if not sol and request.method == "GET":
            return render_template(
                "activar_cuenta.html",
                token=token,
                invalido=True,
                solicitud=None,
                min_len=min_len,
            )

        error_msg = None
        if request.method == "POST":
            rl = _rate_limit_bloqueado("activar", _client_ip(), (token or "")[:24])
            if rl is not None:
                return _respuesta_rate_limit(rl)
            pwd = request.form.get("password") or ""
            pwd2 = request.form.get("password2") or ""
            if pwd != pwd2:
                error_msg = tr(lg, "alta_err_password_no_coincide")
            elif request.form.get("acepto_legal") != "1":
                error_msg = tr(lg, "legal_err_aceptacion_requerida")
            else:
                try:
                    from legal_aceptacion import datos_peticion_aceptacion
                    from legal_config import LEGAL_VERSION

                    pet = datos_peticion_aceptacion()
                    reg = registro_activar(
                        token,
                        pwd,
                        aceptacion_legal={
                            "version": LEGAL_VERSION,
                            "metodo": "digital_clickwrap_alta",
                            "ip": pet["ip"],
                            "user_agent": pet["user_agent"],
                        },
                    )
                    notificar_admin_alta_async(
                        str(reg["cuit"]),
                        str(reg.get("email") or ""),
                        str(reg.get("nombre") or ""),
                    )
                    cuit_ok = formatear_cuit(str(reg["cuit"]))
                    return render_template(
                        "activar_cuenta.html",
                        token=token,
                        invalido=False,
                        solicitud=None,
                        cuit_fmt=cuit_ok,
                        completado_pendiente=True,
                        min_len=min_len,
                    )
                except ValueError as exc:
                    key = f"alta_err_{exc}"
                    error_msg = tr(lg, key) if tr(lg, key) != key else str(exc)
                except RuntimeError:
                    error_msg = tr(lg, "alta_err_guardado")
                except Exception as exc:
                    logging.getLogger(__name__).exception(
                        "Error inesperado al activar cuenta (token=%s…): %s",
                        (token or "")[:12],
                        exc,
                    )
                    error_msg = tr(lg, "alta_err_guardado")
            sol = obtener_solicitud(token)

        cuit_fmt = formatear_cuit(str(sol.get("cuit") or "")) if sol else ""
        return render_template(
            "activar_cuenta.html",
            token=token,
            invalido=not sol,
            solicitud=sol,
            cuit_fmt=cuit_fmt,
            error_msg=error_msg,
            min_len=min_len,
        )
    except Exception as exc:
        logging.getLogger(__name__).exception(
            "activar_cuenta falló por completo (token=%s…): %s",
            (token or "")[:12],
            exc,
        )
        return (
            render_template(
                "activar_cuenta.html",
                token=token,
                invalido=True,
                solicitud=None,
                error_msg=tr(lg, "alta_err_guardado"),
                min_len=min_len,
            ),
            200,
        )


@app.route("/admin/altas-usuarios", methods=["GET", "POST"])
def admin_altas_usuarios():
    _requiere_admin()
    from auth_registro import (
        aprobar_cuenta,
        actualizar_email_usuario,
        cambiar_contrasena_usuario,
        crear_solicitud,
        crear_usuario_admin,
        eliminar_cuenta,
        formatear_cuit,
        listar_altas_recientes,
        listar_pendientes_aprobacion,
        listar_usuarios_suscripcion,
        cargar_usuarios_overlay,
        normalizar_cuit,
        probar_email_admin,
        rechazar_cuenta,
        renovar_suscripcion,
        suspender_cuenta,
        reactivar_cuenta,
        actualizar_vencimiento,
        actualizar_cuit_limite,
        actualizar_servicios_usuario,
        SERVICIOS_IDS,
        estado_smtp,
        _dias_suscripcion,
    )

    lg = normalize_lang(session.get("lang"))
    enlace_generado = session.pop("admin_enlace_alta", None)

    if request.method == "POST":
        from auth_auditoria import registrar_accion_admin

        accion = (request.form.get("accion") or "").strip()
        cuit = (request.form.get("cuit") or "").strip()
        actor = (session.get("user") or "").strip()
        if accion:
            objetivo_audit = cuit
            if accion in ("revocar_dispositivo", "renombrar_dispositivo"):
                objetivo_audit = (request.form.get("token_hash") or "")[:16]
            registrar_accion_admin(
                actor,
                accion,
                objetivo=objetivo_audit,
                ip=_client_ip(),
            )
        if accion == "aprobar":
            if aprobar_cuenta(cuit):
                flash(
                    tr(
                        lg,
                        "admin_altas_ok_aprobada",
                        cuit=formatear_cuit(cuit),
                        dias=_dias_suscripcion(),
                    ),
                    "success",
                )
            else:
                flash(tr(lg, "admin_altas_err_no_encontrada"), "warning")
        elif accion == "rechazar":
            if rechazar_cuenta(cuit):
                flash(tr(lg, "admin_altas_ok_rechazada"), "success")
            else:
                flash(tr(lg, "admin_altas_err_no_encontrada"), "warning")
        elif accion == "renovar":
            if renovar_suscripcion(cuit):
                flash(
                    tr(
                        lg,
                        "admin_gestion_ok_renovada",
                        cuit=formatear_cuit(normalizar_cuit(cuit) or cuit),
                        dias=_dias_suscripcion(),
                    ),
                    "success",
                )
            else:
                flash(tr(lg, "admin_altas_err_no_encontrada"), "warning")
        elif accion == "suspender":
            if suspender_cuenta(cuit):
                flash(
                    tr(lg, "admin_gestion_ok_suspendida", cuit=formatear_cuit(normalizar_cuit(cuit) or cuit)),
                    "success",
                )
            else:
                flash(tr(lg, "admin_altas_err_no_encontrada"), "warning")
        elif accion == "reactivar":
            if reactivar_cuenta(cuit):
                flash(
                    tr(lg, "admin_gestion_ok_reactivada", cuit=formatear_cuit(normalizar_cuit(cuit) or cuit)),
                    "success",
                )
            else:
                flash(tr(lg, "admin_altas_err_no_encontrada"), "warning")
        elif accion == "eliminar_cuenta":
            from auth import verify_credentials

            admin_pwd = request.form.get("admin_password") or ""
            admin_user = session.get("user") or ""
            if not verify_credentials(admin_user, admin_pwd):
                flash(tr(lg, "admin_gestion_err_clave_admin"), "warning")
            elif eliminar_cuenta(cuit):
                flash(
                    tr(
                        lg,
                        "admin_gestion_ok_eliminada",
                        cuit=formatear_cuit(normalizar_cuit(cuit) or cuit),
                    ),
                    "success",
                )
            else:
                flash(tr(lg, "admin_gestion_err_eliminar"), "warning")
        elif accion == "actualizar_vencimiento":
            valido_hasta = (request.form.get("valido_hasta") or "").strip()
            if actualizar_vencimiento(cuit, valido_hasta):
                flash(
                    tr(
                        lg,
                        "admin_gestion_ok_vencimiento",
                        cuit=formatear_cuit(normalizar_cuit(cuit) or cuit),
                        fecha=valido_hasta,
                    ),
                    "success",
                )
            else:
                flash(tr(lg, "admin_gestion_err_vencimiento"), "warning")
        elif accion == "actualizar_cuit_limite":
            raw_limite = (request.form.get("cuit_limite") or "").strip()
            try:
                limite = int(raw_limite)
            except ValueError:
                flash(tr(lg, "admin_gestion_err_cuit_limite"), "warning")
            else:
                if actualizar_cuit_limite(cuit, limite):
                    flash(
                        tr(
                            lg,
                            "admin_gestion_ok_cuit_limite",
                            cuit=formatear_cuit(normalizar_cuit(cuit) or cuit),
                            limite=limite,
                        ),
                        "success",
                    )
                else:
                    flash(tr(lg, "admin_gestion_err_cuit_limite"), "warning")
        elif accion == "actualizar_servicios":
            servicios = {
                sid: request.form.get(f"svc_{sid}") == "1" for sid in SERVICIOS_IDS
            }
            if actualizar_servicios_usuario(cuit, servicios):
                flash(
                    tr(
                        lg,
                        "admin_gestion_ok_servicios",
                        cuit=formatear_cuit(normalizar_cuit(cuit) or cuit),
                    ),
                    "success",
                )
            else:
                flash(tr(lg, "admin_gestion_err_servicios"), "warning")
        elif accion == "generar_enlace":
            email = (request.form.get("email") or "").strip()
            nombre = (request.form.get("nombre") or "").strip()
            telefono_area = (request.form.get("telefono_area") or "").strip()
            telefono_numero = (request.form.get("telefono_numero") or "").strip()
            try:
                token, _reg = crear_solicitud(
                    cuit=cuit,
                    email=email,
                    nombre=nombre,
                    telefono_area=telefono_area,
                    telefono_numero=telefono_numero,
                )
                enlace = url_for("activar_cuenta", token=token, _external=True)
                session["admin_enlace_alta"] = enlace
                flash(
                    tr(lg, "admin_altas_enlace_ok", cuit=formatear_cuit(normalizar_cuit(cuit) or cuit)),
                    "success",
                )
            except ValueError as exc:
                key = f"alta_err_{exc}"
                flash(tr(lg, key) if tr(lg, key) != key else str(exc), "warning")
        elif accion == "alta_directa":
            pwd = request.form.get("password") or ""
            pwd2 = request.form.get("password2") or ""
            valido_hasta = (request.form.get("valido_hasta") or "").strip()
            email = (request.form.get("email") or "").strip()
            nombre = (request.form.get("nombre") or "").strip()
            telefono_area = (request.form.get("telefono_area") or "").strip()
            telefono_numero = (request.form.get("telefono_numero") or "").strip()
            if pwd != pwd2:
                flash(tr(lg, "alta_err_password_no_coincide"), "warning")
            else:
                try:
                    reg = crear_usuario_admin(
                        cuit=cuit,
                        password=pwd,
                        valido_hasta=valido_hasta,
                        email=email,
                        nombre=nombre,
                        telefono_area=telefono_area,
                        telefono_numero=telefono_numero,
                    )
                    flash(
                        tr(
                            lg,
                            "admin_alta_directa_ok",
                            cuit=reg["cuit_fmt"],
                            fecha=reg["valido_hasta_fmt"],
                        ),
                        "success",
                    )
                except ValueError as exc:
                    key = f"alta_err_{exc}"
                    flash(tr(lg, key) if tr(lg, key) != key else str(exc), "warning")
                except RuntimeError:
                    flash(tr(lg, "alta_err_guardado"), "warning")
        elif accion == "cambiar_contrasena":
            pwd = request.form.get("password") or ""
            pwd2 = request.form.get("password2") or ""
            if pwd != pwd2:
                flash(tr(lg, "alta_err_password_no_coincide"), "warning")
            else:
                try:
                    cambiar_contrasena_usuario(cuit, pwd)
                    flash(
                        tr(
                            lg,
                            "admin_gestion_ok_clave",
                            cuit=formatear_cuit(normalizar_cuit(cuit) or cuit),
                        ),
                        "success",
                    )
                except ValueError as exc:
                    key = f"alta_err_{exc}" if str(exc).startswith("password_") else "admin_altas_err_no_encontrada"
                    flash(tr(lg, key) if tr(lg, key) != key else str(exc), "warning")
                except RuntimeError:
                    flash(tr(lg, "alta_err_guardado"), "warning")
        elif accion == "actualizar_email":
            email = (request.form.get("email") or "").strip()
            try:
                actualizar_email_usuario(cuit, email)
                flash(
                    tr(
                        lg,
                        "admin_gestion_ok_email",
                        cuit=formatear_cuit(normalizar_cuit(cuit) or cuit),
                        email=email or "—",
                    ),
                    "success",
                )
            except ValueError as exc:
                key = (
                    f"alta_err_{exc}"
                    if str(exc).startswith("email_")
                    else "admin_altas_err_no_encontrada"
                )
                flash(tr(lg, key) if tr(lg, key) != key else str(exc), "warning")
            except RuntimeError:
                flash(tr(lg, "alta_err_guardado"), "warning")
        elif accion == "probar_email":
            resultado = probar_email_admin()
            if resultado.get("ok"):
                flash(
                    tr(lg, "admin_smtp_ok", destino=resultado.get("destino") or ""),
                    "success",
                )
            else:
                flash(
                    tr(
                        lg,
                        "admin_smtp_err",
                        detalle=resultado.get("error") or tr(lg, "admin_smtp_err_generico"),
                    ),
                    "warning",
                )
        elif accion == "revocar_dispositivo":
            from auth_dispositivos import revocar_dispositivo

            th = (request.form.get("token_hash") or "").strip()
            if revocar_dispositivo(th, por=actor or "admin"):
                flash(tr(lg, "admin_disp_ok_revocado"), "success")
            else:
                flash(tr(lg, "admin_disp_err"), "warning")
        elif accion == "renombrar_dispositivo":
            from auth_dispositivos import renombrar_dispositivo

            th = (request.form.get("token_hash") or "").strip()
            etiq = (request.form.get("etiqueta") or "").strip()
            if renombrar_dispositivo(th, etiq):
                flash(tr(lg, "admin_disp_ok_renombrado"), "success")
            else:
                flash(tr(lg, "admin_disp_err"), "warning")
        return redirect(url_for("admin_altas_usuarios"))

    from auth_auditoria import listar_acciones_admin
    from auth_dispositivos import listar_dispositivos

    altas = listar_altas_recientes(40)
    auditoria_admin = listar_acciones_admin(30)
    dispositivos = listar_dispositivos(incluir_revocados=True)
    from datetime import date as _date_cls, timedelta as _td_cls

    fecha_default_alta = (_date_cls.today() + _td_cls(days=_dias_suscripcion())).isoformat()
    overlay_usuarios = cargar_usuarios_overlay()
    db_activo = False
    try:
        from auth_registro_db import enabled

        db_activo = enabled()
    except Exception:
        db_activo = False
    return render_template(
        "admin_altas_usuarios.html",
        pendientes=listar_pendientes_aprobacion(overlay_usuarios),
        suscriptores=listar_usuarios_suscripcion(overlay_usuarios),
        altas=altas,
        auditoria_admin=auditoria_admin,
        dispositivos=dispositivos,
        enlace_generado=enlace_generado,
        dias_suscripcion=_dias_suscripcion(),
        fecha_default_alta=fecha_default_alta,
        min_password_len=os.environ.get("AUTH_MIN_PASSWORD_LEN", "8"),
        smtp_estado=estado_smtp(),
        servicios_ids=SERVICIOS_IDS,
        db_activo=db_activo,
    )


@app.get("/admin/estado-db")
def admin_estado_db():
    """Diagnóstico Neon diferido (no bloquea el render de Altas)."""
    _requiere_admin()
    try:
        from auth_registro_db import enabled, estado_db

        if not enabled():
            return jsonify({"activo": False, "url_configurada": False})
        return jsonify(estado_db())
    except Exception as exc:
        return jsonify({"activo": False, "url_configurada": True, "error": str(exc)}), 500


@app.get("/admin/dashboard-valor")
def admin_dashboard_valor():
    _requiere_admin()
    from auth_registro import formatear_cuit, normalizar_cuit
    from auth_uso_valor import dashboard_valor_usuario

    lg = normalize_lang(session.get("lang"))
    cuit = (request.args.get("cuit") or "").strip()
    dash = dashboard_valor_usuario(cuit) if cuit else None
    if cuit and not dash:
        flash(tr(lg, "admin_dashboard_valor_err"), "warning")
        return redirect(url_for("admin_altas_usuarios"))
    return render_template(
        "admin_dashboard_valor.html",
        dashboard=dash,
        cuit_fmt=formatear_cuit(normalizar_cuit(cuit) or cuit) if cuit else "",
    )


@app.get("/admin/dashboard-valor/exportar")
def admin_dashboard_valor_exportar():
    _requiere_admin()
    lg = normalize_lang(session.get("lang"))
    try:
        from datetime import date

        from auth_uso_valor import generar_excel_dashboard_valor, listar_dashboards_valor

        dashboards = listar_dashboards_valor()
        if not dashboards:
            flash(tr(lg, "admin_dashboard_export_vacio"), "warning")
            return redirect(url_for("admin_altas_usuarios"))

        contenido = generar_excel_dashboard_valor(dashboards)
        if not contenido:
            raise ValueError("Excel vacio")

        nombre = f"Dashboard_Valor_Generado_{date.today().isoformat()}.xlsx"
        # Response con bytes evita fallos de send_file(BytesIO) bajo gunicorn/Render.
        return Response(
            contenido,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f'attachment; filename="{nombre}"',
                "Content-Length": str(len(contenido)),
                "Cache-Control": "no-store",
            },
        )
    except Exception as exc:
        logging.getLogger(__name__).exception("Error al exportar dashboard de valor")
        flash(
            f"{tr(lg, 'admin_dashboard_export_error')} ({type(exc).__name__}: {exc})",
            "danger",
        )
        return redirect(url_for("admin_altas_usuarios"))


@app.get("/admin/legal/exportar-aceptaciones")
def admin_legal_exportar_aceptaciones():
    _requiere_admin()
    from datetime import date

    from auth_registro import listar_usuarios_suscripcion
    from legal_aceptacion import exportar_aceptaciones_csv, exportar_aceptaciones_json

    formato = (request.args.get("formato") or "csv").strip().lower()
    filas = listar_usuarios_suscripcion()
    hoy = date.today().isoformat()
    if formato == "json":
        contenido = exportar_aceptaciones_json(filas)
        nombre = f"Aceptaciones_Legales_{hoy}.json"
        mimetype = "application/json; charset=utf-8"
    else:
        contenido = exportar_aceptaciones_csv(filas)
        nombre = f"Aceptaciones_Legales_{hoy}.csv"
        mimetype = "text/csv; charset=utf-8"

    return send_file(
        io.BytesIO(contenido),
        as_attachment=True,
        download_name=nombre,
        mimetype=mimetype,
    )


@app.route("/olvide-contrasena", methods=["GET", "POST"])
def olvide_contrasena():
    if session.get("user"):
        return redirect(url_for("index"))
    from auth_registro import (
        formatear_cuit,
        normalizar_cuit,
        restablecer_contrasena,
        verificar_identidad_recuperacion,
    )

    lg = normalize_lang(session.get("lang"))
    error_msg = None
    paso = "identificar"
    cuit_fmt = ""
    min_len = os.environ.get("AUTH_MIN_PASSWORD_LEN", "8")

    if request.method == "GET":
        if session.get("reset_cuit"):
            paso = "nueva_clave"
            cuit_fmt = formatear_cuit(str(session["reset_cuit"]))
        else:
            session.pop("reset_email", None)

    if request.method == "POST":
        rl = _rate_limit_bloqueado("reset", _client_ip())
        if rl is not None:
            return _respuesta_rate_limit(rl)
        accion = (request.form.get("paso") or "identificar").strip()
        if accion == "identificar":
            cuit = (request.form.get("cuit") or "").strip()
            email = (request.form.get("email") or "").strip()
            if verificar_identidad_recuperacion(cuit, email):
                u = normalizar_cuit(cuit) or cuit
                session["reset_cuit"] = u
                session["reset_email"] = email.strip().lower()
                session.modified = True
                paso = "nueva_clave"
                cuit_fmt = formatear_cuit(u)
            else:
                error_msg = tr(lg, "reset_err_no_coincide")
        elif accion == "nueva_clave":
            u = session.get("reset_cuit") or ""
            em = session.get("reset_email") or ""
            pwd = request.form.get("password") or ""
            pwd2 = request.form.get("password2") or ""
            cuit_fmt = formatear_cuit(str(u)) if u else ""
            paso = "nueva_clave"
            if not u or not em:
                return redirect(url_for("olvide_contrasena"))
            if pwd != pwd2:
                error_msg = tr(lg, "alta_err_password_no_coincide")
            else:
                try:
                    restablecer_contrasena(str(u), str(em), pwd)
                    session.pop("reset_cuit", None)
                    session.pop("reset_email", None)
                    flash(tr(lg, "reset_ok"), "success")
                    return redirect(url_for("login"))
                except ValueError as exc:
                    key = f"alta_err_{exc}" if str(exc).startswith("password_") else f"reset_err_{exc}"
                    error_msg = tr(lg, key) if tr(lg, key) != key else str(exc)
                except RuntimeError:
                    error_msg = tr(lg, "alta_err_guardado")

    return render_template(
        "olvide_contrasena.html",
        paso=paso,
        cuit_fmt=cuit_fmt,
        error_msg=error_msg,
        min_len=min_len,
    )


@app.get("/health")
def health():
    """Health check de Render: responde sin auth ni consultas a Neon."""
    return jsonify(
        {
            "ok": True,
            "build": os.environ.get("RENDER_GIT_COMMIT")
            or os.environ.get("AIC_BUILD_ID")
            or "a1-login-fix",
        }
    )


@app.route("/login", methods=["GET", "POST"])
def login():
    from auth_registro import alta_publica_habilitada

    if session.get("user"):
        return redirect(_safe_internal_path(request.args.get("next")))
    if request.method == "POST":
        next_val = (request.form.get("next") or "").strip()
        user = (request.form.get("usuario") or "").strip()
        pwd = request.form.get("password") or ""
        # Bloqueo por usuario (no por IP): otra cuenta con clave correcta puede entrar.
        rl = _rate_limit_usuario_consulta("login", user)
        if rl is not None:
            lg = normalize_lang(session.get("lang"))
            return render_template(
                "login.html",
                login_error=True,
                login_error_msg=tr(
                    lg, "err_rate_limit", minutos=max(1, (int(rl) + 59) // 60)
                ),
                next=next_val,
                whatsapp_url=whatsapp_new_user_url(),
                alta_publica=alta_publica_habilitada(),
            ), 429
        try:
            motivo = verificar_acceso(user, pwd)
        except Exception as exc:
            logging.getLogger(__name__).exception("Error en login/verificar_acceso: %s", exc)
            lg = normalize_lang(session.get("lang"))
            return render_template(
                "login.html",
                login_error=True,
                login_error_msg=tr(lg, "login_error_bad"),
                next=next_val,
                whatsapp_url=whatsapp_new_user_url(),
                alta_publica=alta_publica_habilitada(),
            ), 503
        if motivo is None:
            from auth import _resolver_clave_usuario, forzar_sync_usuarios_remoto

            _rate_limit_usuario_ok("login", user)
            session["user"] = _resolver_clave_usuario(user)
            session["es_admin"] = es_administrador(session["user"])
            session["last_activity"] = time.time()
            session.permanent = True
            session.modified = True
            try:
                forzar_sync_usuarios_remoto()
                from auth_registro import refrescar_cupo_usuario_remoto

                refrescar_cupo_usuario_remoto(session["user"])
            except Exception:
                pass
            return redirect(_safe_internal_path(next_val or request.args.get("next")))
        _rate_limit_usuario_fallo("login", user)
        lg = normalize_lang(session.get("lang"))
        if motivo == "rate_limit":
            return render_template(
                "login.html",
                login_error=True,
                login_error_msg=tr(lg, "err_rate_limit", minutos=5),
                next=next_val,
                whatsapp_url=whatsapp_new_user_url(),
                alta_publica=alta_publica_habilitada(),
            ), 429
        login_error_pending = motivo == "pending_approval"
        login_error_suspended = motivo == "suspended"
        return render_template(
            "login.html",
            login_error=motivo == "invalid",
            login_error_expired=motivo in ("expired", "not_yet"),
            login_error_pending=login_error_pending,
            login_error_suspended=login_error_suspended,
            login_error_msg=(
                tr(lg, "login_error_pending")
                if login_error_pending
                else (
                    tr(lg, "login_error_suspended")
                    if login_error_suspended
                    else (
                        tr(lg, "login_error_expired")
                        if motivo in ("expired", "not_yet")
                        else tr(lg, "login_error_bad")
                    )
                )
            ),
            next=next_val,
            whatsapp_url=whatsapp_new_user_url(),
            alta_publica=alta_publica_habilitada(),
        )
    next_val = (request.args.get("next") or "").strip()

    return render_template(
        "login.html",
        next=next_val,
        whatsapp_url=whatsapp_new_user_url(),
        alta_publica=alta_publica_habilitada(),
    )


def _limpiar_sesion_flask() -> None:
    """Cierra sesión Flask conservando solo el idioma elegido."""
    lang = session.get("lang")
    session.clear()
    if lang:
        session["lang"] = lang
    session.modified = True


def _aplicar_borrado_cookie_sesion(resp: Response) -> Response:
    resp.delete_cookie(
        app.config.get("SESSION_COOKIE_NAME", "session"),
        path=app.config.get("SESSION_COOKIE_PATH") or "/",
    )
    return resp


def _iniciar_cierre_proceso_desktop() -> None:
    """Cierra navegador (modo app), borra cookies locales y termina el .exe."""
    global _desktop_cerrando
    _desktop_cerrando = True

    def _salir() -> None:
        time.sleep(0.6)
        try:
            from cuit_en_arca.browser_desktop import (
                cerrar_navegador_desktop,
                limpiar_cookies_localhost,
            )

            cerrar_navegador_desktop()
            limpiar_cookies_localhost()
        except Exception:
            pass
        os._exit(0)

    threading.Thread(target=_salir, daemon=True).start()


def _respuesta_cierre_desktop() -> Response:
    """Cierra el proceso; la ventana del navegador se termina por PID/perfil."""
    lg = normalize_lang(session.get("lang"))
    msg = tr(lg, "logout_cerrando")
    _limpiar_sesion_flask()
    html = (
        "<!doctype html><html lang='es'><head><meta charset='utf-8'>"
        f"<title>{APP_NAME}</title></head><body><p>{msg}</p></body></html>"
    )
    resp = Response(html, mimetype="text/html; charset=utf-8")
    _aplicar_borrado_cookie_sesion(resp)
    _iniciar_cierre_proceso_desktop()
    return resp


@app.route("/desktop/alive", methods=["GET", "POST"])
@csrf.exempt
def desktop_alive():
    """Latido de la ventana del .exe (solo localhost)."""
    if not _es_app_escritorio():
        abort(404)
    if not _peticion_desde_localhost():
        abort(403)
    visible = request.headers.get("X-Desktop-Visible", "1") != "0"
    _registrar_ui_desktop_viva(ventana_visible=visible)
    return "", 204


@app.route("/logout", methods=["GET", "POST"])
def logout():
    """Cierre de sesión solo por POST (+ CSRF). GET no muta (evita logout por img/link forzado)."""
    if request.method == "GET":
        if session.get("user"):
            return redirect(url_for("index"))
        return redirect(url_for("login"))
    _limpiar_sesion_flask()
    if getattr(sys, "frozen", False):
        return _respuesta_cierre_desktop()
    resp = redirect(url_for("login"))
    return _aplicar_borrado_cookie_sesion(resp)


@app.route("/desktop-quit", methods=["GET", "POST"])
@csrf.exempt
def desktop_quit():
    """Solo .exe local: cierra el proceso (sin consola no hay otra forma obvia de salir)."""
    if not getattr(sys, "frozen", False):
        abort(404)
    ra = (request.remote_addr or "").replace("::ffff:", "")
    if ra not in ("127.0.0.1", "::1"):
        abort(403)
    _limpiar_sesion_flask()
    return _respuesta_cierre_desktop()


MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@app.get("/")
def index():
    return render_template("inicio.html")


@app.get("/procesador")
def procesador():
    return render_template("index.html")


@app.get("/procesador/plantilla-imputacion")
def procesador_plantilla_imputacion():
    from cuit_en_arca.plantillas_importacion import ruta_plantilla_imputacion_contable_excel

    ruta = ruta_plantilla_imputacion_contable_excel()
    if not ruta.is_file():
        abort(404)
    return send_file(
        ruta,
        as_attachment=True,
        download_name="Formato imputacion contable.xlsx",
        mimetype=MIME_XLSX,
    )


@app.post("/procesador/cruce-lic-mcr")
def procesador_cruce_lic_mcr():
    from cruce_lic_mcr import procesar_cruce_lic_mcr

    lg = normalize_lang(session.get("lang"))
    f_lic = request.files.get("excel_libro_iva_compras")
    f_mcr = request.files.get("excel_mcr_cruce")
    has_lic = bool(f_lic and (f_lic.filename or "").strip())
    has_mcr = bool(f_mcr and (f_mcr.filename or "").strip())
    if not has_lic or not has_mcr:
        return render_template(
            "index.html",
            error=tr(lg, "err_cruce_lic_mcr_faltan_archivos"),
        )
    nombre_lic = Path(f_lic.filename).name
    nombre_mcr = Path(f_mcr.filename).name
    if not nombre_lic.lower().endswith(".xlsx") or not nombre_mcr.lower().endswith(
        ".xlsx"
    ):
        return render_template(
            "index.html",
            error=tr(lg, "err_cruce_lic_mcr_solo_xlsx"),
        )
    mapa_imputaciones, err_imp, _datos_imp, _imp_nombre = (
        _mapa_imputaciones_desde_peticion(lg)
    )
    if err_imp:
        return render_template("index.html", error=err_imp)
    try:
        contenido, meta = procesar_cruce_lic_mcr(
            f_lic.read(),
            f_mcr.read(),
            lic_nombre=nombre_lic,
            mcr_nombre=nombre_mcr,
            ui_lang=lg,
            mapa_imputaciones=mapa_imputaciones,
        )
    except ValueError as exc:
        return render_template("index.html", error=str(exc))
    except Exception as exc:
        return render_template(
            "index.html",
            error=tr(lg, "err_cruce_lic_mcr_proceso", exc=exc),
        )

    nombre_salida = f"cruce_{Path(nombre_lic).stem}_{Path(nombre_mcr).stem}.xlsx"
    download_id = uuid4().hex
    DESCARGAS[download_id] = (contenido, nombre_salida, MIME_XLSX)
    return render_template(
        "index.html",
        mostrar_resultado_cruce=True,
        cruce_total_mcr=meta["total_mcr"],
        cruce_total_lic=meta["total_lic"],
        cruce_total_faltantes=meta["total_cruce"],
        cruce_con_imputacion=meta.get("con_imputacion", False),
        download_id=download_id,
        nombre_salida=nombre_salida,
    )


@app.get("/descargar/<download_id>")
def descargar(download_id: str):
    item = DESCARGAS.get(download_id)
    if not item:
        lg = normalize_lang(session.get("lang"))
        return render_template("index.html", error=tr(lg, "err_download_gone"))

    contenido, nombre_salida, mime = item
    return send_file(
        io.BytesIO(contenido),
        as_attachment=True,
        download_name=nombre_salida,
        mimetype=mime,
    )


@app.post("/procesar")
def procesar():
    lg = normalize_lang(session.get("lang"))
    f_rec = request.files.get("excel_recibidos")
    f_emit = request.files.get("excel_emitidos")
    has_r = bool(f_rec and (f_rec.filename or "").strip())
    has_e = bool(f_emit and (f_emit.filename or "").strip())
    if not has_r and not has_e:
        return render_template("index.html", error=tr(lg, "err_select_file"))

    def _ext_ok(n: str) -> bool:
        nl = n.lower()
        return nl.endswith(".xlsx") or nl.endswith(".csv")

    mapa_imputaciones, err_imp, datos_imp_bytes, imp_nombre_orig = (
        _mapa_imputaciones_desde_peticion(lg)
    )
    if err_imp:
        return render_template("index.html", error=err_imp)

    nombre_guardar = (request.form.get("nombre_nueva_plantilla_imputacion") or "").strip()
    if (
        plantillas_imputacion_disponibles()
        and nombre_guardar
        and datos_imp_bytes is not None
        and imp_nombre_orig
    ):
        try:
            agregar_plantilla(nombre_guardar, datos_imp_bytes, imp_nombre_orig)
            flash(tr(lg, "flash_plantilla_guardada_ok", nombre=nombre_guardar), "success")
        except ValueError as exc:
            if str(exc) == "nombre_duplicado":
                flash(tr(lg, "flash_plantilla_nombre_duplicado"), "warning")
            elif str(exc) == "nombre_vacio":
                pass

    con_cols_imp = mapa_imputaciones is not None and has_r

    cuits_apoc: set[str] = set()
    apoc_txt_bytes: bytes | None = None
    apoc_txt_nombre = "FacturasApocrifas.txt"
    advertencia_apoc: str | None = None
    con_columna_apoc = has_r
    if has_r:
        cuits_apoc, apoc_txt_bytes, apoc_txt_nombre, advertencia_apoc = (
            _listado_apoc_para_mcr_recibidos(lg)
        )

    if has_r and has_e:
        nombre_r = Path(f_rec.filename).name
        nombre_e = Path(f_emit.filename).name
        if not _ext_ok(nombre_r) or not _ext_ok(nombre_e):
            return render_template("index.html", error=tr(lg, "err_only_xlsx_csv"))
        try:
            buf_r = io.BytesIO(f_rec.read())
            buf_e = io.BytesIO(f_emit.read())
            (
                df_r,
                tot_r,
                tpp_r,
                nce_r,
                tabla_r,
            ) = procesar_archivo(
                buf_r,
                0,
                nombre_archivo=nombre_r,
                ui_lang=lg,
                emitidos=False,
            )
            (
                df_e,
                tot_e,
                tpp_e,
                nce_e,
                tabla_e,
            ) = procesar_archivo(
                buf_e,
                0,
                nombre_archivo=nombre_e,
                ui_lang=lg,
                emitidos=True,
            )
        except ValueError as exc:
            return render_template("index.html", error=str(exc))
        except Exception as exc:
            return render_template(
                "index.html", error=tr(lg, "err_processing", exc=exc)
            )

        tabla_r = enriquecer_contrapartes_con_imputacion(tabla_r, mapa_imputaciones)
        res_imp_r = (
            resumen_totales_por_imputacion(tabla_r) if con_cols_imp else None
        )
        res_imp_e = None

        per_r = periodos_orden_crono(
            tpp_r,
            nce_r.get("neto_nc_por_periodo", {}),
            nce_r.get("iva_nc_por_periodo", {}),
        )
        per_e = periodos_orden_crono(
            tpp_e,
            nce_e.get("neto_nc_por_periodo", {}),
            nce_e.get("iva_nc_por_periodo", {}),
        )
        tres_r = {c: tot_r[c] for c in COLUMNAS_TOTAL_RESUMEN}
        tdet_r = {c: tot_r[c] for c in COLUMNAS_DETALLE_SIN_RESUMEN}
        tres_e = {c: tot_e[c] for c in COLUMNAS_TOTAL_RESUMEN}
        tdet_e = {c: tot_e[c] for c in COLUMNAS_DETALLE_SIN_RESUMEN}

        salida = io.BytesIO()
        escribir_excel_informe_dual(
            salida,
            df_recibidos=df_r,
            totales_por_periodo_rec=tpp_r,
            periodos_orden_rec=per_r,
            notas_credito_extras_rec=nce_r,
            totales_resumen_rec=tres_r,
            totales_detalle_rec=tdet_r,
            suma_total_rec=round(total_resumen_pantalla(tot_r), 2),
            tabla_contrapartes_rec=tabla_r,
            df_emitidos=df_e,
            totales_por_periodo_emit=tpp_e,
            periodos_orden_emit=per_e,
            notas_credito_extras_emit=nce_e,
            totales_resumen_emit=tres_e,
            totales_detalle_emit=tdet_e,
            suma_total_emit=round(total_resumen_pantalla(tot_e), 2),
            tabla_contrapartes_emit=tabla_e,
            columnas_orden=COLUMNAS_A_AJUSTAR,
            resumen_imputacion_rec=res_imp_r,
            resumen_imputacion_emit=res_imp_e,
            con_columnas_imputacion_en_contrapartes=con_cols_imp,
            mapa_imputaciones=mapa_imputaciones,
            cuits_apoc=cuits_apoc,
            con_columna_apoc=True,
        )
        contenido = salida.getvalue()
        nombre_salida = f"{Path(nombre_r).stem}_{Path(nombre_e).stem}_ajustado.xlsx"
        download_id = uuid4().hex
        DESCARGAS[download_id] = (contenido, nombre_salida, MIME_XLSX)
        apoc_txt_download_id = None
        if apoc_txt_bytes:
            apoc_txt_download_id = uuid4().hex
            DESCARGAS[apoc_txt_download_id] = (
                apoc_txt_bytes,
                apoc_txt_nombre,
                MIME_TXT,
            )

        return render_template(
            "index.html",
            mostrar_resultado=True,
            procesamiento_dual=True,
            totales_resumen_recibidos=tres_r,
            totales_detalle_recibidos=tdet_r,
            suma_total_recibidos=round(total_resumen_pantalla(tot_r), 2),
            totales_resumen_emitidos=tres_e,
            totales_detalle_emitidos=tdet_e,
            suma_total_emitidos=round(total_resumen_pantalla(tot_e), 2),
            columnas_orden=COLUMNAS_A_AJUSTAR,
            totales_por_periodo_recibidos=tpp_r,
            periodos_orden_recibidos=per_r,
            resumen_total_periodo_recibidos=totales_resumen_por_periodo(tpp_r),
            total_neto_nc_recibidos=nce_r["total_neto_nc"],
            total_iva_nc_recibidos=nce_r["total_iva_nc"],
            neto_nc_por_periodo_recibidos=nce_r["neto_nc_por_periodo"],
            iva_nc_por_periodo_recibidos=nce_r["iva_nc_por_periodo"],
            totales_por_periodo_emitidos=tpp_e,
            periodos_orden_emitidos=per_e,
            resumen_total_periodo_emitidos=totales_resumen_por_periodo(tpp_e),
            total_neto_nc_emitidos=nce_e["total_neto_nc"],
            total_iva_nc_emitidos=nce_e["total_iva_nc"],
            neto_nc_por_periodo_emitidos=nce_e["neto_nc_por_periodo"],
            iva_nc_por_periodo_emitidos=nce_e["iva_nc_por_periodo"],
            tabla_contrapartes_recibidos=tabla_r,
            tabla_contrapartes_emitidos=tabla_e,
            download_id=download_id,
            nombre_salida=nombre_salida,
            imputacion_activa=con_cols_imp,
            resumen_imputacion_recibidos=res_imp_r,
            resumen_imputacion_emitidos=res_imp_e,
            apoc_txt_download_id=apoc_txt_download_id,
            apoc_txt_nombre=apoc_txt_nombre,
            advertencia_apoc=advertencia_apoc,
        )

    emitidos = bool(has_e)
    archivo = f_emit if emitidos else f_rec
    nombre = Path(archivo.filename).name
    if not _ext_ok(nombre):
        return render_template("index.html", error=tr(lg, "err_only_xlsx_csv"))

    try:
        datos = archivo.read()
        buffer = io.BytesIO(datos)
        (
            df_ajustado,
            totales,
            totales_por_periodo,
            notas_credito_extras,
            tabla_contrapartes,
        ) = procesar_archivo(
            buffer,
            0,
            nombre_archivo=nombre,
            ui_lang=lg,
            emitidos=emitidos,
        )
    except ValueError as exc:
        return render_template("index.html", error=str(exc))
    except Exception as exc:  # fallback para errores no esperados
        return render_template(
            "index.html", error=tr(lg, "err_processing", exc=exc)
        )

    tabla_contrapartes = enriquecer_contrapartes_con_imputacion(
        tabla_contrapartes,
        mapa_imputaciones if (con_cols_imp and not emitidos) else None,
    )
    res_imp = (
        resumen_totales_por_imputacion(tabla_contrapartes) if con_cols_imp and not emitidos else None
    )

    salida = io.BytesIO()
    periodos_orden = periodos_orden_crono(
        totales_por_periodo,
        notas_credito_extras.get("neto_nc_por_periodo", {}),
        notas_credito_extras.get("iva_nc_por_periodo", {}),
    )
    totales_resumen = {c: totales[c] for c in COLUMNAS_TOTAL_RESUMEN}
    totales_detalle = {c: totales[c] for c in COLUMNAS_DETALLE_SIN_RESUMEN}
    escribir_excel_informe_completo(
        df_ajustado,
        salida,
        emitidos=emitidos,
        totales=totales,
        totales_por_periodo=totales_por_periodo,
        periodos_orden=periodos_orden,
        notas_credito_extras=notas_credito_extras,
        totales_resumen=totales_resumen,
        totales_detalle=totales_detalle,
        suma_total=round(total_resumen_pantalla(totales), 2),
        columnas_orden=COLUMNAS_A_AJUSTAR,
        tabla_contrapartes=tabla_contrapartes,
        resumen_imputacion=res_imp,
        con_columnas_imputacion_en_contrapartes=con_cols_imp,
        mapa_imputaciones=mapa_imputaciones,
        cuits_apoc=cuits_apoc if not emitidos else None,
        con_columna_apoc=con_columna_apoc and not emitidos,
    )
    contenido = salida.getvalue()

    nombre_salida = f"{Path(nombre).stem}_ajustado.xlsx"
    download_id = uuid4().hex
    DESCARGAS[download_id] = (contenido, nombre_salida, MIME_XLSX)
    apoc_txt_download_id = None
    if con_columna_apoc and apoc_txt_bytes:
        apoc_txt_download_id = uuid4().hex
        DESCARGAS[apoc_txt_download_id] = (
            apoc_txt_bytes,
            apoc_txt_nombre,
            MIME_TXT,
        )

    resumen_total_periodo = totales_resumen_por_periodo(totales_por_periodo)

    return render_template(
        "index.html",
        mostrar_resultado=True,
        procesamiento_dual=False,
        emitidos=emitidos,
        totales_resumen=totales_resumen,
        totales_detalle=totales_detalle,
        columnas_orden=COLUMNAS_A_AJUSTAR,
        suma_total=round(total_resumen_pantalla(totales), 2),
        totales_por_periodo=totales_por_periodo,
        periodos_orden=periodos_orden,
        resumen_total_periodo=resumen_total_periodo,
        total_neto_nc=notas_credito_extras["total_neto_nc"],
        total_iva_nc=notas_credito_extras["total_iva_nc"],
        neto_nc_por_periodo=notas_credito_extras["neto_nc_por_periodo"],
        iva_nc_por_periodo=notas_credito_extras["iva_nc_por_periodo"],
        tabla_contrapartes=tabla_contrapartes,
        download_id=download_id,
        nombre_salida=nombre_salida,
        imputacion_activa=con_cols_imp,
        resumen_imputacion=res_imp,
        apoc_txt_download_id=apoc_txt_download_id,
        apoc_txt_nombre=apoc_txt_nombre,
        advertencia_apoc=advertencia_apoc,
    )


@app.route("/plantillas-imputaciones", methods=["GET", "POST"])
def plantillas_imputaciones():
    if not plantillas_imputacion_disponibles():
        abort(404)
    lg = normalize_lang(session.get("lang"))
    if request.method == "POST":
        accion = (request.form.get("accion") or "").strip()
        pid = (request.form.get("plantilla_id") or "").strip()
        try:
            if accion == "renombrar":
                nuevo = (request.form.get("nuevo_nombre") or "").strip()
                renombrar_plantilla(pid, nuevo)
                flash(tr(lg, "flash_plantilla_renombrada"), "success")
            elif accion == "reemplazar":
                f_rep = request.files.get("nuevo_archivo")
                fn = (
                    (getattr(f_rep, "filename", None) or "").strip()
                    if f_rep
                    else ""
                )
                if not f_rep or not fn:
                    flash(tr(lg, "err_plantilla_archivo_falta"), "warning")
                else:
                    nl = fn.lower()
                    if not (nl.endswith(".xlsx") or nl.endswith(".csv")):
                        flash(tr(lg, "err_only_xlsx_csv"), "warning")
                    else:
                        reemplazar_archivo_plantilla(
                            pid, f_rep.read(), Path(fn).name
                        )
                        flash(tr(lg, "flash_plantilla_archivo_ok"), "success")
            elif accion == "eliminar":
                eliminar_plantilla(pid)
                flash(tr(lg, "flash_plantilla_eliminada"), "success")
            else:
                flash(tr(lg, "err_plantilla_accion"), "warning")
        except ValueError as exc:
            code = str(exc)
            if code == "nombre_duplicado":
                flash(tr(lg, "flash_plantilla_nombre_duplicado"), "warning")
            elif code == "nombre_vacio":
                flash(tr(lg, "err_plantilla_nombre_vacio"), "warning")
            elif code == "no_existe":
                flash(tr(lg, "err_plantilla_no_existe"), "warning")
            else:
                flash(tr(lg, "err_plantilla_generico"), "warning")
        return redirect(url_for("plantillas_imputaciones"))
    try:
        plantillas = listar_plantillas()
    except OSError:
        plantillas = []
    return render_template(
        "plantillas_imputaciones.html",
        plantillas=plantillas,
    )


def _filas_arca_desde_peticion(
    lg: str,
) -> tuple[list, list[str], str | None]:
    """Devuelve (filas, errores_parciales, mensaje_error | None)."""
    planilla = request.files.get("planilla_arca")
    has_file = bool(
        planilla and getattr(planilla, "filename", None) and str(planilla.filename).strip()
    )

    if has_file:
        if not Path(planilla.filename).name.lower().endswith(".xlsx"):
            return [], [], tr(lg, "err_arca_xlsx")
        try:
            filas, errores = leer_planilla_lote_con_errores(
                io.BytesIO(planilla.read())
            )
        except ArcaProcesoError as exc:
            return [], [], str(exc)
        if not filas:
            msg = "; ".join(errores) or tr(lg, "err_arca_xlsx")
            return [], errores, msg
        return filas, errores, None

    cuits_login = request.form.getlist("arca_cuit_login")
    claves = request.form.getlist("arca_clave_fiscal")
    cuits_repr = request.form.getlist("arca_cuit_representado")
    rangos = request.form.getlist("arca_rango_fechas")

    hay_algo = any(
        (v or "").strip()
        for lista in (cuits_login, claves, cuits_repr, rangos)
        for v in lista
    )
    if not hay_algo:
        return [], [], tr(lg, "err_arca_sin_datos")

    filas, errores = parsear_entradas_manuales(
        cuits_login, claves, cuits_repr, rangos
    )
    if not filas:
        msg = "; ".join(errores) or tr(lg, "err_arca_manual_incompleto")
        return [], errores, msg
    return filas, errores, None


@app.get("/arca-descarga-lote/plantilla")
def arca_plantilla():
    from cuit_en_arca.plantillas_importacion import ruta_plantilla_arca_excel

    ruta = ruta_plantilla_arca_excel()
    if not ruta.is_file():
        abort(404)
    return send_file(
        ruta,
        as_attachment=True,
        download_name="Formato Analisis Comprobantes.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.post("/arca-descarga-lote")
def arca_descarga_lote():
    lg = normalize_lang(session.get("lang"))
    if not _mostrar_ui_cuit_arca():
        if request.headers.get("X-Requested-With") == "fetch":
            return jsonify({"error": tr(lg, "err_arca_disabled")}), 403
        return (
            render_template(
                "index.html",
                error=tr(lg, "err_arca_disabled"),
            ),
            403,
        )

    filas, _errores_planilla, err_msg = _filas_arca_desde_peticion(lg)
    if err_msg:
        if request.headers.get("X-Requested-With") == "fetch":
            return jsonify({"error": err_msg}), 400
        return render_template("index.html", error=err_msg)

    err_cupo = _verificar_cupo_inicio(lg)
    if err_cupo:
        if request.headers.get("X-Requested-With") == "fetch":
            return jsonify({"error": err_cupo}), 403
        return render_template("index.html", error=err_cupo)

    # Imputación contable opcional: si se adjuntó un Excel en la solapa de
    # imputación o se eligió una plantilla guardada, se aplica al lote
    # (solo a comprobantes recibidos). Si no, el lote se procesa sin imputar.
    mapa_imputaciones, err_imp, _datos_imp, _imp_nom = (
        _mapa_imputaciones_desde_peticion(lg)
    )
    if err_imp:
        if request.headers.get("X-Requested-With") == "fetch":
            return jsonify({"error": err_imp}), 400
        return render_template("index.html", error=err_imp)

    carpeta_form = (request.form.get("carpeta_destino") or "").strip() or None

    job_id = uuid4().hex
    base, entrega = _fabricar_entrega(
        job_id,
        carpeta_form,
        lambda did, rel, nom: agregar_archivo_lote(job_id, did, rel, nom),
    )
    if base is None:
        msg = tr(lg, "carpeta_cancelada")
        if request.headers.get("X-Requested-With") == "fetch":
            return jsonify({"error": msg}), 400
        return render_template("index.html", error=msg)
    carpeta_destino = str(base)
    nombre_sesion_mc = _nombre_carpeta_web_sesion("Mis Comprobantes")

    def _err_inesperado(exc: Exception) -> str:
        return tr(lg, "err_arca_unexpected", exc=exc)

    from cuit_en_arca.cancelacion import reset_cancelacion

    reset_cancelacion(job_id)
    crear_job(job_id, len(filas))
    from cuit_en_arca.entrega_web import envolver_log_con_entrega

    on_prog = _wrap_progreso_con_entrega(callback_progreso(job_id), entrega)
    on_paso = callback_paso(job_id)
    on_log = envolver_log_con_entrega(callback_log_lote(job_id), entrega)
    hay_cupo, on_cuit_exitoso = _control_cupo_sesion()
    usuario_cupo_job = _usuario_cupo_web()
    reg_valor = _registro_valor_sesion()

    headless = _headless_desde_peticion()

    def _on_reiniciar() -> None:
        reiniciar_pasos(job_id)

    def _worker() -> None:
        try:
            on_log(f"Iniciando descarga de Mis Comprobantes ({len(filas)} fila(s))…")
            resultado = ejecutar_lote_arca(
                filas,
                errores_planilla=_errores_planilla,
                on_progreso=on_prog,
                on_paso=on_paso,
                on_log=on_log,
                on_reiniciar_pasos=_on_reiniciar,
                mapa_imputaciones=mapa_imputaciones,
                carpeta_destino=carpeta_destino,
                job_id=job_id,
                nombre_carpeta_sesion=nombre_sesion_mc,
                hay_cupo=hay_cupo,
                on_cuit_exitoso=on_cuit_exitoso,
                usuario_cupo=usuario_cupo_job,
                registrar_valor_mc=reg_valor.mc if reg_valor else None,
                headless=headless,
            )
            if entrega:
                entrega.escanear()
            if resultado.carpeta:
                # Modo carpeta: los archivos ya están en disco, sin descarga.
                fallos = list(resultado.ingresos_fallidos) + list(resultado.advertencias)
                marcar_ok(
                    job_id,
                    nombre_archivo=resultado.nombre_archivo,
                    carpeta=resultado.carpeta,
                    descargas_ok=resultado.descargas_ok,
                    ingresos_fallidos=len(resultado.ingresos_fallidos),
                    fallos_detalle=fallos,
                )
                return
            did = uuid4().hex
            DESCARGAS[did] = (
                resultado.contenido,
                resultado.nombre_archivo,
                resultado.mimetype,
            )
            marcar_ok(
                job_id,
                download_id=did,
                nombre_archivo=resultado.nombre_archivo,
                descargas_ok=resultado.descargas_ok,
                ingresos_fallidos=len(resultado.ingresos_fallidos),
                fallos_detalle=list(resultado.ingresos_fallidos) + list(resultado.advertencias),
            )
        except CancelacionUsuarioError as exc:
            marcar_cancelado(job_id, str(exc))
        except ArcaProcesoError as exc:
            marcar_error(job_id, str(exc))
        except Exception as exc:
            marcar_error(job_id, _err_inesperado(exc))

    threading.Thread(target=_worker, daemon=True).start()

    if request.headers.get("X-Requested-With") == "fetch":
        return jsonify({"job_id": job_id, "total": len(filas)})

    return render_template(
        "index.html",
        arca_job_id=job_id,
        arca_job_total=len(filas),
    )


@app.get("/arca-lote-estado/<job_id>")
def arca_lote_estado(job_id: str):
    estado = obtener_job(job_id)
    if estado is None:
        return jsonify({"error": "job_not_found"}), 404
    return jsonify(estado)


# --------------------------------------------------------------------------- #
# Domicilio Fiscal Electrónico (Ventanilla Electrónica)
# --------------------------------------------------------------------------- #
def _filas_dfe_desde_peticion(lg: str):
    """Devuelve (filas, errores_planilla, mensaje_error)."""
    f = request.files.get("dfe_excel")
    has_file = bool(f and getattr(f, "filename", None) and str(f.filename).strip())
    if has_file:
        nombre = Path(f.filename).name
        if not nombre.lower().endswith(".xlsx"):
            return [], [], tr(lg, "err_only_xlsx_csv")
        try:
            filas, errores = leer_planilla_lote_con_errores(io.BytesIO(f.read()))
        except ArcaProcesoError as exc:
            return [], [], str(exc)
        if not filas:
            return [], errores, "; ".join(errores) or tr(lg, "dfe_err_sin_datos")
        return filas, errores, None

    cuits = request.form.getlist("dfe_cuit_login")
    claves = request.form.getlist("dfe_clave_fiscal")
    reprs = request.form.getlist("dfe_cuit_representado")
    desdes = request.form.getlist("dfe_fecha_desde")
    hastas = request.form.getlist("dfe_fecha_hasta")

    hay_algo = any(
        (v or "").strip()
        for lista in (cuits, claves, reprs, desdes, hastas)
        for v in lista
    )
    if not hay_algo:
        return [], [], tr(lg, "dfe_err_sin_datos")

    def _at(lista, i):
        return (lista[i] if i < len(lista) else "").strip()

    n = max(len(cuits), len(claves), len(reprs), len(desdes), len(hastas))
    rangos = []
    for i in range(n):
        d = _at(desdes, i)
        h = _at(hastas, i)
        rangos.append(f"{d} - {h}" if (d or h) else "")

    filas, errores = parsear_entradas_manuales(cuits, claves, reprs, rangos)
    if not filas:
        return [], errores, "; ".join(errores) or tr(lg, "dfe_err_manual_incompleto")
    return filas, errores, None


@app.get("/domicilio-fiscal")
def domicilio_fiscal():
    return render_template("dfe.html")


@app.get("/domicilio-fiscal/plantilla")
def dfe_plantilla():
    from cuit_en_arca.dfe_automation import ruta_plantilla_dfe_excel

    ruta = ruta_plantilla_dfe_excel()
    if not ruta.is_file():
        abort(404)
    return send_file(
        ruta,
        as_attachment=True,
        download_name="Formato DFE.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.post("/dfe-descargar")
def dfe_descargar():
    lg = normalize_lang(session.get("lang"))
    es_fetch = request.headers.get("X-Requested-With") == "fetch"

    if not _mostrar_ui_cuit_arca():
        if es_fetch:
            return jsonify({"error": tr(lg, "err_arca_disabled")}), 403
        return render_template("dfe.html", error=tr(lg, "err_arca_disabled")), 403

    filas, _errores, err_msg = _filas_dfe_desde_peticion(lg)
    if err_msg:
        if es_fetch:
            return jsonify({"error": err_msg}), 400
        return render_template("dfe.html", error=err_msg)

    err_cupo = _verificar_cupo_inicio(lg)
    if err_cupo:
        if es_fetch:
            return jsonify({"error": err_cupo}), 403
        return render_template("dfe.html", error=err_cupo)

    from cuit_en_arca.dfe_automation import ejecutar_dfe_lote

    headless = _headless_desde_peticion()

    carpeta_form = (request.form.get("carpeta_destino") or "").strip() or None

    job_id = uuid4().hex
    base, entrega = _fabricar_entrega(
        job_id,
        carpeta_form,
        lambda did, rel, nom: agregar_archivo_dfe(job_id, did, rel, nom),
    )
    if base is None:
        msg = tr(lg, "carpeta_cancelada")
        if es_fetch:
            return jsonify({"error": msg}), 400
        return render_template("dfe.html", error=msg)
    carpeta_destino = str(base)
    nombre_sesion_dfe = _nombre_carpeta_web_sesion("DFE")

    def _err_inesperado(exc: Exception) -> str:
        return tr(lg, "err_arca_unexpected", exc=exc)

    from cuit_en_arca.cancelacion import reset_cancelacion
    from cuit_en_arca.entrega_web import envolver_log_con_entrega

    reset_cancelacion(job_id)
    crear_job_dfe(job_id, len(filas))
    reiniciar_pasos_dfe(job_id)
    on_log = envolver_log_con_entrega(callback_log_dfe(job_id), entrega)
    on_paso = callback_paso_dfe(job_id)
    hay_cupo, on_cuit_exitoso = _control_cupo_sesion()
    usuario_cupo_job = _usuario_cupo_web()
    reg_valor = _registro_valor_sesion()

    def _reinit() -> None:
        reiniciar_pasos_dfe(job_id)

    def _prog(actual: int, total: int, msg: str) -> None:
        progreso_cuit_dfe(job_id, actual, total, msg)

    def _cuit_fin(cuit, razon_social, total_archivos, error) -> None:
        agregar_resumen_cuit_dfe(
            job_id,
            cuit=cuit,
            razon_social=razon_social,
            total_archivos=total_archivos,
            error=error,
        )
        if entrega:
            entrega.escanear()

    def _worker() -> None:
        try:
            progreso_cuit_dfe(job_id, 0, len(filas), "Iniciando…")
            carpeta = ejecutar_dfe_lote(
                filas,
                headless=headless,
                on_log=on_log,
                on_paso=on_paso,
                on_reiniciar_pasos=_reinit,
                on_progreso=_prog,
                on_cuit_fin=_cuit_fin,
                carpeta_base=carpeta_destino,
                job_id=job_id,
                nombre_carpeta_sesion=nombre_sesion_dfe,
                hay_cupo=hay_cupo,
                on_cuit_exitoso=on_cuit_exitoso,
                usuario_cupo=usuario_cupo_job,
                registrar_valor_dfe=reg_valor.dfe if reg_valor else None,
            )
            if entrega:
                entrega.escanear()
            marcar_ok_dfe(job_id, carpeta=str(carpeta))
        except CancelacionUsuarioError as exc:
            marcar_cancelado_dfe(job_id, str(exc))
        except ArcaProcesoError as exc:
            marcar_error_dfe(job_id, str(exc))
        except Exception as exc:
            marcar_error_dfe(job_id, _err_inesperado(exc))

    threading.Thread(target=_worker, daemon=True).start()

    if es_fetch:
        return jsonify({"job_id": job_id, "total": len(filas)})
    return render_template("dfe.html", dfe_job_id=job_id)


@app.get("/dfe-estado/<job_id>")
def dfe_estado(job_id: str):
    estado = obtener_job_dfe(job_id)
    if estado is None:
        return jsonify({"error": "job_not_found"}), 404
    return jsonify(estado)


# --------------------------------------------------------------------------- #
# Ventas y Liquidaciones (Liquidaciones primarias de granos)
# --------------------------------------------------------------------------- #
def _filas_vl_desde_peticion(lg: str):
    """Devuelve (filas, errores_planilla, mensaje_error)."""
    from cuit_en_arca.planilla_vl import (
        leer_planilla_vl_con_errores,
        parsear_entradas_manuales_vl,
    )

    f = request.files.get("vl_excel")
    has_file = bool(f and getattr(f, "filename", None) and str(f.filename).strip())
    if has_file:
        nombre = Path(f.filename).name
        if not nombre.lower().endswith(".xlsx"):
            return [], [], tr(lg, "err_only_xlsx_csv")
        try:
            filas, errores = leer_planilla_vl_con_errores(io.BytesIO(f.read()))
        except ArcaProcesoError as exc:
            return [], [], str(exc)
        if not filas:
            return [], errores, "; ".join(errores) or tr(lg, "vl_err_sin_datos")
        return filas, errores, None

    cuits = request.form.getlist("vl_cuit_login")
    claves = request.form.getlist("vl_clave_fiscal")
    nombres = request.form.getlist("vl_nombre_representado")
    desdes = request.form.getlist("vl_fecha_desde")
    hastas = request.form.getlist("vl_fecha_hasta")

    hay_algo = any(
        (v or "").strip()
        for lista in (cuits, claves, nombres, desdes, hastas)
        for v in lista
    )
    if not hay_algo:
        return [], [], tr(lg, "vl_err_sin_datos")

    filas, errores = parsear_entradas_manuales_vl(
        cuits, claves, nombres, desdes, hastas
    )
    if not filas:
        return [], errores, "; ".join(errores) or tr(lg, "vl_err_manual_incompleto")
    return filas, errores, None


@app.get("/ventas-liquidaciones")
def ventas_liquidaciones():
    return render_template("ventas_liquidaciones.html")


@app.get("/ventas-liquidaciones/plantilla")
def vl_plantilla():
    from cuit_en_arca.vl_automation import ruta_plantilla_vl_excel

    ruta = ruta_plantilla_vl_excel()
    if not ruta.is_file():
        abort(404)
    return send_file(
        ruta,
        as_attachment=True,
        download_name="Formato VyL.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.post("/vl-descargar")
def vl_descargar():
    lg = normalize_lang(session.get("lang"))
    es_fetch = request.headers.get("X-Requested-With") == "fetch"

    if not _mostrar_ui_cuit_arca():
        if es_fetch:
            return jsonify({"error": tr(lg, "err_arca_disabled")}), 403
        return render_template("ventas_liquidaciones.html", error=tr(lg, "err_arca_disabled")), 403

    filas, _errores, err_msg = _filas_vl_desde_peticion(lg)
    if err_msg:
        if es_fetch:
            return jsonify({"error": err_msg}), 400
        return render_template("ventas_liquidaciones.html", error=err_msg)

    err_cupo = _verificar_cupo_inicio(lg)
    if err_cupo:
        if es_fetch:
            return jsonify({"error": err_cupo}), 403
        return render_template("ventas_liquidaciones.html", error=err_cupo)

    sistemas = [
        s
        for s in request.form.getlist("vl_sistemas")
        if s in ("granos", "certificados", "hacienda")
    ]
    if not sistemas:
        msg = tr(lg, "vl_err_sin_sistema")
        if es_fetch:
            return jsonify({"error": msg}), 400
        return render_template("ventas_liquidaciones.html", error=msg)

    from cuit_en_arca.vl_automation import ejecutar_vl_lote

    headless = _headless_desde_peticion()

    carpeta_form = (request.form.get("carpeta_destino") or "").strip() or None

    job_id = uuid4().hex
    base, entrega = _fabricar_entrega(
        job_id,
        carpeta_form,
        lambda did, rel, nom: agregar_archivo_vl(job_id, did, rel, nom),
    )
    if base is None:
        msg = tr(lg, "carpeta_cancelada")
        if es_fetch:
            return jsonify({"error": msg}), 400
        return render_template("ventas_liquidaciones.html", error=msg)
    carpeta_destino = str(base)
    nombre_sesion_vl = _nombre_carpeta_web_sesion("Ventas y Liquidaciones")

    def _err_inesperado(exc: Exception) -> str:
        return tr(lg, "err_arca_unexpected", exc=exc)

    from cuit_en_arca.cancelacion import reset_cancelacion
    from cuit_en_arca.entrega_web import envolver_log_con_entrega

    reset_cancelacion(job_id)
    crear_job_vl(job_id, len(filas), sistemas=sistemas)
    reiniciar_pasos_vl(job_id, sistemas)
    on_log = envolver_log_con_entrega(callback_log_vl(job_id), entrega)
    on_paso = callback_paso_vl(job_id)
    hay_cupo, on_cuit_exitoso = _control_cupo_sesion()
    usuario_cupo_job = _usuario_cupo_web()
    generar_resumen_excel_vl = "certificados" in sistemas
    reg_valor = _registro_valor_sesion()

    def _reinit() -> None:
        reiniciar_pasos_vl(job_id)

    def _prog(actual: int, total: int, msg: str) -> None:
        progreso_cuit_vl(job_id, actual, total, msg)

    def _cuit_fin(cuit, razon_social, total_archivos, error) -> None:
        agregar_resumen_cuit_vl(
            job_id,
            cuit=cuit,
            razon_social=razon_social,
            total_archivos=total_archivos,
            error=error,
        )
        if entrega:
            entrega.escanear()

    def _worker() -> None:
        try:
            progreso_cuit_vl(job_id, 0, len(filas), "Iniciando…")
            carpeta = ejecutar_vl_lote(
                filas,
                sistemas=sistemas,
                generar_resumen_excel=generar_resumen_excel_vl,
                headless=headless,
                on_log=on_log,
                on_paso=on_paso,
                on_reiniciar_pasos=_reinit,
                on_progreso=_prog,
                on_cuit_fin=_cuit_fin,
                carpeta_base=carpeta_destino,
                job_id=job_id,
                nombre_carpeta_sesion=nombre_sesion_vl,
                hay_cupo=hay_cupo,
                on_cuit_exitoso=on_cuit_exitoso,
                usuario_cupo=usuario_cupo_job,
                registrar_valor_vl=reg_valor.vl if reg_valor else None,
            )
            if entrega:
                entrega.escanear()
            marcar_ok_vl(job_id, carpeta=str(carpeta))
        except CancelacionUsuarioError as exc:
            marcar_cancelado_vl(job_id, str(exc))
        except ArcaProcesoError as exc:
            marcar_error_vl(job_id, str(exc))
        except Exception as exc:
            marcar_error_vl(job_id, _err_inesperado(exc))

    threading.Thread(target=_worker, daemon=True).start()

    if es_fetch:
        return jsonify({"job_id": job_id, "total": len(filas)})
    return render_template("ventas_liquidaciones.html", vl_job_id=job_id)


@app.get("/vl-estado/<job_id>")
def vl_estado(job_id: str):
    estado = obtener_job_vl(job_id)
    if estado is None:
        return jsonify({"error": "job_not_found"}), 404
    return jsonify(estado)


# --------------------------------------------------------------------------- #
# Inversiones financieras — Análisis FCI (solo administrador)
# --------------------------------------------------------------------------- #
@app.get("/inversiones-financieras")
def inversiones_financieras():
    return render_template("inversiones_financieras.html")


# --------------------------------------------------------------------------- #
# Facturador (solo administrador)
# --------------------------------------------------------------------------- #
def _facturador_contexto_plantilla() -> dict:
    from cuit_en_arca.planilla_facturador import listar_tipos_comprobante_modelo

    return {"tipos_comprobante": listar_tipos_comprobante_modelo()}


def _filas_facturador_desde_peticion(lg: str):
    """Devuelve (filas, errores_planilla, mensaje_error)."""
    from cuit_en_arca.planilla_facturador import (
        construir_filas_express,
        leer_planilla_facturador_con_errores,
    )

    f = request.files.get("fact_excel")
    has_file = bool(f and getattr(f, "filename", None) and str(f.filename).strip())
    if has_file:
        nombre = Path(f.filename).name
        if not nombre.lower().endswith(".xlsx"):
            return [], [], tr(lg, "err_only_xlsx_csv")
        try:
            filas, errores = leer_planilla_facturador_con_errores(io.BytesIO(f.read()))
        except ArcaProcesoError as exc:
            return [], [], str(exc)
        if not filas:
            return [], errores, "; ".join(errores) or tr(lg, "fact_err_sin_datos")
        return filas, errores, None

    hay_algo = any(
        (v or "").strip()
        for v in (
            request.form.get("express_cuit_login"),
            request.form.get("express_clave_fiscal"),
            request.form.get("express_representado"),
            request.form.get("express_punto_venta"),
            *request.form.getlist("express_producto"),
            *request.form.getlist("express_tipo"),
            *request.form.getlist("express_cantidad"),
            *request.form.getlist("express_precio"),
        )
    )
    if not hay_algo:
        return [], [], tr(lg, "fact_err_sin_datos")

    filas, errores = construir_filas_express(
        cuit_login=request.form.get("express_cuit_login") or "",
        clave_fiscal=request.form.get("express_clave_fiscal") or "",
        representado=request.form.get("express_representado") or "",
        punto_venta=request.form.get("express_punto_venta") or "",
        fechas=request.form.getlist("express_fecha"),
        tipos=request.form.getlist("express_tipo"),
        conceptos=request.form.getlist("express_concepto"),
        productos=request.form.getlist("express_producto"),
        cantidades=request.form.getlist("express_cantidad"),
        precios=request.form.getlist("express_precio"),
    )
    if not filas:
        return [], errores, "; ".join(errores) or tr(lg, "fact_err_express_incompleto")
    return filas, errores, None


@app.get("/facturador")
def facturador():
    return render_template("facturador.html", **_facturador_contexto_plantilla())


@app.get("/facturador/plantilla")
def facturador_plantilla():
    from cuit_en_arca.facturador_automation import ruta_plantilla_facturador_excel

    ruta = ruta_plantilla_facturador_excel()
    if not ruta.is_file():
        abort(404)
    return send_file(
        ruta,
        as_attachment=True,
        download_name="Formato Comprobantes en Linea.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.post("/facturador/emitir")
def facturador_emitir():
    lg = normalize_lang(session.get("lang"))
    es_fetch = request.headers.get("X-Requested-With") == "fetch"
    ctx = _facturador_contexto_plantilla()

    if not _mostrar_ui_cuit_arca():
        msg = tr(lg, "err_arca_disabled")
        if es_fetch:
            return jsonify({"error": msg}), 403
        return render_template("facturador.html", error=msg, **ctx), 403

    filas, _errores, err_msg = _filas_facturador_desde_peticion(lg)
    if err_msg:
        if es_fetch:
            return jsonify({"error": err_msg}), 400
        return render_template("facturador.html", error=err_msg, **ctx), 400

    from cuit_en_arca.cancelacion import reset_cancelacion
    from cuit_en_arca.facturador_automation import ejecutar_facturador_lote
    from cuit_en_arca.progreso_facturador import (
        callback_log_facturador,
        callback_paso_facturador,
        crear_job_facturador,
        finalizar_job_facturador,
        marcar_cancelado_facturador,
        progreso_facturador,
        reiniciar_pasos_facturador,
    )

    job_id = uuid4().hex
    reset_cancelacion(job_id)
    crear_job_facturador(job_id, len(filas))
    reiniciar_pasos_facturador(job_id)
    on_log = callback_log_facturador(job_id)
    on_paso = callback_paso_facturador(job_id)
    headless = _headless_desde_peticion()

    def _worker() -> None:
        try:
            progreso_facturador(job_id, 0, len(filas), "Iniciando…")
            resultado = ejecutar_facturador_lote(
                filas,
                headless=headless,
                on_log=on_log,
                on_paso=on_paso,
                on_progreso=lambda a, t, m: progreso_facturador(job_id, a, t, m),
                job_id=job_id,
            )
            resumen = [
                {
                    "fila": r.fila_excel,
                    "representado": r.representado,
                    "tipo": r.tipo_comprobante,
                    "comprobante": r.comprobante,
                    "error": r.error,
                }
                for r in resultado.filas
            ]
            finalizar_job_facturador(
                job_id,
                ok=resultado.ok,
                fallidos=resultado.fallidos,
                resumen=resumen,
            )
        except Exception as exc:
            from cuit_en_arca.cancelacion import DescargaCanceladaError

            if isinstance(exc, DescargaCanceladaError):
                marcar_cancelado_facturador(job_id, str(exc))
            else:
                finalizar_job_facturador(
                    job_id, ok=0, fallidos=len(filas), resumen=[], error=str(exc)
                )

    threading.Thread(target=_worker, daemon=True).start()
    if es_fetch:
        return jsonify({"job_id": job_id, "total": len(filas)})
    return render_template("facturador.html", fact_job_id=job_id, **ctx)


@app.get("/facturador/estado/<job_id>")
def facturador_estado(job_id: str):
    from cuit_en_arca.progreso_facturador import obtener_estado_facturador

    estado = obtener_estado_facturador(job_id)
    if estado is None:
        return jsonify({"error": "job_not_found"}), 404
    return jsonify(estado)


# --------------------------------------------------------------------------- #
# Nuestra Parte
# --------------------------------------------------------------------------- #
def _filas_np_desde_peticion(lg: str):
    """Devuelve (filas, errores_planilla, mensaje_error) para Nuestra Parte."""
    f = request.files.get("np_excel")
    has_file = bool(f and getattr(f, "filename", None) and str(f.filename).strip())
    if has_file:
        nombre = Path(f.filename).name
        if not nombre.lower().endswith(".xlsx"):
            return [], [], tr(lg, "err_only_xlsx_csv")
        try:
            filas, errores = leer_planilla_np_con_errores(io.BytesIO(f.read()))
        except ArcaProcesoError as exc:
            return [], [], str(exc)
        if not filas:
            return [], errores, "; ".join(errores) or tr(lg, "np_err_sin_datos")
        return filas, errores, None

    cuits = request.form.getlist("np_cuit_login")
    claves = request.form.getlist("np_clave_fiscal")
    reprs = request.form.getlist("np_cuit_representado")
    ejercicios = request.form.getlist("np_ejercicio")

    hay_algo = any(
        (v or "").strip()
        for lista in (cuits, claves, reprs, ejercicios)
        for v in lista
    )
    if not hay_algo:
        return [], [], tr(lg, "np_err_sin_datos")

    filas, errores = parsear_entradas_manuales_np(cuits, claves, reprs, ejercicios)
    if not filas:
        return [], errores, "; ".join(errores) or tr(lg, "np_err_manual_incompleto")
    return filas, errores, None


@app.get("/nuestra-parte/plantilla")
def np_plantilla():
    from cuit_en_arca.plantillas_importacion import ruta_plantilla_np_excel

    ruta = ruta_plantilla_np_excel()
    if not ruta.is_file():
        abort(404)
    return send_file(
        ruta,
        as_attachment=True,
        download_name="Formato Nuestra Parte.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.get("/nuestra-parte")
def nuestra_parte():
    return render_template("nuestra_parte.html")


@app.post("/np-descargar")
def np_descargar():
    lg = normalize_lang(session.get("lang"))
    es_fetch = request.headers.get("X-Requested-With") == "fetch"

    if not _mostrar_ui_cuit_arca():
        if es_fetch:
            return jsonify({"error": tr(lg, "err_arca_disabled")}), 403
        return render_template("nuestra_parte.html", error=tr(lg, "err_arca_disabled")), 403

    filas, _errores, err_msg = _filas_np_desde_peticion(lg)
    if err_msg:
        if es_fetch:
            return jsonify({"error": err_msg}), 400
        return render_template("nuestra_parte.html", error=err_msg)

    err_cupo = _verificar_cupo_inicio(lg)
    if err_cupo:
        if es_fetch:
            return jsonify({"error": err_cupo}), 403
        return render_template("nuestra_parte.html", error=err_cupo)

    from cuit_en_arca.nuestra_parte_automation import ejecutar_nuestra_parte_lote

    headless = _headless_desde_peticion()
    carpeta_form = (request.form.get("carpeta_destino") or "").strip() or None

    job_id = uuid4().hex
    base, entrega = _fabricar_entrega(
        job_id,
        carpeta_form,
        lambda did, rel, nom: agregar_archivo_np(job_id, did, rel, nom),
    )
    if base is None:
        msg = tr(lg, "carpeta_cancelada")
        if es_fetch:
            return jsonify({"error": msg}), 400
        return render_template("nuestra_parte.html", error=msg)
    carpeta_destino = str(base)
    nombre_sesion_np = _nombre_carpeta_web_sesion("Nuestra Parte")

    def _err_inesperado(exc: Exception) -> str:
        return tr(lg, "err_arca_unexpected", exc=exc)

    from cuit_en_arca.cancelacion import reset_cancelacion
    from cuit_en_arca.entrega_web import envolver_log_con_entrega

    reset_cancelacion(job_id)
    crear_job_np(job_id, len(filas))
    reiniciar_pasos_np(job_id)
    on_log = envolver_log_con_entrega(callback_log_np(job_id), entrega)
    on_paso = callback_paso_np(job_id)
    hay_cupo, on_cuit_exitoso = _control_cupo_sesion()
    usuario_cupo_job = _usuario_cupo_web()
    reg_valor = _registro_valor_sesion()

    def _reinit() -> None:
        reiniciar_pasos_np(job_id)

    def _prog(actual: int, total: int, msg: str) -> None:
        progreso_cuit_np(job_id, actual, total, msg)

    def _cuit_fin(cuit, razon_social, total_archivos, error) -> None:
        agregar_resumen_cuit_np(
            job_id,
            cuit=cuit,
            razon_social=razon_social,
            total_archivos=total_archivos,
            error=error,
        )
        if entrega:
            entrega.escanear()

    def _worker() -> None:
        try:
            progreso_cuit_np(job_id, 0, len(filas), "Iniciando…")
            carpeta = ejecutar_nuestra_parte_lote(
                filas,
                headless=headless,
                on_log=on_log,
                on_paso=on_paso,
                on_reiniciar_pasos=_reinit,
                on_progreso=_prog,
                on_cuit_fin=_cuit_fin,
                carpeta_base=carpeta_destino,
                job_id=job_id,
                nombre_carpeta_sesion=nombre_sesion_np,
                hay_cupo=hay_cupo,
                on_cuit_exitoso=on_cuit_exitoso,
                usuario_cupo=usuario_cupo_job,
                registrar_valor_np=reg_valor.np if reg_valor else None,
            )
            if entrega:
                entrega.escanear()
            marcar_ok_np(job_id, carpeta=str(carpeta))
        except CancelacionUsuarioError as exc:
            marcar_cancelado_np(job_id, str(exc))
        except ArcaProcesoError as exc:
            marcar_error_np(job_id, str(exc))
        except Exception as exc:
            marcar_error_np(job_id, _err_inesperado(exc))

    threading.Thread(target=_worker, daemon=True).start()

    if es_fetch:
        return jsonify({"job_id": job_id, "total": len(filas)})
    return render_template("nuestra_parte.html", np_job_id=job_id)


@app.get("/np-estado/<job_id>")
def np_estado(job_id: str):
    estado = obtener_job_np(job_id)
    if estado is None:
        return jsonify({"error": "job_not_found"}), 404
    return jsonify(estado)


# --------------------------------------------------------------------------- #
# Análisis Programado
# --------------------------------------------------------------------------- #
def _filas_ap_desde_peticion(lg: str):
    from cuit_en_arca.planilla_analisis_programado import leer_planilla_analisis_programado

    f = request.files.get("ap_excel")
    has_file = bool(f and getattr(f, "filename", None) and str(f.filename).strip())
    if has_file:
        nombre = Path(f.filename).name
        if not nombre.lower().endswith(".xlsx"):
            return [], [], tr(lg, "err_only_xlsx_csv")
        try:
            filas, errores = leer_planilla_analisis_programado(io.BytesIO(f.read()))
        except ArcaProcesoError as exc:
            return [], [], str(exc)
        if not filas:
            return [], errores, "; ".join(errores) or tr(lg, "ap_err_sin_datos")
        return filas, errores, None

    return _filas_ap_desde_manual(lg)


def _filas_ap_desde_manual(lg: str):
    from cuit_en_arca.planilla_analisis_programado import parsear_entradas_manuales_ap

    cuits = request.form.getlist("ap_cuit")
    claves = request.form.getlist("ap_clave")
    reprs = request.form.getlist("ap_repr")
    fechas_mc = request.form.getlist("ap_fechas_mc")
    dfe_desde = request.form.getlist("ap_dfe_desde")
    dfe_hasta = request.form.getlist("ap_dfe_hasta")
    ejercicios = request.form.getlist("ap_ejercicio")
    repr_liq = request.form.getlist("ap_repr_liq")
    liq_desde = request.form.getlist("ap_liq_desde")
    liq_hasta = request.form.getlist("ap_liq_hasta")

    hay = any(
        (v or "").strip()
        for lst in (
            cuits,
            claves,
            reprs,
            fechas_mc,
            dfe_desde,
            dfe_hasta,
            ejercicios,
            repr_liq,
            liq_desde,
            liq_hasta,
        )
        for v in lst
    )
    if not hay:
        return [], [], tr(lg, "ap_err_sin_datos")

    filas, errores = parsear_entradas_manuales_ap(
        cuits,
        claves,
        reprs,
        fechas_mc,
        dfe_desde,
        dfe_hasta,
        ejercicios,
        repr_liq,
        liq_desde,
        liq_hasta,
    )
    if not filas:
        return [], errores, "; ".join(errores) or tr(lg, "ap_err_sin_datos")
    return filas, errores, None


def _filas_ap_a_dict(filas) -> list[dict]:
    from dataclasses import asdict

    return [asdict(f) for f in filas]


def _cfg_ap_desde_peticion(lg: str, *, solo_ejecucion: bool = False):
    """Arma la config desde el formulario. Devuelve (cfg, err_msg)."""
    from cuit_en_arca.analisis_programado import ConfigAnalisisProgramado, cargar_config

    sistemas = [
        s
        for s in request.form.getlist("ap_sistemas")
        if s in ("mis_comprobantes", "dfe", "nuestra_parte", "liquidaciones")
    ]
    if not sistemas:
        return None, tr(lg, "ap_err_sin_sistema")

    carpeta = (request.form.get("carpeta_destino") or "").strip()
    if _es_app_escritorio() and not carpeta:
        return None, tr(lg, "ap_err_sin_carpeta")
    if not _es_app_escritorio():
        from cuit_en_arca.entrega_web import carpeta_ap_servidor

        carpeta = str(carpeta_ap_servidor())

    filas, _errores, err_msg = _filas_ap_desde_peticion(lg)
    if err_msg:
        return None, err_msg

    filas_dict = _filas_ap_a_dict(filas)

    if solo_ejecucion:
        prev = cargar_config()
        usuario_cupo = _usuario_cupo_web() or (prev.usuario_cupo or "").strip()
        cfg = ConfigAnalisisProgramado(
            activo=prev.activo,
            dia_semana=prev.dia_semana,
            hora=prev.hora,
            minuto=prev.minuto,
            sistemas=sistemas,
            carpeta_destino=carpeta,
            filas=filas_dict,
            ultima_ejecucion=prev.ultima_ejecucion,
            ultimo_resultado=prev.ultimo_resultado,
            usuario_cupo=usuario_cupo,
        )
        return cfg, None

    try:
        dia = int(request.form.get("ap_dia_semana", "0"))
        hora = int(request.form.get("ap_hora", "9"))
        minuto = int(request.form.get("ap_minuto", "0"))
    except ValueError:
        dia, hora, minuto = 0, 9, 0

    cfg = ConfigAnalisisProgramado(
        activo=True,
        dia_semana=max(0, min(6, dia)),
        hora=max(0, min(23, hora)),
        minuto=max(0, min(59, minuto)),
        sistemas=sistemas,
        carpeta_destino=carpeta,
        filas=filas_dict,
        ultima_ejecucion=None,
        ultimo_resultado=None,
        usuario_cupo=_usuario_cupo_web() or "",
    )
    return cfg, None


@app.get("/analisis-programado")
def analisis_programado():
    from cuit_en_arca.analisis_programado import cargar_config

    cfg = cargar_config()
    return render_template(
        "analisis_programado.html",
        config=cfg.a_dict_publico(),
    )


@app.get("/analisis-programado/plantilla")
def analisis_programado_plantilla():
    from cuit_en_arca.analisis_programado import ruta_plantilla_excel

    ruta = ruta_plantilla_excel()
    if not ruta.is_file():
        abort(404)
    return send_file(
        ruta,
        as_attachment=True,
        download_name="Formato Analisis Programado.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.get("/analisis-programado/estado")
def analisis_programado_estado():
    from cuit_en_arca.analisis_programado import cargar_config, scheduler_estado

    cfg = cargar_config()
    payload = cfg.a_dict_publico()
    payload["scheduler"] = scheduler_estado(cfg)
    return jsonify(payload)


@app.get("/analisis-programado/ejecucion")
def analisis_programado_ejecucion():
    from cuit_en_arca.progreso_analisis_programado import obtener_ejecucion_ap

    return jsonify(obtener_ejecucion_ap())


@app.post("/analisis-programado/guardar")
def analisis_programado_guardar():
    from cuit_en_arca.analisis_programado import cargar_config, guardar_config

    lg = normalize_lang(session.get("lang"))
    es_fetch = request.headers.get("X-Requested-With") == "fetch"

    cfg, err_msg = _cfg_ap_desde_peticion(lg)
    if err_msg:
        if es_fetch:
            return jsonify({"error": err_msg}), 400
        return render_template(
            "analisis_programado.html",
            error=err_msg,
            config=cargar_config().a_dict_publico(),
        )

    try:
        guardar_config(cfg)
    except OSError as exc:
        msg = tr(lg, "ap_err_guardar") + f" ({exc})"
        if es_fetch:
            return jsonify({"error": msg}), 500
        return render_template(
            "analisis_programado.html",
            error=msg,
            config=cargar_config().a_dict_publico(),
        )

    if es_fetch:
        return jsonify({"ok": True, "mensaje": tr(lg, "ap_ok_guardado"), "config": cfg.a_dict_publico()})
    return render_template(
        "analisis_programado.html",
        ok=tr(lg, "ap_ok_guardado"),
        config=cfg.a_dict_publico(),
    )


@app.post("/analisis-programado/ejecutar-ahora")
def analisis_programado_ejecutar_ahora():
    from cuit_en_arca.analisis_programado import cargar_config, lanzar_ejecucion_ap

    lg = normalize_lang(session.get("lang"))
    es_fetch = request.headers.get("X-Requested-With") == "fetch"

    cfg, err_msg = _cfg_ap_desde_peticion(lg, solo_ejecucion=True)
    if err_msg:
        if es_fetch:
            return jsonify({"error": err_msg}), 400
        return render_template(
            "analisis_programado.html",
            error=err_msg,
            config=cargar_config().a_dict_publico(),
        )

    err_cupo = _verificar_cupo_inicio(lg)
    if err_cupo:
        if es_fetch:
            return jsonify({"error": err_cupo}), 403
        return render_template(
            "analisis_programado.html",
            error=err_cupo,
            config=cargar_config().a_dict_publico(),
        )

    ok, msg = lanzar_ejecucion_ap(
        cfg,
        manual=True,
        headless=_headless_desde_peticion(),
    )
    if not ok:
        err = tr(lg, "ap_err_en_curso")
        if es_fetch:
            return jsonify({"error": err}), 409
        return render_template(
            "analisis_programado.html",
            error=err,
            config=cargar_config().a_dict_publico(),
        )

    payload = {"ok": True, "mensaje": tr(lg, "ap_ejecutar_iniciado")}
    if es_fetch:
        return jsonify(payload)
    return render_template(
        "analisis_programado.html",
        ok=payload["mensaje"],
        config=cargar_config().a_dict_publico(),
    )


@app.post("/api/cancelar-descarga")
def cancelar_descarga():
    from cuit_en_arca.browser_desktop import cerrar_navegador_desktop
    from cuit_en_arca.cancelacion import solicitar_cancelacion, solicitar_cancelacion_ap
    from cuit_en_arca.progreso_analisis_programado import marcar_cancelado_ap

    payload = request.get_json(silent=True) or {}
    tipo = (payload.get("tipo") or request.form.get("tipo") or "").strip()
    job_id = (payload.get("job_id") or request.form.get("job_id") or "").strip()
    lg = normalize_lang(session.get("lang"))
    msg = tr(lg, "msg_descarga_cancelada")

    if tipo == "ap":
        _requiere_servicio("ap")
        solicitar_cancelacion_ap()
        marcar_cancelado_ap(msg)
    elif job_id:
        solicitar_cancelacion(job_id)
        if tipo == "dfe":
            marcar_cancelado_dfe(job_id, msg)
        elif tipo == "vl":
            marcar_cancelado_vl(job_id, msg)
        elif tipo == "np":
            marcar_cancelado_np(job_id, msg)
        elif tipo == "fact":
            from cuit_en_arca.progreso_facturador import marcar_cancelado_facturador

            marcar_cancelado_facturador(job_id, msg)
        else:
            marcar_cancelado(job_id, msg)
    else:
        return jsonify({"error": tr(lg, "err_arca_unexpected", exc="sin job")}), 400

    try:
        cerrar_navegador_desktop()
    except Exception:
        pass
    return jsonify({"ok": True})


def _auth_api_remota():
    """(tipo, usuario_ligado|None) o None. Sync solo con token global."""
    from auth_dispositivos import resolver_autorizacion_api

    return resolver_autorizacion_api(request.headers.get("Authorization"))


def _usuario_desde_auth_cupo(pedido: str) -> tuple[str | None, tuple | None]:
    """Resuelve usuario para cupo/uso. Solo device token; body no puede suplantar.

    Returns:
        (clave, None) OK; (None, (jsonify..., status)) error HTTP.
    """
    from auth_registro import resolver_clave_usuario_overlay

    auth = _auth_api_remota()
    if auth is None:
        return None, (jsonify({"error": "unauthorized"}), 401)
    tipo, usuario_token = auth
    if tipo != "device" or not usuario_token:
        return None, (jsonify({"error": "device_token_requerido"}), 401)
    pedido_u = (pedido or "").strip()
    if pedido_u and pedido_u != usuario_token:
        clave_ped = resolver_clave_usuario_overlay(pedido_u) or pedido_u
        clave_tok = resolver_clave_usuario_overlay(usuario_token) or usuario_token
        if clave_ped != clave_tok:
            return None, (jsonify({"error": "usuario_no_coincide"}), 403)
    clave = resolver_clave_usuario_overlay(usuario_token) or usuario_token
    return clave, None


def _perfil_publico_usuario(clave: str) -> dict:
    """Metadatos sin secretos para el propio usuario (post-login /api)."""
    from auth import _meta_sin_secretos

    perfil: dict = {"usuario": clave}
    try:
        from auth_registro import cargar_usuarios_overlay, info_cupo_cuit, info_suscripcion_usuario

        meta = (cargar_usuarios_overlay() or {}).get(clave)
        if isinstance(meta, dict):
            perfil.update(_meta_sin_secretos(meta))
        cupo = info_cupo_cuit(clave)
        if isinstance(cupo, dict):
            perfil.update(
                {
                    "cuit_limite": cupo.get("cuit_limite"),
                    "cuit_usados": cupo.get("cuit_usados"),
                    "cuit_disponibles": cupo.get("cuit_disponibles"),
                    "cuit_ilimitado": cupo.get("cuit_ilimitado"),
                }
            )
        sus = info_suscripcion_usuario(clave)
        if isinstance(sus, dict):
            vh = sus.get("valido_hasta")
            perfil["valido_hasta"] = (
                vh.isoformat() if hasattr(vh, "isoformat") else sus.get("valido_hasta_fmt") or vh
            )
            perfil["dias_restantes"] = sus.get("dias_restantes")
    except Exception:
        logging.getLogger(__name__).debug("Perfil público incompleto", exc_info=True)
    return perfil


@app.get("/api/auth-users")
@csrf.exempt
def api_auth_users():
    """Deshabilitado por defecto (Fase 1.2). Escape: AUTH_EXPORT_AUTH_USERS=1."""
    auth = _auth_api_remota()
    if auth is None or auth[0] != "global":
        return jsonify({"error": "unauthorized"}), 401
    flag = (os.environ.get("AUTH_EXPORT_AUTH_USERS") or "").strip().lower()
    if flag not in ("1", "true", "yes", "on", "si", "sí"):
        return (
            jsonify(
                {
                    "error": "gone",
                    "message": "Usá POST /api/auth/verificar; el directorio global ya no se exporta.",
                    "credentials_omitted": True,
                    "users": {},
                }
            ),
            410,
        )
    return jsonify(export_users_payload())


@app.post("/api/auth/verificar")
@csrf.exempt
def api_auth_verificar():
    """Valida usuario/contraseña y emite token de dispositivo (Bearer global)."""
    auth = _auth_api_remota()
    if auth is None or auth[0] != "global":
        return jsonify({"error": "unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    usuario = (data.get("usuario") or "").strip()
    password = data.get("password") or ""
    device_id = (data.get("device_id") or "").strip()[:120]
    public_key = (data.get("public_key") or "").strip()[:200]
    etiqueta = (data.get("etiqueta") or "portable").strip()[:80] or "portable"
    integridad = data.get("integridad") if isinstance(data.get("integridad"), dict) else {}
    rl = _rate_limit_usuario_consulta("login", usuario)
    if rl is not None:
        return _respuesta_rate_limit(rl, api=True)
    if not usuario or not password:
        return jsonify({"ok": False, "motivo": "invalid"}), 400
    motivo = verificar_acceso(usuario, password)
    if motivo is None:
        from auth import _resolver_clave_usuario
        from auth_dispositivos import emitir_token_dispositivo, registrar_integridad

        _rate_limit_usuario_ok("login", usuario)
        clave = _resolver_clave_usuario(usuario)
        try:
            device_token = emitir_token_dispositivo(
                clave,
                etiqueta=etiqueta,
                device_id=device_id,
                public_key=public_key,
            )
        except Exception:
            logging.getLogger(__name__).exception("No se pudo emitir device token")
            device_token = ""
        if device_token and integridad:
            try:
                ok_raw = integridad.get("integrity_ok")
                registrar_integridad(
                    device_id=device_id,
                    usuario=clave,
                    build_id=str(integridad.get("build_id") or ""),
                    app_version=str(integridad.get("app_version") or ""),
                    root_hash=str(integridad.get("root_hash") or ""),
                    integrity_ok=None if ok_raw is None else bool(ok_raw),
                    detail=str(integridad.get("detail") or ""),
                )
            except Exception:
                logging.getLogger(__name__).debug(
                    "No se pudo registrar integridad en login", exc_info=True
                )
        payload = {
            "ok": True,
            "usuario": clave,
            "es_admin": es_administrador(clave),
            "device_id": device_id,
            "perfil": _perfil_publico_usuario(clave),
        }
        if device_token:
            payload["device_token"] = device_token
        try:
            from auth_entitlements import emitir_entitlement_usuario

            firmado = emitir_entitlement_usuario(clave, device_id=device_id)
            if firmado:
                payload["entitlement_signed"] = firmado
        except Exception:
            logging.getLogger(__name__).exception("No se pudo emitir entitlement")
        return jsonify(payload)
    _rate_limit_usuario_fallo("login", usuario)
    return jsonify({"ok": False, "motivo": motivo}), 401


@app.get("/api/auth/perfil")
@csrf.exempt
def api_auth_perfil():
    """Metadatos del propio usuario (solo device token)."""
    clave, err = _usuario_desde_auth_cupo("")
    if err is not None:
        return err
    return jsonify({"ok": True, "usuario": clave, "perfil": _perfil_publico_usuario(clave)})


@app.post("/api/instalacion/integridad")
@csrf.exempt
def api_instalacion_integridad():
    """Telemetría de manifiesto (solo device token)."""
    from auth_dispositivos import registrar_integridad, resolver_device_meta

    meta = resolver_device_meta(request.headers.get("Authorization"))
    if not meta:
        return jsonify({"error": "device_token_requerido"}), 401
    data = request.get_json(silent=True) or {}
    ok_raw = data.get("integrity_ok")
    ok = registrar_integridad(
        device_id=str(meta.get("device_id") or data.get("device_id") or ""),
        usuario=str(meta.get("usuario") or ""),
        build_id=str(data.get("build_id") or ""),
        app_version=str(data.get("app_version") or ""),
        root_hash=str(data.get("root_hash") or ""),
        integrity_ok=None if ok_raw is None else bool(ok_raw),
        detail=str(data.get("detail") or ""),
    )
    if not ok:
        return jsonify({"error": "no_actualizado"}), 404
    return jsonify({"ok": True})


@app.get("/api/cupo/info")
@csrf.exempt
def api_cupo_info():
    """Consulta cupo CUIT (solo device token)."""
    clave, err = _usuario_desde_auth_cupo(request.args.get("usuario") or "")
    if err is not None:
        return err
    from auth_registro import info_cupo_cuit

    info = info_cupo_cuit(clave)
    if info is None:
        return jsonify({"error": "sin_cupo", "usuario": clave}), 404
    return jsonify({"ok": True, "usuario": clave, **info})


@app.post("/api/cupo/consumir")
@csrf.exempt
def api_cupo_consumir():
    """Registra consumo de cupo (solo device token)."""
    data = request.get_json(silent=True) or {}
    clave, err = _usuario_desde_auth_cupo(data.get("usuario") or "")
    if err is not None:
        return err
    try:
        cantidad = max(1, int(data.get("cantidad") or 1))
    except (TypeError, ValueError):
        cantidad = 1
    from auth_registro import consumir_cuit_exitoso, info_cupo_cuit

    if info_cupo_cuit(clave) is None:
        return jsonify({"error": "sin_cupo", "usuario": clave}), 404
    if not consumir_cuit_exitoso(clave, cantidad):
        return jsonify({"error": "cupo_agotado", "usuario": clave}), 409
    info = info_cupo_cuit(clave) or {}
    return jsonify(
        {
            "ok": True,
            "usuario": clave,
            "cuit_usados": info.get("cuit_usados"),
            "cuit_disponibles": info.get("cuit_disponibles"),
        }
    )


@app.post("/api/uso/registrar")
@csrf.exempt
def api_uso_registrar():
    """Registra métricas de uso (solo device token)."""
    data = request.get_json(silent=True) or {}
    clave, err = _usuario_desde_auth_cupo(data.get("usuario") or "")
    if err is not None:
        return err
    from auth_uso_valor import _incrementar_uso
    from uso_metricas import meta_keys_uso

    campos: dict[str, int] = {}
    for key in meta_keys_uso():
        try:
            val = int(data.get(key) or 0)
        except (TypeError, ValueError):
            val = 0
        if val > 0:
            campos[key] = val
    if not campos:
        return jsonify({"error": "sin_incrementos"}), 400
    try:
        _incrementar_uso(clave, **campos)
    except Exception as exc:
        return jsonify({"error": "registro_fallido", "detalle": str(exc)}), 500
    return jsonify({"ok": True, "usuario": clave})


@app.post("/analisis-programado/limpiar")
def analisis_programado_limpiar():
    from cuit_en_arca.analisis_programado import limpiar_configuracion_completa
    from cuit_en_arca.progreso_analisis_programado import resetear_ejecucion_ap

    lg = normalize_lang(session.get("lang"))
    cfg = limpiar_configuracion_completa()
    resetear_ejecucion_ap()
    return jsonify({
        "ok": True,
        "mensaje": tr(lg, "ap_ok_limpiado"),
        "config": cfg.a_dict_publico(),
    })


@app.get("/admin/cursor")
def admin_cursor():
    _requiere_admin()
    return render_template(
        "admin_cursor.html",
        cursor_config=cursor_verificar_enlace(probar_api=False),
    )


@app.get("/admin/cursor/estado")
def admin_cursor_estado():
    _requiere_admin()
    probar = request.args.get("probar") in ("1", "true", "yes")
    return jsonify(cursor_verificar_enlace(probar_api=probar))


@app.post("/admin/cursor/mensaje")
def admin_cursor_mensaje():
    _requiere_admin()
    lg = normalize_lang(session.get("lang"))
    verif = cursor_verificar_enlace(probar_api=False)
    if not verif.get("configured"):
        return jsonify({"error": tr(lg, "admin_cursor_err_no_config")}), 503
    if cursor_requiere_repo() and not verif.get("repo_url"):
        return jsonify({"error": tr(lg, "admin_cursor_err_sin_repo")}), 400
    if not verif.get("ready"):
        return jsonify({"error": tr(lg, "admin_cursor_err_checks")}), 400
    data = request.get_json(silent=True) or {}
    texto = (data.get("text") or "").strip()
    agent_id = (data.get("agent_id") or "").strip()
    if not texto:
        return jsonify({"error": tr(lg, "admin_cursor_err_vacio")}), 400
    try:
        if agent_id:
            out = cursor_crear_run(agent_id, texto)
        else:
            out = cursor_crear_agente(texto)
        return jsonify(
            {
                "ok": True,
                "agent_id": out.get("agent_id"),
                "run_id": out.get("run_id"),
                "agent_url": out.get("agent_url"),
                "flujo": [
                    "enviado",
                    "agente",
                    "push",
                    "pr" if verif.get("auto_create_pr") else "listo",
                ],
            }
        )
    except CursorCloudError as exc:
        return jsonify(
            {
                "error": _mensaje_error_cursor(lg, exc),
                "code": exc.code,
                "help_url": (
                    "https://www.cursor.com/dashboard?tab=settings"
                    if exc.code == "usage_limit_exceeded"
                    else None
                ),
            }
        ), exc.status


@app.get("/admin/cursor/run/<agent_id>/<run_id>")
def admin_cursor_run(agent_id: str, run_id: str):
    _requiere_admin()
    try:
        run = cursor_obtener_run(agent_id, run_id)
        return jsonify({"ok": True, "run": cursor_run_publico(run)})
    except CursorCloudError as exc:
        return jsonify({"error": str(exc), "code": exc.code}), exc.status


@app.get("/admin/cursor/stream/<agent_id>/<run_id>")
def admin_cursor_stream(agent_id: str, run_id: str):
    _requiere_admin()
    last_event = request.headers.get("Last-Event-ID")

    def generate():
        try:
            for chunk in cursor_stream_run(agent_id, run_id, last_event):
                yield chunk
        except CursorCloudError as exc:
            payload = json.dumps({"message": str(exc)}, ensure_ascii=False)
            yield f"event: cursor_error\ndata: {payload}\n\n".encode("utf-8")

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/admin/cursor/cancelar/<agent_id>/<run_id>")
def admin_cursor_cancelar(agent_id: str, run_id: str):
    _requiere_admin()
    lg = normalize_lang(session.get("lang"))
    try:
        cursor_cancelar_run(agent_id, run_id)
        return jsonify({"ok": True})
    except CursorCloudError as exc:
        return jsonify({"error": str(exc), "code": exc.code}), exc.status


@app.get("/elegir-carpeta")
def elegir_carpeta():
    """Abre un diálogo nativo del sistema para elegir la carpeta de descarga.

    Solo tiene sentido en el escritorio (servidor = PC del usuario), por eso se
    restringe a peticiones locales.
    """
    ra = (request.remote_addr or "").replace("::ffff:", "")
    if ra not in ("127.0.0.1", "::1"):
        return jsonify({"error": "solo_local"}), 403

    from urllib.parse import unquote

    titulo = unquote(request.args.get("titulo") or "Elegir carpeta de descarga").strip()
    from cuit_en_arca.elegir_carpeta import elegir_carpeta_dialogo

    ruta = elegir_carpeta_dialogo(titulo)
    if not ruta:
        return jsonify({"cancelado": True})
    return jsonify({"carpeta": ruta})


if __name__ == "__main__":
    import threading
    import webbrowser

    try:
        from cuit_en_arca.analisis_programado import iniciar_scheduler

        iniciar_scheduler()
    except Exception:
        pass

    puerto = int(os.environ.get("PORT", 5000))
    url = f"http://127.0.0.1:{puerto}/"
    print(f"\n  Servidor: {url}\n  (Abrí esa dirección en el navegador si no se abre sola.)\n", flush=True)
    if os.environ.get("OPEN_BROWSER", "1").strip().lower() in ("1", "true", "yes", "on"):
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    app.run(host="0.0.0.0", port=puerto, debug=False)
