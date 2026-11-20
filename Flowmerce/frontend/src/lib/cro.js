/**
 * CRO page helpers: tabs, choices, labels and number formatting shared by views/Cro.jsx and components/cro.jsx.
 * The figures themselves come from the Python API (/api/cro/...); nothing is calculated here except display.
 *
 * Units from the API: conversion and funnel rates are already percentages (2.47 means 2.47%), and every
 * `change_pct` is a percentage too (50.6 means +50.6%).
 */

export const TABS = [
    { key: 'overview', label: 'Overview' },
    { key: 'conversion', label: 'Conversion' },
    { key: 'checkout', label: 'Cart & checkout' },
    { key: 'products', label: 'Products' },
    { key: 'sales', label: 'Sales' },
    { key: 'recommendations', label: 'Recommendations' },
    // Set up once and rarely opened: kept under the tab bar's "Advanced" menu and the sidebar's Advanced group.
    { key: 'alarms', label: 'Alarms', advanced: true },
    { key: 'changes', label: 'Change log', advanced: true },
];

/** CRO works on one store at a time: conversion rates of two stores cannot be added together. */
export const STORES = [
    { key: 'ridhi', label: 'Ridhi' },
    { key: 'cpc', label: 'CPC' },
];

export const AREAS = [
    { key: 'theme', label: 'Theme' },
    { key: 'app', label: 'App' },
    { key: 'price', label: 'Price' },
    { key: 'promo', label: 'Promo' },
    { key: 'ad', label: 'Ad' },
    { key: 'other', label: 'Other' },
];
export const areaLabel = (k) => AREAS.find((a) => a.key === k)?.label ?? k;

export const PERFORMANCE = {
    top: { label: 'Top', tone: 'ok' },
    average: { label: 'Average', tone: 'neutral' },
    low: { label: 'Low', tone: 'warn' },
};

export const PRIORITY_TONE = { High: 'crit', Medium: 'warn', Low: 'neutral' };

/** Claude's action plan (modules/cro/ai_advice.py): how each action's expected impact and effort are shown. */
export const IMPACT_TONE = { High: 'ok', Medium: 'info', Low: 'neutral' };
export const EFFORT_TONE = { Low: 'ok', Medium: 'warn', High: 'crit' };
export const ADVICE_AREA = {
    traffic: 'Traffic', product_page: 'Product page', pricing: 'Pricing', checkout: 'Checkout', merchandising: 'Merchandising',
    retention: 'Repeat customers', trust: 'Trust', operations: 'Operations',
};

export const RULE_KIND = {
    cvr_drop: { label: 'Conversion-rate drop', unit: '%', help: 'Alert when yesterday\'s conversion rate is this many percent lower than the day before.' },
    no_product_orders: { label: 'No orders for a product', unit: 'hours', help: 'Alert when no order with a matching product (title, type or tag) arrives for this many hours.' },
};

/**
 * What the page says when the API answers with an error code (see modules/cro/api.py).
 * Returns { title, text, tone } or null for codes the generic error box explains well enough.
 */
export function explainError(err) {
    switch (err?.code) {
        case 'reports_access_missing':
            return {
                title: 'Shopify analytics is not available for this store',
                text: 'The store\'s Shopify app needs the read_reports permission and Level 2 protected customer data access. '
                    + 'Order figures still work; sessions, conversion rate and the funnel need this.',
                tone: 'warn',
            };
        case 'not_configured':
            return { title: 'CRO is not connected yet', text: 'Supabase or the store\'s Shopify keys are not set up on the server.', tone: 'warn' };
        case 'schema_missing':
            return { title: 'The CRO tables are not reachable', text: err.message, tone: 'crit' };
        case 'query_error':
        case 'shopify_error':
            return { title: 'Shopify analytics could not be read', text: err.message, tone: 'crit' };
        default:
            return null;
    }
}

/* ------------------------------------------------------------------ formatting */
const moneyFmt = new Map();
/** $1,234.56 in the store's currency (USD when unknown). */
export function money(value, currency = 'USD', digits = 2) {
    if (value === null || value === undefined || Number.isNaN(value)) return '—';
    const key = `${currency}|${digits}`;
    if (!moneyFmt.has(key)) {
        try {
            moneyFmt.set(key, new Intl.NumberFormat('en-US', { style: 'currency', currency, minimumFractionDigits: digits, maximumFractionDigits: digits }));
        } catch {
            moneyFmt.set(key, new Intl.NumberFormat('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits }));
        }
    }
    return moneyFmt.get(key).format(value);
}

/** A percentage that is already in percent units: 2.47 -> "2.47%". */
export const pct = (v, digits = 2) => (v === null || v === undefined || Number.isNaN(v) ? '—' : `${Number(v).toFixed(digits)}%`);

/** A signed change in percent units: 50.6 -> "+50.6%". */
export const signedPct = (v, digits = 1) => (v === null || v === undefined || Number.isNaN(v) ? '—' : `${v > 0 ? '+' : ''}${Number(v).toFixed(digits)}%`);

/** A change in percentage points: 0.4 -> "+0.40 pts". */
export const signedPts = (v) => (v === null || v === undefined || Number.isNaN(v) ? '—' : `${v > 0 ? '+' : ''}${Number(v).toFixed(2)} pts`);

/** Chart series for LineChart from rows that carry `date` and a numeric field. */
export const seriesOf = (rows, field, key, label, color, extra = {}) => ({
    key, label, color, ...extra,
    points: (rows || []).map((r) => ({ x: r.date, y: r[field] ?? null })),
});

/* ------------------------------------------------------------------ date ranges
 * The CRO page works on any store-local day range picked on a calendar. Quick picks are recomputed from the
 * store's "today" every time the page opens, so "Yesterday" always means yesterday. A range lives in the address
 * (?r=last7, or ?r=custom&from=2026-11-01&to=2026-11-15) with the comparison in ?cmp=, so a link opens the same view. */

export const RANGE_PRESETS = [
    { key: 'today', label: 'Today' },
    { key: 'yesterday', label: 'Yesterday' },
    { key: 'last7', label: 'Last 7 days' },
    { key: 'last14', label: 'Last 14 days' },
    { key: 'last30', label: 'Last 30 days' },
    { key: 'this_month', label: 'This month' },
    { key: 'last_month', label: 'Last month' },
];

export const RANGE_COMPARES = [
    { key: 'previous', label: 'Previous period' },
    { key: 'last_week', label: 'Same days a week earlier' },
    { key: '4week_avg', label: '4-week weekday average', single: true },
    { key: 'none', label: 'No comparison' },
];

/** Today's date (YYYY-MM-DD) in the store's timezone. */
export function todayIn(tz) {
    try {
        return new Intl.DateTimeFormat('en-CA', { timeZone: tz || 'UTC', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());
    } catch {
        return new Date().toISOString().slice(0, 10);
    }
}

/** Shift a YYYY-MM-DD date by `n` days (calendar arithmetic, no timezone involved). */
export function shiftDay(iso, n) {
    const [y, m, d] = iso.split('-').map(Number);
    const t = new Date(Date.UTC(y, m - 1, d + n));
    return t.toISOString().slice(0, 10);
}

/** { from, to } for a quick pick, relative to the store's today. Unknown keys give yesterday. */
export function presetRange(key, today) {
    const y = shiftDay(today, -1);
    const [yy, mm] = today.split('-').map(Number);
    const monthStart = `${yy}-${String(mm).padStart(2, '0')}-01`;
    switch (key) {
        case 'today': return { from: today, to: today };
        case 'last7': return { from: shiftDay(y, -6), to: y };
        case 'last14': return { from: shiftDay(y, -13), to: y };
        case 'last30': return { from: shiftDay(y, -29), to: y };
        case 'this_month': return { from: monthStart, to: today };
        case 'last_month': {
            const lastEnd = shiftDay(monthStart, -1);
            return { from: `${lastEnd.slice(0, 7)}-01`, to: lastEnd };
        }
        default: return { from: y, to: y };
    }
}

/** Number of days in an inclusive YYYY-MM-DD range. */
export const rangeDays = (from, to) => Math.round((Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / 864e5) + 1;

/** The comparison actually used: the 4-week weekday average only exists for a single day. */
export const effectiveCompare = (cmp, from, to) => (cmp === '4week_avg' && rangeDays(from, to) !== 1 ? 'previous' : cmp);

/* ------------------------------------------------------------------ Overview drawing helpers
 * Small calculations for the Overview's charts (components/croOverview.jsx). They only arrange figures the API
 * already sent; they never invent one. */

/**
 * The days the sales chart draws, with the days it is compared against. `current` and `previous` are the API's
 * 28-day sales trend and the 28 days before it, oldest first. For 28 days the chart uses both lists as they are;
 * for a shorter window (7 or 14 days) it takes the last `n` days of `current` and the `n` days just before them.
 */
export function salesWindow(current, previous, n) {
    const cur = current || [];
    if (n >= cur.length) return { current: cur, previous: previous || [] };
    return { current: cur.slice(cur.length - n), previous: cur.slice(Math.max(0, cur.length - 2 * n), cur.length - n) };
}

/**
 * The conversion gauge's scale from the last few weeks of daily rates (percent units). The "usual" band is within
 * 13% of the average either side, so a day is "strong" or "below usual" only when it clearly differs.
 * `beats` counts the days in the history the given value is higher than. Returns null without history.
 */
export function conversionScale(history, value = null) {
    const v = (history || []).filter((x) => typeof x === 'number' && Number.isFinite(x));
    if (!v.length) return null;
    const avg = v.reduce((a, x) => a + x, 0) / v.length;
    const all = value === null || value === undefined ? v : [...v, value];
    const lo = Math.max(0, Math.floor((Math.min(...all) - 0.2) * 5) / 5);
    const hi = Math.ceil((Math.max(...all) + 0.2) * 5) / 5;
    return { lo, hi, avg, low: avg * 0.87, high: avg * 1.13, days: v.length, beats: value === null || value === undefined ? null : v.filter((x) => x < value).length };
}

/** Which band a conversion rate falls in on a scale from conversionScale: 'high', 'mid' or 'low' (null without a rate). */
export const conversionBand = (rate, scale) => (rate === null || rate === undefined || !scale ? null : rate >= scale.high ? 'high' : rate < scale.low ? 'low' : 'mid');

/** A rounded top for a chart axis and its step, so the axis reads 0, 5k, 10k, 15k rather than odd numbers. */
export function niceAxis(max, ticks = 3) {
    if (!(max > 0)) return { top: ticks, step: 1 };
    const raw = max / ticks;
    const p = 10 ** Math.floor(Math.log10(raw));
    const step = [1, 2, 2.5, 5, 10].map((m) => m * p).find((s) => s >= raw);
    return { top: step * Math.ceil(max / step), step };
}

/** CSV text from rows of plain values; the first row is the header. Cells with commas or quotes are quoted. */
export function toCsv(rows) {
    const cell = (x) => {
        const s = x === null || x === undefined ? '' : String(x);
        return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
    };
    return rows.map((r) => r.map(cell).join(',')).join('\n');
}
