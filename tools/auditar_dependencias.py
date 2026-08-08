#!/usr/bin/env python3
"""SCA: audita vulnerabilidades conocidas del lockfile (P2.14).

Uso:
  python tools/auditar_dependencias.py

Requiere: pip install pip-audit
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQ = ROOT / "requirements.txt"


def main() -> int:
    if not REQ.is_file():
        print("ERROR: falta requirements.txt", file=sys.stderr)
        return 1
    exe = shutil.which("pip-audit")
    if exe:
        cmd = [exe, "-r", str(REQ), "--progress-spinner", "off"]
    else:
        cmd = [
            sys.executable,
            "-m",
            "pip_audit",
            "-r",
            str(REQ),
            "--progress-spinner",
            "off",
        ]
    print(" ".join(cmd), flush=True)
    r = subprocess.run(cmd, cwd=str(ROOT))
    if r.returncode == 0:
        print("OK: pip-audit no reportó vulnerabilidades conocidas en el lockfile.")
    else:
        print(
            "pip-audit encontró hallazgos o falló (codigo %s). "
            "Revisá el listado y actualizá requirements.in + lockfile."
            % r.returncode,
            file=sys.stderr,
        )
    return r.returncode


if __name__ == "__main__":
    raise SystemExit(main())
