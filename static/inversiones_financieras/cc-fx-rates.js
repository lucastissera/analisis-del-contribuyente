/**
 * Cotizaciones históricas: Bluelytics evolution.json
 * - Oficial → BNA (comprador = value_buy, vendedor = value_sell)
 * - Blue → proxy MEP / AL30C (comprador/vendedor) por fecha de operación
 */

const EVOLUTION_URL = "https://api.bluelytics.com.ar/v2/evolution.json";

/**
 * @param {Set<string>|Iterable<string>} fechasIso fechas YYYY-MM-DD necesarias
 * @returns {Promise<Map<string, { bnaComprador: number, bnaVendedor: number, al30cComprador: number, al30cVendedor: number }>>}
 */
export async function obtenerCotizacionesPorFechas(fechasIso) {
  const fechas = [...new Set(fechasIso)].filter(Boolean).sort();
  if (fechas.length === 0) {
    return new Map();
  }

  const res = await fetch(EVOLUTION_URL);
  if (!res.ok) {
    throw new Error(
      `No se pudo descargar cotizaciones (${res.status}). Comprobá la conexión.`
    );
  }
  const evo = await res.json();
  if (!Array.isArray(evo)) {
    throw new Error("Respuesta de cotizaciones inválida.");
  }

  /** @type {Map<string, { bnaComprador?: number, bnaVendedor?: number, al30cComprador?: number, al30cVendedor?: number }>} */
  const porDia = new Map();

  for (const row of evo) {
    const d = row.date;
    if (!d) continue;
    if (!porDia.has(d)) porDia.set(d, {});
    const o = porDia.get(d);
    if (row.source === "Oficial") {
      o.bnaComprador = Number(row.value_buy);
      o.bnaVendedor = Number(row.value_sell);
    }
    if (row.source === "Blue") {
      o.al30cComprador = Number(row.value_buy);
      o.al30cVendedor = Number(row.value_sell);
    }
  }

  const todasLasFechas = [...porDia.keys()].sort();
  if (todasLasFechas.length === 0) {
    throw new Error("No hay datos de cotización en la fuente.");
  }

  function rellenarAl30DesdeBna(o) {
    if (
      o.al30cComprador == null &&
      o.bnaComprador != null &&
      Number.isFinite(o.bnaComprador)
    ) {
      o.al30cComprador = o.bnaComprador;
      o.al30cVendedor = o.bnaVendedor;
    }
  }

  for (const o of porDia.values()) {
    rellenarAl30DesdeBna(o);
  }

  const indicePorFecha = new Map();
  for (let i = 0; i < todasLasFechas.length; i++) {
    indicePorFecha.set(todasLasFechas[i], i);
  }

  function cotizacionParaFecha(iso) {
    if (porDia.has(iso)) {
      const o = { ...porDia.get(iso) };
      rellenarAl30DesdeBna(o);
      if (
        o.bnaComprador != null &&
        o.bnaVendedor != null &&
        o.al30cComprador != null &&
        o.al30cVendedor != null
      ) {
        return o;
      }
    }
    const idx = indicePorFecha.has(iso)
      ? indicePorFecha.get(iso)
      : -1;
    let usar = idx >= 0 ? idx : -1;
    if (usar < 0) {
      for (let i = todasLasFechas.length - 1; i >= 0; i--) {
        if (todasLasFechas[i] < iso) {
          usar = i;
          break;
        }
      }
    }
    if (usar < 0) usar = 0;
    const fechaRef = todasLasFechas[usar];
    const o = { ...porDia.get(fechaRef) };
    rellenarAl30DesdeBna(o);
    return o;
  }

  const resultado = new Map();
  for (const iso of fechas) {
    const o = cotizacionParaFecha(iso);
    const bnaC = o.bnaComprador;
    const bnaV = o.bnaVendedor;
    const aC = o.al30cComprador ?? bnaC;
    const aV = o.al30cVendedor ?? bnaV;
    if (
      ![bnaC, bnaV, aC, aV].every((x) => x != null && Number.isFinite(x) && x > 0)
    ) {
      throw new Error(
        `Cotización incompleta para ${iso} (BNA/AL30C). Probá otra fecha o revisá la fuente.`
      );
    }
    resultado.set(iso, {
      bnaComprador: bnaC,
      bnaVendedor: bnaV,
      al30cComprador: aC,
      al30cVendedor: aV,
      mepComprador: aC,
      mepVendedor: aV,
    });
  }

  return resultado;
}
