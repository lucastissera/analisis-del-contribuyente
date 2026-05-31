"""
Punto de entrada para la aplicación de escritorio (.exe).

El servidor Flask escucha en 127.0.0.1: el procesamiento de Excel/CSV es **100 % local**
y **no requiere Internet**.

En el .exe, por defecto se intenta abrir la interfaz en una **ventana tipo aplicación**
(Edge o Chrome con ``--app=URL``), sin barra de pestañas. Si no hay Edge/Chrome en las
rutas habituales, se usa el navegador predeterminado del sistema.

Autenticación: copiá ``auth_users.json`` junto al .exe (misma carpeta) o usá el ejemplo
incluido (ver README).
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import traceback
import webbrowser
from pathlib import Path


def _puerto_deseado() -> int:
    return int(os.environ.get("PORT", "8765"))


def _directorio_log() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _escribir_log(mensaje: str) -> None:
    try:
        log = _directorio_log() / "MisComprobantes_error.log"
        with open(log, "a", encoding="utf-8") as f:
            f.write(mensaje.rstrip() + "\n")
    except OSError:
        pass


def _avisar_usuario(titulo: str, texto: str) -> None:
    _escribir_log(f"{titulo}: {texto}")
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(0, texto, titulo, 0x10)
            return
        except Exception:
            pass
    print(f"{titulo}\n{texto}", flush=True)


def _puerto_disponible(port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        try:
            s.close()
        except OSError:
            pass


def _abrir_interfaz(url: str) -> None:
    """Abre la UI: en portable, Edge/Chrome en modo app si se puede; si no, navegador."""
    if os.environ.get("OPEN_BROWSER", "1").strip().lower() not in (
        "1",
        "true",
        "yes",
        "on",
    ):
        return

    frozen = bool(getattr(sys, "frozen", False))
    use_app = (os.environ.get("DESKTOP_APP_WINDOW") or ("1" if frozen else "0")).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    if not use_app:
        try:
            webbrowser.open(url)
        except Exception:
            pass
        return

    edge_paths = (
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    )
    for edge in edge_paths:
        if os.path.isfile(edge):
            try:
                subprocess.Popen(
                    [edge, f"--app={url}", "--no-first-run"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                return
            except OSError:
                pass

    for chrome in (
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
    ):
        if os.path.isfile(chrome):
            try:
                subprocess.Popen(
                    [chrome, f"--app={url}", "--no-first-run"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                return
            except OSError:
                pass

    try:
        webbrowser.open(url)
    except Exception:
        pass


def main() -> None:
    os.environ.setdefault("ENABLE_LOCAL_PLANTILLAS_IMPUTACION", "1")
    if getattr(sys, "frozen", False):
        from cuit_en_arca.playwright_env import aplicar_entorno_playwright_portable

        aplicar_entorno_playwright_portable()

    port = _puerto_deseado()
    url = f"http://127.0.0.1:{port}/"

    if not _puerto_disponible(port):
        _avisar_usuario(
            "Mis Comprobantes",
            f"La aplicación ya está en ejecución o el puerto {port} está ocupado.\n\n"
            f"Abrí: {url}\n\n"
            "Si no responde, cerrá procesos «MisComprobantesAnalisis» en el "
            "Administrador de tareas e intentá de nuevo.",
        )
        return

    try:
        from app import app
    except Exception as exc:
        _avisar_usuario(
            "Mis Comprobantes — error al iniciar",
            f"No se pudo cargar la aplicación:\n{exc}\n\n"
            f"Detalle en: {_directorio_log() / 'MisComprobantes_error.log'}",
        )
        _escribir_log(traceback.format_exc())
        return

    threading.Timer(2.0, lambda: _abrir_interfaz(url)).start()

    if not getattr(sys, "frozen", False):
        print(
            f"\n  Mis Comprobantes — análisis local\n"
            f"  Interfaz: {url}\n"
            f"  Los archivos se procesan en esta PC (sin conexión a Internet).\n"
            f"  Cerrá esta ventana de consola para detener el programa.\n",
            flush=True,
        )

    try:
        app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)
    except Exception:
        _escribir_log(traceback.format_exc())
        _avisar_usuario(
            "Mis Comprobantes — error",
            f"El servidor se detuvo. Ver {_directorio_log() / 'MisComprobantes_error.log'}",
        )
        raise


if __name__ == "__main__":
    main()
