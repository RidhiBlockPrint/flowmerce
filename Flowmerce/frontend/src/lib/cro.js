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
    { key: 'landing', label: 'Landing pages' },
    { key: 'checkout', label: 'Cart & checkout' },
    { key: 'products', label: 'Products' },
    { key: 'sales', label: 'Sales' },
    // Opened now and then: kept in the sidebar's Advanced group (owner decision
    // 2026-11-21 for Site health, Recommendations and Experiments).
    { key: 'site', label: 'Site health', advanced: true },
    { key: 'recommendations', label: 'Recommendations', advanced: true },
    { key: 'experiments', label: 'Experiments', advanced: true },
    { key: 'alarms', label: 'Alarms', advanced: true },
    { key: 'changes', label: 'Change log', advanced: true },
];

/** CRO works on one store at a time: conversion rates of two stores cannot be added together. */
export const STORES = [
    { key: 'ridhi', label: 'Ridhi', tz: 'America/New_York' },
    { key: 'cpc', label: 'CPC', tz: 'America/Phoenix' },
];

/**
 * The store's timezone before /cro/settings has answered: the one Shopify reports for each store (21 Nov 2026), so a
 * CRO page can work out "yesterday" and start its requests at once instead of waiting about 2 s for settings. When
 * settings answers with a different zone, the page simply asks again for the right days.
 */
export function storeTimezone(brand, reported) {
    return reported || STORES.find((s) => s.key === brand)?.tz || 'UTC';
}

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
    cvr_drop: { label: 'Conversion-rate drop', unit: '%', help: 'Alert when yesterday\'s conversion rate is this many percent below the average of the same weekday over the last 4 weeks. Days with fewer than 30 sessions are not judged.' },
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
 * The CRO page works on any store-local day range, picked like Shopify's date picker (2026-11-24): Today, Yesterday,
 * Last N days / weeks / months / quarters / years, Period to date, Black Friday Cyber Monday, Quarters or a custom
 * range. A pick that moves with time keeps its key, so "Yesterday" always means yesterday. A range lives in the address
 * (?r=last-7-days, or ?r=custom&from=2026-11-01&to=2026-11-15) with the comparison in ?cmp= (and ?cfrom= for a custom
 * comparison), so a link opens the same view. Older keys (last7, this_month, last_month...) still work. */

/** The comparisons. The picker offers Shopify's five; `hidden` ones are kept only so older links still open. */
export const RANGE_COMPARES = [
    { key: 'previous', label: 'Previous period' },
    { key: 'previous_year', label: 'Previous year' },
    { key: 'previous_year_dow', label: 'Previous year (match day of week)' },
    { key: 'custom', label: 'Custom' },
    { key: 'none', label: 'No comparison' },
    { key: 'last_week', label: 'Same days a week earlier', hidden: true },
    { key: '4week_avg', label: '4-week weekday average', single: true, hidden: true },
];

export const TO_DATE = [{ key: 'wtd', label: 'Week to date' }, { key: 'mtd', label: 'Month to date' }, { key: 'qtd', label: 'Quarter to date' },
    { key: 'ytd', label: 'Year to date' }];
const LEGACY = { last7: 'last-7-days', last14: 'last-14-days', last30: 'last-30-days', this_month: 'mtd', last_month: 'last-1-months' };
const pad2 = (n) => String(n).padStart(2, '0');
const ymd = (y, m, d) => new Date(Date.UTC(y, m - 1, d)).toISOString().slice(0, 10);
const weekStart = (iso) => shiftDay(iso, -new Date(`${iso}T00:00:00Z`).getUTCDay());   // weeks start on Sunday, as in Shopify
const monthStart = (iso) => `${iso.slice(0, 7)}-01`;
const quarterStart = (iso) => `${iso.slice(0, 4)}-${pad2(Math.floor((Number(iso.slice(5, 7)) - 1) / 3) * 3 + 1)}-01`;
const yearStart = (iso) => `${iso.slice(0, 4)}-01-01`;
/** The first day of the month `k` months after the month starting on `first`. */
const addMonths = (first, k) => ymd(Number(first.slice(0, 4)), Number(first.slice(5, 7)) + k, 1);

/** Black Friday to Cyber Monday of a year: the day after the fourth Thursday of November, for four days. */
export function bfcm(year) {
    const wd = new Date(Date.UTC(year, 10, 1)).getUTCDay();
    const thanksgiving = 1 + ((4 - wd + 7) % 7) + 21;
    return { from: ymd(year, 11, thanksgiving + 1), to: ymd(year, 11, thanksgiving + 4) };
}
/** Quarter `q` (1-4) of `year`. */
export function quarterRange(year, q) {
    const from = ymd(year, (q - 1) * 3 + 1, 1);
    return { from, to: shiftDay(addMonths(from, 3), -1) };
}
/** "Last n unit" keys: last-7-days, last-1-months... (`-t` = up to and including today, for older links). */
export function parseLast(key) {
    const m = /^last-(\d{1,3})-(days|weeks|months|quarters|years)(-t)?$/.exec(LEGACY[key] ?? key ?? '');
    return m ? { n: Math.max(1, Number(m[1])), unit: m[2], today: !!m[3] } : null;
}

/** Whether a range key is one the picker understands (custom ranges use 'custom'). */
export const isRangeKey = (key) => !!key && (key === 'custom' || key === 'today' || key === 'yesterday' || !!LEGACY[key] || !!parseLast(key)
    || TO_DATE.some((t) => t.key === key) || /^bfcm-\d{4}$/.test(key) || /^q-\d{4}-[1-4]$/.test(key));

/** The label a range key shows on the picker button ("Yesterday", "Last 7 days", "Q3 2026"...). */
export function rangeLabel(key, from, to) {
    if (key === 'today') return 'Today';
    if (key === 'yesterday') return 'Yesterday';
    const last = parseLast(key);
    if (last) {
        const one = last.unit.replace(/s$/, '');
        return (last.n === 1 && last.unit !== 'days' ? `Last ${one}` : `Last ${last.n} ${last.n === 1 ? one : last.unit}`) + (last.today ? ' (incl. today)' : '');
    }
    const td = TO_DATE.find((t) => t.key === (LEGACY[key] ?? key));
    if (td) return td.label;
    if (/^bfcm-\d{4}$/.test(key ?? '')) return `BFCM ${key.slice(5)}`;
    if (/^q-\d{4}-[1-4]$/.test(key ?? '')) return `Q${key.slice(7)} ${key.slice(2, 6)}`;
    return from && to ? fmtSpan(from, to) : 'Pick dates';
}
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
/** "Nov 1 – 15, 2026", "Oct 28 – Nov 3, 2026" or "Nov 23, 2026". */
export function fmtSpan(from, to) {
    const [fy, fm, fd] = from.split('-').map(Number);
    const [ty, tm, td] = to.split('-').map(Number);
    if (from === to) return `${MONTHS[fm - 1]} ${fd}, ${fy}`;
    if (fy !== ty) return `${MONTHS[fm - 1]} ${fd}, ${fy} – ${MONTHS[tm - 1]} ${td}, ${ty}`;
    return fm === tm ? `${MONTHS[fm - 1]} ${fd} – ${td}, ${fy}` : `${MONTHS[fm - 1]} ${fd} – ${MONTHS[tm - 1]} ${td}, ${fy}`;
}

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

/** { from, to } for a range key, relative to the store's today (Shopify's meanings: "Last 3 months" = the three
 * whole months before this one; "(incl. today)" runs up to today). Unknown keys give yesterday. */
export function presetRange(key, today) {
    const y = shiftDay(today, -1);
    const k = LEGACY[key] ?? key;
    if (k === 'today') return { from: today, to: today };
    if (k === 'wtd') return { from: weekStart(today), to: today };
    if (k === 'mtd') return { from: monthStart(today), to: today };
    if (k === 'qtd') return { from: quarterStart(today), to: today };
    if (k === 'ytd') return { from: yearStart(today), to: today };
    if (/^bfcm-\d{4}$/.test(k ?? '')) {
        const b = bfcm(Number(k.slice(5)));
        return { from: b.from, to: b.to < today ? b.to : today };
    }
    if (/^q-\d{4}-[1-4]$/.test(k ?? '')) {
        const r = quarterRange(Number(k.slice(2, 6)), Number(k.slice(7)));
        return { from: r.from, to: r.to < today ? r.to : today };
    }
    const last = parseLast(k);
    if (last) {
        const { n, unit } = last;
        if (unit === 'days') return last.today ? { from: shiftDay(today, -(n - 1)), to: today } : { from: shiftDay(y, -(n - 1)), to: y };
        const start = { weeks: weekStart, months: monthStart, quarters: quarterStart, years: yearStart }[unit](today);
        const back = (first, steps) => (unit === 'weeks' ? shiftDay(first, -7 * steps)
            : addMonths(first, -steps * ({ months: 1, quarters: 3, years: 12 }[unit])));
        return last.today ? { from: back(start, n - 1), to: today } : { from: back(start, n), to: shiftDay(start, -1) };
    }
    return { from: y, to: y };
}

/** Number of days in an inclusive YYYY-MM-DD range. */
export const rangeDays = (from, to) => Math.round((Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / 864e5) + 1;

/** The comparison actually used: the 4-week weekday average only exists for a single day, and a custom comparison
 * needs a first day before the chosen days. */
export function effectiveCompare(cmp, from, to, cfrom) {
    if (cmp === '4week_avg' && rangeDays(from, to) !== 1) return 'previous';
    if (cmp === 'custom' && !(cfrom && cfrom < from)) return 'previous';
    return RANGE_COMPARES.some((c) => c.key === cmp) ? cmp : 'previous';
}

/** The days a comparison covers, for the picker to show ({ from, to }, or null for none / the 4-week average). */
export function compareRange(cmp, from, to, cfrom) {
    const n = rangeDays(from, to);
    const back = (days) => ({ from: shiftDay(from, -days), to: shiftDay(to, -days) });
    if (cmp === 'previous') return back(n);
    if (cmp === 'last_week') return back(7);
    if (cmp === 'previous_year_dow') return back(364);
    if (cmp === 'previous_year') {
        const [y, m, d] = from.split('-').map(Number);
        const start = m === 2 && d === 29 ? ymd(y - 1, 2, 28) : ymd(y - 1, m, d);
        return { from: start, to: shiftDay(start, n - 1) };
    }
    if (cmp === 'custom' && cfrom) return { from: cfrom, to: shiftDay(cfrom, n - 1) };
    return null;
}

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

/* ------------------------------------------------------------------ landing pages, site health, payments */
/** Google's Core Web Vitals as the Site health tab names them. */
export const VITALS = [
    { key: 'lcp', label: 'Main content shows (LCP)', help: 'Largest Contentful Paint: how long until the biggest image or text block is on screen. Good: 2.5 s or less.' },
    { key: 'inp', label: 'Reacts to a tap (INP)', help: 'Interaction to Next Paint: how long the page takes to respond to a tap or click. Good: 200 ms or less.' },
    { key: 'cls', label: 'Layout stays put (CLS)', help: 'Cumulative Layout Shift: how much the page jumps while loading. Good: 0.1 or less.' },
];
/** Google's rating of a vital, as a calendar-lane chip. */
export const RATING = {
    good: { label: 'Good', lane: 'lane-live' },
    needs_improvement: { label: 'Needs work', lane: 'lane-event' },
    poor: { label: 'Poor', lane: 'lane-due' },
};

/** A vital's p75 for display: LCP in seconds, INP in milliseconds, CLS as a plain number. */
export function fmtVital(metric, v) {
    if (v === null || v === undefined || Number.isNaN(v)) return '—';
    if (metric === 'cls') return Number(v).toFixed(2);
    if (metric === 'lcp') return `${(v / 1000).toFixed(2)} s`;
    return `${Math.round(v)} ms`;
}

/** Shopify's machine labels made readable: 'credit_card' -> 'Credit card', 'shopify_pay' -> 'Shop Pay'. */
const LABELS = { shopify_pay: 'Shop Pay', apple_pay: 'Apple Pay', google_pay: 'Google Pay', paypal: 'PayPal', cardserver_token: 'Saved card', meta_pay: 'Meta Pay' };
export function readable(label) {
    const s = String(label ?? '').trim();
    if (!s) return 'Other';
    if (LABELS[s]) return LABELS[s];
    const t = s.replace(/_/g, ' ');
    return t.charAt(0).toUpperCase() + t.slice(1);
}

/**
 * How a weekday-hour cell compares with the period's average conversion: 0 (well below) to 4 (well above), or null
 * when the cell has too few visits for a rate. Used to shade the heatmap.
 */
export function heatLevel(cvr, avg) {
    if (cvr === null || cvr === undefined || !avg) return null;
    const r = cvr / avg;
    return r < 0.5 ? 0 : r < 0.85 ? 1 : r < 1.15 ? 2 : r < 1.5 ? 3 : 4;
}

/** The best weekday-hours by conversion (cells with a rate only), best first. */
export function bestHours(cells, n = 3) {
    return (cells ?? []).filter((c) => c.cvr !== null && c.cvr !== undefined).sort((a, b) => b.cvr - a.cvr || b.sessions - a.sessions).slice(0, n);
}

/** '14:00' for an hour of the day. */
export const fmtHour = (h) => `${String(h).padStart(2, '0')}:00`;
