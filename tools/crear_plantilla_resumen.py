"""Genera (una sola vez) la plantilla con tabla dinámica nativa para el
resumen por CUIT: static/plantilla_resumen_cuit.xlsx

Requiere Microsoft Excel instalado + pywin32 (solo entorno de desarrollo).
El portable NO necesita Excel: en runtime se inyectan los datos en esta
plantilla con openpyxl/zip y la tabla dinámica se refresca al abrir.

Uso:  python tools/crear_plantilla_resumen.py
"""

from __future__ import annotations

import io
import re
import sys
import zipfile
from pathlib import Path

import win32com.client as win32

ROOT = Path(__file__).resolve().parents[1]
SALIDA = ROOT / "static" / "plantilla_resumen_cuit.xlsx"

# Constantes Excel
xlDatabase = 1
xlRowField = 1
xlColumnField = 2
xlDataField = 4
xlSum = -4157
xlTabularRow = 1
xlOpenXMLWorkbook = 51

# Formato contabilidad sin moneda, 2 decimales (negativos entre paréntesis,
# cero como guión), igual criterio que el resto de los informes del sistema.
FORMATO_CONTABILIDAD = '_ * #,##0.00_ ;_ * (#,##0.00)_ ;_ * "-"??_ ;_ @_ '

HEADERS = [
    "CUIT",
    "Razón Social",
    "Tipo",
    "Mes",
    "Neto Gravado Total",
    "Ingresos no grav. y exentos",
    "Total IVA",
    "Imp. Total",
]

# Filas de muestra (necesarias para construir la dinámica; se sobreescriben en runtime)
MUESTRA = [
    ["20000000001", "EJEMPLO SA", "Emitidos", "2025-01", 1000.0, 150.0, 210.0, 1210.0],
    ["20000000001", "EJEMPLO SA", "Recibidos", "2025-01", 500.0, 80.0, 105.0, 605.0],
    ["20000000002", "OTRO EJEMPLO SRL", "Emitidos", "2025-02", 2000.0, 200.0, 420.0, 2420.0],
]


# Formato contabilidad canónico (separadores en-US, como se guarda en el xlsx).
# Excel lo guarda mal según el idioma del sistema; lo forzamos por XML.
_FORMATO_XML = (
    "_ * #,##0.00_ ;_ * \\(#,##0.00\\)_ ;_ * &quot;-&quot;??_ ;_ @_ "
)


def _corregir_formato_contabilidad(ruta: Path) -> None:
    """Reescribe el formatCode de los numFmt de styles.xml a contabilidad
    canónica (Excel lo deforma según la config regional al guardar)."""
    base = ruta.read_bytes()
    salida = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(base)) as zin, zipfile.ZipFile(
        salida, "w", zipfile.ZIP_DEFLATED
    ) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "xl/styles.xml":
                txt = data.decode("utf-8")
                txt = re.sub(
                    r'(<numFmt numFmtId="164" formatCode=")[^"]*(")',
                    rf"\g<1>{_FORMATO_XML}\g<2>",
                    txt,
                )
                data = txt.encode("utf-8")
            zout.writestr(item, data)
    ruta.write_bytes(salida.getvalue())


def main() -> int:
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    excel = win32.Dispatch("Excel.Application")
    excel.Visible = False
    excel.DisplayAlerts = False
    wb = excel.Workbooks.Add()
    try:
        ws = wb.Worksheets(1)
        ws.Name = "Datos"

        # Encabezados + muestra
        for j, h in enumerate(HEADERS, start=1):
            ws.Cells(1, j).Value = h
        for i, fila in enumerate(MUESTRA, start=2):
            for j, val in enumerate(fila, start=1):
                ws.Cells(i, j).Value = val

        n_filas = len(MUESTRA) + 1
        n_cols = len(HEADERS)
        rango = ws.Range(ws.Cells(1, 1), ws.Cells(n_filas, n_cols))

        # Tabla estructurada (ListObject) para que la dinámica siga el rango al crecer
        tabla = ws.ListObjects.Add(1, rango, None, 1)  # xlSrcRange=1, xlYes=1
        tabla.Name = "TablaDatos"

        # Hoja de la dinámica
        ws_piv = wb.Worksheets.Add(After=ws)
        ws_piv.Name = "Resumen"

        cache = wb.PivotCaches().Create(
            SourceType=xlDatabase, SourceData="TablaDatos"
        )
        pt = cache.CreatePivotTable(
            TableDestination=ws_piv.Cells(1, 1), TableName="ResumenCUIT"
        )

        f_cuit = pt.PivotFields("CUIT")
        f_cuit.Orientation = xlRowField
        f_cuit.Position = 1
        f_razon = pt.PivotFields("Razón Social")
        f_razon.Orientation = xlRowField
        f_razon.Position = 2
        pt.PivotFields("Tipo").Orientation = xlColumnField

        # Sin subtotales por CUIT/Razón Social (cada CUIT es una sola fila limpia)
        sin_subtotales = [False] * 12
        f_cuit.Subtotals = sin_subtotales
        f_razon.Subtotals = sin_subtotales

        for medida in (
            "Neto Gravado Total",
            "Ingresos no grav. y exentos",
            "Total IVA",
            "Imp. Total",
        ):
            campo = pt.AddDataField(pt.PivotFields(medida), f"Σ {medida}", xlSum)
            campo.NumberFormat = FORMATO_CONTABILIDAD

        # Columnas de importes en la hoja de origen también en contabilidad.
        ws.Columns("E:H").NumberFormat = FORMATO_CONTABILIDAD

        # Layout tabular + repetir etiquetas (CUIT y Razón Social en columnas propias)
        pt.RowAxisLayout(xlTabularRow)
        try:
            pt.RepeatAllLabels(2)  # xlRepeatLabels=2
        except Exception:
            pass
        # RowGrand=columna de total a la derecha (mezcla emitidos+recibidos, sin
        # sentido) → la quitamos. ColumnGrand=fila "Total general" al pie → se deja.
        pt.RowGrand = False
        pt.ColumnGrand = True

        # Refrescar al abrir (clave: en runtime sólo cambiamos los datos)
        pt.PivotCache().RefreshOnFileOpen = True
        pt.EnableDrilldown = True

        if SALIDA.exists():
            SALIDA.unlink()
        wb.SaveAs(str(SALIDA), FileFormat=xlOpenXMLWorkbook)
    finally:
        wb.Close(SaveChanges=False)
        excel.Quit()

    _corregir_formato_contabilidad(SALIDA)
    print(f"Plantilla creada: {SALIDA}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
