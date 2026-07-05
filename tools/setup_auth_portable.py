#!/usr/bin/env python3
"""Genera auth_users.enc (cifrado) y auth_remote.txt sin dejar JSON en claro.

Uso (desde la raíz del proyecto):

  set AUTH_ADMIN_PASSWORD=tu_clave
  python tools/setup_auth_portable.py

  python tools/setup_auth_portable.py --usuario Lucas --password "tu_clave"

Sync Neon / Render (opcional):

  python tools/setup_auth_portable.py ^
    --url https://analisisdelcontribuyente.onrender.com/api/auth-users ^
    --token el-token-de-Render
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_branding import APP_EXE_BASENAME, AUTH_USERS_API_URL

DIST_DIR = ROOT / "dist" / APP_EXE_BASENAME


def _payload_usuario(usuario: str, password: str, valido_hasta: str) -> dict:
    return {
        "version": 1,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "users": {
            usuario: {
                "password": password,
                "rol": "admin",
                "valido_hasta": valido_hasta,
            }
        },
    }


def _escribir_enc(ruta: Path, payload: dict) -> None:
    from auth_crypto import escribir_archivo_cifrado

    ruta.parent.mkdir(parents=True, exist_ok=True)
    escribir_archivo_cifrado(ruta, payload)
    print(f"  auth_users.enc -> {ruta}")


def _escribir_remote(ruta: Path, url: str, token: str) -> None:
    lineas = [
        "# Usuarios desde Neon vía la web (Render). Editá el token si cambia en Render.",
        url.strip(),
    ]
    if token.strip():
        lineas.append(token.strip())
    else:
        lineas.extend(
            [
                "# PEGÁ_ACÁ_EL_AUTH_USERS_REMOTE_TOKEN_DE_RENDER",
            ]
        )
    ruta.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    print(f"  auth_remote.txt -> {ruta}")


def _leer_auth_remote_existente(ruta: Path) -> tuple[str, str]:
    if not ruta.is_file():
        return "", ""
    try:
        lineas = [
            ln.strip()
            for ln in ruta.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.strip().startswith("#")
        ]
    except OSError:
        return "", ""
    url = lineas[0] if lineas else ""
    token = lineas[1] if len(lineas) > 1 else ""
    return url, token


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generar auth_users.enc cifrado para el portable (sin JSON en claro)"
    )
    parser.add_argument(
        "--usuario",
        default=(os.environ.get("AUTH_ADMIN_USER") or "Lucas").strip(),
    )
    parser.add_argument(
        "--password",
        default=(os.environ.get("AUTH_ADMIN_PASSWORD") or "").strip(),
    )
    parser.add_argument(
        "--valido-hasta",
        default=(os.environ.get("AUTH_ADMIN_VALIDO_HASTA") or "2027-12-31").strip(),
    )
    parser.add_argument(
        "--url",
        default=(os.environ.get("AUTH_USERS_URL") or "").strip(),
        help="URL /api/auth-users de Render (sync Neon)",
    )
    parser.add_argument(
        "--token",
        default=(os.environ.get("AUTH_USERS_REMOTE_TOKEN") or "").strip(),
        help="Bearer token (AUTH_USERS_REMOTE_TOKEN en Render)",
    )
    parser.add_argument(
        "--sin-raiz",
        action="store_true",
        help="No crear auth_users.enc en la raíz del repo (solo dist)",
    )
    parser.add_argument(
        "--solo-remoto",
        action="store_true",
        help="Solo auth_remote.txt (sin .enc local)",
    )
    parser.add_argument(
        "--no-tocar-remoto",
        action="store_true",
        help="No modificar auth_remote.txt (solo regenerar .enc)",
    )
    parser.add_argument(
        "--solo-url",
        action="store_true",
        help="Actualizar solo la URL oficial en auth_remote.txt (conserva el token)",
    )
    args = parser.parse_args()

    remote_path = DIST_DIR / "auth_remote.txt"
    url_prev, token_prev = _leer_auth_remote_existente(remote_path)

    if args.solo_url:
        DIST_DIR.mkdir(parents=True, exist_ok=True)
        _escribir_remote(remote_path, AUTH_USERS_API_URL, token_prev)
        print(f"\nURL actualizada: {AUTH_USERS_API_URL}")
        return 0

    if not args.solo_remoto and not args.password:
        print(
            "ERROR: indicá la contraseña con --password o AUTH_ADMIN_PASSWORD.",
            file=sys.stderr,
        )
        print('Ejemplo: set AUTH_ADMIN_PASSWORD=tu_clave && python tools/setup_auth_portable.py', file=sys.stderr)
        return 1

    print("Generando archivos de autenticación cifrados…")

    if not args.solo_remoto:
        payload = _payload_usuario(args.usuario, args.password, args.valido_hasta)
        if not args.sin_raiz:
            _escribir_enc(ROOT / "auth_users.enc", payload)
        if DIST_DIR.is_dir() or True:
            DIST_DIR.mkdir(parents=True, exist_ok=True)
            _escribir_enc(DIST_DIR / "auth_users.enc", payload)

    ejemplo = ROOT / "auth_remote.example.txt"
    if ejemplo.is_file():
        dest_ej = DIST_DIR / "auth_remote.example.txt"
        if DIST_DIR.is_dir() or True:
            shutil.copy2(ejemplo, dest_ej)
            print(f"  auth_remote.example.txt -> {dest_ej}")

    url = (
        args.url
        or url_prev
        or (os.environ.get("AUTH_USERS_URL") or "").strip()
        or AUTH_USERS_API_URL
    ).strip()
    token = (args.token or token_prev or os.environ.get("AUTH_USERS_REMOTE_TOKEN") or "").strip()

    if not args.no_tocar_remoto and url and (args.solo_remoto or args.url or args.token or not url_prev):
        if DIST_DIR.is_dir() or True:
            _escribir_remote(remote_path, url, token)
    elif remote_path.is_file():
        print(f"  auth_remote.txt sin cambios -> {remote_path}")

    print("\nListo. En dist no hace falta auth_users.json ni auth_users.example.json.")
    if url and not token:
        print(
            "Completá el token en dist/…/auth_remote.txt "
            "con AUTH_USERS_REMOTE_TOKEN de Render para sync Neon."
        )
    elif url:
        print(f"Sync remoto: {url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
