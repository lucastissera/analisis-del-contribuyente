"""Versión local, última publicada (Render) y changelog.

El portable consulta el servidor para saber si hay una build más nueva.
En la web, la versión desplegada es la referencia.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from app_branding import APP_VERSION, RENDER_PUBLIC_URL

_LOG = logging.getLogger(__name__)
_CACHE: dict[str, Any] = {"t": 0.0, "remoto": None}
_CACHE_SEC = 300.0
_TIMEOUT_SEC = 3.0


def _parse_ver(raw: str) -> tuple[int, ...]:
    partes = [int(p) for p in re.findall(r"\d+", (raw or "").strip())]
    return tuple(partes) if partes else (0,)


def _es_mas_nueva(a: str, b: str) -> bool:
    """True si a > b."""
    pa, pb = _parse_ver(a), _parse_ver(b)
    n = max(len(pa), len(pb))
    pa += (0,) * (n - len(pa))
    pb += (0,) * (n - len(pb))
    return pa > pb


def _candidatos_changelog() -> list[Path]:
    out: list[Path] = []
    if getattr(sys, "frozen", False):
        meipass = Path(getattr(sys, "_MEIPASS", "") or ".")
        out.append(meipass / "static" / "changelog.json")
        out.append(Path(sys.executable).resolve().parent / "static" / "changelog.json")
        out.append(Path(sys.executable).resolve().parent / "_internal" / "static" / "changelog.json")
    raiz = Path(__file__).resolve().parent
    out.append(raiz / "static" / "changelog.json")
    vistos: set[str] = set()
    unicos: list[Path] = []
    for p in out:
        key = str(p)
        if key in vistos:
            continue
        vistos.add(key)
        unicos.append(p)
    return unicos


def cargar_changelog_local() -> dict[str, Any]:
    for path in _candidatos_changelog():
        try:
            if not path.is_file():
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("releases"), list):
                return data
        except (OSError, json.JSONDecodeError):
            continue
    return {"latest": APP_VERSION, "releases": []}


def _fetch_remoto() -> dict[str, Any] | None:
    ahora = time.time()
    if ahora - float(_CACHE.get("t") or 0) < _CACHE_SEC:
        rem = _CACHE.get("remoto")
        return rem if isinstance(rem, dict) else None
    _CACHE["t"] = ahora
    if (os.environ.get("RENDER") or "").strip():
        _CACHE["remoto"] = None
        return None
    url = f"{RENDER_PUBLIC_URL.rstrip('/')}/api/app-version"
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "AIC-portable"})
        with urllib.request.urlopen(req, timeout=_TIMEOUT_SEC) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        if isinstance(data, dict) and data.get("ok"):
            _CACHE["remoto"] = data
            return data
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError, ValueError):
        _LOG.debug("No se pudo leer version remota", exc_info=True)
    _CACHE["remoto"] = None
    return None


def estado_version() -> dict[str, Any]:
    local = cargar_changelog_local()
    releases = list(local.get("releases") or [])
    latest_local = str(local.get("latest") or APP_VERSION).strip() or APP_VERSION
    remoto = None
    comprobado = False
    latest = latest_local
    en_servidor = bool((os.environ.get("RENDER") or "").strip())
    if en_servidor:
        comprobado = True
    else:
        remoto = _fetch_remoto()
        if remoto:
            comprobado = True
            latest = str(remoto.get("latest") or latest).strip() or latest
            rem_rel = remoto.get("releases")
            if isinstance(rem_rel, list) and rem_rel:
                releases = rem_rel
    es_ultima = not _es_mas_nueva(latest, APP_VERSION)
    return {
        "ok": True,
        "local": APP_VERSION,
        "latest": latest,
        "es_ultima": es_ultima,
        "comprobado": comprobado,
        "releases": releases,
    }
