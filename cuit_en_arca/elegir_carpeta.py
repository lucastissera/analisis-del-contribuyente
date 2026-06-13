"""Selector de carpeta nativo del sistema (diálogo de Windows).

El diálogo se abre en un **subproceso** (Tkinter) para no bloquear el hilo principal
con restricciones de Tcl/Tk. En la app empaquetada (.exe) el subproceso es el propio
ejecutable con ``MC_PICK_FOLDER=1`` y la ruta elegida se devuelve por archivo temporal.

Importante: no usar ``CREATE_NO_WINDOW`` al lanzar el subproceso del picker; en Windows
impide que aparezca el diálogo gráfico.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

_TK_SCRIPT = (
    "import os, tkinter as tk\n"
    "from tkinter import filedialog\n"
    "r = tk.Tk(); r.withdraw()\n"
    "try:\n"
    "    r.attributes('-topmost', True)\n"
    "except Exception:\n"
    "    pass\n"
    "p = filedialog.askdirectory(title=os.environ.get('MC_PICK_TITLE', 'Elegir carpeta'))\n"
    "try:\n"
    "    r.destroy()\n"
    "except Exception:\n"
    "    pass\n"
    "out = os.environ.get('MC_PICK_OUT')\n"
    "if out:\n"
    "    open(out, 'w', encoding='utf-8').write(p or '')\n"
)


def ejecutar_picker_desde_env() -> None:
    """Abre el diálogo leyendo MC_PICK_TITLE y escribe la ruta en MC_PICK_OUT."""
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        try:
            root.attributes("-topmost", True)
        except Exception:
            pass
        ruta = filedialog.askdirectory(
            title=os.environ.get("MC_PICK_TITLE", "Elegir carpeta")
        )
        try:
            root.destroy()
        except Exception:
            pass
    except Exception:
        ruta = ""

    out = os.environ.get("MC_PICK_OUT")
    if out:
        try:
            Path(out).write_text(ruta or "", encoding="utf-8")
        except Exception:
            pass


def _startupinfo_sin_consola():
    """Oculta consola del subproceso Python en Windows sin bloquear ventanas GUI."""
    if sys.platform != "win32":
        return None
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 0
    return si


def _elegir_carpeta_subproceso(titulo: str, out_path: Path, *, timeout: int) -> None:
    env = dict(os.environ)
    env["MC_PICK_FOLDER"] = "1"
    env["MC_PICK_TITLE"] = titulo
    env["MC_PICK_OUT"] = str(out_path)

    if getattr(sys, "frozen", False):
        cmd = [sys.executable]
    else:
        cmd = [sys.executable, "-c", _TK_SCRIPT]

    si = _startupinfo_sin_consola()
    kwargs: dict = {
        "args": cmd,
        "env": env,
        "timeout": timeout,
        "capture_output": True,
    }
    if si is not None:
        kwargs["startupinfo"] = si
    subprocess.run(**kwargs)


def elegir_carpeta_dialogo(titulo: str = "Elegir carpeta", *, timeout: int = 300) -> str | None:
    """Muestra el diálogo nativo y devuelve la ruta elegida (o None si se cancela)."""
    fd, tmp = tempfile.mkstemp(suffix=".pick")
    os.close(fd)
    out_path = Path(tmp)
    try:
        _elegir_carpeta_subproceso(titulo, out_path, timeout=timeout)
        ruta = out_path.read_text(encoding="utf-8").strip()
        return ruta or None
    except Exception:
        return None
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
