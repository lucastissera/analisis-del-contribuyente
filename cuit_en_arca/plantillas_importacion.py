"""Rutas a modelos Excel de importación (desarrollo y PyInstaller)."""

from __future__ import annotations

import sys
from pathlib import Path


def ruta_plantilla_excel(carpeta: str, nombre: str) -> Path:
    """Ubica un .xlsx empaquetado o en la raíz del proyecto."""
    candidatos: list[Path] = []
    if getattr(sys, "frozen", False):
        bundle = Path(getattr(sys, "_MEIPASS", ""))
        candidatos.extend(
            [
                bundle / carpeta / nombre,
                bundle / nombre,
            ]
        )
    raiz = (
        Path(sys.executable).resolve().parent
        if getattr(sys, "frozen", False)
        else Path(__file__).resolve().parent.parent
    )
    dev_raiz = Path(__file__).resolve().parent.parent
    candidatos.extend(
        [
            raiz / carpeta / nombre,
            raiz / nombre,
            dev_raiz / carpeta / nombre,
            dev_raiz / nombre,
        ]
    )
    for p in candidatos:
        if p.is_file():
            return p
    return candidatos[0]


def ruta_plantilla_arca_excel() -> Path:
    return ruta_plantilla_excel(
        "Formato Analisis Comprobantes",
        "Formato Analisis Comprobantes.xlsx",
    )


def ruta_plantilla_np_excel() -> Path:
    return ruta_plantilla_excel(
        "Formato Nuestra Parte",
        "Formato Nuestra Parte.xlsx",
    )
