import { procesarPEPS, parsearFilasExcel } from "./fifo-engine.js";
import { fmtContabilidad } from "./formato-contabilidad.js";
import { redondearA } from "./formato-contabilidad.js";
import { fechaIsoLocal } from "./cc-fx.js";
import { obtenerCotizacionesPorFechas } from "./cc-fx-rates.js";
import { generarWorkbookFciProcesado, construirHojaRdoMensual } from "./fci-excel.js";

const $ = (id) => document.getElementById(id);

let ultimoResultado = null;
let ultimoNombreArchivo = "analisis_fci_procesado.xlsx";
let ultimasFilasExcel = null;
/** @type {"ARS" | "USD"} */
let ultimaMonedaFci = "ARS";

function fmtFecha(d) {
  if (d == null) return "—";
  if (!(d instanceof Date) || Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString("es-AR");
}

function parseNumLocal(v) {
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

function leerMonedaFci() {
  const v = $("fciMonedaFondo")?.value;
  return v === "USD" ? "USD" : "ARS";
}

/**
 * Lotes iniciales y operaciones en USD → montos/PU en ARS (TC MEP por fecha).
 * Suscripción / lote: MEP vendedor. Rescate: MEP comprador.
 */
async function convertirFciUsdAArs(lotesIniciales, operaciones) {
  const set = new Set();
  for (const o of operaciones) {
    set.add(fechaIsoLocal(o.fecha));
  }
  for (const l of lotesIniciales) {
    set.add(fechaIsoLocal(l.fecha));
  }
  const fechas = [...set];
  if (fechas.length === 0) {
    return { lotes: lotesIniciales, operaciones };
  }
  const mapa = await obtenerCotizacionesPorFechas(fechas);
  const lotesN = lotesIniciales.map((l) => {
    const iso = fechaIsoLocal(l.fecha);
    const c = mapa.get(iso);
    if (!c) {
      throw new Error(
        `No hay TC MEP (vendedor) para la fecha del lote inicial (${iso}).`
      );
    }
    return {
      ...l,
      valorUnitario: redondearA(l.valorUnitario * c.mepVendedor, 6),
    };
  });
  const opsN = operaciones.map((o) => {
    const iso = fechaIsoLocal(o.fecha);
    const c = mapa.get(iso);
    if (!c) {
      throw new Error(
        `No hay TC MEP para la operación con fecha ${iso} (fila en Excel con esa fecha).`
      );
    }
    const mult = o.tipo === "suscripcion" ? c.mepVendedor : c.mepComprador;
    return { ...o, monto: redondearA(o.monto * mult, 2) };
  });
  return { lotes: lotesN, operaciones: opsN };
}

function actualizarHintMonedaFci() {
  const h = $("fciMonedaHint");
  if (h) h.hidden = leerMonedaFci() !== "USD";
}

function crearFilaLoteInicial() {
  const wrap = document.createElement("div");
  wrap.className = "lote-inicial-row";
  wrap.innerHTML = `
    <div class="field">
      <label>Fecha</label>
      <input type="date" data-field="fecha" />
    </div>
    <div class="field">
      <label>Cuotas parte</label>
      <input type="number" data-field="cuotas" inputmode="decimal" min="0" step="any" placeholder="0" />
    </div>
    <div class="field">
      <label>Valor unitario (moneda del selector «Archivo»)</label>
      <input type="number" data-field="vu" inputmode="decimal" min="0" step="any" placeholder="0" />
    </div>
    <div class="lote-remove-wrap">
      <button type="button" class="btn-remove-lote" title="Quitar lote" data-action="remove-lote">×</button>
    </div>
  `;
  return wrap;
}

function contarFilasLotes() {
  return document.querySelectorAll("#lotesInicialesContainer .lote-inicial-row")
    .length;
}

function agregarFilaLoteInicial() {
  const c = $("lotesInicialesContainer");
  if (!c) return;
  c.appendChild(crearFilaLoteInicial());
}

function initLotesIniciales() {
  const c = $("lotesInicialesContainer");
  if (!c) return;
  if (contarFilasLotes() === 0) {
    agregarFilaLoteInicial();
  }
}

function leerLotesIniciales() {
  const rows = document.querySelectorAll(
    "#lotesInicialesContainer .lote-inicial-row"
  );
  const lotes = [];
  for (let i = 0; i < rows.length; i++) {
    const row = rows[i];
    const fechaVal = row.querySelector('[data-field="fecha"]')?.value?.trim();
    const cuotas = parseNumLocal(row.querySelector('[data-field="cuotas"]')?.value);
    const vu = parseNumLocal(row.querySelector('[data-field="vu"]')?.value);

    const vacio =
      !fechaVal &&
      (cuotas == null || cuotas <= 0) &&
      (vu == null || vu <= 0);
    if (vacio) continue;

    const n = i + 1;
    if (!fechaVal) {
      throw new Error(`Lote inicial #${n}: indicá la fecha o vaciá la fila.`);
    }
    if (cuotas == null || cuotas <= 0) {
      throw new Error(`Lote inicial #${n}: cuotas parte debe ser mayor que 0.`);
    }
    if (vu == null || vu < 0) {
      throw new Error(`Lote inicial #${n}: valor unitario inválido (≥ 0).`);
    }
    const d = new Date(`${fechaVal}T12:00:00`);
    if (Number.isNaN(d.getTime())) {
      throw new Error(`Lote inicial #${n}: fecha inválida.`);
    }
    lotes.push({ fecha: d, cuotas, valorUnitario: vu });
  }
  return lotes;
}

function mostrarError(msg) {
  const el = $("errMsg");
  el.textContent = msg;
  el.hidden = !msg;
}

function ocultarPanelesResultado() {
  if ($("panelResultados")) $("panelResultados").hidden = true;
  if ($("panelRdoMensual")) $("panelRdoMensual").hidden = true;
  if ($("panelLotesPendientes")) $("panelLotesPendientes").hidden = true;
}

function leerExcelDesdeBuffer(data) {
  const XLSX = window.XLSX;
  if (!XLSX) throw new Error("No se cargó la librería XLSX.");

  const wb = XLSX.read(data, { type: "array", cellDates: true });
  const name = wb.SheetNames[0];
  if (!name) throw new Error("El archivo no tiene hojas.");

  const ws = wb.Sheets[name];
  /* raw: true — fechas y números nativos de la celda. raw:false devuelve
   * strings según locale de Excel (p. ej. 3/28/25) y rompe el orden PEPS
   * al parsearlos como D/M/Y. */
  const all = XLSX.utils.sheet_to_json(ws, {
    header: 1,
    defval: "",
    raw: true,
  });
  if (!all.length) return { headers: [], rows: [] };

  const rawHeaders = all[0].map((h) => String(h ?? "").trim());
  const dataRows = all.slice(1);
  const headersVacios = rawHeaders.every((h) => h === "");
  const maxCol = Math.max(
    rawHeaders.length,
    ...dataRows.map((r) => (Array.isArray(r) ? r.length : 0)),
    4
  );
  const headers = headersVacios
    ? Array.from({ length: maxCol }, (_, i) => `__col${i + 1}`)
    : rawHeaders;
  return { headers, rows: dataRows };
}

function exportarExcel() {
  if (!ultimoResultado) return;
  const XLSX = window.XLSX;
  if (!XLSX) {
    mostrarError("No se cargó la librería XLSX.");
    return;
  }
  const mon = ultimoResultado.monedaFci ?? leerMonedaFci();
  generarWorkbookFciProcesado({
    XLSX,
    resultado: ultimoResultado.resultado,
    operaciones: ultimoResultado.operaciones,
    nombreBase: ultimoNombreArchivo,
    monedaFci: mon,
  });
}

async function ejecutarAnalisis(filasExcel) {
  mostrarError("");

  const monedaFci = leerMonedaFci();
  ultimaMonedaFci = monedaFci;

  let lotesIniciales;
  try {
    lotesIniciales = leerLotesIniciales();
  } catch (e) {
    mostrarError(e.message || String(e));
    ocultarPanelesResultado();
    return;
  }

  let operaciones;
  try {
    operaciones = parsearFilasExcel(filasExcel);
  } catch (e) {
    mostrarError(e.message || String(e));
    ocultarPanelesResultado();
    return;
  }

  if (operaciones.length === 0) {
    mostrarError("No hay filas de datos válidas (desde la fila 2 del Excel).");
    return;
  }

  ultimasFilasExcel = filasExcel;

  if (monedaFci === "USD") {
    mostrarError("Obteniendo TC MEP por fecha de operación…");
    const btnE = $("btnExportar");
    const prev = btnE?.disabled;
    if (btnE) btnE.disabled = true;
    try {
      const conv = await convertirFciUsdAArs(lotesIniciales, operaciones);
      lotesIniciales = conv.lotes;
      operaciones = conv.operaciones;
    } catch (e) {
      mostrarError(e.message || String(e));
      ocultarPanelesResultado();
      if (btnE) btnE.disabled = prev;
      return;
    }
    mostrarError("");
    if (btnE) btnE.disabled = false;
  }

  let resultado;
  try {
    resultado = procesarPEPS({ lotesIniciales }, operaciones);
  } catch (e) {
    mostrarError(e.message || String(e));
    ocultarPanelesResultado();
    return;
  }

  ultimoResultado = { resultado, operaciones, monedaFci };

  $("resEjercicio").textContent = fmtContabilidad(resultado.resultadoEjercicio, 2);
  $("resEjercicio").className =
    resultado.resultadoEjercicio >= 0 ? "valor ok" : "valor loss";

  $("resCuotas").textContent = fmtContabilidad(resultado.cuotasCierre, 5);
  $("resVU").textContent = fmtContabilidad(resultado.valorUnitarioCierre, 6);

  $("panelResultados").hidden = false;
  $("btnExportar").disabled = false;
  renderRdoMensual(resultado);
  renderLotesPendientes(resultado);
}

function renderTablaSimple(containerId, emptyId, cabeceras, filas, renderFila) {
  const tbody = $(containerId);
  const empty = $(emptyId);
  if (!tbody) return;
  tbody.innerHTML = "";
  if (!filas.length) {
    if (empty) empty.hidden = false;
    return;
  }
  if (empty) empty.hidden = true;
  for (const fila of filas) {
    const tr = document.createElement("tr");
    tr.innerHTML = renderFila(fila);
    tbody.appendChild(tr);
  }
}

function renderRdoMensual(resultado) {
  const panel = $("panelRdoMensual");
  const aoa = construirHojaRdoMensual(resultado.detallePepsPorLote || []);
  const filas = aoa.length > 1 ? aoa.slice(1) : [];
  if (panel) panel.hidden = false;
  renderTablaSimple(
    "tablaRdoMensual",
    "rdoMensualVacio",
    ["Año", "Mes", "Resultado"],
    filas,
    ([yy, mm, val]) =>
      `<td>${yy}</td><td>${mm}</td><td class="num">${fmtContabilidad(val, 2)}</td>`
  );
}

function renderLotesPendientes(resultado) {
  const panel = $("panelLotesPendientes");
  const pend = resultado.lotesPendientes || [];
  if (panel) panel.hidden = false;
  renderTablaSimple(
    "tablaLotesPendientes",
    "lotesPendientesVacio",
    ["Fecha", "Cuotas", "Valor unitario", "Costo", "Origen"],
    pend,
    (p) => {
      const origen =
        p.origen === "inicial" ? "Lote inicial" : "Suscripción (Excel)";
      return `<td>${fmtFecha(p.fecha)}</td>
        <td class="num">${fmtContabilidad(p.cuotasParte, 5)}</td>
        <td class="num">${fmtContabilidad(p.valorUnitario, 6)}</td>
        <td class="num">${fmtContabilidad(p.costoRemanente, 2)}</td>
        <td>${origen}</td>`;
    }
  );
}

async function reintentarSiHayDatos() {
  if (ultimasFilasExcel != null) {
    await ejecutarAnalisis(ultimasFilasExcel);
  }
}

function iniciarFciUi() {
  try {
    initLotesIniciales();
    actualizarHintMonedaFci();
  } catch (e) {
    mostrarError(`No se pudo inicializar la pantalla FCI: ${e.message || e}`);
    return;
  }

  $("btnImportar")?.addEventListener("click", () => {
    $("fileInput")?.click();
  });

  $("fileInput")?.addEventListener("change", async (ev) => {
    const file = ev.target.files?.[0];
    ev.target.value = "";
    if (!file) return;

    ultimoNombreArchivo = file.name || "analisis_fci.xlsx";

    try {
      const buf = await file.arrayBuffer();
      const filas = leerExcelDesdeBuffer(buf);
      await ejecutarAnalisis(filas);
    } catch (e) {
      mostrarError(e.message || String(e));
      ocultarPanelesResultado();
      if ($("btnExportar")) $("btnExportar").disabled = true;
    }
  });

  $("btnExportar")?.addEventListener("click", () => {
    if (!ultimoResultado) return;
    exportarExcel();
  });

  $("btnAgregarLoteInicial")?.addEventListener("click", () => {
    agregarFilaLoteInicial();
  });

  $("fciMonedaFondo")?.addEventListener("change", () => {
    actualizarHintMonedaFci();
    if (ultimasFilasExcel != null) {
      void reintentarSiHayDatos();
    }
  });

  $("lotesInicialesContainer")?.addEventListener("click", (ev) => {
    const btn = ev.target.closest("[data-action=remove-lote]");
    if (!btn) return;
    const row = btn.closest(".lote-inicial-row");
    if (!row) return;
    if (contarFilasLotes() <= 1) {
      row.querySelectorAll("input").forEach((inp) => {
        inp.value = "";
      });
      return;
    }
    row.remove();
  });

  $("lotesInicialesContainer")?.addEventListener("change", reintentarSiHayDatos);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", iniciarFciUi);
} else {
  iniciarFciUi();
}
