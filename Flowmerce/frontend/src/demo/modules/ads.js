/**
 * Demo module: Ads (Meta Ads + Google Ads). Everything here is synthetic: invented campaigns, ads, search terms and
 * daily figures, sized like a real account so the screens can be judged. No real ad account, name or number is in
 * this file, because the demo data ships inside the web app's public files (and the GitHub Pages demo).
 * It answers the /api/ads/... calls the Python module will answer later (docs/plans/ads-module.md), with the same
 * response shapes. Only used when NEXT_PUBLIC_FLOWMERCE_DATA_SOURCE=demo.
 *
 * Daily figures are not stored: every figure is a fixed function of (ad or campaign, calendar day), so the same day
 * always shows the same numbers and the browser snapshot stays small. Money is in US dollars. Ridhi's Meta account is
 * billed in rupees; its figures are converted with the rate on the Rules tab, so changing the rate moves them.
 *
 * Collection `db.ads` holds only what a person can change:
 *   rules:   { ridhi|cpc: { fx_rate, fx_from, goal_daily_sales, bulk_order_min, ...thresholds } }
 *   status:  { ridhi|cpc: { [actionId]: 'done' | 'skipped' } }   (an action with no entry is open)
 *   history: [{ id, brand, action_id, title, status, by, at }]   newest first
 */
import { DemoError, hoursAgo } from '../util.js';

const DAY = 864e5;
const HISTORY_DAYS = 90;
const BASE_FX = 88;
const PLATFORMS = ['all', 'meta', 'google'];

const ACCOUNTS = {
  ridhi: { meta: { name: 'Demo Ridhi (Meta)', currency: 'INR', timezone: 'Asia/Kolkata' }, google: { name: 'Demo Ridhi (Google Ads)', currency: 'USD', timezone: 'Asia/Kolkata' } },
  cpc: { meta: { name: 'Demo CPC (Meta)', currency: 'USD', timezone: 'America/Chicago' }, google: { name: 'Demo CPC (Google Ads)', currency: 'USD', timezone: 'America/Chicago' } },
};

export const DEFAULT_RULES = {
  fx_rate: BASE_FX, goal_daily_sales: 20000, bulk_order_min: 1500,
  target_roas: 2.2, target_mer: 2.5, mer_floor: 2.2,
  gate_green_3d: 2.2, gate_green_7d: 2.0, gate_red: 1.8,
  budget_up_7d: 2.2, budget_up_3d: 1.8, budget_down_7d: 1.6, budget_down_3d: 1.4, budget_step_pct: 20,
  test_spend: 110, proven_spend: 220, stop_roas: 1.5, scale_roas: 2.2, scale_3d_roas: 1.8, scale_min_purchases: 5,
  graduate_min_purchases: 3, cbo_min_ads: 4, cbo_max_ads: 8,
};
const RULE_LIMITS = { fx_rate: [1, 500], goal_daily_sales: [100, 1e7], bulk_order_min: [50, 1e6], budget_step_pct: [1, 50], cbo_min_ads: [1, 50], cbo_max_ads: [1, 50] };

const LINES = { quilt: 'Quilt', rectangle: 'Rectangle tablecloth', round: 'Round tablecloth', stripe: 'Stripe tablecloth', skirt: 'Tree skirt', all: 'All products' };
const HOOKS = {
  quilt: ['Cloud-Soft Unboxing', 'Hotel Bed at Home', 'Cold Night Fix', 'Bedroom Makeover', 'Stylist Fold Trick', 'Five Reasons', 'Hand Block Story', 'Price Reveal'],
  rectangle: ['Dinner Party Hack', 'Did You Redecorate', 'Fall Table in 30 Seconds', 'Price Shock', 'Print Close-Up', 'Before and After', 'Hosting Season', 'Styled Table Static'],
  round: ['Will It Fit My Table', 'Round Table Problem', 'Drop Length Guide', 'Three Prints', 'Holiday Table for Six'],
  stripe: ['Scallop Edge Stop-Scroll', 'Sunday Brunch', 'Custom Size', 'Indoor to Outdoor', 'No Hidden Charges', 'Farmhouse Table'],
  skirt: ['Tree Skirt Reveal', 'Gift Idea', 'Heirloom Christmas', 'Under the Tree'],
  all: ['Bestsellers Catalog', 'Come Back Offer'],
};

/** Campaigns: [key, platform, type, product line, name, daily budget (USD), number of ads, typical ROAS]. */
const CAMPAIGNS = {
  ridhi: [
    ['cbo_quilt', 'meta', 'cbo', 'quilt', 'CBO | Sales | Demo Quilt | #4', 1100, 7, 1.65],
    ['cbo_table', 'meta', 'cbo', 'rectangle', 'CBO | Sales | Demo Tablecloth | #1', 420, 8, 2.1],
    ['cbo_stripe', 'meta', 'cbo', 'stripe', 'CBO | Sales | Demo Stripe Tablecloth | #5', 260, 5, 2.9],
    ['abo_table', 'meta', 'abo', 'rectangle', 'ABO | Demo Tablecloth Testing', 390, 14, 2.0],
    ['abo_quilt', 'meta', 'abo', 'quilt', 'ABO | Demo Quilt Testing', 280, 8, 2.6],
    ['abo_stripe', 'meta', 'abo', 'stripe', 'ABO | Demo Stripe Testing', 175, 8, 2.3],
    ['abo_round', 'meta', 'abo', 'round', 'ABO | Demo Round Tablecloth', 125, 5, 2.2],
    ['catalog', 'meta', 'catalog', 'all', 'Demo Catalog | All products', 160, 1, 1.3],
    ['retarget', 'meta', 'retargeting', 'all', 'Demo Retargeting', 40, 2, 1.6],
    ['g_pmax_table', 'google', 'pmax', 'rectangle', 'Demo PMax | Tablecloths', 35, 0, 2.1],
    ['g_pmax_round', 'google', 'pmax', 'round', 'Demo PMax | Round tablecloths', 29, 0, 1.8],
    ['g_pmax_quilt', 'google', 'pmax', 'quilt', 'Demo PMax | Quilts', 16, 0, 3.4],
    ['g_brand', 'google', 'search', 'all', 'Demo Brand | Search', 14, 0, 28],
    ['g_display', 'google', 'display', 'all', 'Demo Display | Seasonal sale', 12, 0, 0.4],
    ['g_shopping', 'google', 'shopping', 'rectangle', 'Demo Shopping | Rectangle', 0, 0, 0],
  ],
  cpc: [
    ['cbo_table', 'meta', 'cbo', 'rectangle', '#2 CBO | Demo Tablecloth | USA', 520, 7, 1.6],
    ['cbo_round', 'meta', 'cbo', 'round', '#4 CBO | Demo Round Tablecloth | USA', 250, 6, 1.9],
    ['cbo_quilt', 'meta', 'cbo', 'quilt', '#5 CBO | Demo Quilts | USA', 140, 4, 1.3],
    ['abo_quilt', 'meta', 'abo', 'quilt', 'ABO | Demo Quilt Test', 160, 8, 1.8],
    ['abo_table', 'meta', 'abo', 'rectangle', 'ABO | Demo Tablecloth Test', 160, 8, 1.7],
    ['abo_skirt', 'meta', 'abo', 'skirt', 'ABO | Demo Tree Skirt | Audience Test', 72, 4, 2.4],
    ['catalog', 'meta', 'catalog', 'all', '#3 Demo Catalog | Remarketing', 70, 1, 2.2],
    ['g_pmax_all', 'google', 'pmax', 'all', 'Demo PMax | All products', 40, 0, 2.4],
    ['g_brand', 'google', 'search', 'all', 'Demo Brand | Search', 8, 0, 22],
    ['g_search', 'google', 'search', 'rectangle', 'Demo Search | Block print tablecloth', 15, 0, 1.2],
  ],
};
const TYPE_LABEL = { cbo: 'CBO', abo: 'ABO', catalog: 'Catalog', retargeting: 'Retargeting', pmax: 'Performance Max', search: 'Search', display: 'Display', shopping: 'Shopping' };
const SEED = { ridhi: 31, cpc: 57 };
const STORE = { ridhi: { organic: 620, aov: 112, cvr: 0.016, bulkAgo: 4, bulk: 6200 }, cpc: { organic: 330, aov: 96, cvr: 0.014, bulkAgo: 9, bulk: 2400 } };

/* ------------------------------------------------------------------ dates and fixed "random" numbers */
const dayNum = (iso) => Math.round(Date.parse(`${iso}T00:00:00Z`) / DAY);
const isoOf = (n) => new Date(n * DAY).toISOString().slice(0, 10);
const todayNum = () => Math.floor(Date.now() / DAY);
/** A fixed number in [0, 1) for a set of whole numbers: the same inputs always give the same answer. */
function fixed(a, b = 0, c = 0) {
  let h = (Math.imul(a + 374761393, 668265263) ^ Math.imul(b + 1274126177, 2246822519) ^ Math.imul(c + 362437, 3266489917)) >>> 0;
  h = Math.imul(h ^ (h >>> 15), 2246822519) >>> 0;
  h = Math.imul(h ^ (h >>> 13), 3266489917) >>> 0;
  return ((h ^ (h >>> 16)) >>> 0) / 4294967296;
}
const round2 = (v) => Math.round(v * 100) / 100;
const ratio = (a, b) => (b > 0 ? round2(a / b) : null);
const pctOf = (a, b) => (b > 0 ? Math.round((a / b) * 1000) / 10 : null);

/* ------------------------------------------------------------------ the account: campaigns and ads (built once per brand) */
const built = {};
function account(brand) {
  if (built[brand]) return built[brand];
  const seed = SEED[brand];
  const now = todayNum();
  const campaigns = CAMPAIGNS[brand].map(([key, platform, type, line, name, budget, nAds, quality], ci) => ({
    key, id: `demo-${brand}-${key}`, platform, type, line, name, budget, quality, ci,
    status: budget > 0 ? 'ACTIVE' : 'PAUSED', is_brand: key === 'g_brand',
    // One CBO per brand had its budget changed yesterday, so its budget call is "hold for 72 hours".
    budget_changed_days_ago: key === 'cbo_table' || key === 'cbo_round' ? 1 : null, nAds,
  }));
  const ads = [];
  let n = 0;
  const addAd = (c, k, over = {}) => {
    const u = (j) => fixed(seed, c.ci * 100 + k, j);
    const hooks = HOOKS[c.line];
    const hook = over.hook ?? hooks[(k + c.ci) % hooks.length];
    const idx = n++;
    const code = over.code ?? `DM${100 + idx}`;
    const video = c.type !== 'catalog' && u(1) < 0.72;
    const testing = c.type === 'abo';
    const launchedAgo = over.launchedAgo ?? (testing ? 2 + Math.floor(u(2) * 44) : 18 + Math.floor(u(2) * 66));
    const roll = u(3);
    const status = c.type === 'catalog' ? 'ACTIVE' : roll < 0.66 ? 'ACTIVE' : roll < 0.84 ? 'PAUSED' : 'ADSET_PAUSED';
    const dud = testing && u(4) < 0.18;
    const strength = dud ? 0 : 0.66 + u(5) * 1.1;
    const hook3 = 0.13 + u(10) * 0.38;
    ads.push({
      idx, id: `99${String(seed).padStart(2, '0')}${String(1000000 + idx * 7919).slice(-7)}`, code, hook, campaign: c,
      post_id: over.post_id ?? `post-${brand}-${idx}`, copy_of: over.copy_of ?? null,
      name: `${code} | ${hook} | ${LINES[c.line]}`, format: video ? 'video' : 'image', status,
      launchDay: now - launchedAgo, endDay: status === 'ACTIVE' ? Infinity : now - 1 - Math.floor(u(6) * 6),
      weight: over.weight ?? (k === 0 ? 2.6 + u(7) * 1.6 : 0.35 + u(7) * 1.1),
      q: c.quality * strength * (over.lift ?? 1), fatigue: launchedAgo > 45 && u(8) < 0.5 ? 0.72 : 1,
      ctr: 0.021 + u(9) * 0.036, cpm: 42 + u(11) * 46, lpvRate: 0.9 + u(12) * 0.07, atcRate: 0.06 + u(13) * 0.15, icRate: 0.27 + u(14) * 0.1,
      aov: 92 + u(15) * 34, hook3, p25: hook3 * (0.35 + u(16) * 0.4), r50: 0.42 + u(17) * 0.2, r75: 0.5 + u(18) * 0.17, r95: 0.55 + u(19) * 0.18,
      watch: 4 + Math.round(u(20) * 5), length: 15 + Math.round(u(21) * 15),
      adset: c.type === 'cbo' ? `${c.name.split('|').pop().trim()}-${1 + (k % 2)}` : c.type === 'abo' ? `V${60 + idx} | ${hook}` : `${TYPE_LABEL[c.type]} ad set`,
    });
  };
  // Testing (ABO) campaigns first, so the scaling (CBO) campaigns can hold copies of their best ads.
  for (const c of campaigns.filter((x) => x.platform === 'meta' && x.type !== 'cbo')) for (let k = 0; k < c.nAds; k++) addAd(c, k);
  for (const c of campaigns.filter((x) => x.type === 'cbo')) {
    const source = ads.filter((a) => a.campaign.type === 'abo' && a.campaign.line === c.line).sort((a, b) => b.q - a.q);
    for (let k = 0; k < c.nAds; k++) {
      // The second-best and fourth-best test ads were already copied in; the best one was not (that is the "gap").
      const from = k >= 1 && k <= 2 ? source[k * 2 - 1] : null;
      addAd(c, k, from ? { code: from.code, hook: from.hook, post_id: from.post_id, copy_of: from.id, lift: 0.85 } : {});
    }
  }
  for (const c of campaigns.filter((x) => x.platform === 'meta')) {
    const mine = ads.filter((a) => a.campaign === c);
    const total = mine.reduce((s, a) => s + a.weight, 0);
    for (const a of mine) a.dailySpend = c.type === 'abo' ? c.budget / mine.length * (0.6 + fixed(seed, a.idx, 30) * 0.8) : c.budget * a.weight / total;
  }
  built[brand] = { brand, seed, campaigns, ads, cache: new Map() };
  return built[brand];
}

const ZERO = { spend: 0, impressions: 0, vimp: 0, clicks: 0, lpv: 0, atc: 0, ic: 0, purchases: 0, value: 0, v3: 0, p25: 0, p50: 0, p75: 0, p95: 0 };
const add = (t, r) => { for (const k of Object.keys(ZERO)) t[k] += r[k] ?? 0; return t; };

/** One Meta ad on one day (US dollars at the base rate). */
function adDay(acc, ad, d) {
  if (d < ad.launchDay || d > ad.endDay || d >= todayNum()) return null;
  const key = `a${ad.idx}:${d}`;
  if (acc.cache.has(key)) return acc.cache.get(key);
  const u = (j) => fixed(acc.seed * 131 + ad.idx, d, j);
  const spend = ad.dailySpend * (0.72 + u(1) * 0.56);
  const impressions = Math.round(spend / ad.cpm * 1000);
  const clicks = Math.round(impressions * ad.ctr * (0.85 + u(2) * 0.3));
  const lpv = Math.round(clicks * ad.lpvRate);
  const atc = Math.round(lpv * ad.atcRate * (0.7 + u(3) * 0.6));
  const recent = todayNum() - d <= 10 ? ad.fatigue : 1;
  const purchases = Math.min(atc, Math.floor(spend * ad.q * recent / ad.aov + u(4)));
  const video = ad.format === 'video';
  const v3 = video ? Math.round(impressions * ad.hook3) : 0;
  const p25 = video ? Math.round(impressions * ad.p25) : 0;
  const p50 = Math.round(p25 * ad.r50);
  const p75 = Math.round(p50 * ad.r75);
  const row = { spend, impressions, vimp: video ? impressions : 0, clicks, lpv, atc, ic: Math.max(purchases, Math.round(atc * ad.icRate)), purchases, value: purchases * ad.aov * (0.85 + u(5) * 0.3), v3, p25, p50, p75, p95: Math.round(p75 * ad.r95) };
  acc.cache.set(key, row);
  return row;
}
const sumAd = (acc, ad, from, to) => { const t = { ...ZERO }; for (let d = Math.max(from, ad.launchDay); d <= to; d++) { const r = adDay(acc, ad, d); if (r) add(t, r); } return t; };

/** One Google campaign on one day. */
function googleDay(acc, c, d) {
  if (c.budget <= 0 || d >= todayNum()) return null;
  const u = (j) => fixed(acc.seed * 977 + c.ci, d, j);
  const spend = c.budget * (0.6 + u(1) * 0.7);
  const cpc = c.type === 'search' ? 0.38 + u(2) * 0.3 : 0.55 + u(2) * 0.5;
  const clicks = Math.max(1, Math.round(spend / cpc));
  const aov = 96 + u(3) * 40;
  const purchases = Math.floor(spend * c.quality / aov + u(4));
  return { ...ZERO, spend, impressions: Math.round(clicks / (c.type === 'search' ? 0.42 : c.type === 'display' ? 0.09 : 0.028)), clicks, purchases, value: purchases * aov * (0.85 + u(5) * 0.3) };
}
const sumGoogle = (acc, c, from, to) => { const t = { ...ZERO }; for (let d = from; d <= to; d++) { const r = googleDay(acc, c, d); if (r) add(t, r); } return t; };

/** A platform's totals for a span of days, in reporting dollars (Ridhi's Meta figures follow the rupee rate). */
function platformTotals(acc, platform, from, to, fx) {
  const t = { ...ZERO };
  if (platform === 'meta') {
    for (const ad of acc.ads) add(t, sumAd(acc, ad, from, to));
    t.spend *= fx; t.value *= fx;
  } else for (const c of acc.campaigns.filter((x) => x.platform === 'google')) add(t, sumGoogle(acc, c, from, to));
  return t;
}

/** The store's own sales for one day (what Shopify reports), with the bulk order kept apart. */
function storeDay(acc, d, rules) {
  if (d >= todayNum()) return null;
  const key = `s:${d}`;
  let base = acc.cache.get(key);
  if (!base) {
    const meta = platformTotals(acc, 'meta', d, d, 1);
    const google = platformTotals(acc, 'google', d, d, 1);
    const s = STORE[acc.brand];
    const u = (j) => fixed(acc.seed * 53, d, j);
    const sales = meta.value * (0.95 + u(1) * 0.2) + google.value * 0.62 + s.organic * (0.6 + u(2) * 0.8);
    const orders = Math.max(1, Math.round(sales / (s.aov * (0.92 + u(3) * 0.16))));
    base = { sales, orders, sessions: Math.round(orders / (s.cvr * (0.85 + u(4) * 0.3))), bulk: todayNum() - d === s.bulkAgo ? s.bulk : 0 };
    acc.cache.set(key, base);
  }
  const bulk = base.bulk >= rules.bulk_order_min ? base.bulk : 0;
  return { sales: base.sales + base.bulk, sales_ex_bulk: base.sales + base.bulk - bulk, orders: base.orders + (base.bulk ? 1 : 0), bulk_orders: bulk ? 1 : 0, bulk_amount: bulk, sessions: base.sessions };
}
function storeTotals(acc, from, to, rules) {
  const t = { sales: 0, sales_ex_bulk: 0, orders: 0, bulk_orders: 0, bulk_amount: 0, sessions: 0 };
  for (let d = from; d <= to; d++) { const r = storeDay(acc, d, rules); if (r) for (const k of Object.keys(t)) t[k] += r[k]; }
  return t;
}

/* ------------------------------------------------------------------ request context and small builders */
function ctx(query, db) {
  const brand = query.brand;
  if (!ACCOUNTS[brand]) throw new DemoError(400, "brand must be 'ridhi' or 'cpc'. Ads shows one brand at a time.", 'bad_request');
  const platform = PLATFORMS.includes(query.platform) ? query.platform : 'all';
  const ok = (v) => /^\d{4}-\d{2}-\d{2}$/.test(v ?? '');
  const last = todayNum() - 1;
  const to = ok(query.to) ? Math.min(dayNum(query.to), last) : last;
  const from = ok(query.from) ? Math.min(dayNum(query.from), to) : to - 6;
  if (to - from > 366) throw new DemoError(400, 'Pick at most 366 days.', 'bad_request');
  const days = to - from + 1;
  // The same comparisons as the Python module: previous period (default), previous year (same dates or same
  // weekdays), custom (?cfrom= first day, same length) or none. The demo keeps 90 days, so a year back is empty.
  let compare = COMPARES.includes(query.compare) ? query.compare : 'previous';
  if (compare === 'custom' && !ok(query.cfrom)) compare = 'previous';
  if (compare === 'custom' && dayNum(query.cfrom) >= from) throw new DemoError(400, 'The comparison must start before the chosen days.', 'bad_request');
  const prevFrom = compare === 'previous_year' ? dayNum(yearBack(isoOf(from))) : compare === 'previous_year_dow' ? from - 364
    : compare === 'custom' ? dayNum(query.cfrom) : from - days;
  const rules = db.ads.rules[brand];
  return { brand, platform, from, to, days, compare, prevFrom, prevTo: prevFrom + days - 1, rules, acc: account(brand), fx: brand === 'ridhi' ? BASE_FX / rules.fx_rate : 1 };
}
const COMPARES = ['previous', 'previous_year', 'previous_year_dow', 'custom', 'none'];
/** The same date a year earlier (29 February becomes the 28th). */
const yearBack = (iso) => (iso.slice(5) === '02-29' ? `${Number(iso.slice(0, 4)) - 1}-02-28` : `${Number(iso.slice(0, 4)) - 1}${iso.slice(4)}`);
const COMPARE_LABEL = { previous_year: 'same dates last year', previous_year_dow: 'last year, same weekdays' };
const info = (c) => ({ brand: c.brand, platform: c.platform, from: isoOf(c.from), to: isoOf(c.to), days: c.days,
  compare: c.compare === 'none' ? null : { key: c.compare, from: isoOf(c.prevFrom), to: isoOf(c.prevTo),
    label: COMPARE_LABEL[c.compare] ?? (c.compare === 'custom' ? `${isoOf(c.prevFrom)} – ${isoOf(c.prevTo)}` : c.days === 1 ? 'the day before' : `previous ${c.days} days`) } });
const block = (value, base) => ({ value: value === null ? null : round2(value), baseline_value: base === null || base === undefined ? null : round2(base),
  change_pct: base === null || base === undefined || !base || value === null ? null : Math.round((value / base - 1) * 1000) / 10 });
const div = (a, b) => (b > 0 ? a / b : null);
const spendOf = (c, from, to, platform = c.platform) => ['meta', 'google'].filter((p) => platform === 'all' || platform === p).map((p) => platformTotals(c.acc, p, from, to, c.fx));

/** MER without bulk orders for the n days ending on `to`. */
function merFor(c, n, to = c.to) {
  const spend = platformTotals(c.acc, 'meta', to - n + 1, to, c.fx).spend + platformTotals(c.acc, 'google', to - n + 1, to, 1).spend;
  return div(storeTotals(c.acc, to - n + 1, to, c.rules).sales_ex_bulk, spend);
}
function gateOf(c) {
  const r = c.rules;
  const m3 = merFor(c, 3), m7 = merFor(c, 7);
  const state = m3 >= r.gate_green_3d && m7 >= r.gate_green_7d ? 'green' : Math.min(m3, m7) < r.gate_red ? 'red' : 'amber';
  const avgSpend = (platformTotals(c.acc, 'meta', c.to - 6, c.to, c.fx).spend + platformTotals(c.acc, 'google', c.to - 6, c.to, 1).spend) / 7;
  const factor = state === 'green' ? 1 + r.budget_step_pct / 100 : state === 'red' ? 1 - r.budget_step_pct * 0.75 / 100 : 1;
  return { state, mer_3d: round2(m3), mer_7d: round2(m7), avg_daily_spend_7d: Math.round(avgSpend), recommended_daily_spend: Math.round(avgSpend * factor / 10) * 10,
    advice: state === 'green' ? `Raise total spend by up to ${r.budget_step_pct}% over the next 72 hours.` : state === 'red' ? 'Cut total spend by 10 to 20% and fix from inside the campaigns.' : 'Hold total spend and move budget to the better campaigns.' };
}
const dayColour = (mer, r) => (mer === null ? null : mer >= r.gate_green_3d ? 'green' : mer >= r.gate_red ? 'amber' : 'red');

/* ------------------------------------------------------------------ Meta ads: figures, verdicts and weakest step */
function adFigures(c, ad) {
  const s = (from, to) => { const t = sumAd(c.acc, ad, from, to); t.spend *= c.fx; t.value *= c.fx; return t; };
  const cur = s(c.from, c.to), d7 = s(c.to - 6, c.to), d3 = s(c.to - 2, c.to), d14 = s(c.to - 13, c.to), life = s(ad.launchDay, c.to), prev = s(c.prevFrom, c.prevTo);
  return { cur, d7, d3, d14, life, prev };
}
/** The rule set from the Rules tab, applied to one ad. Returns [verdict, the reason in words]. */
function verdictOf(ad, f, r) {
  const roas = (t) => div(t.value, t.spend) ?? 0;
  const money = (v) => `$${Math.round(v)}`;
  if (f.life.spend < r.test_spend) return ['testing', `In test: ${money(f.life.spend)} of ${money(r.test_spend)} spent.`];
  if (f.life.purchases === 0) return ['stop', `No purchase after ${money(f.life.spend)} (test limit ${money(r.test_spend)}).`];
  if (f.life.spend < r.proven_spend) return ['continue', `${f.life.purchases} purchase${f.life.purchases === 1 ? '' : 's'} at ${money(f.life.spend)}: continue to ${money(r.proven_spend)}.`];
  if (f.d7.spend >= r.test_spend && roas(f.d7) < r.stop_roas) return ['stop', `7-day ROAS ${roas(f.d7).toFixed(2)} on ${money(f.d7.spend)} (stop below ${r.stop_roas}).`];
  if (roas(f.life) < r.stop_roas) return ['stop', `Lifetime ROAS ${roas(f.life).toFixed(2)} on ${money(f.life.spend)} (stop below ${r.stop_roas}).`];
  if (roas(f.d7) >= r.scale_roas && f.d7.purchases >= r.scale_min_purchases && roas(f.d3) >= r.scale_3d_roas)
    return ['scale', `7-day ROAS ${roas(f.d7).toFixed(2)} with ${f.d7.purchases} purchases, 3-day ${roas(f.d3).toFixed(2)}.`];
  if (ad.campaign.type === 'abo' && roas(f.life) >= r.scale_roas && f.life.purchases >= r.graduate_min_purchases)
    return ['graduate', `Lifetime ROAS ${roas(f.life).toFixed(2)} with ${f.life.purchases} purchases: ready for the scaling campaign.`];
  if (roas(f.d7) < r.scale_roas && f.d7.spend > 0) return ['iterate', `7-day ROAS ${roas(f.d7).toFixed(2)} is between ${r.stop_roas} and ${r.scale_roas}.`];
  return ['hold', `Lifetime ROAS ${roas(f.life).toFixed(2)}; nothing to change.`];
}
/**
 * Where an ad loses people first. The limits are placeholders for the screens (docs/plans/ads-module.md lists them as
 * still to be agreed): hook under 20% of impressions, CTR under 2.5%, add to cart under 9% of page views, purchases
 * under 8% of carts. Needs at least 300 impressions.
 */
function weakest(ad, t) {
  if (t.impressions < 300) return { key: 'early', label: 'Too early' };
  if (ad.format === 'video' && t.v3 / t.vimp < 0.2) return { key: 'hook', label: 'Hook' };
  if (t.clicks / t.impressions < 0.025) return { key: 'click', label: ad.format === 'video' ? 'Call to action' : 'Image' };
  if (t.lpv >= 20 && t.atc / t.lpv < 0.09) return { key: 'landing', label: 'Landing page' };
  if (t.atc >= 10 && t.purchases / t.atc < 0.08) return { key: 'checkout', label: 'Checkout' };
  return { key: 'none', label: 'None' };
}
function adRow(c, ad) {
  const f = adFigures(c, ad);
  const [verdict, reason] = verdictOf(ad, f, c.rules);
  const t = f.cur;
  return {
    id: ad.id, code: ad.code, name: ad.name, hook: ad.hook, format: ad.format, status: ad.status, post_id: ad.post_id,
    campaign_id: ad.campaign.id, campaign: ad.campaign.name, campaign_type: ad.campaign.type, product_line: ad.campaign.line, ad_set: ad.adset,
    launched: isoOf(ad.launchDay), days_live: c.to - ad.launchDay + 1, is_new: c.to - ad.launchDay < 7,
    verdict, reason, weakest: weakest(ad, f.d14.impressions > t.impressions ? f.d14 : t),
    spend: round2(t.spend), purchases: t.purchases, value: round2(t.value), roas: ratio(t.value, t.spend), cpa: ratio(t.spend, t.purchases),
    prev_roas: ratio(f.prev.value, f.prev.spend), roas_3d: ratio(f.d3.value, f.d3.spend), roas_7d: ratio(f.d7.value, f.d7.spend), roas_14d: ratio(f.d14.value, f.d14.spend),
    spend_7d: round2(f.d7.spend), purchases_7d: f.d7.purchases,
    lifetime: { spend: round2(f.life.spend), purchases: f.life.purchases, roas: ratio(f.life.value, f.life.spend) },
    impressions: t.impressions, ctr: pctOf(t.clicks, t.impressions), cpm: ratio(t.spend * 1000, t.impressions), lpv: t.lpv, atc: t.atc,
    atc_rate: pctOf(t.atc, t.lpv), purchase_rate: pctOf(t.purchases, t.atc),
    video: ad.format === 'video' ? { hook_rate: pctOf(t.v3, t.vimp), hook_25: pctOf(t.p25, t.vimp), to_50: pctOf(t.p50, t.p25), to_75: pctOf(t.p75, t.p50), to_95: pctOf(t.p95, t.p75), avg_watch_s: ad.watch, length_s: ad.length } : null,
  };
}
const metaAds = (c) => c.acc.ads.map((ad) => adRow(c, ad));

/* ------------------------------------------------------------------ campaigns */
function budgetCall(camp, roas7, roas3, r) {
  if (camp.type !== 'cbo') return null;
  const step = r.budget_step_pct;
  if (camp.budget_changed_days_ago !== null && camp.budget_changed_days_ago < 3) return { key: 'hold', label: 'Hold', why: 'The budget changed in the last 72 hours.', new_budget: null };
  if (roas7 >= r.budget_up_7d && roas3 >= r.budget_up_3d)
    return { key: 'increase', label: `Raise ${step}%`, why: `7-day ROAS ${roas7.toFixed(2)} and 3-day ${roas3.toFixed(2)} are both above the raise line.`, new_budget: Math.round(camp.budget * (1 + step / 100)) };
  if (roas7 < r.budget_down_7d || roas3 < r.budget_down_3d)
    return { key: 'decrease', label: `Lower ${step}%`, why: `7-day ROAS ${roas7.toFixed(2)}, 3-day ${roas3.toFixed(2)}: below the lower line.`, new_budget: Math.round(camp.budget * (1 - step / 100)) };
  return { key: 'hold', label: 'Hold', why: `7-day ROAS ${roas7.toFixed(2)} is between ${r.budget_down_7d} and ${r.budget_up_7d}.`, new_budget: null };
}
function campaignRows(c) {
  const ads = c.platform === 'google' ? [] : metaAds(c);
  const rows = [];
  for (const camp of c.acc.campaigns) {
    if (c.platform !== 'all' && camp.platform !== c.platform) continue;
    const row = { id: camp.id, platform: camp.platform, name: camp.name, type: camp.type, type_label: TYPE_LABEL[camp.type], product_line: camp.line, status: camp.status,
      is_brand: camp.is_brand, daily_budget: camp.type === 'abo' ? null : camp.budget * (camp.platform === 'meta' ? c.fx : 1) };
    if (camp.platform === 'meta') {
      const mine = ads.filter((a) => a.campaign_id === camp.id);
      const own = c.acc.ads.filter((a) => a.campaign === camp);
      const span = (from, to) => { const t = { ...ZERO }; for (const a of own) add(t, sumAd(c.acc, a, from, to)); t.spend *= c.fx; t.value *= c.fx; return t; };
      const cur = span(c.from, c.to), prev = span(c.prevFrom, c.prevTo), d7 = span(c.to - 6, c.to), d3 = span(c.to - 2, c.to);
      const delivering = own.filter((a) => sumAd(c.acc, a, c.to - 2, c.to).spend > 0);
      const top = [...mine].sort((a, b) => b.spend_7d - a.spend_7d)[0];
      const groups = [...new Set(mine.map((a) => a.ad_set))].map((name) => {
        const g = mine.filter((a) => a.ad_set === name);
        const sp = g.reduce((s, a) => s + a.spend, 0), val = g.reduce((s, a) => s + a.value, 0);
        return { name, kind: 'ad_set', ads: g.length, active_ads: g.filter((a) => a.status === 'ACTIVE').length, spend: round2(sp), purchases: g.reduce((s, a) => s + a.purchases, 0), roas: ratio(val, sp) };
      }).sort((a, b) => b.spend - a.spend);
      Object.assign(row, figures(cur, prev), { roas_3d: ratio(d3.value, d3.spend), roas_7d: ratio(d7.value, d7.spend), atc: cur.atc, frequency: round2(1.1 + fixed(c.acc.seed, camp.ci, 9) * 0.9),
        groups, ads: mine.length, active_ads: mine.filter((a) => a.status === 'ACTIVE').length,
        health: camp.type === 'cbo' ? { delivering_ads: delivering.length, min_ads: c.rules.cbo_min_ads, max_ads: c.rules.cbo_max_ads,
          top_ad: top ? top.code : null, top_ad_share: top && d7.spend ? Math.round(top.spend_7d / d7.spend * 100) : null,
          call: budgetCall(camp, div(d7.value, d7.spend) ?? 0, div(d3.value, d3.spend) ?? 0, c.rules) } : null });
    } else {
      const cur = sumGoogle(c.acc, camp, c.from, c.to), prev = sumGoogle(c.acc, camp, c.prevFrom, c.prevTo), d3 = sumGoogle(c.acc, camp, c.to - 2, c.to), d7 = sumGoogle(c.acc, camp, c.to - 6, c.to);
      Object.assign(row, figures(cur, prev), { roas_3d: ratio(d3.value, d3.spend), roas_7d: ratio(d7.value, d7.spend), atc: null, frequency: null, groups: [], ads: null, active_ads: null, health: null });
    }
    rows.push(row);
  }
  return rows.sort((a, b) => b.spend - a.spend);
}
const figures = (cur, prev) => ({ spend: round2(cur.spend), purchases: cur.purchases, value: round2(cur.value), roas: ratio(cur.value, cur.spend), cpa: ratio(cur.spend, cur.purchases),
  prev_spend: round2(prev.spend), prev_roas: ratio(prev.value, prev.spend), impressions: cur.impressions, clicks: cur.clicks, ctr: pctOf(cur.clicks, cur.impressions), cpm: ratio(cur.spend * 1000, cur.impressions) });

/* ------------------------------------------------------------------ ABO to CBO gap */
function gapPairs(c) {
  const ads = metaAds({ ...c, from: c.to - 6, prevFrom: c.to - 13, prevTo: c.to - 7 });
  const pairs = [];
  for (const test of c.acc.campaigns.filter((x) => x.type === 'abo')) {
    const scale = c.acc.campaigns.find((x) => x.type === 'cbo' && x.line === test.line);
    const inScale = new Set(scale ? ads.filter((a) => a.campaign_id === scale.id).map((a) => a.post_id) : []);
    const rows = ads.filter((a) => a.campaign_id === test.id).map((a) => {
      const already = inScale.has(a.post_id);
      // "Proven" is the lifetime rule the tab states (spend, ROAS and purchases since the ad started), not the 7-day verdict.
      const lt = a.lifetime;
      const proven = lt.spend >= c.rules.proven_spend && (lt.roas ?? 0) >= c.rules.scale_roas && lt.purchases >= c.rules.graduate_min_purchases;
      const verdict = !scale ? (proven ? 'watch' : a.verdict === 'stop' ? 'stop' : 'early') : already ? 'already' : proven ? 'add' : a.verdict === 'stop' ? 'stop'
        : (lt.roas ?? 0) >= c.rules.scale_roas && lt.purchases >= 1 ? 'watch' : 'early';
      const why = already ? `Already running in ${scale.name}.`
        : proven ? `Lifetime ROAS ${lt.roas.toFixed(2)} with ${lt.purchases} purchases on $${Math.round(lt.spend)}.` : a.reason;
      return { id: a.id, code: a.code, name: a.name, status: a.status, verdict, why,
        spend: a.lifetime.spend, purchases: a.lifetime.purchases, roas: a.lifetime.roas, cpa: ratio(a.lifetime.spend, a.lifetime.purchases), ctr: a.ctr, roas_7d: a.roas_7d };
    });
    const order = { add: 0, watch: 1, already: 2, stop: 3, early: 4 };
    rows.sort((x, y) => order[x.verdict] - order[y.verdict] || (y.roas ?? 0) - (x.roas ?? 0));
    pairs.push({ test_campaign: test.name, scale_campaign: scale?.name ?? null, product_line: test.line, missing: rows.filter((r) => r.verdict === 'add').length, rows,
      note: scale ? null : 'This product has no scaling campaign: proven ads stay in the testing campaign.' });
  }
  return pairs;
}

/* ------------------------------------------------------------------ rule-based suggestions */
function actionList(c, db) {
  const recent = { ...c, from: c.to - 6, prevFrom: c.to - 13, prevTo: c.to - 7, days: 7, platform: 'meta' };
  const out = [];
  const push = (a) => out.push({ platform: 'meta', confidence: 'Medium', daily_impact: 0, ...a, status: db.ads.status[c.brand][a.id] ?? 'open' });
  const camps = campaignRows(recent);
  for (const camp of camps.filter((x) => x.health?.call && x.health.call.key !== 'hold')) {
    const call = camp.health.call;
    push({ id: `budget:${camp.id}`, group: 'budget', title: camp.name, where: 'Campaign budget', current: `$${Math.round(camp.daily_budget)}/day`, proposed: `$${call.new_budget}/day`,
      evidence: call.why, confidence: 'High', daily_impact: call.new_budget - Math.round(camp.daily_budget) });
  }
  const ads = metaAds(recent);
  for (const a of ads.filter((x) => x.verdict === 'stop' && x.status === 'ACTIVE' && x.campaign_type !== 'catalog').sort((x, y) => y.spend_7d - x.spend_7d).slice(0, 6))
    push({ id: `stop:${a.id}`, group: 'stop', title: a.name, where: `${a.campaign} › ${a.ad_set}`, current: 'Active', proposed: 'Paused', evidence: a.reason,
      confidence: a.lifetime.purchases === 0 ? 'High' : 'Medium', daily_impact: a.campaign_type === 'abo' ? -Math.round(a.spend_7d / 7) : 0 });
  for (const pair of gapPairs(c)) for (const r of pair.rows.filter((x) => x.verdict === 'add').slice(0, 2))
    push({ id: `add:${r.id}`, group: 'refresh', title: `Add ${r.code} to ${pair.scale_campaign}`, where: `${pair.scale_campaign} (use the existing post)`, current: `Only in ${pair.test_campaign}`, proposed: 'Running in the scaling campaign',
      evidence: `Lifetime ROAS ${r.roas?.toFixed(2)} with ${r.purchases} purchases on $${Math.round(r.spend)}.`, confidence: 'Medium' });
  for (const a of ads.filter((x) => x.verdict === 'iterate' && x.status === 'ACTIVE' && !['none', 'early'].includes(x.weakest.key)).sort((x, y) => y.spend_7d - x.spend_7d).slice(0, 3))
    push({ id: `iterate:${a.id}`, group: 'iterate', title: a.name, where: `${a.campaign} › ${a.ad_set}`, current: `7-day ROAS ${a.roas_7d?.toFixed(2) ?? 'n/a'}`, proposed: `New version that fixes the ${a.weakest.label.toLowerCase()}`,
      evidence: `${a.reason} Weakest step: ${a.weakest.label}.` });
  const order = { stop: 0, refresh: 1, budget: 2, iterate: 3 };
  return out.sort((a, b) => order[a.group] - order[b.group]).map((a, i) => ({ n: i + 1, ...a }));
}

/* ------------------------------------------------------------------ Google: keywords, search terms, products */
const SEARCH = {
  ridhi: { keywords: [['demo ridhi', 'BROAD', true], ['demo ridhi tablecloth', 'PHRASE', true], ['block print tablecloth', 'BROAD', false], ['round cotton tablecloth', 'PHRASE', false], ['hand block quilt', 'BROAD', false], ['scallop tablecloth', 'EXACT', false]],
    terms: [['demo ridhi', true], ['demo ridhi block print', true], ['demo ridi', true], ['block print tablecloth 60 x 90', false], ['round tablecloth 70 inch cotton', false], ['indian quilt queen', false], ['scalloped stripe tablecloth', false], ['cotton tablecloth rectangle washable', false]],
    products: ['Demo Round Tablecloth | Blush 70 in', 'Demo Round Tablecloth | Garnet 120 in', 'Demo Rectangle Tablecloth | Indigo 60 x 102', 'Demo Quilt | Sage Queen', 'Demo Pillow Cover | Rust 18 in', 'Demo Table Runner | Ochre 72 in'] },
  cpc: { keywords: [['demo cotton print club', 'BROAD', true], ['demo cpc tablecloth', 'PHRASE', true], ['block print tablecloth', 'BROAD', false], ['cotton quilt king', 'PHRASE', false]],
    terms: [['demo cotton print club', true], ['demo cotton print', true], ['block print tablecloth round', false], ['cotton quilt king size', false], ['tree skirt block print', false]],
    products: ['Demo Round Tablecloth | Jade 60 in', 'Demo Rectangle Tablecloth | Mocha 60 x 84', 'Demo Quilt | Indigo King', 'Demo Tree Skirt | Red 48 in'] },
};
function googleDetail(c) {
  const camps = c.acc.campaigns.filter((x) => x.platform === 'google');
  const total = (pick) => { const t = { ...ZERO }; for (const camp of camps.filter(pick)) add(t, sumGoogle(c.acc, camp, c.from, c.to)); return t; };
  const split = (t, list, salt, map) => {
    const w = list.map((_, i) => 0.3 + fixed(c.acc.seed, salt, i) * (i === 0 ? 4 : 1.2));
    const sum = w.reduce((a, b) => a + b, 0);
    return list.map((item, i) => {
      const share = w[i] / sum;
      const purchases = Math.round(t.purchases * share), spend = t.spend * share, value = t.value * share;
      return { ...map(item), spend: round2(spend), clicks: Math.round(t.clicks * share), impressions: Math.round(t.impressions * share), purchases, value: round2(purchases ? value : 0), roas: purchases ? ratio(value, spend) : 0 };
    }).sort((a, b) => b.spend - a.spend);
  };
  const s = SEARCH[c.brand];
  const brand = total((x) => x.is_brand), generic = total((x) => x.type === 'search' && !x.is_brand), shop = total((x) => x.type === 'pmax' || x.type === 'shopping');
  const kw = (list, t, salt) => split(t, list, salt, ([text, match]) => ({ text, match_type: match, is_brand: list === s.keywords.filter((k) => k[2]) }));
  const brandKw = s.keywords.filter((k) => k[2]), otherKw = s.keywords.filter((k) => !k[2]);
  const brandTerms = s.terms.filter((k) => k[1]), otherTerms = s.terms.filter((k) => !k[1]);
  return {
    keywords: [...kw(brandKw, brand, 1).map((r) => ({ ...r, is_brand: true })), ...kw(otherKw, generic, 2).map((r) => ({ ...r, is_brand: false }))].sort((a, b) => b.spend - a.spend),
    terms: [...split(brand, brandTerms, 3, ([term]) => ({ term, is_brand: true })), ...split(generic, otherTerms, 4, ([term]) => ({ term, is_brand: false }))].sort((a, b) => b.spend - a.spend),
    products: split(shop, s.products, 5, (title) => ({ title })),
    brand_share: { spend: round2(brand.spend), value: round2(brand.value), total_value: round2(total(() => true).value), total_spend: round2(total(() => true).spend) },
  };
}

/* ------------------------------------------------------------------ seed and routes */
export function seed(db) {
  const from = isoOf(todayNum() - 60);
  db.ads = {
    rules: { ridhi: { ...DEFAULT_RULES, fx_from: from }, cpc: { ...DEFAULT_RULES, fx_from: from, goal_daily_sales: 8000 } },
    status: { ridhi: {}, cpc: {} },
    history: [],
  };
}

const GLOSSARY = [
  ['MER', 'Store sales divided by all ad spend (Meta and Google together). The store-level answer to "are the ads paying?".'],
  ['ROAS', 'Sales an ad platform claims, divided by what was spent on that platform. Two platforms can both claim the same order.'],
  ['CPA', 'Spend divided by purchases: the cost of one order.'],
  ['AOV', 'Store sales divided by orders (bulk orders left out).'],
  ['CTR', 'Of the people who saw the ad, the share who clicked through to the website.'],
  ['Hook rate', 'Of the times a video was shown, the share watched for at least 3 seconds. Low means the first frame does not stop the scroll.'],
  ['25% to 95%', 'Of the viewers at one point of a video, the share who reach the next. A sharp fall shows where the video loses people.'],
  ['Add-to-cart rate', 'Of the people whose page loaded, the share who added to cart. Low with a good CTR points at the page or the offer, not the ad.'],
  ['CBO / ABO', 'CBO: one budget for the campaign, shared by its ads (used for scaling). ABO: a budget per ad set (used for testing).'],
  ['Scaling gate', 'Red, amber or green from the 3-day and 7-day MER without bulk orders. It says whether total spend may go up.'],
  ['Bulk order', 'One unusually large order. Left out of the "excl. bulk" figures so a single order does not hide a weak day.'],
];

export const routes = [
  ['GET', '/ads/settings', ({ query, db }) => {
    const c = ctx(query, db);
    return { brand: c.brand, reporting_currency: 'USD', today: isoOf(todayNum()), data_from: isoOf(todayNum() - HISTORY_DAYS),
      product_lines: [...new Set(c.acc.campaigns.map((x) => x.line))].map((key) => ({ key, label: LINES[key] })),
      accounts: ['meta', 'google'].map((p) => ({ platform: p, ...ACCOUNTS[c.brand][p], status: 'ok', last_read_at: hoursAgo(0.6),
        token_days_left: p === 'meta' ? 57 : null, converted_at: ACCOUNTS[c.brand][p].currency === 'INR' ? c.rules.fx_rate : null })) };
  }],
  ['GET', '/ads/overview', ({ query, db }) => {
    const c = ctx(query, db);
    const side = (from, to) => {
      const parts = spendOf(c, from, to), allSpend = spendOf(c, from, to, 'all');
      const store = storeTotals(c.acc, from, to, c.rules);
      const spend = parts.reduce((s, t) => s + t.spend, 0), value = parts.reduce((s, t) => s + t.value, 0), purchases = parts.reduce((s, t) => s + t.purchases, 0);
      const total = allSpend.reduce((s, t) => s + t.spend, 0);
      return { spend, value, purchases, roas: div(value, spend), cpa: div(spend, purchases), total_spend: total, sales: store.sales, sales_ex_bulk: store.sales_ex_bulk, orders: store.orders,
        mer: div(store.sales, total), mer_ex_bulk: div(store.sales_ex_bulk, total), cost_per_order: div(total, store.orders), aov: div(store.sales_ex_bulk, store.orders - store.bulk_orders), bulk_orders: store.bulk_orders, bulk_amount: store.bulk_amount };
    };
    const cur = side(c.from, c.to);
    const prev = c.compare === 'none' ? null : side(c.prevFrom, c.prevTo);
    // With both platforms chosen there is no single ROAS: platform sales are never added together (see `platforms`).
    const own = c.platform === 'all' ? [] : ['roas', 'value', 'purchases', 'cpa'];
    const metrics = Object.fromEntries(['spend', 'total_spend', 'sales', 'sales_ex_bulk', 'mer', 'mer_ex_bulk', 'orders', 'aov', 'cost_per_order', ...own].map((k) => [k, block(cur[k], prev ? prev[k] : null)]));
    const trendFrom = Math.min(c.from, c.to - 13);
    const trend = [];
    for (let d = Math.max(trendFrom, c.to - 59); d <= c.to; d++) {
      const meta = platformTotals(c.acc, 'meta', d, d, c.fx), google = platformTotals(c.acc, 'google', d, d, 1), store = storeDay(c.acc, d, c.rules);
      const mer = div(store.sales_ex_bulk, meta.spend + google.spend);
      trend.push({ date: isoOf(d), meta_spend: round2(meta.spend), google_spend: round2(google.spend), spend: round2(meta.spend + google.spend), sales: round2(store.sales), sales_ex_bulk: round2(store.sales_ex_bulk),
        mer: ratio(store.sales, meta.spend + google.spend), mer_ex_bulk: mer === null ? null : round2(mer), meta_roas: ratio(meta.value, meta.spend), google_roas: ratio(google.value, google.spend),
        purchases: meta.purchases + google.purchases, orders: store.orders, colour: dayColour(mer, c.rules), in_range: d >= c.from });
    }
    const platforms = ['meta', 'google'].map((p) => {
      const t = platformTotals(c.acc, p, c.from, c.to, p === 'meta' ? c.fx : 1), b = prev ? platformTotals(c.acc, p, c.prevFrom, c.prevTo, p === 'meta' ? c.fx : 1) : null;
      return { platform: p, account: ACCOUNTS[c.brand][p].name, spend: round2(t.spend), purchases: t.purchases, value: round2(t.value), roas: ratio(t.value, t.spend), cpa: ratio(t.spend, t.purchases),
        prev_roas: b ? ratio(b.value, b.spend) : null, prev_spend: b ? round2(b.spend) : null, share_of_spend: pctOf(t.spend, cur.total_spend) };
    });
    const week = side(c.to - 6, c.to);
    const gate = gateOf(c);
    const goal = c.rules.goal_daily_sales;
    return { ...info(c), metrics, gate, platforms, trend, meta_saved_to: isoOf(c.to),
      goal: { daily_sales_goal: goal, avg_sales_7d: Math.round(week.sales_ex_bulk / 7), avg_spend_7d: Math.round(week.total_spend / 7), mer_7d: gate.mer_7d,
        pct_of_goal: Math.round(week.sales_ex_bulk / 7 / goal * 100), gap: Math.max(0, Math.round(goal - week.sales_ex_bulk / 7)), spend_needed: gate.mer_7d ? Math.round(goal / gate.mer_7d) : null },
      bulk: { min_order: c.rules.bulk_order_min, orders: cur.bulk_orders, amount: round2(cur.bulk_amount) },
      targets: { roas: c.rules.target_roas, mer: c.rules.target_mer, mer_floor: c.rules.mer_floor },
      gate_lines: { green: c.rules.gate_green_3d, red: c.rules.gate_red },
      notes: ['Platform sales are what Meta and Google each claim. They are never added together: the total is the store\'s own sales.',
        c.brand === 'ridhi' ? `Meta is billed in rupees and shown in dollars at Rs ${c.rules.fx_rate} = $1 (Rules tab).` : null].filter(Boolean) };
  }],
  ['GET', '/ads/campaigns', ({ query, db }) => {
    const c = ctx(query, db);
    return { ...info(c), targets: { roas: c.rules.target_roas }, campaigns: campaignRows(c) };
  }],
  ['GET', '/ads/creatives', ({ query, db }) => {
    const c = ctx({ ...query, platform: 'meta' }, db);
    const ads = metaAds(c).sort((a, b) => b.spend - a.spend);
    const counts = {};
    for (const a of ads) counts[a.verdict] = (counts[a.verdict] ?? 0) + 1;
    const bench = [...ads].filter((a) => a.lifetime.spend >= c.rules.proven_spend && a.lifetime.roas >= c.rules.scale_roas && a.lifetime.purchases >= c.rules.graduate_min_purchases)
      .sort((a, b) => b.lifetime.roas - a.lifetime.roas).slice(0, 10).map((a) => a.id);
    const acct = platformTotals(c.acc, 'meta', c.from, c.to, c.fx);
    return { ...info(c), ads, counts, winners: bench, targets: { roas: c.rules.target_roas, test_spend: c.rules.test_spend, proven_spend: c.rules.proven_spend },
      account: { roas: ratio(acct.value, acct.spend), ctr: pctOf(acct.clicks, acct.impressions), atc_rate: pctOf(acct.atc, acct.lpv), hook_rate: pctOf(acct.v3, acct.vimp), cpa: ratio(acct.spend, acct.purchases) } };
  }],
  ['GET', '/ads/funnel', ({ query, db }) => {
    const c = ctx(query, db);
    const steps = (t, b, list) => list.map(([key, label], i) => {
      const before = i ? list[i - 1][0] : null;
      return { key, label, value: t[key], previous: b ? b[key] : null, change_pct: b && b[key] ? Math.round((t[key] / b[key] - 1) * 1000) / 10 : null,
        rate: before ? pctOf(t[key], t[before]) : null, previous_rate: before && b ? pctOf(b[key], b[before]) : null };
    });
    const prev = (p) => (c.compare === 'none' ? null : platformTotals(c.acc, p, c.prevFrom, c.prevTo, p === 'meta' ? c.fx : 1));
    const store = storeTotals(c.acc, c.from, c.to, c.rules), storePrev = c.compare === 'none' ? null : storeTotals(c.acc, c.prevFrom, c.prevTo, c.rules);
    return { ...info(c),
      meta: c.platform === 'google' ? null : { steps: steps(platformTotals(c.acc, 'meta', c.from, c.to, c.fx), prev('meta'),
        [['impressions', 'Impressions'], ['clicks', 'Outbound clicks'], ['lpv', 'Landing page views'], ['atc', 'Add to cart'], ['ic', 'Checkout started'], ['purchases', 'Purchases']]) },
      google: c.platform === 'meta' ? null : { steps: steps(platformTotals(c.acc, 'google', c.from, c.to, 1), prev('google'), [['impressions', 'Impressions'], ['clicks', 'Clicks'], ['purchases', 'Purchases']]),
        note: 'Google reports clicks and purchases only; it has no page-view or cart steps.' },
      store: { sessions: block(store.sessions, storePrev?.sessions ?? null), orders: block(store.orders, storePrev?.orders ?? null),
        conversion_rate: block(pctOf(store.orders, store.sessions), storePrev ? pctOf(storePrev.orders, storePrev.sessions) : null),
        aov: block(div(store.sales_ex_bulk, store.orders - store.bulk_orders), storePrev ? div(storePrev.sales_ex_bulk, storePrev.orders - storePrev.bulk_orders) : null) } };
  }],
  ['GET', '/ads/search-terms', ({ query, db }) => {
    const c = ctx({ ...query, platform: 'google' }, db);
    return { ...info(c), ...googleDetail(c) };
  }],
  ['GET', '/ads/gap', ({ query, db }) => {
    const c = ctx({ ...query, platform: 'meta', from: undefined, to: undefined }, db);
    const pairs = gapPairs(c);
    return { brand: c.brand, as_of: isoOf(c.to), pairs, missing: pairs.reduce((s, p) => s + p.missing, 0),
      rule: { roas: c.rules.scale_roas, purchases: c.rules.graduate_min_purchases, spend: c.rules.proven_spend },
      note: 'Ads are matched by their post, not by their code, because a code can be reused for a different product.' };
  }],
  ['GET', '/ads/actions', ({ query, db }) => {
    const c = ctx({ ...query, from: undefined, to: undefined }, db);
    const actions = c.platform === 'google' ? [] : actionList(c, db);
    return { brand: c.brand, platform: c.platform, as_of: isoOf(c.to), actions, open: actions.filter((a) => a.status === 'open').length,
      daily_impact: actions.filter((a) => a.status === 'open').reduce((s, a) => s + a.daily_impact, 0),
      history: db.ads.history.filter((h) => h.brand === c.brand).slice(0, 30),
      google_note: 'No Google rules are agreed yet, so there are no automatic Google suggestions.',
      read_only: 'Flowmerce does not change anything in Meta or Google. Make the change in the ad account, then mark it done here.' };
  }],
  ['PATCH', '/ads/actions/:id', ({ params, query, body, db }) => {
    const c = ctx({ ...query, from: undefined, to: undefined }, db);
    if (!['open', 'done', 'skipped'].includes(body.status)) throw new DemoError(400, "status must be 'open', 'done' or 'skipped'.", 'bad_request');
    const action = actionList(c, db).find((a) => a.id === params.id);
    if (!action) throw new DemoError(404, 'That suggestion no longer applies.', 'not_found');
    if (body.status === 'open') delete db.ads.status[c.brand][action.id];
    else db.ads.status[c.brand][action.id] = body.status;
    db.ads.history.unshift({ id: db.ads.history.length + 1, brand: c.brand, action_id: action.id, title: action.title, group: action.group, status: body.status, by: 'Demo user', at: new Date().toISOString() });
    return { ...action, status: body.status };
  }],
  ['GET', '/ads/rules', ({ query, db }) => {
    const c = ctx(query, db);
    return { brand: c.brand, rules: c.rules, defaults: DEFAULT_RULES, meta_currency: ACCOUNTS[c.brand].meta.currency, glossary: GLOSSARY.map(([term, meaning]) => ({ term, meaning })) };
  }],
  ['PATCH', '/ads/rules', ({ query, body, db }) => {
    const c = ctx(query, db);
    const next = { ...c.rules };
    for (const [k, v] of Object.entries(body ?? {})) {
      if (!(k in DEFAULT_RULES)) throw new DemoError(400, `Unknown setting: ${k}.`, 'bad_request');
      const [lo, hi] = RULE_LIMITS[k] ?? [0.1, 100000];
      if (typeof v !== 'number' || !Number.isFinite(v) || v < lo || v > hi) throw new DemoError(400, `${k} must be a number between ${lo} and ${hi}.`, 'bad_request');
      next[k] = v;
    }
    if (next.cbo_min_ads > next.cbo_max_ads) throw new DemoError(400, 'The smallest number of ads in a CBO cannot be above the largest.', 'bad_request');
    if (next.fx_rate !== c.rules.fx_rate) next.fx_from = isoOf(todayNum());
    db.ads.rules[c.brand] = next;
    return { brand: c.brand, rules: next };
  }],
  // Both brands together (the company view on the Overview when the top bar says All): the same shape as the Python
  // module's GET /api/ads/company, built from each brand's own overview answer.
  ['GET', '/ads/company', ({ query, db }) => {
    const overviewOf = routes.find((r) => r[1] === '/ads/overview')[2];
    const parts = ['ridhi', 'cpc'].map((brand) => ({ brand, o: overviewOf({ query: { ...query, brand, platform: 'all' }, db }) }));
    const sum = (key, side) => parts.reduce((s, p) => s + (p.o.metrics[key][side] ?? 0), 0);
    const pair = (key) => [sum(key, 'value'), parts.every((p) => p.o.metrics[key].baseline_value === null) ? null : sum(key, 'baseline_value')];
    const [spend, spendB] = pair('total_spend'), [sales, salesB] = pair('sales'), [ex, exB] = pair('sales_ex_bulk'), [orders, ordersB] = pair('orders');
    const days = new Map();
    for (const { brand, o } of parts) for (const r of o.trend) {
      const t = days.get(r.date) ?? { date: r.date, spend: 0, sales_ex_bulk: 0 };
      t.spend += r.spend; t.sales_ex_bulk += r.sales_ex_bulk;
      t[`${brand}_spend`] = r.spend; t[`${brand}_sales_ex_bulk`] = r.sales_ex_bulk; t[`${brand}_mer_ex_bulk`] = r.mer_ex_bulk;
      days.set(r.date, t);
    }
    const LABEL = { ridhi: 'Demo Ridhi', cpc: 'Demo CPC' };
    const first = parts[0].o;
    return { from: first.from, to: first.to, days: first.days, compare: first.compare,
      metrics: { spend: block(spend, spendB), sales: block(sales, salesB), sales_ex_bulk: block(ex, exB), orders: block(orders, ordersB),
        mer_ex_bulk: block(div(ex, spend), spendB ? div(exB, spendB) : null), cost_per_order: block(div(spend, orders), ordersB ? div(spendB, ordersB) : null) },
      brands: parts.map(({ brand, o }) => ({ brand, label: LABEL[brand], ready: true, gate: o.gate, targets: o.targets, gate_lines: o.gate_lines,
        metrics: { total_spend: o.metrics.total_spend, sales_ex_bulk: o.metrics.sales_ex_bulk, mer_ex_bulk: o.metrics.mer_ex_bulk, orders: o.metrics.orders },
        share_of_spend: pctOf(o.metrics.total_spend.value, spend), platforms: o.platforms, goal: o.goal, meta_saved_to: o.meta_saved_to, google_saved_to: null })),
      // Each platform's spend over both brands (spend can be added; claimed sales and ROAS stay per brand).
      platforms: ['meta', 'google'].map((platform) => {
        const v = parts.reduce((n, p) => n + (p.o.platforms.find((x) => x.platform === platform)?.spend ?? 0), 0);
        return { platform, spend: round2(v), share_of_spend: pctOf(v, spend) };
      }).filter((p) => p.spend > 0),
      trend: [...days.values()].sort((a, b) => (a.date < b.date ? -1 : 1)).map((t) => ({ ...t, spend: round2(t.spend), sales_ex_bulk: round2(t.sales_ex_bulk),
        mer_ex_bulk: t.spend ? round2(t.sales_ex_bulk / t.spend) : null })),
      notes: ['Both brands together: ad spend is Meta and Google for both brands; store sales are both stores’ own orders (bulk orders left out of MER). Platform-claimed sales are never added together.',
        'Each brand keeps its own spend call, rules and goal: open a brand to act on it.'] };
  }],
];
