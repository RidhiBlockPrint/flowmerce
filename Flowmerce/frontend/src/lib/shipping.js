/* Shipping page helpers: category names and tones, filter chips, and plain-words text for the data source. */

/** Category -> label and pill tone. The server computes the category; the browser only displays it. */
export const CAT = {
    red: { label: 'Critical 9+ days', tone: 'crit' },
    orange: { label: 'Orange 6-8 days', tone: 'warn' },
    yellow: { label: 'Yellow 4-5 days', tone: 'warn' },
    grey: { label: 'Grey 2-3 days', tone: 'neutral' },
    on_track: { label: 'On track', tone: 'ok' },
    no_scan: { label: 'No scan data', tone: 'outline' },
    unconfirmed: { label: 'Carrier unconfirmed', tone: 'info' },
    lost: { label: 'Lost (team confirmed)', tone: 'crit' },
    failed: { label: "Couldn't deliver (team confirmed)", tone: 'warn' },
    delivered: { label: 'Delivered', tone: 'ok' },
    reshipped: { label: 'Reshipped (old parcel)', tone: 'info' },
    resolved: { label: 'Resolved', tone: 'neutral' },
};

/** Outcomes the team can record for an order Shopify does not know about. */
export const OUTCOMES = [['delivered', 'Delivered'], ['lost', 'Lost'], ['returned', 'Returned'], ['refunded', 'Refunded']];

/** Quick filters above the shipment list. Keys are the `cat` values the API understands. */
export const CHIPS = [
    { key: '', label: 'All active' },
    { key: 'red', label: 'Critical' },
    { key: 'nomove', label: 'No movement' },
    { key: 'noscan', label: 'Scan missing' },
    { key: 'exception', label: 'Exceptions' },
    { key: 'flagged', label: 'Flagged by team' },
    { key: 'unconfirmed', label: 'Carrier unconfirmed' },
    { key: 'reshipped', label: 'Reshipped' },
    { key: 'resolved', label: 'Resolved' },
];

export const SORTS = [
    { key: 'priority', label: 'Most urgent first' },
    { key: 'stuck', label: 'Stuck first' },
    { key: 'oldest', label: 'Oldest in stage' },
    { key: 'order', label: 'Order number' },
];

export const AGE_FILTERS = [
    { key: '', label: 'Any order date' },
    { key: '7', label: 'Ordered in the last 7 days' },
    { key: '14', label: 'Last 14 days' },
    { key: '30', label: 'Last 30 days' },
    { key: '60', label: 'Last 60 days' },
];

export const STAGE_LABEL = { pre_dispatch: 'Not dispatched', dispatched: 'Dispatched', delivered: 'Delivered' };

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
