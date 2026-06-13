#!/usr/bin/env python3
"""Verifica rutas admin Cursor Cloud y configuración de enlace (sin pedir cambios reales)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    load_dotenv(ROOT / "cursor.env")
except ImportError:
    pass


def _mostrar_diagnostico(verif: dict) -> None:
    diag = verif.get("diagnostico") or {}
    print("Diagnóstico del proceso Python:")
    print(f"  - CURSOR_* en os.environ: {', '.join(diag.get('vars_cursor') or []) or '(ninguna)'}")
    print(f"  - API key: {diag.get('api_key_len', 0)} caracteres")
    if diag.get("api_key_fuente"):
        print(f"  - Fuente API key: {diag['api_key_fuente']}")
    raw = verif.get("repo_url_raw")
    if raw:
        print(f"  - Repo raw ({len(raw)} chars): {raw[:120]}")
    if verif.get("repo_url"):
        print(f"  - Repo normalizado: {verif['repo_url']}")
    elif raw:
        print("  - Repo raw NO pudo normalizarse (revisá formato https://github.com/...)")
    if not diag.get("vars_cursor"):
        print(
            "\n  Nota: este script lee el entorno de TU PC (o .env local)."
            "\n  Si las vars están solo en Render, acá fallará aunque producción esté bien."
            "\n  En la web admin usá «Probar conexión» para validar el servidor Render."
        )
    print()


def ok(msg: str) -> None:
    print(f"  OK  {msg}")


def fail(msg: str) -> None:
    print(f"  FAIL {msg}")


def main() -> int:
    print("Verificación Cursor Cloud (admin)\n")
    errores = 0

    from cursor_cloud import verificar_enlace

    verif = verificar_enlace(probar_api=os.environ.get("CURSOR_PROBAR_API") == "1")
    _mostrar_diagnostico(verif)
    print("Configuración:")
    for c in verif.get("checks") or []:
        if c.get("ok"):
            ok(c.get("mensaje") or c.get("id", ""))
        else:
            fail(c.get("mensaje") or c.get("id", ""))
            if c.get("critico", True):
                errores += 1

    if verif.get("ready"):
        ok("Enlace listo para enviar pedidos con git push")
    else:
        fail("Enlace incompleto — revisá variables en Render/.env")
        errores += 1

    print("\nRutas Flask:")
    import app as app_mod

    rules = {r.rule: r.endpoint for r in app_mod.app.url_map.iter_rules()}
    rutas = (
        "/admin/cursor",
        "/admin/cursor/estado",
        "/admin/cursor/mensaje",
        "/admin/cursor/stream/<agent_id>/<run_id>",
        "/admin/cursor/run/<agent_id>/<run_id>",
        "/admin/cursor/cancelar/<agent_id>/<run_id>",
    )
    for ruta in rutas:
        if any(rule == ruta or rule.startswith(ruta.split("<")[0]) for rule in rules):
            ok(ruta)
        else:
            fail(f"Falta ruta {ruta}")
            errores += 1

    print("\nPlantillas / estáticos:")
    for rel in (
        "templates/admin_cursor.html",
        "static/admin_cursor.js",
        "docs/CURSOR_CLOUD_ADMIN.md",
    ):
        p = ROOT / rel
        if p.is_file():
            ok(rel)
        else:
            fail(f"Falta {rel}")
            errores += 1

    print("\nPrompt git/push:")
    from cursor_cloud import envolver_prompt_usuario

    prompt = envolver_prompt_usuario("Prueba")
    if "commit" in prompt.lower() and "push" in prompt.lower():
        ok("Instrucciones de commit/push incluidas en cada pedido")
    else:
        fail("Prompt sin instrucciones git")
        errores += 1

    print()
    if errores:
        print(f"Resultado: {errores} problema(s).")
        print("Tip: CURSOR_PROBAR_API=1 python tools/verificar_cursor_cloud.py")
        return 1
    print("Resultado: todo OK (sin ejecutar agente real).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
