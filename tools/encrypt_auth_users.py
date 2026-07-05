#!/usr/bin/env python3
"""Genera auth_users.enc cifrado a partir de auth_users.json (desarrollo / build portable).

Uso (desde la raíz del proyecto):
  python tools/encrypt_auth_users.py
  python tools/encrypt_auth_users.py --entrada auth_users.json --salida dist/.../auth_users.enc
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from auth_crypto import escribir_archivo_cifrado, leer_archivo_usuarios


def main() -> int:
    parser = argparse.ArgumentParser(description="Cifrar listado de usuarios para el portable")
    parser.add_argument(
        "--entrada",
        type=Path,
        default=ROOT / "auth_users.json",
        help="JSON en claro (por defecto auth_users.json en la raíz)",
    )
    parser.add_argument(
        "--salida",
        type=Path,
        default=ROOT / "auth_users.enc",
        help="Archivo cifrado de salida",
    )
    args = parser.parse_args()

    entrada = args.entrada.resolve()
    if not entrada.is_file():
        print(f"ERROR: no existe {entrada}", file=sys.stderr)
        print("Copiá auth_users.example.json → auth_users.json y completá las claves.", file=sys.stderr)
        return 1

    if entrada.suffix.lower() == ".enc":
        data = leer_archivo_usuarios(entrada)
    else:
        try:
            with open(entrada, encoding="utf-8-sig") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"ERROR leyendo {entrada}: {exc}", file=sys.stderr)
            return 1

    if not isinstance(data, dict):
        print("ERROR: el JSON debe ser un objeto.", file=sys.stderr)
        return 1

    salida = args.salida.resolve()
    escribir_archivo_cifrado(salida, data)
    n = len(data.get("users", data) if isinstance(data.get("users"), dict) else data)
    print(f"OK: {salida} ({n} cuenta(s) cifradas)")
    print("No distribuyas auth_users.json en claro; solo auth_users.enc o auth_remote.txt.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
