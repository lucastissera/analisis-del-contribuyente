"""Descarga y parseo del listado de facturas apócrifas (APOC) de AFIP."""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path
from typing import Callable
from urllib.request import Request, urlopen

APOC_URL_DEFAULT = (
    "https://servicioscf.afip.gob.ar/facturacion/facturasapocrifas/default.aspx"
)
APOC_URL_DOWNLOAD = (
    "https://servicioscf.afip.gob.ar/facturacion/facturasapocrifas/DownloadFile.aspx"
)
NOMBRE_TXT_APOC = "FacturasApocrifas.txt"
_USER_AGENT = (
    "Mozilla/5.0 (compatible; AnalisisIntegralContribuyente/1.0; +https://afip.gob.ar)"
)

_cache: tuple[set[str], bytes, str] | None = None

OnLog = Callable[[str], None] | None


def limpiar_cache_listado_apoc() -> None:
    """Fuerza una nueva descarga en la próxima consulta."""
    global _cache
    _cache = None


def descargar_archivo_apoc(*, timeout: int = 120) -> bytes:
    """Descarga el archivo publicado en DownloadFile.aspx (ZIP con el TXT)."""
    req = Request(APOC_URL_DOWNLOAD, headers={"User-Agent": _USER_AGENT})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read()


def extraer_txt_desde_archivo_apoc(archivo: bytes) -> tuple[bytes, str]:
    """
    Extrae el TXT del ZIP (o devuelve el contenido si ya es texto plano).
    Devuelve ``(contenido_txt, nombre_archivo)``.
    """
    if archivo[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(archivo)) as zf:
            candidatos = [
                n
                for n in zf.namelist()
                if n.lower().endswith(".txt") and not n.endswith("/")
            ]
            if not candidatos:
                raise ValueError("El archivo APOC no contiene un .txt")
            nombre = candidatos[0]
            return zf.read(nombre), Path(nombre).name
    if archivo[:4] == b"Rar!":
        raise ValueError(
            "El listado APOC llegó en formato RAR; se esperaba ZIP. "
            "Instale 7-Zip o WinRAR en el equipo."
        )
    return archivo, NOMBRE_TXT_APOC


def _normalizar_cuit(val: str) -> str:
    return re.sub(r"\D", "", val or "")


def parsear_cuits_desde_listado_apoc(contenido: str | bytes) -> set[str]:
    """
    Lee CUITs del TXT de AFIP. Las tres primeras líneas son comentarios (#);
    desde la cuarta fila: CUIT, Fecha Condicion Apocrifo, Fecha Publicacion, Descripcion.
    """
    if isinstance(contenido, bytes):
        texto = contenido.decode("latin-1", errors="replace")
    else:
        texto = contenido
    cuits: set[str] = set()
    for linea in texto.splitlines():
        s = linea.strip()
        if not s or s.startswith("#"):
            continue
        cuit = _normalizar_cuit(s.split(",", 1)[0])
        if cuit:
            cuits.add(cuit)
    return cuits


def obtener_listado_apoc(
    *,
    on_log: OnLog = None,
    force_refresh: bool = False,
) -> tuple[set[str], bytes, str]:
    """
    Descarga (o reutiliza caché), extrae el TXT y devuelve
    ``(conjunto_cuits, bytes_txt, nombre_txt)``.
    """
    global _cache
    if _cache is not None and not force_refresh:
        return _cache

    if on_log:
        on_log("Descargando listado APOC de AFIP…")
    archivo = descargar_archivo_apoc()
    txt_bytes, nombre_txt = extraer_txt_desde_archivo_apoc(archivo)
    cuits = parsear_cuits_desde_listado_apoc(txt_bytes)
    if on_log:
        on_log(f"Listado APOC: {len(cuits)} CUIT(s) en «{nombre_txt}».")
    _cache = (cuits, txt_bytes, nombre_txt)
    return _cache
