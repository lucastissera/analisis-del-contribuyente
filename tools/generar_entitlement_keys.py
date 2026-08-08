#!/usr/bin/env python3
"""Genera un par Ed25519 para entitlements (P2.12).

Uso:
  python tools/generar_entitlement_keys.py

Escribe la privada en ``.entitlement_private.key`` (gitignored) y muestra
la pública para pegar en ``auth_entitlements._PUBLIC_KEY_B64`` y en Render:

  AUTH_ENTITLEMENT_PRIVATE_KEY=...
  AUTH_ENTITLEMENT_PUBLIC_KEY=...   (opcional; si no, usa la embebida)
"""

from __future__ import annotations

import base64
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def main() -> int:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    priv = Ed25519PrivateKey.generate()
    priv_b64 = _b64(priv.private_bytes_raw())
    pub_b64 = _b64(priv.public_key().public_bytes_raw())
    out = ROOT / ".entitlement_private.key"
    out.write_text(priv_b64 + "\n", encoding="utf-8")
    print("Privada guardada en:", out)
    print()
    print("En Render -> Environment:")
    print(f"  AUTH_ENTITLEMENT_PRIVATE_KEY={priv_b64}")
    print()
    print("Actualiza auth_entitlements.py _PUBLIC_KEY_B64 =", repr(pub_b64))
    print("(o AUTH_ENTITLEMENT_PUBLIC_KEY en Render y en el portable)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
