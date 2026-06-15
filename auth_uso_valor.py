"""Métricas de valor generado por usuario (período de suscripción actual)."""

from __future__ import annotations

import io
import logging
from typing import Any, Callable

_LOG = logging.getLogger(__name__)

_USO_KEYS = (
    "uso_mce_comprobantes",
    "uso_mcr_comprobantes",
    "uso_dfe_notificaciones",
    "uso_np_cuits",
)


def reset_uso_periodo_meta(meta: dict[str, Any]) -> None:
    for key in _USO_KEYS:
        meta[key] = 0


def _leer_uso_meta(meta: dict[str, Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for key in _USO_KEYS:
        try:
            out[key] = max(0, min(int(meta.get(key) or 0), 1_000_000_000))
        except (TypeError, ValueError):
            out[key] = 0
    return out


def _incrementar_uso(username: str, **campos: int) -> None:
    from auth_registro import (
        _lock,
        _path_usuarios_overlay,
        _read_store,
        _write_store,
        meta_es_admin,
        resolver_clave_overlay,
    )
    from auth import es_administrador
    from datetime import datetime, timezone

    u_raw = (username or "").strip()
    if not u_raw or es_administrador(u_raw):
        return
    u = resolver_clave_overlay(u_raw)
    if not u:
        return
    incrementos = {k: max(0, int(v)) for k, v in campos.items() if int(v) > 0}
    if not incrementos:
        return
    with _lock:
        path = _path_usuarios_overlay()
        overlay = _read_store("usuarios_registrados", {"version": 1, "users": {}}, path)
        users = overlay.get("users")
        if not isinstance(users, dict) or u not in users:
            return
        meta = users[u]
        if not isinstance(meta, dict) or meta_es_admin(meta):
            return
        uso = _leer_uso_meta(meta)
        for key, val in incrementos.items():
            if key not in _USO_KEYS:
                continue
            uso[key] = min(uso[key] + val, 1_000_000_000)
        for key in _USO_KEYS:
            meta[key] = uso[key]
        overlay["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        _write_store("usuarios_registrados", overlay, path)


def contar_comprobantes_en_archivo(datos: bytes, nombre: str) -> int:
    try:
        from sumar_imp_total import leer_tabla

        df = leer_tabla(io.BytesIO(datos), nombre_archivo=nombre or "comprobantes.csv")
        return max(0, len(df))
    except Exception as exc:
        _LOG.debug("No se pudo contar comprobantes en %s: %s", nombre, exc)
        return 0


def contadores_mc_desde_resultado(resultado) -> tuple[int, int]:
    mce = (
        contar_comprobantes_en_archivo(resultado.emitidos[0], resultado.emitidos[1])
        if getattr(resultado, "emitidos", None)
        else 0
    )
    mcr = (
        contar_comprobantes_en_archivo(resultado.recibidos[0], resultado.recibidos[1])
        if getattr(resultado, "recibidos", None)
        else 0
    )
    return mce, mcr


def registrar_uso_mc(username: str, *, mce: int = 0, mcr: int = 0) -> None:
    _incrementar_uso(
        username,
        uso_mce_comprobantes=max(0, int(mce)),
        uso_mcr_comprobantes=max(0, int(mcr)),
    )


def registrar_uso_dfe(username: str, notificaciones: int) -> None:
    _incrementar_uso(username, uso_dfe_notificaciones=max(0, int(notificaciones)))


def registrar_uso_np(username: str) -> None:
    _incrementar_uso(username, uso_np_cuits=1)


def dashboard_valor_usuario(cuit: str) -> dict[str, Any] | None:
    from auth_registro import (
        _parse_fecha_local,
        cargar_usuarios_overlay,
        formatear_cuit,
        meta_es_admin,
        normalizar_cuit,
        resolver_clave_overlay,
        _leer_cupo_meta,
    )

    u = resolver_clave_overlay(cuit) or normalizar_cuit(cuit)
    if not u:
        return None
    meta = cargar_usuarios_overlay().get(u)
    if not isinstance(meta, dict) or meta_es_admin(meta):
        return None
    if meta.get("pendiente_aprobacion"):
        return None
    limite, usados = _leer_cupo_meta(meta)
    uso = _leer_uso_meta(meta)
    vd = _parse_fecha_local(meta.get("valido_desde"))
    vh = _parse_fecha_local(meta.get("valido_hasta"))
    return {
        "cuit": u,
        "cuit_fmt": formatear_cuit(u),
        "nombre": meta.get("nombre") or "",
        "email": meta.get("email") or "",
        "valido_desde_fmt": vd.strftime("%d/%m/%Y") if vd else "—",
        "valido_hasta_fmt": vh.strftime("%d/%m/%Y") if vh else "—",
        "cuit_usados": usados,
        "cuit_limite": limite,
        "cuit_disponibles": max(0, limite - usados),
        "mce_comprobantes": uso["uso_mce_comprobantes"],
        "mcr_comprobantes": uso["uso_mcr_comprobantes"],
        "dfe_notificaciones": uso["uso_dfe_notificaciones"],
        "np_cuits": uso["uso_np_cuits"],
    }


def fabricar_registro_valor(
    username: str | None,
) -> tuple[
    Callable[[int, int], None] | None,
    Callable[[int], None] | None,
    Callable[[], None] | None,
]:
    u = (username or "").strip()
    if not u:
        return None, None, None
    from auth import es_administrador

    if es_administrador(u):
        return None, None, None

    def mc(mce: int, mcr: int) -> None:
        registrar_uso_mc(u, mce=mce, mcr=mcr)

    def dfe(notificaciones: int) -> None:
        registrar_uso_dfe(u, notificaciones)

    def np() -> None:
        registrar_uso_np(u)

    return mc, dfe, np


def listar_dashboards_valor() -> list[dict[str, Any]]:
    from auth_registro import listar_usuarios_suscripcion

    out: list[dict[str, Any]] = []
    for sub in listar_usuarios_suscripcion():
        dash = dashboard_valor_usuario(sub.get("cuit") or "")
        if dash:
            out.append(dash)
    out.sort(key=lambda d: (d.get("cuit_fmt") or d.get("cuit") or "").lower())
    return out


def _nombre_hoja_excel(d: dict[str, Any], usados: set[str]) -> str:
    import re

    base = re.sub(r"[\\/*?:\[\]]", "", (d.get("cuit_fmt") or d.get("cuit") or "Usuario")).strip()
    base = base.replace("—", "-")[:28] or "Usuario"
    nombre = base
    n = 1
    while nombre in usados:
        suf = f"_{n}"
        nombre = f"{base[: max(1, 31 - len(suf))]}{suf}"
        n += 1
    usados.add(nombre)
    return nombre


def generar_excel_dashboard_valor() -> bytes:
    """Excel: hoja Resumen (tabla + enlaces) y una hoja de detalle por usuario."""
    from datetime import date

    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.table import Table, TableStyleInfo

    dashboards = listar_dashboards_valor()
    wb = Workbook()
    ws = wb.active
    ws.title = "Resumen"

    encabezados = [
        "CUIT / Usuario",
        "Nombre",
        "Email",
        "Válido desde",
        "Válido hasta",
        "CUIT procesados",
        "Cupo límite",
        "CUIT disponibles",
        "Comprob. emitidos (MCE)",
        "Comprob. recibidos (MCR)",
        "Notificaciones DFE",
        "CUIT Nuestra Parte",
    ]
    ws.append(encabezados)
    for col in range(1, len(encabezados) + 1):
        c = ws.cell(row=1, column=col)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1F4E79")
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    hojas_usuario: list[tuple[str, dict[str, Any]]] = []
    usados: set[str] = {"Resumen"}
    for d in dashboards:
        hojas_usuario.append((_nombre_hoja_excel(d, usados), d))

    fila = 2
    for hoja, d in hojas_usuario:
        ws.append(
            [
                d.get("cuit_fmt") or d.get("cuit"),
                d.get("nombre") or "",
                d.get("email") or "",
                d.get("valido_desde_fmt") or "",
                d.get("valido_hasta_fmt") or "",
                d.get("cuit_usados", 0),
                d.get("cuit_limite", 0),
                d.get("cuit_disponibles", 0),
                d.get("mce_comprobantes", 0),
                d.get("mcr_comprobantes", 0),
                d.get("dfe_notificaciones", 0),
                d.get("np_cuits", 0),
            ]
        )
        celda = ws.cell(row=fila, column=1)
        celda.hyperlink = f"#'{hoja}'!A1"
        celda.font = Font(color="0563C1", underline="single")
        fila += 1

    ultima_fila = max(1, len(dashboards) + 1)
    ultima_col = get_column_letter(len(encabezados))
    if dashboards:
        tabla = Table(
            displayName="TablaValorGenerado",
            ref=f"A1:{ultima_col}{ultima_fila}",
        )
        tabla.tableStyleInfo = TableStyleInfo(
            name="TableStyleMedium2",
            showFirstColumn=False,
            showLastColumn=False,
            showRowStripes=True,
            showColumnStripes=False,
        )
        ws.add_table(tabla)

    ws.freeze_panes = "A2"
    for col in range(1, len(encabezados) + 1):
        ws.column_dimensions[get_column_letter(col)].width = 16
    ws.column_dimensions["A"].width = 18
    ws.column_dimensions["B"].width = 22
    ws.column_dimensions["C"].width = 26

    ws["N1"] = "Instrucciones"
    ws["N2"] = (
        "Hacé clic en el CUIT de la tabla para abrir el detalle del usuario en otra hoja. "
        "Podés filtrar y ordenar con los controles de la tabla."
    )
    ws["N2"].alignment = Alignment(wrap_text=True)
    ws.column_dimensions["N"].width = 36

    titulo_fill = PatternFill("solid", fgColor="E8F0FE")
    lbl_font = Font(bold=True)

    filas_detalle = [
        ("CUIT / Usuario", lambda d: d.get("cuit_fmt") or d.get("cuit")),
        ("Nombre", lambda d: d.get("nombre") or "—"),
        ("Email", lambda d: d.get("email") or "—"),
        ("Período desde", lambda d: d.get("valido_desde_fmt") or "—"),
        ("Período hasta", lambda d: d.get("valido_hasta_fmt") or "—"),
        ("CUIT procesados (cupo)", lambda d: d.get("cuit_usados", 0)),
        ("Cupo límite", lambda d: d.get("cuit_limite", 0)),
        ("CUIT disponibles", lambda d: d.get("cuit_disponibles", 0)),
        ("Comprobantes emitidos (MCE)", lambda d: d.get("mce_comprobantes", 0)),
        ("Comprobantes recibidos (MCR)", lambda d: d.get("mcr_comprobantes", 0)),
        ("Notificaciones DFE", lambda d: d.get("dfe_notificaciones", 0)),
        ("CUIT Nuestra Parte", lambda d: d.get("np_cuits", 0)),
    ]

    for hoja, d in hojas_usuario:
        det = wb.create_sheet(title=hoja)
        det["A1"] = f"Dashboard de valor — {d.get('cuit_fmt') or d.get('cuit')}"
        det["A1"].font = Font(bold=True, size=14)
        det["A2"] = "← Volver al resumen"
        det["A2"].hyperlink = "#Resumen!A1"
        det["A2"].font = Font(color="0563C1", underline="single")
        det["A4"] = "Métrica"
        det["B4"] = "Valor"
        det["A4"].font = lbl_font
        det["B4"].font = lbl_font
        det["A4"].fill = titulo_fill
        det["B4"].fill = titulo_fill
        r = 5
        for etiqueta, fn in filas_detalle:
            det.cell(row=r, column=1, value=etiqueta)
            det.cell(row=r, column=2, value=fn(d))
            r += 1
        det.column_dimensions["A"].width = 32
        det.column_dimensions["B"].width = 22
        det["D4"] = f"Exportado: {date.today().strftime('%d/%m/%Y')}"

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
