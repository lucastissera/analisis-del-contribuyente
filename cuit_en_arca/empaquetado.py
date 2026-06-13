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


SUBCARPETA_PROCESADOS = "Procesados"


def empaquetar_descargas(
    archivos: dict[str, bytes],
    errores_txt: str,
    procesados: dict[str, bytes] | None = None,
    extra: dict[str, bytes] | None = None,
) -> tuple[bytes, str, str]:
    """Devuelve (contenido, nombre_archivo, mimetype).

    ``archivos`` van en la raíz del comprimido (tal como salen de ARCA),
    ``procesados`` (si se pasan) en la subcarpeta ``Procesados/`` y ``extra``
    (p. ej. el resumen por CUIT) también en la raíz.
    """
    tmp = Path(tempfile.mkdtemp(prefix="arca_lote_"))
    paquete = tmp / "contenido"
    paquete.mkdir()
    try:
        for nombre, data in archivos.items():
            (paquete / nombre).write_bytes(data)
        (paquete / NOMBRE_ERRORES).write_text(errores_txt, encoding="utf-8")

        if extra:
            for nombre, data in extra.items():
                (paquete / nombre).write_bytes(data)

        if procesados:
            dir_proc = paquete / SUBCARPETA_PROCESADOS
            dir_proc.mkdir(exist_ok=True)
            for nombre, data in procesados.items():
                (dir_proc / nombre).write_bytes(data)

        rar = _buscar_rar_exe()
        if rar:
            out = tmp / "mis_comprobantes_arca.rar"
            # -r recursivo (incluye subcarpetas); cwd en el paquete para guardar
            # rutas relativas (archivo.xlsx y Procesados\archivo.xlsx).
            subprocess.run(
                [str(rar), "a", "-r", "-y", str(out), "*"],
                check=True,
                capture_output=True,
                cwd=str(paquete),
            )
            return out.read_bytes(), "mis_comprobantes_arca.rar", "application/x-rar-compressed"

        seven = _buscar_7z_exe()
        if seven:
            out = tmp / "mis_comprobantes_arca.7z"
            subprocess.run(
                [str(seven), "a", "-r", "-y", str(out), "*"],
                check=True,
                capture_output=True,
                cwd=str(paquete),
            )
            return out.read_bytes(), "mis_comprobantes_arca.7z", "application/x-7z-compressed"

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in sorted(paquete.rglob("*")):
                if f.is_file():
                    zf.write(f, str(f.relative_to(paquete)))
        return buf.getvalue(), "mis_comprobantes_arca.zip", "application/zip"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
