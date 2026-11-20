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
    return { brand, ...info(p), days: complete.length, trend: complete.map(funnelRow), total: t, baseline_total: b,
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
    const { brand } = storeOf(query);
    const recs = [];
    const quilt = db.cro.products[brand].find((p) => p.units7 * 4 < p.units30 * 0.5);
    if (quilt) {
      recs.push({ title: `'${quilt.name}' sales are declining`, explanation: 'Revenue from this product fell sharply in the last 7 days against the 7 days before.',
        evidence: `Prior 7 days: ${round(quilt.units30 / 4 * quilt.price)} (${Math.round(quilt.units30 / 4)} sold) -> last 7 days: ${round(quilt.units7 * quilt.price)} (${quilt.units7} sold)`,
        priority: 'High', suggested_action: 'Check stock, price and the product page.', affected_metric: quilt.name });
    }
    const f = funnelRow(complete(db, brand).at(-1));
    if (f.checkout_completion_rate !== null && f.checkout_completion_rate <= 55) {
      recs.push({ title: 'Few checkouts are completed', explanation: `Only ${f.checkout_completion_rate}% of the sessions that reached checkout completed the purchase.`,
        evidence: `Reached checkout: ${f.reached_checkout}, completed: ${f.completed_checkout} (${f.date})`, priority: 'Medium',
        suggested_action: 'Check payment methods, shipping-cost visibility and checkout load time.', affected_metric: 'Checkout completion' });
    }
    return { brand, recommendations: recs, skipped: [], order_data: orderData };
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
      sync: { store, cursor: hoursAgo(0.1), last_status: 'ok', last_run_at: hoursAgo(0.1) }, order_data: orderData, email_alerts: false };
  }],
  ['PATCH', '/cro/settings', ({ query, body, db }) => {
    const { brand, store } = storeOf(query);
    if (typeof body.alarms_enabled !== 'boolean') throw new DemoError(400, 'alarms_enabled must be true or false.', 'bad_request');
    db.cro.enabled[store] = body.alarms_enabled;
    return { brand, store, alarms_enabled: body.alarms_enabled, email_alerts: false };
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
];

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
