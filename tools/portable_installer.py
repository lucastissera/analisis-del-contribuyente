#!/usr/bin/env python3
"""
Compila el instalador/actualizador (Inno Setup) sobre el portable ya generado.

No recompila el .exe: usa dist/AnalisisIntegralContribuyente/.

Uso (desde la raíz del proyecto):
  python tools/portable_installer.py
  python tools/portable_installer.py --sin-playwright

Salida:
  dist/instalador/AIC-Update-<versión>.exe
  dist/instalador/AIC-Update-<versión>-sin-chromium.exe  (con --sin-playwright)

Chromium se omite en destino si ya está la misma carpeta chromium-*.

Una corrida del .exe de update actualiza UNA carpeta (ej. D:\\sistemas\\juan).
Para el siguiente usuario, se ejecuta de nuevo y se elige su carpeta.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_branding import APP_EXE_BASENAME, APP_VERSION

DIST_DIR = ROOT / "dist" / APP_EXE_BASENAME
ISS = ROOT / "tools" / "installer.iss"
OUT_DIR = ROOT / "dist" / "instalador"
EXE_NAME = f"{APP_EXE_BASENAME}.exe"

_ISCC_CANDIDATOS = (
    Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
    / "Inno Setup 6"
    / "ISCC.exe",
    Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    / "Inno Setup 6"
    / "ISCC.exe",
    Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
    Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
    / "Inno Setup 7"
    / "ISCC.exe",
    Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    / "Inno Setup 7"
    / "ISCC.exe",
)


def _buscar_iscc() -> Path | None:
    env = (os.environ.get("AIC_ISCC") or "").strip()
    if env:
        p = Path(env)
        if p.is_file():
            return p
    for p in _ISCC_CANDIDATOS:
        if p.is_file():
            return p
    from shutil import which

    w = which("ISCC") or which("iscc")
    if w:
        return Path(w)
    return None


def _instalar_inno_setup() -> Path | None:
    """Instala Inno Setup 6 con winget si hace falta (aceptado para este proceso)."""
    print("Inno Setup no está. Instalando JRSoftware.InnoSetup con winget…", flush=True)
    r = subprocess.run(
        [
            "winget",
            "install",
            "--id",
            "JRSoftware.InnoSetup",
            "-e",
            "--accept-package-agreements",
            "--accept-source-agreements",
            "--disable-interactivity",
        ],
        cwd=str(ROOT),
    )
    if r.returncode != 0:
        print(
            "ERROR: no se pudo instalar Inno Setup. Instalalo a mano y reintentá.\n"
            "  winget install --id JRSoftware.InnoSetup -e",
            file=sys.stderr,
        )
        return None
    return _buscar_iscc()


def _stamp_chromium() -> str:
    """Nombre de la carpeta chromium-* del dist (version de Playwright)."""
    base = DIST_DIR / "ms-playwright"
    if not base.is_dir():
        return ""
    nombres = sorted(
        p.name
        for p in base.iterdir()
        if p.is_dir() and p.name.startswith("chromium-")
    )
    stamp = nombres[0] if nombres else ""
    (DIST_DIR / "ms-playwright.stamp").write_text(
        (stamp or "none") + "\n", encoding="ascii"
    )
    return stamp


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compila el actualizador Inno sobre el portable ya generado."
    )
    parser.add_argument(
        "--sin-playwright",
        action="store_true",
        help="Paquete liviano: no incluye Chromium (solo si el destino ya lo tiene).",
    )
    args = parser.parse_args()

    if not ISS.is_file():
        print(f"ERROR: no se encuentra {ISS}", file=sys.stderr)
        return 1
    if not (DIST_DIR / EXE_NAME).is_file():
        print(
            f"ERROR: no está el portable en {DIST_DIR / EXE_NAME}.\n"
            "  Compilalo antes: python tools/portable_build.py",
            file=sys.stderr,
        )
        return 1

    iscc = _buscar_iscc()
    if iscc is None:
        iscc = _instalar_inno_setup()
    if iscc is None:
        return 1

    stamp = _stamp_chromium()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if args.sin_playwright:
        output_base = f"AIC-Update-{APP_VERSION}-sin-chromium"
        extra = " (sin Chromium)"
    else:
        output_base = f"AIC-Update-{APP_VERSION}"
        extra = " (incluye Chromium; en destino se omite si ya esta esa version)"

    print(f"Inno Setup: {iscc}", flush=True)
    print(f"Origen:     {DIST_DIR}", flush=True)
    print(f"Version:    {APP_VERSION}", flush=True)
    print(f"Chromium:   {stamp or '(no hay ms-playwright)'}", flush=True)
    print(f"Compilando instalador{extra}...", flush=True)

    cmd = [
        str(iscc),
        f"/DMyAppVersion={APP_VERSION}",
        f"/DMyAppExeName={EXE_NAME}",
        f"/DPlaywrightStamp={stamp}",
        f"/DOutputBase={output_base}",
    ]
    if args.sin_playwright:
        cmd.append("/DSkipPlaywright=1")
    cmd.append(str(ISS))
    r = subprocess.run(cmd, cwd=str(ROOT))
    if r.returncode != 0:
        print("ERROR: fallo la compilacion de Inno Setup.", file=sys.stderr)
        return r.returncode

    setup = OUT_DIR / f"{output_base}.exe"
    if not setup.is_file():
        print(f"ERROR: no aparecio {setup}", file=sys.stderr)
        return 1

    print(
        f"\nListo: {setup}\n"
        "Uso en Estudio DyC (una carpeta por vez):\n"
        "  1. Cerrar el sistema de Juan.\n"
        "  2. Ejecutar el instalador y elegir D:\\sistemas\\juan\n"
        "  3. Cuando termine, cerrar el de Diego y ejecutar de nuevo -> D:\\sistemas\\diego\n"
        "No pisa navegador-perfil ni archivos de sitio que ya existan.\n"
        "Chromium: se copia solo si falta o cambio la version.\n",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
