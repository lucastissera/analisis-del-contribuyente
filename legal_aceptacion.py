"""Registro y verificación de aceptación de TyC / privacidad."""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from typing import Any

from legal_config import LEGAL_DOCUMENTOS, LEGAL_VERSION


def _ahora_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def aplicar_aceptacion_a_meta(
    meta: dict[str, Any],
    *,
    version: str | None = None,
    metodo: str = "digital_clickwrap",
    ip: str = "",
    user_agent: str = "",
    documentos: tuple[str, ...] | None = None,
) -> None:
    meta["legal_aceptacion"] = {
        "version": (version or LEGAL_VERSION).strip(),
        "aceptada_en": _ahora_iso(),
        "documentos": list(documentos or LEGAL_DOCUMENTOS),
        "metodo": (metodo or "digital_clickwrap").strip(),
        "ip": (ip or "")[:64],
        "user_agent": (user_agent or "")[:500],
    }


def aceptacion_vigente(meta: dict[str, Any] | None) -> bool:
    if not isinstance(meta, dict):
        return False
    reg = meta.get("legal_aceptacion")
    if not isinstance(reg, dict):
        return False
    return str(reg.get("version") or "").strip() == LEGAL_VERSION


def resumen_aceptacion(meta: dict[str, Any] | None) -> dict[str, str]:
    if not isinstance(meta, dict):
        return {}
    reg = meta.get("legal_aceptacion")
    if not isinstance(reg, dict):
        return {}
    return {
        "version": str(reg.get("version") or ""),
        "aceptada_en": str(reg.get("aceptada_en") or ""),
        "metodo": str(reg.get("metodo") or ""),
        "ip": str(reg.get("ip") or ""),
    }


def datos_peticion_aceptacion() -> dict[str, str]:
    from flask import has_request_context, request

    if not has_request_context():
        return {"ip": "", "user_agent": ""}
    ip = (request.headers.get("X-Forwarded-For") or request.remote_addr or "").split(",")[0].strip()
    return {
        "ip": ip[:64],
        "user_agent": (request.headers.get("User-Agent") or "")[:500],
    }


def exportar_aceptaciones_csv(filas: list[dict[str, Any]]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(
        [
            "CUIT",
            "Nombre",
            "Email",
            "Version legal",
            "Aceptada en (UTC)",
            "Metodo",
            "IP",
            "User-Agent",
        ]
    )
    for f in filas:
        w.writerow(
            [
                f.get("cuit_fmt") or f.get("cuit") or "",
                f.get("nombre") or "",
                f.get("email") or "",
                f.get("legal_version") or "",
                f.get("legal_aceptada_en") or "",
                f.get("legal_metodo") or "",
                f.get("legal_ip") or "",
                f.get("legal_user_agent") or "",
            ]
        )
    return buf.getvalue().encode("utf-8-sig")


def exportar_aceptaciones_json(filas: list[dict[str, Any]]) -> bytes:
    return json.dumps(filas, ensure_ascii=False, indent=2).encode("utf-8")


def usuario_requiere_aceptacion_legal(username: str) -> bool:
    from auth import es_administrador

    if es_administrador(username):
        return False
    from auth_registro import cargar_usuarios_overlay, resolver_clave_usuario_overlay

    u = resolver_clave_usuario_overlay(username) or (username or "").strip()
    if not u:
        return True
    meta = cargar_usuarios_overlay().get(u)
    if not isinstance(meta, dict):
        return True
    if meta.get("pendiente_aprobacion"):
        return False
    return not aceptacion_vigente(meta)
