#!/usr/bin/env python3
"""Bloquea git push si hay secretos del portable en el commit o en el índice.

Uso (desde la raíz del repo):
  python tools/verificar_antes_de_push.py

Hook opcional (bloquea git push automáticamente):
  git config core.hooksPath .githooks

En Render van solo variables de entorno (DATABASE_URL, AUTH_USERS_REMOTE_TOKEN, etc.),
no auth_users.enc, auth_remote.txt ni .env del portable.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import PurePosixPath

# Rutas o nombres que no deben entrar al repositorio remoto
_PROHIBIDOS = frozenset(
    {
        ".env",
        ".env.local",
        "auth_users.json",
        "auth_users.enc",
        "auth_remote.txt",
        "auth_data_dir.txt",
    }
)


def _normalizar(ruta: str) -> str:
    return PurePosixPath(ruta.replace("\\", "/")).as_posix()


def _es_prohibido(ruta: str) -> bool:
    p = _normalizar(ruta)
    nombre = PurePosixPath(p).name
    if nombre in _PROHIBIDOS:
        return True
    if "/dist/" in f"/{p}/" or p.startswith("dist/"):
        return True
    if "/build/vl_grabacion/" in f"/{p}/" or p.startswith("build/vl_grabacion/"):
        return True
    return False


def _git(args: list[str]) -> str:
    r = subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if r.returncode not in (0, 1):
        print(r.stderr or r.stdout, file=sys.stderr)
    return r.stdout or ""


def main() -> int:
    staged = [
        ln.strip()
        for ln in _git(["diff", "--cached", "--name-only", "--diff-filter=ACM"]).splitlines()
        if ln.strip()
    ]
    tracked_prohibidos = [
        ln.strip()
        for ln in _git(["ls-files"]).splitlines()
        if ln.strip() and _es_prohibido(ln.strip())
    ]

    mal_staged = [f for f in staged if _es_prohibido(f)]
    if mal_staged:
        print("ERROR: estos archivos están en el commit y no deben subirse a Render/Git:", file=sys.stderr)
        for f in mal_staged:
            print(f"  - {f}", file=sys.stderr)
        print(
            "\nQuitálos del índice: git reset HEAD -- <archivo>\n"
            "Los secretos van en el dashboard de Render o solo en dist/ local.",
            file=sys.stderr,
        )
        return 1

    if tracked_prohibidos:
        print(
            "AVISO: el repo ya trackea archivos sensibles (deberían dejar de versionarse):",
            file=sys.stderr,
        )
        for f in tracked_prohibidos:
            print(f"  - {f}", file=sys.stderr)
        print(
            "\nPara sacarlos del repo sin borrarlos en disco:\n"
            "  git rm --cached <archivo>\n",
            file=sys.stderr,
        )
        return 1

    print("OK: no hay secretos del portable en el commit pendiente.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
