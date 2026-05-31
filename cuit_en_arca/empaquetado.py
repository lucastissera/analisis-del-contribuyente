"""Empaqueta descargas en .rar (WinRAR/7-Zip) o .zip como respaldo."""

from __future__ import annotations

import io
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

NOMBRE_ERRORES = "ingresos_fallidos.txt"


def _buscar_rar_exe() -> Path | None:
    candidatos = (
        r"C:\Program Files\WinRAR\Rar.exe",
        r"C:\Program Files (x86)\WinRAR\Rar.exe",
    )
    for c in candidatos:
        p = Path(c)
        if p.is_file():
            return p
    return None


def _buscar_7z_exe() -> Path | None:
    candidatos = (
        r"C:\Program Files\7-Zip\7z.exe",
        r"C:\Program Files (x86)\7-Zip\7z.exe",
    )
    for c in candidatos:
        p = Path(c)
        if p.is_file():
            return p
    return None


def empaquetar_descargas(
    archivos: dict[str, bytes],
    errores_txt: str,
) -> tuple[bytes, str, str]:
    """Devuelve (contenido, nombre_archivo, mimetype)."""
    tmp = Path(tempfile.mkdtemp(prefix="arca_lote_"))
    paquete = tmp / "contenido"
    paquete.mkdir()
    try:
        for nombre, data in archivos.items():
            (paquete / nombre).write_bytes(data)
        (paquete / NOMBRE_ERRORES).write_text(errores_txt, encoding="utf-8")

        rar = _buscar_rar_exe()
        if rar:
            out = tmp / "mis_comprobantes_arca.rar"
            files = [str(f) for f in paquete.iterdir() if f.is_file()]
            subprocess.run(
                [str(rar), "a", "-ep1", "-y", str(out), *files],
                check=True,
                capture_output=True,
            )
            return out.read_bytes(), "mis_comprobantes_arca.rar", "application/x-rar-compressed"

        seven = _buscar_7z_exe()
        if seven:
            out = tmp / "mis_comprobantes_arca.7z"
            subprocess.run(
                [str(seven), "a", "-y", str(out), str(paquete / "*")],
                check=True,
                capture_output=True,
            )
            return out.read_bytes(), "mis_comprobantes_arca.7z", "application/x-7z-compressed"

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in paquete.iterdir():
                if f.is_file():
                    zf.write(f, f.name)
        return buf.getvalue(), "mis_comprobantes_arca.zip", "application/zip"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
