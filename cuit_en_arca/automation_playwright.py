"""
Automatización del navegador según el diagrama CUIT en ARCA.

Los selectores de AFIP cambian con frecuencia: si falla, revisar HTML vigente
y ajustar localizadores en este módulo (sin tocar sumar_imp_total).

Requisitos: pip install playwright && playwright install chromium
Habilitar en servidor: variable de entorno CUIT_EN_ARCA_PLAYWRIGHT=1
"""

from __future__ import annotations

import re
import sys
import time
from datetime import date
from pathlib import Path
from typing import Literal

from cuit_en_arca.credenciales import CredencialesArca
from cuit_en_arca.descarga import DescargaArcaResult
from cuit_en_arca.errores import (
    AutomatizacionArcaError,
    AutomatizacionNoDisponibleError,
    CuitRepresentadoNoEncontradoError,
    LoginArcaError,
)
from cuit_en_arca.stealth import (
    CHROMIUM_ARGS,
    STEALTH_INIT_SCRIPT,
    USER_AGENT_CHROME,
    clic_humano,
    escribir_como_humano,
    pausa_humana,
)

LOGIN_URL = "https://auth.afip.gob.ar/contribuyente_/login.xhtml"
PORTAL_ARCA_URL = "https://portalcf.cloud.afip.gob.ar/portal/app/"
# Tras login con sesión válida, el flujo Selenium probado abre esta URL.
URL_MIS_COMPROBANTES_DIRECTA = (
    "https://serviciosweb.afip.gob.ar/genericos/comprobantes/Default.aspx",
)
ESPERA_CORTA_SEC = 3.5
TipoComprobantes = Literal["emitidos", "recibidos", "ambos"]


def _esperar_pagina(page, timeout: int = 42_000) -> None:
    """AFIP rara vez alcanza networkidle; domcontentloaded + pausa breve."""
    try:
        page.wait_for_load_state("domcontentloaded", timeout=timeout)
    except Exception:
        pass
    pausa_humana(0.35, 0.84)

_FRASES_ERROR_LOGIN = (
    "clave incorrect",
    "cuit incorrect",
    "datos incorrect",
    "usuario o contraseña",
    "usuario o contrasena",
    "no coincide",
    "error de autent",
    "verifique los datos",
    "credenciales",
    "acceso denegado",
    "no pudimos validar",
)


def _playwright_disponible() -> bool:
    try:
        import playwright  # noqa: F401

        return True
    except ImportError:
        return False


def _formatear_rango_afip(d: date, h: date) -> tuple[str, str]:
    return d.strftime("%d/%m/%Y"), h.strftime("%d/%m/%Y")


def _normalizar_cuit_busqueda(s: str) -> str:
    return re.sub(r"\D", "", s)


_PATRON_MIS_COMPROBANTES = re.compile(r"mis\s*comprobantes", re.I)
_TERMINO_BUSQUEDA_MC = "Mis Comprobantes"


def _iter_contextos(page):
    """Página principal e iframes (Mis Comprobantes suele cargar el contenido en frames)."""
    yield page
    for frame in page.frames:
        if frame != page.main_frame:
            yield frame


def _encontrar_seccion_tipo(root, etiqueta: str):
    """Localiza Emitidos / Recibidos (enlace, botón, pestaña o celda clickeable)."""
    variantes = (
        etiqueta,
        f"Comprobantes {etiqueta.lower()}",
        f"Comprobantes {etiqueta}",
    )
    for texto in variantes:
        estrategias = (
            root.get_by_role("link", name=texto, exact=True),
            root.locator(f"a:text-is('{texto}')"),
            root.get_by_role("link", name=re.compile(rf"^\s*{re.escape(texto)}\s*$", re.I)),
            root.get_by_role("tab", name=re.compile(re.escape(texto), re.I)),
            root.get_by_role("button", name=re.compile(re.escape(texto), re.I)),
            root.get_by_text(re.compile(rf"^\s*{re.escape(texto)}\s*$", re.I)),
            root.locator("a, button, span, td, li, div, label").filter(
                has_text=re.compile(re.escape(texto), re.I)
            ),
            root.locator(
                f"a[href*='{etiqueta}' i], a[href*='{etiqueta.lower()}' i], "
                f"a[onclick*='{etiqueta}' i]"
            ),
            root.locator(f"a:has-text('{texto}')"),
        )
        for loc in estrategias:
            try:
                n = min(loc.count(), 12)
                for i in range(n):
                    item = loc.nth(i)
                    if item.is_visible(timeout=900):
                        txt = (item.inner_text() or "").strip().lower()
                        if etiqueta.lower() in txt or texto.lower() in txt:
                            return item
                        href = item.get_attribute("href") or ""
                        if etiqueta.lower() in href.lower():
                            return item
            except Exception:
                continue
    return None


def _locator_enlace_mis_comprobantes(root):
    candidatos = (
        root.get_by_role("link", name=_PATRON_MIS_COMPROBANTES),
        root.locator("a", has_text=_PATRON_MIS_COMPROBANTES),
        root.locator(
            "button, [role='button'], [role='option'], li, div, span",
            has_text=_PATRON_MIS_COMPROBANTES,
        ),
    )
    for loc in candidatos:
        try:
            n = min(loc.count(), 15)
            for i in range(n):
                item = loc.nth(i)
                if item.is_visible(timeout=800):
                    return item
        except Exception:
            continue
    return None


def _locator_buscador_servicios(root):
    selectores = (
        'input[placeholder*="Buscar" i]',
        'input[placeholder*="servicio" i]',
        'input[id*="buscador" i]',
        'input[name*="buscador" i]',
        'input[type="search"]',
        "#buscadorInput",
        "#inputSearch",
        ".buscador input",
        'input[aria-label*="Buscar" i]',
    )
    for sel in selectores:
        loc = root.locator(sel).first
        try:
            if loc.count() > 0 and loc.is_visible(timeout=1200):
                return loc
        except Exception:
            continue
    try:
        sb = root.get_by_role("searchbox").first
        if sb.count() > 0 and sb.is_visible(timeout=1200):
            return sb
    except Exception:
        pass
    try:
        ph = root.get_by_placeholder(re.compile(r"buscar", re.I)).first
        if ph.count() > 0 and ph.is_visible(timeout=1200):
            return ph
    except Exception:
        pass
    return None


def _click_servicio_y_obtener_pagina(page, link) -> object:
    try:
        with page.expect_popup(timeout=20_000) as pop:
            clic_humano(link)
        mc = pop.value
    except Exception:
        clic_humano(link)
        _esperar_pagina(page, timeout=42_000)
        mc = page
    _esperar_pagina(mc, timeout=42_000)
    pausa_humana(0.56, 1.12)
    return mc


def _esperar_resultado_mis_comprobantes(page, intentos: int = 10):
    for _ in range(intentos):
        for ctx in _iter_contextos(page):
            link = _locator_enlace_mis_comprobantes(ctx)
            if link is not None:
                return link
        pausa_humana(0.35, 0.7)
    return None


def _buscar_mis_comprobantes_en_portal(page):
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

    escribir_como_humano(buscador, _TERMINO_BUSQUEDA_MC)
    pausa_humana(0.5, 1.0)

    btn_clicado = False
    for ctx in (ctx_buscador, page):
        try:
            btn = ctx.locator(
                "button[type='submit'], button .fa-search, .btn-search, "
                "[class*='search'] button, button[aria-label*='buscar' i]"
            ).first
            if btn.count() > 0 and btn.is_visible(timeout=800):
                clic_humano(btn)
                btn_clicado = True
                break
        except Exception:
            pass
        try:
            btn = ctx.get_by_role("button", name=re.compile(r"buscar|search", re.I)).first
            if btn.count() > 0 and btn.is_visible(timeout=800):
                clic_humano(btn)
                btn_clicado = True
                break
        except Exception:
            pass
    if not btn_clicado:
        page.keyboard.press("Enter")

    pausa_humana(0.7, 1.3)
    _esperar_pagina(page, timeout=35_000)

    link = _esperar_resultado_mis_comprobantes(page)
    if link is None:
        raise AutomatizacionArcaError(
            "No apareció «Mis Comprobantes» en los resultados del buscador de ARCA."
        )
    return _click_servicio_y_obtener_pagina(page, link)


def _pagina_es_login_afip(page) -> bool:
    try:
        url = page.url.lower()
        if "auth.afip" in url or "login.xhtml" in url:
            return True
        pwd = page.locator('input[type="password"]')
        return bool(pwd.count() and pwd.first.is_visible(timeout=1200))
    except Exception:
        return False


def _pagina_es_constatacion(page) -> bool:
    """Página pública de constatación (no es Mis Comprobantes autenticado)."""
    try:
        url = page.url.lower()
        if "servicioscf.afip" in url and "comprobante" in url:
            return True
    except Exception:
        pass
    try:
        cuerpo = page.locator("body").inner_text(timeout=4000).lower()
    except Exception:
        return False
    return (
        "constataci" in cuerpo
        or "se ha movido" in cuerpo
        or "esta pagina se ha movido" in cuerpo
    )


def _tiene_ui_mis_comprobantes(page) -> bool:
    """Emitidos/Recibidos o filtros de fecha visibles (validación estricta)."""
    if _pagina_es_login_afip(page) or _pagina_es_constatacion(page):
        return False
    for ctx in _iter_contextos(page):
        try:
            fechas = ctx.locator(
                "input[id*='fechaEmision' i], input[name*='fechaDesde' i]"
            ).first
            if fechas.count() and fechas.is_visible(timeout=700):
                return True
        except Exception:
            pass
        if _encontrar_seccion_tipo(ctx, "Emitidos") or _encontrar_seccion_tipo(
            ctx, "Recibidos"
        ):
            return True
    return False


def _pagina_parece_mis_comprobantes(page) -> bool:
    """Indicios de que cargó el servicio Mis Comprobantes."""
    if _tiene_ui_mis_comprobantes(page):
        return True
    if _pagina_es_login_afip(page) or _pagina_es_constatacion(page):
        return False
    try:
        cuerpo = page.locator("body").inner_text(timeout=4000).lower()
        return (
            "mis comprobantes" in cuerpo
            and ("emitidos" in cuerpo or "recibidos" in cuerpo)
        )
    except Exception:
        return False


def _esperar_mis_comprobantes_listo(page, timeout_sec: float = 22) -> None:
    limite = time.time() + timeout_sec
    while time.time() < limite:
        if _pagina_parece_mis_comprobantes(page):
            return
        pausa_humana(0.45, 0.9)


def _esperar_post_login(page, timeout_sec: float = 25) -> None:
    """Espera a salir del login de AFIP antes de abrir Mis Comprobantes."""
    limite = time.time() + timeout_sec
    while time.time() < limite:
        if not _pagina_es_login_afip(page):
            return
        pausa_humana(0.4, 0.8)
    _esperar_pagina(page, timeout=15_000)


def _ir_al_portal_arca(page) -> None:
    try:
        if "portalcf.cloud.afip" in page.url.lower():
            _esperar_pagina(page, timeout=35_000)
            return
    except Exception:
        pass
    page.goto(PORTAL_ARCA_URL, wait_until="domcontentloaded")
    _esperar_pagina(page, timeout=42_000)
    pausa_humana(0.7, 1.4)


def _ir_directo_mis_comprobantes(page):
    """Navega directo al servicio con la cookie de sesión (flujo Selenium probado)."""
    try:
        page.goto(URL_MIS_COMPROBANTES_DIRECTA, wait_until="domcontentloaded")
        _esperar_pagina(page, timeout=42_000)
        pausa_humana(1.2, 2.4)
        _esperar_mis_comprobantes_listo(page, timeout_sec=28)
        if _pagina_es_login_afip(page) or _pagina_es_constatacion(page):
            return None
        try:
            page.wait_for_selector(
                "a:has-text('Emitidos'), a:has-text('Recibidos'), "
                "input[id*='fechaEmision' i], input[name*='fechaDesde' i]",
                timeout=14_000,
            )
        except Exception:
            pass
        if _tiene_ui_mis_comprobantes(page):
            return page
    except Exception:
        pass
    return None


def _nuevo_contexto_stealth(playwright, *, headless: bool):
    if not getattr(sys, "frozen", False):
        from cuit_en_arca.ensure_playwright import asegurar_chromium_playwright

        asegurar_chromium_playwright()
    browser = playwright.chromium.launch(
        headless=headless,
        args=list(CHROMIUM_ARGS),
    )
    context = browser.new_context(
        locale="es-AR",
        timezone_id="America/Argentina/Buenos_Aires",
        accept_downloads=True,
        user_agent=USER_AGENT_CHROME,
        viewport={"width": 1366, "height": 768},
        device_scale_factor=1,
        has_touch=False,
        is_mobile=False,
    )
    context.add_init_script(STEALTH_INIT_SCRIPT)
    return browser, context


def _detectar_fallo_login(page, cuit: str) -> None:
    pausa_humana(0.84, 1.75)
    try:
        cuerpo = page.locator("body").inner_text(timeout=5000).lower()
    except Exception:
        cuerpo = ""
    if any(f in cuerpo for f in _FRASES_ERROR_LOGIN):
        raise LoginArcaError(
            f"No se pudo ingresar a ARCA con CUIT {cuit} (clave o CUIT incorrectos)."
        )
    url = page.url.lower()
    if "login" in url or "auth.afip" in url:
        pwd = page.locator('input[type="password"]')
        try:
            if pwd.count() and pwd.first.is_visible(timeout=2000):
                raise LoginArcaError(
                    f"No se pudo ingresar a ARCA con CUIT {cuit} (clave o CUIT incorrectos)."
                )
        except LoginArcaError:
            raise
        except Exception:
            pass


def _llenar_cuit_y_avanzar(page, cuit: str) -> None:
    cuit_llenado = False
    for sel in (
        "input#F1\\:username",
        'input[name*="cuit" i]',
        'input[id*="cuit" i]',
        'input[type="text"]',
    ):
        loc = page.locator(sel).first
        try:
            if loc.count() > 0 and loc.is_visible(timeout=2000):
                escribir_como_humano(loc, cuit)
                cuit_llenado = True
                break
        except Exception:
            continue
    if not cuit_llenado:
        raise AutomatizacionArcaError(
            "No se encontró el campo de CUIT en el login de AFIP (selector desactualizado)."
        )
    btn_sig = page.locator("input#F1\\:btnSiguiente, button#F1\\:btnSiguiente").first
    if btn_sig.count() and btn_sig.is_visible(timeout=1500):
        clic_humano(btn_sig)
    else:
        for texto_btn in ("Siguiente", "Continuar", "Ingresar", "Aceptar"):
            btn = page.get_by_role("button", name=re.compile(texto_btn, re.I))
            if btn.count():
                clic_humano(btn.first)
                break
        else:
            page.keyboard.press("Enter")
    _esperar_pagina(page, timeout=42_000)
    pausa_humana(0.35, 0.84)


def _login_clave_fiscal(page, clave: str, cuit: str) -> None:
    clave_ok = False
    for sel in (
        "input#F1\\:password",
        'input[type="password"]',
        'input[name*="password" i]',
        'input[id*="password" i]',
    ):
        loc = page.locator(sel).first
        try:
            if loc.count() > 0 and loc.is_visible(timeout=2000):
                escribir_como_humano(loc, clave)
                clave_ok = True
                break
        except Exception:
            continue
    if not clave_ok:
        raise AutomatizacionArcaError(
            "No se encontró el campo de clave fiscal (selector desactualizado)."
        )
    btn_ing = page.locator("input#F1\\:btnIngresar, button#F1\\:btnIngresar").first
    if btn_ing.count():
        try:
            if btn_ing.is_visible(timeout=1500):
                clic_humano(btn_ing)
            else:
                page.keyboard.press("Enter")
        except Exception:
            page.keyboard.press("Enter")
    else:
        ingresar = page.get_by_role("button", name=re.compile("ingresar|aceptar", re.I))
        if ingresar.count():
            clic_humano(ingresar.first)
        else:
            page.keyboard.press("Enter")
    _esperar_pagina(page, timeout=63_000)
    _detectar_fallo_login(page, cuit)


def _abrir_mis_comprobantes(page):
    pausa_humana(ESPERA_CORTA_SEC * 0.8, ESPERA_CORTA_SEC * 1.4)
    _esperar_post_login(page)
    _esperar_pagina(page, timeout=42_000)

    for _ in range(2):
        mc = _ir_directo_mis_comprobantes(page)
        if mc is not None and _tiene_ui_mis_comprobantes(mc):
            pausa_humana(0.56, 1.12)
            return mc
        pausa_humana(1.5, 2.5)

    link = _esperar_resultado_mis_comprobantes(page, intentos=8)
    if link is not None:
        mc = _click_servicio_y_obtener_pagina(page, link)
        if _tiene_ui_mis_comprobantes(mc):
            return mc

    try:
        _ir_al_portal_arca(page)
        mc = _buscar_mis_comprobantes_en_portal(page)
        if _tiene_ui_mis_comprobantes(mc):
            return mc
    except AutomatizacionArcaError:
        pass

    for _ in range(2):
        mc = _ir_directo_mis_comprobantes(page)
        if mc is not None and _tiene_ui_mis_comprobantes(mc):
            return mc
        pausa_humana(1.0, 2.0)

    raise AutomatizacionArcaError(
        "No se pudo abrir Mis Comprobantes tras el login "
        "(URL directa, enlace en home y buscador del portal fallaron). "
        "Verifique que el CUIT tenga el servicio «Mis Comprobantes» habilitado."
    )


def _ya_en_pantalla_comprobantes(mc) -> bool:
    """Emitidos/Recibidos o filtros de fecha → ya no hace falta elegir contribuyente."""
    for ctx in _iter_contextos(mc):
        try:
            fechas = ctx.locator(
                "input[id*='fechaEmision' i], input[name*='fechaDesde' i]"
            ).first
            if fechas.count() and fechas.is_visible(timeout=800):
                return True
        except Exception:
            pass
        for etiqueta in ("Emitidos", "Recibidos"):
            if _encontrar_seccion_tipo(ctx, etiqueta) is not None:
                return True
    return False


def _filas_cuit_clicables(mc):
    """Elementos visibles que parecen opciones de contribuyente en un selector."""
    filas = mc.locator(
        "table tbody tr, ul li, div[role='option'], a, button, label"
    ).filter(has_text=re.compile(r"\d{2}[-.]?\d{8}[-.]?\d"))
    resultado = []
    vistos: set[str] = set()
    for i in range(min(filas.count(), 40)):
        item = filas.nth(i)
        try:
            if not item.is_visible(timeout=400):
                continue
            txt = item.inner_text()
            digitos = re.sub(r"\D", "", txt)
            if len(digitos) < 11:
                continue
            cuit = digitos[-11:]
            if cuit in vistos:
                continue
            vistos.add(cuit)
            resultado.append((item, cuit))
        except Exception:
            continue
    return resultado


def _elegir_perfil_representado(
    mc,
    cuit_repr: str,
    *,
    cuit_login: str | None = None,
) -> None:
    pausa_humana(0.6, 1.2)

    if _ya_en_pantalla_comprobantes(mc):
        return

    cuit_repr_n = _normalizar_cuit_busqueda(cuit_repr)
    cuit_login_n = _normalizar_cuit_busqueda(cuit_login) if cuit_login else cuit_repr_n
    fmt = f"{cuit_repr_n[:2]}-{cuit_repr_n[2:10]}-{cuit_repr_n[10]}"

    for loc in (
        mc.get_by_role("link", name=re.compile(re.escape(fmt), re.I)),
        mc.locator("a, tr, li, button").filter(has_text=re.compile(re.escape(fmt))),
        mc.locator("a, tr, li, button").filter(has_text=re.compile(re.escape(cuit_repr_n))),
    ):
        try:
            if loc.count() and loc.first.is_visible(timeout=1000):
                clic_humano(loc.first)
                pausa_humana(ESPERA_CORTA_SEC * 0.7, ESPERA_CORTA_SEC * 1.2)
                return
        except Exception:
            continue

    opciones = _filas_cuit_clicables(mc)

    # Sin lista de perfiles: un solo contribuyente en sesión (CUIT ingreso por defecto).
    if not opciones:
        return

    for item, cuit in opciones:
        if cuit == cuit_repr_n:
            clic_humano(item)
            pausa_humana(ESPERA_CORTA_SEC * 0.7, ESPERA_CORTA_SEC * 1.2)
            return

    # Una sola opción o CUIT pedido = ingreso: AFIP ya usa el contribuyente activo.
    if len(opciones) == 1 or cuit_repr_n == cuit_login_n:
        return

    raise CuitRepresentadoNoEncontradoError(
        "Verificar datos ingresados: el CUIT representado no aparece en la lista."
    )


def _ir_a_tipo_comprobantes(mc, tipo: Literal["emitidos", "recibidos"]) -> None:
    etiqueta = "Emitidos" if tipo == "emitidos" else "Recibidos"
    pausa_humana(0.5, 1.0)
    _esperar_pagina(mc, timeout=42_000)

    if _pagina_es_constatacion(mc):
        raise AutomatizacionArcaError(
            f"No se encontró la sección {etiqueta} en Mis Comprobantes "
            "(se abrió la página de constatación pública en lugar del servicio autenticado)."
        )

    for intento in range(14):
        for ctx in _iter_contextos(mc):
            loc = _encontrar_seccion_tipo(ctx, etiqueta)
            if loc is not None:
                clic_humano(loc)
                _esperar_pagina(mc, timeout=42_000)
                pausa_humana(0.35, 0.7)
                return
        pausa_humana(0.5, 1.0)

    raise AutomatizacionArcaError(
        f"No se encontró la sección {etiqueta} en Mis Comprobantes."
    )


def _llenar_campo_fecha(mc, selectores: tuple[str, ...], valor: str) -> bool:
    for sel in selectores:
        loc = mc.locator(sel).first
        try:
            if loc.count() > 0 and loc.is_visible(timeout=1500):
                escribir_como_humano(loc, valor)
                return True
        except Exception:
            continue
    return False


def _aplicar_filtro_fechas_y_buscar(mc, fd: str, fh: str) -> None:
    filled = 0
    for ctx in _iter_contextos(mc):
        if _llenar_campo_fecha(
            ctx,
            (
                "input[id*='fechaEmisionDesde' i]",
                "input[name*='fechaDesde' i]",
                "input[name*='fechaEmisionDesde' i]",
            ),
            fd,
        ):
            filled += 1
        if _llenar_campo_fecha(
            ctx,
            (
                "input[id*='fechaEmisionHasta' i]",
                "input[name*='fechaHasta' i]",
                "input[name*='fechaEmisionHasta' i]",
            ),
            fh,
        ):
            filled += 1
        if filled >= 2:
            break

    if filled < 2:
        for ctx in _iter_contextos(mc):
            inputs_date = ctx.locator('input[type="text"], input:not([type="hidden"])')
            n_inp = min(inputs_date.count(), 24)
            for i in range(n_inp):
                el = inputs_date.nth(i)
                try:
                    if not el.is_visible():
                        continue
                    ph = (el.get_attribute("placeholder") or "").lower()
                    nm = (el.get_attribute("name") or "").lower()
                    el_id = (el.get_attribute("id") or "").lower()
                    if filled == 0 and (
                        "desde" in ph
                        or "inicio" in ph
                        or "desde" in nm
                        or "desde" in el_id
                        or "emision" in nm
                    ):
                        escribir_como_humano(el, fd)
                        filled += 1
                    elif filled == 1 and (
                        "hasta" in ph or "fin" in ph or "hasta" in nm or "hasta" in el_id
                    ):
                        escribir_como_humano(el, fh)
                        filled += 1
                except Exception:
                    continue
            if filled >= 2:
                break

    buscar_clicado = False
    for ctx in _iter_contextos(mc):
        buscar = ctx.locator(
            "input[value='Buscar'], input[value='BUSCAR'], button:has-text('Buscar')"
        ).first
        if buscar.count() and buscar.is_visible(timeout=1500):
            clic_humano(buscar)
            buscar_clicado = True
            break
        btn = ctx.get_by_role("button", name=re.compile("buscar|consultar|aplicar", re.I))
        if btn.count() and btn.first.is_visible(timeout=1000):
            clic_humano(btn.first)
            buscar_clicado = True
            break
    if not buscar_clicado:
        btn = mc.get_by_role("button", name=re.compile("buscar|consultar|aplicar", re.I))
        if btn.count():
            clic_humano(btn.first)
    _esperar_pagina(mc, timeout=84_000)
    pausa_humana(0.56, 1.05)


def _descargar_excel_o_csv(mc) -> tuple[bytes, str]:
    with mc.expect_download(timeout=120_000) as dl_info:
        excel_btn = mc.locator(
            "a[href*='Excel' i], a:has-text('Excel'), "
            "a:has-text('Descargar'), input[value*='Excel' i]"
        ).first
        if excel_btn.count() and excel_btn.is_visible(timeout=2000):
            clic_humano(excel_btn)
        else:
            alt = mc.get_by_role("button", name=re.compile("excel|xlsx", re.I))
            if not alt.count():
                alt = mc.locator("a, button").filter(
                    has_text=re.compile(r"excel|\.xlsx", re.I)
                )
            if alt.count():
                clic_humano(alt.first)
            else:
                csv_btn = mc.locator("a, button").filter(has_text=re.compile("csv", re.I))
                if csv_btn.count():
                    clic_humano(csv_btn.first)
                else:
                    raise AutomatizacionArcaError(
                        "No se encontró botón de descarga Excel ni CSV tras la búsqueda."
                    )
    download = dl_info.value
    path = download.path()
    if path is None:
        raise AutomatizacionArcaError("La descarga no generó archivo temporal.")
    data = Path(path).read_bytes()
    sug = download.suggested_filename or "mis_comprobantes_descarga"
    return data, sug


def _descargar_tipo_en_sesion(
    mc,
    cuit_repr: str,
    fd: str,
    fh: str,
    tipo: Literal["emitidos", "recibidos"],
    *,
    elegir_perfil: bool,
    cuit_login: str | None = None,
) -> tuple[bytes, str]:
    if elegir_perfil:
        _elegir_perfil_representado(mc, cuit_repr, cuit_login=cuit_login)
    _ir_a_tipo_comprobantes(mc, tipo)
    _aplicar_filtro_fechas_y_buscar(mc, fd, fh)
    return _descargar_excel_o_csv(mc)


def _flujo_post_login(
    mc,
    cuit_repr: str,
    cuit_login: str,
    fd: str,
    fh: str,
    tipo: TipoComprobantes,
) -> DescargaArcaResult:
    if tipo == "ambos":
        data_e, nom_e = _descargar_tipo_en_sesion(
            mc,
            cuit_repr,
            fd,
            fh,
            "emitidos",
            elegir_perfil=True,
            cuit_login=cuit_login,
        )
        pausa_humana(0.7, 1.4)
        data_r, nom_r = _descargar_tipo_en_sesion(
            mc,
            cuit_repr,
            fd,
            fh,
            "recibidos",
            elegir_perfil=False,
            cuit_login=cuit_login,
        )
        return DescargaArcaResult(emitidos=(data_e, nom_e), recibidos=(data_r, nom_r))
    data, nom = _descargar_tipo_en_sesion(
        mc,
        cuit_repr,
        fd,
        fh,
        tipo,
        elegir_perfil=True,
        cuit_login=cuit_login,
    )
    return DescargaArcaResult.simple(data, nom, emitidos=(tipo == "emitidos"))


def ejecutar_descarga_mis_comprobantes(
    cred: CredencialesArca,
    fecha_desde: date,
    fecha_hasta: date,
    *,
    headless: bool = True,
    tipo: TipoComprobantes = "emitidos",
) -> DescargaArcaResult:
    if not _playwright_disponible():
        raise AutomatizacionNoDisponibleError(
            "Playwright no está instalado. En local: pip install playwright && playwright install chromium"
        )

    from playwright.sync_api import TimeoutError as PlaywrightTimeout
    from playwright.sync_api import sync_playwright

    fd, fh = _formatear_rango_afip(fecha_desde, fecha_hasta)
    cuit_repr = _normalizar_cuit_busqueda(cred.cuit_representado)
    cuit_login = _normalizar_cuit_busqueda(cred.cuit_login)

    browser = None
    try:
        with sync_playwright() as p:
            browser, context = _nuevo_contexto_stealth(p, headless=headless)
            page = context.new_page()
            page.set_default_timeout(60_000)

            page.goto(LOGIN_URL, wait_until="domcontentloaded")
            pausa_humana(0.56, 1.26)
            _llenar_cuit_y_avanzar(page, cred.cuit_login)
            _login_clave_fiscal(page, cred.clave_fiscal, cred.cuit_login)
            mc = _abrir_mis_comprobantes(page)
            return _flujo_post_login(mc, cuit_repr, cuit_login, fd, fh, tipo)

    except LoginArcaError:
        raise
    except CuitRepresentadoNoEncontradoError:
        raise
    except PlaywrightTimeout as exc:
        raise AutomatizacionArcaError(
            "Tiempo de espera agotado en AFIP (sitio lento o página distinta a la esperada)."
        ) from exc
    except AutomatizacionArcaError:
        raise
    except Exception as exc:
        raise AutomatizacionArcaError(f"Error en automatización: {exc}") from exc
    finally:
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
