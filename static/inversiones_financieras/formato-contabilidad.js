/**
 * @param {number} n
 * @param {number} dec
 * @returns {number}
 */
export function redondearA(n, dec) {
  if (n == null || !Number.isFinite(n)) return n;
  const f = 10 ** dec;
  return Math.round(n * f) / f;
}

/** Cuotas parte FCI: 5 decimales (redondeo estándar para PEPS). */
export const DECIMALES_CUOTAS_FCI = 5;

/** Redondeo estándar para cuotas FCI (evita error numérico en PEPS). */
export function redondearCuotasFci(n) {
  return redondearA(n, DECIMALES_CUOTAS_FCI);
}

/**
 * Formato contabilidad es-AR: miles con punto, decimales con coma, negativos entre paréntesis.
 * Usar para montos, precios y cantidades en pantalla y en Excel exportado (como texto en celda).
 * @param {number} n
 * @param {number} [dec=2]
 * @returns {string}
 */
export function fmtContabilidad(n, dec = 2) {
  if (n == null || !Number.isFinite(n)) return "—";
  const neg = n < 0;
  const abs = Math.abs(n);
  const body = abs.toLocaleString("es-AR", {
    minimumFractionDigits: dec,
    maximumFractionDigits: dec,
  });
  return neg ? `(${body})` : body;
}

/**
 * Cantidades de títulos (hasta 6 decimales); mismas reglas de signo.
 * @param {number} n
 * @returns {string}
 */
export function fmtCantidadActivos(n) {
  if (n == null || !Number.isFinite(n)) return "—";
  const neg = n < 0;
  const abs = Math.abs(n);
  const body = abs.toLocaleString("es-AR", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 6,
  });
  return neg ? `(${body})` : body;
}

/** Celda Excel: vacío si no hay número (evita "—" en export). */
export function celdaMontoExcel(n, dec = 2) {
  if (n == null || !Number.isFinite(n)) return "";
  return fmtContabilidad(n, dec);
}

/** Precio unitario (más decimales habituales en operaciones). */
export function celdaPrecioExcel(n, dec = 4) {
  return celdaMontoExcel(n, dec);
}

/** Nominales / cantidad: mismo criterio contable que fmtContabilidad, hasta 6 decimales. */
export function celdaCantidadExcel(n) {
  if (n == null || !Number.isFinite(n)) return "";
  return fmtCantidadActivos(n);
}
