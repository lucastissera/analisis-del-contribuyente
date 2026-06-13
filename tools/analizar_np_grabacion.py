#!/usr/bin/env python3
"""Resume una carpeta build/np_grabacion/* para revisar el flujo manual grabado."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    if len(sys.argv) < 2:
        print("Uso: python tools/analizar_np_grabacion.py build/np_grabacion/YYYYMMDD_HHMMSS")
        return 1
    carpeta = Path(sys.argv[1])
    if not carpeta.is_absolute():
        carpeta = ROOT / carpeta
    clicks_path = carpeta / "clicks.json"
    if not clicks_path.is_file():
        print(f"No existe {clicks_path}")
        return 1
    data = json.loads(clicks_path.read_text(encoding="utf-8"))
    clicks = data.get("clicks") or []
    print(f"Carpeta: {carpeta}")
    print(f"CUIT: {data.get('cuit')}  Ejercicio: {data.get('ejercicio')}")
    print(f"Total clics: {len(clicks)}")
    if not clicks:
        print("\nAVISO: clicks.json vacio. Volvé a grabar con explorar_np_patrimonial.bat")
        print("  y cerrá con Ctrl+C en la consola (no solo cerrando el navegador).")
        return 2
    print("\nSecuencia:")
    for i, c in enumerate(clicks, 1):
        txt = (c.get("text") or "").replace("\n", " ")[:80]
        path = c.get("path") or ""
        href = c.get("href") or ""
        print(f"{i:3}. [{c.get('tag')}] {txt!r}")
        if href:
            print(f"      href: {href}")
        if path:
            print(f"      path: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
