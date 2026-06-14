#!/usr/bin/env python3
"""Crea o actualiza el administrador en PostgreSQL (Neon).

Uso (con DATABASE_URL en el entorno):

    python tools/init_admin_neon.py
    python tools/init_admin_neon.py --user Lucas --password "Lucas1992."

Variables opcionales: AUTH_ADMIN_USER, AUTH_ADMIN_PASSWORD, AUTH_ADMIN_VALIDO_HASTA.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="Guardar administrador en Neon/PostgreSQL")
    parser.add_argument("--user", default=(os.environ.get("AUTH_ADMIN_USER") or "Lucas").strip())
    parser.add_argument(
        "--password",
        default=(os.environ.get("AUTH_ADMIN_PASSWORD") or "").strip(),
        help="Contraseña en texto plano (se guarda hasheada con bcrypt)",
    )
    parser.add_argument(
        "--valido-hasta",
        default=(os.environ.get("AUTH_ADMIN_VALIDO_HASTA") or "").strip(),
        help="Fecha YYYY-MM-DD; por defecto ~100 años desde hoy",
    )
    args = parser.parse_args()

    if not (os.environ.get("DATABASE_URL") or os.environ.get("AUTH_DATABASE_URL") or "").strip():
        print("ERROR: definí DATABASE_URL (connection string de Neon).")
        return 1
    if not args.user:
        print("ERROR: usuario admin vacío.")
        return 1
    if not args.password:
        print("ERROR: indicá --password o AUTH_ADMIN_PASSWORD.")
        return 1

    from auth_registro import admin_en_overlay, guardar_admin_sistema
    from auth_registro import _admin_valido_hasta_default, _parse_fecha_local  # noqa: PLC2701
    from auth_registro_db import enabled, estado_db

    if not enabled():
        print("ERROR: DATABASE_URL no activa en auth_registro_db.")
        return 1

    previo = admin_en_overlay(args.user)
    vh = _parse_fecha_local(args.valido_hasta) if args.valido_hasta else _admin_valido_hasta_default()
    guardar_admin_sistema(args.user, args.password, valido_hasta=vh)
    st = estado_db()
    accion = "actualizado" if previo else "creado"
    print(f"OK: administrador «{args.user}» {accion} en PostgreSQL.")
    print(f"    Vencimiento: {vh.isoformat()}")
    print(f"    Estado DB: {st}")
    print()
    print("Próximo paso en Render:")
    print("  1. Probá login con Lucas.")
    print("  2. Si funciona, podés borrar AUTH_USERS_JSON.")
    print("  3. Opcional: quitá AUTH_ADMIN_PASSWORD (la clave ya está en Neon).")
    print("     Mantené AUTH_ADMIN_USER=Lucas para identificar al admin.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
