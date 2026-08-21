#!/usr/bin/env python3
"""
Unico comando para actualizar UNA carpeta (Estudio DyC: juan, luego diego).

Elige solo el paquete (completo o sin Chromium) y el instalador omite
archivos que no hacen falta (licencia, perfil, Chromium si ya esta).

  aplicar_update.bat
  aplicar_update.bat "D:\\sistemas\\juan"
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

OUT_DIR = ROOT / "dist" / "instalador"
DIST_DIR = ROOT / "dist" / APP_EXE_BASENAME
EXE_NAME = f"{APP_EXE_BASENAME}.exe"
PADRE_TIPICO = Path(r"D:\sistemas")


def _stamp_chromium() -> str:
    p = DIST_DIR / "ms-playwright.stamp"
    if p.is_file():
        return p.read_text(encoding="ascii").strip()
    base = DIST_DIR / "ms-playwright"
    if not base.is_dir():
        return ""
    nombres = sorted(
        x.name
        for x in base.iterdir()
        if x.is_dir() and x.name.startswith("chromium-")
    )
    return nombres[0] if nombres else ""


def _destino_tiene_chromium(dest: Path, stamp: str) -> bool:
    if not dest.is_dir():
        return False
    if stamp and stamp != "none":
        return (dest / "ms-playwright" / stamp).is_dir()
    return (dest / "ms-playwright").is_dir()


def _paquete(nombre: str) -> Path | None:
    p = OUT_DIR / nombre
    return p if p.is_file() else None


def _elegir_instalador(dest: Path | None) -> tuple[Path | None, str]:
    """Completo si falta Chromium; liviano si el destino ya lo tiene."""
    full = _paquete(f"AIC-Update-{APP_VERSION}.exe")
    slim = _paquete(f"AIC-Update-{APP_VERSION}-sin-chromium.exe")
    stamp = _stamp_chromium()
    if dest is not None and _destino_tiene_chromium(dest, stamp) and slim is not None:
        return slim, "Chromium: ya esta, se omite"
    if full is not None:
        if dest is not None and _destino_tiene_chromium(dest, stamp):
            return full, "Chromium: ya esta, el instalador no lo recopia"
        return full, "Chromium: se copia si falta"
    if slim is not None:
        return slim, "Chromium: paquete liviano (debe existir en destino)"
    if not OUT_DIR.is_dir():
        return None, ""
    cands = [
        p
        for p in OUT_DIR.glob("AIC-Update-*.exe")
        if "sin-chromium" not in p.name
    ]
    cands.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    if cands:
        return cands[0], "Chromium: segun instalador encontrado"
    return None, ""


def _correr_inno(setup: Path, dest: Path, log: Path) -> int:
    arglist = [
        "/SILENT",
        "/NORESTART",
        "/SUPPRESSMSGBOXES",
        "/FORCECLOSEAPPLICATIONS",
        f'/DIR="{dest}"',
        f'/LOG="{log}"',
    ]
    ps_args = ",".join("'" + a.replace("'", "''") + "'" for a in arglist)
    setup_ps = str(setup).replace("'", "''")
    r = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            f"$p = Start-Process -FilePath '{setup_ps}' "
            f"-ArgumentList @({ps_args}) -Wait -PassThru; "
            f"if (-not $p) {{ exit 1 }}; exit $p.ExitCode",
        ]
    )
    return r.returncode


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Actualiza una carpeta del sistema (una por corrida)."
    )
    parser.add_argument(
        "carpeta",
        nargs="?",
        default="",
        help="Carpeta del usuario (ej. D:\\sistemas\\juan). Sin esto, abre el asistente.",
    )
    parser.add_argument(
        "--comprobar",
        action="store_true",
        help="No instala: muestra que paquete usaria y si el destino esta listo.",
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Forzar el asistente aunque pases carpeta.",
    )
    parser.add_argument(
        "--forzar-padre",
        action="store_true",
        help="Permitir actualizar D:\\sistemas (no recomendado).",
    )
    args = parser.parse_args()

    dest: Path | None = None
    if (args.carpeta or "").strip() and not args.gui:
        dest = Path(args.carpeta.strip()).expanduser()
        try:
            dest = dest.resolve()
        except OSError:
            dest = dest.absolute()
        if dest == PADRE_TIPICO.resolve() and not args.forzar_padre:
            print(
                "ERROR: esa ruta es la carpeta padre D:\\sistemas.\n"
                "  Pasa la carpeta de UN usuario, por ejemplo D:\\sistemas\\juan",
                file=sys.stderr,
            )
            return 1
        if not dest.is_dir():
            print(f"ERROR: no existe la carpeta {dest}", file=sys.stderr)
            return 1

    setup, motivo = _elegir_instalador(dest)
    if setup is None:
        print(
            "ERROR: no hay instalador en dist\\instalador\\.\n"
            "  Generarlo: python tools/portable_installer.py",
            file=sys.stderr,
        )
        return 1

    print(f"Instalador: {setup.name}", flush=True)
    if motivo:
        print(motivo, flush=True)

    if dest is None:
        if args.comprobar:
            print("Modo asistente: se usaria el paquete completo (Chromium se omite al copiar si ya esta).", flush=True)
            return 0
        print(
            "Abriendo asistente: elegi la carpeta del usuario y espera que termine.",
            flush=True,
        )
        return subprocess.call([str(setup)], cwd=str(ROOT))

    exe_ok = (dest / EXE_NAME).is_file()
    nav_ok = (dest / "navegador-perfil").is_dir()
    print(f"Destino:    {dest}", flush=True)
    print(f"Exe:        {'si' if exe_ok else 'NO'}", flush=True)
    print(f"Perfil nav: {'si (no se pisa)' if nav_ok else 'no'}", flush=True)
    if args.comprobar:
        print("Comprobacion OK. No se instalo nada.", flush=True)
        return 0

    if not exe_ok:
        print(
            f"AVISO: no esta {EXE_NAME} en esa carpeta (instalacion nueva o ruta incorrecta).",
            flush=True,
        )

    log = Path(os.environ.get("TEMP") or ".") / "aic_aplicar_update.log"
    print(
        "Actualizando (una carpeta). Cuando termine, podes apuntar a otro usuario.",
        flush=True,
    )
    code = _correr_inno(setup, dest, log)
    if code != 0:
        print(
            f"ERROR: el actualizador salio con codigo {code}. Ver {log}",
            file=sys.stderr,
        )
        return code
    print(f"Listo. Carpeta actualizada: {dest}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
