#!/usr/bin/env python3
"""Verifica que /api/auth-users no exporta el directorio y que /api/auth/verificar es público acotado."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:
    pass


def main() -> int:
    from app_branding import AUTH_USERS_API_URL
    from auth import _remote_url, _url_api_auth_verificar

    url = _remote_url() or AUTH_USERS_API_URL
    print("=== Verificar auth remoto ===")
    print(f"  URL listado: {url or '(vacía)'}")
    if not url:
        print("\nFAIL: no hay URL del servidor.")
        return 1

    req = Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "verificar-sync-remoto"},
    )
    try:
        with urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode("utf-8-sig"))
            code = getattr(resp, "status", 200)
    except HTTPError as exc:
        raw = exc.read().decode("utf-8-sig", errors="replace")
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = {}
        code = exc.code
        if code in (401, 410):
            print(f"  OK  /api/auth-users → {code} (directorio no público)")
        else:
            print(f"FAIL: HTTP {code} inesperado en /api/auth-users: {raw[:200]}")
            return 1
    else:
        users = payload.get("users") if isinstance(payload, dict) else {}
        if isinstance(users, dict) and users:
            print("FAIL: /api/auth-users exportó usuarios sin autenticación.")
            return 1
        print(f"  OK  /api/auth-users HTTP {code} sin directorio útil")

    verify = _url_api_auth_verificar() or url.replace("/auth-users", "/auth/verificar")
    print(f"  URL verificar: {verify}")
    req_v = Request(
        verify,
        data=b"{}",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "verificar-sync-remoto",
        },
        method="POST",
    )
    try:
        with urlopen(req_v, timeout=60) as resp:
            _ = resp.read()
            print(f"  OK  /api/auth/verificar HTTP {getattr(resp, 'status', 200)}")
    except HTTPError as exc:
        if exc.code == 401:
            print(
                "FAIL: /api/auth/verificar exige token (¿Render todavía no tiene este cambio?)."
            )
            return 1
        if exc.code in (400, 429):
            print(f"  OK  /api/auth/verificar responde sin Bearer (HTTP {exc.code})")
        else:
            print(f"FAIL: /api/auth/verificar HTTP {exc.code}")
            return 1

    print("\nOK: listado cerrado; login portable vía /api/auth/verificar sin auth_remote.enc.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
