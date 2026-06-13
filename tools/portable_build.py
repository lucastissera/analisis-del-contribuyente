#!/usr/bin/env python3
"""
Compila el portable con PyInstaller, copia ``auth_users.json`` e instala Chromium
en ``dist/AnalisisIntegralContribuyente/ms-playwright`` para descarga ARCA en el .exe.

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
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_branding import APP_EXE_BASENAME

DIST_DIR = ROOT / "dist" / APP_EXE_BASENAME
SPEC = ROOT / "MisComprobantesDesktop.spec"
AUTH_SRC = ROOT / "auth_users.json"
BROWSERS_DIR = DIST_DIR / "ms-playwright"
LOGO_PNG = ROOT / "static" / "logo.png"
LOGO_ICO = ROOT / "static" / "logo.ico"
ISOTIPO_PNG = ROOT / "static" / "isotipo.png"


def _preparar_logo() -> None:
    """Regenera logo.ico desde static/isotipo.png (marca Vórtice) para el icono del .exe."""
    fuente = ISOTIPO_PNG if ISOTIPO_PNG.is_file() else LOGO_PNG
    if not fuente.is_file():
        return
    try:
        from PIL import Image

        img = Image.open(fuente).convert("RGBA")
        # Recorte cuadrado al contenido visible (isotipo / isologo)
        bbox = img.getbbox()
        if bbox:
            img = img.crop(bbox)
        lado = max(img.size)
        cuadrado = Image.new("RGBA", (lado, lado), (0, 0, 0, 0))
        ox = (lado - img.width) // 2
        oy = (lado - img.height) // 2
        cuadrado.paste(img, (ox, oy), img)
        cuadrado.save(
            LOGO_ICO,
            format="ICO",
            sizes=[(s, s) for s in (16, 32, 48, 64, 128, 256)],
        )
    except Exception as exc:
        print(f"Aviso: no se pudo regenerar {LOGO_ICO}: {exc}", file=sys.stderr)


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
    _preparar_logo()
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
    ejemplo_remoto = ROOT / "auth_remote.example.txt"
    if ejemplo_remoto.is_file():
        shutil.copy2(ejemplo_remoto, DIST_DIR / "auth_remote.example.txt")
    if AUTH_SRC.is_file():
        dest = DIST_DIR / "auth_users.json"
        shutil.copy2(AUTH_SRC, dest)
        print(f"Claves sincronizadas: {dest}", flush=True)
    else:
        print(
            "Aviso: no hay auth_users.json en la raíz del repo; "
            "configurá auth_remote.txt o .env para usuarios en la nube "
            "(ver docs/AUTH_USUARIOS_NUBE.md).",
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
