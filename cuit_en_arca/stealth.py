"""Pausas y escritura con ritmo humano (tiempos ~30% más cortos que la versión inicial)."""

from __future__ import annotations

import random
import time

# Segundos estimados por CUIT (emitidos + recibidos) para la barra de progreso.
SEC_ESTIMADOS_POR_CUIT = 126


def pausa_humana(min_sec: float = 0.28, max_sec: float = 0.84) -> None:
    time.sleep(random.uniform(min_sec, max_sec))


def pausa_entre_filas_lote() -> None:
    time.sleep(random.uniform(5.6, 12.6))


def escribir_como_humano(locator, texto: str) -> None:
    locator.click()
    pausa_humana(0.1, 0.32)
    try:
        locator.fill("")
    except Exception:
        pass
    locator.type(str(texto), delay=random.randint(38, 102))
    pausa_humana(0.14, 0.42)


def clic_humano(locator) -> None:
    pausa_humana(0.07, 0.25)
    locator.click()
    pausa_humana(0.18, 0.49)


USER_AGENT_CHROME = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)

STEALTH_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
window.chrome = window.chrome || { runtime: {} };
Object.defineProperty(navigator, 'languages', { get: () => ['es-AR', 'es', 'en'] });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
"""

CHROMIUM_ARGS = (
    "--disable-blink-features=AutomationControlled",
    "--disable-dev-shm-usage",
    "--no-sandbox",
)
