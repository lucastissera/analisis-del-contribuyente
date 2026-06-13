"""Verificación estática de la reutilización de navegador (sin AFIP)."""

from __future__ import annotations

import inspect
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _ok(msg: str) -> None:
    print(f"OK  {msg}")


def verificar_imports() -> None:
    from cuit_en_arca.sesion_playwright import (
        SesionPlaywrightCompartida,
        reutilizar_navegador_por_defecto,
    )
    from cuit_en_arca.automation_playwright import ejecutar_descarga_mis_comprobantes
    from cuit_en_arca.dfe_automation import ejecutar_descarga_dfe, ejecutar_dfe_lote
    from cuit_en_arca.nuestra_parte_automation import (
        ejecutar_descarga_nuestra_parte,
        ejecutar_nuestra_parte_lote,
    )
    from cuit_en_arca.lote import ejecutar_lote_arca
    from cuit_en_arca.analisis_programado import (
        ejecutar_analisis_programado,
        lanzar_ejecucion_ap,
        scheduler_estado,
    )

    for fn in (
        ejecutar_descarga_mis_comprobantes,
        ejecutar_descarga_dfe,
        ejecutar_descarga_nuestra_parte,
        ejecutar_lote_arca,
        ejecutar_dfe_lote,
        ejecutar_nuestra_parte_lote,
    ):
        assert "sesion" in inspect.signature(fn).parameters, fn.__name__

    assert reutilizar_navegador_por_defecto(modo_ap=True, filas=1)
    assert reutilizar_navegador_por_defecto(modo_ap=False, filas=2)
    assert not reutilizar_navegador_por_defecto(modo_ap=False, filas=1)
    assert scheduler_estado()["zona_horaria"] == "America/Argentina/Buenos_Aires"
    _ok("imports y firmas de sesion")


def verificar_sesion_ciclo_vida() -> None:
    from cuit_en_arca.sesion_playwright import SesionPlaywrightCompartida

    mock_browser = MagicMock()
    mock_context = MagicMock()
    mock_page = MagicMock()
    mock_context.pages = []

    def _nueva_pagina():
        mock_context.pages.append(mock_page)
        return mock_page

    mock_context.new_page.side_effect = _nueva_pagina

    mock_pw = MagicMock()
    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_pw
    mock_cm.__exit__.return_value = False

    with patch("playwright.sync_api.sync_playwright", return_value=mock_cm), patch(
        "cuit_en_arca.automation_playwright._nuevo_contexto_stealth",
        return_value=(mock_browser, mock_context),
    ):
        with SesionPlaywrightCompartida(headless=True) as sesion:
            page = sesion.nueva_pagina()
            assert page is mock_page
            sesion.cerrar_paginas()
            mock_page.close.assert_called()

    mock_browser.close.assert_called()
    mock_cm.__exit__.assert_called()
    _ok("ciclo de vida SesionPlaywrightCompartida")


def verificar_app() -> None:
    import app

    rutas = {r.rule for r in app.app.url_map.iter_rules()}
    for needle in (
        "/analisis-programado/ejecutar-ahora",
        "/analisis-programado/ejecucion",
        "/api/cancelar-descarga",
        "/arca-descarga-lote",
        "/dfe-descargar",
        "/np-descargar",
    ):
        assert needle in rutas, needle
    _ok("app Flask y rutas principales")


def verificar_lanzar_ap_sin_duplicar() -> None:
    from cuit_en_arca.analisis_programado import ConfigAnalisisProgramado, lanzar_ejecucion_ap
    import cuit_en_arca.analisis_programado as ap_mod

    cfg = ConfigAnalisisProgramado(
        activo=False,
        sistemas=["mis_comprobantes"],
        carpeta_destino="/tmp",
        filas=[{
            "fila_excel": 1,
            "cuit_login": "20123456789",
            "clave_fiscal": "x",
            "cuit_representado": "20123456789",
            "fechas_mis_comprobantes": "01/01/2025 - 31/01/2025",
        }],
    )

    with patch("cuit_en_arca.progreso_analisis_programado.ejecutando_ap", return_value=True):
        ok, msg = lanzar_ejecucion_ap(cfg, manual=True)
        assert not ok and msg

    with patch.object(ap_mod, "ejecutar_analisis_programado") as mock_exec:
        ok, msg = lanzar_ejecucion_ap(cfg, manual=True)
        assert ok and not msg
        import time
        time.sleep(0.05)
    _ok("lanzar_ejecucion_ap reserva slot sin duplicar")


def main() -> int:
    verificar_imports()
    verificar_sesion_ciclo_vida()
    verificar_app()
    verificar_lanzar_ap_sin_duplicar()
    print("Verificacion completa sin errores.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
