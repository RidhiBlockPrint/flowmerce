/**
 * Demo module: CRO. Everything here is synthetic (fictional products, generated daily figures, no customer data).
 * It answers the same /api/cro/... calls as modules/cro/api.py with the same response shapes, so the CRO page can be
 * shown without Supabase or Shopify. Only used when NEXT_PUBLIC_FLOWMERCE_DATA_SOURCE=demo.
 *
 * Collection `db.cro`:
 *   days:     { ridhi|cpc: [{ date, sessions, cart, checkout, done, orders, revenue, subtotal, discounts, shipping,
 *              tax, refunded, paid, refundedOrders, cancelled }] }  oldest first, the last entry is today (partial)
 *   products: { ridhi|cpc: [{ product_id, name, product_type, units7, units30, price }] }
 *   rules:    [{ id, store, kind, title, threshold, product_keyword, is_active, last_checked_at }]
 *   alerts:   [{ id, rule_id, store, period_date, message, triggered_at, resolved_at }]
 *   changes:  [{ id, store, entry_date, change, area, owner, created_by, created_at }]
 *   enabled:  { RBP: true, CPC: true }
 * Product insights and discount codes (batch 4) are worked out from `products` and `days`. Like the real stores, Ridhi
 * has GA4 product views for the whole range and CPC only for its last 2 days (its groups are "collecting").
 */
import { DemoError, dayAgo, hoursAgo, nextId, rng } from '../util.js';

const STORE = { ridhi: 'RBP', cpc: 'CPC' };
const TZ = { ridhi: 'America/New_York', cpc: 'America/Phoenix' };
const DAYS = 70;
const BENCHMARKS = {
  cart_abandonment_rate: { value: 70.0, label: 'Average online cart abandonment rate', source: 'Baymard Institute (commonly cited e-commerce average)' },
  checkout_abandonment_rate: { value: 69.0, label: 'Average checkout abandonment rate', source: 'Baymard Institute (commonly cited e-commerce average)' },
  conversion_rate: { value: 2.5, label: 'Average e-commerce conversion rate', source: 'Commonly cited e-commerce average (2-3% depending on sector)' },
};
const PRODUCTS = {
  ridhi: [['Demo Indigo Quilt', 'Quilts', 160], ['Demo Saffron Tablecloth', 'Tablecloths', 72], ['Demo Sage Napkins (set of 4)', 'Napkins', 38],
    ['Demo Rust Bedspread', 'Bedspreads', 120], ['Demo Floral Pillow Cover', 'Pillow covers', 28], ['Demo Kantha Throw', 'Throws', 95]],
  cpc: [['Demo Jade Round Tablecloth', 'Tablecloths', 68], ['Demo Emerald Chair Cushions', 'Cushions', 75], ['Demo Mocha Runner', 'Runners', 34],
    ['Demo Lotus Napkins (set of 6)', 'Napkins', 42], ['Demo Indigo Quilt', 'Quilts', 150]],
};

/* ------------------------------------------------------------------ seed */
export function seed(db) {
  const days = {};
  const products = {};
  for (const [brand, base] of [['ridhi', { sessions: 2800, cvr: 0.022, aov: 104 }], ['cpc', { sessions: 1500, cvr: 0.016, aov: 92 }]]) {
    const r = rng(brand === 'ridhi' ? 11 : 23);
    days[brand] = [];
    for (let i = DAYS - 1; i >= 0; i--) {
      const weekend = [0, 6].includes(new Date(Date.now() - i * 864e5).getDay());
      const partial = i === 0 ? 0.55 : 1;
      const sessions = Math.round(base.sessions * (weekend ? 1.15 : 1) * (0.85 + r() * 0.3) * partial);
      const done = Math.round(sessions * base.cvr * (0.8 + r() * 0.4));
      const checkout = Math.round(done * (1.8 + r() * 0.6));
      const cart = Math.round(checkout * (2.2 + r() * 0.8));
      const revenue = Math.round(done * base.aov * (0.9 + r() * 0.2) * 100) / 100;
      const discounts = Math.round(revenue * 0.06 * 100) / 100;
      const tax = Math.round(revenue * 0.015 * 100) / 100;
      days[brand].push({
        date: dayAgo(i), sessions, cart, checkout, done, orders: done, revenue,
        subtotal: Math.round((revenue - tax) * 100) / 100, discounts, shipping: 0, tax,
        refunded: r() < 0.15 ? Math.round(base.aov * 100) / 100 : 0,
        paid: done - (r() < 0.2 ? 1 : 0), refundedOrders: r() < 0.15 ? 1 : 0, cancelled: r() < 0.1 ? 1 : 0,
      });
    }
    products[brand] = PRODUCTS[brand].map(([name, type, price], k) => {
      const units30 = Math.round(20 + r() * 60);
      return { product_id: 9000 + k, name, product_type: type, price, units30, units7: Math.round(units30 / 4 * (k === 0 ? 0.3 : 0.8 + r() * 0.4)) };
    });
  }
  db.cro = {
    days, products, enabled: { RBP: true, CPC: true },
    rules: [
      { id: 1, store: 'RBP', kind: 'cvr_drop', title: 'Conversion rate drop 20%', threshold: 20, product_keyword: null, is_active: true, last_checked_at: hoursAgo(0.2) },
      { id: 2, store: 'RBP', kind: 'no_product_orders', title: 'No quilt orders for 12 hours', threshold: 12, product_keyword: 'quilt', is_active: true, last_checked_at: hoursAgo(0.2) },
      { id: 3, store: 'CPC', kind: 'cvr_drop', title: 'Conversion rate drop 20%', threshold: 20, product_keyword: null, is_active: true, last_checked_at: hoursAgo(0.2) },
    ],
    alerts: [
      { id: 1, rule_id: 1, store: 'RBP', period_date: dayAgo(9), message: `Conversion rate fell 24.1%: 2.41% on ${dayAgo(10)} -> 1.83% on ${dayAgo(9)} (alarm at 20%).`, triggered_at: hoursAgo(9 * 24 - 6), resolved_at: hoursAgo(8 * 24 - 6) },
    ],
    changes: [
      { id: 1, store: 'RBP', entry_date: dayAgo(12), change: 'Demo: new product page layout for quilts', area: 'theme', owner: 'Demo designer', created_by: 'demo', created_at: hoursAgo(12 * 24) },
      { id: 2, store: 'CPC', entry_date: dayAgo(5), change: 'Demo: 10% off tablecloths promotion started', area: 'promo', owner: 'Demo marketer', created_by: 'demo', created_at: hoursAgo(5 * 24) },
    ],
    recStatus: { RBP: {}, CPC: {} },
    freeShipping: { RBP: 100, CPC: null },
    experiments: [
      { id: 1, store: 'RBP', name: 'Demo: sticky add-to-cart on mobile', hypothesis: 'Keeping the button on screen while shoppers scroll should lift conversion.',
        metric: 'conversion_rate', page_path: null, start_date: dayAgo(7), end_date: null, owner: 'Design team', rec_key: null, created_by: 'demo', created_at: hoursAgo(7 * 24) },
      { id: 2, store: 'RBP', name: 'Demo: free shipping from $100 banner', hypothesis: 'A clear threshold in the header should push baskets just under $100 over it.',
        metric: 'aov', page_path: null, start_date: dayAgo(30), end_date: dayAgo(17), owner: 'Marketing', rec_key: null, created_by: 'demo', created_at: hoursAgo(30 * 24) },
      { id: 3, store: 'RBP', name: 'Demo: bigger first photos on the sale collection', hypothesis: 'Larger lifestyle photos above the fold should keep visitors browsing.',
        metric: 'bounce_rate', page_path: '/collections/sale', start_date: dayAgo(-3), end_date: null, owner: 'Design team', rec_key: 'landing_bounce:/collections/sale', created_by: 'demo', created_at: hoursAgo(2) },
    ],
  };
}

/* ------------------------------------------------------------------ helpers */
function storeOf(query) {
  const brand = query.brand || 'ridhi';
  if (!STORE[brand]) throw new DemoError(400, `Unknown brand '${brand}'; expected one of cpc, ridhi.`, 'bad_request');
  return { brand, store: STORE[brand] };
}
const rows = (db, brand) => db.cro.days[brand];
const complete = (db, brand) => rows(db, brand).slice(0, -1);
const byDate = (db, brand) => new Map(rows(db, brand).map((d) => [d.date, d]));
const sum = (list, f) => list.reduce((a, d) => a + (d?.[f] || 0), 0);
const round = (v, n = 2) => (v === null || v === undefined ? null : Math.round(v * 10 ** n) / 10 ** n);
const rate = (part, whole, n = 2) => (whole ? round((part / whole) * 100, n) : null);
/** Shopify session reports leave today out: the complete days of a plan and its first comparison, lined up. */
function sessionDays(p) {
  const cur = p.partial && p.current.length > 1 ? p.current.slice(0, -1) : p.current;
  const base = p.baselines.length ? p.baselines[0].slice(0, cur.length) : [];
  return { cur, base };
}
const windowOf = (cur, base) => ({ from: cur[0]?.date ?? null, to: cur[cur.length - 1]?.date ?? null, base_from: base[0]?.date ?? null, base_to: base[base.length - 1]?.date ?? null });
const LIMITS = { lcp: [2500, 4000], inp: [200, 500], cls: [0.1, 0.25] };
const rating = (m, v) => (v <= LIMITS[m][0] ? 'good' : v > LIMITS[m][1] ? 'poor' : 'needs_improvement');
/** The Conversion tab's funnel by device with the "viewed a product" step (about half of visits view a product). */
function demoFunnel(t, from, to) {
  if (!t || !t.sessions) return null;
  const mk = (sessions, steps) => ({ sessions, conversion_rate: rate(steps[3][1], sessions),
    steps: steps.map(([key, count], i) => ({ key, count, pct_of_sessions: rate(count, sessions, 1), pct_of_previous: rate(count, i ? steps[i - 1][1] : sessions, 1) })) });
  const split = (share, lift) => {
    const n = Math.round(t.sessions * share);
    return mk(n, [['viewed_product', Math.round(n * 0.51)], ['added_to_cart', Math.round(t.added_to_cart * share * lift)],
      ['reached_checkout', Math.round(t.reached_checkout * share * lift)], ['completed_checkout', Math.round(t.completed_checkout * share * lift)]]);
  };
  return { from, to, product_views_available: true,
    all: mk(t.sessions, [['viewed_product', Math.round(t.sessions * 0.51)], ['added_to_cart', t.added_to_cart], ['reached_checkout', t.reached_checkout], ['completed_checkout', t.completed_checkout]]),
    devices: [['Mobile', 0.72, 0.9], ['Desktop', 0.2, 1.4], ['Tablet', 0.08, 1.0]].map(([label, share, lift]) => ({ label, ...split(share, lift) })) };
}
const orderData = { first_load_complete: true, running: false, last_status: 'ok', last_run_at: hoursAgo(0.1), synced_up_to: hoursAgo(0.1), note: '' };

function block(value, baseline, tooEarly, label) {
  return {
    value, baseline_value: baseline, baseline_label: label,
    change_abs: tooEarly || value === null || baseline === null ? null : round(value - baseline),
    change_pct: tooEarly || value === null || !baseline ? null : round(((value - baseline) / baseline) * 100),
    too_early: tooEarly,
  };
}

const WEEKDAY = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const shift = (iso, n) => new Date(Date.parse(`${iso}T00:00:00Z`) + n * 864e5).toISOString().slice(0, 10);
const span = (from, to) => Math.round((Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / 864e5) + 1;
const dayLabel = (iso) => `${WEEKDAY[new Date(`${iso}T12:00:00Z`).getUTCDay()]} ${Number(iso.slice(8))} ${new Date(`${iso}T12:00:00Z`).toLocaleString('en-US', { month: 'short', timeZone: 'UTC' })}`;

/** The chosen days and their comparison day-sets, like modules/cro/periods.py range_plan(). Older `period`
 *  and `days` parameters are turned into a range first. */
function plan(db, brand, query, fallbackDays = null, includeToday = true) {
  const all = rows(db, brand);
  const today = all[all.length - 1].date;
  let from = query.from;
  let to = query.to;
  if (!from && !to) {
    const days = Number(query.days) || fallbackDays;
    if (days) {
      to = includeToday ? today : shift(today, -1);
      from = shift(to, -(days - 1));
    } else if (query.period === 'today') { from = today; to = today; }
    else if (query.period === 'last7') { to = shift(today, -1); from = shift(to, -6); }
    else { from = shift(today, -1); to = from; }
  }
  from = from || to;
  to = to || from;
  if (from > to) throw new DemoError(400, 'The start date is after the end date.', 'bad_request');
  if (from > today) throw new DemoError(400, 'The range starts in the future.', 'bad_request');
  if (to > today) to = today;
  const n = span(from, to);
  if (n > 366) throw new DemoError(400, 'Pick at most 366 days.', 'bad_request');
  let compare = ['previous', 'last_week', '4week_avg', 'none'].includes(query.compare) ? query.compare : (n === 1 && to < today ? '4week_avg' : 'previous');
  if (compare === '4week_avg' && n !== 1) compare = 'previous';
  const byDay = byDate(db, brand);
  const daysOf = (start, count) => Array.from({ length: count }, (_, i) => shift(start, i));
  const pick = (list) => list.map((d) => byDay.get(d)).filter(Boolean);
  const current = daysOf(from, n);
  const back = compare === 'none' ? [] : compare === 'last_week' ? [7] : compare === '4week_avg' ? [7, 14, 21, 28] : [n];
  const partial = to === today;
  const baselines = back.map((b) => pick(daysOf(shift(from, -b), n)).map((d, i, a) => (partial && i === a.length - 1 ? { ...d, ...scale(d, 0.55) } : d)));
  const baseLabel = compare === 'none' ? 'no comparison' : compare === 'last_week' ? (n === 1 ? `vs same ${dayLabel(from).slice(0, 3)} last week` : 'vs same days a week earlier')
    : compare === '4week_avg' ? `vs 4-week ${dayLabel(from).slice(0, 3)} average` : (n === 1 ? 'vs previous day' : `vs previous ${n} days`);
  const label = (n === 1 ? dayLabel(from) : `${dayLabel(from).slice(4)} - ${dayLabel(to).slice(4)} (${n} days)`) + (partial ? ', so far' : '');
  return { from, to, n, compare, label, baseLabel, partial, current: pick(current), baselines };
}
const info = (p) => ({ period: 'range', period_label: p.label, compare: p.compare, baseline_label: p.baseLabel, is_partial: p.partial, from: p.from, to: p.to });
const scale = (d, f) => Object.fromEntries(['sessions', 'cart', 'checkout', 'done', 'orders', 'revenue', 'subtotal', 'discounts', 'tax', 'refunded'].map((k) => [k, Math.round(d[k] * f * 100) / 100]));
const avg = (sets, fn) => round(sets.reduce((a, s) => a + fn(s), 0) / sets.length);
const stats = (set) => {
  const orders = sum(set, 'orders');
  const revenue = round(sum(set, 'revenue'));
  return { orders, revenue, aov: orders ? round(revenue / orders) : 0 };
};
const sales = (set) => {
  const subtotal = sum(set, 'subtotal');
  const discounts = sum(set, 'discounts');
  const refunded = sum(set, 'refunded');
  return { orders: sum(set, 'orders'), total: round(sum(set, 'revenue')), gross: round(subtotal + discounts), discounts: round(discounts),
    returns: round(refunded), net: round(subtotal - refunded), shipping: 0, tax: round(sum(set, 'tax')) };
};
function funnelRow(d) {
  if (!d) return { date: '', sessions: 0, added_to_cart: 0, reached_checkout: 0, completed_checkout: 0, cart_rate: null, checkout_rate: null, conversion_rate: null,
    cart_abandonment_rate: null, checkout_abandonment_rate: null, checkout_completion_rate: null };
  return {
    date: d.date, sessions: d.sessions, added_to_cart: d.cart, reached_checkout: d.checkout, completed_checkout: d.done,
    cart_rate: rate(d.cart, d.sessions, 1), checkout_rate: rate(d.checkout, d.sessions, 1), conversion_rate: rate(d.done, d.sessions),
    cart_abandonment_rate: rate(d.cart - d.done, d.cart, 1), checkout_abandonment_rate: rate(d.checkout - d.done, d.checkout, 1),
    checkout_completion_rate: rate(d.done, d.checkout, 1),
  };
}
function cvrComparison(db, brand) {
  const c = complete(db, brand);
  const y = funnelRow(c[c.length - 1]);
  const p = funnelRow(c[c.length - 2]);
  return { yesterday_date: y.date, yesterday_cvr: y.conversion_rate, previous_date: p.date, previous_cvr: p.conversion_rate,
    drop_percent: p.conversion_rate ? round(((p.conversion_rate - y.conversion_rate) / p.conversion_rate) * 100) : null };
}
function health(set) {
  const total = sum(set, 'orders');
  const share = (n) => ({ count: n, pct: total ? round((n / total) * 100, 1) : 0 });
  const refunded = sum(set, 'refundedOrders');
  const cancelled = sum(set, 'cancelled');
  const paid = Math.min(sum(set, 'paid'), total - refunded - cancelled);
  return { days: set.length, total_orders: total, paid: share(paid), refunded: share(refunded), cancelled: share(cancelled), pending: share(Math.max(0, total - paid - refunded - cancelled)) };
}
function productRows(db, brand, days) {
  const list = db.cro.products[brand].map((p) => {
    const units = days <= 7 ? p.units7 : Math.round(p.units30 * (days / 30));
    return { product_id: p.product_id, name: p.name, product_type: p.product_type, quantity: units, revenue: round(units * p.price), orders: Math.max(1, Math.round(units * 0.85)) };
  }).sort((a, b) => b.revenue - a.revenue);
  const revs = list.map((p) => p.revenue);
  const top = revs[Math.max(0, Math.floor(revs.length / 3) - 1)];
  const low = revs[Math.max(0, Math.floor((2 * revs.length) / 3))];
  return list.map((p) => ({ ...p, performance_status: p.revenue >= top ? 'top' : p.revenue <= low ? 'low' : 'average' }));
}
const rulesOf = (db, store) => db.cro.rules.filter((r) => r.store === store);
function checkKeyword(kind, body) {
  if (kind === 'no_product_orders' && !String(body.product_keyword || '').trim()) throw new DemoError(400, 'Give a product keyword of 1 to 100 characters.', 'bad_request');
}
function checkThreshold(kind, v) {
  const t = Number(v);
  if (!(t > 0) || (kind === 'cvr_drop' && t > 100)) throw new DemoError(400, 'The threshold must be above 0 (and at most 100 for a conversion-rate drop).', 'bad_request');
  return round(t);
}

/* ------------------------------------------------------------------ products, batch 4 (modules/cro/products.py) */
const GROUP_LABELS = { star: 'Stars', hidden_gem: 'Hidden gems', leaky: 'Leaky', dead_weight: 'Dead weight' };
const BANDS = [[0, 25], [25, 50], [50, 75], [75, 100], [100, 150], [150, 200], [200, 300], [300, null]];
const bandLabel = (lo, hi) => (hi === null ? `$${lo}+` : lo ? `$${lo}-${hi - 1}` : `Under $${hi}`);
const median = (xs) => { const s = [...xs].sort((a, b) => a - b); const m = Math.floor(s.length / 2); return s.length ? (s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2) : 0; };
// Demo product views per sold unit and how well each turns views into carts (fixed, so the groups are stable).
const VIEW_SHAPE = { 0: [60, 0.55], 1: [26, 1.1], 2: [14, 1.6], 3: [40, 0.7], 4: [9, 1.4], 5: [30, 0.9] };
function classifyDemo(rows) {
  const seen = rows.filter((p) => p.views);
  const peer = (m) => { const v = m.reduce((a, p) => a + p.views, 0); return { cr: v ? m.reduce((a, p) => a + p.view_orders, 0) / v : 0, med: median(m.map((p) => p.views)) }; };
  const members = {};
  for (const p of seen) (members[p.category] ??= []).push(p);
  const store = peer(seen);
  for (const p of seen) {
    const own = members[p.category].length >= 3;   // smaller categories are compared with all products
    const { cr, med } = own ? peer(members[p.category]) : store;
    const raw = p.view_orders / p.views;
    const adjusted = (p.view_orders + 200 * cr) / (p.views + 200);
    const many = p.views >= med;
    const good = cr > 0 && adjusted >= cr;
    const group = good ? (many ? 'star' : 'hidden_gem') : (many ? 'leaky' : 'dead_weight');
    Object.assign(p, { compared_with: own ? p.category : 'All products', category_rate: round(cr * 100), adjusted_rate: round(adjusted * 100), vs_category_pts: round((adjusted - cr) * 100), group,
      left_on_table: group === 'leaky' && cr > raw ? round(p.views * (cr - raw) * p.price) : 0 });
  }
}
function productInsights(db, brand, p) {
  const ready = brand === 'ridhi';   // like the real stores: CPC's GA4 only started recently
  const viewDays = ready ? p.n : Math.min(2, p.n);
  const list = productRows(db, brand, p.n);
  const rows = list.map((r, k) => {
    const src = db.cro.products[brand].find((x) => x.product_id === r.product_id);
    const [perUnit, strength] = VIEW_SHAPE[k % 6];
    const views = Math.round(r.quantity * perUnit * (viewDays / p.n));
    const viewOrders = Math.round(r.orders * (viewDays / p.n));
    const gross = round(r.revenue * 1.06);
    const refunded = round(gross * [0.081, 0.012, 0.02, 0.046, 0.0, 0.03][k % 6]);
    const carts = Math.round(views * 0.08 * strength);
    return { product_id: r.product_id, name: r.name, category: src.product_type, orders: r.orders, items: r.quantity, net_sales: round(gross - refunded - r.revenue * 0.06),
      gross_sales: gross, discounts: round(r.revenue * 0.06), refunded, refund_rate: rate(refunded, gross, 1), price: src.price, handle: r.name.toLowerCase().replace(/[^a-z0-9]+/g, '-'),
      views, add_to_carts: carts, add_to_cart_rate: rate(carts, views, 1), view_orders: viewOrders, conversion_rate: rate(viewOrders, views), group: null };
  });
  rows.push({ product_id: 9100, name: 'Demo Viewed-only Runner', category: 'Runners', orders: 0, items: 0, net_sales: 0, gross_sales: 0, discounts: 0, refunded: 0, refund_rate: null,
    price: 36, handle: 'demo-viewed-only-runner', views: ready ? 640 : 40, add_to_carts: ready ? 9 : 1, add_to_cart_rate: ready ? 1.4 : 2.5, view_orders: 0, conversion_rate: 0, group: null });
  if (ready) classifyDemo(rows);
  const days = Array.from({ length: viewDays }, (_, i) => shift(p.to, -(viewDays - 1 - i)));
  const views = ready
    ? { state: 'ready', days: viewDays, window_days: p.n, from: days[0], to: days.at(-1), unmatched_views: 0,
      message: `Views and add-to-carts from GA4 for ${viewDays} day${viewDays === 1 ? '' : 's'}; conversion uses the orders of the same days.` + (viewDays < 14 ? ' The groups settle as more days come in (best after 14).' : '') }
    : { state: 'collecting', days: viewDays, window_days: p.n, from: days[0], to: days.at(-1), unmatched_views: 0,
      message: `GA4 has product views for ${viewDays} of the ${p.n} day${p.n === 1 ? '' : 's'} so far; the groups and the fix-first list show once it has 7.` };
  const gross = rows.reduce((a, r) => a + (r.gross_sales || 0), 0);
  const refunded = rows.reduce((a, r) => a + (r.refunded || 0), 0);
  const listed = rows.filter((r) => r.gross_sales >= 300 && r.refunded)
    .map(({ product_id, name, category, gross_sales, refunded: rf, refund_rate }) => ({ product_id, name, category, gross_sales, refunded: rf, refund_rate }));
  const groups = ready ? {
    groups: Object.keys(GROUP_LABELS).map((g) => {
      const m = rows.filter((r) => r.group === g);
      return { group: g, label: GROUP_LABELS[g], products: m.length, views: m.reduce((a, r) => a + r.views, 0), net_sales: round(m.reduce((a, r) => a + r.net_sales, 0)),
        top: [...m].sort((a, b) => b.views - a.views).slice(0, 3).map((r) => r.name) };
    }),
    fix_first: rows.filter((r) => r.group === 'leaky' && r.left_on_table).sort((a, b) => b.left_on_table - a.left_on_table).slice(0, 10)
      .map(({ product_id, name, category, handle, views: v, add_to_cart_rate, view_orders, conversion_rate, compared_with, category_rate, price, left_on_table }) =>
        ({ product_id, name, category, handle, views: v, add_to_cart_rate, view_orders, conversion_rate, compared_with, category_rate, price, left_on_table })),
  } : null;
  if (groups) groups.left_on_table = round(groups.fix_first.reduce((a, r) => a + r.left_on_table, 0));
  const totalOrders = sum(p.current, 'orders');
  const acc = {};
  for (const r of rows) {
    const [lo, hi] = BANDS.find(([a, b]) => r.price >= a && (b === null || r.price < b));
    const b = acc[lo] ?? (acc[lo] = { lo, hi, products: 0, items: 0, net_sales: 0, views: 0, orders: 0, vo: 0 });
    b.products += 1; b.items += r.items; b.net_sales += r.net_sales; b.views += r.views; b.orders += r.orders; b.vo += r.view_orders;
  }
  const net = Object.values(acc).reduce((a, b) => a + b.net_sales, 0);
  const price_bands = BANDS.filter(([lo]) => acc[lo]).map(([lo]) => {
    const b = acc[lo];
    return { band: bandLabel(b.lo, b.hi), from: b.lo, products: b.products, orders: Math.min(b.orders, totalOrders), items: b.items, net_sales: round(b.net_sales),
      share_of_sales: rate(b.net_sales, net, 1), views: ready ? b.views : null, conversion_rate: ready ? rate(b.vo, b.views) : null };
  });
  const names = rows.map((r) => r.name);
  const pair = (a, b, together, aOrders, bOrders) => ({ a: names[a], b: names[b], orders_together: together, a_orders: aOrders, b_orders: bOrders,
    pct_of_a: rate(together, aOrders, 1), pct_of_b: rate(together, bOrders, 1), lift: round((together / totalOrders) / ((aOrders / totalOrders) * (bOrders / totalOrders)), 1) });
  const o = rows.map((r) => Math.max(1, r.orders));
  const bought_together = { orders: totalOrders, multi_product_orders: Math.round(totalOrders * 0.38), multi_share: 38.0, min_orders_together: 2,
    rows: [pair(0, 4, Math.round(o[4] * 0.45), o[0], o[4]), pair(1, 2, Math.round(o[2] * 0.4), o[1], o[2]), pair(0, 2, Math.round(o[2] * 0.12), o[0], o[2]),
      pair(1, 3, Math.max(2, Math.round(o[3] * 0.08)), o[1], o[3])].filter((r) => r.orders_together >= 2).sort((a, b) => b.orders_together - a.orders_together) };
  rows.sort((a, b) => b.net_sales - a.net_sales || a.name.localeCompare(b.name));
  return { products: rows, sales_source: 'shopify', sales_error: null, catalog_error: null, views, views_source: 'ga4',
    refunds: { store_refund_rate: rate(refunded, gross, 1), total_refunded: round(refunded), refunded_without_product: round(refunded * 0.12), min_gross_sales: 300,
      products_with_refunds: rows.filter((r) => r.refunded).length, by_rate: [...listed].sort((a, b) => b.refund_rate - a.refund_rate).slice(0, 10),
      by_amount: [...listed].sort((a, b) => b.refunded - a.refunded).slice(0, 10) },
    groups, price_bands, bought_together };
}
function discountSummary(set, codeShare) {
  const orders = sum(set, 'orders');
  const gross = sum(set, 'subtotal') + sum(set, 'discounts');
  const CODES = [['WELCOME10', 0.42, 0.1, 1.04], ['SPRING15', 0.21, 0.15, 0.93], ['VIP', 0.12, 0.1, 1.36], ['BUNDLE20', 0.09, 0.2, 1.22], ['FREESHIP', 0.08, 0.0, 0.88],
    ['FRIENDS', 0.05, 0.1, 0.97], ['SORRY5', 0.03, 0.05, 0.9]];
  const aov = orders ? gross / orders : 0;
  const block = (n, g, d, a) => ({ orders: n, share_of_orders: rate(n, orders, 1), net_sales: round(g - d), aov: n ? round(a) : null, discount_given: round(d), discount_pct: rate(d, g, 1) });
  const withN = Math.round(orders * codeShare);
  const codes = CODES.map(([code, share, pct, lift]) => { const n = Math.max(1, Math.round(withN * share)); const g = n * aov * lift; return { code, ...block(n, g, g * pct, (g - g * pct) / n) }; });
  const wg = codes.reduce((a, c) => a + c.net_sales + c.discount_given, 0);
  const wd = codes.reduce((a, c) => a + c.discount_given, 0);
  const og = gross - wg;
  const od = Math.max(0, sum(set, 'discounts') - wd);
  return { total_orders: orders, with_code: block(withN, wg, wd, (wg - wd) / Math.max(1, withN)),
    without_code: block(orders - withN, og, od, (og - od) / Math.max(1, orders - withN)), codes, code_count: codes.length + 9 };
}

/* ------------------------------------------------------------------ batch 5: customers (modules/cro/customers.py) */
function customersDemo(db, brand, p, cur, base) {
  const nr = (set, newShare, newAov, retAov, rr) => {
    const orders = sum(set, 'orders');
    const n = Math.round(orders * newShare);
    const r = orders - n;
    return { orders, new: { orders: n, share_of_orders: rate(n, orders, 1), net_sales: round(n * newAov), aov: n ? newAov : null },
      returning: { orders: r, share_of_orders: rate(r, orders, 1), net_sales: round(r * retAov), aov: r ? retAov : null }, returning_customer_rate: rr };
  };
  const ridhi = brand === 'ridhi';
  const now = nr(cur, ridhi ? 0.77 : 0.8, ridhi ? 119.85 : 101.63, ridhi ? 92.57 : 78.76, ridhi ? 21.9 : 20.0);
  const prev = base.length ? nr(base, ridhi ? 0.83 : 0.83, ridhi ? 129.58 : 84.92, ridhi ? 92.74 : 93.33, ridhi ? 15.6 : 16.7) : null;
  return { new_vs_returning: { ...now, previous: prev, skipped: [] }, new_vs_returning_error: null };
}

/* ------------------------------------------------------------------ experiments (modules/cro/experiments.py) */
const EXP_METRICS = {
  conversion_rate: { label: 'Conversion rate', better: 'up' }, added_to_cart_rate: { label: 'Add-to-cart rate', better: 'up' },
  bounce_rate: { label: 'Bounce rate', better: 'down' }, aov: { label: 'Average order value', better: 'up' },
};
function cleanExperiment(body) {
  const name = String(body.name || '').trim(), hypothesis = String(body.hypothesis || '').trim();
  if (!name || name.length > 200) throw new DemoError(400, 'Give the experiment a name of 1 to 200 characters.', 'bad_request');
  if (!hypothesis) throw new DemoError(400, 'Describe what you expect to happen (1 to 2,000 characters).', 'bad_request');
  if (!EXP_METRICS[body.metric]) throw new DemoError(400, 'Pick a metric.', 'bad_request');
  if (!/^\d{4}-\d{2}-\d{2}$/.test(String(body.start_date || ''))) throw new DemoError(400, 'Give a start date (YYYY-MM-DD).', 'bad_request');
  if (body.end_date && body.end_date < body.start_date) throw new DemoError(400, 'The end date is before the start date.', 'bad_request');
  return { name, hypothesis, metric: body.metric, start_date: body.start_date, end_date: body.end_date || null,
    page_path: body.metric === 'aov' ? null : String(body.page_path || '').trim() || null, owner: String(body.owner || '').trim() || null, rec_key: body.rec_key || null };
}
/** Before = the same number of days just before the start; during = start to end (or yesterday). Same rules as the API. */
function withResult(db, brand, e) {
  const meta = EXP_METRICS[e.metric];
  const out = { ...e, metric_label: meta.label, better: meta.better };
  const yesterday = dayAgo(1);
  if (e.start_date > yesterday) return { ...out, result: { state: 'planned', verdict: 'planned', summary: `Starts ${e.start_date}` } };
  const last = e.end_date && e.end_date < yesterday ? e.end_date : yesterday;
  const n = span(e.start_date, last);
  const days = byDate(db, brand);
  const pick = (from, count) => Array.from({ length: count }, (_, i) => days.get(shift(from, i))).filter(Boolean);
  const during = pick(e.start_date, n), before = pick(shift(e.start_date, -n), n);
  const state = e.end_date && e.end_date <= yesterday ? 'finished' : 'running';
  const lab = (a, b) => `${a.slice(5)} - ${b.slice(5)}`;
  const base = { state, days_measured: n, before_label: lab(shift(e.start_date, -n), shift(e.start_date, -1)), during_label: lab(e.start_date, last) };
  if (e.metric === 'aov') {
    const av = (set) => { const o = sum(set, 'orders'); return o ? round((sum(set, 'subtotal') + sum(set, 'discounts')) / o) : null; };
    const b = av(before), d = av(during);
    const ch = b && d ? round(((d - b) / b) * 100, 1) : null;
    return { ...out, result: { ...base, before: b, during: d, before_n: sum(before, 'orders'), during_n: sum(during, 'orders'), n_unit: 'orders', confidence: null, change: ch, change_unit: '%',
      verdict: ch === null ? 'no_data' : state === 'running' ? 'early' : ch > 0 ? 'better' : ch < 0 ? 'worse' : 'flat' } };
  }
  const rateOf = (set) => { const s = sum(set, 'sessions'); return s ? sum(set, e.metric === 'added_to_cart_rate' ? 'cart' : 'done') / s : null; };
  let pb = rateOf(before), pd = rateOf(during);
  if (e.metric === 'bounce_rate' && pb !== null) { pb = 0.55; pd = 0.53; }
  const nb = sum(before, 'sessions'), nd = sum(during, 'sessions');
  const pooled = (pb * nb + pd * nd) / (nb + nd);
  const se = Math.sqrt(pooled * (1 - pooled) * (1 / nb + 1 / nd));
  const z = se ? Math.abs(pd - pb) / se : 0;
  const conf = se ? round((1 - 2 * (1 - normal(z))) * 100, 1) : null;
  const good = meta.better === 'up' ? pd > pb : pd < pb;
  const verdict = Math.min(nb, nd) < 200 ? 'too_few' : conf !== null && conf >= 95 ? (good ? 'win' : 'loss') + (state === 'running' ? '_so_far' : '') : state === 'running' ? 'running' : 'no_clear_result';
  return { ...out, result: { ...base, before: round(pb * 100), during: round(pd * 100), before_n: nb, during_n: nd, n_unit: 'visits', change: round((pd - pb) * 100), change_unit: 'pts', confidence: conf, verdict } };
}
/** Standard normal cumulative distribution (Abramowitz-Stegun 7.1.26 via erf). */
function normal(z) {
  const t = 1 / (1 + 0.3275911 * (z / Math.SQRT2));
  const erf = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-(z * z) / 2);
  return 0.5 * (1 + erf);
}

/* ------------------------------------------------------------------ routes */
export const routes = [
  ['GET', '/cro/overview', ({ query, db }) => {
    const { brand } = storeOf(query);
    const p = plan(db, brand, query);
    const cur = stats(p.current);
    const tooEarly = cur.orders < 20;
    const base = (fn) => (p.baselines.length ? avg(p.baselines, fn) : null);
    const metrics = {
      orders: block(cur.orders, base((s) => stats(s).orders), tooEarly, p.baseLabel),
      revenue: block(cur.revenue, base((s) => stats(s).revenue), tooEarly, p.baseLabel),
      aov: block(cur.aov, base((s) => stats(s).aov), tooEarly, p.baseLabel),
    };
    const complete = p.partial ? p.current.slice(0, -1) : p.current;
    if (!complete.length) {
      metrics.conversion_rate = { ...block(null, null, true, p.baseLabel), sessions: null, base_label: 'Shopify reports sessions for complete days only' };
    } else {
      const sessions = sum(complete, 'sessions');
      const value = rate(sum(complete, 'done'), sessions);
      metrics.conversion_rate = { ...block(value, base((s) => rate(sum(s, 'done'), sum(s, 'sessions'))), sessions < 500, p.baseLabel),
        sessions, base_label: `${cur.orders} orders from ${sessions.toLocaleString('en-US')} sessions${p.partial ? ' (today left out)' : ''}` };
      const baseSessions = p.baselines.length ? avg(p.baselines, (s) => sum(s, 'sessions')) : null;
      metrics.sessions = block(sessions, baseSessions, sessions < 500, p.baseLabel);
      if (!p.partial)
        metrics.revenue_per_session = block(round(cur.revenue / sessions), baseSessions ? round(avg(p.baselines, (s) => stats(s).revenue) / baseSessions) : null, sessions < 500, p.baseLabel);
    }
    return { brand, ...info(p), timezone: TZ[brand], as_of: new Date().toISOString(), metrics, health: { last_order_at: hoursAgo(0.4) },
      cvr_error: null, data_since: dayAgo(63), order_data: orderData };
  }],
  ['GET', '/cro/sales-breakdown', ({ query, db }) => {
    const { brand } = storeOf(query);
    const p = plan(db, brand, query);
    const cur = sales(p.current);
    const base = Object.fromEntries(Object.keys(cur).map((k) => [k, p.baselines.length ? avg(p.baselines, (s) => sales(s)[k]) : null]));
    const tooEarly = cur.orders < 20;
    const ROWS = [['gross', 'Gross sales'], ['discounts', 'Discounts'], ['returns', 'Returns'], ['net', 'Net sales'], ['shipping', 'Shipping'], ['tax', 'Taxes'], ['total', 'Total sales']];
    return { brand, ...info(p), too_early: tooEarly,
      rows: ROWS.map(([key, label]) => ({ key, label, ...block(cur[key], base[key], tooEarly, p.baseLabel) })),
      note: "Returns is Shopify's total refunded amount for the order, which can include refunded shipping or tax, not only products.", order_data: orderData };
  }],
  ['GET', '/cro/sales-trend', ({ query, db }) => {
    const { brand } = storeOf(query);
    const p = plan(db, brand, query, 14, false);
    const pickDay = (list) => list.map((d) => ({ date: d.date, orders: d.orders, revenue: round(d.revenue), net: round(d.subtotal - d.refunded) }));
    return { brand, ...info(p), days: p.n, current: pickDay(p.current), previous: p.baselines.length ? pickDay(p.baselines[0]) : [], order_data: orderData };
  }],
  ['GET', '/cro/order-health', ({ query, db }) => {
    const { brand } = storeOf(query);
    const p = plan(db, brand, query, 30);
    return { brand, ...info(p), ...health(p.current), order_data: orderData };
  }],
  ['GET', '/cro/products', ({ query, db }) => {
    const { brand } = storeOf(query);
    const p = plan(db, brand, query, 30);
    return { brand, ...info(p), days: p.n, products: productRows(db, brand, p.n), order_data: orderData };
  }],
  ['GET', '/cro/conversion', ({ query, db }) => {
    const { brand } = storeOf(query);
    const p = plan(db, brand, query, 7, false);
    const complete = p.partial ? p.current.slice(0, -1) : p.current;
    const total = (list) => funnelRow(list.reduce((a, d) => ({ date: '', sessions: a.sessions + d.sessions, cart: a.cart + d.cart, checkout: a.checkout + d.checkout, done: a.done + d.done }),
      { date: '', sessions: 0, cart: 0, checkout: 0, done: 0 }));
    const t = total(complete);
    const b = p.baselines.length ? total(p.baselines[0]) : null;
    const ends = (list) => [list[0]?.date, list[list.length - 1]?.date];
    return { brand, ...info(p), days: complete.length, trend: complete.map(funnelRow), baseline_trend: p.baselines.length ? p.baselines[0].slice(0, complete.length).map(funnelRow) : [], total: t, baseline_total: b,
      funnel: demoFunnel(t, ...ends(complete)), baseline_funnel: b && p.baselines.length ? demoFunnel(b, ...ends(p.baselines[0])) : null,
      conversion_change_pct: b && b.conversion_rate && t.conversion_rate !== null ? round(((t.conversion_rate - b.conversion_rate) / b.conversion_rate) * 100) : null,
      today_left_out: p.partial };
  }],
  ['GET', '/cro/funnel', ({ query, db }) => {
    const { brand } = storeOf(query);
    const c = complete(db, brand);
    return { brand, ...funnelRow(c[c.length - 1]) };
  }],
  ['GET', '/cro/segments', ({ query, db }) => {
    const { brand } = storeOf(query);
    const dimension = query.dimension === 'channel' ? 'channel' : query.dimension === 'device' ? 'device' : null;
    if (!dimension) throw new DemoError(400, 'Unknown dimension; expected device or channel.', 'bad_request');
    const p = plan(db, brand, query, 7, false);
    const now = sum(p.current, 'sessions');
    const before = p.baselines.length ? sum(p.baselines[0], 'sessions') : 0;
    const SHARES = dimension === 'device'
      ? [['mobile', 0.72, 1.6, 0.1], ['desktop', 0.2, 3.4, -0.2], ['tablet', 0.08, 2.2, 0.05]]
      : [['direct', 0.34, 2.6, 0.1], ['search', 0.31, 2.2, -0.1], ['social', 0.22, 1.1, 0.2], ['email', 0.08, 4.1, 0.3], ['unknown', 0.05, 0.9, 0]];
    const out = SHARES.map(([label, share, cvr, delta]) => {
      const sessions = Math.round(now * share);
      const base = Math.round(before * share);
      return { label, sessions, orders: Math.round((sessions * cvr) / 100), added_to_cart_rate: round(cvr * 4.5), conversion_rate: cvr,
        baseline_sessions: base || null, baseline_conversion_rate: base ? round(cvr - delta) : null, sessions_change_pct: base ? round(((sessions - base) / base) * 100, 1) : null,
        conversion_rate_change_pts: base ? round(delta) : null };
    });
    return { brand, ...info(p), dimension, days: p.n, rows: out, revenue_available: false,
      revenue_note: "AOV and revenue per session are not split by device or channel: Shopify does not link order revenue to the session's device or channel in this data." };
  }],
  // ---- batch 2: Shopify session reports (synthetic shares of the demo days' figures) ----
  ['GET', '/cro/traffic-changes', ({ query, db }) => {
    const { brand } = storeOf(query);
    const p = plan(db, brand, query, 7, false);
    const { cur, base } = sessionDays(p);
    const now = sum(cur, 'sessions'), before = base.length ? sum(base, 'sessions') : Math.round(now * 0.93);
    const table = (dim, shares) => shares.map(([key, share, cvr, delta, rps]) => {
      const s1 = Math.round(now * share), s0 = Math.round(before * (share - delta / 40));
      const c1 = cvr / 100, c0 = Math.max(0.001, (cvr - delta) / 100);
      const b1 = Math.round(s1 * c1), b0 = Math.round(s0 * c0);
      return { key, label: key[0].toUpperCase() + key.slice(1), sessions: s1, previous_sessions: s0, sessions_change_pct: s0 ? round(((s1 - s0) / s0) * 100, 1) : null,
        conversion_rate: round(c1 * 100), previous_conversion_rate: round(c0 * 100), conversion_change_pts: round(delta), purchases: b1, previous_purchases: b0,
        traffic_effect: round((s1 - s0) * c0, 1), conversion_effect: round(s1 * (c1 - c0), 1), enough_data: s1 >= 300 && s0 >= 300,
        ...(dim === 'channel' ? { revenue: round(s1 * rps), revenue_per_session: rps, previous_revenue_per_session: round(rps * 0.94), revenue_per_session_change_pct: 6.4 } : {}) };
    });
    const device = table('device', [['mobile', 0.72, 1.9, 0.25], ['desktop', 0.2, 3.6, -0.2], ['tablet', 0.08, 2.2, 0.05]]);
    const channel = table('channel', [['social', 0.4, 1.4, 0.15, 1.6], ['direct', 0.3, 3.1, 0.3, 3.4], ['search', 0.2, 2.4, -0.1, 2.6], ['email', 0.06, 4.2, 0.2, 4.8], ['unknown', 0.04, 0.9, 0, 0.9]]);
    const movers = [...device.map((r) => ['device', r]), ...channel.map((r) => ['channel', r])].filter(([, r]) => r.enough_data)
      .flatMap(([dim, r]) => [
        { dimension: dim, segment: r.label, kind: 'conversion', effect: r.conversion_effect,
          text: `${dim === 'device' ? `${r.label} conversion` : `Conversion from ${r.label}`} ${r.conversion_effect > 0 ? 'rose' : 'fell'} from ${r.previous_conversion_rate}% to ${r.conversion_rate}% (${r.conversion_change_pts > 0 ? '+' : ''}${r.conversion_change_pts.toFixed(2)} pts): about ${Math.abs(Math.round(r.conversion_effect))} ${r.conversion_effect > 0 ? 'more' : 'fewer'} purchases.` },
        { dimension: dim, segment: r.label, kind: 'traffic', effect: r.traffic_effect,
          text: `${dim === 'device' ? `${r.label} visits` : `Visits from ${r.label}`} ${r.sessions > r.previous_sessions ? 'rose' : 'fell'} ${Math.abs(Math.round(r.sessions_change_pct ?? 0))}% (${r.previous_sessions.toLocaleString('en-US')} to ${r.sessions.toLocaleString('en-US')}): about ${Math.abs(Math.round(r.traffic_effect))} ${r.traffic_effect > 0 ? 'more' : 'fewer'} purchases.` },
      ]).filter((m) => Math.abs(m.effect) >= 1).sort((a, b) => Math.abs(b.effect) - Math.abs(a.effect)).slice(0, 3).map((m) => ({ ...m, good: m.effect > 0 }));
    return { brand, ...info(p), window: windowOf(cur, base), total_sessions: now, too_early: now < 500, min_segment_sessions: 300,
      device, channel, movers: now < 500 ? [] : movers, revenue_available: true, errors: {} };
  }],
  ['GET', '/cro/geo', ({ query, db }) => {
    const { brand } = storeOf(query);
    const p = plan(db, brand, query, 28, false);
    const { cur, base } = sessionDays(p);
    const now = sum(cur, 'sessions');
    const rows = (list) => list.map(([label, share, cvr, delta]) => ({ label, sessions: Math.round(now * share), share_pct: round(share * 100, 1), cart_rate: round(cvr * 2.8, 1),
      conversion_rate: cvr, orders: Math.round((now * share * cvr) / 100), previous_sessions: Math.round(now * share * 0.95), previous_conversion_rate: round(cvr - delta),
      conversion_change_pts: now * share >= 100 ? round(delta) : null, too_few_sessions: now * share < 100 }));
    return { brand, ...info(p), window: windowOf(cur, base), min_sessions: 100, errors: {},
      countries: rows([['United States', 0.9, 2.1, 0.2], ['Canada', 0.04, 1.6, -0.1], ['United Kingdom', 0.025, 1.2, 0.1], ['Australia', 0.015, 1.4, 0], ['India', 0.02, 0.4, 0]]),
      us_states: rows([['California', 0.1, 1.9, 0.1], ['Texas', 0.08, 2.2, 0.3], ['Florida', 0.07, 2.0, -0.2], ['New York', 0.07, 2.4, 0.1], ['Illinois', 0.04, 2.1, 0]]) };
  }],
  ['GET', '/cro/landing-pages', ({ query, db }) => {
    const { brand } = storeOf(query);
    const p = plan(db, brand, query, 28, false);
    const { cur, base } = sessionDays(p);
    const now = sum(cur, 'sessions');
    const aov = brand === 'ridhi' ? 104 : 92;
    const pages = DEMO_PAGES.map(([path, type, share, bounce, cvr, src], i) => {
      const s = Math.round(now * share);
      const change = i === 4 ? 7.2 : i % 2 ? -1.1 : 0.8;
      const revenue = round((s * cvr * aov) / 100);
      return { path, page_type: type, sessions: s, bounce_rate: bounce, added_to_cart_rate: round(cvr * 3.2), conversion_rate: cvr, previous_sessions: Math.round(s * 0.92),
        previous_bounce_rate: round(bounce - change), bounce_change_pts: s >= 100 ? change : null, previous_conversion_rate: round(cvr * 0.95), conversion_change_pts: s >= 100 ? round(cvr * 0.05) : null,
        too_few_sessions: s < 100, revenue, orders: Math.round((s * cvr) / 100), revenue_per_session: s ? round(revenue / s) : null, top_source: src, top_source_share: 61 + i,
        bounce_flag: s >= 100 && change >= 5 };
    });
    const rows = (list) => list.map(([label, share, bounce, cvr, change]) => ({ label, sessions: Math.round(now * share), bounce_rate: bounce, added_to_cart_rate: round(cvr * 3), conversion_rate: cvr,
      previous_sessions: Math.round(now * share * 0.93), previous_bounce_rate: round(bounce - change), bounce_change_pts: change, previous_conversion_rate: round(cvr * 0.96),
      conversion_change_pts: round(cvr * 0.04), too_few_sessions: false, share_of_sessions: round(share * 100, 1) }));
    return { brand, ...info(p), window: windowOf(cur, base), min_sessions: 100, bounce_flag_pts: 5,
      bounce_definition: "Shopify's definition: a bounce is a visit that saw only one page. Bounce rate = bounces / visits. Bots left out.",
      revenue_available: true, revenue_note: 'Revenue = total sales of orders whose visit started on this page.', pages,
      page_types: rows([['Collection', 0.56, 52, 1.2, 0.6], ['Homepage', 0.22, 38, 3.4, -0.8], ['Product', 0.15, 44, 2.8, 0.4], ['Article', 0.05, 78, 0.3, 1.2], ['Page', 0.02, 70, 0.4, 0]]),
      by_source: rows([['social', 0.4, 58, 1.4, 1.1], ['direct', 0.3, 35, 3.1, -0.4], ['search', 0.2, 41, 2.4, 0.2], ['email', 0.06, 47, 4.2, -1.0]]),
      by_device: rows([['mobile', 0.72, 51, 1.9, 0.7], ['desktop', 0.2, 39, 3.6, -0.5], ['tablet', 0.08, 46, 2.2, 0.1]]), errors: {} };
  }],
  ['GET', '/cro/landing-grids', ({ query, db }) => {
    const { brand } = storeOf(query);
    const p = plan(db, brand, query, 28, false);
    const { cur, base } = sessionDays(p);
    const now = sum(cur, 'sessions');
    const r = rng(brand === 'ridhi' ? 5 : 9);
    const mk = (s, cvr) => ({ sessions: s, conversion_rate: s >= 30 ? round(cvr, 2) : null, added_to_cart_rate: s >= 30 ? round(cvr * 3.1, 2) : null, bounce_rate: s >= 30 ? round(70 - cvr * 8, 2) : null });
    const grid = (rows, cols, base) => {
      const raw = rows.map((_, i) => cols.map((_, j) => { const s = Math.round((now * (0.3 / (i + 1)) * (0.5 / (j + 1)))); return [s, base * (0.5 + r())]; }));
      const tot = (list) => { const s = list.reduce((a, [n]) => a + n, 0); return mk(s, s ? list.reduce((a, [n, c]) => a + n * c, 0) / s : 0); };
      return { rows, columns: cols, cells: raw.map((row) => row.map(([n, c]) => mk(n, c))), row_totals: raw.map(tot),
        column_totals: cols.map((_, j) => tot(raw.map((row) => row[j]))), total: tot(raw.flat()) };
    };
    return { brand, ...info(p), window: windowOf(cur, base), errors: {},
      page_by_source: grid(['/collections/quilts', '/', '/collections/tablecloths', '/products/demo-indigo-quilt', '/collections/sale'], ['social', 'direct', 'search', 'email'], 2),
      type_by_device: grid(['Collection', 'Homepage', 'Product', 'Article'], ['mobile', 'desktop', 'tablet'], 2.2) };
  }],
  ['GET', '/cro/site-health', ({ query, db }) => {
    const { brand } = storeOf(query);
    const p = plan(db, brand, query, 28, false);
    const { cur, base } = sessionDays(p);
    const vit = (lcp, inp, cls, loads, prev) => ({ page_loads: loads,
      lcp: { p75: lcp, rating: rating('lcp', lcp), good_share: 92.4, poor_share: 2.1, previous_p75: prev ? lcp + 60 : null, change: prev ? -60 : null },
      inp: { p75: inp, rating: rating('inp', inp), good_share: 88.1, poor_share: 3.0, previous_p75: prev ? inp - 12 : null, change: prev ? 12 : null },
      cls: { p75: cls, rating: rating('cls', cls), good_share: 96.5, poor_share: 1.2, previous_p75: prev ? cls : null, change: prev ? 0 : null } });
    const loads = sum(cur, 'sessions') * 2;
    const trend = cur.map((d, i) => ({ date: d.date, page_loads: Math.round(d.sessions * 1.4), lcp_s: round(1.35 + ((i * 7) % 5) / 20, 2), inp_ms: 130 + (i % 4) * 6, cls: 0.03 }));
    return { brand, ...info(p), window: windowOf(cur, base),
      limits: { lcp: { good: 2500, poor: 4000, unit: 'ms' }, inp: { good: 200, poor: 500, unit: 'ms' }, cls: { good: 0.1, poor: 0.25, unit: '' } },
      speed_available: true, devices: { Mobile: vit(1480, 138, 0.04, Math.round(loads * 0.78), true), Desktop: vit(1720, 122, 0.03, Math.round(loads * 0.22), true) },
      page_types: [['Collection', 1520, 140, 0.04], ['Homepage', 1390, 120, 0.02], ['Product', 1610, 150, 0.06], ['Article', 2680, 110, 0.12]].map(([label, l, n, c]) => ({ label, ...vit(l, n, c, 4000, false) })),
      pages: [['/collections/quilts', 1530], ['/', 1390], ['/collections/tablecloths', 1480], ['/products/demo-indigo-quilt', 1660], ['/blogs/news/care-guide', 2710]].map(([path, l]) => ({ path, ...vit(l, 140, 0.05, 2000, false) })),
      trend, late_note: null, errors: {},
      search: { sessions_with_searches: Math.round(sum(cur, 'sessions') * 0.033), share_of_sessions: 3.3, searcher_conversion_rate: 6.6, non_searcher_conversion_rate: 1.9,
        search_added_to_cart_rate: 16.2, search_click_rate: 67.5, searches: 5400, zero_result_searches: 31, zero_result_share: 0.6,
        top_terms: [['round tablecloth', 450, 45.6], ['quilt', 260, 51.2], ['christmas', 205, 35.1], ['napkins', 186, 38.2], ['runner', 134, 38.1]].map(([term, searches, click_rate]) => ({ term, searches, click_rate })),
        zero_result_terms: [['diary', 6], ['gift card holder', 3], ['92"', 1]].map(([term, searches]) => ({ term, searches })) } };
  }],
  ['GET', '/cro/overview-trends', ({ query, db }) => {
    const { brand } = storeOf(query);
    const p = plan(db, brand, query, 28, false);
    const { cur, base } = sessionDays(p);
    const aovOf = (d) => ({ date: d.date, aov: d.orders ? round((d.subtotal + d.discounts) / d.orders) : 0, orders: d.orders });
    const total = sum(cur, 'revenue');
    const ch = [['Online Store', 0.92], ['Shop', 0.05], ['Facebook & Instagram', 0.02], ['Draft Orders', 0.01]];
    return { brand, ...info(p), window: windowOf(cur, base), aov: cur.map(aovOf), previous_aov: base.map(aovOf), errors: {},
      channels: ch.map(([label, share]) => ({ label, total_sales: round(total * share), orders: Math.round(sum(cur, 'orders') * share), share_pct: round(share * 100, 1) })) };
  }],
  ['GET', '/cro/checkout-extras', ({ query, db }) => {
    const { brand } = storeOf(query);
    const p = plan(db, brand, query, 28);
    const { cur, base } = sessionDays(p);
    const orders = sum(p.current, 'orders');
    const attempts = Math.round(orders * 1.03);
    const method = (label, share, ok) => ({ label, attempts: Math.round(attempts * share), successful: Math.round(attempts * share * ok), failed_attempts: Math.round(attempts * share * (1 - ok) * 1.4),
      success_rate: round(ok * 100, 1), share_of_payments: round(share * 100, 1) });
    const VALUES = [0.03, 0.08, 0.14, 0.17, 0.16, 0.12, 0.09, 0.06, 0.05, 0.03, 0.02, 0.02, 0.03];
    const threshold = db.cro.freeShipping[STORE[brand]] ?? null;
    const near = threshold ? threshold * 0.8 : null;
    const values = (n, shift) => {
      const bars = VALUES.map((share, i) => ({ from: i * 25, label: i === 12 ? '$300+' : `$${i * 25}-${i * 25 + 24}`, orders: Math.round(n * share), share: round(share * 100, 1),
        near_threshold: !!(threshold && i * 25 < threshold && i * 25 + 25 > near) }));
      const inZone = threshold ? bars.filter((b) => b.near_threshold).reduce((a, b) => a + b.orders, 0) : null;
      const above = threshold ? bars.filter((b) => b.from >= threshold).reduce((a, b) => a + b.orders, 0) : null;
      return { orders: n, average: round(sum(p.current, 'subtotal') / Math.max(1, orders) * shift), median: round(95 * shift), bars, threshold,
        near_threshold_from: near, near_threshold_orders: inZone, near_threshold_share: threshold ? rate(inZone, n, 1) : null, at_or_above_threshold_share: threshold ? rate(above, n, 1) : null,
        items: { average: round(1.77 * shift), single_item_share: round(54 / shift, 1), bars: ITEMS.map((sh, i) => ({ label: i === 4 ? '5+' : String(i + 1), orders: Math.round(n * sh), share: round(sh * 100, 1) })) } };
    };
    const ITEMS = [0.54, 0.29, 0.1, 0.04, 0.03];
    return { brand, ...info(p), window: windowOf(cur, base), order_data: orderData, payments_error: null,
      payments: { methods: [method('credit_card', 0.92, 0.983), method('paypal', 0.05, 1), method('cardserver_token', 0.03, 0.977)],
        wallets: [method('shopify_pay', 0.7, 0.983), method('apple_pay', 0.17, 0.996), method('google_pay', 0.04, 0.99)],
        attempts, successful: Math.round(attempts * 0.983), failed_attempts: Math.round(attempts * 0.024), success_rate: 98.3, previous_success_rate: 97.9,
        previous_attempts: Math.round(attempts * 0.95), previous_failed_attempts: Math.round(attempts * 0.027),
        previous_methods: [method('credit_card', 0.9, 0.979), method('paypal', 0.07, 0.99), method('cardserver_token', 0.03, 0.97)],
        previous_wallets: [method('shopify_pay', 0.68, 0.98), method('apple_pay', 0.18, 0.995), method('google_pay', 0.04, 0.99)],
        latest_day_with_data: cur.length ? cur[cur.length - 1].date : null, errors: {} },
      order_values: values(orders, 1), previous_order_values: p.baselines.length ? values(Math.round(orders * 0.95), 0.97) : null,
      free_shipping_source: threshold ? 'settings' : null };
  }],
  ['GET', '/cro/product-insights', ({ query, db }) => {
    const { brand } = storeOf(query);
    const p = plan(db, brand, query, 28, false);
    const { cur, base } = sessionDays(p);
    return { brand, ...info(p), window: windowOf(cur, base), ...productInsights(db, brand, p), order_data: orderData };
  }],
  ['GET', '/cro/discount-codes', ({ query, db }) => {
    const { brand } = storeOf(query);
    const p = plan(db, brand, query, 28, false);
    const { cur, base } = sessionDays(p);
    const now = discountSummary(cur, brand === 'ridhi' ? 0.35 : 0.32);
    const before = base.length ? discountSummary(base, brand === 'ridhi' ? 0.36 : 0.4) : null;
    return { brand, ...info(p), window: windowOf(cur, base), ...now,
      previous: before && { total_orders: before.total_orders, with_code: before.with_code, without_code: before.without_code }, skipped: [] };
  }],
  ['GET', '/cro/customers', ({ query, db }) => {
    const { brand } = storeOf(query);
    const p = plan(db, brand, query, 28, false);
    const { cur, base } = sessionDays(p);
    return { brand, ...info(p), window: windowOf(cur, base), ...customersDemo(db, brand, p, cur, base), order_data: orderData };
  }],
  ['GET', '/cro/buy-heatmap', ({ query, db }) => {
    const { brand } = storeOf(query);
    const days = Math.max(7, Math.min(56, Number(query.days) || 28));
    const c = complete(db, brand).slice(-days);
    const sessions = sum(c, 'sessions'), done = sum(c, 'done');
    const avgCvr = rate(done, sessions);
    const cells = [];
    for (let w = 0; w < 7; w++) for (let h = 0; h < 24; h++) {
      const busy = h < 6 ? 0.2 : h < 9 ? 0.6 : h < 18 ? 1 : h < 23 ? 1.3 : 0.5;
      const s = Math.round((sessions / 168) * busy * (w >= 5 ? 1.15 : 1));
      const lift = (h >= 19 && h <= 22 ? 1.35 : h < 7 ? 0.6 : 1) * (w === 1 || w === 6 ? 1.1 : 1);
      cells.push({ weekday: w, hour: h, sessions: s, orders: Math.round((s * avgCvr * lift) / 100), cvr: s >= 20 ? round(avgCvr * lift) : null });
    }
    return { brand, days, from: c[0]?.date, to: c[c.length - 1]?.date, metric: 'cvr', weekdays: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'], cells,
      hours_with_data: cells.length, average_cvr: avgCvr, source: 'shopify_sessions' };
  }],
  ['GET', '/cro/home', ({ query, db }) => {
    const brands = query.brand ? [storeOf(query).brand] : ['ridhi', 'cpc'];
    return { stores: brands.map((brand) => {
      const all = rows(db, brand);
      const today = all[all.length - 1];
      const y = all[all.length - 2];
      const net = (d) => round(d.subtotal - d.refunded);
      const weeks = [8, 15, 22, 29].map((i) => all[all.length - 1 - i]);
      const lastWeek = { ...all[all.length - 8], ...scale(all[all.length - 8], 0.55) };
      const mk = (cur, bases, label, baseLabel) => {
        const early = cur.orders < 20;
        return { label, orders: block(cur.orders, avg(bases.map((b) => [b]), (s) => s[0].orders), early, baseLabel),
          net_sales: block(net(cur), avg(bases.map((b) => [b]), (s) => net(s[0])), early, baseLabel) };
      };
      const c = cvrComparison(db, brand);
      return { brand, state: 'ok', timezone: TZ[brand],
        yesterday: mk(y, weeks, 'Yesterday', 'vs 4-week weekday average'),
        today: mk(today, [lastWeek], 'Today so far', 'vs same time last week'),
        conversion: { value: c.yesterday_cvr, previous: c.previous_cvr, date: c.yesterday_date }, conversion_state: null,
        trend: complete(db, brand).slice(-14).map((d) => ({ date: d.date, orders: d.orders, revenue: round(d.revenue), net: net(d) })),
        last_order_at: hoursAgo(0.4), order_data: orderData };
    }) };
  }],
  ['GET', '/cro/recommendations', ({ query, db }) => {
    const { brand, store } = storeOf(query);
    const c = complete(db, brand).slice(-28);
    const sessions = sum(c, 'sessions');
    const cvr = rate(sum(c, 'done'), sessions);
    const aov = round(sum(c, 'subtotal') / Math.max(1, sum(c, 'orders')));
    const item = (kind, action, key, title, area, segment, evidence, visits, gap, extra = '') => ({ key, kind, action, effort: { landing_fix: 'Medium', landing_bounce: 'Medium', landing_promote: 'Low', source_test: 'Medium', source_promote: 'Low', payment_method: 'Low', product_leaky: 'Medium' }[kind],
      area, segment, title, explanation: evidence[0], evidence: evidence[0], evidence_list: evidence, priority: action === 'fix' ? 'High' : 'Medium', suggested_action: evidence.at(-1), affected_metric: area,
      impact: round(visits * gap / 100 * aov), impact_formula: `${visits.toLocaleString('en-US')} visits × ${gap.toFixed(2)} pts conversion gap × $${Math.round(aov)} average order${extra}` });
    const v = (share) => Math.round(sessions * share);
    const recs = [
      item('landing_fix', 'fix', 'landing_fix:/collections/quilts', `Fix landing page /collections/quilts: converts 0.90% vs ${cvr}% store`, 'Landing pages', 'Collection · /collections/quilts',
        [`${v(0.34).toLocaleString('en-US')} visits, conversion 0.90% vs store ${cvr}%`, 'Bounce 52.0%, add to cart 2.9%', 'Main traffic: social (61% of visits)'], v(0.34), Math.max(0.2, cvr - 0.9)),
      item('source_promote', 'promote', 'source_promote:email', `Grow Email traffic: converts 4.20% vs ${cvr}% store`, 'Landing pages', 'Traffic source · Email',
        [`${v(0.06).toLocaleString('en-US')} visits, conversion 4.20%`], v(0.06), 4.2 - cvr, ' (extra earned by these visits vs average)'),
      item('landing_bounce', 'fix', 'landing_bounce:/collections/sale', 'Bounce jumped on /collections/sale (+7.2 pts) and conversion fell', 'Landing pages', 'Collection · /collections/sale',
        ['Bounce 53.8% → 61.0% (before → now)', `Conversion 1.20% → 1.10% on ${v(0.06).toLocaleString('en-US')} visits`, 'Check the change log for what changed on this page'], v(0.06), 0.1),
      item('source_test', 'test', 'source_test:pinterest', 'Test a better landing page or offer for Pinterest traffic (0.60% conversion)', 'Landing pages', 'Traffic source · Pinterest',
        [`${v(0.03).toLocaleString('en-US')} visits, conversion 0.60% vs store ${cvr}%`, 'Bounce 71.4%'], v(0.03), Math.max(0.2, cvr - 0.6)),
    ];
    if (brand === 'ridhi') {
      const leaky = productInsights(db, brand, plan(db, brand, {}, 28, false)).groups?.fix_first ?? [];
      for (const f of leaky.slice(0, 5).filter((x) => x.left_on_table >= 50)) {
        const peers = f.compared_with.toLowerCase();
        const line = `${f.views.toLocaleString('en-US')} product views in 28 days (GA4), conversion ${f.conversion_rate.toFixed(2)}% vs ${f.category_rate.toFixed(2)}% for ${peers}`;
        recs.push({ key: `product_leaky:${f.product_id}`, kind: 'product_leaky', action: 'fix', effort: 'Medium', area: 'Products', segment: `Product · ${f.name}`,
          title: `Fix product page ${f.name}: converts ${f.conversion_rate.toFixed(2)}% vs ${f.category_rate.toFixed(2)}% for ${peers}`,
          explanation: line, evidence: line, evidence_list: [line, `Added to cart on ${f.add_to_cart_rate}% of views`, 'Check the photos, price, reviews, delivery promise and stock on this page'],
          priority: 'High', suggested_action: 'Check the photos, price, reviews, delivery promise and stock on this page', affected_metric: 'Products', impact: f.left_on_table,
          impact_formula: `${f.views.toLocaleString('en-US')} views × ${(f.category_rate - f.conversion_rate).toFixed(2)} pts conversion gap × $${Math.round(f.price)} price` });
      }
    }
    recs.sort((a, b) => b.impact - a.impact);
    recs.push({ key: 'product_gap:quilt', kind: 'check', action: 'fix', effort: 'Low', area: 'Products', segment: "Alarm · no 'quilt' order for 14h", title: "Orders for 'quilt' products have stalled",
      explanation: 'No order with a quilt product in the last 14 hours (alarm at 12h).', evidence: 'Last such order: #RBP1042, 14h ago', evidence_list: ['Last such order: #RBP1042, 14h ago', 'Check availability, pricing and ads pointed at these products.'],
      priority: 'High', suggested_action: 'Check availability, pricing and ads pointed at these products.', affected_metric: 'quilt orders', impact: null, impact_formula: '' });
    const status = db.cro.recStatus[store] ?? {};
    const out = recs.map((r, i) => ({ ...r, rank: i + 1, status: status[r.key] ?? 'open', status_updated_at: null }));
    const open = out.filter((r) => !['done', 'ignored'].includes(r.status));
    return { brand, window: { from: c[0]?.date, to: c.at(-1)?.date, base_from: null, base_to: null }, store_conversion_rate: cvr, sessions, aov, orders: sum(c, 'orders'),
      total_open_impact: round(open.reduce((a, r) => a + (r.impact ?? 0), 0)), recommendations: out, statuses_available: true, status_error: null, skipped: [], order_data: orderData };
  }],
  ['POST', '/cro/recommendations/status', ({ query, body, db }) => {
    const { store } = storeOf(query);
    if (!body.key || !['open', 'in_progress', 'done', 'ignored'].includes(body.status)) throw new DemoError(400, 'status must be one of: open, in_progress, done, ignored.', 'bad_request');
    db.cro.recStatus[store] = { ...(db.cro.recStatus[store] ?? {}), [body.key]: body.status };
    return { key: body.key, status: body.status };
  }],
  ['GET', '/cro/experiments', ({ query, db }) => {
    const { brand, store } = storeOf(query);
    const items = db.cro.experiments.filter((e) => e.store === store).sort((a, b) => b.start_date.localeCompare(a.start_date)).map((e) => withResult(db, brand, e));
    const finished = items.filter((e) => e.result.state === 'finished');
    const won = finished.filter((e) => ['win', 'better'].includes(e.result.verdict)).length;
    return { brand, experiments: items, change_log: db.cro.changes.filter((c) => c.store === store), metrics: Object.entries(EXP_METRICS).map(([key, v]) => ({ key, ...v })),
      summary: { total: items.length, planned: items.filter((e) => e.result.state === 'planned').length, running: items.filter((e) => e.result.state === 'running').length,
        finished: finished.length, won, win_rate: finished.length ? Math.round((won / finished.length) * 100) : null } };
  }],
  ['POST', '/cro/experiments', ({ query, body, db }) => {
    const { brand, store } = storeOf(query);
    const row = { id: nextId() + 2000, store, ...cleanExperiment(body), created_by: 'demo', created_at: new Date().toISOString() };
    db.cro.experiments.push(row);
    return withResult(db, brand, row);
  }],
  ['PATCH', '/cro/experiments/:id', ({ params, query, body, db }) => {
    const { brand, store } = storeOf(query);
    const row = db.cro.experiments.find((e) => String(e.id) === params.id && e.store === store);
    if (!row) throw new DemoError(400, 'No such experiment for this store.', 'bad_request');
    Object.assign(row, cleanExperiment(body));
    return withResult(db, brand, row);
  }],
  ['DELETE', '/cro/experiments/:id', ({ params, query, db }) => {
    const { store } = storeOf(query);
    const i = db.cro.experiments.findIndex((e) => String(e.id) === params.id && e.store === store);
    if (i < 0) throw new DemoError(404, 'No such experiment for this store.', 'not_found');
    db.cro.experiments.splice(i, 1);
    return { deleted: Number(params.id) };
  }],
  // The monthly revenue goal (modules/cro/goals.py).
  ['GET', '/cro/goal', ({ query, db }) => ({ brand: storeOf(query).brand, monthly_revenue: db.cro.goals?.[storeOf(query).brand] ?? 0, updated_at: null })],
  ['PUT', '/cro/goal', ({ query, body, db }) => {
    const { brand } = storeOf(query);
    const v = Number(body.monthly_revenue);
    if (!Number.isFinite(v) || v < 0) throw new DemoError(400, 'monthly_revenue must be a number.', 'bad_request');
    db.cro.goals = { ...(db.cro.goals ?? {}), [brand]: v };
    return { brand, monthly_revenue: v, updated_at: hoursAgo(0) };
  }],
  // Claude's action plan (modules/cro/ai_advice.py). The demo never calls Claude: a fixed, fictional plan is shown.
  ['GET', '/cro/ai-advice', ({ query, db }) => adviceState(db, storeOf(query).brand)],
  ['POST', '/cro/ai-advice', ({ query, db }) => {
    const { brand } = storeOf(query);
    db.cro.advice = { ...(db.cro.advice ?? {}), [brand]: hoursAgo(0) };
    return adviceState(db, brand);
  }],
  ['GET', '/cro/benchmarks', () => ({ benchmarks: BENCHMARKS })],
  ['GET', '/cro/alarms', ({ query, db }) => {
    const { brand, store } = storeOf(query);
    const rules = rulesOf(db, store).map((r) => {
      const mine = db.cro.alerts.filter((a) => a.rule_id === r.id).sort((a, b) => (a.triggered_at < b.triggered_at ? 1 : -1));
      return { ...r, open_alert: mine.find((a) => !a.resolved_at) ?? null, last_triggered_at: mine[0]?.triggered_at ?? null };
    });
    return { brand, alarms_enabled: db.cro.enabled[store], rules };
  }],
  ['POST', '/cro/alarms', ({ query, body, db }) => {
    const { store } = storeOf(query);
    if (!['cvr_drop', 'no_product_orders'].includes(body.kind)) throw new DemoError(400, 'kind must be cvr_drop or no_product_orders.', 'bad_request');
    checkKeyword(body.kind, body);
    const kw = body.kind === 'no_product_orders' ? String(body.product_keyword).trim() : null;
    if (rulesOf(db, store).some((r) => r.kind === body.kind && (r.product_keyword || '').toLowerCase() === (kw || '').toLowerCase())) throw new DemoError(409, 'Another run is already in progress, or the row already exists.', 'conflict');
    const rule = { id: nextId() + 100, store, kind: body.kind, title: String(body.title || '').trim() || 'New alarm', threshold: checkThreshold(body.kind, body.threshold),
      product_keyword: kw, is_active: body.is_active !== false, last_checked_at: null };
    db.cro.rules.push(rule);
    return rule;
  }],
  ['PATCH', '/cro/alarms/:id', ({ params, query, body, db }) => {
    const { store } = storeOf(query);
    const rule = rulesOf(db, store).find((r) => String(r.id) === params.id);
    if (!rule) throw new DemoError(404, 'No such alarm rule for this store.', 'not_found');
    if ('is_active' in body) rule.is_active = !!body.is_active;
    if ('threshold' in body) rule.threshold = checkThreshold(rule.kind, body.threshold);
    if ('title' in body) rule.title = String(body.title).trim() || rule.title;
    if ('product_keyword' in body) { checkKeyword(rule.kind, body); rule.product_keyword = String(body.product_keyword).trim(); }
    return rule;
  }],
  ['GET', '/cro/alerts', ({ query, db }) => {
    const { brand, store } = storeOf(query);
    const titles = Object.fromEntries(db.cro.rules.map((r) => [r.id, r.title]));
    return { brand, alerts: db.cro.alerts.filter((a) => a.store === store).map((a) => ({ ...a, details: {}, rule: titles[a.rule_id] })) };
  }],
  ['GET', '/cro/settings', ({ query, db }) => {
    const { brand, store } = storeOf(query);
    return { brand, store, timezone: TZ[brand], alarms_enabled: db.cro.enabled[store], shopify_configured: true,
      sync: { store, cursor: hoursAgo(0.1), last_status: 'ok', last_run_at: hoursAgo(0.1) }, order_data: orderData,
      free_shipping_threshold: db.cro.freeShipping[store] ?? null, email_alerts: false };
  }],
  ['PATCH', '/cro/settings', ({ query, body, db }) => {
    const { brand, store } = storeOf(query);
    if (!('alarms_enabled' in body) && !('free_shipping_threshold' in body)) throw new DemoError(400, 'Send alarms_enabled and/or free_shipping_threshold.', 'bad_request');
    if ('alarms_enabled' in body) {
      if (typeof body.alarms_enabled !== 'boolean') throw new DemoError(400, 'alarms_enabled must be true or false.', 'bad_request');
      db.cro.enabled[store] = body.alarms_enabled;
    }
    if ('free_shipping_threshold' in body) {
      const v = body.free_shipping_threshold === null || body.free_shipping_threshold === '' ? null : Number(body.free_shipping_threshold);
      if (v !== null && !(v > 0 && v < 100000)) throw new DemoError(400, 'The free-shipping amount must be above 0 and below 100,000.', 'bad_request');
      db.cro.freeShipping[store] = v;
    }
    return { brand, store, alarms_enabled: db.cro.enabled[store], email_alerts: false, free_shipping_threshold: db.cro.freeShipping[store] ?? null };
  }],
  ['POST', '/cro/sync', ({ query }) => {
    const { store } = storeOf(query);
    return { store, state: 'ok', mode: 'changes', orders_read: 0, orders_written: 0, alarms: { store, state: 'checked', rules: {} } };
  }],
  ['GET', '/cro/status', () => ({ last_run: { at: hoursAgo(0.1), stores: {} } })],
  ['GET', '/cro/change-log', ({ query, db }) => {
    const { brand, store } = storeOf(query);
    const since = dayAgo(Math.max(1, Math.min(730, Number(query.days) || 90)));
    const entries = db.cro.changes.filter((e) => e.store === store && e.entry_date >= since).sort((a, b) => (a.entry_date < b.entry_date ? 1 : -1));
    return { brand, areas: ['theme', 'app', 'price', 'promo', 'ad', 'other'], entries };
  }],
  ['POST', '/cro/change-log', ({ query, body, db }) => {
    const { store } = storeOf(query);
    const change = String(body.change || '').trim();
    if (!change || change.length > 1000) throw new DemoError(400, 'Describe the change in 1 to 1000 characters.', 'bad_request');
    const entry = { id: nextId() + 1000, store, entry_date: body.entry_date || dayAgo(0), change,
      area: ['theme', 'app', 'price', 'promo', 'ad', 'other'].includes(body.area) ? body.area : 'other',
      owner: String(body.owner || '').trim() || null, created_by: 'demo', created_at: new Date().toISOString() };
    db.cro.changes.push(entry);
    return entry;
  }],
  ['DELETE', '/cro/change-log/:id', ({ params, query, db }) => {
    const { store } = storeOf(query);
    const i = db.cro.changes.findIndex((e) => String(e.id) === params.id && e.store === store);
    if (i < 0) throw new DemoError(404, 'No such change-log entry for this store.', 'not_found');
    db.cro.changes.splice(i, 1);
    return { deleted: Number(params.id) };
  }],
  // Store notes for Claude (modules/cro/ai_advice.py notes / set_notes).
  ['GET', '/cro/store-notes', ({ query, db }) => notesOf(db, storeOf(query).brand)],
  ['PUT', '/cro/store-notes', ({ query, body, db }) => {
    const { brand } = storeOf(query);
    const text = String(body.text ?? '').trim();
    if (text.length > 3000) throw new DemoError(400, 'Keep the notes to 3,000 characters or fewer.', 'bad_request');
    db.cro.notes = { ...(db.cro.notes ?? {}), [brand]: { text, updated_at: new Date().toISOString(), updated_by: 'demo' } };
    return notesOf(db, brand);
  }],
  // Landing pages week / month compare, funnel by page, date-wise and one page's deep dive (modules/cro/landing_detail.py).
  ['GET', '/cro/landing-compare', ({ query, db }) => {
    const { brand } = storeOf(query);
    const mode = lpMode(query);
    const { cur, base } = lpWindows(db, brand, mode);
    const pages = DEMO_PAGES.map((pg) => {
      const d = lpDaily(db, brand, pg);
      const now = lpTotal(lpIn(d, cur)), before = lpTotal(lpIn(d, base));
      return { path: pg[0], page_type: pg[1], now, before, change: lpChange(now, before), low_data: now.sessions < 100 || before.sessions < 100 };
    }).sort((a, b) => b.now.sessions - a.now.sessions);
    return { brand, mode, current: lpSpan(cur), previous: lpSpan(base), min_sessions: 100, revenue_available: true, pages, errors: {} };
  }],
  ['GET', '/cro/landing-funnel', ({ query, db }) => {
    const { brand } = storeOf(query);
    const mode = lpMode(query);
    const { cur, base } = lpWindows(db, brand, mode);
    const pages = DEMO_PAGES.map((pg) => {
      const d = lpDaily(db, brand, pg);
      const now = lpFunnel(lpTotal(lpIn(d, cur)), pg), before = lpFunnel(lpTotal(lpIn(d, base)), pg);
      const step_change_pts = Object.fromEntries(now.steps.map((s, i) => [s.key, s.pct_of_sessions === null || before.steps[i].pct_of_sessions === null ? null : round(s.pct_of_sessions - before.steps[i].pct_of_sessions)]));
      return { path: pg[0], page_type: pg[1], now, before, sessions_change: now.sessions - before.sessions,
        sessions_change_pct: before.sessions ? round(((now.sessions - before.sessions) / before.sessions) * 100, 1) : null, step_change_pts, low_data: now.sessions < 100 || before.sessions < 100 };
    }).sort((a, b) => b.now.sessions - a.now.sessions);
    return { brand, mode, current: lpSpan(cur), previous: lpSpan(base), min_sessions: 100, pages, errors: {} };
  }],
  ['GET', '/cro/landing-daily', ({ query, db }) => {
    const { brand } = storeOf(query);
    const n = Math.max(7, Math.min(60, Number(query.days) || 60));
    const choices = DEMO_PAGES.map((pg) => ({ path: pg[0], page_type: pg[1], sessions: lpTotal(lpDaily(db, brand, pg).slice(-30)).sessions })).sort((a, b) => b.sessions - a.sessions);
    const asked = String(query.paths || '').split(',').map((p) => p.trim()).filter(Boolean);
    const chosen = (asked.length ? asked.filter((p) => DEMO_PAGES.some((pg) => pg[0] === p)) : choices.slice(0, 8).map((c) => c.path)).slice(0, 12);
    const pages = chosen.map((path) => {
      const pg = DEMO_PAGES.find((x) => x[0] === path);
      return { path, page_type: pg[1], rows: lpDaily(db, brand, pg).slice(-n) };
    });
    return { brand, from: pages[0]?.rows[0]?.date ?? null, to: pages[0]?.rows.at(-1)?.date ?? null, pages, choices, revenue_available: true, errors: {} };
  }],
  ['GET', '/cro/landing-page', ({ query, db }) => {
    const { brand } = storeOf(query);
    const pg = DEMO_PAGES.find((x) => x[0] === String(query.path || '').trim().toLowerCase());
    if (!pg) throw new DemoError(400, 'Give a landing page path like /collections/quilts.', 'bad_request');
    const daily = lpDaily(db, brand, pg);
    const blocks = {};
    const segs = {};
    const funnel = {};
    for (const mode of ['week', 'month']) {
      const { cur, base } = lpWindows(db, brand, mode);
      const now = lpTotal(lpIn(daily, cur)), before = lpTotal(lpIn(daily, base));
      blocks[mode] = { current: lpSpan(cur), previous: lpSpan(base), now, before, change: lpChange(now, before) };
      segs[`sources_${mode}`] = lpSegments(now, before, [['social', 0.66, 1.1], ['direct', 0.18, 0.8], ['search', 0.1, 1.3], ['email', 0.04, 1.8], ['unknown', 0.02, 0.5]], mode === 'week' ? 50 : 100);
      segs[`devices_${mode}`] = lpSegments(now, before, [['mobile', 0.84, 0.95], ['desktop', 0.11, 1.3], ['tablet', 0.05, 1.0]], mode === 'week' ? 50 : 100);
      const dev = (t, label, share, lift) => ({ label, ...lpFunnel({ ...t, sessions: Math.round(t.sessions * share), added_to_cart_rate: t.added_to_cart_rate * lift, orders: Math.round(t.orders * share * lift) }, pg) });
      const split = (t) => ({ all: lpFunnel(t, pg), devices: [dev(t, 'Mobile', 0.84, 0.95), dev(t, 'Desktop', 0.11, 1.3), dev(t, 'Tablet', 0.05, 1.0)] });
      funnel[mode] = { now: split(now), before: split(before) };
    }
    const countries = lpSegments(blocks.month.now, blocks.month.before, [['United States', 0.93, 1], ['Canada', 0.03, 0.7], ['United Kingdom', 0.02, 0.8], ['Australia', 0.01, 0.6], ['India', 0.01, 0.2]], 100);
    return { brand, path: pg[0], days: daily.length, week: blocks.week, month: blocks.month, daily, ...segs, countries, funnel,
      what_changed: lpWhatChanged(blocks.week, blocks.month, segs.sources_week), revenue_available: true, errors: {} };
  }],
];

/* ------------------------------------------------------------------ store notes and landing pages (demo) */
function notesOf(db, brand) {
  const n = db.cro.notes?.[brand];
  return { brand, text: n?.text ?? '', updated_at: n?.updated_at ?? null, updated_by: n?.updated_by ?? null, max_length: 3000 };
}

/** The demo's landing pages: [path, page type, share of the store's visits, bounce %, conversion %, top source]. */
const DEMO_PAGES = [['/collections/quilts', 'Collection', 0.34, 52, 0.9, 'social'], ['/', 'Homepage', 0.22, 38, 3.4, 'direct'], ['/collections/tablecloths', 'Collection', 0.14, 49, 1.6, 'social'],
  ['/products/demo-indigo-quilt', 'Product', 0.08, 44, 2.8, 'search'], ['/collections/sale', 'Collection', 0.06, 61, 1.1, 'email'], ['/blogs/news/care-guide', 'Article', 0.03, 78, 0.3, 'search'],
  ['/pages/about', 'Page', 0.004, 70, 0.4, 'direct']];
const lpMode = (query) => (query.mode === 'month' ? 'month' : 'week');
const lpSeed = (s) => [...s].reduce((a, c) => (Math.imul(a, 31) + c.charCodeAt(0)) >>> 0, 7);
/** The page's last 60 complete days, generated from the store's own days so totals stay in line with the other tabs. */
function lpDaily(db, brand, [path, , share, bounce, cvr]) {
  const r = rng(lpSeed(`${brand}${path}`));
  const aov = brand === 'ridhi' ? 104 : 92;
  return complete(db, brand).slice(-60).map((d) => {
    const s = Math.round(d.sessions * share * (0.85 + r() * 0.3));
    const orders = Math.round((s * cvr * (0.7 + r() * 0.6)) / 100);
    const revenue = round(orders * aov * (0.9 + r() * 0.2));
    return { date: d.date, sessions: s, bounce_rate: round(bounce * (0.92 + r() * 0.16)), added_to_cart_rate: round(cvr * 3.2 * (0.85 + r() * 0.3)),
      conversion_rate: s ? round((orders / s) * 100) : null, orders, revenue, revenue_per_session: s ? round(revenue / s) : null, aov: orders ? round(revenue / orders) : null };
  });
}
function lpWindows(db, brand, mode) {
  const days = complete(db, brand).slice(-60).map((d) => d.date);
  const n = mode === 'month' ? 30 : 7;
  return { cur: days.slice(-n), base: days.slice(-2 * n, -n) };
}
const lpIn = (daily, dates) => daily.filter((d) => dates.includes(d.date));
const lpSpan = (dates) => ({ from: dates[0], to: dates[dates.length - 1] });
function lpTotal(rows) {
  const s = sum(rows, 'sessions');
  const w = (k) => (s ? round(rows.reduce((a, r) => a + (r[k] || 0) * r.sessions, 0) / s) : null);
  const revenue = round(sum(rows, 'revenue'));
  const orders = sum(rows, 'orders');
  return { sessions: s, bounce_rate: w('bounce_rate'), added_to_cart_rate: w('added_to_cart_rate'), conversion_rate: w('conversion_rate'), orders, revenue,
    revenue_per_session: s ? round(revenue / s) : null, aov: orders ? round(revenue / orders) : null };
}
const lpPct = (a, b) => (a === null || !b ? null : round(((a - b) / Math.abs(b)) * 100, 1));
const lpPts = (a, b) => (a === null || b === null ? null : round(a - b));
const lpChange = (n, b) => ({ sessions: n.sessions - b.sessions, sessions_pct: lpPct(n.sessions, b.sessions), bounce_pts: lpPts(n.bounce_rate, b.bounce_rate),
  added_to_cart_pts: lpPts(n.added_to_cart_rate, b.added_to_cart_rate), conversion_pts: lpPts(n.conversion_rate, b.conversion_rate), orders: n.orders - b.orders,
  orders_pct: lpPct(n.orders, b.orders), revenue: round(n.revenue - b.revenue), revenue_pct: lpPct(n.revenue, b.revenue),
  revenue_per_session_pct: lpPct(n.revenue_per_session, b.revenue_per_session), aov_pct: lpPct(n.aov, b.aov) });
/** A page's funnel from its totals: product pages are a product view by definition; others about a third. */
function lpFunnel(t, pg) {
  const s = t.sessions;
  const viewed = Math.round(s * (pg[1] === 'Product' ? 1 : 0.35));
  const cart = Math.min(viewed, Math.round((s * (t.added_to_cart_rate || 0)) / 100));
  const done = Math.min(cart, t.orders);
  const checkout = Math.max(done, Math.round(cart * 0.45));
  const counts = [['viewed_product', viewed], ['added_to_cart', cart], ['reached_checkout', checkout], ['completed_checkout', done]];
  return { sessions: s, steps: counts.map(([key, count], i) => ({ key, count, pct_of_sessions: rate(count, s), step_pct: rate(count, i ? counts[i - 1][1] : s, 1) })),
    purchase_rate: rate(done, s), checkout_abandonment: rate(checkout - done, checkout, 1) };
}
/** A page's sources, devices or countries: the page's totals split by fixed shares, conversion lifted per segment. */
function lpSegments(now, before, parts, least) {
  const one = (t, share, lift, k) => ({ sessions: Math.round(t.sessions * share * (k ? 0.97 : 1)), bounce_rate: round((t.bounce_rate || 0) / Math.sqrt(lift)),
    added_to_cart_rate: round((t.added_to_cart_rate || 0) * lift), conversion_rate: round((t.conversion_rate || 0) * lift) });
  return parts.map(([label, share, lift], k) => {
    const v = one(now, share, lift, 0), p = one(before, share, lift, k % 2);
    const low = v.sessions < least || p.sessions < least;
    return { label, ...v, share: round(share * 100, 1), previous_sessions: p.sessions, sessions_change: v.sessions - p.sessions, sessions_change_pct: lpPct(v.sessions, p.sessions),
      bounce_change_pts: low ? null : lpPts(v.bounce_rate, p.bounce_rate), added_to_cart_change_pts: low ? null : lpPts(v.added_to_cart_rate, p.added_to_cart_rate),
      conversion_change_pts: low ? null : lpPts(v.conversion_rate, p.conversion_rate), low_data: low };
  });
}
function lpWhatChanged(week, month, sources) {
  const out = [];
  const c = week.change;
  if (c.bounce_pts !== null && Math.abs(c.bounce_pts) >= 3) out.push({ text: `Bounce rate ${c.bounce_pts > 0 ? 'up' : 'down'} ${Math.abs(c.bounce_pts).toFixed(1)} pts week on week.`, tone: c.bounce_pts > 0 ? 'bad' : 'good' });
  if (c.conversion_pts !== null && Math.abs(c.conversion_pts) >= 0.3) out.push({ text: `Conversion ${c.conversion_pts > 0 ? 'up' : 'down'} ${Math.abs(c.conversion_pts).toFixed(2)} pts week on week.`, tone: c.conversion_pts > 0 ? 'good' : 'bad' });
  for (const [label, b] of [['WoW', week], ['MoM', month]]) {
    if (b.change.sessions_pct !== null && Math.abs(b.change.sessions_pct) >= 5) out.push({ text: `Sessions ${b.change.sessions_pct > 0 ? '+' : ''}${Math.round(b.change.sessions_pct)}% ${label} (${b.before.sessions.toLocaleString()} -> ${b.now.sessions.toLocaleString()}).`, tone: b.change.sessions_pct > 0 ? 'good' : 'bad' });
  }
  if (sources[0]) out.push({ text: `Biggest traffic source: ${sources[0].label} (${sources[0].share}% of visits). Demo figures.`, tone: 'info' });
  return out;
}

/* ------------------------------------------------------------------ Claude's action plan (demo) */
function adviceState(db, brand) {
  const top = [...db.cro.products[brand]].sort((a, b) => b.units30 * b.price - a.units30 * a.price)[0];
  return {
    brand, configured: true, status: 'ready', fresh: true, day: dayAgo(0), generated_at: db.cro.advice?.[brand] ?? hoursAgo(2), by: 'demo',
    model: 'demo', not_available: [], error: null, estimate_usd: 0.3,
    budget: { todayUsd: 0.6, dailyLimitUsd: 3, remainingTodayUsd: 2.4, monthlyBudgetUsd: 90, monthUsd: 21.4, warning: null },
    advice: {
      summary: `Demo plan. Sales are steady against last month; most visitors leave between the cart and checkout. '${top.name}' carries the store, so its page is the best place to test first.`,
      actions: [
        { title: 'Show delivery cost and time before checkout', impact: 'High', effort: 'Low', area: 'checkout', metric: 'Checkout completion',
          why: 'About two thirds of shoppers who add to cart do not reach checkout. Surprise costs are the most common reason.',
          evidence: 'Demo figures: cart rate 7.1%, checkout rate 3.2% over the last 30 days.',
          steps: ['Add a delivery estimate under the Add to cart button', 'State the free-delivery threshold in the cart', 'Check the cart on a phone'] },
        { title: `Feature '${top.name}' on the home page and in ads`, impact: 'High', effort: 'Medium', area: 'merchandising', metric: 'Revenue',
          why: 'Your best seller earns the most per visit; more visitors on its page should mean more orders.',
          evidence: `Demo figures: ${top.units30} sold in 30 days, the highest of any product.`,
          steps: ['Move it into the first home-page banner', 'Point the best-performing ad at its page', 'Add 3 more lifestyle photos'] },
        { title: 'Win back mobile shoppers', impact: 'Medium', effort: 'Medium', area: 'product_page', metric: 'Mobile conversion',
          why: 'Phones bring most sessions but convert below desktop.',
          evidence: 'Demo figures: mobile converts at about half the desktop rate.',
          steps: ['Shorten the product description above the fold', 'Make the Add to cart button sticky on phones'] },
        { title: 'Ask happy customers for reviews', impact: 'Medium', effort: 'Low', area: 'trust', metric: 'Conversion rate',
          why: 'Reviews raise trust on product pages with few photos.', evidence: 'Demo figures: refunds stay under 3% of orders.',
          steps: ['Send a review request 10 days after delivery', 'Show the review count under each product title'] },
      ],
    },
  };
}
