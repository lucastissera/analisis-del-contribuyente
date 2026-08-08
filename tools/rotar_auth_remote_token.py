#!/usr/bin/env python3
"""Rota AUTH_USERS_REMOTE_TOKEN (sync portable <-> Render).

Que logra: si el token viejo quedo en un USB/dist filtrado, deja de servir
para llamar a /api/auth-users, /api/auth/verificar, cupo, etc.

Orden seguro (con ventana de gracia):

  1. Deploy del codigo que acepta AUTH_USERS_REMOTE_TOKEN_PREVIOUS (ya en main).
  2. python tools/rotar_auth_remote_token.py
       -> escribe el token nuevo en .auth_token_rotation.local (gitignored)
  3. En Render -> Environment:
       AUTH_USERS_REMOTE_TOKEN=<nuevo del archivo local>
       AUTH_USERS_REMOTE_TOKEN_PREVIOUS=<valor que hoy tiene AUTH_USERS_REMOTE_TOKEN en Render>
  4. python tools/rotar_auth_remote_token.py --aplicar
  5. Redistribuir portable / regenerar auth_remote.enc
  6. Cuando no queden portables viejos, borrar PREVIOUS en Render.

Sin --aplicar no toca .env ni auth_remote.enc.
"""

from __future__ import annotations

import argparse
import os
import re
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

STAGING = ROOT / ".auth_token_rotation.local"

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:
    pass


def _token_actual() -> str:
    from auth import _normalizar_token_remoto, _remote_token

    t = _normalizar_token_remoto(os.environ.get("AUTH_USERS_REMOTE_TOKEN") or "")
    if t:
        return t
    return _remote_token()


def _url_sync() -> str:
    from app_branding import AUTH_USERS_API_URL
    from auth import _remote_url

    return (_remote_url() or AUTH_USERS_API_URL or "").strip()


def _mask(token: str) -> str:
    if not token:
        return "(vacio)"
    if len(token) <= 8:
        return "*" * len(token)
    return f"...{token[-4:]} (len={len(token)})"


def _upsert_env(path: Path, updates: dict[str, str]) -> None:
    if path.is_file():
        texto = path.read_text(encoding="utf-8")
    else:
        texto = ""
    lineas = texto.splitlines()
    claves = set(updates)
    vistas: set[str] = set()
    nuevas: list[str] = []
    for ln in lineas:
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", ln.strip())
        if m and m.group(1) in claves:
            k = m.group(1)
            nuevas.append(f"{k}={updates[k]}")
            vistas.add(k)
        else:
            nuevas.append(ln)
    for k, v in updates.items():
        if k not in vistas:
            if nuevas and nuevas[-1].strip():
                nuevas.append("")
            nuevas.append(f"{k}={v}")
    path.write_text("\n".join(nuevas) + ("\n" if nuevas else ""), encoding="utf-8")


def _escribir_remote_locales(url: str, token: str) -> None:
    from app_branding import APP_EXE_BASENAME
    from auth_crypto import escribir_archivo_cifrado

    payload = {"version": 1, "url": url, "token": token}
    destinos = [
        ROOT / "auth_remote.enc",
        ROOT / "dist" / APP_EXE_BASENAME / "auth_remote.enc",
    ]
    for ruta in destinos:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        escribir_archivo_cifrado(ruta, payload)
        print(f"  actualizado: {ruta}")
        txt = ruta.with_suffix(".txt")
        if txt.is_file() and txt.name == "auth_remote.txt":
            try:
                txt.unlink()
                print(f"  eliminado (reemplazado por .enc): {txt}")
            except OSError as exc:
                print(f"  aviso: no se pudo borrar {txt}: {exc}", file=sys.stderr)


def _leer_staging() -> str:
    if not STAGING.is_file():
        return ""
    try:
        for ln in STAGING.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if ln.startswith("AUTH_USERS_REMOTE_TOKEN="):
                return ln.split("=", 1)[1].strip()
    except OSError:
        return ""
    return ""


def _escribir_staging(nuevo: str, url: str) -> None:
    STAGING.write_text(
        "\n".join(
            [
                "# Generado por tools/rotar_auth_remote_token.py — NO subir a Git",
                f"AUTH_USERS_URL={url}",
                f"AUTH_USERS_REMOTE_TOKEN={nuevo}",
                "# En Render, PREVIOUS = el valor ACTUAL de AUTH_USERS_REMOTE_TOKEN (antes de pegar el nuevo).",
                "",
            ]
        ),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Rotar AUTH_USERS_REMOTE_TOKEN")
    parser.add_argument(
        "--aplicar",
        action="store_true",
        help="Escribe .env + auth_remote.enc con el token nuevo (despues de pegar en Render)",
    )
    parser.add_argument(
        "--token-nuevo",
        default="",
        help="Token nuevo (por defecto: reusa .auth_token_rotation.local o genera uno)",
    )
    args = parser.parse_args()

    viejo = _token_actual()
    url = _url_sync()
    nuevo = (args.token_nuevo or "").strip() or _leer_staging() or secrets.token_urlsafe(48)

    if not args.aplicar:
        _escribir_staging(nuevo, url)

    print("=== Rotacion AUTH_USERS_REMOTE_TOKEN ===")
    print(f"  URL sync: {url or '(sin URL)'}")
    print(f"  Token actual: {_mask(viejo)}")
    print(f"  Token nuevo:  {_mask(nuevo)}")
    print(f"  Detalle del nuevo: {STAGING.name} (local, no se imprime en claro aqui)")
    print()
    print("Pasos en Render -> Environment:")
    print("  1) Copiar el valor ACTUAL de AUTH_USERS_REMOTE_TOKEN a AUTH_USERS_REMOTE_TOKEN_PREVIOUS")
    print(f"  2) Pegar el nuevo desde {STAGING.name} en AUTH_USERS_REMOTE_TOKEN")
    print("  3) Guardar / redeploy si hace falta")
    print()
    print("Luego en esta maquina:")
    print("  python tools/rotar_auth_remote_token.py --aplicar")
    print("Redistribuir portable. Al final, borrar PREVIOUS en Render.")

    if not args.aplicar:
        print("\nModo checklist: no se modifico .env ni auth_remote.enc.")
        return 0

    if not url:
        print("ERROR: falta URL de sync (AUTH_USERS_URL / auth_remote).", file=sys.stderr)
        return 1
    if not nuevo:
        print("ERROR: no hay token nuevo (corre sin --aplicar primero).", file=sys.stderr)
        return 1

    env_path = ROOT / ".env"
    updates = {"AUTH_USERS_REMOTE_TOKEN": nuevo, "AUTH_USERS_URL": url}
    if viejo and viejo != nuevo:
        updates["AUTH_USERS_REMOTE_TOKEN_PREVIOUS"] = viejo
    _upsert_env(env_path, updates)
    print(f"\n  actualizado: {env_path}")
    _escribir_remote_locales(url, nuevo)
    print("\nListo en local. Confirma Render y prueba sync / login portable.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
