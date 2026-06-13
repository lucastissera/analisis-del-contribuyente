"""Utilidades compartidas para registrar CUIT/claves fallidos en descargas ARCA."""

from __future__ import annotations

from pathlib import Path

NOMBRE_ERRORES = "ingresos_fallidos.txt"


def escribir_fallos_txt(
    destino: str | Path,
    *,
    fallos_login: list[str] | None = None,
    otros: list[str] | None = None,
    resumen_cuits: list[dict] | None = None,
) -> Path | None:
    """Escribe ``ingresos_fallidos.txt`` en ``destino`` si hay algo que reportar."""
    lineas: list[str] = []
    if fallos_login:
        lineas.append("=== Ingresos a ARCA no exitosos (CUIT / clave) ===")
        lineas.extend(fallos_login)
        lineas.append("")
    if resumen_cuits:
        errs = [r for r in resumen_cuits if r.get("error")]
        if errs:
            lineas.append("=== CUIT no procesados correctamente ===")
            for r in errs:
                cuit = r.get("cuit", "?")
                rs = r.get("razon_social") or ""
                err = r.get("error") or "Error desconocido"
                extra = f" ({rs})" if rs else ""
                lineas.append(f"CUIT {cuit}{extra}: {err}")
            lineas.append("")
    if otros:
        lineas.append("=== Otros avisos ===")
        lineas.extend(otros)
        lineas.append("")
    if not lineas:
        return None
    ruta = Path(destino) / NOMBRE_ERRORES
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text("\n".join(lineas), encoding="utf-8")
    return ruta
