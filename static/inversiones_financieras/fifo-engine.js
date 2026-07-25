/**
 * Procesamiento PEPS (FIFO) para operaciones de FCI.
 * Lotes: { qty, totalCost } — costo histórico acumulado por lote.
 */

import { redondearA, redondearCuotasFci } from "./formato-contabilidad.js";

function normalizeTipo(raw) {
  if (raw == null) return null;
  const s = String(raw).trim().toLowerCase();
  if (s.includes("suscrip")) return "suscripcion";
  if (s.includes("rescat")) return "rescate";
  return null;
}

/**
 * Normaliza cuotas según tipo: suscripción → positivo; rescate → cantidad vendida (positiva para el algoritmo).
 */
function normalizeCuotas(tipo, cuotasRaw) {
  const n = Number(cuotasRaw);
  if (!Number.isFinite(n)) return null;
  if (tipo === "suscripcion") return Math.abs(n);
  if (tipo === "rescate") {
    // Positivo o negativo en archivo: se interpreta como venta de unidades
    return Math.abs(n);
  }
  return null;
}

function normalizeMonto(montoRaw) {
  const n = Number(montoRaw);
  if (!Number.isFinite(n)) return null;
  return Math.abs(n);
}

/** Orden cronológico: fecha → suscripciones antes que rescates → secuencia en el mismo día. */
function compararOperacionesCronologico(a, b) {
  const t = a.fecha - b.fecha;
  if (t !== 0) return t;
  if (a.tipo !== b.tipo) {
    if (a.tipo === "suscripcion") return -1;
    if (b.tipo === "suscripcion") return 1;
  }
  const seqA = a.ordenInicial ?? a.filaExcel ?? 0;
  const seqB = b.ordenInicial ?? b.filaExcel ?? 0;
  return seqA - seqB;
}

function refOperacion(op) {
  if (op.origen === "inicial") {
    return `Lote inicial #${(op.ordenInicial ?? 0) + 1}`;
  }
  return `Fila ${op.filaExcel ?? "?"} (Excel)`;
}

/**
 * @param {{ lotesIniciales: Array<{ fecha: Date, cuotas: number, valorUnitario: number }> }} inicial
 * @param {Array<{ fecha: Date, tipo: string, cuotas: number, monto: number }>} operaciones — Excel u otras fuentes
 */
export function procesarPEPS(inicial, operaciones) {
  /** Cola PEPS: { lotId, qty, totalCost } */
  const lots = [];
  /** lotId -> metadatos al crear el lote */
  const lotMetaById = new Map();
  /** lotId -> fracciones de rescates que consumen ese lote (orden cronológico al agregar) */
  const rescatesPorLote = new Map();

  let nextLotId = 0;

  function crearLote(qty, totalCost, meta) {
    const lotId = nextLotId++;
    lots.push({ lotId, qty, totalCost });
    lotMetaById.set(lotId, {
      ...meta,
      cuotasInicial: qty,
      costoInicial: totalCost,
    });
    return lotId;
  }

  const lotesIni = Array.isArray(inicial?.lotesIniciales)
    ? inicial.lotesIniciales
    : [];
  const eventos = [];

  for (let i = 0; i < lotesIni.length; i++) {
    const li = lotesIni[i];
    const cuotas = redondearCuotasFci(Number(li.cuotas));
    const vu = redondearA(Number(li.valorUnitario), 6);
    if (!Number.isFinite(cuotas) || cuotas <= 0) continue;
    if (!Number.isFinite(vu) || vu < 0) {
      throw new Error(
        `Lote inicial #${i + 1}: valor unitario inválido (debe ser ≥ 0).`
      );
    }
    const fd = li.fecha;
    if (!fd || !(fd instanceof Date) || Number.isNaN(fd.getTime())) {
      throw new Error(`Lote inicial #${i + 1}: fecha inválida.`);
    }
    const montoLote = redondearA(cuotas * vu, 2);
    eventos.push({
      fecha: fd,
      tipo: "suscripcion",
      cuotas,
      monto: montoLote,
      origen: "inicial",
      filaExcel: null,
      ordenInicial: i,
    });
  }

  for (let i = 0; i < operaciones.length; i++) {
    const op = operaciones[i];
    eventos.push({
      ...op,
      origen: op.origen ?? "suscripcion",
      ordenInicial: op.ordenInicial ?? null,
    });
  }

  eventos.sort(compararOperacionesCronologico);

  let resultadoEjercicio = 0;

  for (let i = 0; i < eventos.length; i++) {
    const op = eventos[i];
    const ref = refOperacion(op);

    if (op.tipo === "suscripcion") {
      const qty = redondearCuotasFci(op.cuotas);
      const monto = redondearA(op.monto, 2);
      if (qty <= 0) {
        throw new Error(`${ref}: suscripción con cuotas inválidas.`);
      }
      if (monto < 0) {
        throw new Error(`${ref}: suscripción con monto inválido.`);
      }
      crearLote(qty, monto, {
        fecha: op.fecha,
        origen: op.origen === "inicial" ? "inicial" : "suscripcion",
        filaExcel: op.filaExcel ?? null,
        ordenInicial: op.ordenInicial ?? null,
      });
      continue;
    }

    if (op.tipo === "rescate") {
      const qtyToSell = redondearCuotasFci(op.cuotas);
      const proceeds = redondearA(op.monto, 2);
      if (qtyToSell <= 0) {
        throw new Error(`${ref}: rescate con cuotas inválidas.`);
      }

      let remaining = redondearCuotasFci(qtyToSell);

      while (redondearCuotasFci(remaining) > 0 && lots.length > 0) {
        const lot = lots[0];
        const take = redondearCuotasFci(Math.min(lot.qty, remaining));
        if (take <= 0) {
          if (redondearCuotasFci(lot.qty) <= 0) lots.shift();
          else break;
          continue;
        }
        const costFromLot = redondearA(lot.totalCost * (take / lot.qty), 2);
        const proceedsChunk = redondearA(proceeds * (take / qtyToSell), 2);
        const realizadoChunk = redondearA(proceedsChunk - costFromLot, 2);

        resultadoEjercicio = redondearA(resultadoEjercicio + realizadoChunk, 2);

        lot.qty = redondearCuotasFci(lot.qty - take);
        lot.totalCost = redondearA(lot.totalCost - costFromLot, 2);
        const saldoLote = redondearCuotasFci(lot.qty);

        if (!rescatesPorLote.has(lot.lotId)) rescatesPorLote.set(lot.lotId, []);
        rescatesPorLote.get(lot.lotId).push({
          fecha: op.fecha,
          filaExcel: op.filaExcel ?? null,
          cuotasParte: take,
          monto: proceedsChunk,
          costoPeps: costFromLot,
          resultadoParcial: realizadoChunk,
          saldoCuotasParte: saldoLote,
        });

        remaining = redondearCuotasFci(remaining - take);
        if (redondearCuotasFci(lot.qty) <= 0) lots.shift();
      }

      if (redondearCuotasFci(remaining) > 0) {
        throw new Error(
          `${ref}: rescate de ${qtyToSell} cuotas supera las cuotas partes disponibles hasta esa fecha (PEPS). Revisá el saldo previo y las suscripciones anteriores.`
        );
      }
    }
  }

  const cuotasCierre = redondearCuotasFci(
    lots.reduce((s, l) => s + l.qty, 0)
  );
  const costoCierre = redondearA(
    lots.reduce((s, l) => s + l.totalCost, 0),
    2
  );
  const valorUnitarioCierre =
    cuotasCierre > 0 ? redondearA(costoCierre / cuotasCierre, 6) : 0;

  const detallePepsPorLote = construirDetallePepsPorLote(
    lotMetaById,
    rescatesPorLote
  );

  const lotesPendientes = construirLotesPendientes(lots, lotMetaById);

  return {
    resultadoEjercicio: redondearA(resultadoEjercicio, 2),
    cuotasCierre,
    valorUnitarioCierre,
    costoRemanente: costoCierre,
    detallePepsPorLote,
    lotesPendientes,
    lots,
  };
}

/**
 * Lotes con saldo al cierre (orden PEPS), para exportar como próximos lotes iniciales.
 */
function construirLotesPendientes(lotsCola, lotMetaById) {
  return lotsCola.map((l) => {
    const meta = lotMetaById.get(l.lotId);
    const q = redondearCuotasFci(l.qty);
    const tr = redondearA(l.totalCost, 2);
    const vu = q > 0 ? redondearA(tr / q, 6) : 0;
    return {
      fecha: meta?.fecha ?? null,
      cuotasParte: q,
      valorUnitario: vu,
      costoRemanente: tr,
      origen: meta?.origen ?? "suscripcion",
    };
  });
}

/**
 * Orden: por cada lote en orden de creación (PEPS), fila de alta del lote y debajo los rescates que consumen ese lote.
 */
function construirDetallePepsPorLote(lotMetaById, rescatesPorLote) {
  const ids = [...lotMetaById.keys()].sort((a, b) => a - b);
  const filas = [];

  for (const lotId of ids) {
    const meta = lotMetaById.get(lotId);
    const esInicial = meta.origen === "inicial";
    filas.push({
      fecha: meta.fecha,
      tipo: esInicial ? "Lote inicial" : "Suscripción",
      cuotasParte: redondearCuotasFci(meta.cuotasInicial),
      monto: meta.costoInicial,
      costoPeps: meta.costoInicial,
      resultadoParcial: 0,
      saldoCuotasParte: redondearCuotasFci(meta.cuotasInicial),
    });

    const chunks = rescatesPorLote.get(lotId);
    if (!chunks?.length) continue;

    chunks.sort((a, b) => {
      const t = a.fecha - b.fecha;
      if (t !== 0) return t;
      return (a.filaExcel ?? 0) - (b.filaExcel ?? 0);
    });

    for (const ch of chunks) {
    filas.push({
      fecha: ch.fecha,
      tipo: "Rescate",
      cuotasParte: redondearCuotasFci(ch.cuotasParte),
      monto: ch.monto,
      costoPeps: ch.costoPeps,
      resultadoParcial: ch.resultadoParcial,
      saldoCuotasParte: redondearCuotasFci(ch.saldoCuotasParte),
    });
    }
  }

  return filas;
}

/**
 * Convierte filas del Excel en operaciones ordenadas.
 * Requiere encabezados con columna fecha, operación/concepto y monto; cuotaparte es opcional
 * (si no hay columna reconocida, se usa el monto como cantidad para PEPS).
 */
function parseNumAR(v) {
  if (v === null || v === undefined) return null;
  if (typeof v === "number" && Number.isFinite(v)) return v;
  const s = String(v).trim();
  if (s === "") return null;
  let t = s.replace(/\s/g, "");
  if (t.includes(",") && t.includes(".")) {
    const li = t.lastIndexOf(",");
    const ld = t.lastIndexOf(".");
    if (li > ld) t = t.replace(/\./g, "").replace(",", ".");
    else t = t.replace(/,/g, "");
  } else if (t.includes(",")) t = t.replace(",", ".");
  const n = parseFloat(t);
  return Number.isFinite(n) ? n : null;
}

function normalizarEncabezado(s) {
  return String(s ?? "")
    .trim()
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/\s+/g, " ");
}

/**
 * @param {string[]} headers
 * @returns {{ fecha: number, tipo: number, monto: number, cuotas: number | null, cuotasOpcional: boolean, etiquetas: Record<string, string> }}
 */
export function resolverColumnasFci(headers) {
  const hArr = Array.isArray(headers) ? headers : [];
  const norm = hArr.map((h) => normalizarEncabezado(h));
  const usado = new Set();

  function primeraCoincidencia(patrones) {
    for (const re of patrones) {
      for (let i = 0; i < norm.length; i++) {
        if (usado.has(i)) continue;
        if (re.test(norm[i])) return i;
      }
    }
    return null;
  }

  /* Cuotas antes que monto por si el título incluye "valor" ligado a cuotapartes. */
  const idxCuotas = primeraCoincidencia([
    /cuotapartes?/,
    /cuotas?\s+parte/,
    /cuota\s+parte/,
    /^cuotas$/,
    /cantidad\s+(de\s+)?cuotas/,
    /nro\.?\s*cuotas/,
    /^qty$/,
    /^unidades$/,
  ]);
  if (idxCuotas != null) usado.add(idxCuotas);

  const idxFecha = primeraCoincidencia([
    /^fecha$/,
    /^fecha\b/,
    /fecha\s+(de\s+)?(oper|mov|liq|liquid)/,
    /^f\.\s*oper/,
    /^date$/,
    /^fecha\s+valor$/,
  ]);
  if (idxFecha != null) usado.add(idxFecha);

  const idxTipo = primeraCoincidencia([
    /^operacion(es)?$/,
    /^tipo$/,
    /tipo\s+(de\s+)?oper/,
    /^concepto$/,
    /^movimiento$/,
    /^descripcion$/,
    /^detalle$/,
    /^naturaleza$/,
    /^type$/,
  ]);
  if (idxTipo != null) usado.add(idxTipo);

  const idxMonto = primeraCoincidencia([
    /\bimporte\b/,
    /\bmonto\b/,
    /\bpesos\b/,
    /\bARS\b/i,
    /^valor$/,
    /\bneto\b/,
    /total\s+(ARS|peso)/,
  ]);
  if (idxMonto != null) usado.add(idxMonto);

  const soloPosicion =
    norm.length > 0 &&
    norm.every((n) => n === "" || /^__col\d+$/.test(n));

  if (soloPosicion && norm.length >= 4) {
    return {
      fecha: 0,
      tipo: 1,
      cuotas: 2,
      monto: 3,
      cuotasOpcional: false,
      etiquetas: {
        fecha: String(headers[0] ?? "A"),
        tipo: String(headers[1] ?? "B"),
        cuotas: String(headers[2] ?? "C"),
        monto: String(headers[3] ?? "D"),
      },
    };
  }

  const etiquetas = {
    fecha: idxFecha != null ? String(headers[idxFecha] ?? "").trim() : "",
    tipo: idxTipo != null ? String(headers[idxTipo] ?? "").trim() : "",
    monto: idxMonto != null ? String(headers[idxMonto] ?? "").trim() : "",
    cuotas:
      idxCuotas != null ? String(headers[idxCuotas] ?? "").trim() : null,
  };

  return {
    fecha: idxFecha,
    tipo: idxTipo,
    monto: idxMonto,
    cuotas: idxCuotas,
    cuotasOpcional: idxCuotas == null,
    etiquetas,
  };
}

/**
 * @param {{ headers: string[], rows: any[][] }} tabla
 */
export function parsearFilasExcel(tabla) {
  const { headers, rows } = tabla;
  const filas = Array.isArray(rows) ? rows : [];
  const mapa = resolverColumnasFci(headers);

  if (mapa.fecha == null || mapa.tipo == null || mapa.monto == null) {
    const titulos = (headers ?? [])
      .map((h, i) => (String(h ?? "").trim() ? `"${h}"` : `(col ${i + 1})`))
      .join(", ");
    throw new Error(
      "No se pudieron detectar columnas obligatorias (fecha, operación y monto). " +
        `Encabezados en la fila 1: ${titulos || "(vacío)"}. ` +
        "Usá títulos reconocibles, p. ej. Fecha, Operación o Concepto, Importe o Monto."
    );
  }

  const ops = [];
  const tagFecha = mapa.etiquetas.fecha || "fecha";
  const tagTipo = mapa.etiquetas.tipo || "operación";
  const tagMonto = mapa.etiquetas.monto || "monto";
  const tagCuotas = mapa.etiquetas.cuotas;

  for (let r = 0; r < filas.length; r++) {
    const row = filas[r];
    const get = (ix) => (ix == null ? undefined : row?.[ix]);
    const fechaRaw = get(mapa.fecha);
    const tipoRaw = get(mapa.tipo);
    const montoRaw = parseNumAR(get(mapa.monto));
    const cuotasPars = parseNumAR(get(mapa.cuotas));

    if (
      fechaRaw === undefined ||
      fechaRaw === null ||
      String(fechaRaw).trim() === ""
    ) {
      continue;
    }

    const tipo = normalizeTipo(tipoRaw);
    if (!tipo) {
      throw new Error(
        `Fila ${r + 2}: tipo de operación no reconocido (columna «${tagTipo}»). ` +
          "Tiene que indicarse suscripción o rescate."
      );
    }

    const fecha = excelDateToDate(fechaRaw);
    if (!fecha || Number.isNaN(fecha.getTime())) {
      throw new Error(
        `Fila ${r + 2}: fecha inválida (columna «${tagFecha}»).`
      );
    }

    const montoN = normalizeMonto(montoRaw);
    if (montoN == null || montoN < 0) {
      throw new Error(
        `Fila ${r + 2}: monto inválido (columna «${tagMonto}»).`
      );
    }

    const baseCuotas =
      cuotasPars != null && Number.isFinite(cuotasPars)
        ? cuotasPars
        : montoN;
    const cuotasN = normalizeCuotas(tipo, baseCuotas);
    if (cuotasN == null || cuotasN <= 0) {
      const ref = tagCuotas ? `columna «${tagCuotas}»` : "monto (sin columna de cuotas)";
      throw new Error(
        `Fila ${r + 2}: cantidad de cuotas inválida (${ref}).`
      );
    }

    const cuotasR = redondearCuotasFci(cuotasN);
    const montoR = redondearA(montoN, 2);
    ops.push({ fecha, tipo, cuotas: cuotasR, monto: montoR, filaExcel: r + 2 });
  }

  ops.sort(compararOperacionesCronologico);
  return ops;
}

function excelUtcMedianocheACalendarioLocal(d) {
  return new Date(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate());
}

function excelDateToDate(v) {
  if (v instanceof Date && !Number.isNaN(v.getTime())) {
    const d = v;
    /* Día calendario local: evita desfasajes UTC vs hoja o serial Excel. */
    return new Date(d.getFullYear(), d.getMonth(), d.getDate());
  }
  if (typeof v === "number" && v > 20000 && v < 60000) {
    const diaEntero = Math.floor(v);
    const utc = Math.round((diaEntero - 25569) * 86400 * 1000);
    return excelUtcMedianocheACalendarioLocal(new Date(utc));
  }
  const s = String(v).trim();
  if (s === "") return null;
  const isoYmd = s.match(/^(\d{4})[\/\-](\d{1,2})[\/\-](\d{1,2})(?:[T\s].*)?$/);
  if (isoYmd) {
    const y = parseInt(isoYmd[1], 10);
    const mo = parseInt(isoYmd[2], 10);
    const d = parseInt(isoYmd[3], 10);
    if (y >= 1900 && y <= 2100 && mo >= 1 && mo <= 12 && d >= 1 && d <= 31) {
      return new Date(y, mo - 1, d);
    }
  }
  const m = s.match(/^(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{2,4})/);
  if (m) {
    const a = parseInt(m[1], 10);
    const b = parseInt(m[2], 10);
    let y = parseInt(m[3], 10);
    if (y < 100) y += 2000;
    let day;
    let mo;
    if (a > 12) {
      /* D/M/Y (p. ej. 28/3/25) */
      day = a;
      mo = b;
    } else if (b > 12) {
      /* M/D/Y — export habitual de Excel en inglés (p. ej. 3/28/25) */
      mo = a;
      day = b;
    } else {
      /* Ambiguo (p. ej. 4/1/25): convención Argentina día/mes/año */
      day = a;
      mo = b;
    }
    if (y >= 1900 && y <= 2100 && mo >= 1 && mo <= 12 && day >= 1 && day <= 31) {
      return new Date(y, mo - 1, day);
    }
  }
  const parsed = new Date(s);
  if (!Number.isNaN(parsed.getTime())) {
    return new Date(
      parsed.getFullYear(),
      parsed.getMonth(),
      parsed.getDate()
    );
  }
  return null;
}

export { normalizeTipo, normalizeCuotas };
