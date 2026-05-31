"""Variables de entorno Playwright/Chromium para el .exe portable."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def directorio_browsers_portable() -> Path | None:
    if not getattr(sys, "frozen", False):
        return None
    return Path(sys.executable).resolve().parent / "ms-playwright"


def aplicar_entorno_playwright_portable() -> None:
    """Chromium junto al .exe (ms-playwright/) y descarga ARCA habilitada."""
    if not getattr(sys, "frozen", False):
        return
    browsers = directorio_browsers_portable()
    if browsers is not None:
        browsers.mkdir(parents=True, exist_ok=True)
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(browsers)
    os.environ.setdefault("CUIT_EN_ARCA_UI", "1")
    os.environ.setdefault("CUIT_EN_ARCA_PLAYWRIGHT", "1")


def chromium_instalado_en_portable() -> bool:
    base = directorio_browsers_portable()
    if base is None or not base.is_dir():
        return False
    return any(base.glob("chromium-*")) or any(base.glob("chromium_headless_shell-*"))
