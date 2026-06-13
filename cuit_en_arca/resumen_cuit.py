"""Genera el Excel resumen por CUIT con tabla dinámica nativa.

Estrategia (recomendada para openpyxl, que no crea dinámicas desde cero):
se parte de una plantilla `static/plantilla_resumen_cuit.xlsx` creada una vez
con Excel (tabla dinámica + `refreshOnLoad`). En runtime sólo se reemplazan los
datos de la hoja «Datos» y se ajusta el rango de la tabla; Excel recalcula la
dinámica al abrir el archivo. El drill-down (doble clic en un valor) abre una
hoja nueva con el detalle —incluye la clasificación por mes— sin que el sistema
tenga que generarla.
"""

from __future__ import annotations

import io
import re
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape

HEADERS = [
    "CUIT",
    "Razón Social",
    "Tipo",
    "Mes",
    "Neto Gravado Total",
    "Total IVA",
    "Imp. Total",
]

NOMBRE_SALIDA = "Resumen por CUIT.xlsx"
_PLANTILLA = "plantilla_resumen_cuit.xlsx"
_HOJA_DATOS = "xl/worksheets/sheet1.xml"
_TABLA = "xl/tables/table1.xml"


@dataclass
class _AcumTipo:
    # mes "YYYY-MM" -> [neto, iva, total]
    por_mes: dict[str, list[float]] = field(default_factory=dict)

    def sumar(self, mes: str, neto: float, iva: float, total: float) -> None:
        acc = self.por_mes.setdefault(mes, [0.0, 0.0, 0.0])
        acc[0] += neto
        acc[1] += iva
        acc[2] += total


@dataclass
class _AcumCuit:
    cuit: str
    razon_social: str = ""
    emitidos: _AcumTipo = field(default_factory=_AcumTipo)
    recibidos: _AcumTipo = field(default_factory=_AcumTipo)


class ResumenCuitAcumulador:
    """Acumula totales por CUIT/tipo/mes para el Excel resumen."""

    def __init__(self) -> None:
        self._cuits: dict[str, _AcumCuit] = {}

    def agregar(
        self,
        cuit: str,
        *,
        emitidos: bool,
        razon_social: str,
        por_mes: dict[str, dict[str, float]],
    ) -> None:
        ac = self._cuits.setdefault(cuit, _AcumCuit(cuit=cuit))
        if razon_social and not ac.razon_social:
            ac.razon_social = razon_social
        destino = ac.emitidos if emitidos else ac.recibidos
        for mes, vals in por_mes.items():
            destino.sumar(
                mes,
                float(vals.get("neto", 0.0)),
                float(vals.get("iva", 0.0)),
                float(vals.get("total", 0.0)),
            )

    def tiene_datos(self) -> bool:
        return any(
            ac.emitidos.por_mes or ac.recibidos.por_mes
            for ac in self._cuits.values()
        )

    def filas_datos(self) -> list[tuple[str, str, str, str, float, float, float]]:
        filas: list[tuple[str, str, str, str, float, float, float]] = []
        for cuit in sorted(self._cuits):
            ac = self._cuits[cuit]
            for tipo_nombre, tipo_acc in (
                ("Emitidos", ac.emitidos),
                ("Recibidos", ac.recibidos),
            ):
                for mes in sorted(tipo_acc.por_mes):
                    neto, iva, total = tipo_acc.por_mes[mes]
                    filas.append(
                        (cuit, ac.razon_social or cuit, tipo_nombre, mes, neto, iva, total)
                    )
        return filas


def _dir_static() -> Path:
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    else:
        base = Path(__file__).resolve().parents[1]
    return base / "static"


def _ruta_plantilla() -> Path | None:
    p = _dir_static() / _PLANTILLA
    return p if p.is_file() else None


# Estilo 2 en la plantilla = formato contabilidad (numFmtId 164).
_ESTILO_CONTABILIDAD = "2"


def _celda_num(ref: str, valor: float) -> str:
    return f'<c r="{ref}" s="{_ESTILO_CONTABILIDAD}"><v>{valor:.2f}</v></c>'


def _celda_txt(ref: str, texto: str) -> str:
    return f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{escape(texto)}</t></is></c>'


def _col(idx: int) -> str:
    return chr(ord("A") + idx)


def _construir_sheet_data(filas) -> tuple[str, int]:
    rows = []
    encab = "".join(_celda_txt(f"{_col(j)}1", h) for j, h in enumerate(HEADERS))
    rows.append(f'<row r="1" spans="1:7">{encab}</row>')

    r = 2
    for (cuit, razon, tipo, mes, neto, iva, total) in filas:
        try:
            cuit_cell = f'<c r="A{r}"><v>{int(cuit)}</v></c>'
        except (ValueError, TypeError):
            cuit_cell = _celda_txt(f"A{r}", str(cuit))
        celdas = (
            cuit_cell
            + _celda_txt(f"B{r}", str(razon))
            + _celda_txt(f"C{r}", str(tipo))
            + _celda_txt(f"D{r}", str(mes))
            + _celda_num(f"E{r}", float(neto))
            + _celda_num(f"F{r}", float(iva))
            + _celda_num(f"G{r}", float(total))
        )
        rows.append(f'<row r="{r}" spans="1:7">{celdas}</row>')
        r += 1
    return "<sheetData>" + "".join(rows) + "</sheetData>", r - 1


def construir_resumen_cuit_xlsx(acumulador: ResumenCuitAcumulador) -> bytes | None:
    """Devuelve el xlsx resumen (bytes) o None si no hay plantilla/datos."""
    if not acumulador.tiene_datos():
        return None
    plantilla = _ruta_plantilla()
    if plantilla is None:
        return None

    filas = acumulador.filas_datos()
    sheet_data, n_filas = _construir_sheet_data(filas)
    ref = f"A1:G{n_filas}"

    base = plantilla.read_bytes()
    salida = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(base)) as zin, zipfile.ZipFile(
        salida, "w", zipfile.ZIP_DEFLATED
    ) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == _HOJA_DATOS:
                txt = data.decode("utf-8")
                txt = re.sub(r"<sheetData>.*?</sheetData>", sheet_data, txt, flags=re.S)
                txt = re.sub(
                    r'<dimension ref="[^"]*"/>',
                    f'<dimension ref="{ref}"/>',
                    txt,
                )
                data = txt.encode("utf-8")
            elif item.filename == _TABLA:
                txt = data.decode("utf-8")
                txt = re.sub(r'(<table[^>]*\sref=")[^"]*(")', rf"\g<1>{ref}\g<2>", txt)
                txt = re.sub(
                    r'(<autoFilter\s+ref=")[^"]*(")', rf"\g<1>{ref}\g<2>", txt
                )
                data = txt.encode("utf-8")
            zout.writestr(item, data)
    return salida.getvalue()
