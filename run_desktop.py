"""
Punto de entrada para la aplicación de escritorio (.exe).

El servidor Flask escucha en 127.0.0.1: el procesamiento de Excel/CSV es **100 % local**
y **no requiere Internet**.

En el .exe, por defecto se intenta abrir la interfaz en una **ventana tipo aplicación**
(Edge o Chrome con ``--app=URL``), sin barra de pestañas. Si no hay Edge/Chrome en las
rutas habituales, se usa el navegador predeterminado del sistema.

Autenticación: listado remoto en la nube (``auth_remote.txt`` o ``.env`` junto al .exe)
o ``auth_users.json`` local (ver README y docs/AUTH_USUARIOS_NUBE.md).
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

from app_branding import APP_EXE_BASENAME, APP_LOG_FILENAME, APP_NAME
from cuit_en_arca.browser_desktop import (
    flags_navegador_app,
    preparar_perfil_sin_cuenta,
    registrar_lanzamiento_navegador,
    ruta_perfil_navegador,
)


def _puerto_deseado() -> int:
    return int(os.environ.get("PORT", "8765"))


def _directorio_log() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _escribir_log(mensaje: str) -> None:
    try:
        log = _directorio_log() / APP_LOG_FILENAME
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


def _area_trabajo() -> tuple[int, int, int, int] | None:
    """Área de trabajo del escritorio en Windows (pantalla menos la barra de
    tareas), como (left, top, width, height). Sirve para abrir la ventana
    **maximizada** (con barra de tareas visible), no en pantalla completa.
    """
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass
        rect = wintypes.RECT()
        # SPI_GETWORKAREA = 0x0030
        if user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):
            ancho = int(rect.right - rect.left)
            alto = int(rect.bottom - rect.top)
            if ancho > 0 and alto > 0:
                return int(rect.left), int(rect.top), ancho, alto
    except Exception:
        pass
    return None


def _args_ventana_app(url: str) -> list[str]:
    """Flags para abrir el navegador en modo app **maximizado**.

    En modo ``--app`` Edge/Chrome suelen ignorar ``--start-maximized``, por eso
    además fijamos posición y tamaño al área de trabajo (sin tapar la barra de
    tareas). No se usa pantalla completa.
    """
    args = [
        f"--app={url}",
        "--start-maximized",
        *flags_navegador_app(),
    ]
    area = _area_trabajo()
    if area:
        left, top, ancho, alto = area
        args += [
            f"--window-position={left},{top}",
            f"--window-size={ancho},{alto}",
        ]
    return args


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

    args_ventana = _args_ventana_app(url)

    # Perfil dedicado: sin cuenta Microsoft ni sync (evita popup al iniciar).
    perfil = ruta_perfil_navegador()
    preparar_perfil_sin_cuenta(perfil)
    args_ventana = [*args_ventana, f"--user-data-dir={perfil}"]

    prefer = (os.environ.get("DESKTOP_BROWSER") or "chrome").strip().lower()

    def _lanzar(exe: str) -> bool:
        try:
            proc = subprocess.Popen(
                [exe, *args_ventana],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            registrar_lanzamiento_navegador(proc.pid, perfil)
            return True
        except OSError:
            return False

    chrome_paths = (
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
    )
    edge_paths = (
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    )

    orden = (
        ("chrome", chrome_paths, edge_paths)
        if prefer != "edge"
        else ("edge", edge_paths, chrome_paths)
    )
    _, primarios, respaldo = orden
    for exe in primarios:
        if os.path.isfile(exe) and _lanzar(exe):
            return
    for exe in respaldo:
        if os.path.isfile(exe) and _lanzar(exe):
            return

    try:
        webbrowser.open(url)
    except Exception:
        pass


def main() -> None:
    # Modo selector de carpeta: el propio .exe se relanza con MC_PICK_FOLDER=1
    # para mostrar el diálogo nativo (Tkinter) y devolver la ruta por archivo.
    if os.environ.get("MC_PICK_FOLDER"):
        try:
            from cuit_en_arca.elegir_carpeta import ejecutar_picker_desde_env

            ejecutar_picker_desde_env()
        except Exception:
            pass
        return

    os.environ.setdefault("ENABLE_LOCAL_PLANTILLAS_IMPUTACION", "1")
    try:
        from dotenv import load_dotenv

        if getattr(sys, "frozen", False):
            load_dotenv(Path(sys.executable).resolve().parent / ".env")
        else:
            load_dotenv(Path(__file__).resolve().parent / ".env")
    except ImportError:
        pass
    if getattr(sys, "frozen", False):
        from cuit_en_arca.playwright_env import aplicar_entorno_playwright_portable

        aplicar_entorno_playwright_portable()
        os.environ.setdefault(
            "MC_BROWSER_PROFILE", str(ruta_perfil_navegador().resolve())
        )

    port = _puerto_deseado()
    url = f"http://127.0.0.1:{port}/"

    if not _puerto_disponible(port):
        _avisar_usuario(
            APP_NAME,
            f"La aplicación ya está en ejecución o el puerto {port} está ocupado.\n\n"
            f"Abrí: {url}\n\n"
            f"Si no responde, cerrá procesos «{APP_EXE_BASENAME}» en el "
            "Administrador de tareas e intentá de nuevo.",
        )
        return

    try:
        from app import app
    except Exception as exc:
        _avisar_usuario(
            f"{APP_NAME} — error al iniciar",
            f"No se pudo cargar la aplicación:\n{exc}\n\n"
            f"Detalle en: {_directorio_log() / APP_LOG_FILENAME}",
        )
        _escribir_log(traceback.format_exc())
        return

    threading.Timer(2.0, lambda: _abrir_interfaz(url)).start()

    try:
        from cuit_en_arca.analisis_programado import iniciar_scheduler

        iniciar_scheduler()
    except Exception:
        pass

    if not getattr(sys, "frozen", False):
        print(
            f"\n  {APP_NAME} — análisis local\n"
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
            f"{APP_NAME} — error",
            f"El servidor se detuvo. Ver {_directorio_log() / APP_LOG_FILENAME}",
        )
        raise


if __name__ == "__main__":
    main()
