"""Paquete ZIP de soporte (versión, integridad, logs). Sin claves ni auth_remote."""

from __future__ import annotations

import io
import json
import os
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from app_branding import APP_EXE_BASENAME, APP_LOG_FILENAME, APP_VERSION

_RE_SECRETO = re.compile(
    r"(?i)(password|passwd|contrase[ñn]a|clave\s*fiscal|secret[_-]?key|"
    r"token|bearer|auth_remote|authorization)\s*[=:]\s*\S+"
)
_MAX_LOG = 250_000


def _redactar(texto: str) -> str:
    return _RE_SECRETO.sub(r"\1=***", texto)


def _dir_exe() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _ruta_log() -> Path | None:
    p = _dir_exe() / APP_LOG_FILENAME
    return p if p.is_file() else None


def _ruta_manifest() -> Path | None:
    p = _dir_exe() / "manifest.signed.json"
    return p if p.is_file() else None


def _fallos_arca_recientes() -> list[tuple[str, str]]:
    """Hasta 3 archivos ingresos_fallidos.txt recientes (solo texto, redactado)."""
    bases = [_dir_exe()]
    local = _localappdata()
    if local:
        bases.append(local / "DepuracionExcelComprobantes")
    hallados: list[Path] = []
    for base in bases:
        if not base.is_dir():
            continue
        try:
            for p in base.rglob("ingresos_fallidos.txt"):
                if p.is_file():
                    hallados.append(p)
                if len(hallados) >= 40:
                    break
        except OSError:
            continue
    hallados.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    out: list[tuple[str, str]] = []
    for p in hallados[:3]:
        try:
            raw = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        nombre = f"arca_{p.parent.name}_{p.name}"
        out.append((nombre, _redactar(raw[-_MAX_LOG:])))
    return out


def _localappdata() -> Path | None:
    raw = (os.environ.get("LOCALAPPDATA") or "").strip()
    return Path(raw) if raw else None


def armar_zip_soporte() -> bytes:
    buf = io.BytesIO()
    info: dict = {
        "app_version": APP_VERSION,
        "frozen": bool(getattr(sys, "frozen", False)),
        "exe": APP_EXE_BASENAME,
        "generado_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "platform": sys.platform,
        "python": sys.version.split()[0],
    }
    try:
        from auth_manifest import estado_integridad

        est = estado_integridad()
        info["integridad"] = {
            "integrity_ok": est.get("integrity_ok"),
            "build_id": est.get("build_id") or "",
            "app_version": est.get("app_version") or "",
            "detail": (est.get("detail") or "")[:500],
        }
    except Exception as exc:
        info["integridad"] = {"error": type(exc).__name__}

    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "LEEME.txt",
            "Paquete de soporte AIC.\n"
            "No incluye auth_remote.enc, .env ni contraseñas.\n"
            "Los logs pueden estar recortados y con secretos tachados.\n",
        )
        zf.writestr("info.json", json.dumps(info, ensure_ascii=False, indent=2) + "\n")
        man = _ruta_manifest()
        if man is not None:
            try:
                # Solo metadatos del manifiesto (sin lista completa de hashes).
                blob = json.loads(man.read_text(encoding="utf-8"))
                inner = blob.get("manifest") if isinstance(blob, dict) else None
                meta = inner if isinstance(inner, dict) else blob if isinstance(blob, dict) else {}
                resumen = {
                    "app_version": meta.get("app_version"),
                    "build_id": meta.get("build_id"),
                    "created_at": meta.get("created_at"),
                    "file_count": meta.get("file_count"),
                    "root_hash": meta.get("root_hash"),
                }
                zf.writestr(
                    "manifest_resumen.json",
                    json.dumps(resumen, ensure_ascii=False, indent=2) + "\n",
                )
            except (OSError, json.JSONDecodeError):
                pass
        logp = _ruta_log()
        if logp is not None:
            try:
                data = logp.read_bytes()
                if len(data) > _MAX_LOG:
                    data = data[-_MAX_LOG:]
                texto = _redactar(data.decode("utf-8", errors="replace"))
                zf.writestr(APP_LOG_FILENAME, texto)
            except OSError:
                pass
        for nombre, contenido in _fallos_arca_recientes():
            zf.writestr(f"arca/{nombre}", contenido)

    return buf.getvalue()
