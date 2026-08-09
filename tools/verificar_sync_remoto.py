#!/usr/bin/env python3
"""Verifica que /api/auth-users ya no exporta el directorio (410) y que verificar responde."""

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
    from auth import _modo_remoto_activo, _remote_token, _remote_url, _url_api_auth_verificar

    url = _remote_url()
    token = _remote_token()
    print("=== Verificar sync / auth remoto ===")
    print(f"  URL listado: {url or '(vacía)'}")
    if not url or not token:
        print("\nFAIL: falta AUTH_USERS_URL / AUTH_USERS_REMOTE_TOKEN (o auth_remote).")
        return 1
    if not _modo_remoto_activo():
        print("\nFAIL: modo remoto desactivado.")
        return 1

    req = Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "verificar-sync-remoto",
        },
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
        if code == 410 and isinstance(payload, dict) and payload.get("error") == "gone":
            print("  OK  /api/auth-users → 410 gone (directorio no exportado)")
        else:
            print(f"FAIL: HTTP {code} inesperado en /api/auth-users: {raw[:200]}")
            return 1
    else:
        # Escape AUTH_EXPORT_AUTH_USERS=1 todavía activo
        users = payload.get("users") if isinstance(payload, dict) else {}
        if isinstance(users, dict) and users:
            con_secreto = [
                u
                for u, m in users.items()
                if isinstance(m, dict)
                and str(m.get("password") or m.get("clave") or "").strip()
            ]
            if con_secreto:
                print(f"FAIL: la API aún expone password para: {', '.join(con_secreto[:10])}")
                return 1
            print(
                "  AVISO: /api/auth-users aún exporta usuarios "
                "(¿AUTH_EXPORT_AUTH_USERS=1?). Preferible dejarlo en 410."
            )
        else:
            print(f"  OK  /api/auth-users HTTP {code} sin directorio útil")

    verify = _url_api_auth_verificar()
    print(f"  URL verificar: {verify}")
    # Solo comprueba que el endpoint exista (400 sin body), no hace login.
    req_v = Request(
        verify,
        data=b"{}",
        headers={
            "Authorization": f"Bearer {token}",
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
        if exc.code in (400, 401):
            print(f"  OK  /api/auth/verificar responde (HTTP {exc.code})")
        else:
            print(f"FAIL: /api/auth/verificar HTTP {exc.code}")
            return 1

    print("\nOK: listado global cerrado; login portable vía /api/auth/verificar.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
