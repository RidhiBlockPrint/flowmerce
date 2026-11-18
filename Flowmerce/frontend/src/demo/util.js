/** Small helpers shared by the demo data modules. Everything here is synthetic and runs in the browser only. */

/** Seeded random generator, so the demo shows the same figures on every load. */
export function rng(seed = 1) {
  let s = seed >>> 0;
  return () => {
    s = (Math.imul(s, 1664525) + 1013904223) >>> 0;
    return s / 4294967296;
  };
}

const HOUR = 3600 * 1000;
/** ISO timestamp `h` hours ago (negative = in the future). Relative to now, so the demo always looks current. */
export const hoursAgo = (h) => new Date(Date.now() - h * HOUR).toISOString();
export const daysAgo = (d) => hoursAgo(d * 24);
/** YYYY-MM-DD, `d` days ago. */
export const dayAgo = (d) => daysAgo(d).slice(0, 10);

let counter = 1000;
/** Next integer id for records created in the demo. */
export const nextId = () => ++counter;

export const clone = (v) => (v === undefined ? v : JSON.parse(JSON.stringify(v)));

/** Parse a query-string value list: "a,b" -> ['a','b'] (empty -> []). */
export const list = (v) => (v ? String(v).split(',').filter(Boolean) : []);

/** Case-insensitive "contains" over several fields. */
export const matches = (q, ...fields) => {
  if (!q) return true;
  const needle = String(q).toLowerCase();
  return fields.some((f) => String(f ?? '').toLowerCase().includes(needle));
};

/** Throw this from a handler to answer with an API error (the UI shows `message`). */
export class DemoError extends Error {
  constructor(status, message, code = 'error', details) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

/** Return this from an export handler: the browser builds a CSV from it and saves it. No server file is made. */
export const csvDownload = (filename, columns, rows) => ({ __download: { filename, columns, rows } });

export function toCsv(columns, rows) {
  const esc = (v) => {
    const s = v === null || v === undefined ? '' : String(v);
    return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return [columns.map(esc).join(','), ...rows.map((r) => r.map(esc).join(','))].join('\r\n');
}
