#!/usr/bin/env python3
"""
Compila el portable con PyInstaller, copia ``auth_users.json`` e instala Chromium
en ``dist/MisComprobantesAnalisis/ms-playwright`` para descarga ARCA en el .exe.

Uso: desde la raíz del proyecto
  python tools/portable_build.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = ROOT / "dist" / "MisComprobantesAnalisis"
SPEC = ROOT / "MisComprobantesDesktop.spec"
AUTH_SRC = ROOT / "auth_users.json"
BROWSERS_DIR = DIST_DIR / "ms-playwright"


def _instalar_chromium_portable() -> int:
    BROWSERS_DIR.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["PLAYWRIGHT_BROWSERS_PATH"] = str(BROWSERS_DIR)
    print(f"Instalando Chromium para ARCA en {BROWSERS_DIR}…", flush=True)
    r = subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        env=env,
        cwd=str(ROOT),
    )
    if r.returncode != 0:
        print(
            "AVISO: falló playwright install chromium. "
            "La descarga ARCA no funcionará en el .exe hasta reinstalarlo.",
            file=sys.stderr,
        )
    return r.returncode


def main() -> int:
    if not SPEC.is_file():
        print(f"ERROR: no se encuentra {SPEC}", file=sys.stderr)
        return 1
    print("Ejecutando PyInstaller…", flush=True)
    r = subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", str(SPEC)],
        cwd=str(ROOT),
    )
    if r.returncode != 0:
        return r.returncode
    if not DIST_DIR.is_dir():
        print(f"ERROR: no existe {DIST_DIR} tras compilar.", file=sys.stderr)
        return 1
    if AUTH_SRC.is_file():
        dest = DIST_DIR / "auth_users.json"
        shutil.copy2(AUTH_SRC, dest)
        print(f"Claves sincronizadas: {dest}", flush=True)
    else:
        print(
            "Aviso: no hay auth_users.json en la raíz del repo; "
            "el portable usará el ejemplo empaquetado o credenciales por entorno.",
            flush=True,
        )
    _instalar_chromium_portable()
    print(
        f"\nListo: {DIST_DIR}\n"
        "Distribuí la carpeta completa (exe + _internal + ms-playwright).\n",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
