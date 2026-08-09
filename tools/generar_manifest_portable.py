#!/usr/bin/env python3
"""Genera y firma manifest.signed.json en dist/… (Fase 2.1).

Requiere la misma clave privada que entitlements:
  AUTH_ENTITLEMENT_PRIVATE_KEY  o  .entitlement_private.key
"""

from __future__ import annotations

import argparse
import os
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


def main() -> int:
    from app_branding import APP_EXE_BASENAME, APP_VERSION
    from auth_manifest import (
        escribir_manifest_firmado,
        firmar_manifest,
        generar_manifest,
    )

    parser = argparse.ArgumentParser(description="Firmar manifiesto del portable")
    parser.add_argument(
        "--dist",
        default=str(ROOT / "dist" / APP_EXE_BASENAME),
        help="Carpeta dist del portable",
    )
    parser.add_argument("--build-id", default="", help="Build ID opcional")
    parser.add_argument("--app-version", default=APP_VERSION)
    args = parser.parse_args()

    base = Path(args.dist)
    if not base.is_dir():
        print(f"ERROR: no existe {base}", file=sys.stderr)
        return 1

    body = generar_manifest(
        base, build_id=args.build_id, app_version=args.app_version
    )
    blob = firmar_manifest(body)
    if not blob:
        print(
            "ERROR: no se pudo firmar (definí AUTH_ENTITLEMENT_PRIVATE_KEY "
            "o .entitlement_private.key).",
            file=sys.stderr,
        )
        return 1
    path = escribir_manifest_firmado(base, blob)
    print(f"OK manifiesto: {path}")
    print(f"  build_id: {body.get('build_id')}")
    print(f"  files: {body.get('file_count')}")
    print(f"  root_hash: {(body.get('root_hash') or '')[:16]}…")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
