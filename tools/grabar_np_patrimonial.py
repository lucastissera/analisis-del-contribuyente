#!/usr/bin/env python3
"""Alias de grabar_nuestra_parte.py con --auto-np (compat. explorar_np_patrimonial.bat)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if "--auto-np" not in sys.argv:
    sys.argv.append("--auto-np")

_path = ROOT / "tools" / "grabar_nuestra_parte.py"
_spec = importlib.util.spec_from_file_location("grabar_nuestra_parte", _path)
_mod = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_mod)

if __name__ == "__main__":
    raise SystemExit(_mod.main())
