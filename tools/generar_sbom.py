#!/usr/bin/env python3
"""Genera SBOM CycloneDX 1.5 JSON desde requirements.txt (P2.14).

No depende de cyclonedx-bom (a veces falla validación). Parsea el lockfile
pineado y emite un inventario usable para auditoría.

Uso:
  python tools/generar_sbom.py
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "sbom" / "cyclonedx-requirements.json"
_PIN = re.compile(r"^([A-Za-z0-9_.\-]+)==([^#\s]+)")


def _parse_lock(path: Path) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for ln in path.read_text(encoding="utf-8").splitlines():
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        m = _PIN.match(s)
        if m:
            out.append((m.group(1), m.group(2)))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="SBOM CycloneDX desde requirements.txt")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    req = ROOT / "requirements.txt"
    if not req.is_file():
        print("ERROR: falta requirements.txt (python tools/actualizar_lockfile.py)", file=sys.stderr)
        return 1

    pkgs = _parse_lock(req)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    components = []
    for name, ver in pkgs:
        purl = f"pkg:pypi/{name.lower()}@{ver}"
        components.append(
            {
                "type": "library",
                "name": name,
                "version": ver,
                "purl": purl,
                "bom-ref": purl,
            }
        )

    bom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:{uuid.uuid4()}",
        "version": 1,
        "metadata": {
            "timestamp": now,
            "tools": [
                {
                    "vendor": "AnalisisIntegralContribuyente",
                    "name": "tools/generar_sbom.py",
                    "version": "1.0",
                }
            ],
            "component": {
                "type": "application",
                "name": "AnalisisIntegralContribuyente",
                "version": "lockfile",
            },
        },
        "components": components,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(bom, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"OK SBOM: {args.out} ({len(components)} componentes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
