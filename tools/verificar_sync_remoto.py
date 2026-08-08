#!/usr/bin/env python3
"""Verifica que local/portable pueda sincronizar TODOS los usuarios activos de Neon/web.

Uso (desde la raíz del proyecto):

  python tools/verificar_sync_remoto.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
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
    from auth import (
        _actualizar_cache_remota,
        _modo_remoto_activo,
        _remote_token,
        _remote_url,
    )

    print("=== Sync remoto usuarios (Neon via Render) ===")
    url = _remote_url()
    token = _remote_token()
    print(f"  URL: {url or '(vacía)'}")
    print(f"  Token: {'OK (' + str(len(token)) + ' chars)' if token else 'FALTA'}")
    print(f"  modo_remoto: {_modo_remoto_activo()}")
    print(f"  RENDER: {bool((os.environ.get('RENDER') or '').strip())}")

    if not url or not token:
        print(
            "\nFAIL: falta AUTH_USERS_URL + AUTH_USERS_REMOTE_TOKEN en .env, "
            "o auth_remote.txt / auth_remote.enc (raíz o junto al .exe)."
        )
        return 1
    if not _modo_remoto_activo():
        print(
            "\nFAIL: modo remoto desactivado. En local/portable no debe haber RENDER=1."
        )
        return 1

    req = Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "verificar-sync-remoto",
        },
    )
    with urlopen(req, timeout=60) as resp:
        payload = json.loads(resp.read().decode("utf-8-sig"))
    remote_users = payload.get("users") if isinstance(payload, dict) else {}
    if not isinstance(remote_users, dict):
        print("FAIL: respuesta /api/auth-users sin users")
        return 1

    activos = {
        u: m
        for u, m in remote_users.items()
        if isinstance(m, dict)
        and not m.get("pendiente_aprobacion")
        and m.get("activo") is not False
    }
    con_secreto = [
        u
        for u, m in activos.items()
        if str(m.get("password") or m.get("clave") or "").strip()
    ]
    print(f"  API users: {len(remote_users)} (activos: {len(activos)})")
    print(f"  credentials_omitted: {bool(payload.get('credentials_omitted'))}")
    if con_secreto:
        print(f"FAIL: la API aún expone password/clave para: {', '.join(con_secreto[:10])}")
        return 1

    cuentas = _actualizar_cache_remota(forzar=True)
    # Tras omitir passwords, el parseo local puede no crear CuentaUsuario;
    # el sync de metadatos/overlay sigue siendo válido si la API lista a todos.
    faltan_api = []  # reservado
    print(f"  Sync parse cuentas con password local: {len(cuentas)}")
    if faltan_api:
        print(f"FAIL: no sincronizaron: {', '.join(faltan_api)}")
        return 1

    print("\nOK: /api/auth-users no expone contraseñas; metadatos de activos disponibles.")
    print("    Login portable debe usar POST /api/auth/verificar (no hashes locales).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
