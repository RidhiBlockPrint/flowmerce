/**
 * Ads page helpers: tabs, choices, labels, date ranges, sorting and filtering shared by views/Ads.jsx and
 * components/ads.jsx. The figures themselves come from /api/ads/... (docs/plans/ads-module.md); nothing here works
 * out a business figure. Rates from the API are already percentages (3.6 means 3.6%), ROAS and MER are plain ratios
 * (1.87 means $1.87 of sales per $1 spent) and money is in US dollars.
 */
import { money } from './cro.js';

/** `only`: the tab belongs to one platform and is hidden while the other is chosen. `range`: it reads a date range. */
export const TABS = [
    { key: 'overview', label: 'Overview', range: true },
    { key: 'campaigns', label: 'Campaigns', range: true },
    { key: 'creatives', label: 'Creatives', only: 'meta', range: true },
    { key: 'funnel', label: 'Funnel', range: true },
    { key: 'actions', label: 'Actions' },
    // Opened now and then: under the tab bar's "Advanced" menu and the sidebar's Advanced group.
    { key: 'search', label: 'Search terms', only: 'google', range: true, advanced: true },
    { key: 'gap', label: 'ABO to CBO gap', only: 'meta', advanced: true },
    { key: 'rules', label: 'Rules', advanced: true },
];
export const tabsFor = (platform) => TABS.filter((t) => !t.only || platform === 'all' || t.only === platform);

/** One brand at a time: two brands' ad accounts are never added together. `tz` is the Meta account's time zone. */
export const BRANDS = [
    { key: 'ridhi', label: 'Ridhi', tz: 'Asia/Kolkata' },
    { key: 'cpc', label: 'CPC', tz: 'America/Chicago' },
];
export const PLATFORMS = [
    { key: 'all', label: 'All' },
    { key: 'meta', label: 'Meta' },
    { key: 'google', label: 'Google' },
];
export const PLATFORM_LABEL = { meta: 'Meta', google: 'Google' };

/** The platform the page shows: a tab that belongs to one platform always shows that platform. */
export function platformFor(tabKey, chosen) {
    const only = TABS.find((t) => t.key === tabKey)?.only;
    const picked = PLATFORMS.some((p) => p.key === chosen) ? chosen : 'all';
    return only && picked !== 'all' && picked !== only ? only : picked;
}

export const CAMPAIGN_TYPES = [
    { key: 'cbo', label: 'CBO', platform: 'meta' },
    { key: 'abo', label: 'ABO', platform: 'meta' },
    { key: 'catalog', label: 'Catalog', platform: 'meta' },
    { key: 'retargeting', label: 'Retargeting', platform: 'meta' },
    { key: 'pmax', label: 'Performance Max', platform: 'google' },
    { key: 'search', label: 'Search', platform: 'google' },
    { key: 'display', label: 'Display', platform: 'google' },
    { key: 'shopping', label: 'Shopping', platform: 'google' },
];

export const AD_STATUS = {
    ACTIVE: { label: 'Active', tone: 'ok' },
    PAUSED: { label: 'Paused', tone: 'neutral' },
    ADSET_PAUSED: { label: 'Ad set paused', tone: 'neutral' },
    REMOVED: { label: 'Removed', tone: 'neutral' },
};

/** The rule set's answer for one ad (Rules tab), in the order the chips are shown. */
export const VERDICTS = {
    scale: { label: 'Scale', tone: 'ok', help: 'Proven and still strong: raise its budget.' },
    graduate: { label: 'Graduate', tone: 'ok', help: 'A test ad that passed: move it into the scaling campaign.' },
    hold: { label: 'Hold', tone: 'neutral', help: 'Doing its job: leave it alone.' },
    iterate: { label: 'Iterate', tone: 'warn', help: 'Between stop and scale: make a new version that fixes its weakest step.' },
    stop: { label: 'Stop', tone: 'crit', help: 'Failed its test or fell below the stop line.' },
    continue: { label: 'Continue test', tone: 'info', help: 'Has a purchase but has not spent enough to judge.' },
    testing: { label: 'In test', tone: 'neutral', help: 'Still below the test spend.' },
};
export const VERDICT_ORDER = ['scale', 'graduate', 'hold', 'iterate', 'stop', 'continue', 'testing'];

export const GAP_VERDICTS = {
    add: { label: 'Add to CBO', tone: 'ok' },
    watch: { label: 'Watch', tone: 'info' },
    already: { label: 'Already in', tone: 'neutral' },
    stop: { label: 'Stop', tone: 'crit' },
    early: { label: 'Too early', tone: 'neutral' },
};

export const ACTION_GROUPS = {
    stop: { label: 'Stop', tone: 'crit' },
    refresh: { label: 'Refresh', tone: 'info' },
    budget: { label: 'Budget', tone: 'warn' },
    iterate: { label: 'Iterate', tone: 'accent' },
};
export const ACTION_STATUS = [
    { key: 'open', label: 'Open' },
    { key: 'done', label: 'Done' },
    { key: 'skipped', label: 'Skipped' },
];

/** The scaling gate and the day colours: a label, the theme colour to draw it with, the ink for text in it, and its
 *  pale background. */
export const GATE = {
    green: { label: 'Green', word: 'Room to scale', color: 'var(--theme-good-strong)', ink: 'var(--ok)', soft: 'var(--ok-soft)' },
    amber: { label: 'Amber', word: 'Hold', color: 'var(--theme-usual-strong)', ink: 'var(--warn)', soft: 'var(--warn-soft)' },
    red: { label: 'Red', word: 'Cut back', color: 'var(--theme-low-strong)', ink: 'var(--crit)', soft: 'var(--crit-soft)' },
    unknown: { label: 'No call', word: 'No call yet', color: 'var(--faint)', ink: 'var(--muted)', soft: 'var(--surface-3)' },
};

/** Every setting on the Rules tab, grouped as it is shown. `only` hides a field unless the Meta account is in that currency. */
export const RULE_GROUPS = [
    { title: 'Money and goals', fields: [
        { key: 'fx_rate', label: 'Rupees for one US dollar', unit: 'Rs', only: 'INR', hint: 'Meta is billed in rupees; its figures are shown in dollars at this rate. The rate is saved with the day it was set.' },
        { key: 'goal_daily_sales', label: 'Daily store sales goal', unit: '$' },
        { key: 'bulk_order_min', label: 'Bulk order: leave out orders above', unit: '$', hint: 'Left out of the "excl. bulk" figures and of the scaling gate.' },
    ] },
    { title: 'Targets', fields: [
        { key: 'target_roas', label: 'Meta ROAS target' },
        { key: 'target_mer', label: 'MER target' },
        { key: 'mer_floor', label: 'MER floor while scaling' },
    ] },
    { title: 'Scaling gate (MER without bulk orders)', fields: [
        { key: 'gate_green_3d', label: 'Green: 3-day MER at least' },
        { key: 'gate_green_7d', label: 'Green: 7-day MER at least' },
        { key: 'gate_red', label: 'Red: MER below' },
    ] },
    { title: 'CBO budgets', fields: [
        { key: 'budget_up_7d', label: 'Raise: 7-day ROAS at least' },
        { key: 'budget_up_3d', label: 'Raise: 3-day ROAS at least' },
        { key: 'budget_down_7d', label: 'Lower: 7-day ROAS below' },
        { key: 'budget_down_3d', label: 'Lower: 3-day ROAS below' },
        { key: 'budget_step_pct', label: 'Budget step', unit: '%' },
        { key: 'cbo_min_ads', label: 'Fewest delivering ads in a CBO' },
        { key: 'cbo_max_ads', label: 'Most delivering ads in a CBO' },
    ] },
    { title: 'Creative tests and proven ads', fields: [
        { key: 'test_spend', label: 'Test spend', unit: '$', hint: 'No purchase at this spend: stop.' },
        { key: 'proven_spend', label: 'Proven at lifetime spend', unit: '$' },
        { key: 'stop_roas', label: 'Stop: ROAS below' },
        { key: 'scale_roas', label: 'Scale or graduate: ROAS at least' },
        { key: 'scale_3d_roas', label: 'Scale: 3-day ROAS at least' },
        { key: 'scale_min_purchases', label: 'Scale: 7-day purchases at least' },
        { key: 'graduate_min_purchases', label: 'Graduate: lifetime purchases at least' },
    ] },
];

/* ------------------------------------------------------------------ formatting */
/** Whole dollars by default: $1,235. */
export const usd = (v, digits = 0) => money(v, 'USD', digits);
/** A ROAS or MER ratio: 1.87 (a dash when there was no spend). */
export const x2 = (v) => (v === null || v === undefined || Number.isNaN(v) ? '—' : Number(v).toFixed(2));
/** A rate that is already in percent units: 3.6 -> "3.6%". */
export const pct1 = (v) => (v === null || v === undefined || Number.isNaN(v) ? '—' : `${Number(v).toFixed(1)}%`);
/** How a ratio compares with its target: 'ok' at or above it, 'warn' within 30% below, 'crit' further below. */
export function ratioTone(value, target) {
    if (value === null || value === undefined || !target) return '';
    return value >= target ? 'ok' : value >= target * 0.7 ? 'warn' : 'crit';
}
/** A change in percent between two values, or null when it cannot be worked out. */
export const changeOf = (cur, prev) => (cur === null || cur === undefined || !prev ? null : Math.round((cur / prev - 1) * 1000) / 10);

/** What the page says for an API error it can explain, or null for the generic error box. */
export function explainAdsError(err) {
    if (err?.status === 404 && err?.code !== 'not_found')
        return { title: 'Ads is not connected yet', tone: 'info', text: 'These screens are ready, but the live Meta and Google data is the next build step. The preview copy shows them with sample numbers.' };
    if (err?.code === 'not_configured')
        return { title: 'Ads is not connected yet', tone: 'warn', text: 'The ad account keys or the Ads tables are not set up on the server.' };
    if (err?.code === 'token_expired')
        return { title: 'The ad account sign-in has expired', tone: 'crit', text: err.message };
    // A brand without a Google Ads account (or not read yet) is not an error: say why, calmly.
    if (err?.code === 'google_not_connected')
        return { title: 'Google Ads is not connected for this brand', tone: 'info', text: err.message };
    return null;
}

/* ------------------------------------------------------------------ date ranges
 * The same date picker and comparison menu as the CRO page (components/croDates.jsx, keys from lib/cro.js): Today,
 * Yesterday, Last N days / weeks / months, Period to date, Black Friday Cyber Monday, Quarters or a custom range,
 * compared with the previous period, the previous year (same dates or same weekdays), a custom period or nothing.
 * A range lives in the address (?r=last-7-days, or ?r=custom&from=...&to=...) with ?cmp= and ?cfrom=, so a link
 * opens the same view. The default is the last 7 complete days against the 7 before. */
export const DEFAULT_RANGE = 'last-7-days';

/* ------------------------------------------------------------------ tables: sorting and filtering */
const valueAt = (row, key) => key.split('.').reduce((o, k) => (o === null || o === undefined ? o : o[k]), row);

/** Rows sorted by a column (`key` may be nested: 'lifetime.roas'). Empty values always go last. */
export function sortRows(rows, key, dir = 'desc') {
    const sign = dir === 'asc' ? 1 : -1;
    return [...rows].sort((a, b) => {
        const x = valueAt(a, key), y = valueAt(b, key);
        const xe = x === null || x === undefined, ye = y === null || y === undefined;
        if (xe || ye) return xe === ye ? 0 : xe ? 1 : -1;
        return (typeof x === 'string' ? x.localeCompare(y) : x - y) * sign;
    });
}

const has = (q, ...fields) => !q || fields.some((f) => String(f ?? '').toLowerCase().includes(q));

/**
 * The ads a set of filters leaves. `f`: { q, verdict, campaign, line, format, status, minSpend, view } where view is
 * 'all', 'new' (launched in the last 7 days), 'tests' (still in or just out of its test) or 'winners' (the bench).
 */
export function filterAds(ads, f = {}, winners = []) {
    const q = (f.q ?? '').trim().toLowerCase();
    const min = Number(f.minSpend) || 0;
    const bench = new Set(winners);
    return (ads ?? []).filter((a) => has(q, a.name, a.code, a.id, a.campaign, a.ad_set)
        && (!f.verdict || a.verdict === f.verdict)
        && (!f.campaign || a.campaign_id === f.campaign)
        && (!f.line || a.product_line === f.line)
        && (!f.format || a.format === f.format)
        && (!f.status || (f.status === 'active' ? a.status === 'ACTIVE' : a.status !== 'ACTIVE'))
        && a.spend >= min
        && (f.view === 'new' ? a.is_new : f.view === 'tests' ? ['testing', 'continue'].includes(a.verdict) || (a.verdict === 'stop' && a.lifetime.purchases === 0) : f.view === 'winners' ? bench.has(a.id) : true));
}

/** The campaigns a set of filters leaves. `f`: { q, type, line, status }. */
export function filterCampaigns(campaigns, f = {}) {
    const q = (f.q ?? '').trim().toLowerCase();
    return (campaigns ?? []).filter((c) => has(q, c.name, c.id)
        && (!f.type || c.type === f.type)
        && (!f.line || c.product_line === f.line)
        && (!f.status || (f.status === 'active' ? c.status === 'ACTIVE' : c.status !== 'ACTIVE')));
}
