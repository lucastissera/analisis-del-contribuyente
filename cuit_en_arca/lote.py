"""Descarga masiva Mis Comprobantes (emitidos + recibidos) desde planilla Excel."""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import Callable

from cuit_en_arca.credenciales import CredencialesArca
from cuit_en_arca.empaquetado import empaquetar_descargas
from cuit_en_arca.errores import AutomatizacionNoDisponibleError, LoginArcaError
from cuit_en_arca.planilla_lote import FilaPlanillaArca, leer_planilla_lote
from cuit_en_arca.service import _headless_desde_env, _requiere_playwright
from cuit_en_arca.stealth import pausa_entre_filas_lote
from cuit_en_arca.validacion import parsear_fecha_argentina

OnProgresoLote = Callable[[int, int, str, bool], None]


@dataclass
class ResultadoLoteArca:
    contenido: bytes
    nombre_archivo: str
    mimetype: str
    total_filas: int
    descargas_ok: int
    ingresos_fallidos: list[str] = field(default_factory=list)
    advertencias: list[str] = field(default_factory=list)


def _nombre_seguro(cuit: str, tipo: str, nombre_sug: str) -> str:
    base = nombre_sug if nombre_sug else f"mis_comprobantes_{tipo}"
    if not base.lower().endswith((".xlsx", ".csv")):
        ext = ".csv" if ".csv" in base.lower() else ".xlsx"
        base = f"{base}{ext}"
    stem = base.rsplit(".", 1)[0]
    ext = base.rsplit(".", 1)[-1]
    return f"{cuit}_{tipo}_{stem}.{ext}"


def _mensaje_sin_descargas(
    advertencias: list[str],
    ingresos_fallidos: list[str],
) -> str:
    base = "No se obtuvo ninguna descarga."
    if advertencias:
        muestra = "; ".join(advertencias[:3])
        extra = f" (+{len(advertencias) - 3} más)" if len(advertencias) > 3 else ""
        return f"{base} Detalle: {muestra}{extra}"
    if ingresos_fallidos:
        muestra = "; ".join(ingresos_fallidos[:3])
        extra = f" (+{len(ingresos_fallidos) - 3} más)" if len(ingresos_fallidos) > 3 else ""
        return f"{base} Ingresos fallidos: {muestra}{extra}"
    return f"{base} Revisá la planilla (CUIT, clave y rango de fechas en columna D)."


def ejecutar_lote_planilla_arca(
    buf: io.BytesIO,
    *,
    on_progreso: OnProgresoLote | None = None,
) -> ResultadoLoteArca:
    _requiere_playwright()

    from cuit_en_arca.automation_playwright import ejecutar_descarga_mis_comprobantes

    filas = leer_planilla_lote(buf)
    total = len(filas)
    archivos: dict[str, bytes] = {}
    ingresos_fallidos: list[str] = []
    advertencias: list[str] = []
    descargas_ok = 0

    headless = _headless_desde_env()

    for i, fila in enumerate(filas):
        if i > 0:
            pausa_entre_filas_lote()

        if on_progreso:
            on_progreso(
                i + 1,
                total,
                f"CUIT {fila.cuit_representado} (fila {fila.fila_excel})…",
                False,
            )

        cred = CredencialesArca(
            cuit_login=fila.cuit_login,
            clave_fiscal=fila.clave_fiscal,
            cuit_representado=fila.cuit_representado,
        )
        desde = parsear_fecha_argentina(fila.fecha_desde)
        hasta = parsear_fecha_argentina(fila.fecha_hasta)

        try:
            resultado = ejecutar_descarga_mis_comprobantes(
                cred,
                desde,
                hasta,
                headless=headless,
                tipo="ambos",
            )
        except LoginArcaError as exc:
            ingresos_fallidos.append(
                f"CUIT ingreso {fila.cuit_login} (fila {fila.fila_excel}): {exc}"
            )
            if on_progreso:
                on_progreso(i + 1, total, f"Fila {fila.fila_excel}: ingreso fallido", True)
            continue
        except Exception as exc:
            advertencias.append(
                f"CUIT {fila.cuit_representado} (fila {fila.fila_excel}): {exc}"
            )
            if on_progreso:
                on_progreso(i + 1, total, f"Fila {fila.fila_excel}: error", True)
            continue

        cuit = fila.cuit_representado
        if resultado.emitidos:
            data_e, nom_e = resultado.emitidos
            archivos[_nombre_seguro(cuit, "emitidos", nom_e)] = data_e
        if resultado.recibidos:
            data_r, nom_r = resultado.recibidos
            archivos[_nombre_seguro(cuit, "recibidos", nom_r)] = data_r
        if resultado.emitidos or resultado.recibidos:
            descargas_ok += 1

        if on_progreso:
            on_progreso(
                i + 1,
                total,
                f"Fila {fila.fila_excel} completada",
                True,
            )

    lineas_errores = []
    if ingresos_fallidos:
        lineas_errores.append("=== Ingresos a ARCA no exitosos (CUIT / clave) ===")
        lineas_errores.extend(ingresos_fallidos)
        lineas_errores.append("")
    if advertencias:
        lineas_errores.append("=== Otros avisos ===")
        lineas_errores.extend(advertencias)
        lineas_errores.append("")
    if not lineas_errores:
        lineas_errores.append("Sin errores de ingreso registrados.")
    texto_errores = "\n".join(lineas_errores)

    if not archivos:
        if ingresos_fallidos and not advertencias:
            pass
        else:
            raise AutomatizacionNoDisponibleError(
                _mensaje_sin_descargas(advertencias, ingresos_fallidos)
            )

    contenido, nombre, mime = empaquetar_descargas(archivos, texto_errores)

    return ResultadoLoteArca(
        contenido=contenido,
        nombre_archivo=nombre,
        mimetype=mime,
        total_filas=len(filas),
        descargas_ok=descargas_ok,
        ingresos_fallidos=ingresos_fallidos,
        advertencias=advertencias,
    )
