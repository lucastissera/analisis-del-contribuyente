#!/usr/bin/env python3
"""
Programa un rebuild portable con debounce (hooks Cursor afterFileEdit / stop).

Evita builds en paralelo y recompila ~3,5 s después del último cambio relevante.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = ROOT / "tools" / "portable_build.py"
BUILD_DIR = ROOT / "build"
LOG = BUILD_DIR / "hook-rebuild.log"
DEBOUNCE_SEC = 3.5

_IGNORE_ROOT = frozenset(
    {"dist", "build", ".git", "__pycache__", ".venv", "venv", "env", ".cursor", "terminals"}
)
_RELEVANT_SUFFIX = frozenset({".py", ".html", ".spec", ".json", ".bat", ".md"})
_RELEVANT_NAMES = frozenset(
    {"requirements.txt", "MisComprobantesDesktop.spec", "auth_users.json"}
)

_timer: threading.Timer | None = None
_timer_lock = threading.Lock()
_running = False


def _log(msg: str) -> None:
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {msg}\n")


def _es_relevante(path: Path) -> bool:
    try:
        rel = path.resolve().relative_to(ROOT)
    except (OSError, ValueError):
        return False
    if not rel.parts or rel.parts[0] in _IGNORE_ROOT:
        return False
    if rel.name in _RELEVANT_NAMES:
        return True
    if rel.suffix.lower() in _RELEVANT_SUFFIX:
        return True
    if rel.parts[0] == "templates":
        return True
    if rel.parts[0] == "cuit_en_arca":
        return True
    return False


def _run_build() -> None:
    global _running
    _running = True
    _log("Iniciando portable_build.py")
    try:
        r = subprocess.run(
            [sys.executable, str(BUILD_SCRIPT)],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        with open(LOG, "a", encoding="utf-8") as f:
            if r.stdout:
                f.write(r.stdout)
            if r.stderr:
                f.write(r.stderr)
        _log(f"Build terminó con código {r.returncode}")
    except Exception as exc:
        _log(f"Error en build: {exc}")
    finally:
        _running = False


def _fire() -> None:
    global _timer
    with _timer_lock:
        _timer = None
    if not _running:
        threading.Thread(target=_run_build, daemon=True).start()


def schedule(reason: str = "cambio") -> None:
    global _timer
    _log(f"Rebuild programado ({reason}), debounce {DEBOUNCE_SEC}s")
    with _timer_lock:
        if _timer is not None:
            _timer.cancel()
        _timer = threading.Timer(DEBOUNCE_SEC, _fire)
        _timer.daemon = True
        _timer.start()


def schedule_now(reason: str = "stop") -> None:
    """Build inmediato (hook stop); espera si hay uno en curso."""
    _log(f"Rebuild inmediato solicitado ({reason})")
    if _running:
        _log("Build ya en curso; se omite duplicado")
        return
    threading.Thread(target=_run_build, daemon=True).start()


def main() -> int:
    paths: list[str] = []
    if not sys.stdin.isatty():
        try:
            raw = sys.stdin.read()
            if raw.strip():
                data = json.loads(raw)
                for key in ("file_path", "path", "filePath"):
                    if data.get(key):
                        paths.append(str(data[key]))
                edits = data.get("edits") or data.get("files")
                if isinstance(edits, list):
                    for item in edits:
                        if isinstance(item, str):
                            paths.append(item)
                        elif isinstance(item, dict):
                            for key in ("file_path", "path", "filePath"):
                                if item.get(key):
                                    paths.append(str(item[key]))
        except (json.JSONDecodeError, TypeError):
            pass

    if paths:
        relevant = any(_es_relevante(Path(p)) for p in paths)
        if not relevant:
            return 0

    if "--now" in sys.argv:
        schedule_now()
    else:
        schedule(paths[0] if paths else "hook")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
