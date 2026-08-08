#!/usr/bin/env python3
"""Genera requirements.txt pineado desde requirements.in (P2.14).

Crea un venv temporal, instala requirements.in y congela versiones exactas.
Compatible con Python reciente (no depende de pip-tools).

Uso (desde la raíz):
  python tools/actualizar_lockfile.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import venv
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IN_FILE = ROOT / "requirements.in"
OUT_FILE = ROOT / "requirements.txt"

# Paquetes de tooling del venv que no deben ir al lock de la app
_EXCLUIR = frozenset(
    {
        "pip",
        "setuptools",
        "wheel",
        "pip-tools",
        "pip-audit",
        "cyclonedx-bom",
        "cyclonedx-python-lib",
        "packageurl-python",
        "boolean.py",
        "CacheControl",
        "filelock",
        "msgpack",
        "tomli",
        "pyparsing",
        "license-expression",
        "sortedcontainers",
        "py-serializable",
    }
)


def main() -> int:
    if not IN_FILE.is_file():
        print(f"ERROR: falta {IN_FILE}", file=sys.stderr)
        return 1

    tmp = Path(tempfile.mkdtemp(prefix="aic-lock-"))
    try:
        print(f"Creando venv temporal en {tmp} …", flush=True)
        venv.create(tmp, with_pip=True, clear=True)
        if sys.platform == "win32":
            py = tmp / "Scripts" / "python.exe"
        else:
            py = tmp / "bin" / "python"
        if not py.is_file():
            print("ERROR: no se creó el python del venv", file=sys.stderr)
            return 1

        print("Instalando requirements.in …", flush=True)
        r = subprocess.run(
            [str(py), "-m", "pip", "install", "--upgrade", "pip"],
            cwd=str(ROOT),
        )
        if r.returncode != 0:
            return r.returncode
        r = subprocess.run(
            [str(py), "-m", "pip", "install", "-r", str(IN_FILE)],
            cwd=str(ROOT),
        )
        if r.returncode != 0:
            return r.returncode

        print("Congelando versiones …", flush=True)
        r = subprocess.run(
            [str(py), "-m", "pip", "freeze"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if r.returncode != 0:
            print(r.stderr, file=sys.stderr)
            return r.returncode

        lineas: list[str] = []
        for ln in r.stdout.splitlines():
            s = ln.strip()
            if not s or s.startswith("#"):
                continue
            # editable / local paths no
            if s.startswith("-e ") or " @ " in s or s.startswith("file:"):
                continue
            nombre = s.split("==", 1)[0].split("[", 1)[0].strip()
            if nombre.lower() in {x.lower() for x in _EXCLUIR}:
                continue
            lineas.append(s)
        lineas.sort(key=str.lower)

        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        encabezado = (
            f"# Lockfile generado automáticamente — no editar a mano.\n"
            f"# Fuente: requirements.in | {ts} | Python {sys.version.split()[0]}\n"
            f"# Regenerar: python tools/actualizar_lockfile.py\n"
            f"#\n"
        )
        OUT_FILE.write_text(encabezado + "\n".join(lineas) + "\n", encoding="utf-8")
        print(f"OK: {OUT_FILE} ({len(lineas)} paquetes)", flush=True)
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
