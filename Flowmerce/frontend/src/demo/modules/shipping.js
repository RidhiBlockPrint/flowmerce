/**
 * Demo module: Shipping. Everything here is synthetic (fake order numbers, fictional carriers, no customer data).
 *
 * Collection `db.shipping`:
 *   shipments: one record per parcel (an order can have several), as stored by the real Shipping database:
 *     { id, brand: 'ridhi'|'cpc', order_number: 'DEMO-#10001', tracking_number ('' = missing), carrier_name ('' = unknown),
 *       order_created_at, fulfilled_at (dispatch, null = not dispatched), expected_delivery_at (promised date), delivered_at,
 *       last_scan_at, last_scan_description, last_scan_location, normalized_tracking_status
 *       ('', pending, in_transit, out_for_delivery, delivered, failed_delivery, returned), exception ('', failed_delivery,
 *       returned, address_issue), delay_reason, order_total, order_currency, city, state, items: [{name, qty, price}],
 *       events: [{at, status, description, location}], manual: null | {status: delivered|lost|failed|in_transit, at} }
 *   checks: one per order: { order_number, brand, order_created_at, fulfillment_status, financial_status, cancelled,
 *       says_done, order_total, order_currency }
 *   annotations: { [order_number]: { reviewedAt, reviewedBy, flagged, flaggedAt, notes: [{at, by, text}] } }
 *       (the frontend-only actions in the order drawer: Mark as checked, Flag for escalation, Add note)
 * Timestamps are ISO strings generated relative to the first load, and ages are recomputed from "now" on every request,
 * so the delayed / critical indicators always make sense. Category rules are the real ones (aging.py).
 */
import { DemoError, csvDownload, rng } from '../util.js';

const H = 3600 * 1000;
const D = 24 * H;
const THRESH = { grey: 2, yellow: 4, orange: 6, red: 9 };
const NO_MOVE_DAYS = 5;
const RANK = { red: 0, orange: 1, yellow: 2, grey: 3, no_scan: 4, on_track: 5, unconfirmed: 5, lost: 5, failed: 5, delivered: 6 };
const LABELS = { on_track: 'On Track', grey: 'Grey 2-3 days', yellow: 'Yellow 4-5 days', orange: 'Orange 6-8 days', red: 'Red 9+ days', no_scan: 'No scan data', delivered: 'Delivered', unconfirmed: 'Carrier unconfirmed', lost: 'Lost (team confirmed)', failed: "Couldn't deliver (team confirmed)" };
const ACTIONS = { on_track: 'Continue monitoring.', grey: 'Continue monitoring.', yellow: 'Review if carrier SLA or expected delivery date shows a problem.', orange: 'Prioritize for investigation.', red: 'Add to urgent escalation list.', no_scan: 'Verify tracking details or wait for the first carrier scan.', delivered: 'None. Delivered.' };
const AGING_KEYS = ['red', 'orange', 'yellow', 'grey', 'on_track', 'no_scan'];
const AGING_LABELS = { red: 'Critical 9+', orange: 'Orange 6-8', yellow: 'Yellow 4-5', grey: 'Grey 2-3', on_track: 'On track', no_scan: 'No scan' };
const MCF_LEVELS = [[10, 'critical'], [7, 'watch'], [5, 'alert']];
export const IMPORT_CARRIERS = ['Standard Ground', 'Express Air', 'Regional Post', 'Economy Freight', 'Marketplace Logistics'];
const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

const iso = (ms) => (ms === null || ms === undefined ? null : new Date(ms).toISOString());
const ms = (s) => (s ? Date.parse(s) : null);
const completeDays = (since, now) => (since === null || since === undefined ? null : Math.max(0, Math.floor((now - since) / D)));

/* ------------------------------------------------------------------ seed */
const CARRIERS = {
  'Standard Ground': { p: 'SG', sla: 6, tr: [4, 8], w: 40 },
  'Express Air': { p: 'EA', sla: 3, tr: [2, 4], w: 25 },
  'Regional Post': { p: 'RP', sla: 5, tr: [3, 7], w: 20 },
  'Economy Freight': { p: 'EF', sla: 9, tr: [6, 11], w: 15 },
};
const PLACES = [
  ['Austin', 'TX'], ['Dallas', 'TX'], ['Denver', 'CO'], ['Seattle', 'WA'], ['Portland', 'OR'], ['Chicago', 'IL'], ['Atlanta', 'GA'],
  ['Miami', 'FL'], ['Boston', 'MA'], ['Brooklyn', 'NY'], ['Phoenix', 'AZ'], ['Nashville', 'TN'], ['Columbus', 'OH'], ['Minneapolis', 'MN'],
  ['Charlotte', 'NC'], ['San Diego', 'CA'], ['Oakland', 'CA'], ['Raleigh', 'NC'],
];
const ITEMS = {
  ridhi: [['Indigo Block Print Tablecloth', 84], ['Set of 6 Cotton Napkins', 36], ['Hand Block Print Quilt', 168], ['Cushion Cover (Pair)', 42], ['Block Print Table Runner', 38], ['Block Print Bedsheet Set', 120]],
  cpc: [['Cotton Placemats (Set of 4)', 32], ['Printed Tea Towels (Set of 3)', 24], ['Seasonal Table Runner', 40], ['Printed Cotton Apron', 28], ['Napkin Set (Set of 8)', 44]],
};
const DELAY_REASONS = ['Carrier hub backlog', 'Weather disruption on the route', 'Awaiting customs-style paperwork check', 'Parcel held at regional hub', 'Address verification pending', 'High seasonal volume'];
const TEMPLATE = [
  ['in_transit', 'Picked up from sender', 'Origin facility'],
  ['in_transit', 'Departed origin facility', 'Origin facility'],
  ['in_transit', 'Arrived at regional hub', 'Regional hub'],
  ['in_transit', 'Departed regional hub', 'Regional hub'],
  ['in_transit', 'Arrived at local delivery facility', null],
  ['out_for_delivery', 'Out for delivery', null],
];

export function seed(db) {
  const r = rng(20260);
  const now = Date.now();
  const between = (a, b) => a + r() * (b - a);
  const ib = (a, b) => Math.floor(between(a, b + 1));
  const pick = (arr) => arr[Math.floor(r() * arr.length)];
  const carrierPick = (weights) => {
    const entries = Object.entries(CARRIERS);
    const total = entries.reduce((s, [k, c]) => s + (weights?.[k] ?? c.w), 0);
    let x = r() * total;
    for (const [k, c] of entries) { x -= weights?.[k] ?? c.w; if (x <= 0) return k; }
    return entries[0][0];
  };
  const tracking = (carrier) => `${CARRIERS[carrier]?.p ?? 'ML'}${String(ib(1e9, 9.99e9))}`;

  const records = [];
  const make = (o) => {
    const place = pick(PLACES);
    const brand = r() < 0.62 ? 'ridhi' : 'cpc';
    const items = Array.from({ length: ib(1, 3) }, () => { const [name, price] = pick(ITEMS[brand]); return { name, qty: ib(1, 2), price }; });
    const total = Math.round(items.reduce((s, i) => s + i.qty * i.price, 0) + between(0, 12));
    records.push({
      brand, tracking_number: '', carrier_name: '', order_created_at: null, fulfilled_at: null, expected_delivery_at: null, delivered_at: null,
      last_scan_at: null, last_scan_description: '', last_scan_location: '', normalized_tracking_status: '', exception: '', delay_reason: '',
      order_total: total, order_currency: 'USD', city: place[0], state: place[1], items, events: [], manual: null, _tag: '', ...o,
    });
    return records[records.length - 1];
  };
  /** Scan timeline between dispatch and the last scan; the last event carries the final wording. */
  const timeline = (rec, dispatchMs, lastMs, n, finalEvent, delivered) => {
    const ev = [{ at: iso(dispatchMs - H), status: 'label_created', description: 'Shipping label created', location: 'Origin facility' }];
    const steps = TEMPLATE.slice(0, Math.max(0, Math.min(n, TEMPLATE.length)));
    const span = Math.max(lastMs - (dispatchMs + 2 * H), H);
    steps.forEach(([status, description, loc], i) => {
      const t = dispatchMs + 2 * H + (span * (i + 1)) / (steps.length + (finalEvent || delivered ? 1 : 0));
      ev.push({ at: iso(Math.min(t, lastMs - 1)), status, description, location: loc ?? `${rec.city}, ${rec.state}` });
    });
    if (delivered) ev.push({ at: iso(rec.delivered_at ? ms(rec.delivered_at) : lastMs), status: 'delivered', description: 'Delivered - left at front door', location: `${rec.city}, ${rec.state}` });
    else if (finalEvent) ev.push({ at: iso(lastMs), status: finalEvent[0], description: finalEvent[1], location: finalEvent[2] ?? `${rec.city}, ${rec.state}` });
    rec.events = ev;
    const last = ev[ev.length - 1];
    rec.last_scan_at = last.at; rec.last_scan_description = last.description; rec.last_scan_location = last.location;
  };

  // A: delivered (110)
  for (let i = 0; i < 110; i += 1) {
    const carrier = carrierPick();
    const c = CARRIERS[carrier];
    const late = r() < (carrier === 'Economy Freight' ? 0.3 : carrier === 'Regional Post' ? 0.18 : 0.1);
    const transit = late ? c.sla + between(0.5, 3.5) : between(c.tr[0], Math.min(c.tr[1], c.sla));
    const deliveredMs = now - between(8, 90 * 24) * H;
    const dispatchMs = deliveredMs - transit * D;
    const rec = make({ carrier_name: carrier, tracking_number: tracking(carrier), order_created_at: iso(dispatchMs - between(10, 50) * H), fulfilled_at: iso(dispatchMs), expected_delivery_at: iso(dispatchMs + c.sla * D), delivered_at: iso(deliveredMs), normalized_tracking_status: 'delivered' });
    timeline(rec, dispatchMs, deliveredMs, ib(3, 6), null, true);
  }
  // B: in transit, on track (38)
  for (let i = 0; i < 56; i += 1) {
    const carrier = carrierPick();
    const dispatchAgo = between(5, 80);
    const lastAgo = between(2, Math.min(30, dispatchAgo - 2));
    const dispatchMs = now - dispatchAgo * H;
    const status = r() < 0.15 ? 'out_for_delivery' : 'in_transit';
    const rec = make({ carrier_name: carrier, tracking_number: tracking(carrier), order_created_at: iso(dispatchMs - between(10, 40) * H), fulfilled_at: iso(dispatchMs), expected_delivery_at: iso(dispatchMs + CARRIERS[carrier].sla * D), normalized_tracking_status: status, _tag: 'B' });
    timeline(rec, dispatchMs, now - lastAgo * H, status === 'out_for_delivery' ? 6 : ib(1, 4), null, false);
  }
  // J: cancelled / refunded orders that still have a parcel record (left out of the active figures)
  for (let i = 0; i < 5; i += 1) {
    const carrier = carrierPick();
    const dispatchMs = now - between(30, 70) * H;
    const rec = make({ carrier_name: carrier, tracking_number: tracking(carrier), order_created_at: iso(dispatchMs - 20 * H), fulfilled_at: iso(dispatchMs), expected_delivery_at: iso(dispatchMs + CARRIERS[carrier].sla * D), normalized_tracking_status: 'in_transit', _tag: i < 3 ? 'cancelled' : 'refunded' });
    timeline(rec, dispatchMs, dispatchMs + 12 * H, 2, null, false);
  }
  // D: delayed (26): 10 with no carrier scan for 5+ days
  for (let i = 0; i < 26; i += 1) {
    const carrier = carrierPick({ 'Standard Ground': 25, 'Express Air': 8, 'Regional Post': 30, 'Economy Freight': 40 });
    const stuck = i < 10;
    const dispatchAgo = stuck ? between(6.2, 10.5) : between(4, 8.2);
    const scanAgo = stuck ? between(5.2, dispatchAgo - 0.4) : between(0.5, 3.8);
    const dispatchMs = now - dispatchAgo * D;
    const rec = make({ carrier_name: carrier, tracking_number: tracking(carrier), order_created_at: iso(dispatchMs - between(10, 40) * H), fulfilled_at: iso(dispatchMs), expected_delivery_at: iso(dispatchMs + CARRIERS[carrier].sla * D), normalized_tracking_status: 'in_transit', delay_reason: pick(DELAY_REASONS), _tag: stuck ? 'stuck' : 'D' });
    timeline(rec, dispatchMs, now - scanAgo * D, ib(2, 4), null, false);
  }
  // E: carrier exceptions (10)
  const excKinds = ['failed_delivery', 'failed_delivery', 'failed_delivery', 'failed_delivery', 'returned', 'returned', 'returned', 'address_issue', 'address_issue', 'address_issue'];
  excKinds.forEach((kind) => {
    const carrier = carrierPick();
    const dispatchMs = now - between(3, 8.5) * D;
    const scanMs = now - between(0.5, 3) * D;
    const final = kind === 'returned' ? ['returned', 'Returned to sender'] : kind === 'failed_delivery' ? ['failed_delivery', 'Delivery attempt failed - recipient not available'] : ['in_transit', 'Address could not be verified - parcel on hold'];
    const rec = make({ carrier_name: carrier, tracking_number: tracking(carrier), order_created_at: iso(dispatchMs - between(10, 40) * H), fulfilled_at: iso(dispatchMs), expected_delivery_at: iso(dispatchMs + CARRIERS[carrier].sla * D), normalized_tracking_status: kind === 'address_issue' ? 'in_transit' : kind, exception: kind, delay_reason: kind === 'address_issue' ? 'Address verification pending' : kind === 'returned' ? 'Returned after failed attempts' : 'Recipient not available at delivery', _tag: 'E' });
    timeline(rec, dispatchMs, scanMs, ib(2, 4), final, false);
  });
  // F: carrier unconfirmed (14): 9 marketplace logistics, 5 unknown; the first 6 have no tracking number
  for (let i = 0; i < 14; i += 1) {
    const carrier = i < 9 ? 'Marketplace Logistics' : '';
    const dispatchMs = now - between(1, 14) * D;
    const rec = make({ carrier_name: carrier, tracking_number: i < 6 ? '' : `ML${ib(1e9, 9.99e9)}`, order_created_at: iso(dispatchMs - between(10, 40) * H), fulfilled_at: iso(dispatchMs), _tag: i < 6 ? 'F_missing' : 'F' });
    if (i >= 6) rec.normalized_tracking_status = '';
  }
  // G: dispatched, tracking given, carrier has not scanned anything yet (4)
  for (let i = 0; i < 4; i += 1) {
    const carrier = carrierPick();
    const dispatchMs = now - between(1, 5) * D;
    make({ carrier_name: carrier, tracking_number: tracking(carrier), order_created_at: iso(dispatchMs - between(10, 40) * H), fulfilled_at: iso(dispatchMs), expected_delivery_at: iso(dispatchMs + CARRIERS[carrier].sla * D), normalized_tracking_status: 'pending', _tag: 'G' });
  }
  // H: carrier scan says delivered but the status was never updated (4)
  for (let i = 0; i < 4; i += 1) {
    const carrier = carrierPick();
    const dispatchMs = now - between(3, 6) * D;
    const rec = make({ carrier_name: carrier, tracking_number: tracking(carrier), order_created_at: iso(dispatchMs - 20 * H), fulfilled_at: iso(dispatchMs), expected_delivery_at: iso(dispatchMs + CARRIERS[carrier].sla * D), normalized_tracking_status: 'in_transit', _tag: 'H' });
    timeline(rec, dispatchMs, now - between(0.4, 2.5) * D, 4, ['in_transit', 'Delivered - left with resident'], false);
  }
  // C: not dispatched yet (12): the first 7 say DONE in the order note but are not fulfilled
  const preAges = [5.5, 6.2, 7.6, 8.1, 10.4, 7.2, 5.9, 0.4, 0.9, 1.6, 2.4, 3.1];
  preAges.forEach((age, i) => {
    const carrier = carrierPick();
    make({ carrier_name: carrier, order_created_at: iso(now - age * D), _tag: i < 7 ? 'mcf' : 'C' });
  });

  // number the orders by creation date, then add duplicates and second parcels
  records.sort((a, b) => ms(a.order_created_at) - ms(b.order_created_at));
  records.forEach((rec, i) => { rec.order_number = `DEMO-#${10001 + i}`; });
  const pool = records.filter((x) => x._tag === 'B' || x._tag === 'D');
  for (let i = 0; i < 3; i += 1) pool[i * 2 + 1].tracking_number = pool[i * 2].tracking_number;     // duplicate tracking numbers
  const extras = [];
  pool.slice(8, 14).forEach((src) => {                                                              // second parcel on the same order
    const c = src.carrier_name;
    extras.push({ ...JSON.parse(JSON.stringify(src)), tracking_number: tracking(c), _tag: 'multi' });
  });
  records.push(...extras);
  // team marks on Marketplace / unknown carrier parcels
  const marks = ['delivered', 'delivered', 'lost', 'failed', 'in_transit'];
  records.filter((x) => x._tag === 'F').slice(0, 5).forEach((x, i) => { x.manual = { status: marks[i], at: iso(now - between(2, 60) * H) }; });
  records.forEach((x, i) => { x.id = i + 1; });

  // one check per order
  const byOrder = new Map();
  records.forEach((x) => { if (!byOrder.has(x.order_number)) byOrder.set(x.order_number, []); byOrder.get(x.order_number).push(x); });
  const checks = [];
  for (const [order, pk] of byOrder) {
    const first = pk[0];
    const fulfilled = pk.some((x) => x.fulfilled_at);
    const tag = first._tag;
    checks.push({
      order_number: order, brand: first.brand, order_created_at: first.order_created_at,
      fulfillment_status: fulfilled ? 'FULFILLED' : 'UNFULFILLED', financial_status: tag === 'refunded' ? 'REFUNDED' : 'PAID', cancelled: tag === 'cancelled',
      says_done: tag === 'mcf' ? true : tag === 'C' ? false : r() < 0.35, order_total: first.order_total, order_currency: 'USD',
    });
  }
  const annotations = {};
  const flagTargets = records.filter((x) => x._tag === 'stuck').slice(0, 2);
  flagTargets.forEach((x, i) => {
    annotations[x.order_number] = { reviewedAt: i === 0 ? iso(now - 5 * H) : null, reviewedBy: i === 0 ? 'Demo Admin' : null, flagged: true, flaggedAt: iso(now - 20 * H),
      notes: [{ at: iso(now - 20 * H), by: 'Demo Admin', text: i === 0 ? 'Carrier says the parcel is at the regional hub. Asked for an update.' : 'Customer asked about this order. Escalating to the carrier.' }] };
  });
  records.forEach((x) => { delete x._tag; });
  db.shipping = { shipments: records, checks, annotations };
}

/* ------------------------------------------------------------------ dataset (enrichment, as service.py) */
const isUnconfirmed = (c) => { const x = (c || '').trim().toLowerCase(); return x === '' || x.includes('amazon') || x === 'unknown' || x.includes('marketplace'); };
const missingTracking = (n) => n === '' || n.startsWith('EMPTY');

function flowCategory(created, dispatched, now, delivered) {
  if (delivered) return ['delivered', null, 'delivered'];
  const t = THRESH;
  if (dispatched === null) {
    const days = completeDays(created, now);
    if (days === null) return ['no_scan', null, 'pre_dispatch'];
    return [days >= t.red ? 'red' : days >= t.orange ? 'orange' : days >= t.yellow ? 'yellow' : days >= t.grey ? 'grey' : 'on_track', days, 'pre_dispatch'];
  }
  const days = completeDays(dispatched, now) || 0;
  return [days >= t.red ? 'red' : days >= t.orange ? 'orange' : days >= t.yellow ? 'yellow' : 'on_track', days, 'dispatched'];
}

function buildDataset(db, brand, now = Date.now()) {
  const inScope = (x) => !brand || x.brand === brand;
  const checks = db.shipping.checks.filter(inScope);
  const everything = db.shipping.shipments.filter(inScope).map((s) => {
    const created = ms(s.order_created_at); const fulfilled = ms(s.fulfilled_at); const lastScan = ms(s.last_scan_at);
    const delivered = s.normalized_tracking_status === 'delivered' || !!s.delivered_at;
    const [cat, days, stage] = flowCategory(created, fulfilled, now, delivered);
    const unconfirmed = isUnconfirmed(s.carrier_name);
    const scanAge = completeDays(lastScan, now);
    const exc = s.exception || (['failed_delivery', 'returned'].includes(s.normalized_tracking_status) ? s.normalized_tracking_status : '');
    const noMove = cat !== 'delivered' && !unconfirmed && lastScan !== null && (scanAge || 0) >= NO_MOVE_DAYS;
    let shown = cat !== 'delivered' && unconfirmed ? 'unconfirmed' : cat;
    let manual = null;
    if (s.manual && unconfirmed) { manual = s.manual; shown = { delivered: 'delivered', lost: 'lost', failed: 'failed' }[s.manual.status] ?? shown; }
    return { ...s, cat: shown, agingCat: cat, days, stage, scanAge, noMove, unconfirmed, exc, manual, key: `${s.order_number}|${s.tracking_number}|${s.id}`,
      missingTracking: missingTracking(s.tracking_number), created, fulfilled, lastScan, expected: ms(s.expected_delivery_at), deliveredAt: ms(s.delivered_at) };
  });
  const excluded = new Set(checks.filter((c) => c.cancelled || c.financial_status === 'REFUNDED').map((c) => c.order_number));
  const kept = everything.filter((x) => !excluded.has(x.order_number));
  // not dispatched yet: their own Unfulfilled tab, never Critical (same as board.build)
  const unfulfilled = kept.filter((x) => x.stage === 'pre_dispatch');
  const rows = kept.filter((x) => x.stage !== 'pre_dispatch');
  return { rows, unfulfilled, everything, checks, now, brand, annotations: db.shipping.annotations, active: rows.filter((x) => x.cat !== 'delivered') };
}

const brandOf = (query) => (query.brand && query.brand !== 'all' ? query.brand : undefined);
function ds(db, query) {
  const brand = brandOf(query);
  if (brand && !['ridhi', 'cpc'].includes(brand)) throw new DemoError(400, 'Unknown brand.');
  return buildDataset(db, brand);
}

function envelope(d, payload) {
  const asOf = iso(d.now);
  return {
    brand: d.brand ?? 'all', scope: d.brand ?? 'all',
    source: { state: 'ok', reason: '', asOf, parts: {}, demo: true, freshness: { state: 'fresh', message: '', lastChecked: asOf, runs: [] } },
    notConfigured: [], ...payload,
  };
}

/* ------------------------------------------------------------------ reports */
function valueAtRisk(d) {
  const orders = new Map();
  d.rows.forEach((x) => { if (x.cat === 'red' && x.order_total !== null && !orders.has(x.order_number)) orders.set(x.order_number, x.order_total); });
  if (!orders.size) return { available: true, orders: 0, total: null, currency: '' };
  return { available: true, orders: orders.size, total: Math.round([...orders.values()].reduce((s, v) => s + v, 0) * 100) / 100, currency: 'USD', note: '' };
}

function mcfReport(d) {
  const rows = [];
  d.checks.forEach((c) => {
    if (!c.says_done || c.cancelled || c.financial_status === 'REFUNDED' || c.fulfillment_status === 'FULFILLED') return;
    const age = completeDays(ms(c.order_created_at), d.now);
    const level = MCF_LEVELS.find(([days]) => age !== null && age >= days)?.[1];
    if (level) rows.push({ order: c.order_number, age, status: c.fulfillment_status || 'NOT FULFILLED', level });
  });
  rows.sort((a, b) => b.age - a.age);
  const counts = Object.fromEntries(MCF_LEVELS.map(([, lv]) => [lv, rows.filter((x) => x.level === lv).length]));
  return { available: true, rows, counts, rule: 'The order note says DONE but Shopify still shows the order as not fulfilled, 5+ days after the order (demo data).' };
}

const UNFULFILLED_BANDS = [['9+', '9+ days', 9], ['6-8', '6-8 days', 6], ['4-5', '4-5 days', 4], ['0-3', '0-3 days', 0]];
function unfulfilledReport(d) {
  const best = new Map();
  d.unfulfilled.forEach((x) => { const k = `${x.brand || ''}|${x.order_number}`; if (!best.has(k) || (x.days ?? 0) > (best.get(k).days ?? 0)) best.set(k, x); });
  const rows = [...best.values()].sort((a, b) => (b.days ?? 0) - (a.days ?? 0) || a.order_number.localeCompare(b.order_number)).map((x) => {
    const days = x.days ?? 0;
    return { order: x.order_number, key: x.key, brand: x.brand, shopifyUrl: '', placedAt: x.order_created_at, days: x.days,
      band: UNFULFILLED_BANDS.find(([, , low]) => days >= low)[0], agingCat: x.agingCat, withAmazon: false, amazon: null,
      noteDone: false, fulfillment: 'UNFULFILLED', total: x.order_total ?? null, currency: 'USD', flagged: !!d.annotations[x.order_number]?.flagged,
      action: 'Not sent yet. Send it (or fulfil it in Shopify with its tracking number).' };
  });
  return { total: rows.length, rows, counts: Object.fromEntries(UNFULFILLED_BANDS.map(([k]) => [k, rows.filter((r) => r.band === k).length])),
    bands: UNFULFILLED_BANDS.map(([key, label]) => ({ key, label })), withAmazon: 0,
    rule: 'Orders with no parcel sent yet. They are kept out of Critical and the shipment delay figures; days count from the order date (demo data).' };
}

function verifyReport(d) {
  const group = d.rows.filter((x) => x.unconfirmed);
  const st = (k) => group.filter((x) => (x.manual?.status ?? '') === k).length;
  return { total: group.length, missingTracking: group.filter((x) => x.missingTracking).length, team: { delivered: st('delivered'), lost: st('lost'), failed: st('failed'), inTransit: st('in_transit'), notChecked: st('') }, teamReason: '' };
}

const EXC_TYPES = {
  carrier_exception: { label: 'Carrier exception', severity: 'high' },
  stuck: { label: 'No movement', severity: 'high' },
  missing_tracking: { label: 'Dispatched without tracking number', severity: 'high' },
  overdue: { label: 'Past promised date', severity: 'medium' },
  delivered_not_marked: { label: 'Delivered but not marked', severity: 'medium' },
  duplicate_tracking: { label: 'Duplicate tracking number', severity: 'medium' },
};

function exceptionRows(d) {
  const out = [];
  const add = (x, type, detail) => out.push({ order: x.order_number, key: x.key, type, label: EXC_TYPES[type].label, severity: EXC_TYPES[type].severity, detail, carrier: x.carrier_name || 'Unknown', tracking: x.missingTracking ? '' : x.tracking_number, days: x.days, brand: x.brand });
  const dupCount = {};
  d.active.forEach((x) => { if (!x.missingTracking) dupCount[x.tracking_number] = (dupCount[x.tracking_number] || 0) + 1; });
  d.rows.forEach((x) => {
    if (x.exc) add(x, 'carrier_exception', `${x.exc.replace(/_/g, ' ')}${x.last_scan_description ? `: ${x.last_scan_description}` : ''}`);
    if (x.unconfirmed && x.missingTracking) add(x, 'missing_tracking', `Dispatched ${x.days ?? 0} days ago with no tracking number. Add it in the shop admin.`);
  });
  d.active.forEach((x) => {
    if (x.noMove) add(x, 'stuck', `No carrier scan for ${x.scanAge} days (last: ${x.last_scan_description || 'none'}).`);
    if (x.stage === 'dispatched' && !x.unconfirmed && x.expected && d.now - x.expected >= D && !x.noMove && !x.exc) add(x, 'overdue', `Promised ${new Date(x.expected).toISOString().slice(0, 10)}, now ${Math.floor((d.now - x.expected) / D)} day(s) late.`);
    if (/^delivered/i.test(x.last_scan_description)) add(x, 'delivered_not_marked', `Last scan says "${x.last_scan_description}" but the parcel is not marked delivered.`);
    if (!x.missingTracking && dupCount[x.tracking_number] > 1) add(x, 'duplicate_tracking', `Tracking number ${x.tracking_number} is used on ${dupCount[x.tracking_number]} parcels.`);
  });
  const sev = { high: 0, medium: 1 };
  out.sort((a, b) => sev[a.severity] - sev[b.severity] || (b.days ?? 0) - (a.days ?? 0) || a.order.localeCompare(b.order));
  return out;
}

// One row per order (same as board.exception_orders): its issues as tags, most severe first.
function exceptionOrders(issues) {
  const by = new Map();
  issues.forEach((x) => { const k = `${x.brand || ''}|${x.order}`; if (!by.has(k)) by.set(k, []); by.get(k).push(x); });
  const uniq = (a) => [...new Set(a)];
  return [...by.values()].map((xs) => {
    const seen = new Set();
    const tags = xs.filter((x) => { const k = `${x.type}|${x.detail}`; if (seen.has(k)) return false; seen.add(k); return true; });
    const days = tags.map((x) => x.days).filter((v) => v !== null && v !== undefined);
    return { ...tags[0], types: uniq(tags.map((x) => x.type)), carrier: uniq(tags.map((x) => x.carrier)).join(' / '),
      tracking: uniq(tags.map((x) => x.tracking).filter(Boolean)).join(', '), days: days.length ? Math.max(...days) : null,
      severity: tags.some((x) => x.severity === 'high') ? 'high' : tags[0].severity,
      issues: tags.map(({ type, label, severity, detail, carrier, tracking, key }) => ({ type, label, severity, detail, carrier, tracking, key })) };
  });
}

function carriersReport(d) {
  const by = new Map();
  d.rows.forEach((x) => {
    const name = x.carrier_name || 'Unknown';
    if (!by.has(name)) by.set(name, { n: 0, crit: 0, stuck: 0, exc: 0, days: [], cats: {} });
    const c = by.get(name);
    if (x.cat !== 'delivered') { c.n += 1; c.cats[x.cat] = (c.cats[x.cat] || 0) + 1; if (x.days !== null) c.days.push(x.days); if (x.noMove) c.stuck += 1; }
    if (x.cat === 'red') c.crit += 1;
    if (x.exc) c.exc += 1;
  });
  const scored = [...by.entries()].sort((a, b) => b[1].n - a[1].n).filter(([, c]) => c.n).map(([name, c]) => {
    const pct = Math.round((c.crit / c.n) * 100);
    return { carrier: name, active: c.n, critical: c.crit, criticalPct: pct, stuck: c.stuck, exceptions: c.exc,
      avgDays: c.days.length ? Math.round(c.days.reduce((s, v) => s + v, 0) / c.days.length) : null,
      health: pct > 50 ? 'bad' : pct > 20 ? 'warn' : 'ok', healthLabel: pct > 50 ? 'Needs action' : pct > 20 ? 'Watch' : 'Healthy',
      cats: Object.fromEntries(AGING_KEYS.map((k) => [k, c.cats[k] || 0])) };
  });
  return { scorecard: scored, heatmap: scored.slice(0, 8), categories: AGING_KEYS.map((k) => ({ key: k, label: AGING_LABELS[k] })) };
}

const weekStart = (t) => { const x = new Date(t); const dow = (x.getUTCDay() + 6) % 7; return new Date(Date.UTC(x.getUTCFullYear(), x.getUTCMonth(), x.getUTCDate() - dow)).toISOString().slice(0, 10); };

/** Delivery performance for delivered parcels in the last `period` days. */
function deliveryReport(d, period) {
  const since = d.now - period * D;
  const done = d.rows.filter((x) => x.deliveredAt && x.deliveredAt >= since && x.fulfilled);
  const days = (x) => (x.deliveredAt - x.fulfilled) / D;
  const onTime = (x) => x.expected === null || x.deliveredAt <= x.expected;
  const pct = (list) => (list.length ? Math.round((list.filter(onTime).length / list.length) * 100) : null);
  const avg = (list) => (list.length ? Math.round((list.reduce((s, x) => s + days(x), 0) / list.length) * 10) / 10 : null);
  const buckets = [['1-2 days', 0, 3], ['3-4 days', 3, 5], ['5-6 days', 5, 7], ['7-8 days', 7, 9], ['9+ days', 9, 1e9]];
  const group = (keyFn) => {
    const m = new Map();
    done.forEach((x) => { const k = keyFn(x); if (!m.has(k)) m.set(k, []); m.get(k).push(x); });
    return [...m.entries()].map(([k, list]) => ({ name: k, delivered: list.length, onTimePct: pct(list), avgDays: avg(list) })).sort((a, b) => b.delivered - a.delivered);
  };
  const weeks = new Map();
  done.forEach((x) => { const w = weekStart(x.deliveredAt); if (!weeks.has(w)) weeks.set(w, []); weeks.get(w).push(x); });
  return {
    period, delivered: done.length, onTimePct: pct(done), avgDays: avg(done),
    distribution: buckets.map(([label, lo, hi]) => ({ key: label, label, value: done.filter((x) => days(x) >= lo && days(x) < hi).length })),
    byCarrier: group((x) => x.carrier_name || 'Unknown').map((g) => ({ carrier: g.name, delivered: g.delivered, onTimePct: g.onTimePct, avgDays: g.avgDays })),
    byRegion: group((x) => x.state).slice(0, 8).map((g) => ({ region: g.name, delivered: g.delivered, onTimePct: g.onTimePct, avgDays: g.avgDays })),
    trend: [...weeks.entries()].sort((a, b) => (a[0] < b[0] ? -1 : 1)).map(([week, list]) => ({ week, onTimePct: pct(list), delivered: list.length })),
  };
}

function analytics(d, query) {
  const active = d.active;
  const crit = active.filter((x) => x.cat === 'red').length;
  const stuck = active.filter((x) => x.noMove).length;
  const dayList = active.filter((x) => x.days !== null).map((x) => x.days);
  const count = (k) => active.filter((x) => x.cat === k).length;
  const weeks = new Map();
  active.forEach((x) => { if (x.created) { const w = weekStart(x.created); weeks.set(w, (weeks.get(w) || 0) + 1); } });
  const weekRows = [...weeks.entries()].sort((a, b) => (a[0] < b[0] ? -1 : 1)).slice(-12);
  const cr = carriersReport(d);
  const car = cr.scorecard.slice(0, 8);
  const dispatch = {}; const dispatchCrit = {};
  active.forEach((x) => {
    const day = x.fulfilled ? WEEKDAYS[(new Date(x.fulfilled + 5.5 * H).getUTCDay() + 6) % 7] : 'No date';
    dispatch[day] = (dispatch[day] || 0) + 1;
    if (x.cat === 'red') dispatchCrit[day] = (dispatchCrit[day] || 0) + 1;
  });
  const dayLabels = [...WEEKDAYS.filter((w) => dispatch[w]), ...(dispatch['No date'] ? ['No date'] : [])];
  const exc = d.rows.filter((x) => x.exc).length;
  const tips = [];
  if (crit) tips.push(`${crit} active shipments are ${THRESH.red}+ days in stage. Escalate these first (filter: Critical).`);
  const worst = car.reduce((m, c) => (!m || c.critical > m.critical ? c : m), null);
  if (worst && worst.critical) tips.push(`${worst.carrier} has the most critical shipments (${worst.critical}). Check them with this carrier first.`);
  if (stuck) tips.push(`${stuck} shipments have had no carrier scan for ${NO_MOVE_DAYS}+ days. These may be stuck or lost.`);
  if (exc) tips.push(`${exc} carrier exception(s) need a decision (failed delivery or return).`);
  if (weekRows.length) { const top = weekRows.reduce((m, w) => (w[1] > m[1] ? w : m)); tips.push(`Most active shipments were created in the week of ${top[0]} (${top[1]}). Check why intake spiked.`); }
  const period = query.period === '90' ? 90 : 30;
  return {
    kpis: { active: active.length, critical: crit, criticalPct: active.length ? Math.round((crit / active.length) * 100) : 0, onTrackPct: active.length ? Math.round((count('on_track') / active.length) * 100) : 0,
      avgDays: dayList.length ? Math.round(dayList.reduce((s, v) => s + v, 0) / dayList.length) : null, stuck, carriersInUse: new Set(active.map((x) => x.carrier_name || 'Unknown')).size, valueAtRisk: valueAtRisk(d) },
    aging: AGING_KEYS.map((k) => ({ key: k, label: AGING_LABELS[k], value: count(k) })),
    weeks: weekRows.map(([week, value]) => ({ week, value })),
    carriers: car.map((c) => ({ carrier: c.carrier, critical: c.critical, other: c.active - c.critical })),
    stage: [
      { label: 'Not dispatched (Unfulfilled tab)', value: unfulfilledReport(d).total },
      { label: 'Dispatched (active)', value: d.rows.filter((x) => x.stage === 'dispatched' && x.cat !== 'delivered').length },
      { label: 'Delivered', value: d.rows.filter((x) => x.cat === 'delivered').length },
    ],
    dispatchDay: dayLabels.map((day) => ({ day, critical: dispatchCrit[day] || 0, other: dispatch[day] - (dispatchCrit[day] || 0) })),
    insights: tips,
    carriersReport: cr,
    delivery: deliveryReport(d, period),
  };
}

/* ------------------------------------------------------------------ list, detail */
const cmp = (a, b) => { for (let i = 0; i < a.length; i += 1) if (a[i] !== b[i]) return a[i] < b[i] ? -1 : 1; return 0; };
const orderDigits = (n) => Number(n.replace(/\D/g, '')) || 0;
const SORT_KEYS = {
  priority: (x) => [x.exc ? 0 : 1, x.noMove ? 0 : 1, RANK[x.cat] ?? 9, -(x.days || 0)],
  stuck: (x) => [x.noMove ? 0 : 1, -(x.scanAge || 0)],
  order: (x) => [orderDigits(x.order_number), x.order_number],
  oldest: (x) => [-(x.days ?? -1)],
};

function selectRows(d, f) {
  const needle = (f.q || '').trim().toLowerCase();
  const orderDays = Number(f.days) || 0;
  const cutoff = orderDays ? d.now - orderDays * D : 0;
  const out = d.rows.filter((x) => {
    if (cutoff && (!x.created || x.created < cutoff)) return false;
    if (x.cat === 'delivered') return false;
    if (f.cat === 'nomove') { if (!x.noMove) return false; }
    else if (f.cat === 'noscan') { if (x.lastScan) return false; }
    else if (f.cat === 'exception') { if (!x.exc) return false; }
    else if (f.cat === 'flagged') { if (!d.annotations[x.order_number]?.flagged) return false; }
    else if (f.cat && x.cat !== f.cat) return false;
    if (f.carrier && x.carrier_name !== f.carrier) return false;
    if (f.status && x.normalized_tracking_status !== f.status) return false;
    if (needle && !x.order_number.toLowerCase().includes(needle) && !x.tracking_number.toLowerCase().includes(needle)) return false;
    return true;
  });
  const key = SORT_KEYS[f.sort] || SORT_KEYS.priority;
  return out.sort((a, b) => cmp(key(a), key(b)));
}

function publicRow(x, d, packages) {
  return {
    key: x.key, order: x.order_number, tracking: x.tracking_number, carrier: x.carrier_name, cat: x.cat, agingCat: x.agingCat, label: LABELS[x.cat] ?? x.cat,
    days: x.days, stage: x.stage, exception: x.exc, noMove: x.noMove, scanAge: x.scanAge, status: x.normalized_tracking_status, orderCreatedAt: x.order_created_at,
    dispatchedAt: x.fulfilled_at, lastScanAt: x.last_scan_at, lastScan: x.last_scan_description, expectedAt: x.expected_delivery_at, trackUrl: '', shopifyUrl: '',
    manual: x.manual, packages: packages[x.order_number] ?? 1, missingTracking: x.missingTracking, unconfirmed: x.unconfirmed,
    flagged: !!d.annotations[x.order_number]?.flagged, brand: x.brand, city: x.city, state: x.state, delayReason: x.delay_reason,
  };
}

function packageCounts(d) {
  const p = {};
  d.rows.forEach((x) => { p[x.order_number] = (p[x.order_number] || 0) + 1; });
  return p;
}

function listRows(d, query) {
  const f = { q: (query.q || '').slice(0, 100), carrier: query.carrier || '', cat: query.cat || '', status: query.status || '', days: query.days || '', sort: query.sort || 'priority' };
  const out = selectRows(d, f);
  const size = Math.max(1, Math.min(Number(query.size) || 25, 200));
  const pages = Math.max(1, Math.ceil(out.length / size));
  const page = Math.max(0, Math.min(Number(query.page) || 0, pages - 1));
  const pk = packageCounts(d);
  return envelope(d, {
    total: out.length, page, size, pages, rows: out.slice(page * size, (page + 1) * size).map((x) => publicRow(x, d, pk)),
    facets: {
      carriers: [...new Set(d.rows.map((x) => x.carrier_name).filter(Boolean))].sort(),
      statuses: [...new Set(d.rows.map((x) => x.normalized_tracking_status).filter(Boolean))].sort(),
    },
  });
}

function annotationOf(d, order) {
  const a = d.annotations[order];
  return { reviewedAt: a?.reviewedAt ?? null, reviewedBy: a?.reviewedBy ?? null, flagged: !!a?.flagged, flaggedAt: a?.flaggedAt ?? null, notes: a?.notes ?? [] };
}

function orderDetail(d, order) {
  const pkgs = d.everything.filter((x) => x.order_number === order);
  if (!pkgs.length) throw new DemoError(404, 'No shipment found for that order.');
  const check = d.checks.find((c) => c.order_number === order) ?? null;
  const excluded = check && (check.cancelled || check.financial_status === 'REFUNDED') ? (check.cancelled ? 'cancelled' : 'refunded') : null;
  const counts = { [order]: pkgs.length };
  return {
    order, excluded, brand: pkgs[0].brand, destination: { city: pkgs[0].city, state: pkgs[0].state }, items: pkgs[0].items,
    packages: pkgs.map((x) => ({
      ...publicRow(x, d, counts),
      action: x.cat !== 'delivered' ? (x.exc ? `Carrier exception (${x.exc}): review the reason and decide the next step.` : x.unconfirmed ? (x.missingTracking ? 'Add the tracking number in the shop admin, then check the parcel by hand.' : 'Check the parcel by hand on the carrier page.') : ACTIONS[x.agingCat] ?? 'Review manually.') : ACTIONS.delivered,
      location: x.last_scan_location, source: 'demo', checkedAt: iso(d.now - 3 * H), scanDescription: x.last_scan_description, events: x.events, city: x.city, state: x.state,
      delayReason: x.delay_reason, promisedAt: x.expected_delivery_at, deliveredAt: x.delivered_at,
    })),
    check: check && { fulfillment: check.fulfillment_status, financial: check.financial_status, cancelled: check.cancelled, notesSayDone: check.says_done, createdAt: check.order_created_at, total: check.order_total, currency: check.order_currency },
    checkAvailable: true,
    annotation: annotationOf(d, order),
  };
}

function annotate({ params, query, body, db }) {
  const d = ds(db, query);
  const order = params.order;
  if (!d.everything.some((x) => x.order_number === order)) throw new DemoError(404, 'No shipment found for that order.');
  const store = db.shipping.annotations;
  const a = store[order] ?? (store[order] = { reviewedAt: null, reviewedBy: null, flagged: false, flaggedAt: null, notes: [] });
  const at = new Date().toISOString();
  const action = body.action;
  if (action === 'check') { a.reviewedAt = at; a.reviewedBy = 'Demo Admin'; }
  else if (action === 'uncheck') { a.reviewedAt = null; a.reviewedBy = null; }
  else if (action === 'flag') { a.flagged = true; a.flaggedAt = at; }
  else if (action === 'unflag') { a.flagged = false; a.flaggedAt = null; }
  else if (action === 'note') {
    const text = String(body.text ?? '').trim();
    if (!text) throw new DemoError(400, 'Write a note first.');
    a.notes = [{ at, by: 'Demo Admin', text: text.slice(0, 500) }, ...a.notes];
  } else throw new DemoError(400, 'Unknown action.');
  return orderDetail(buildDataset(db, brandOf(query)), order);
}

/* ------------------------------------------------------------------ import preview (as reports.preview_import) */
function parseCsv(text) {
  const rows = []; let row = []; let cur = ''; let q = false;
  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i];
    if (q) { if (ch === '"') { if (text[i + 1] === '"') { cur += '"'; i += 1; } else q = false; } else cur += ch; }
    else if (ch === '"') q = true;
    else if (ch === ',') { row.push(cur); cur = ''; }
    else if (ch === '\n' || ch === '\r') { if (ch === '\r' && text[i + 1] === '\n') i += 1; row.push(cur); rows.push(row); row = []; cur = ''; }
    else cur += ch;
  }
  row.push(cur); rows.push(row);
  return rows.filter((r) => r.some((c) => c.trim()));
}

function previewImport(d, text) {
  if (typeof text !== 'string') throw new DemoError(400, 'Send the sheet as text.');
  if (text.length > 512000) throw new DemoError(413, 'That sheet is too large to preview.');
  const parsed = parseCsv(text);
  if (!parsed.length) throw new DemoError(400, 'The sheet is empty.');
  const header = parsed[0].map((h) => h.trim().toLowerCase().replace(/ /g, '_'));
  const [io, it, ic] = ['order_number', 'tracking_number', 'carrier'].map((k) => header.indexOf(k));
  if (io < 0 || it < 0 || ic < 0) throw new DemoError(400, 'The first row must have: order_number, tracking_number, carrier.');
  const body = parsed.slice(1);
  if (body.length > 1000) throw new DemoError(400, 'At most 1000 rows can be previewed at once.');
  const cell = (row, i) => (i < row.length ? row[i].trim() : '');
  const sheet = body.map((rw, n) => ({ line: n + 2, order: cell(rw, io), tracking: cell(rw, it), carrier: cell(rw, ic) }));
  const byOrder = new Map();
  [...d.rows, ...d.unfulfilled].forEach((x) => { if (!byOrder.has(x.order_number)) byOrder.set(x.order_number, []); byOrder.get(x.order_number).push(x); });
  const dup = {};
  sheet.forEach((s) => { if (s.order) dup[`${s.order}|${s.tracking}`] = (dup[`${s.order}|${s.tracking}`] || 0) + 1; });
  const allowed = Object.fromEntries(IMPORT_CARRIERS.map((c) => [c.toLowerCase(), c]));
  const check = (s) => {
    if (!s.order) return ['error', 'Order number is missing.'];
    if (dup[`${s.order}|${s.tracking}`] > 1) return ['error', 'Duplicate row in this sheet.'];
    if (!s.tracking) return ['error', 'Tracking number is missing.'];
    if (!/^[A-Za-z0-9][A-Za-z0-9-]{5,39}$/.test(s.tracking)) return ['error', 'Tracking number looks wrong (letters, digits and dashes, 6 to 40 characters).'];
    if (!allowed[s.carrier.toLowerCase()]) return ['error', `Carrier must be one of: ${IMPORT_CARRIERS.join(', ')}.`];
    const pk = byOrder.get(s.order);
    if (!pk) return ['error', 'Order not found among active packages.'];
    const blank = pk.filter((p) => missingTracking(p.tracking_number));
    if (!blank.length) return ['skip_has_tracking', 'Every package of this order already has a tracking number.'];
    if (blank.length > 1) return ['ambiguous', `${blank.length} packages of this order have no tracking number. Choose one.`];
    return ['will_update', 'Would update one package with this tracking number (preview only).'];
  };
  const out = sheet.map((s) => { const [outcome, message] = check(s); return { ...s, carrier: allowed[s.carrier.toLowerCase()] ?? s.carrier, outcome, message }; });
  const counts = Object.fromEntries(['will_update', 'skip_has_tracking', 'ambiguous', 'error'].map((k) => [k, out.filter((o) => o.outcome === k).length]));
  return envelope(d, { previewOnly: true, rows: out, counts, note: 'Preview only (demo). Nothing was changed anywhere.' });
}

/* ------------------------------------------------------------------ Home overview for the lead's Home page */
export function shippingHomeSummary(db, brandId) {
  const d = buildDataset(db, brandId || undefined);
  const active = d.active;
  const delivery = deliveryReport(d, 30);
  const delayed = active.filter((x) => ['yellow', 'orange', 'red'].includes(x.cat) || x.noMove);
  const top = [...delayed].sort((a, b) => cmp(SORT_KEYS.priority(a), SORT_KEYS.priority(b))).slice(0, 4);
  return {
    total: d.rows.length,
    inTransit: active.filter((x) => x.stage === 'dispatched' && ['in_transit', 'out_for_delivery'].includes(x.normalized_tracking_status)).length,
    delayed: delayed.length,
    red: active.filter((x) => x.cat === 'red').length,
    delivered: d.rows.filter((x) => x.cat === 'delivered').length,
    onTimePct: delivery.onTimePct,
    asOf: iso(d.now),
    topDelayed: top.map((x) => ({
      order: x.order_number, brand: x.brand, carrier: x.carrier_name || 'Unknown',
      daysLate: x.expected && d.now > x.expected ? Math.floor((d.now - x.expected) / D) : (x.days ?? 0), customerCity: `${x.city}, ${x.state}`,
    })),
  };
}

/* ------------------------------------------------------------------ routes */
const fileStamp = () => new Date().toISOString().slice(0, 10);
const csvRows = (list) => list;

export const routes = [
  ['GET', '/shipping/summary', ({ query, db }) => {
    const d = ds(db, query);
    const counts = {};
    d.active.forEach((x) => { counts[x.cat] = (counts[x.cat] || 0) + 1; });
    const values = { '': d.active.length, exception: d.rows.filter((x) => x.exc).length, nomove: d.rows.filter((x) => x.noMove).length };
    const KPI = [['', 'Total active shipments', 'neutral'], ['on_track', 'On track (0-3 days)', 'good'], ['grey', 'Grey 2-3 days', 'muted'], ['yellow', 'Yellow 4-5 days', 'warn'], ['orange', 'Orange 6-8 days', 'orange'],
      ['red', 'Red 9+ days', 'bad'], ['unconfirmed', 'Carrier unconfirmed (Amazon/Unknown)', 'info'], ['exception', 'Carrier exceptions', 'bad'], ['nomove', `No movement (${NO_MOVE_DAYS}+ days)`, 'orange'],
      ['unfulfilled', 'Unfulfilled orders (not sent yet)', 'warn']];
    values.unfulfilled = unfulfilledReport(d).total;
    const critical = counts.red || 0;
    const mcf = mcfReport(d);
    const verify = verifyReport(d);
    return envelope(d, {
      kpis: KPI.map(([key, label, tone]) => ({ key, label: key === 'unconfirmed' ? 'Carrier unconfirmed (marketplace / unknown)' : label, value: key in values ? values[key] : counts[key] || 0, tone })),
      activeTotal: d.active.length, critical, delivered: d.rows.filter((x) => x.cat === 'delivered').length,
      unfulfilled: unfulfilledReport(d).total,
      stage: { preDispatch: unfulfilledReport(d).total, dispatched: d.rows.filter((x) => x.stage === 'dispatched' && x.cat !== 'delivered').length, delivered: d.rows.filter((x) => x.cat === 'delivered').length },
      banner: critical ? `CRITICAL: ${critical} shipment(s) are ${THRESH.red}+ days in stage. Escalate today.` : '',
      valueAtRisk: valueAtRisk(d), checks: { mcf: mcf.counts, toVerify: verify.total, missingTracking: verify.missingTracking },
      thresholds: { ...THRESH, noMove: NO_MOVE_DAYS }, totals: { shipments: d.everything.length, afterExclusions: d.rows.length },
      exceptions: exceptionOrders(exceptionRows(d)).length,
    });
  }],
  ['GET', '/shipping/shipments', ({ query, db }) => listRows(ds(db, query), query)],
  ['GET', '/shipping/unfulfilled', ({ query, db }) => { const d = ds(db, query); return envelope(d, unfulfilledReport(d)); }],
  ['GET', '/shipping/shipments/:order', ({ params, query, db }) => { const d = ds(db, query); return envelope(d, orderDetail(d, params.order)); }],
  ['POST', '/shipping/shipments/:order/note', (ctx) => envelope(ds(ctx.db, ctx.query), annotate(ctx))],
  ['GET', '/shipping/analytics', ({ query, db }) => { const d = ds(db, query); return envelope(d, analytics(d, query)); }],
  ['GET', '/shipping/checks', ({ query, db }) => {
    const d = ds(db, query);
    const mcf = mcfReport(d);
    const verify = verifyReport(d);
    const issues = exceptionRows(d);
    const rows = exceptionOrders(issues);
    const counts = Object.fromEntries(Object.keys(EXC_TYPES).map((k) => [k, rows.filter((x) => x.types.includes(k)).length]));
    return envelope(d, { mcf, verify, counts: { mcf: mcf.counts, toVerify: verify.total, missingTracking: verify.missingTracking }, exceptions: { total: rows.length, issues: issues.length, counts, types: Object.entries(EXC_TYPES).map(([key, v]) => ({ key, ...v })), rows } });
  }],
  ['POST', '/shipping/import/preview', ({ query, body, db }) => previewImport(ds(db, query), body.text)],
  ['GET', '/shipping/import/sample', ({ query, db }) => {
    const d = ds(db, query);
    const blank = [...d.rows, ...d.unfulfilled].filter((x) => x.cat !== 'delivered' && x.missingTracking && !x.unconfirmed).slice(0, 3);
    const has = d.rows.find((x) => !x.missingTracking && x.cat !== 'delivered');
    const lines = ['order_number,tracking_number,carrier', ...blank.map((x, i) => `${x.order_number},SG${7000000100 + i * 37},Standard Ground`)];
    if (has) lines.push(`${has.order_number},EA7000000555,Express Air`);
    if (blank[0]) lines.push(`${blank[0].order_number},SG7000000100,Standard Ground`);
    lines.push('DEMO-#99999,SG7000000999,Standard Ground', `${blank[1]?.order_number ?? 'DEMO-#10001'},12,Express Air`, `${blank[2]?.order_number ?? 'DEMO-#10002'},EA7000000777,Unknown Courier`);
    return { text: lines.join('\n') };
  }],
  ['GET', '/shipping/export/shipments', ({ query, db }) => {
    const d = ds(db, query);
    const rows = selectRows(d, { q: query.q, carrier: query.carrier, cat: query.cat, status: query.status, days: query.days, sort: query.sort || 'priority' });
    return csvDownload(`shipments-${fileStamp()}.csv`,
      ['order_number', 'carrier_name', 'tracking_number', 'category', 'days_in_stage', 'stage', 'exception', 'no_movement', 'tracking_status', 'order_created_at', 'dispatched_at', 'last_scan_at', 'last_scan', 'expected_delivery_at'],
      csvRows(rows.map((x) => [x.order_number, x.carrier_name, x.tracking_number, x.cat, x.days, x.stage, x.exc, x.noMove ? 'yes' : '', x.normalized_tracking_status, x.order_created_at, x.fulfilled_at, x.last_scan_at, x.last_scan_description, x.expected_delivery_at])));
  }],
  ['GET', '/shipping/export/escalation', ({ query, db }) => {
    const d = ds(db, query);
    const flagged = (x) => d.annotations[x.order_number]?.flagged;
    const rows = d.rows.filter((x) => x.cat === 'red' || x.noMove || flagged(x)).sort((a, b) => (b.days || 0) - (a.days || 0));
    return csvDownload(`escalation-list-${fileStamp()}.csv`, ['order_number', 'carrier_name', 'tracking_number', 'days_in_stage', 'stage', 'reason', 'last_scan_at', 'last_scan_description'],
      rows.map((x) => [x.order_number, x.carrier_name, x.tracking_number, x.days, x.stage, x.cat === 'red' && x.noMove ? 'critical + stuck' : x.cat === 'red' ? 'critical' : x.noMove ? 'stuck' : 'flagged by team', x.last_scan_at, x.last_scan_description]));
  }],
  ['GET', '/shipping/export/verify', ({ query, db }) => {
    const d = ds(db, query);
    const rows = d.rows.filter((x) => x.cat === 'unconfirmed').sort((a, b) => Number(b.missingTracking) - Number(a.missingTracking) || (b.days || 0) - (a.days || 0));
    return csvDownload(`parcels-to-verify-${fileStamp()}.csv`, ['action', 'order_number', 'carrier_name', 'tracking_number', 'dispatched', 'days_in_stage', 'last_scan_at', 'team_status'],
      rows.map((x) => [x.missingTracking ? 'ADD TRACKING NUMBER IN SHOP ADMIN' : 'Check carrier page', x.order_number, x.carrier_name || 'Unknown', x.missingTracking ? '' : x.tracking_number, x.fulfilled_at, x.days, x.last_scan_at, x.manual?.status ?? 'not checked']));
  }],
];
