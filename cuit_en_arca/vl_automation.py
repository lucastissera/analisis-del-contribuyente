"""Automatización Ventas y Liquidaciones — LPG / LSG / LSP hacienda (ARCA).

Flujos:
- **Granos:** Liquidación primaria de granos → primarias y secundarias recibidas.
- **Hacienda:** Comprobantes en línea → Hacienda y Carne → por emisor y por receptor
  (100 comprobantes por hoja, paginación completa).

Si se eligen granos y hacienda, se procesan **en serie** con login y pestañas
independientes (primero granos, después hacienda), para no mezclar servicios en ARCA.

Grabación hacienda: ``build/vl_grabacion/20260704_230138``, ``20260704_233832`` (CERRAR SESIÓN → Salir).
Grabación granos: ``build/vl_grabacion/20260704_152152``.
Manual: ``python tools/grabar_vl.py`` o ``explorar_vl.bat``.
"""

from __future__ import annotations

import re
import sys
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from cuit_en_arca.sesion_playwright import SesionPlaywrightCompartida

from cuit_en_arca.credenciales import CredencialesArca
from cuit_en_arca.errores import (
    AutomatizacionArcaError,
    AutomatizacionNoDisponibleError,
    CuitRepresentadoNoEncontradoError,
    LoginArcaError,
)
from cuit_en_arca.service import _headless_desde_env

_modo_headless_vl: bool | None = None


def _vl_headless() -> bool:
    if _modo_headless_vl is not None:
        return _modo_headless_vl
    return _headless_desde_env()
from cuit_en_arca.stealth import clic_humano, escribir_como_humano, pausa_humana

VL_TERMINO_BUSQUEDA = "Liquidación primaria de granos"
LSP_TERMINO_BUSQUEDA = "Comprobantes en línea"
_VL_ESPERA_MS = 12_000
_MENU_EMPRESA_RX = re.compile(
    r"liquidaci|consulta|men[uú]|terminar|volver|salir|ingresar",
    re.I,
)

_INVALIDOS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


@dataclass
class ResultadoVlCuit:
    cuit_login: str
    cuit_representado: str
    razon_social: str | None
    carpeta: str
    archivos: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def total_archivos(self) -> int:
        return len(self.archivos)


def _playwright_disponible() -> bool:
    try:
        import playwright  # noqa: F401

        return True
    except ImportError:
        return False


def _log(on_log: Callable[[str], None] | None, msg: str) -> None:
    if on_log:
        try:
            on_log(msg)
        except Exception:
            pass


def _nombre_seguro(nombre: str, *, fallback: str = "archivo") -> str:
    nombre = (nombre or "").strip()
    nombre = _INVALIDOS.sub("_", nombre)
    nombre = re.sub(r"\s+", " ", nombre).strip(" .")
    return nombre or fallback


def _cuit_n(s: str) -> str:
    from cuit_en_arca.automation_playwright import _normalizar_cuit_busqueda

    return _normalizar_cuit_busqueda(s)


def _cuit_fmt(cuit_n: str) -> str:
    if len(cuit_n) != 11:
        return cuit_n
    return f"{cuit_n[:2]}-{cuit_n[2:10]}-{cuit_n[10]}"


def _nombre_carpeta_cuit_vl(
    etiqueta_planilla: str,
    razon_social: str | None = None,
    *,
    fallback: str = "",
) -> str:
    """Carpeta del contribuyente: razón social en ARCA (igual criterio granos/hacienda)."""
    rs = _nombre_seguro((razon_social or "").strip(), fallback="")
    if rs and not re.fullmatch(r"[\d\-]+", rs):
        return rs[:180]
    plan = _nombre_seguro((etiqueta_planilla or "").strip(), fallback="")
    if plan and not re.fullmatch(r"[\d\-]+", plan):
        return plan[:180]
    cuit_n = _cuit_n(fallback or etiqueta_planilla)
    if len(cuit_n) == 11:
        return _cuit_fmt(cuit_n)
    return _nombre_seguro(fallback or etiqueta_planilla, fallback="contribuyente")[:180]


def _renombrar_carpeta_cuit_vl(
    dest: Path,
    etiqueta_planilla: str,
    razon_social: str | None,
    *,
    fallback: str = "",
) -> Path:
    if not dest.is_dir():
        return dest
    nuevo = dest.parent / _nombre_carpeta_cuit_vl(
        etiqueta_planilla, razon_social, fallback=fallback
    )
    if nuevo == dest:
        return dest
    if nuevo.is_dir():
        return dest
    try:
        dest.rename(nuevo)
        return nuevo
    except OSError:
        return dest


def _escritorio_windows() -> Path | None:
    if sys.platform != "win32":
        return None
    import os

    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders",
        ) as key:
            val, _ = winreg.QueryValueEx(key, "Desktop")
            p = Path(str(val))
            if p.is_dir():
                return p
    except Exception:
        pass
    home = Path.home()
    for sub in ("Desktop", "Escritorio", "OneDrive/Desktop", "OneDrive/Escritorio"):
        p = home / sub
        if p.is_dir():
            return p
    return home / "Desktop" if (home / "Desktop").exists() else None


def carpeta_vl_escritorio(
    *,
    base_elegida: str | Path | None = None,
    nombre_sesion: str | None = None,
) -> Path:
    from cuit_en_arca.carpetas_salida import momento_carpeta_ar, stamp_carpeta_ejecucion

    hoy = datetime.now()
    if nombre_sesion:
        nombre = nombre_sesion
    else:
        nombre = f"Ventas y Liquidaciones {stamp_carpeta_ejecucion(momento_carpeta_ar(hoy))}"
    if base_elegida:
        destino = Path(base_elegida) / nombre
        destino.mkdir(parents=True, exist_ok=True)
        return destino
    esc = _escritorio_windows()
    if esc is None:
        destino = Path.cwd() / nombre
    else:
        destino = esc / nombre
    destino.mkdir(parents=True, exist_ok=True)
    return destino


def _activar_busqueda_portal(page, ctx_buscador) -> None:
    btn_clicado = False
    for ctx in (ctx_buscador, page):
        try:
            btn = ctx.get_by_role("button", name=re.compile(r"buscar|search", re.I)).first
            if btn.count() and btn.is_visible(timeout=800):
                clic_humano(btn)
                btn_clicado = True
                break
        except Exception:
            pass
    if not btn_clicado:
        page.keyboard.press("Enter")


def _locator_enlace_lpg(root):
    patron = re.compile(
        r"liquidaci[oó]n\s*primarias?\s*de\s*granos?",
        re.I,
    )
    candidatos = (
        root.get_by_text(patron),
        root.get_by_role("link", name=patron),
        root.locator("a.accesoPrincipal").filter(has_text=patron),
    )
    for loc in candidatos:
        for i in range(min(loc.count(), 12)):
            try:
                item = loc.nth(i)
                if item.is_visible(timeout=900):
                    return item
            except Exception:
                continue
    return None


def _esperar_enlace_lpg(page, intentos: int = 10):
    from cuit_en_arca.automation_playwright import _iter_contextos

    for _ in range(intentos):
        for ctx in _iter_contextos(page):
            link = _locator_enlace_lpg(ctx)
            if link is not None:
                return link
        pausa_humana(0.35, 0.7)
    return None


def _buscar_lpg_en_portal(page):
    from cuit_en_arca.automation_playwright import (
        _click_servicio_y_obtener_pagina,
        _esperar_pagina,
        _iter_contextos,
        _locator_buscador_servicios,
    )

    buscador = None
    ctx_buscador = page
    for ctx in _iter_contextos(page):
        buscador = _locator_buscador_servicios(ctx)
        if buscador is not None:
            ctx_buscador = ctx
            break
    if buscador is None:
        raise AutomatizacionArcaError(
            "No se encontró la barra de búsqueda de servicios en ARCA."
        )

    escribir_como_humano(buscador, VL_TERMINO_BUSQUEDA)
    pausa_humana(0.5, 1.0)
    _activar_busqueda_portal(page, ctx_buscador)
    pausa_humana(0.7, 1.3)
    _esperar_pagina(page, timeout=35_000)

    link = _esperar_enlace_lpg(page)
    if link is None:
        raise AutomatizacionArcaError(
            "No apareció «Liquidación primaria de granos» en el buscador de ARCA."
        )
    return _click_servicio_y_obtener_pagina(page, link)


def _abrir_lpg(page):
    from cuit_en_arca.automation_playwright import (
        _esperar_pagina,
        _esperar_post_login,
        _ir_al_portal_arca,
        _iter_contextos,
    )

    pausa_humana(0.8, 1.4)
    _esperar_post_login(page)
    _esperar_pagina(page, timeout=42_000)

    objetivo = None
    try:
        objetivo = _buscar_lpg_en_portal(page)
    except AutomatizacionArcaError:
        link = _esperar_enlace_lpg(page, intentos=8)
        if link is not None:
            from cuit_en_arca.automation_playwright import _click_servicio_y_obtener_pagina

            objetivo = _click_servicio_y_obtener_pagina(page, link)

    if objetivo is None:
        for ctx in _iter_contextos(page):
            link = _locator_enlace_lpg(ctx)
            if link is None:
                continue
            from cuit_en_arca.automation_playwright import _click_servicio_y_obtener_pagina

            try:
                objetivo = _click_servicio_y_obtener_pagina(page, link)
                break
            except Exception:
                continue

    if objetivo is None:
        try:
            _ir_al_portal_arca(page)
            objetivo = _buscar_lpg_en_portal(page)
        except Exception as exc:
            raise AutomatizacionArcaError(
                f"No se pudo abrir Liquidaciones primarias de granos ({exc})."
            ) from exc

    vl = objetivo or page
    try:
        vl.bring_to_front()
    except Exception:
        pass
    vl.set_default_timeout(40_000)
    try:
        vl.wait_for_load_state("domcontentloaded", timeout=_VL_ESPERA_MS)
    except Exception:
        pass
    pausa_humana(1.0, 1.8)
    return vl


def _esperar_seleccion_contribuyente_lpg(vl, on_log=None) -> None:
    """Espera la pantalla inicial de LPG con la lista de contribuyentes."""
    import re as _re

    patron_url = _re.compile(r"lpg/jsp|serviciosjava.*lpg", _re.I)
    try:
        vl.wait_for_url(patron_url, timeout=25_000)
    except Exception:
        pass
    for _ in range(24):
        try:
            url = (vl.url or "").lower()
            if "lpg" in url and vl.locator(
                "input.botonEmpresa, input.usarManito.botonEmpresa"
            ).count():
                _log(on_log, f"Pantalla LPG: {vl.url}")
                pausa_humana(0.4, 0.8)
                return
        except Exception:
            pass
        pausa_humana(0.35, 0.65)
    raise AutomatizacionArcaError(
        "No cargó la pantalla de selección de contribuyente en Liquidaciones primarias de granos."
    )


def _locator_botones_contribuyente_index(vl):
    """Botones de empresa en index.jsp (grabación 20260704_154951)."""
    return vl.locator(
        "#divCentral form table tbody tr td input.usarManito.botonEmpresa.bordesRedondos, "
        "#divCentral form table tbody tr input.usarManito.botonEmpresa.bordesRedondos"
    )


def _esperar_index_contribuyentes_lpg(vl, on_log=None) -> None:
    """Espera index.jsp con la grilla de contribuyentes (solo razón social visible)."""
    try:
        vl.wait_for_url(re.compile(r"index\.jsp", re.I), timeout=28_000)
    except Exception:
        _esperar_seleccion_contribuyente_lpg(vl, on_log)
    botones = _locator_botones_contribuyente_index(vl)
    try:
        botones.first.wait_for(state="visible", timeout=20_000)
    except Exception as exc:
        raise AutomatizacionArcaError(
            "No apareció la lista de contribuyentes en Liquidaciones primarias de granos "
            "(index.jsp)."
        ) from exc
    _log(on_log, f"Lista de contribuyentes: {vl.url}")
    pausa_humana(0.35, 0.7)


def _listar_empresas_lpg_debug(vl) -> list[str]:
    try:
        botones = _locator_botones_contribuyente_index(vl)
        n = botones.count()
        return [
            (botones.nth(i).get_attribute("value") or "").strip()
            for i in range(min(n, 30))
            if (botones.nth(i).get_attribute("value") or "").strip()
        ]
    except Exception:
        return []


def _confirmar_seleccion_contribuyente_lpg(vl, on_log=None) -> None:
    try:
        vl.wait_for_url(re.compile(r"setearContribuyente|liquidacion", re.I), timeout=18_000)
    except Exception:
        pass
    try:
        vl.wait_for_load_state("domcontentloaded", timeout=_VL_ESPERA_MS)
    except Exception:
        pass
    pausa_humana(0.5, 1.0)


def _seleccionar_contribuyente_lpg(vl, nombre_repr: str, on_log=None) -> str | None:
    """Elige contribuyente: primero por nombre, luego por tipo societario si hay duplicados."""
    from cuit_en_arca.razon_social import AmbiguedadRazonSocialError, resolver_razon_social

    nombre = (nombre_repr or "").strip()
    if not nombre:
        raise AutomatizacionArcaError("Falta el nombre del representado en la planilla.")

    _esperar_index_contribuyentes_lpg(vl, on_log)
    botones = _locator_botones_contribuyente_index(vl)
    total = botones.count()

    if total == 0:
        raise AutomatizacionArcaError(
            "No hay contribuyentes para seleccionar en Liquidaciones primarias de granos."
        )

    opciones: list[str] = []
    botones_por_valor: dict[str, object] = {}
    for i in range(total):
        btn = botones.nth(i)
        try:
            if not btn.is_visible(timeout=1500):
                continue
            valor = (btn.get_attribute("value") or "").strip()
            if not valor:
                continue
            opciones.append(valor)
            botones_por_valor[valor] = btn
        except Exception:
            continue

    try:
        elegido = resolver_razon_social(nombre, opciones)
    except AmbiguedadRazonSocialError as exc:
        raise CuitRepresentadoNoEncontradoError(str(exc)) from exc

    if not elegido:
        visibles = opciones or _listar_empresas_lpg_debug(vl)
        raise CuitRepresentadoNoEncontradoError(
            f"No se encontró «{nombre}» en la lista de LPG. "
            f"Empresas visibles: {', '.join(visibles[:12]) or '(ninguna)'}."
        )

    btn = botones_por_valor.get(elegido)
    if btn is None:
        raise AutomatizacionArcaError(f"No se pudo seleccionar «{elegido}».")

    _log(on_log, f"Contribuyente: {elegido} (planilla: {nombre}).")
    clic_humano(btn)
    _confirmar_seleccion_contribuyente_lpg(vl, on_log)
    return elegido


def _click_input_menu(vl, patron: str, on_log=None) -> None:
    """Clic en botones del menú LPG (input.botonEmpresa con texto en value)."""
    rx = re.compile(patron, re.I)
    inputs = vl.locator("input.usarManito.botonEmpresa, input.botonEmpresa")
    for i in range(min(inputs.count(), 24)):
        inp = inputs.nth(i)
        try:
            val = (inp.get_attribute("value") or inp.inner_text(timeout=400) or "").strip()
            if not val or not rx.search(val):
                continue
            if not inp.is_visible(timeout=2000):
                continue
            clic_humano(inp)
            pausa_humana(0.5, 1.0)
            try:
                vl.wait_for_load_state("domcontentloaded", timeout=_VL_ESPERA_MS)
            except Exception:
                pass
            _log(on_log, f"Menú: {val}.")
            return
        except Exception:
            continue
    raise AutomatizacionArcaError(f"No se encontró el botón de menú «{patron}».")


def _ir_menu_principal(vl, on_log=None) -> None:
    """Vuelve al menú primaria/secundaria (grabación: enlace «Menú principal»)."""
    for loc in (
        vl.get_by_role("link", name=re.compile(r"men[uú]\s*principal", re.I)),
        vl.locator("a").filter(has_text=re.compile(r"men[uú]\s*principal", re.I)),
    ):
        try:
            if loc.count() and loc.first.is_visible(timeout=4000):
                clic_humano(loc.first)
                pausa_humana(0.6, 1.1)
                try:
                    vl.wait_for_load_state("domcontentloaded", timeout=_VL_ESPERA_MS)
                except Exception:
                    pass
                _log(on_log, "Menú principal (primarias / secundarias).")
                return
        except Exception:
            continue
    raise AutomatizacionArcaError("No se encontró el enlace «Menú principal».")


def _escribir_fecha_vl(campo, valor: date) -> None:
    texto = valor.strftime("%d/%m/%Y")
    escribir_como_humano(campo, texto)
    try:
        campo.evaluate(
            """(el, v) => {
              el.value = v;
              el.dispatchEvent(new Event("input", { bubbles: true }));
              el.dispatchEvent(new Event("change", { bubbles: true }));
              el.blur();
            }""",
            texto,
        )
    except Exception:
        pass
    pausa_humana(0.12, 0.25)


def _consultar_por_criterio(vl, desde: date, hasta: date, on_log=None) -> None:
    di = dh = None
    for sel in (
        "#fecha-desde",
        "#fechaDesde",
        "#daterange-fechas-desde",
        'input[name*="desde" i]',
        'input[id*="desde" i]',
    ):
        loc = vl.locator(sel).first
        if loc.count():
            try:
                if loc.is_visible(timeout=1500):
                    di = loc
                    break
            except Exception:
                pass
    for sel in (
        "#fecha-hasta",
        "#fechaHasta",
        "#daterange-fechas-hasta",
        'input[name*="hasta" i]',
        'input[id*="hasta" i]',
    ):
        loc = vl.locator(sel).first
        if loc.count():
            try:
                if loc.is_visible(timeout=1500):
                    dh = loc
                    break
            except Exception:
                pass
    if di is None or dh is None:
        inputs = vl.locator('input[type="text"], input[type="date"]')
        visibles = []
        for i in range(min(inputs.count(), 12)):
            item = inputs.nth(i)
            try:
                if item.is_visible(timeout=400):
                    visibles.append(item)
            except Exception:
                pass
        if len(visibles) >= 2:
            di, dh = visibles[0], visibles[1]
    if di is None or dh is None:
        raise AutomatizacionArcaError(
            "No se encontraron los campos de fecha para la consulta."
        )

    _escribir_fecha_vl(di, desde)
    _escribir_fecha_vl(dh, hasta)
    _log(on_log, f"Rango: {desde:%d/%m/%Y} – {hasta:%d/%m/%Y}.")

    for loc in (
        vl.locator("input.bordesRedondos.textoGris.sombraBlanca"),
        vl.get_by_role("button", name=re.compile(r"consultar\s+por\s+criterio", re.I)),
        vl.locator("input[type='submit'], input[type='button'], button").filter(
            has_text=re.compile(r"consultar\s+por\s+criterio", re.I)
        ),
    ):
        try:
            if loc.count() and loc.first.is_visible(timeout=3000):
                clic_humano(loc.first)
                pausa_humana(0.6, 1.2)
                _log(on_log, "Consulta ejecutada (Consultar por criterio).")
                return
        except Exception:
            continue
    raise AutomatizacionArcaError("No se encontró el botón «Consultar por criterio».")


_SELECTOR_FILAS_GRILLA = (
    "table#tabla4 tbody tr.jig_impar, "
    "table#tabla4 tbody tr.jig_par, "
    "table#tabla4 tbody tr[class*='jig_'], "
    "table#tabla4 tbody tr"
)
_SELECTOR_LINKS_PDF = (
    "table#tabla4 tbody tr.jig_impar a, "
    "table#tabla4 tbody tr.jig_par a, "
    "table#tabla4 tbody tr[class*='jig_'] a.usarManito, "
    "table#tabla4 tbody tr a.usarManito"
)


def _locator_links_pdf(vl):
    return vl.locator(_SELECTOR_LINKS_PDF)


def _contar_liquidaciones_grilla(vl) -> int:
    """Cuenta enlaces de descarga visibles en table#tabla4."""
    try:
        n = _locator_links_pdf(vl).count()
        if n > 0:
            return n
    except Exception:
        pass

    filas = vl.locator(_SELECTOR_FILAS_GRILLA)
    total = filas.count()
    con_link = 0
    for i in range(total):
        fila = filas.nth(i)
        try:
            if fila.locator("a.usarManito").count() or fila.locator("a").count():
                con_link += 1
        except Exception:
            continue
    return con_link


def _link_pdf_grilla(vl, indice: int):
    links = _locator_links_pdf(vl)
    if links.count() > indice:
        return links.nth(indice)

    filas = vl.locator(_SELECTOR_FILAS_GRILLA)
    fila = filas.nth(indice)
    link = fila.locator("a.usarManito").first
    if link.count():
        return link
    return fila.locator("a").first


def _esperar_grilla_liquidaciones(
    vl, on_log=None, *, timeout_ms: int = _VL_ESPERA_MS
) -> bool:
    limite = max(timeout_ms, 4000)
    try:
        vl.locator("table#tabla4").first.wait_for(state="visible", timeout=limite)
        _locator_links_pdf(vl).first.wait_for(state="attached", timeout=limite)
    except Exception:
        return False
    pausa_humana(0.3, 0.6)
    return _contar_liquidaciones_grilla(vl) > 0


def _indice_siguiente_descarga(
    descargados: int, total_inicial: int, disponibles: int
) -> int:
    """Índice del próximo PDF: fila posterior a la última descargada."""
    if disponibles <= 0:
        return -1
    if descargados >= total_inicial:
        return -1
    if disponibles >= total_inicial:
        return min(descargados, disponibles - 1)
    if disponibles == total_inicial - descargados:
        return 0
    return min(descargados, disponibles - 1)


def _volver_tras_pdf(vl, url_grilla: str, on_log=None) -> None:
    try:
        if (vl.url or "") != url_grilla:
            vl.go_back(wait_until="domcontentloaded", timeout=_VL_ESPERA_MS)
            pausa_humana(0.4, 0.8)
    except Exception as exc:
        _log(on_log, f"  • Volver a la grilla: {exc}")


def _restaurar_vista_grilla(vl, url_grilla: str, on_log=None) -> bool:
    """Tras un PDF, ARCA recarga o navega; volver a la grilla de resultados."""
    for intento in range(5):
        if _esperar_grilla_liquidaciones(vl, on_log, timeout_ms=_VL_ESPERA_MS):
            return True
        url_actual = vl.url or ""
        try:
            if url_grilla and url_actual and url_actual != url_grilla:
                vl.go_back(wait_until="domcontentloaded", timeout=_VL_ESPERA_MS)
            else:
                vl.wait_for_load_state("domcontentloaded", timeout=_VL_ESPERA_MS)
            pausa_humana(0.6, 1.1)
        except Exception as exc:
            _log(on_log, f"  • Reintentando volver a la grilla ({intento + 1}/5): {exc}")
    return _esperar_grilla_liquidaciones(vl, on_log, timeout_ms=_VL_ESPERA_MS)


def _intentar_pdf_desde_url(vl, url: str, ruta: Path) -> bool:
    if not url or "about:blank" in url:
        return False

    def _persistir(data: bytes) -> bool:
        if not data or data[:4] != b"%PDF":
            return False
        ruta.write_bytes(data)
        return ruta.is_file()

    try:
        resp = vl.context.request.get(url)
        if resp.ok and _persistir(resp.body()):
            return True
    except Exception:
        pass
    return False


def _guardar_pdf_desde_click(
    vl, link, ruta: Path, on_log=None, *, url_grilla: str = ""
) -> bool:
    """Descarga o captura el PDF al hacer clic en el icono de la grilla LPG/LSG."""
    if ruta.exists():
        return False

    url_antes = vl.url or ""

    try:
        with vl.expect_download(timeout=18_000) as di:
            clic_humano(link)
        d = di.value
        d.save_as(str(ruta))
        return ruta.is_file()
    except Exception:
        pass

    url_tras_click = vl.url or ""
    if url_tras_click and url_tras_click != url_antes:
        if _intentar_pdf_desde_url(vl, url_tras_click, ruta):
            _volver_tras_pdf(vl, url_grilla or url_antes, on_log)
            return True

    try:
        with vl.context.expect_page(timeout=8_000) as pi:
            if url_tras_click == url_antes:
                clic_humano(link)
        pg = pi.value
        pg.wait_for_load_state("domcontentloaded", timeout=25_000)
        pausa_humana(0.4, 0.8)
        url = pg.url or ""
        if _intentar_pdf_desde_url(vl, url, ruta):
            try:
                pg.close()
            except Exception:
                pass
            return True
        try:
            pg.pdf(path=str(ruta))
            if ruta.is_file():
                pg.close()
                return True
        except Exception:
            pass
        try:
            pg.close()
        except Exception:
            pass
    except Exception:
        pass

    url_final = vl.url or ""
    if url_final and url_final != url_antes and _intentar_pdf_desde_url(vl, url_final, ruta):
        _volver_tras_pdf(vl, url_grilla or url_antes, on_log)
        return True

    _log(on_log, "  • Falló descarga PDF (sin respuesta del navegador).")
    return False


def _descargar_pdfs_grilla(
    vl,
    dest: Path,
    *,
    prefijo: str = "liq",
    on_log=None,
) -> list[str]:
    """Descarga todos los PDF visibles en table#tabla4 (columna Acción)."""
    dest.mkdir(parents=True, exist_ok=True)
    guardados: list[str] = []

    if not _esperar_grilla_liquidaciones(vl, on_log):
        _log(on_log, f"No hay PDF para descargar ({prefijo}).")
        return guardados

    total_objetivo = _contar_liquidaciones_grilla(vl)
    if total_objetivo == 0:
        _log(on_log, f"No hay PDF para descargar ({prefijo}).")
        return guardados

    url_grilla = vl.url or ""
    _log(on_log, f"PDFs a descargar ({prefijo}): {total_objetivo}.")

    descargados = 0
    fallos_seguidos = 0
    intentos = 0
    max_intentos = max(total_objetivo * 4, 8)

    while descargados < total_objetivo and intentos < max_intentos:
        intentos += 1
        if descargados > 0:
            if not _restaurar_vista_grilla(vl, url_grilla, on_log):
                _log(
                    on_log,
                    f"  • No se pudo recuperar la grilla tras {descargados}/{total_objetivo} PDF.",
                )
                break
        elif not _esperar_grilla_liquidaciones(vl, on_log):
            _log(on_log, f"  • La grilla de resultados no está lista ({prefijo}).")
            break

        disponibles = _contar_liquidaciones_grilla(vl)
        indice = _indice_siguiente_descarga(descargados, total_objetivo, disponibles)
        if indice < 0:
            break

        try:
            link = _link_pdf_grilla(vl, indice)
            try:
                if link.count() == 0:
                    fallos_seguidos += 1
                    _log(
                        on_log,
                        f"  • Sin enlace en fila {indice + 1} ({disponibles} visibles).",
                    )
                    continue
            except Exception:
                fallos_seguidos += 1
                continue
            if not link.is_visible(timeout=3000):
                link.scroll_into_view_if_needed(timeout=5000)
            numero = descargados + 1
            nombre = _nombre_seguro(
                f"{prefijo}_{numero}.pdf",
                fallback=f"{prefijo}_{numero}.pdf",
            )
            ruta = dest / nombre
            if ruta.exists():
                ruta = dest / f"{prefijo}_{numero}_{intentos}.pdf"
            if _guardar_pdf_desde_click(vl, link, ruta, on_log, url_grilla=url_grilla):
                guardados.append(str(ruta))
                descargados += 1
                fallos_seguidos = 0
                _log(on_log, f"  • PDF ({prefijo}) {descargados}/{total_objetivo}: {ruta.name}")
                _restaurar_vista_grilla(vl, url_grilla, on_log)
            else:
                fallos_seguidos += 1
                _log(
                    on_log,
                    f"  • No se pudo descargar PDF {numero}/{total_objetivo} (fila {indice + 1}).",
                )
                _restaurar_vista_grilla(vl, url_grilla, on_log)
            pausa_humana(0.25, 0.5)
        except Exception as exc:
            fallos_seguidos += 1
            _log(on_log, f"  • Error descargando PDF {descargados + 1}/{total_objetivo}: {exc}")
            _restaurar_vista_grilla(vl, url_grilla, on_log)

        if fallos_seguidos >= 3:
            _log(
                on_log,
                f"  • Se detiene la descarga ({prefijo}) tras varios intentos fallidos.",
            )
            break

    if descargados < total_objetivo and descargados > 0:
        _log(
            on_log,
            f"  • Descarga parcial ({prefijo}): {descargados} de {total_objetivo} PDF.",
        )
    return guardados


# --------------------------------------------------------------------------- #
# Liquidaciones de hacienda (Comprobantes en línea → LSP)
# --------------------------------------------------------------------------- #


def _locator_enlace_comprobantes(root):
    patron = re.compile(r"comprobantes\s+en\s+l[ií]nea", re.I)
    candidatos = (
        root.get_by_text(patron),
        root.get_by_role("link", name=patron),
        root.locator("a.dropdown-item").filter(has_text=patron),
    )
    for loc in candidatos:
        for i in range(min(loc.count(), 12)):
            try:
                item = loc.nth(i)
                if item.is_visible(timeout=900):
                    return item
            except Exception:
                continue
    return None


def _esperar_enlace_comprobantes(page, intentos: int = 10):
    from cuit_en_arca.automation_playwright import _iter_contextos

    for _ in range(intentos):
        for ctx in _iter_contextos(page):
            link = _locator_enlace_comprobantes(ctx)
            if link is not None:
                return link
        pausa_humana(0.35, 0.7)
    return None


def _buscar_comprobantes_en_linea(page):
    from cuit_en_arca.automation_playwright import (
        _click_servicio_y_obtener_pagina,
        _esperar_pagina,
        _iter_contextos,
        _locator_buscador_servicios,
    )

    buscador = None
    ctx_buscador = page
    for ctx in _iter_contextos(page):
        buscador = _locator_buscador_servicios(ctx)
        if buscador is not None:
            ctx_buscador = ctx
            break
    if buscador is None:
        raise AutomatizacionArcaError(
            "No se encontró la barra de búsqueda de servicios en ARCA."
        )

    escribir_como_humano(buscador, LSP_TERMINO_BUSQUEDA)
    pausa_humana(0.5, 1.0)
    _activar_busqueda_portal(page, ctx_buscador)
    pausa_humana(0.7, 1.3)
    _esperar_pagina(page, timeout=35_000)

    link = _esperar_enlace_comprobantes(page)
    if link is None:
        raise AutomatizacionArcaError(
            "No apareció «Comprobantes en línea» en el buscador de ARCA."
        )
    return _click_servicio_y_obtener_pagina(page, link)


def _listar_paginas_lsp(context) -> list:
    out = []
    for pg in context.pages:
        if pg.is_closed():
            continue
        if "lsp-web" in (pg.url or "").lower():
            out.append(pg)
    return out


def _nueva_pestana_lsp(context, paginas_antes: set[int] | None = None):
    """Última pestaña LSP abierta tras el clic (excluye las que ya existían)."""
    candidatas: list = []
    for pg in context.pages:
        if pg.is_closed():
            continue
        if "lsp-web" not in (pg.url or "").lower():
            continue
        if paginas_antes and id(pg) in paginas_antes:
            continue
        candidatas.append(pg)
    return candidatas[-1] if candidatas else None


def _intentos_lsp_apertura() -> int:
    return 5 if _vl_headless() else 3


def _esperar_lsp_tras_clic_rcel(rcel, paginas_antes: set[int], on_log=None):
    """Espera pestaña LSP (popup o misma pestaña); en headless ARCA tarda más."""
    ciclos = 28 if _vl_headless() else 18
    for _ in range(ciclos):
        if "lsp-web" in (rcel.url or "").lower():
            return rcel
        pg = _nueva_pestana_lsp(rcel.context, paginas_antes)
        if pg is not None:
            return pg
        for p in rcel.context.pages:
            if p.is_closed() or id(p) in paginas_antes:
                continue
            if "lsp-web" in (p.url or "").lower():
                return p
        pausa_humana(0.45, 0.75)
    return None


def _cerrar_pestanas_servicio(context, conservar, on_log=None) -> None:
    """Cierra pestañas ARCA que no sean la de portal/rcel/LPG activa."""
    for pg in list(context.pages):
        if pg.is_closed() or pg is conservar:
            continue
        url = (pg.url or "").lower()
        if any(x in url for x in ("lsp-web", "liquidacion", "lpg", "grano")):
            _cerrar_pestana_navegador(pg, on_log, etiqueta="Pestaña de servicio")


def _preparar_reintento_lsp_desde_rcel(rcel, on_log=None) -> None:
    """Tras recuperación: solo menú rcel visible, sin pestañas LSP colgadas."""
    _cerrar_pestanas_lsp(rcel.context, on_log)
    pausa_humana(0.4, 0.8)
    try:
        rcel.bring_to_front()
        rcel.wait_for_load_state("domcontentloaded", timeout=_VL_ESPERA_MS)
    except Exception:
        pass
    link = rcel.locator("#btn_fwd_lsp, a#btn_fwd_lsp").first
    if not link.count():
        link = rcel.get_by_role(
            "link",
            name=re.compile(r"hacienda\s+y\s+carne.*liquidaci", re.I),
        ).first
    try:
        link.wait_for(state="visible", timeout=15_000)
    except Exception:
        pass
    _log(on_log, "  • Menú Comprobantes en línea listo; se reintenta Hacienda y Carne.")


def _cerrar_pestana_navegador(pg, on_log=None, *, etiqueta: str = "Pestaña") -> None:
    """Cierra pestaña (page.close, window.close o Ctrl+W si hace falta)."""
    if pg.is_closed():
        return
    try:
        pg.bring_to_front()
        pausa_humana(0.15, 0.35)
    except Exception:
        pass
    try:
        pg.close()
        pausa_humana(0.2, 0.4)
        if pg.is_closed():
            _log(on_log, f"  • {etiqueta} cerrada.")
            return
    except Exception:
        pass
    if pg.is_closed():
        return
    try:
        pg.evaluate("() => { try { window.close(); } catch (e) {} }")
        pausa_humana(0.25, 0.45)
        if pg.is_closed():
            _log(on_log, f"  • {etiqueta} cerrada (window.close).")
            return
    except Exception:
        pass
    if pg.is_closed():
        return
    if _vl_headless():
        _log(on_log, f"  • No se pudo cerrar {etiqueta} en headless.")
        return
    try:
        pg.bring_to_front()
        pg.keyboard.press("Control+w")
        pausa_humana(0.25, 0.5)
        if not pg.is_closed():
            pg.keyboard.press("Control+W")
        if pg.is_closed():
            _log(on_log, f"  • {etiqueta} cerrada (Ctrl+W).")
        else:
            _log(on_log, f"  • No se pudo cerrar {etiqueta}.")
    except Exception as exc:
        _log(on_log, f"  • No se pudo cerrar {etiqueta}: {exc}")


def _cerrar_pestanas_lsp(context, on_log=None, *, excepto=None) -> None:
    for pg in _listar_paginas_lsp(context):
        if pg is excepto:
            continue
        _cerrar_pestana_navegador(pg, on_log, etiqueta="Pestaña LSP incorrecta")


def _resolver_pagina_lsp(context, on_log=None, *, cerrar_obsoletas: bool = True):
    """Elige la pestaña LSP correcta (con selector de empresa) y cierra las demás."""
    candidatas = _listar_paginas_lsp(context)
    if not candidatas:
        return None

    buena = None
    for pg in reversed(candidatas):
        if _lsp_tiene_seleccion_empresa(pg):
            buena = pg
            break
    if buena is None:
        buena = candidatas[-1]

    if cerrar_obsoletas:
        for pg in candidatas:
            if pg is not buena:
                _cerrar_pestana_navegador(pg, on_log, etiqueta="Pestaña LSP incorrecta")

    try:
        buena.bring_to_front()
        buena.wait_for_load_state("domcontentloaded", timeout=_VL_ESPERA_MS)
    except Exception:
        pass
    pausa_humana(0.35, 0.65)
    return buena


def _pagina_lsp_en_contexto(context) -> object | None:
    return _resolver_pagina_lsp(context, cerrar_obsoletas=False)


def _cerrar_pestanas_no_lsp(context, conservar=None) -> None:
    for pg in list(context.pages):
        if pg.is_closed() or pg is conservar:
            continue
        url = (pg.url or "").lower()
        if "lsp-web" in url:
            continue
        if "fe.afip.gob.ar/rcel" in url or "lsp" in url or "liquidacion" in url:
            try:
                pg.close()
            except Exception:
                pass


def _esperar_pagina_lsp(context, *, timeout_ms: int = 18_000, on_log=None):
    intentos = max(int(timeout_ms / 500), 8)
    for _ in range(intentos):
        pg = _resolver_pagina_lsp(context, on_log, cerrar_obsoletas=True)
        if pg is not None:
            return pg
        pausa_humana(0.35, 0.65)
    return None


def _abrir_comprobantes_en_linea(page):
    from cuit_en_arca.automation_playwright import (
        _esperar_pagina,
        _esperar_post_login,
        _ir_al_portal_arca,
    )

    pausa_humana(0.8, 1.4)
    _esperar_post_login(page)
    _esperar_pagina(page, timeout=42_000)

    rcel = None
    try:
        rcel = _buscar_comprobantes_en_linea(page)
    except AutomatizacionArcaError:
        try:
            _ir_al_portal_arca(page)
            rcel = _buscar_comprobantes_en_linea(page)
        except Exception as exc:
            raise AutomatizacionArcaError(
                f"No se pudo abrir Comprobantes en línea ({exc})."
            ) from exc

    rcel = rcel or page
    try:
        rcel.bring_to_front()
    except Exception:
        pass
    try:
        rcel.wait_for_load_state("domcontentloaded", timeout=_VL_ESPERA_MS)
    except Exception:
        pass
    pausa_humana(0.6, 1.1)
    return rcel


def _locator_botones_empresa(page, *, rcel: bool = False):
    if rcel:
        return page.locator(
            "input.btn_empresa.ui-button, input.btn_empresa, "
            "input.usarManito.botonEmpresa.bordesRedondos, input.botonEmpresa"
        )
    return page.locator("input.btn.btn-default.btn-sm, input.btn_empresa")


def _seleccionar_empresa_por_nombre(
    page,
    nombre_repr: str,
    *,
    contexto: str,
    rcel: bool = False,
    on_log=None,
) -> str | None:
    from cuit_en_arca.razon_social import AmbiguedadRazonSocialError, resolver_razon_social

    nombre = (nombre_repr or "").strip()
    if not nombre:
        raise AutomatizacionArcaError("Falta el nombre del representado en la planilla.")

    botones = _locator_botones_empresa(page, rcel=rcel)
    try:
        botones.first.wait_for(state="visible", timeout=20_000)
    except Exception as exc:
        raise AutomatizacionArcaError(
            f"No apareció la lista de empresas en {contexto}."
        ) from exc

    opciones: list[str] = []
    botones_por_valor: dict[str, object] = {}
    total = botones.count()
    for i in range(total):
        btn = botones.nth(i)
        try:
            if not btn.is_visible(timeout=1500):
                continue
            valor = (btn.get_attribute("value") or btn.inner_text(timeout=400) or "").strip()
            if not valor:
                continue
            opciones.append(valor)
            botones_por_valor[valor] = btn
        except Exception:
            continue

    try:
        elegido = resolver_razon_social(nombre, opciones)
    except AmbiguedadRazonSocialError as exc:
        raise CuitRepresentadoNoEncontradoError(str(exc)) from exc

    if not elegido:
        raise CuitRepresentadoNoEncontradoError(
            f"No se encontró «{nombre}» en {contexto}. "
            f"Empresas visibles: {', '.join(opciones[:12]) or '(ninguna)'}."
        )

    btn = botones_por_valor.get(elegido)
    if btn is None:
        raise AutomatizacionArcaError(f"No se pudo seleccionar «{elegido}».")

    _log(on_log, f"Empresa ({contexto}): {elegido} (planilla: {nombre}).")
    clic_humano(btn)
    pausa_humana(0.6, 1.1)
    try:
        page.wait_for_load_state("domcontentloaded", timeout=_VL_ESPERA_MS)
    except Exception:
        pass
    return elegido


def _lsp_tiene_seleccion_empresa(lsp) -> bool:
    """True si index.jsp muestra botones para elegir contribuyente (grabación 20260704_233832)."""
    botones = lsp.locator(
        "form#frmId input.btn.btn-default.btn-sm, "
        "form#frmId input.btn, "
        "div.container form input.btn"
    )
    try:
        if botones.count() == 0:
            return False
        return botones.first.is_visible(timeout=8000 if _vl_headless() else 4000)
    except Exception:
        return False


def _lsp_cerrar_sesion_y_volver_rcel(lsp, rcel, on_log=None) -> None:
    """CERRAR SESIÓN → Salir → 3 s → cerrar pestaña LSP → volver al menú rcel.

    No reutiliza pestañas LSP que ARCA pueda abrir solas: el reintento lo hace
    ``_abrir_lsp_desde_rcel`` clickeando otra vez Hacienda y Carne.
    """
    _log(on_log, "  • LSP en estado erróneo: CERRAR SESIÓN…")
    pestana_danada = lsp
    cerrar = None
    for loc in (
        lsp.get_by_role("link", name=re.compile(r"cerrar\s+sesi[oó]n", re.I)),
        lsp.locator("nav#navHeader a.menu_a").filter(
            has_text=re.compile(r"cerrar\s+sesi[oó]n", re.I)
        ),
    ):
        try:
            if loc.count() and loc.first.is_visible(timeout=4000):
                cerrar = loc.first
                break
        except Exception:
            continue
    if cerrar is None:
        raise AutomatizacionArcaError(
            "LSP abrió en estado incorrecto y no apareció «CERRAR SESIÓN» para recuperar."
        )
    try:
        pestana_danada.bring_to_front()
    except Exception:
        pass
    clic_humano(cerrar)
    pausa_humana(0.5, 1.0)
    btn_salir = lsp.get_by_role("button", name=re.compile(r"^salir$", re.I))
    try:
        btn_salir.first.wait_for(state="visible", timeout=10_000)
        clic_humano(btn_salir.first)
    except Exception as exc:
        raise AutomatizacionArcaError(
            "No se confirmó «Salir» tras CERRAR SESIÓN en LSP."
        ) from exc

    _log(on_log, "  • Esperando 3 s antes de cerrar la pestaña LSP dañada…")
    time.sleep(3)

    if not pestana_danada.is_closed():
        _cerrar_pestana_navegador(pestana_danada, on_log, etiqueta="Pestaña LSP dañada")
    _cerrar_pestanas_lsp(lsp.context, on_log)

    try:
        rcel.bring_to_front()
        rcel.wait_for_url(re.compile(r"menu_ppal|rcel/jsp", re.I), timeout=20_000)
        rcel.wait_for_load_state("domcontentloaded", timeout=_VL_ESPERA_MS)
    except Exception:
        pass
    _preparar_reintento_lsp_desde_rcel(rcel, on_log)


def _abrir_lsp_desde_rcel(rcel, on_log=None):
    """Abre Hacienda y Carne — Liquidación Electrónica; reintenta si la pestaña falla."""
    max_int = _intentos_lsp_apertura()
    for intento in range(1, max_int + 1):
        _cerrar_pestanas_lsp(rcel.context, on_log)
        link = rcel.locator("#btn_fwd_lsp, a#btn_fwd_lsp").first
        if not link.count():
            link = rcel.get_by_role(
                "link",
                name=re.compile(r"hacienda\s+y\s+carne.*liquidaci", re.I),
            ).first
        if not link.count():
            raise AutomatizacionArcaError(
                "No se encontró «Hacienda y Carne - Liquidación Electrónica» en Comprobantes en línea."
            )
        try:
            if not link.is_visible(timeout=4000):
                link.scroll_into_view_if_needed(timeout=5000)
        except Exception:
            pass

        _log(on_log, f"Abriendo liquidación hacienda (intento {intento}/{max_int})…")
        paginas_antes = {
            id(pg) for pg in rcel.context.pages if not pg.is_closed()
        }
        lsp = None
        try:
            with rcel.expect_popup(timeout=16_000) as pop:
                clic_humano(link)
            lsp = pop.value
        except Exception:
            try:
                with rcel.context.expect_page(timeout=16_000) as pi:
                    clic_humano(link)
                lsp = pi.value
            except Exception:
                clic_humano(link)
                pausa_humana(1.0, 2.0 if _vl_headless() else 1.5)
                lsp = _esperar_lsp_tras_clic_rcel(rcel, paginas_antes, on_log)

        if lsp is None:
            lsp = _esperar_lsp_tras_clic_rcel(rcel, paginas_antes, on_log)

        if lsp is None:
            _log(on_log, "  • No se detectó pestaña LSP; se reintenta desde el menú.")
            _preparar_reintento_lsp_desde_rcel(rcel, on_log)
            continue

        try:
            lsp.wait_for_load_state("domcontentloaded", timeout=25_000 if _vl_headless() else 20_000)
        except Exception:
            pass
        pausa_humana(0.8, 1.4 if _vl_headless() else 1.0)
        lsp.set_default_timeout(40_000)

        if _lsp_tiene_seleccion_empresa(lsp):
            try:
                lsp.bring_to_front()
            except Exception:
                pass
            return lsp

        _log(on_log, "  • LSP sin selector de empresa; se recupera y se reintenta…")
        try:
            _lsp_cerrar_sesion_y_volver_rcel(lsp, rcel, on_log)
        except AutomatizacionArcaError as exc:
            _log(on_log, f"  • Recuperación LSP: {exc}")
            _cerrar_pestanas_lsp(rcel.context, on_log)
            _preparar_reintento_lsp_desde_rcel(rcel, on_log)
        continue

    raise AutomatizacionArcaError(
        "No se pudo abrir Liquidación de hacienda (LSP). "
        "ARCA abrió una pestaña incorrecta repetidamente."
    )


def _abrir_sidebar_lsp(lsp) -> None:
    btn = lsp.locator("button.hamburger.is-closed, #buttonSidebar button.hamburger").first
    try:
        if btn.count() and btn.is_visible(timeout=2000):
            clic_humano(btn)
            pausa_humana(0.3, 0.6)
    except Exception:
        pass


def _menu_lsp(lsp, patron: str, on_log=None) -> None:
    rx = re.compile(patron, re.I)
    _abrir_sidebar_lsp(lsp)
    enlaces = lsp.locator("nav#sidebar-wrapper a, ul.sidebar-nav a")
    for i in range(min(enlaces.count(), 20)):
        link = enlaces.nth(i)
        try:
            txt = (link.inner_text(timeout=500) or "").strip()
            if not txt or not rx.search(txt):
                continue
            if not link.is_visible(timeout=2000):
                continue
            clic_humano(link)
            pausa_humana(0.6, 1.1)
            try:
                lsp.wait_for_load_state("domcontentloaded", timeout=_VL_ESPERA_MS)
            except Exception:
                pass
            _log(on_log, f"Menú LSP: {txt}.")
            return
        except Exception:
            continue
    raise AutomatizacionArcaError(f"No se encontró en el menú LSP: «{patron}».")


def _buscar_liquidaciones_lsp(lsp, desde: date, hasta: date, on_log=None) -> None:
    di = lsp.locator("#fechaDesde").first
    dh = lsp.locator("#fechaHasta").first
    if not di.count() or not dh.count():
        raise AutomatizacionArcaError(
            "No se encontraron los campos de fecha en la consulta LSP."
        )
    _escribir_fecha_vl(di, desde)
    _escribir_fecha_vl(dh, hasta)
    _log(on_log, f"Rango LSP: {desde:%d/%m/%Y} – {hasta:%d/%m/%Y}.")

    btn = lsp.locator("#btnConsultar, a#btnConsultar").first
    if not btn.count():
        btn = lsp.get_by_role("link", name=re.compile(r"^buscar$", re.I)).first
    if not btn.count():
        raise AutomatizacionArcaError("No se encontró el botón «Buscar» en LSP.")
    clic_humano(btn)
    pausa_humana(0.8, 1.4)
    try:
        lsp.wait_for_load_state("domcontentloaded", timeout=_VL_ESPERA_MS)
    except Exception:
        pass
    try:
        lsp.locator("table#resultTable").first.wait_for(state="visible", timeout=20_000)
    except Exception:
        pass


def _establecer_registros_por_pagina_lsp(lsp, n: int = 100, on_log=None) -> None:
    sel = lsp.locator("select#cantPages").first
    if not sel.count():
        return
    try:
        actual = (sel.input_value() or "").strip()
        if actual == str(n):
            return
        sel.select_option(str(n))
        pausa_humana(0.8, 1.4)
        try:
            lsp.wait_for_load_state("domcontentloaded", timeout=_VL_ESPERA_MS)
        except Exception:
            pass
        _log(on_log, f"Grilla LSP: {n} comprobantes por hoja.")
    except Exception as exc:
        _log(on_log, f"  • No se pudo cambiar registros por página: {exc}")


def _pagina_actual_lsp(lsp) -> int:
    try:
        active = lsp.locator("ul.pagination li.active a").first
        if active.count():
            txt = (active.inner_text(timeout=500) or "").strip()
            if txt.isdigit():
                return int(txt)
    except Exception:
        pass
    return 1


def _paginas_visibles_lsp(lsp) -> list[int]:
    paginas: list[int] = []
    links = lsp.locator("ul.pagination li a")
    for i in range(links.count()):
        try:
            txt = (links.nth(i).inner_text(timeout=400) or "").strip()
            if txt.isdigit():
                paginas.append(int(txt))
        except Exception:
            continue
    return sorted(set(paginas)) or [_pagina_actual_lsp(lsp)]


def _ir_pagina_lsp(lsp, num: int, on_log=None) -> None:
    if _pagina_actual_lsp(lsp) == num:
        return
    for loc in (
        lsp.locator(f"ul.pagination a[href*='paginationFormSubmit({num})']"),
        lsp.locator("ul.pagination li a").filter(has_text=re.compile(rf"^{num}$")),
    ):
        try:
            if loc.count() and loc.first.is_visible(timeout=2500):
                clic_humano(loc.first)
                pausa_humana(0.8, 1.4)
                try:
                    lsp.wait_for_load_state("domcontentloaded", timeout=_VL_ESPERA_MS)
                except Exception:
                    pass
                _log(on_log, f"  • Página {num} de resultados LSP.")
                return
        except Exception:
            continue
    raise AutomatizacionArcaError(f"No se pudo ir a la página {num} de resultados LSP.")


_RX_NUM_LIQ_LSP = re.compile(r"(\d+)\s*-\s*(\d+)")


def _formatear_numero_liquidacion_lsp(pto: str, nro: str) -> str:
    p = int(re.sub(r"\D", "", pto) or "0")
    n = int(re.sub(r"\D", "", nro) or "0")
    return f"{p:05d} - {n:08d}"


def _extraer_numero_liquidacion_fila_lsp(fila) -> str | None:
    """Número visible en la grilla LSP, p. ej. «00023 - 00016059»."""
    try:
        raw = fila.evaluate(
            """(row) => {
              const fmt = (pto, nro) => {
                const p = String(parseInt(pto, 10) || 0).padStart(5, '0');
                const n = String(parseInt(nro, 10) || 0).padStart(8, '0');
                return p + ' - ' + n;
              };
              const link = row.querySelector('a.btnImprimir');
              if (link) {
                const onclick = link.getAttribute('onclick') || '';
                const nums = onclick.match(/\\d+/g);
                if (nums && nums.length >= 2) {
                  return fmt(nums[nums.length - 2], nums[nums.length - 1]);
                }
                const href = link.getAttribute('href') || '';
                const hrefNums = href.match(/\\d+/g);
                if (hrefNums && hrefNums.length >= 2) {
                  return fmt(hrefNums[hrefNums.length - 2], hrefNums[hrefNums.length - 1]);
                }
              }
              const tds = [...row.querySelectorAll('td')];
              for (const td of tds) {
                const t = (td.innerText || '').trim();
                const m = t.match(/^(\\d{4,5})\\s*-\\s*(\\d{5,8})$/);
                if (m) return m[1] + ' - ' + m[2];
              }
              for (let i = 0; i < tds.length - 1; i++) {
                const a = (tds[i].innerText || '').trim();
                const b = (tds[i + 1].innerText || '').trim();
                if (/^\\d{4,5}$/.test(a) && /^\\d{5,8}$/.test(b)) {
                  return a + ' - ' + b;
                }
              }
              const full = row.innerText || '';
              const m = full.match(/(\\d{4,5})\\s*-\\s*(\\d{5,8})/);
              if (m) return m[1] + ' - ' + m[2];
              return '';
            }"""
        )
    except Exception:
        return None
    raw = (raw or "").strip()
    if not raw:
        return None
    m = _RX_NUM_LIQ_LSP.search(raw)
    if m:
        return _formatear_numero_liquidacion_lsp(m.group(1), m.group(2))
    return _nombre_seguro(raw, fallback="")


def _ruta_pdf_lsp(dest: Path, numero_liq: str, *, prefijo: str, fila: int, seq: int) -> Path:
    base = _nombre_seguro(f"{numero_liq}.pdf", fallback=f"{prefijo}_{seq}.pdf")
    if not base.lower().endswith(".pdf"):
        base = f"{base}.pdf"
    ruta = dest / base
    if ruta.exists():
        stem = _nombre_seguro(numero_liq, fallback=f"{prefijo}_{seq}")
        ruta = dest / f"{stem}_{fila}.pdf"
    return ruta


def _locator_links_pdf_lsp(lsp):
    """Solo ícono imprimir/PDF (grabación 20260704_230138: btnImprimir.usarMano.glyphicon)."""
    return lsp.locator("table#resultTable tbody tr a.btnImprimir.usarMano, table#resultTable tbody tr a.btnImprimir")


def _link_pdf_fila_lsp(lsp, indice_fila: int):
    filas = lsp.locator("table#resultTable tbody tr")
    fila = filas.nth(indice_fila)
    link = fila.locator("a.btnImprimir.usarMano, a.btnImprimir").first
    if link.count():
        return link
    return None


def _contar_pdfs_lsp(lsp) -> int:
    try:
        n = _locator_links_pdf_lsp(lsp).count()
        if n > 0:
            return n
    except Exception:
        pass
    try:
        filas = lsp.locator("table#resultTable tbody tr")
        total = filas.count()
        con_pdf = 0
        for i in range(total):
            if filas.nth(i).locator("a.btnImprimir").count():
                con_pdf += 1
        return con_pdf
    except Exception:
        return 0


def _descargar_pdfs_pagina_lsp(
    lsp,
    dest: Path,
    *,
    prefijo: str,
    offset: int,
    on_log=None,
) -> list[str]:
    dest.mkdir(parents=True, exist_ok=True)
    guardados: list[str] = []
    total = _contar_pdfs_lsp(lsp)
    if total == 0:
        return guardados

    url_grilla = lsp.url or ""
    fila = 0
    intentos = 0
    max_intentos = max(total * 4, 8)

    while len(guardados) < total and intentos < max_intentos:
        intentos += 1
        if len(guardados) > 0 or intentos > 1:
            if not _restaurar_vista_grilla_lsp(lsp, url_grilla, on_log):
                _log(
                    on_log,
                    f"  • No se pudo recuperar la grilla LSP tras {len(guardados)}/{total} PDF.",
                )
                break

        filas = lsp.locator("table#resultTable tbody tr")
        if fila >= filas.count():
            break

        fila_loc = filas.nth(fila)
        link = _link_pdf_fila_lsp(lsp, fila)
        if link is None:
            fila += 1
            continue

        try:
            if not link.is_visible(timeout=3000):
                link.scroll_into_view_if_needed(timeout=5000)
        except Exception:
            pass

        numero_liq = _extraer_numero_liquidacion_fila_lsp(fila_loc)
        seq = offset + len(guardados) + 1
        if not numero_liq:
            numero_liq = f"{prefijo}_{seq}"
            _log(on_log, f"  • No se leyó nº de liquidación en fila {fila + 1}; se usa {numero_liq}.")
        ruta = _ruta_pdf_lsp(dest, numero_liq, prefijo=prefijo, fila=fila, seq=seq)

        if _guardar_pdf_desde_click(lsp, link, ruta, on_log, url_grilla=url_grilla):
            guardados.append(str(ruta))
            fila += 1
            _log(on_log, f"  • PDF ({prefijo}) {numero_liq}: {ruta.name}")
            _restaurar_vista_grilla_lsp(lsp, url_grilla, on_log)
        else:
            _log(
                on_log,
                f"  • No se pudo descargar PDF {numero_liq} (fila {fila + 1}, {prefijo}).",
            )
            if intentos >= max_intentos - 1:
                break
        pausa_humana(0.25, 0.5)

    return guardados


def _restaurar_vista_grilla_lsp(lsp, url_grilla: str, on_log=None) -> bool:
    for intento in range(5):
        try:
            tbl = lsp.locator("table#resultTable").first
            if tbl.count() and tbl.is_visible(timeout=3000):
                if _contar_pdfs_lsp(lsp) > 0:
                    return True
        except Exception:
            pass
        url_actual = lsp.url or ""
        try:
            if url_grilla and url_actual and url_actual != url_grilla:
                lsp.go_back(wait_until="domcontentloaded", timeout=_VL_ESPERA_MS)
            else:
                lsp.reload(wait_until="domcontentloaded", timeout=_VL_ESPERA_MS)
            pausa_humana(0.5, 1.0)
            lsp.locator("table#resultTable").first.wait_for(state="visible", timeout=12_000)
            if _contar_pdfs_lsp(lsp) > 0:
                return True
        except Exception as exc:
            _log(on_log, f"  • Reintentando grilla LSP ({intento + 1}/5): {exc}")
    return False


def _descargar_lsp_paginado(
    lsp,
    dest: Path,
    *,
    prefijo: str,
    on_log=None,
) -> list[str]:
    """Descarga todos los PDF visibles, recorriendo todas las hojas (100 por página)."""
    guardados: list[str] = []
    visitadas: set[int] = set()
    rondas_sin_nuevas = 0

    while rondas_sin_nuevas < 2:
        paginas = _paginas_visibles_lsp(lsp)
        pendientes = [p for p in paginas if p not in visitadas]
        if not pendientes:
            rondas_sin_nuevas += 1
            continue
        rondas_sin_nuevas = 0
        for pag in sorted(pendientes):
            _ir_pagina_lsp(lsp, pag, on_log)
            visitadas.add(pag)
            nuevos = _descargar_pdfs_pagina_lsp(
                lsp,
                dest,
                prefijo=prefijo,
                offset=len(guardados),
                on_log=on_log,
            )
            guardados.extend(nuevos)
        # Tras completar las hojas conocidas, verificar si aparecieron más
        paginas_despues = _paginas_visibles_lsp(lsp)
        if any(p not in visitadas for p in paginas_despues):
            _log(on_log, "  • Nuevas hojas de comprobantes detectadas; se continúa la descarga.")
            continue
        rondas_sin_nuevas += 1

    if not guardados:
        _log(on_log, f"No hay PDF para descargar ({prefijo}).")
    else:
        _log(on_log, f"Total PDF ({prefijo}): {len(guardados)}.")
    return guardados


def _procesar_liquidaciones_hacienda_emisor(
    lsp,
    dest: Path,
    desde: date,
    hasta: date,
    on_log=None,
) -> list[str]:
    _menu_lsp(lsp, r"consulta.*liquidaciones.*por\s+emisor", on_log)
    _buscar_liquidaciones_lsp(lsp, desde, hasta, on_log)
    _establecer_registros_por_pagina_lsp(lsp, 100, on_log)
    pausa_humana(0.5, 1.0)
    return _descargar_lsp_paginado(lsp, dest, prefijo="LSH_E", on_log=on_log)


def _procesar_liquidaciones_hacienda_receptor(
    lsp,
    dest: Path,
    desde: date,
    hasta: date,
    on_log=None,
) -> list[str]:
    _menu_lsp(lsp, r"consulta.*liquidaciones.*por\s+receptor", on_log)
    _buscar_liquidaciones_lsp(lsp, desde, hasta, on_log)
    _establecer_registros_por_pagina_lsp(lsp, 100, on_log)
    pausa_humana(0.5, 1.0)
    return _descargar_lsp_paginado(lsp, dest, prefijo="LSH_R", on_log=on_log)


def _ejecutar_hacienda_vl(
    page,
    nombre_representado: str,
    carpeta_destino: Path,
    fecha_desde: date,
    fecha_hasta: date,
    *,
    cuit_login: str = "",
    on_log=None,
    on_paso=None,
) -> tuple[str | None, list[str], Path]:
    def paso(clave: str, estado: str) -> None:
        if on_paso:
            try:
                on_paso(clave, estado)
            except Exception:
                pass

    paso("servicio_hacienda", "en_curso")
    _log(on_log, "Abriendo Comprobantes en línea…")
    rcel = _abrir_comprobantes_en_linea(page)
    paso("servicio_hacienda", "ok")

    paso("contribuyente_rcel", "en_curso")
    razon_rcel = _seleccionar_empresa_por_nombre(
        rcel,
        nombre_representado,
        contexto="Comprobantes en línea",
        rcel=True,
        on_log=on_log,
    )
    paso("contribuyente_rcel", "ok")

    lsp = _abrir_lsp_desde_rcel(rcel, on_log)
    try:
        lsp.bring_to_front()
    except Exception:
        pass

    paso("contribuyente_lsp", "en_curso")
    try:
        lsp.wait_for_url(re.compile(r"lsp-web/index\.jsp|lsp-web/inicio", re.I), timeout=20_000)
    except Exception:
        pass
    razon_lsp = _seleccionar_empresa_por_nombre(
        lsp,
        nombre_representado,
        contexto="Liquidación hacienda (LSP)",
        on_log=on_log,
    )
    paso("contribuyente_lsp", "ok")

    razon = razon_lsp or razon_rcel
    carpeta_destino = _renombrar_carpeta_cuit_vl(
        carpeta_destino,
        nombre_representado,
        razon,
        fallback=cuit_login,
    )
    _log(on_log, f"Carpeta contribuyente: {carpeta_destino.name}")

    dest_emisor = carpeta_destino / "Hacienda" / "Emisor"
    dest_receptor = carpeta_destino / "Hacienda" / "Receptor"

    paso("consulta_emisor", "en_curso")
    _log(on_log, "Liquidaciones de hacienda — por emisor…")
    archivos_emisor = _procesar_liquidaciones_hacienda_emisor(
        lsp, dest_emisor, fecha_desde, fecha_hasta, on_log
    )
    paso("consulta_emisor", "ok")
    paso("descargar_emisor", "ok")

    paso("consulta_receptor", "en_curso")
    _log(on_log, "Liquidaciones de hacienda — por receptor…")
    archivos_receptor = _procesar_liquidaciones_hacienda_receptor(
        lsp, dest_receptor, fecha_desde, fecha_hasta, on_log
    )
    paso("consulta_receptor", "ok")
    paso("descargar_receptor", "ok")

    return razon, archivos_emisor + archivos_receptor, carpeta_destino


def _procesar_liquidaciones_primarias(
    vl,
    dest: Path,
    desde: date,
    hasta: date,
    on_log=None,
) -> list[str]:
    _click_input_menu(vl, r"liquidaci[oó]n\s+primaria\s+de\s+granos", on_log)
    _click_input_menu(vl, r"consulta\s+liquidaciones\s+recibidas(?!\s+de)", on_log)
    _consultar_por_criterio(vl, desde, hasta, on_log)
    pausa_humana(0.8, 1.4)
    return _descargar_pdfs_grilla(vl, dest, prefijo="LPG", on_log=on_log)


def _procesar_liquidaciones_secundarias(
    vl,
    dest: Path,
    desde: date,
    hasta: date,
    on_log=None,
) -> list[str]:
    _ir_menu_principal(vl, on_log)
    _click_input_menu(vl, r"liquidaci[oó]n\s+secundaria\s+de\s+granos", on_log)
    _click_input_menu(vl, r"consulta\s+de\s+liquidaciones\s+recibidas", on_log)
    _consultar_por_criterio(vl, desde, hasta, on_log)
    pausa_humana(0.8, 1.4)
    return _descargar_pdfs_grilla(vl, dest, prefijo="LSG", on_log=on_log)


def _fecha_de(texto: str) -> date | None:
    from cuit_en_arca.validacion import parsear_fecha_argentina

    try:
        return parsear_fecha_argentina(texto)
    except Exception:
        return None


_PLANTILLA_VL = "Formato VyL.xlsx"
_PLANTILLA_VL_DIR = "Formato Ventas y Liquidaciones"


def ruta_plantilla_vl_excel() -> Path:
    candidatos: list[Path] = []
    if getattr(sys, "frozen", False):
        bundle = Path(getattr(sys, "_MEIPASS", ""))
        candidatos.extend(
            [
                bundle / _PLANTILLA_VL_DIR / _PLANTILLA_VL,
                bundle / _PLANTILLA_VL,
            ]
        )
    raiz = Path(__file__).resolve().parent.parent
    candidatos.extend(
        [
            raiz / _PLANTILLA_VL_DIR / _PLANTILLA_VL,
            raiz / "Formato DFE" / "Formato DFE.xlsx",
        ]
    )
    for p in candidatos:
        if p.is_file():
            return p
    return candidatos[0]


def ejecutar_vl_cuit(
    cred: CredencialesArca,
    fecha_desde: date | None,
    fecha_hasta: date | None,
    *,
    nombre_representado: str,
    carpeta_destino: Path,
    sistemas: list[str] | None = None,
    headless: bool | None = None,
    on_log: Callable[[str], None] | None = None,
    on_paso: Callable[[str, str], None] | None = None,
    sesion: SesionPlaywrightCompartida | None = None,
) -> ResultadoVlCuit:
    global _modo_headless_vl
    headless = _headless_desde_env() if headless is None else headless
    _modo_headless_vl = headless
    try:
        if not _playwright_disponible():
            raise AutomatizacionNoDisponibleError(
                "Playwright no está instalado. En local: pip install playwright && playwright install chromium"
            )

        from cuit_en_arca.sesion_playwright import SesionPlaywrightCompartida

        sis = sistemas or ["granos"]
        if sesion is not None:
            return _ejecutar_vl_impl(
                sesion,
                cred,
                fecha_desde,
                fecha_hasta,
                nombre_representado=nombre_representado,
                carpeta_destino=carpeta_destino,
                sistemas=sis,
                on_log=on_log,
                on_paso=on_paso,
            )

        with SesionPlaywrightCompartida(headless=headless) as sesion_local:
            return _ejecutar_vl_impl(
                sesion_local,
                cred,
                fecha_desde,
                fecha_hasta,
                nombre_representado=nombre_representado,
                carpeta_destino=carpeta_destino,
                sistemas=sis,
                on_log=on_log,
                on_paso=on_paso,
            )
    finally:
        _modo_headless_vl = None


def _orden_sistemas_vl(sistemas: list[str] | None) -> list[str]:
    """Granos y hacienda nunca comparten sesión ARCA (uno termina, recién empieza el otro)."""
    sis = sistemas or ["granos"]
    return [s for s in ("granos", "hacienda") if s in sis]


def _login_vl(page, cred: CredencialesArca, on_log, paso) -> None:
    from cuit_en_arca.automation_playwright import (
        LOGIN_URL,
        _llenar_cuit_y_avanzar,
        _login_clave_fiscal,
    )

    paso("login", "en_curso")
    _log(on_log, f"Iniciando sesión (CUIT {cred.cuit_login})…")
    page.goto(LOGIN_URL, wait_until="domcontentloaded")
    pausa_humana(0.6, 1.2)
    _llenar_cuit_y_avanzar(page, cred.cuit_login)
    _login_clave_fiscal(page, cred.clave_fiscal, cred.cuit_login)
    paso("login", "ok")


def _ejecutar_vl_impl(
    sesion: SesionPlaywrightCompartida,
    cred: CredencialesArca,
    fecha_desde: date | None,
    fecha_hasta: date | None,
    *,
    nombre_representado: str,
    carpeta_destino: Path,
    sistemas: list[str] | None = None,
    on_log=None,
    on_paso=None,
) -> ResultadoVlCuit:
    from playwright.sync_api import TimeoutError as PlaywrightTimeout

    sistemas_ord = _orden_sistemas_vl(sistemas)
    carpeta_destino.mkdir(parents=True, exist_ok=True)
    resultado = ResultadoVlCuit(
        cuit_login=cred.cuit_login,
        cuit_representado=nombre_representado,
        razon_social=None,
        carpeta=str(carpeta_destino),
    )

    def paso(clave: str, estado: str) -> None:
        if on_paso:
            try:
                on_paso(clave, estado)
            except Exception:
                pass

    if not fecha_desde or not fecha_hasta:
        raise AutomatizacionArcaError("Faltan fechas desde/hasta para la consulta.")

    archivos: list[str] = []
    razon: str | None = None

    try:
        for sistema in sistemas_ord:
            if len(sistemas_ord) > 1:
                _log(
                    on_log,
                    f"Liquidaciones de {sistema}: sesión ARCA independiente "
                    f"(login y navegador aparte).",
                )
            sesion.cerrar_paginas()
            page = sesion.nueva_pagina()
            try:
                _login_vl(page, cred, on_log, paso)

                if sistema == "granos":
                    paso("servicio_granos", "en_curso")
                    _log(on_log, "Abriendo Liquidación primaria de granos…")
                    vl = _abrir_lpg(page)
                    paso("servicio_granos", "ok")

                    paso("contribuyente_granos", "en_curso")
                    razon_granos = _seleccionar_contribuyente_lpg(vl, nombre_representado, on_log)
                    razon = razon or razon_granos
                    paso("contribuyente_granos", "ok")

                    carpeta_destino = _renombrar_carpeta_cuit_vl(
                        carpeta_destino,
                        nombre_representado,
                        razon_granos,
                        fallback=cred.cuit_login,
                    )
                    resultado.carpeta = str(carpeta_destino)
                    _log(on_log, f"Carpeta contribuyente: {carpeta_destino.name}")
                    dest_prim = carpeta_destino / "Primarias"
                    dest_sec = carpeta_destino / "Secundarias"

                    paso("consulta_prim", "en_curso")
                    _log(on_log, "Liquidaciones primarias de granos…")
                    archivos_prim = _procesar_liquidaciones_primarias(
                        vl, dest_prim, fecha_desde, fecha_hasta, on_log
                    )
                    paso("consulta_prim", "ok")
                    paso("descargar_prim", "ok")

                    paso("consulta_sec", "en_curso")
                    _log(on_log, "Liquidaciones secundarias de granos (Menú principal)…")
                    archivos_sec = _procesar_liquidaciones_secundarias(
                        vl, dest_sec, fecha_desde, fecha_hasta, on_log
                    )
                    paso("consulta_sec", "ok")
                    paso("descargar_sec", "ok")
                    archivos.extend(archivos_prim + archivos_sec)

                elif sistema == "hacienda":
                    razon_hac, archivos_hac, carpeta_destino = _ejecutar_hacienda_vl(
                        page,
                        nombre_representado,
                        carpeta_destino,
                        fecha_desde,
                        fecha_hasta,
                        cuit_login=cred.cuit_login,
                        on_log=on_log,
                        on_paso=on_paso,
                    )
                    razon = razon or razon_hac
                    resultado.carpeta = str(carpeta_destino)
                    archivos.extend(archivos_hac)
            finally:
                try:
                    page.close()
                except Exception:
                    pass
                sesion.cerrar_paginas()
                pausa_humana(0.8, 1.4)

        resultado.razon_social = razon
        resultado.archivos = archivos
        _log(
            on_log,
            f"Listo. {len(archivos)} PDF en {carpeta_destino}.",
        )
        return resultado

    except LoginArcaError:
        raise
    except CuitRepresentadoNoEncontradoError:
        raise
    except PlaywrightTimeout as exc:
        raise AutomatizacionArcaError(
            "Tiempo de espera agotado en ARCA (sitio lento o pantalla distinta)."
        ) from exc
    except AutomatizacionArcaError:
        raise
    except Exception as exc:
        raise AutomatizacionArcaError(f"Error en Ventas y Liquidaciones: {exc}") from exc


def ejecutar_vl_lote(
    filas,
    *,
    sistemas: list[str] | None = None,
    headless: bool | None = None,
    on_log=None,
    on_paso=None,
    on_reiniciar_pasos=None,
    on_progreso=None,
    on_cuit_fin=None,
    carpeta_base: str | Path | None = None,
    job_id: str | None = None,
    nombre_carpeta_sesion: str | None = None,
    hay_cupo: Callable[[], bool] | None = None,
    on_cuit_exitoso: Callable[[], None] | None = None,
) -> Path:
    headless = _headless_desde_env() if headless is None else headless
    base = carpeta_vl_escritorio(
        base_elegida=carpeta_base,
        nombre_sesion=nombre_carpeta_sesion,
    )
    total = len(filas)
    _log(on_log, f"Carpeta de destino: {base}")

    from cuit_en_arca.cancelacion import cupo_consumible_tras_cuit, verificar_cancelacion
    from cuit_en_arca.errores import CancelacionUsuarioError
    from cuit_en_arca.sesion_playwright import (
        SesionPlaywrightCompartida,
        reutilizar_navegador_por_defecto,
    )

    def _procesar_lote(con_sesion: SesionPlaywrightCompartida | None) -> None:
        for idx, fila in enumerate(filas, start=1):
            if job_id:
                verificar_cancelacion(job_id)
            cuit_log = getattr(fila, "cuit_login", "")
            nombre_repr = getattr(fila, "nombre_representado", "") or ""
            if on_progreso:
                on_progreso(idx - 1, total, f"{nombre_repr or cuit_log} ({idx}/{total})")
            if on_reiniciar_pasos:
                on_reiniciar_pasos()

            if hay_cupo is not None and not hay_cupo():
                msg = f"Cupo de CUIT agotado ({nombre_repr or cuit_log})"
                _log(on_log, msg)
                if on_cuit_fin:
                    on_cuit_fin(nombre_repr or cuit_log, None, 0, msg)
                if on_progreso:
                    on_progreso(idx, total, msg)
                continue

            cred = CredencialesArca(
                cuit_login=cuit_log,
                clave_fiscal=getattr(fila, "clave_fiscal", ""),
                cuit_representado=cuit_log,
            )
            fd = _fecha_de(getattr(fila, "fecha_desde", "") or "")
            fh = _fecha_de(getattr(fila, "fecha_hasta", "") or "")

            dest = base / _nombre_seguro(
                f"contribuyente_{idx}",
                fallback=cuit_log or f"fila_{idx}",
            )
            dest.mkdir(parents=True, exist_ok=True)

            try:
                res = ejecutar_vl_cuit(
                    cred,
                    fd,
                    fh,
                    nombre_representado=nombre_repr,
                    carpeta_destino=dest,
                    sistemas=sistemas,
                    headless=headless,
                    on_log=on_log,
                    on_paso=on_paso,
                    sesion=con_sesion,
                )
                if job_id and not cupo_consumible_tras_cuit(job_id):
                    raise CancelacionUsuarioError("Descarga cancelada por el usuario.")
                if on_cuit_fin:
                    on_cuit_fin(nombre_repr or cuit_log, res.razon_social, res.total_archivos, None)
                if on_cuit_exitoso:
                    on_cuit_exitoso()
            except CancelacionUsuarioError:
                raise
            except Exception as exc:
                _log(on_log, f"{nombre_repr or cuit_log}: ERROR {exc}")
                if on_paso:
                    try:
                        on_paso("descargar_sec", "error")
                    except Exception:
                        pass
                if on_cuit_fin:
                    on_cuit_fin(nombre_repr or cuit_log, None, 0, str(exc))

            if on_progreso:
                on_progreso(idx, total, f"{nombre_repr or cuit_log} completado ({idx}/{total})")

    if reutilizar_navegador_por_defecto(filas=total):
        with SesionPlaywrightCompartida(headless=headless) as sesion_local:
            _log(on_log, "Navegador compartido activo.")
            _procesar_lote(sesion_local)
    else:
        _procesar_lote(None)

    return base
