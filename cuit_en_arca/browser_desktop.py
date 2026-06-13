"""Navegador embebido del .exe (Edge/Chrome en modo app).

- Perfil aislado sin promoción de cuenta Microsoft / sync.
- Cierre forzado al salir (window.close no funciona en modo --app).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def directorio_app() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def ruta_perfil_navegador() -> Path:
    return directorio_app() / "navegador-perfil"


def preparar_perfil_sin_cuenta(perfil: Path) -> None:
    """Evita popups de «iniciar sesión / sincronizar» en Edge/Chrome."""
    perfil.mkdir(parents=True, exist_ok=True)
    default = perfil / "Default"
    default.mkdir(parents=True, exist_ok=True)

    prefs: dict = {}
    prefs_path = default / "Preferences"
    if prefs_path.is_file():
        try:
            prefs = json.loads(prefs_path.read_text(encoding="utf-8"))
        except Exception:
            prefs = {}

    prefs.setdefault("sync", {})
    prefs["sync"]["suppress_start"] = True
    prefs["sync"]["enabled"] = False
    prefs.setdefault("browser", {})
    prefs["browser"]["show_signin_promo"] = False
    prefs["browser"]["signin_promo_auto_accepted"] = True
    prefs.setdefault("signin", {})
    prefs["signin"]["allowed"] = False
    prefs.setdefault("profile", {})
    prefs["profile"]["default_signin_allowed"] = False
    prefs_path.write_text(json.dumps(prefs, ensure_ascii=False), encoding="utf-8")

    local_state: dict = {}
    ls_path = perfil / "Local State"
    if ls_path.is_file():
        try:
            local_state = json.loads(ls_path.read_text(encoding="utf-8"))
        except Exception:
            local_state = {}
    local_state.setdefault("sync", {})
    local_state["sync"]["requested"] = False
    local_state.setdefault("browser", {})
    local_state["browser"]["enabled_labs_experiments"] = []
    ls_path.write_text(json.dumps(local_state, ensure_ascii=False), encoding="utf-8")

    first_run = perfil / "First Run"
    if not first_run.is_file():
        first_run.write_text("", encoding="utf-8")


def flags_navegador_app() -> list[str]:
    """Argumentos extra para suprimir sync, primera ejecución y promos."""
    return [
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-sync",
        "--disable-background-networking",
        "--disable-features="
        "Translate,MediaRouter,OptimizationHints,"
        "SignInPromo,EdgeSignIn,EdgeSignInProfileCreation,"
        "SigninIntercept,Sync,msEdgeSync,msEdgeSSOFirstRun",
    ]


def registrar_lanzamiento_navegador(pid: int, perfil: Path) -> None:
    os.environ["MC_BROWSER_PID"] = str(pid)
    os.environ["MC_BROWSER_PROFILE"] = str(perfil.resolve())
    try:
        (perfil / "browser.pid").write_text(str(pid), encoding="utf-8")
    except OSError:
        pass


def limpiar_cookies_localhost(perfil: Path | str | None = None) -> None:
    """Elimina cookies de localhost del perfil (sesión Flask persistente en .exe)."""
    if sys.platform != "win32":
        return
    import sqlite3

    base = Path(perfil) if perfil else ruta_perfil_navegador()
    if not base.is_dir():
        return
    for rel in ("Default/Network/Cookies", "Default/Cookies"):
        db = base / rel
        if not db.is_file():
            continue
        try:
            con = sqlite3.connect(str(db))
            con.execute(
                "DELETE FROM cookies WHERE host_key LIKE '%127.0.0.1%' "
                "OR host_key LIKE '%localhost%'"
            )
            con.commit()
            con.close()
        except Exception:
            pass


def cerrar_navegador_desktop() -> None:
    """Termina Edge/Chrome lanzados con el perfil dedicado de la app."""
    if sys.platform != "win32":
        return

    perfil = os.environ.get("MC_BROWSER_PROFILE") or str(ruta_perfil_navegador().resolve())
    perfil_norm = str(Path(perfil).resolve())

    pid = os.environ.get("MC_BROWSER_PID")
    if not pid:
        pid_file = Path(perfil_norm) / "browser.pid"
        if pid_file.is_file():
            try:
                pid = pid_file.read_text(encoding="utf-8").strip()
            except OSError:
                pid = None

    if pid and pid.isdigit():
        try:
            subprocess.run(
                ["taskkill", "/PID", pid, "/T", "/F"],
                capture_output=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception:
            pass

    # Edge suele crear procesos hijo: matar por línea de comandos del perfil.
    try:
        esc = perfil_norm.replace("'", "''")
        ps = (
            f"Get-CimInstance Win32_Process | Where-Object {{ "
            f"($_.Name -eq 'msedge.exe' -or $_.Name -eq 'chrome.exe') "
            f"-and $_.CommandLine -like '*{esc}*' }} | "
            f"ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }}"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            timeout=15,
        )
    except Exception:
        pass
