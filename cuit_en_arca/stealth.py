"""Pausas y escritura con ritmo humano (tiempos optimizados: ~40% más cortos)."""

from __future__ import annotations

import random
import time

# Segundos estimados por CUIT (emitidos + recibidos) para la barra de progreso.
SEC_ESTIMADOS_POR_CUIT = 78


def pausa_humana(min_sec: float = 0.15, max_sec: float = 0.45) -> None:
    time.sleep(random.uniform(min_sec, max_sec))


def pausa_entre_filas_lote() -> None:
    time.sleep(random.uniform(4.0, 8.0))


def escribir_como_humano(locator, texto: str) -> None:
    locator.click()
    pausa_humana(0.06, 0.2)
    try:
        locator.fill("")
    except Exception:
        pass
    locator.type(str(texto), delay=random.randint(20, 55))
    pausa_humana(0.08, 0.26)


def clic_humano(locator) -> None:
    pausa_humana(0.05, 0.15)
    locator.click()
    pausa_humana(0.1, 0.28)


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


def chromium_args(headless: bool) -> list[str]:
    args = list(CHROMIUM_ARGS)
    if not headless:
        args.append("--start-maximized")
    return args
