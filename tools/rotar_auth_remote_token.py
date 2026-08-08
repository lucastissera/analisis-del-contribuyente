#!/usr/bin/env python3
"""Rota AUTH_USERS_REMOTE_TOKEN (sync portable ↔ Render).

Qué logra: si el token viejo quedó en un USB/dist filtrado, deja de servir
para llamar a /api/auth-users, /api/auth/verificar, cupo, etc.

Orden seguro (con ventana de gracia):

  1. Deploy del código que acepta AUTH_USERS_REMOTE_TOKEN_PREVIOUS (ya en main).
  2. python tools/rotar_auth_remote_token.py          # solo muestra valores
  3. En Render → Environment:
       AUTH_USERS_REMOTE_TOKEN=<nuevo>
       AUTH_USERS_REMOTE_TOKEN_PREVIOUS=<viejo>
  4. python tools/rotar_auth_remote_token.py --aplicar  # .env + auth_remote.enc locales
  5. Redistribuí el portable (o regenerá auth_remote.enc en cada copia).
  6. Cuando no queden portables con el token viejo, borrá PREVIOUS en Render.

Sin --aplicar no toca archivos (modo checklist).
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
        if ruta.parent == ROOT or ruta.parent.is_dir() or "dist" in ruta.parts:
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Rotar AUTH_USERS_REMOTE_TOKEN")
    parser.add_argument(
        "--aplicar",
        action="store_true",
        help="Escribe .env + auth_remote.enc con el token nuevo (después de pegar en Render)",
    )
    parser.add_argument(
        "--token-nuevo",
        default="",
        help="Token nuevo (por defecto: secrets.token_urlsafe(48))",
    )
    args = parser.parse_args()

    viejo = _token_actual()
    nuevo = (args.token_nuevo or "").strip() or secrets.token_urlsafe(48)
    url = _url_sync()

    print("=== Rotación AUTH_USERS_REMOTE_TOKEN ===")
    print(f"  URL sync: {url or '(sin URL)'}")
    if viejo:
        print(f"  Token actual (oculto): …{viejo[-6:]}  (len={len(viejo)})")
    else:
        print("  Token actual: (no encontrado en .env / auth_remote)")
    print(f"  Token nuevo: {nuevo}")
    print()
    print("En Render -> Environment (Secrets), pega:")
    print(f"  AUTH_USERS_REMOTE_TOKEN={nuevo}")
    if viejo and viejo != nuevo:
        print(f"  AUTH_USERS_REMOTE_TOKEN_PREVIOUS={viejo}")
    else:
        print("  AUTH_USERS_REMOTE_TOKEN_PREVIOUS=  (opcional; solo si había token viejo)")
    print()
    print(
        "Luego, en esta máquina: python tools/rotar_auth_remote_token.py --aplicar"
        "\n  (o repetí con --token-nuevo el mismo valor si regenerás en otra sesión)."
    )
    print(
        "Cuando todos los portables usen el nuevo, borrá AUTH_USERS_REMOTE_TOKEN_PREVIOUS en Render."
    )

    if not args.aplicar:
        print("\nModo checklist: no se modificó ningún archivo.")
        return 0

    if not url:
        print("ERROR: falta URL de sync (AUTH_USERS_URL / auth_remote).", file=sys.stderr)
        return 1

    env_path = ROOT / ".env"
    updates = {"AUTH_USERS_REMOTE_TOKEN": nuevo, "AUTH_USERS_URL": url}
    if viejo and viejo != nuevo:
        updates["AUTH_USERS_REMOTE_TOKEN_PREVIOUS"] = viejo
    _upsert_env(env_path, updates)
    print(f"\n  actualizado: {env_path}")
    _escribir_remote_locales(url, nuevo)
    print("\nListo en local. Confirmá Render y probá sync / login portable.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
