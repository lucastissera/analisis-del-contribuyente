"""Un solo Chromium reutilizable entre CUITs y sistemas (menor RAM en Render)."""

from __future__ import annotations

import os
from types import TracebackType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.sync_api import Browser, BrowserContext, Page, Playwright


def reutilizar_navegador_por_defecto(*, modo_ap: bool = False, filas: int = 1) -> bool:
    """True si conviene compartir navegador (AP, lotes multi-CUIT o env explícita)."""
    raw = (os.environ.get("CUIT_EN_ARCA_REUTILIZAR_NAVEGADOR") or "").strip().lower()
    if raw in ("0", "false", "no"):
        return False
    if raw in ("1", "true", "si", "sí", "yes"):
        return True
    return modo_ap or filas > 1


class SesionPlaywrightCompartida:
    """Mantiene una instancia de Playwright + Chromium para varias descargas seguidas."""

    def __init__(self, *, headless: bool = True) -> None:
        self._headless = headless
        self._pw_cm = None
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None

    @property
    def activa(self) -> bool:
        return self._browser is not None

    def __enter__(self) -> SesionPlaywrightCompartida:
        from playwright.sync_api import sync_playwright

        from cuit_en_arca.automation_playwright import _nuevo_contexto_stealth

        self._pw_cm = sync_playwright()
        self._playwright = self._pw_cm.__enter__()
        self._browser, self._context = _nuevo_contexto_stealth(
            self._playwright, headless=self._headless
        )
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.cerrar()

    def nueva_pagina(self, *, timeout_ms: int = 60_000) -> Page:
        if self._context is None:
            raise RuntimeError("Sesión Playwright no iniciada.")
        page = self._context.new_page()
        page.set_default_timeout(timeout_ms)
        return page

    def cerrar_paginas(self) -> None:
        if self._context is None:
            return
        for page in list(self._context.pages):
            try:
                page.close()
            except Exception:
                pass

    def cerrar(self) -> None:
        self.cerrar_paginas()
        if self._browser is not None:
            try:
                self._browser.close()
            except Exception:
                pass
            self._browser = None
            self._context = None
        if self._pw_cm is not None:
            try:
                self._pw_cm.__exit__(None, None, None)
            except Exception:
                pass
            self._pw_cm = None
            self._playwright = None
