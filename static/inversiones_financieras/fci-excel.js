/**
 * Exportación FCI: anchos y números con formato contabilidad (negativos entre paréntesis;
 * montos 2 dec., cuotas 5 dec., VU 6 dec.) y hoja "Rdo mensual".
 */
import { redondearA, redondearCuotasFci } from "./formato-contabilidad.js";

/** Contabilidad (miles al abrir según región Excel; negativos entre paréntesis). */
const FMT_CONTABILIDAD_2 = "#,##0.00;(#,##0.00)";
const FMT_CONTABILIDAD_5 = "#,##0.00000;(#,##0.00000)";
const FMT_CONTABILIDAD_6 = "#,##0.000000;(#,##0.000000)";
const FMT_CONTABILIDAD_ENT = "#,##0;(#,##0)";
const FMT_DIA = "dd/mm/yyyy";

/**
 * @param {Array<any>} detallePepsPorLote
 * @returns {Array<Array<any>>} incluye fila 0 = encabezados
 */
export function construirHojaRdoMensual(detallePepsPorLote) {
  const map = new Map();
  for (const row of detallePepsPorLote || []) {
    if (row.tipo !== "Rescate" || !row.fecha) continue;
    const d = row.fecha;
    if (!(d instanceof Date) || Number.isNaN(d.getTime())) continue;
    const y = d.getFullYear();
    const m = d.getMonth() + 1;
    const key = `${y}-${String(m).padStart(2, "0")}`;
    const r = redondearA(Number(row.resultadoParcial) || 0, 2);
    map.set(key, redondearA((map.get(key) || 0) + r, 2));
  }
  const sorted = [...map.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  const cab = ["Año", "Mes", "Resultado parcial (mes, ARS)"];
  if (sorted.length === 0) return [cab];
  return [
    cab,
    ...sorted.map(([ym, v]) => {
      const [yy, mm] = ym.split("-");
      return [Number(yy), Number(mm), v];
    }),
  ];
}

/**
 * Mide ancho lógico por columna (índice) en una hoja.
 * @param {import('xlsx').WorkSheet} ws
 * @param {typeof import('xlsx')} XLSX
 * @returns {{ range: import('xlsx').Range | null, wch: number[] }}
 */
function medirAnchosHoja(ws, XLSX) {
  if (!ws || !ws["!ref"]) return { range: null, wch: [] };
  const range = XLSX.utils.decode_range(ws["!ref"]);
  const wch = [];
  for (let R = range.s.r; R <= range.e.r; R++) {
    for (let C = range.s.c; C <= range.e.c; C++) {
      const addr = XLSX.utils.encode_cell({ r: R, c: C });
      const cell = ws[addr];
      if (!cell) continue;
      const txt =
        cell.w != null
          ? String(cell.w)
          : cell.v instanceof Date
            ? "dd/mm/aaaa"
            : String(cell.v ?? "");
      const len = Math.min(64, txt.length);
      wch[C] = Math.max(wch[C] || 0, len);
    }
  }
  return { range, wch };
}

/**
 * Ajusta `!cols`: el ancho de la columna C es el máximo de C en todas las hojas.
 * @param {import('xlsx').WorkBook} wb
 * @param {typeof import('xlsx')} XLSX
 */
function ajustarAnchosColumnasWorkbook(wb, XLSX) {
  const medidas = [];
  let maxC = 0;
  for (const name of wb.SheetNames) {
    const m = medirAnchosHoja(wb.Sheets[name], XLSX);
    medidas.push({ name, m });
    if (m.range) maxC = Math.max(maxC, m.range.e.c);
  }
  const globalWch = [];
  for (let c = 0; c <= maxC; c++) {
    for (const { m } of medidas) {
      if (m.wch[c] != null) {
        globalWch[c] = Math.max(globalWch[c] || 0, m.wch[c]);
      }
    }
  }
  for (const { name, m } of medidas) {
    if (!m.range) continue;
    const ws = wb.Sheets[name];
    const cols = [];
    for (let C = m.range.s.c; C <= m.range.e.c; C++) {
      const w = globalWch[C] != null ? globalWch[C] : m.wch[C] || 8;
      cols.push({ wch: Math.min(56, w + 1.75) });
    }
    ws["!cols"] = cols;
  }
}

/**
 * @param {import('xlsx').WorkSheet} ws
 * @param {typeof import('xlsx')} XLSX
 * @param {number} filaInicio 0-based primera fila a formatear
 * @param {(r: number, c: number) => string | null} formatoCol
 */
function aplicarFormatoHoja(ws, XLSX, filaInicio, formatoCol) {
  if (!ws["!ref"]) return;
  const range = XLSX.utils.decode_range(ws["!ref"]);
  for (let R = filaInicio; R <= range.e.r; R++) {
    for (let C = range.s.c; C <= range.e.c; C++) {
      const addr = XLSX.utils.encode_cell({ r: R, c: C });
      const cell = ws[addr];
      if (!cell) continue;
      if (cell.v instanceof Date) {
        cell.t = "d";
        cell.z = FMT_DIA;
        continue;
      }
      if (typeof cell.v === "number") {
        const z = formatoCol(R, C);
        if (z) {
          cell.t = "n";
          cell.z = z;
        }
      }
    }
  }
}

/**
 * @param {object} p
 * @param {import('xlsx')} p.XLSX
 * @param {object} p.resultado
 * @param {Array} p.operaciones
 * @param {string} p.nombreBase
 * @param {"ARS" | "USD"} p.monedaFci
 */
export function generarWorkbookFciProcesado({
  XLSX,
  resultado,
  operaciones,
  nombreBase,
  monedaFci,
}) {
  const nota =
    monedaFci === "USD"
      ? "Montos en pesos: conversión con TC MEP (Bluelytics Blue). Suscripciones / lotes: MEP vendedor. Rescates: MEP comprador."
      : "Montos en pesos (sin conversión de moneda).";

  const resumen = [
    ["Análisis de FCI — PEPS (FIFO)"],
    [nota],
    [],
    ["Resultado del ejercicio", redondearA(resultado.resultadoEjercicio, 2)],
    ["Cuotas parte al cierre", redondearCuotasFci(resultado.cuotasCierre)],
    [
      "Valor unitario al cierre (costo PEPS)",
      redondearA(resultado.valorUnitarioCierre, 6),
    ],
    ["Costo remanente en cartera", redondearA(resultado.costoRemanente, 2)],
    [],
  ];

  const det = resultado.detallePepsPorLote || [];
  const cabDet = [
    "Fecha",
    "Tipo",
    "Cuotas parte",
    "Monto",
    "Costo PEPS asignado",
    "Resultado parcial",
    "Saldo cuotas parte (lote)",
  ];
  const filasDet = det.map((d) => [
    d.fecha,
    d.tipo,
    redondearCuotasFci(d.cuotasParte),
    redondearA(d.monto, 2),
    redondearA(d.costoPeps, 2),
    redondearA(d.resultadoParcial, 2),
    redondearCuotasFci(d.saldoCuotasParte),
  ]);

  const cabOps = ["Fecha", "Tipo", "Cuotas", "Monto"];
  const filasOps = operaciones.map((o) => [
    o.fecha,
    o.tipo === "suscripcion" ? "Suscripción" : "Rescate",
    redondearCuotasFci(o.cuotas),
    redondearA(o.monto, 2),
  ]);

  const pend = resultado.lotesPendientes || [];
  const cabPend = [
    "Fecha suscripción / lote",
    "Cuotas parte restantes",
    "Valor unitario (PEPS)",
    "Costo remanente",
    "Origen",
  ];
  const filasPend = pend.map((p) => [
    p.fecha,
    redondearCuotasFci(p.cuotasParte),
    redondearA(p.valorUnitario, 6),
    redondearA(p.costoRemanente, 2),
    p.origen === "inicial" ? "Lote inicial" : "Suscripción (Excel)",
  ]);

  const notaPend = [
    [],
    [
      "Usá estas filas como lotes iniciales en el próximo análisis (mismo orden: primero = más antiguo en PEPS).",
    ],
  ];

  const rdoAoA = construirHojaRdoMensual(det);

  const wb = XLSX.utils.book_new();
  const add = (aoa, name) => {
    const ws = XLSX.utils.aoa_to_sheet(aoa);
    XLSX.utils.book_append_sheet(wb, ws, name);
  };

  add(resumen, "Resumen");
  add([cabDet, ...filasDet], "Detalle PEPS");
  add(rdoAoA, "Rdo mensual");
  add(
    [
      ["Lotes pendientes sin rescatar (saldo al cierre)"],
      [],
      cabPend,
      ...filasPend,
      ...notaPend,
    ],
    "Lotes pendientes"
  );
  add([cabOps, ...filasOps], "Operaciones");

  const fmtRes = (R, c) => {
    if (c !== 1) return null;
    if (R === 3 || R === 6) return FMT_CONTABILIDAD_2;
    if (R === 4) return FMT_CONTABILIDAD_5;
    if (R === 5) return FMT_CONTABILIDAD_6;
    return FMT_CONTABILIDAD_2;
  };
  aplicarFormatoHoja(wb.Sheets["Resumen"], XLSX, 3, fmtRes);

  aplicarFormatoHoja(
    wb.Sheets["Detalle PEPS"],
    XLSX,
    1,
    (R, c) => {
      if (c === 0) return FMT_DIA;
      if (c === 1) return null;
      if (c === 2 || c === 6) return FMT_CONTABILIDAD_5;
      return FMT_CONTABILIDAD_2;
    }
  );

  aplicarFormatoHoja(
    wb.Sheets["Rdo mensual"],
    XLSX,
    1,
    (R, c) => {
      if (c === 0 || c === 1) return FMT_CONTABILIDAD_ENT;
      return FMT_CONTABILIDAD_2;
    }
  );

  aplicarFormatoHoja(
    wb.Sheets["Lotes pendientes"],
    XLSX,
    3,
    (R, c) => {
      if (c === 0) return FMT_DIA;
      if (c === 1) return FMT_CONTABILIDAD_5;
      if (c === 2) return FMT_CONTABILIDAD_6;
      if (c === 3) return FMT_CONTABILIDAD_2;
      return null;
    }
  );

  aplicarFormatoHoja(
    wb.Sheets["Operaciones"],
    XLSX,
    1,
    (R, c) => {
      if (c === 0) return FMT_DIA;
      if (c === 1) return null;
      if (c === 2) return FMT_CONTABILIDAD_5;
      return FMT_CONTABILIDAD_2;
    }
  );

  ajustarAnchosColumnasWorkbook(wb, XLSX);

  const fn = `${(nombreBase || "analisis_fci").replace(/\.[^.]+$/, "")}_procesado.xlsx`;
  XLSX.writeFile(wb, fn);
}
