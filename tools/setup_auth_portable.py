#!/usr/bin/env python3
"""Genera archivos locales de desarrollo (auth_users.enc). Ya no hace falta para el portable.

El .exe 2026.8.3+ habla con Render sin auth_remote.enc ni padrón junto al exe.

Uso (solo desarrollo local, desde la raíz):

  set AUTH_ADMIN_PASSWORD=tu_clave
  python tools/setup_auth_portable.py
"""

from __future__ import annotations

import argparse
import getpass
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


def _escribir_remote_enc(ruta: Path, url: str, token: str) -> None:
    from auth_crypto import escribir_archivo_cifrado

    ruta.parent.mkdir(parents=True, exist_ok=True)
    escribir_archivo_cifrado(
        ruta,
        {
            "version": 1,
            "url": url.strip(),
            "token": token.strip(),
        },
    )
    print(f"  auth_remote.enc -> {ruta}")


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


def _cargar_env_local() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
    except ImportError:
        pass


def main() -> int:
    _cargar_env_local()
    parser = argparse.ArgumentParser(
        description="Generar auth_users.enc cifrado para el portable (sin JSON en claro)"
    )
    parser.add_argument(
        "--usuario",
        default=(os.environ.get("AUTH_ADMIN_USER") or "Lucas").strip(),
    )
    parser.add_argument(
        "--password",
        default="",
        help="Contraseña admin local (o variable AUTH_ADMIN_PASSWORD / .env)",
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
        default="",
        help="Bearer token (AUTH_USERS_REMOTE_TOKEN en Render / .env)",
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
    parser.add_argument(
        "--plain-remote",
        action="store_true",
        help="Además de auth_remote.enc, escribir auth_remote.txt en claro (no recomendado)",
    )
    args = parser.parse_args()
    if not args.password:
        args.password = (os.environ.get("AUTH_ADMIN_PASSWORD") or "").strip()
    if not args.token:
        args.token = (os.environ.get("AUTH_USERS_REMOTE_TOKEN") or "").strip()

    remote_path = DIST_DIR / "auth_remote.txt"
    remote_enc_path = DIST_DIR / "auth_remote.enc"
    url_prev, token_prev = _leer_auth_remote_existente(remote_path)

    if args.solo_url:
        DIST_DIR.mkdir(parents=True, exist_ok=True)
        if remote_enc_path.is_file() and not args.plain_remote:
            _escribir_remote_enc(remote_enc_path, AUTH_USERS_API_URL, token_prev)
        else:
            _escribir_remote(remote_path, AUTH_USERS_API_URL, token_prev)
        print(f"\nURL actualizada: {AUTH_USERS_API_URL}")
        return 0

    if not args.solo_remoto and not args.password:
        try:
            args.password = getpass.getpass("Contraseña del admin local: ")
        except (KeyboardInterrupt, EOFError):
            print("\nCancelado.", file=sys.stderr)
            return 130
        args.password = args.password.strip()
        if not args.password:
            print(
                "ERROR: indicá la contraseña con --password, AUTH_ADMIN_PASSWORD "
                "en el entorno o en .env (copiá .env.example).",
                file=sys.stderr,
            )
            print(
                'Ejemplo: set AUTH_ADMIN_PASSWORD=tu_clave && python tools/setup_auth_portable.py --sin-raiz',
                file=sys.stderr,
            )
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
            _escribir_remote_enc(remote_enc_path, url, token)
            if args.plain_remote:
                _escribir_remote(remote_path, url, token)
            elif remote_path.is_file():
                try:
                    remote_path.unlink()
                    print(f"  auth_remote.txt eliminado (reemplazado por .enc) -> {remote_path}")
                except OSError as exc:
                    print(f"  Aviso: no se pudo borrar auth_remote.txt: {exc}", file=sys.stderr)
    elif remote_enc_path.is_file() or remote_path.is_file():
        dest = remote_enc_path if remote_enc_path.is_file() else remote_path
        print(f"  auth remoto sin cambios -> {dest}")

    print("\nListo. En dist no hace falta auth_users.json ni auth_users.example.json.")
    if url and not token:
        print(
            "Completá el token con setup_auth_portable.py --token … "
            "para generar auth_remote.enc en dist."
        )
    elif url:
        print(f"Sync remoto: {url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
