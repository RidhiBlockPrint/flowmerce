/* Shipping page helpers: category names and tones, filter chips, and plain-words text for the data source. */

/** Category -> label and pill tone. The server computes the category; the browser only displays it. */
export const CAT = {
    red: { label: 'Critical 9+ days', tone: 'crit' },
    orange: { label: 'Orange 6-8 days', tone: 'warn' },
    yellow: { label: 'Yellow 4-5 days', tone: 'warn' },
    on_track: { label: 'On track 0-3 days', tone: 'ok' },
    tracking_missing: { label: 'Tracking missing', tone: 'crit' },
    invalid: { label: 'Invalid tracking', tone: 'info' },
    checks: { label: 'Fix in Shopify', tone: 'warn' },
    delivered: { label: 'Delivered', tone: 'ok' },
    reshipped: { label: 'Reshipped (old parcel)', tone: 'info' },
    resolved: { label: 'Resolved', tone: 'neutral' },
};

/** Outcomes the team can record for an order Shopify does not know about. */
export const OUTCOMES = [['delivered', 'Delivered'], ['lost', 'Lost'], ['returned', 'Returned'], ['refunded', 'Refunded']];

/** Quick filters above the shipment list. Keys are the `cat` values the API understands. Every active order is in
 *  exactly one of the sections (Critical ... Fix in Shopify), so no order is listed under two of them. */
export const CHIPS = [
    { key: '', label: 'All active' },
    { key: 'red', label: 'Critical' },
    { key: 'orange', label: 'Orange' },
    { key: 'yellow', label: 'Yellow' },
    { key: 'on_track', label: 'On track' },
    { key: 'tracking_missing', label: 'Tracking missing' },
    { key: 'invalid', label: 'Invalid tracking' },
    { key: 'checks', label: 'Fix in Shopify' },
    { key: 'reshipped', label: 'Reshipped' },
    { key: 'resolved', label: 'Resolved' },
    { key: 'flagged', label: 'Flagged by team' },
];

export const SORTS = [
    { key: 'priority', label: 'Most urgent first' },
    { key: 'oldest', label: 'Longest without an update' },
    { key: 'order', label: 'Order number' },
];

export const AGE_FILTERS = [
    { key: '', label: 'Any order date' },
    { key: '7', label: 'Ordered in the last 7 days' },
    { key: '14', label: 'Last 14 days' },
    { key: '30', label: 'Last 30 days' },
    { key: '60', label: 'Last 60 days' },
];

export const TEAM_LABEL = { delivered: 'Marked delivered', lost: 'Marked lost', failed: "Marked couldn't deliver", in_transit: 'Marked in transit' };

export const PART_LABEL = {
    shipments: 'Shipments',
    order_value: 'Order values',
    order_checks: 'Order checks',
    order_notes: 'Order notes check',
    manual_status: 'Team marks',
    sync_runs: 'Sync history',
};

export const OUTCOME = {
    will_update: { label: 'Would update', tone: 'ok' },
    skip_has_tracking: { label: 'Already has tracking', tone: 'neutral' },
    ambiguous: { label: 'Choose a package', tone: 'warn' },
    error: { label: 'Error', tone: 'crit' },
};

/** Which parts of a partial source are missing, as readable names. */
export function missingParts(source) {
    return Object.entries(source?.parts ?? {}).filter(([, v]) => v.state !== 'ok').map(([k, v]) => ({ key: k, label: PART_LABEL[k] ?? k, reason: v.reason }));
}

export function fmtMoney(value, currency) {
    if (value === null || value === undefined)
        return '—';
    try {
        return new Intl.NumberFormat('en-US', { style: 'currency', currency: currency || 'USD', maximumFractionDigits: 0 }).format(value);
    }
    catch {
        return String(Math.round(value));
    }
}

/** "1 day" / "5 days" for a number of complete days; '—' when unknown. */
export const dayText = (n) => (n === null || n === undefined ? '—' : `${n} day${n === 1 ? '' : 's'}`);

/** Plain words for the result of Settings > Integrations > Shipping > Test connection. */
export function testText(result, error) {
    if (!result)
        return error ?? 'The test did not run.';
    if (result.state === 'connected') {
        const readable = Object.entries(result.tables ?? {}).filter(([, v]) => v.readable).map(([k]) => k.replace(/_/g, ' '));
        return `Connected. ${result.rows ?? 0} shipments readable (order values ${result.orderValues ? 'available' : 'not available'}). Tables read: ${readable.join(', ')}.${result.warning ? ` ${result.warning}` : ''} Nothing was changed.`;
    }
    return `${result.label ?? 'Not connected'}: ${result.error ?? error ?? 'see the Shipping page for details.'}`;
}

/** Title for each reason the Shipping data can not be shown. */
export const SOURCE_TITLE = {
    not_configured: 'Supabase not configured',
    connection_failed: 'Connection failed',
    permission_denied: 'Permission denied',
    schema_mismatch: 'Schema mismatch',
};

/* Age bands (days since the last carrier update), fresh to oldest, then the hand-check sections. Every active order is
   in exactly one, so together they add up to the active total. The server's label holds the name and the day range. */
const BANDS = ['on_track', 'yellow', 'orange', 'red', 'tracking_missing', 'invalid', 'checks'];
const BAND_COLOUR = { on_track: 'var(--ok)', yellow: '#d6a419', orange: '#c2571a', red: 'var(--crit)',
    tracking_missing: '#8b1e3f', invalid: 'var(--info)', checks: '#a59d93' };
const BAND_NAME = { tracking_missing: ['Tracking missing', 'no number'], invalid: ['Invalid tracking', 'no carrier word'],
    checks: ['Fix in Shopify', 'data to correct'] };
function splitLabel(label) {
    const m = /^(.*?)\s*\(?(\d+\s*[–-]\s*\d+\s*days|\d+\+\s*days)\)?$/.exec(label ?? '');
    return m ? [m[1], m[2]] : [label, ''];
}

/** From the summary's `kpis`: the active total, the on-track share (%) and one ring segment per age band.
 *  `go(cat)` opens that band's shipments. */
export function ageSegments(kpis, go) {
    const by = Object.fromEntries((kpis ?? []).map((k) => [k.key, k]));
    const total = by['']?.value ?? 0;
    const onTrack = total ? Math.round(((by.on_track?.value ?? 0) / total) * 100) : 0;
    const segments = BANDS.filter((k) => by[k] && (k in BAND_NAME ? by[k].value : true)).map((k) => {
        const [name, range] = BAND_NAME[k] ?? splitLabel(by[k].label);
        return { key: k, name, range, value: by[k].value, color: BAND_COLOUR[k], onClick: go ? () => go(k) : undefined };
    });
    return { total, onTrack, segments };
}
