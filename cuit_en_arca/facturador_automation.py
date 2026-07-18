"""Automatización Facturador — emisión de comprobantes en ARCA (Comprobantes en línea)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

from cuit_en_arca.credenciales import CredencialesArca
from cuit_en_arca.errores import (
    AutomatizacionArcaError,
    AutomatizacionNoDisponibleError,
    CuitRepresentadoNoEncontradoError,
    LoginArcaError,
    OpcionPlanillaNoDisponibleError,
)
from cuit_en_arca.planilla_facturador import FilaPlanillaFacturador, normalizar_texto_arca
from cuit_en_arca.plantillas_importacion import ruta_plantilla_facturador_excel
from cuit_en_arca.razon_social import normalizar_razon_social
from cuit_en_arca.stealth import clic_humano, escribir_como_humano, pausa_humana

_ESPERA_MS = 45_000


@dataclass
class ResultadoFacturadorFila:
    fila_excel: int
    representado: str
    tipo_comprobante: str
    comprobante: str | None = None
    error: str | None = None


@dataclass
class ResultadoFacturadorLote:
    total: int = 0
    ok: int = 0
    fallidos: int = 0
    filas: list[ResultadoFacturadorFila] = field(default_factory=list)


@dataclass
class _SesionFacturador:
    cuit_login: str | None = None
    representado_norm: str | None = None
    portal: object | None = None
    rcel: object | None = None


def _playwright_disponible() -> bool:
    try:
        import playwright  # noqa: F401

        return True
    except Exception:
        return False


def _log(on_log: Callable[[str], None] | None, msg: str) -> None:
    if on_log:
        try:
            on_log(msg)
        except Exception:
            pass


class _PasoTracker:
    """Marca el paso en curso; ante error deja el resto en pendiente."""

    def __init__(self, on_paso: Callable[[str, str], None] | None) -> None:
        self._on_paso = on_paso
        self.actual: str | None = None

    def iniciar(self, clave: str) -> None:
        self.actual = clave
        if self._on_paso:
            self._on_paso(clave, "en_curso")

    def ok(self, clave: str) -> None:
        if self._on_paso:
            self._on_paso(clave, "ok")
        if self.actual == clave:
            self.actual = None

    def omitir_ok(self, clave: str) -> None:
        if self._on_paso:
            self._on_paso(clave, "ok")

    def error(self) -> None:
        if self.actual and self._on_paso:
            self._on_paso(self.actual, "error")
        self.actual = None


def _norm_repr(nombre: str) -> str:
    return normalizar_razon_social(nombre) or normalizar_texto_arca(nombre)


def _pagina_rcel(context) -> object | None:
    for pg in context.pages:
        if pg.is_closed():
            continue
        if "fe.afip.gob.ar/rcel" in (pg.url or "").lower():
            return pg
    return None


def _esta_en_menu_principal(rcel) -> bool:
    url = (rcel.url or "").lower()
    if "menu_ppal" not in url:
        return False
    try:
        return rcel.locator("#btn_gen_cmp").first.is_visible(timeout=2000)
    except Exception:
        return "menu_ppal" in url


def _click_input_valor(page, patron: str) -> None:
    loc = page.locator(f'input[type="submit"][value*="{patron}" i], input[value*="{patron}" i]').first
    if not loc.count():
        loc = page.get_by_role("button", name=re.compile(patron, re.I)).first
    clic_humano(loc)
    pausa_humana(0.5, 1.0)


def _click_continuar(page) -> None:
    _click_input_valor(page, "Continuar")


def _seleccionar_opcion_select(
    page,
    selector: str,
    valor_excel: str,
    *,
    etiqueta: str,
    modo_punto_venta: bool = False,
) -> None:
    loc = page.locator(selector).first
    try:
        loc.wait_for(state="visible", timeout=_ESPERA_MS)
    except Exception as exc:
        raise AutomatizacionArcaError(f"No apareció el campo {etiqueta}.") from exc

    opciones = loc.locator("option")
    total = opciones.count()
    candidatas: list[tuple[str, str]] = []
    objetivo = normalizar_texto_arca(valor_excel)
    num_pv = re.sub(r"\D", "", valor_excel or "").zfill(5) if modo_punto_venta else ""

    for i in range(total):
        opt = opciones.nth(i)
        try:
            texto = (opt.inner_text(timeout=500) or "").replace("\xa0", " ").strip()
            val = (opt.get_attribute("value") or "").strip()
            if not texto and not val:
                continue
            candidatas.append((val, texto))
        except Exception:
            continue

    elegido_val: str | None = None
    elegido_label: str | None = None
    for val, texto in candidatas:
        norm_texto = normalizar_texto_arca(texto)
        if modo_punto_venta:
            digits = re.sub(r"\D", "", texto.split("-", 1)[0])
            if digits.zfill(5) == num_pv or texto.strip().startswith(num_pv):
                elegido_val = val or None
                elegido_label = texto
                break
        elif norm_texto == objetivo or objetivo in norm_texto or norm_texto in objetivo:
            elegido_val = val or None
            elegido_label = texto
            break

    if not elegido_label:
        visibles = [t for _, t in candidatas[:8]]
        raise OpcionPlanillaNoDisponibleError(
            f"«{valor_excel}» no está entre las opciones de {etiqueta} en ARCA. "
            f"Disponibles: {', '.join(visibles) or '(ninguna)'}."
        )

    if elegido_val:
        loc.select_option(value=elegido_val)
    else:
        loc.select_option(label=elegido_label)
    pausa_humana(0.35, 0.7)


def _seleccionar_opcion_multi(
    page,
    selectores: tuple[str, ...],
    valor_excel: str,
    *,
    etiqueta: str,
    modo_punto_venta: bool = False,
) -> None:
    ultimo: Exception | None = None
    for sel in selectores:
        loc = page.locator(sel).first
        if not loc.count():
            continue
        try:
            _seleccionar_opcion_select(
                page, sel, valor_excel, etiqueta=etiqueta, modo_punto_venta=modo_punto_venta
            )
            return
        except AutomatizacionArcaError as exc:
            ultimo = exc
        except OpcionPlanillaNoDisponibleError:
            raise
    if ultimo:
        raise ultimo
    raise AutomatizacionArcaError(f"No apareció el campo {etiqueta}.")


def _rellenar_fecha_si_visible(page, selectores: tuple[str, ...], valor: str, etiqueta: str) -> None:
    if not (valor or "").strip():
        return
    for sel in selectores:
        loc = page.locator(sel).first
        try:
            if loc.count() and loc.is_visible(timeout=1200):
                loc.fill(valor.strip())
                pausa_humana(0.2, 0.45)
                return
        except Exception:
            continue


def _seleccionar_condicion_venta(page, valor: str) -> None:
    objetivo = normalizar_texto_arca(valor)
    radios = page.locator('input[name^="formadepago"], input[id^="formadepago"]')
    for i in range(radios.count()):
        r = radios.nth(i)
        try:
            rid = r.get_attribute("id") or ""
            label = page.locator(f'label[for="{rid}"]').first
            texto = ""
            if label.count():
                texto = (label.inner_text(timeout=400) or "").strip()
            if normalizar_texto_arca(texto) == objetivo:
                clic_humano(r)
                pausa_humana(0.25, 0.5)
                return
        except Exception:
            continue
    label = page.locator("label").filter(has_text=re.compile(re.escape(valor), re.I)).first
    if label.count():
        clic_humano(label)
        pausa_humana(0.25, 0.5)
        return
    raise OpcionPlanillaNoDisponibleError(
        f"«{valor}» no está entre las condiciones de venta disponibles en ARCA."
    )


def _moneda_extranjera(page, valor: str) -> None:
    v = normalizar_texto_arca(valor)
    if not v:
        return
    si = v in ("si", "s", "yes", "1", "true")
    for sel in (
        "#idCbteEnMonExtr",
        'select[name="idCbteEnMonExtr"]',
        'input[name="idCbteEnMonExtr"]',
    ):
        loc = page.locator(sel).first
        if not loc.count():
            continue
        try:
            if loc.evaluate("el => el.tagName.toLowerCase()") == "select":
                loc.select_option(value="1" if si else "0")
            else:
                loc.check() if si else loc.uncheck()
            pausa_humana(0.25, 0.5)
            return
        except Exception:
            continue


def _login_arca(page, cred: CredencialesArca, on_log=None) -> None:
    from cuit_en_arca.automation_playwright import (
        LOGIN_URL,
        _llenar_cuit_y_avanzar,
        _login_clave_fiscal,
    )

    _log(on_log, f"Iniciando sesión ARCA (CUIT {cred.cuit_login})…")
    page.goto(LOGIN_URL, wait_until="domcontentloaded")
    pausa_humana(0.5, 1.0)
    _llenar_cuit_y_avanzar(page, cred.cuit_login)
    _login_clave_fiscal(page, cred.clave_fiscal, cred.cuit_login)


def _resolver_nombre_titular_desde_portal(portal, cuit_login: str, *, on_log=None) -> str:
    """Obtiene la razón social del titular según el CUIT de ingreso (portal ARCA)."""
    from cuit_en_arca.automation_playwright import _cuit_activo_mcmp, _razon_social_activa_mcmp

    cuit_n = re.sub(r"\D", "", cuit_login or "")
    if len(cuit_n) != 11:
        return ""

    cuit_activo = _cuit_activo_mcmp(portal) or ""
    nombre = (_razon_social_activa_mcmp(portal) or "").strip()
    if not nombre:
        return ""

    if cuit_activo and cuit_activo != cuit_n:
        _log(
            on_log,
            f"CUIT activo en portal ({cuit_activo}) distinto del de ingreso ({cuit_n}); "
            f"no se infiere titular automáticamente.",
        )
        return ""

    _log(on_log, f"Titular inferido del portal ARCA: {nombre} (CUIT {cuit_n}).")
    return nombre


def _seleccionar_representado_facturador(
    page,
    nombre_repr: str,
    *,
    cuit_login: str = "",
    on_log=None,
) -> str:
    from cuit_en_arca.errores import CuitRepresentadoNoEncontradoError
    from cuit_en_arca.razon_social import AmbiguedadRazonSocialError, resolver_representado_parcial
    from cuit_en_arca.vl_automation import _locator_botones_empresa

    nombre = (nombre_repr or "").strip()

    botones = _locator_botones_empresa(page, rcel=True)
    try:
        botones.first.wait_for(state="visible", timeout=20_000)
    except Exception as exc:
        raise AutomatizacionArcaError(
            "No apareció la lista de representados en Comprobantes en línea."
        ) from exc

    opciones: list[str] = []
    botones_por_valor: dict[str, object] = {}
    for i in range(botones.count()):
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

    if not nombre:
        elegido: str | None = None
        if len(opciones) == 1:
            elegido = opciones[0]
        if not elegido:
            raise CuitRepresentadoNoEncontradoError(
                "Indicá el nombre del representado. En Comprobantes en línea "
                "solo se puede elegir por razón social, no por CUIT."
            )
        btn = botones_por_valor.get(elegido)
        if btn is None:
            raise AutomatizacionArcaError(f"No se pudo seleccionar «{elegido}».")
        _log(on_log, f"Representado (titular): {elegido}.")
        clic_humano(btn)
        pausa_humana(0.6, 1.1)
        try:
            page.wait_for_load_state("domcontentloaded", timeout=_ESPERA_MS)
        except Exception:
            pass
        return elegido

    try:
        elegido = resolver_representado_parcial(nombre, opciones)
    except AmbiguedadRazonSocialError as exc:
        raise CuitRepresentadoNoEncontradoError(str(exc)) from exc

    if not elegido:
        raise CuitRepresentadoNoEncontradoError(
            f"No se encontró «{nombre}» entre los representados disponibles. "
            f"Opciones: {', '.join(opciones[:8]) or '(ninguna)'}."
        )

    btn = botones_por_valor.get(elegido)
    if btn is None:
        raise AutomatizacionArcaError(f"No se pudo seleccionar «{elegido}».")

    _log(on_log, f"Representado: {elegido} (planilla: {nombre}).")
    clic_humano(btn)
    pausa_humana(0.6, 1.1)
    try:
        page.wait_for_load_state("domcontentloaded", timeout=_ESPERA_MS)
    except Exception:
        pass
    return elegido


def _abrir_servicio_y_representado(
    sesion: _SesionFacturador,
    fila: FilaPlanillaFacturador,
    *,
    on_log=None,
    pasos: _PasoTracker | None = None,
) -> object:
    from cuit_en_arca.vl_automation import _abrir_comprobantes_en_linea

    if sesion.portal is None:
        raise AutomatizacionArcaError("No hay sesión de portal ARCA activa.")

    if pasos:
        pasos.iniciar("servicio")
    _log(on_log, "Abriendo Comprobantes en línea…")
    rcel = _abrir_comprobantes_en_linea(sesion.portal)
    if pasos:
        pasos.ok("servicio")

    if pasos:
        pasos.iniciar("representado")
    nombre_repr = (fila.representado or "").strip()
    if not nombre_repr:
        nombre_repr = _resolver_nombre_titular_desde_portal(
            sesion.portal, fila.cuit_login, on_log=on_log
        )
    _log(on_log, f"Seleccionando representado: {nombre_repr or fila.representado}")
    _seleccionar_representado_facturador(
        rcel, nombre_repr, cuit_login=fila.cuit_login, on_log=on_log
    )
    if pasos:
        pasos.ok("representado")

    sesion.rcel = rcel
    sesion.representado_norm = _norm_repr(fila.representado)
    return rcel


def _ir_generar_comprobantes(rcel, on_log=None, pasos: _PasoTracker | None = None) -> None:
    if pasos:
        pasos.iniciar("generar")
    if _esta_en_menu_principal(rcel):
        _log(on_log, "Generar Comprobantes (sesión reutilizada).")
        clic_humano(rcel.locator("#btn_gen_cmp").first)
    else:
        link = rcel.locator("#btn_gen_cmp, a[href*='buscarPtosVtas']").first
        clic_humano(link)
    rcel.wait_for_url(re.compile(r"buscarPtosVtas", re.I), timeout=_ESPERA_MS)
    pausa_humana(0.4, 0.8)
    if pasos:
        pasos.ok("generar")


def _asegurar_pantalla_emision(
    rcel,
    *,
    on_log=None,
    pasos: _PasoTracker | None = None,
) -> None:
    """Tras elegir representado se queda en menú principal; hay que abrir buscarPtosVtas."""
    if re.search(r"buscarPtosVtas", rcel.url or "", re.I):
        return
    if _esta_en_menu_principal(rcel):
        _ir_generar_comprobantes(rcel, on_log=on_log, pasos=pasos)
        return
    _log(on_log, "Navegando al menú principal antes de generar comprobantes…")
    _volver_menu_principal(rcel, on_log=on_log, pasos=None)
    _ir_generar_comprobantes(rcel, on_log=on_log, pasos=pasos)


def _volver_menu_principal(rcel, on_log=None, pasos: _PasoTracker | None = None) -> None:
    if pasos:
        pasos.iniciar("menu")
    _log(on_log, "Volviendo al menú principal para la siguiente factura…")
    btn = rcel.locator('input[value*="Men"], input[value*="Principal"]').first
    if not btn.count():
        btn = rcel.get_by_role("button", name=re.compile(r"men[uú]\s*principal", re.I)).first
    clic_humano(btn)
    rcel.wait_for_url(re.compile(r"menu_ppal", re.I), timeout=_ESPERA_MS)
    pausa_humana(0.5, 1.0)
    if pasos:
        pasos.ok("menu")


def _emitir_comprobante(
    rcel,
    fila: FilaPlanillaFacturador,
    on_log=None,
    pasos: _PasoTracker | None = None,
) -> str | None:
    from cuit_en_arca.planilla_facturador import es_consumidor_final

    _asegurar_pantalla_emision(rcel, on_log=on_log, pasos=pasos)

    if pasos:
        pasos.iniciar("punto_venta")
    _seleccionar_opcion_select(
        rcel, "#puntodeventa", fila.punto_venta, etiqueta="Punto de venta", modo_punto_venta=True
    )
    _seleccionar_opcion_select(
        rcel, "#universocomprobante", fila.tipo_comprobante, etiqueta="Tipo de comprobante"
    )
    _click_continuar(rcel)
    rcel.wait_for_url(re.compile(r"genComDatosEmisor", re.I), timeout=_ESPERA_MS)
    if pasos:
        pasos.ok("punto_venta")

    if pasos:
        pasos.iniciar("datos_emisor")
    _rellenar_fecha_si_visible(
        rcel,
        ("#fechaEmision", 'input[name="fechaEmision"]', "#fchComprobante"),
        fila.fecha_comprobante,
        "Fecha comprobante",
    )
    _seleccionar_opcion_select(rcel, "#idconcepto", fila.concepto, etiqueta="Concepto")
    _moneda_extranjera(rcel, fila.moneda_extranjera)
    _rellenar_fecha_si_visible(
        rcel,
        ("#fchDesde", 'input[name="fchDesde"]', "#fchservdesde"),
        fila.per_facturado_desde,
        "Período facturado desde",
    )
    _rellenar_fecha_si_visible(
        rcel,
        ("#fchHasta", 'input[name="fchHasta"]', "#fchservhasta"),
        fila.per_facturado_hasta,
        "Período facturado hasta",
    )
    _rellenar_fecha_si_visible(
        rcel,
        ("#fchVtoPago", 'input[name="fchVtoPago"]', "#fechavencpago"),
        fila.vto_pago,
        "Vto. para el pago",
    )
    _click_continuar(rcel)
    rcel.wait_for_url(re.compile(r"genComDatosReceptor", re.I), timeout=_ESPERA_MS)
    if pasos:
        pasos.ok("datos_emisor")

    if pasos:
        pasos.iniciar("datos_receptor")
    _seleccionar_opcion_select(
        rcel, "#idivareceptor", fila.condicion_iva, etiqueta="Condición frente al IVA"
    )
    _seleccionar_opcion_multi(
        rcel,
        ("#idtipodocumento", "#idtipodocreceptor"),
        fila.tipo_documento,
        etiqueta="Tipo documento",
    )
    nro_doc = (fila.nro_documento or "").strip()
    if nro_doc or not es_consumidor_final(fila.condicion_iva):
        doc = rcel.locator('#nrodocreceptor, input[name="nrodocreceptor"]').first
        doc.wait_for(state="visible", timeout=_ESPERA_MS)
        if nro_doc:
            valor_doc = (
                re.sub(r"\D", "", nro_doc)
                if "cuit" in normalizar_texto_arca(fila.tipo_documento)
                else nro_doc
            )
            doc.fill(valor_doc)
    _seleccionar_condicion_venta(rcel, fila.condiciones_venta)
    _click_continuar(rcel)
    rcel.wait_for_url(re.compile(r"genComDatosOperacion", re.I), timeout=_ESPERA_MS)
    if pasos:
        pasos.ok("datos_receptor")

    if pasos:
        pasos.iniciar("datos_operacion")
    desc = rcel.locator("#detalle_descripcion1").first
    desc.fill(fila.producto_servicio.strip())
    cant = rcel.locator("#detalle_cantidad1, input[name='detalleCantidad1']").first
    if cant.count() and cant.is_visible(timeout=1500):
        cant.fill(str(fila.cantidad).replace(",", "."))
    precio = rcel.locator("#detalle_precio1, input[name='detallePrecio1']").first
    if precio.count() and precio.is_visible(timeout=1500):
        precio.fill(str(fila.precio_unitario).replace(",", "."))
    um = rcel.locator("#detalle_unidad1, select[name='detalleUM1']").first
    if um.count():
        if um.evaluate("el => el.tagName.toLowerCase()") == "select":
            _seleccionar_opcion_multi(
                rcel,
                ("#detalle_unidad1", "select[name='detalleUM1']"),
                fila.unidad_medida,
                etiqueta="Unidad de medida",
            )
    _click_continuar(rcel)
    rcel.wait_for_url(re.compile(r"genComResumenDatos", re.I), timeout=_ESPERA_MS)
    if pasos:
        pasos.ok("datos_operacion")

    if pasos:
        pasos.iniciar("confirmar")
    clic_humano(rcel.locator("#btngenerar").first)
    pausa_humana(0.4, 0.8)
    confirmar = rcel.locator(
        "div.ui-dialog-buttonpane button",
        has_text=re.compile(r"confirmar", re.I),
    ).first
    confirmar.wait_for(state="visible", timeout=_ESPERA_MS)
    clic_humano(confirmar)
    pausa_humana(0.8, 1.4)
    if pasos:
        pasos.ok("confirmar")

    comprobante = None
    try:
        cuerpo = rcel.locator("body").inner_text(timeout=5000)
        m = re.search(r"(CAE|Comprobante|N[°ºo]\s*)\s*[:\s]*([A-Z0-9\-]+)", cuerpo, re.I)
        if m:
            comprobante = m.group(0).strip()[:120]
    except Exception:
        pass
    _log(on_log, f"Comprobante emitido{f': {comprobante}' if comprobante else ''}.")
    return comprobante


def _recuperar_sesion_para_siguiente_fila(rcel, on_log=None) -> None:
    """Deja la sesión lista para intentar la siguiente fila tras omitir una factura."""
    if rcel is None:
        return
    try:
        if getattr(rcel, "is_closed", lambda: False)():
            return
    except Exception:
        return
    try:
        if _esta_en_menu_principal(rcel):
            return
        url = (rcel.url or "").lower()
        if "buscarptosvtas" in url:
            return
        for _ in range(4):
            if _esta_en_menu_principal(rcel):
                return
            btn = rcel.locator(
                'input[value*="Men"], input[value*="Principal"], a[href*="menu_ppal"]'
            ).first
            if btn.count() and btn.is_visible(timeout=1500):
                clic_humano(btn)
                pausa_humana(0.5, 1.0)
                try:
                    rcel.wait_for_url(re.compile(r"menu_ppal", re.I), timeout=12_000)
                except Exception:
                    pass
            else:
                break
    except Exception as exc:
        _log(on_log, f"Recuperación de sesión limitada tras omitir fila: {exc}")


def _procesar_fila(
    sesion: _SesionFacturador,
    fila: FilaPlanillaFacturador,
    *,
    on_log=None,
    on_paso=None,
) -> ResultadoFacturadorFila:
    pasos = _PasoTracker(on_paso)
    res = ResultadoFacturadorFila(
        fila_excel=fila.fila_excel,
        representado=fila.representado,
        tipo_comprobante=fila.tipo_comprobante,
    )
    try:
        mismo_login = sesion.cuit_login == fila.cuit_login
        mismo_repr = sesion.representado_norm == _norm_repr(fila.representado)
        rcel = sesion.rcel
        if rcel is None or rcel.is_closed():
            mismo_repr = False

        if not mismo_login or not mismo_repr:
            rcel = _abrir_servicio_y_representado(sesion, fila, on_log=on_log, pasos=pasos)
        else:
            pasos.omitir_ok("servicio")
            pasos.omitir_ok("representado")

        res.comprobante = _emitir_comprobante(rcel, fila, on_log=on_log, pasos=pasos)
        _volver_menu_principal(rcel, on_log=on_log, pasos=pasos)
        sesion.rcel = rcel
        sesion.cuit_login = fila.cuit_login
        sesion.representado_norm = _norm_repr(fila.representado)
    except (OpcionPlanillaNoDisponibleError, CuitRepresentadoNoEncontradoError) as exc:
        pasos.error()
        res.error = f"Omitida: {exc}"
        _log(on_log, f"Fila {fila.fila_excel} omitida — {exc}")
        _recuperar_sesion_para_siguiente_fila(rcel, on_log=on_log)
    except Exception as exc:
        pasos.error()
        res.error = str(exc)
        _log(on_log, f"Fila {fila.fila_excel}: {exc}")
        _recuperar_sesion_para_siguiente_fila(rcel, on_log=on_log)
    return res


def ejecutar_facturador_lote(
    filas: list[FilaPlanillaFacturador],
    *,
    headless: bool | None = None,
    on_log: Callable[[str], None] | None = None,
    on_paso: Callable[[str, str], None] | None = None,
    on_progreso: Callable[[int, int, str], None] | None = None,
    job_id: str | None = None,
) -> ResultadoFacturadorLote:
    from cuit_en_arca.cancelacion import verificar_cancelacion
    from cuit_en_arca.service import _headless_desde_env
    from cuit_en_arca.sesion_playwright import SesionPlaywrightCompartida
    from playwright.sync_api import TimeoutError as PlaywrightTimeout

    if not _playwright_disponible():
        raise AutomatizacionNoDisponibleError(
            "Playwright no está instalado. pip install playwright && playwright install chromium"
        )

    headless = _headless_desde_env() if headless is None else headless
    resultado = ResultadoFacturadorLote(total=len(filas))
    sesion_arc = _SesionFacturador()

    with SesionPlaywrightCompartida(headless=headless) as sesion_pw:
        for idx, fila in enumerate(filas, start=1):
            if job_id:
                verificar_cancelacion(job_id)
                from cuit_en_arca.progreso_facturador import reiniciar_pasos_facturador

                reiniciar_pasos_facturador(job_id)
            if on_progreso:
                on_progreso(idx, len(filas), f"Fila {fila.fila_excel} — {fila.tipo_comprobante}")

            if sesion_arc.cuit_login != fila.cuit_login:
                sesion_pw.cerrar_paginas()
                portal = sesion_pw.nueva_pagina()
                cred = CredencialesArca(
                    cuit_login=fila.cuit_login,
                    clave_fiscal=fila.clave_fiscal,
                    cuit_representado=fila.cuit_login,
                )
                pasos_login = _PasoTracker(on_paso)
                try:
                    pasos_login.iniciar("login")
                    _login_arca(portal, cred, on_log=on_log)
                    pasos_login.ok("login")
                except LoginArcaError:
                    pasos_login.error()
                    raise
                sesion_arc = _SesionFacturador(cuit_login=fila.cuit_login, portal=portal)
            elif on_paso and job_id:
                on_paso("login", "ok")

            item = _procesar_fila(sesion_arc, fila, on_log=on_log, on_paso=on_paso)
            resultado.filas.append(item)
            if item.error:
                resultado.fallidos += 1
            else:
                resultado.ok += 1

    return resultado
