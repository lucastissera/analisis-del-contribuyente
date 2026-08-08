#!/usr/bin/env python3
"""Lista cuentas con contraseña legacy (no bcrypt) en Neon / overlay local.

Uso (desde la raíz, con DATABASE_URL o stores locales):

  python tools/auditar_passwords_legacy.py

Migración automática: al iniciar sesión correctamente en la web (o vía
/api/auth/verificar), si la clave estaba en claro se reescribe a bcrypt.

Corte duro opcional en el servidor (después de que el listado quede vacío):

  AUTH_REJECT_LEGACY_PASSWORDS=1
"""

from __future__ import annotations

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
    from auth_registro import listar_passwords_legacy

    filas = listar_passwords_legacy()
    print("=== Auditoría passwords legacy (no bcrypt) ===")
    print(f"  Total: {len(filas)}")
    if not filas:
        print("\nOK: no hay credenciales en claro en usuarios_registrados.")
        print("    Podés activar AUTH_REJECT_LEGACY_PASSWORDS=1 en Render cuando quieras.")
        return 0
    print()
    for f in filas:
        flags = []
        if f.get("es_admin"):
            flags.append("admin")
        if f.get("pendiente_aprobacion"):
            flags.append("pendiente")
        if not f.get("activo"):
            flags.append("inactivo")
        extra = f" ({', '.join(flags)})" if flags else ""
        email = f.get("email") or "—"
        print(f"  - {f.get('usuario')}{extra}  email={email}")
    print(
        "\nAcción: que cada usuario (o admin) inicie sesión una vez con su clave actual;"
        "\n         el servidor migrará a bcrypt automáticamente."
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
