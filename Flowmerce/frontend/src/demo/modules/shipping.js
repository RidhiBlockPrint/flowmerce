/**
 * Demo module: Shipping. Everything here is synthetic (fake order numbers, fictional carriers, no customer data).
 *
 * Collection `db.shipping`:
 *   shipments: one record per DISPATCHED parcel (an order can have several), as the real board (ops.flow_board) holds it:
 *     { id, brand: 'ridhi'|'cpc', order_number: 'DEMO-#10001', row_kind: 'shipment'|'amazon' ('amazon' = Amazon (MCF)
 *       shipped it and Shopify does not list it), tracking_number ('' = missing), carrier_name ('' = unknown),
 *       order_created_at, fulfilled_at (dispatch), expected_delivery_at (promised date), delivered_at,
 *       last_scan_at, last_scan_description, last_scan_location, normalized_tracking_status
 *       ('', pending, in_transit, out_for_delivery, delivered, failed_delivery, returned), exception (display only:
 *       failed_delivery, returned, address_issue), delay_reason, order_total, order_currency, city, state,
 *       items: [{name, qty, price}], events: [{at, status, description, location}],
 *       manual: null | {status: delivered|lost|failed|in_transit, at}, amazon_status, amazon_at, amazon_ref,
 *       amazon_extra (the Shopify order's own numbers, on an Amazon parcel the order does not list),
 *       reshipped: null | {how, detail, newOrder, newTracking, newCarrier, newStatus, newAt} }
 *   checks: one per order: { order_number, brand, order_created_at, fulfillment_status, financial_status, cancelled,
 *       says_done, order_total, order_currency }
 *   annotations: { [order_number]: { reviewedAt, reviewedBy, flagged, flaggedAt, notes: [{at, by, text}],
 *       outcome, outcomeAt, outcomeBy } }   (the team's actions in the order drawer)
 * Timestamps are ISO strings generated relative to the first load, and ages are recomputed from "now" on every request,
 * so the sections always make sense. The rules are the real ones (src/flowmerce/modules/shipping/board.py):
 *   - only dispatched parcels; delivered by ANY evidence leaves every list;
 *   - the clock is days since the last carrier scan (since dispatch while there is none);
 *   - every active order is in ONE section, first wins: tracking missing > invalid > fix in Shopify > red > orange >
 *     yellow > on track; reshipped and resolved parcels are kept apart.
 */
import { DemoError, csvDownload, rng } from '../util.js';

const H = 3600 * 1000;
const D = 24 * H;
const THRESH = { yellow: 4, orange: 6, red: 9 };
const NO_SCAN_GRACE_DAYS = 3;           // a carrier's first scan normally shows within 1-2 days of dispatch
const DELIVERED_KEEP_DAYS = 100;
const SECTIONS = ['tracking_missing', 'invalid', 'checks', 'red', 'orange', 'yellow', 'on_track'];
const RANK = Object.fromEntries(SECTIONS.map((k, i) => [k, i]));
const LABELS = { on_track: 'On track 0-3 days', yellow: 'Yellow 4-5 days', orange: 'Orange 6-8 days', red: 'Critical 9+ days',
  tracking_missing: 'Tracking missing', invalid: 'Invalid tracking', checks: 'Fix in Shopify', delivered: 'Delivered' };
const ACTIONS = { on_track: 'Continue monitoring.', yellow: 'Review if the carrier or the promised delivery date shows a problem.',
  orange: 'Prioritise for investigation.', red: 'Add to the urgent escalation list.', tracking_missing: 'Add the tracking number in Shopify.',
  invalid: 'The carrier has never reported anything on this number: check it on the carrier page, correct it in Shopify if it is wrong, then record a team mark.',
  delivered: 'None. Delivered.' };
const AGING_KEYS = SECTIONS;            // the age charts list every active section, so their bars add up to the active total
const AGING_LABELS = { red: 'Critical 9+', orange: 'Orange 6-8', yellow: 'Yellow 4-5', on_track: 'On track',
  tracking_missing: 'Tracking missing', invalid: 'Invalid tracking', checks: 'Fix in Shopify' };
const HAND_CHECKS = ['tracking_missing', 'invalid', 'checks'];
const TEAM_STATES = ['delivered', 'lost', 'failed', 'in_transit'];
const OUTCOMES = { delivered: 'Delivered', lost: 'Lost', returned: 'Returned', refunded: 'Refunded', failed: "Couldn't deliver" };
const TEAM_OUTCOMES = ['delivered', 'lost', 'returned', 'refunded'];
const LOST_RE = /\bdispos(?:e|al|ed)\b|\bdestroy(?:ed)?\b|\blost\b/i;
const RETURN_RE = /return(?:ed|ing)?\s+to\s+(?:the\s+)?(?:sender|shipper|seller|origin|amazon)|\brts\b/i;
const DELIVERED_SCAN = /^\s*delivered/i;
const AMAZON_DELIVERED = /\bdelivered\b/i;
const AMAZON_NOT_DELIVERED = /\b(not|un)\s*deliver|undeliverable|out for delivery|attempt/i;
const EXC_TYPES = {
  missing_tracking: { label: 'Tracking missing', severity: 'high', section: 'tracking_missing' },
  invalid_tracking: { label: 'Invalid tracking', severity: 'high', section: 'invalid' },
  amazon_not_in_shopify: { label: 'Shipped by Amazon, unfulfilled in Shopify', severity: 'medium', section: 'checks' },
  amazon_tracking_missing: { label: 'Amazon parcel not on the Shopify order', severity: 'medium', section: 'checks' },
  duplicate_tracking: { label: 'Duplicate tracking number', severity: 'medium', section: 'checks' },
};
const RESHIP_HOW = { replacement_order: 'Replacement order', sent_again: 'Same items sent again', note_says_reshipped: 'Note says reshipped',
  second_amazon_order: 'Second Amazon order', delivered_by_other_carrier: 'Delivered by another carrier', delivered_by_later_parcel: 'Delivered by a later parcel' };
const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const HOME_TOP = 4;

const iso = (ms) => (ms === null || ms === undefined ? null : new Date(ms).toISOString());
const ms = (s) => (s ? Date.parse(s) : null);
const completeDays = (since, now) => (since === null || since === undefined ? null : Math.max(0, Math.floor((now - since) / D)));
const day = (t) => new Date(t).toISOString().slice(0, 10);

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
      brand, row_kind: 'shipment', tracking_number: '', carrier_name: '', order_created_at: null, fulfilled_at: null, expected_delivery_at: null, delivered_at: null,
      last_scan_at: null, last_scan_description: '', last_scan_location: '', normalized_tracking_status: '', exception: '', delay_reason: '',
      order_total: total, order_currency: 'USD', city: place[0], state: place[1], items, events: [], manual: null,
      amazon_status: null, amazon_at: null, amazon_ref: null, amazon_extra: null, reshipped: null, _tag: '', ...o,
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
  const sent = (carrier, dispatchMs, o = {}) => make({ carrier_name: carrier, tracking_number: tracking(carrier), order_created_at: iso(dispatchMs - between(10, 40) * H),
    fulfilled_at: iso(dispatchMs), expected_delivery_at: iso(dispatchMs + (CARRIERS[carrier]?.sla ?? 6) * D), ...o });

  // A: delivered (110): only the delivery figures count them
  for (let i = 0; i < 110; i += 1) {
    const carrier = carrierPick();
    const c = CARRIERS[carrier];
    const late = r() < (carrier === 'Economy Freight' ? 0.3 : carrier === 'Regional Post' ? 0.18 : 0.1);
    const transit = late ? c.sla + between(0.5, 3.5) : between(c.tr[0], Math.min(c.tr[1], c.sla));
    const deliveredMs = now - between(8, 90 * 24) * H;
    const dispatchMs = deliveredMs - transit * D;
    const rec = sent(carrier, dispatchMs, { delivered_at: iso(deliveredMs), normalized_tracking_status: 'delivered' });
    timeline(rec, dispatchMs, deliveredMs, ib(3, 6), null, true);
  }
  // B: moving, last scan within a day or so: On track (56)
  for (let i = 0; i < 56; i += 1) {
    const carrier = carrierPick();
    const dispatchAgo = between(5, 80);
    const lastAgo = between(2, Math.min(30, dispatchAgo - 2));
    const dispatchMs = now - dispatchAgo * H;
    const status = r() < 0.15 ? 'out_for_delivery' : 'in_transit';
    const rec = sent(carrier, dispatchMs, { normalized_tracking_status: status, _tag: 'B' });
    timeline(rec, dispatchMs, now - lastAgo * H, status === 'out_for_delivery' ? 6 : ib(1, 4), null, false);
  }
  // J: cancelled / refunded orders that still have a parcel record (left out of every figure)
  for (let i = 0; i < 5; i += 1) {
    const carrier = carrierPick();
    const dispatchMs = now - between(30, 70) * H;
    const rec = sent(carrier, dispatchMs, { order_created_at: iso(dispatchMs - 20 * H), normalized_tracking_status: 'in_transit', _tag: i < 3 ? 'cancelled' : 'refunded' });
    timeline(rec, dispatchMs, dispatchMs + 12 * H, 2, null, false);
  }
  // D: no carrier scan for a while (26): the clock runs from the last scan, so these are Yellow (8), Orange (8), Critical (10)
  for (let i = 0; i < 26; i += 1) {
    const carrier = carrierPick({ 'Standard Ground': 25, 'Express Air': 8, 'Regional Post': 30, 'Economy Freight': 40 });
    const tag = i < 8 ? 'yellow' : i < 16 ? 'orange' : 'red';
    const scanAgo = tag === 'yellow' ? between(4.1, 5.8) : tag === 'orange' ? between(6.1, 8.8) : between(9.1, 14);
    const dispatchMs = now - (scanAgo + between(0.5, 3)) * D;
    const rec = sent(carrier, dispatchMs, { normalized_tracking_status: 'in_transit', delay_reason: pick(DELAY_REASONS), _tag: tag });
    timeline(rec, dispatchMs, now - scanAgo * D, ib(2, 4), null, false);
  }
  // E: the carrier reported a problem (11). Failed attempts and address holds stay active (the word is shown on the row);
  //    "returned to sender" and "lost" are the carrier's own outcome, so they move to Resolved.
  const excKinds = ['failed_delivery', 'failed_delivery', 'failed_delivery', 'failed_delivery', 'returned', 'returned', 'returned', 'address_issue', 'address_issue', 'address_issue', 'lost'];
  excKinds.forEach((kind) => {
    const carrier = carrierPick();
    const dispatchMs = now - between(3, 8.5) * D;
    const scanMs = now - between(0.5, 3) * D;
    const final = { returned: ['returned', 'Returned to sender'], failed_delivery: ['failed_delivery', 'Delivery attempt failed - recipient not available'],
      address_issue: ['in_transit', 'Address could not be verified - parcel on hold'], lost: ['in_transit', 'Package lost in transit - claim opened'] }[kind];
    const rec = sent(carrier, dispatchMs, { normalized_tracking_status: kind === 'address_issue' || kind === 'lost' ? 'in_transit' : kind, exception: kind === 'lost' ? '' : kind,
      delay_reason: { address_issue: 'Address verification pending', returned: 'Returned after failed attempts', failed_delivery: 'Recipient not available at delivery', lost: '' }[kind], _tag: 'E' });
    timeline(rec, dispatchMs, scanMs, ib(2, 4), final, false);
  });
  // F: no carrier data (14): the first 6 were dispatched without a tracking number (Tracking missing); the other 8 have a
  //    number no carrier has said anything about (Invalid tracking once NO_SCAN_GRACE_DAYS have passed)
  for (let i = 0; i < 14; i += 1) {
    const carrier = i < 9 ? 'Marketplace Logistics' : '';
    const dispatchMs = now - between(1, 14) * D;
    make({ carrier_name: carrier, tracking_number: i < 6 ? '' : `ML${ib(1e9, 9.99e9)}`, order_created_at: iso(dispatchMs - between(10, 40) * H),
      fulfilled_at: iso(dispatchMs), _tag: i < 6 ? 'F_missing' : 'F' });
  }
  // G: tracking given, carrier status "pending" and no scan yet (4): On track for the first days, then Invalid tracking
  for (let i = 0; i < 4; i += 1) sent(carrierPick(), now - between(1, 5) * D, { normalized_tracking_status: 'pending', _tag: 'G' });
  // H: the last scan says delivered but the status was never updated (4): delivered by that evidence
  for (let i = 0; i < 4; i += 1) {
    const carrier = carrierPick();
    const dispatchMs = now - between(3, 6) * D;
    const rec = sent(carrier, dispatchMs, { order_created_at: iso(dispatchMs - 20 * H), normalized_tracking_status: 'in_transit', _tag: 'H' });
    timeline(rec, dispatchMs, now - between(0.4, 2.5) * D, 4, ['in_transit', 'Delivered - left with resident'], false);
  }
  // M: Amazon (MCF) shipped it but Shopify still shows the order unfulfilled (3): Fix in Shopify
  for (let i = 0; i < 3; i += 1) {
    const dispatchMs = now - between(2, 6) * D;
    const rec = make({ row_kind: 'amazon', carrier_name: 'Marketplace Logistics', tracking_number: `TBA${ib(1e11, 9.99e11)}`, order_created_at: iso(dispatchMs - between(10, 40) * H),
      fulfilled_at: iso(dispatchMs), normalized_tracking_status: 'in_transit', amazon_status: 'Shipped', amazon_at: iso(dispatchMs), amazon_ref: `MCF-DEMO-${ib(1000, 9999)}`, _tag: 'M' });
    rec.amazon_tracking = rec.tracking_number;
    timeline(rec, dispatchMs, now - between(0.3, 1.5) * D, ib(1, 3), null, false);
  }

  // number the orders by creation date, then add duplicates and second parcels
  records.sort((a, b) => ms(a.order_created_at) - ms(b.order_created_at));
  records.forEach((rec, i) => { rec.order_number = `DEMO-#${10001 + i}`; });
  const pool = records.filter((x) => x._tag === 'B');
  for (let i = 0; i < 3; i += 1) pool[i * 2 + 1].tracking_number = pool[i * 2].tracking_number;     // duplicate tracking numbers: Fix in Shopify
  const extras = [];
  pool.slice(8, 14).forEach((src, i) => {                                                           // second parcel on the same order
    const x = { ...JSON.parse(JSON.stringify(src)), tracking_number: tracking(src.carrier_name), _tag: 'multi' };
    if (i === 0) { x.normalized_tracking_status = 'delivered'; x.delivered_at = iso(now - 6 * H); }  // one parcel arrived: the whole order is delivered
    extras.push(x);
  });
  pool.slice(14, 16).forEach((old) => {                     // reshipped: the old parcel stopped moving, the same items were sent again
    const oldMs = now - between(13, 16) * D;
    old.fulfilled_at = iso(oldMs); old.order_created_at = iso(oldMs - 20 * H); old.normalized_tracking_status = 'in_transit';
    timeline(old, oldMs, now - between(10, 12) * D, 3, null, false);
    const newMs = now - between(1, 2) * D;
    const x = { ...JSON.parse(JSON.stringify(old)), tracking_number: tracking(old.carrier_name), fulfilled_at: iso(newMs), expected_delivery_at: iso(newMs + 5 * D), _tag: 'resent' };
    timeline(x, newMs, now - 8 * H, 2, null, false);
    old.reshipped = { how: 'sent_again', detail: `The same items were sent again on ${day(newMs)}.`, newOrder: old.order_number,
      newTracking: x.tracking_number, newCarrier: x.carrier_name, newStatus: 'on_track', newAt: iso(newMs) };
    extras.push(x);
  });
  const amz = pool[16];                                     // an Amazon parcel the Shopify order does not list: Fix in Shopify
  if (amz) {
    const x = { ...JSON.parse(JSON.stringify(amz)), row_kind: 'amazon', carrier_name: 'Marketplace Logistics', tracking_number: `TBA${ib(1e11, 9.99e11)}`,
      amazon_status: 'Shipped', amazon_at: amz.fulfilled_at, amazon_ref: `MCF-DEMO-${ib(1000, 9999)}`, amazon_extra: [amz.tracking_number], _tag: 'amazon_extra' };
    x.amazon_tracking = x.tracking_number;
    extras.push(x);
  }
  records.push(...extras);
  // team marks on parcels with no carrier data: delivered and lost / couldn't deliver move them out of the active lists
  const marks = ['delivered', 'delivered', 'lost', 'failed', 'in_transit'];
  records.filter((x) => x._tag === 'F').slice(0, 5).forEach((x, i) => { x.manual = { status: marks[i], at: iso(now - between(2, 60) * H) }; });
  const word = records.filter((x) => x._tag === 'F')[6];    // Amazon's own word says it arrived: delivered
  if (word) { word.amazon_status = 'Package delivered near the front door'; word.amazon_at = iso(now - 20 * H); }
  records.forEach((x, i) => { x.id = i + 1; });

  // one check per order
  const byOrder = new Map();
  records.forEach((x) => { if (!byOrder.has(x.order_number)) byOrder.set(x.order_number, []); byOrder.get(x.order_number).push(x); });
  const checks = [];
  for (const [order, pk] of byOrder) {
    const first = pk[0];
    const tag = first._tag;
    checks.push({
      order_number: order, brand: first.brand, order_created_at: first.order_created_at,
      fulfillment_status: pk.some((x) => x.row_kind !== 'amazon') ? 'FULFILLED' : 'UNFULFILLED', financial_status: tag === 'refunded' ? 'REFUNDED' : 'PAID', cancelled: tag === 'cancelled',
      says_done: r() < 0.35, order_total: first.order_total, order_currency: 'USD',
    });
  }
  const annotations = {};
  const flagTargets = records.filter((x) => x._tag === 'red').slice(0, 2);
  flagTargets.forEach((x, i) => {
    annotations[x.order_number] = { reviewedAt: i === 0 ? iso(now - 5 * H) : null, reviewedBy: i === 0 ? 'Demo Admin' : null, flagged: true, flaggedAt: iso(now - 20 * H),
      notes: [{ at: iso(now - 20 * H), by: 'Demo Admin', text: i === 0 ? 'Carrier says the parcel is at the regional hub. Asked for an update.' : 'Customer asked about this order. Escalating to the carrier.' }] };
  });
  const gaveUp = records.filter((x) => x._tag === 'orange')[0];   // the team's outcome on a whole order: Resolved
  if (gaveUp) annotations[gaveUp.order_number] = { reviewedAt: null, reviewedBy: null, flagged: false, flaggedAt: null, outcome: 'lost', outcomeAt: iso(now - 30 * H), outcomeBy: 'Demo Admin',
    notes: [{ at: iso(now - 30 * H), by: 'Demo Admin', text: 'Carrier confirmed the parcel is lost. A replacement is being arranged.' }] };
  records.forEach((x) => { delete x._tag; });
  db.shipping = { shipments: records, checks, annotations };
}

/* ------------------------------------------------------------------ dataset (as board.build) */
function band(days) {
  return days >= THRESH.red ? 'red' : days >= THRESH.orange ? 'orange' : days >= THRESH.yellow ? 'yellow' : 'on_track';
}

/** (category, days on the clock, stage). The clock runs from the last carrier scan, or from dispatch while there is none. */
function flowCategory(dispatched, lastScan, now, delivered) {
  if (delivered) return ['delivered', null, 'delivered'];
  if (dispatched === null) return ['', null, 'pre_dispatch'];
  const days = completeDays(lastScan !== null ? Math.max(dispatched, lastScan) : dispatched, now) || 0;
  return [band(days), days, 'dispatched'];
}

const orderKey = (x) => `${x.brand || ''}|${x.order_number}`;
const group = (list) => { const m = new Map(); list.forEach((x) => { const k = orderKey(x); if (!m.has(k)) m.set(k, []); m.get(k).push(x); }); return m; };

/** One dispatched parcel with its clock and the facts its section is decided from; null for an order not sent yet. */
function enrich(s, now, excluded) {
  const status = (s.normalized_tracking_status || '').toLowerCase();
  const shipped = ms(s.fulfilled_at);
  if (shipped === null) return null;                  // not sent yet: not tracked on this page
  const lastScan = ms(s.last_scan_at);
  const mark = s.manual?.status ?? '';
  const scanSays = DELIVERED_SCAN.test(s.last_scan_description || '');
  const delivered = status === 'delivered' || scanSays || mark === 'delivered';
  let deliveredAt = ms(s.delivered_at);
  if (delivered && deliveredAt === null && scanSays) deliveredAt = lastScan;
  const [cat, days, stage] = flowCategory(shipped, lastScan, now, delivered);
  const missing = !s.tracking_number;
  // a number no carrier has said anything about (no status, no scan) after the grace days: wrong, or never handed over
  const invalid = !delivered && !missing && ['', 'pending'].includes(status) && lastScan === null && (completeDays(shipped, now) || 0) >= NO_SCAN_GRACE_DAYS;
  return { ...s, row_kind: s.row_kind || 'shipment', normalized_tracking_status: status, cat, band: cat, days, stage, scanAge: completeDays(lastScan, now),
    exc: s.exception || (['failed_delivery', 'returned'].includes(status) ? status : ''), manual: TEAM_STATES.includes(mark) ? s.manual : null,
    invalid, issues: [], missingTracking: missing, excluded: excluded.get(s.order_number) ?? null,
    key: `${s.order_number}|${s.tracking_number}|${s.id}`, trackingId: s.tracking_number ? `demo-${s.id}` : null,
    created: ms(s.order_created_at), shipped, lastScan, expected: ms(s.expected_delivery_at), deliveredAt };
}

/** The team's outcome for the whole order wins; then a team "lost" / "couldn't deliver" mark; then the carrier's word. */
function markResolved(everything, annotations) {
  everything.forEach((x) => {
    if (x.cat === 'delivered') return;
    const a = annotations[x.order_number];
    if (TEAM_OUTCOMES.includes(a?.outcome)) {
      x.resolved = { outcome: a.outcome, label: OUTCOMES[a.outcome], by: 'team', who: a.outcomeBy ?? null, at: a.outcomeAt ?? null, detail: '' };
    } else if (x.manual && ['lost', 'failed'].includes(x.manual.status)) {
      x.resolved = { outcome: x.manual.status, label: OUTCOMES[x.manual.status], by: 'team', who: null, at: x.manual.at ?? null, detail: 'Team mark on the parcel.' };
    } else {
      const text = x.last_scan_description || '';
      const o = LOST_RE.test(text) ? 'lost' : x.normalized_tracking_status === 'returned' || RETURN_RE.test(text) ? 'returned' : null;
      if (o) x.resolved = { outcome: o, label: OUTCOMES[o], by: 'carrier', who: x.carrier_name || null, at: iso(x.lastScan), detail: text };
    }
  });
}

const amazonSaysDelivered = (x) => AMAZON_DELIVERED.test(x.amazon_status || '') && !AMAZON_NOT_DELIVERED.test(x.amazon_status || '');

/** An order that has arrived is not a problem: once ANY parcel of it is delivered (or a parcel with the same tracking
 *  number, or Amazon's word on the order), every other open parcel of it is delivered too ("order delivered"). */
function markOrderDelivered(everything) {
  const live = everything.filter((x) => !x.excluded);
  const shared = new Map(live.filter((x) => x.cat === 'delivered' && x.tracking_number).map((x) => [`${x.brand}|${x.tracking_number.toUpperCase()}`, x]));
  const order = (x, detail, at) => { x.resolved = { outcome: 'delivered', label: 'Delivered', by: 'order', who: null, at, detail }; };
  live.forEach((x) => {
    if (x.cat === 'delivered' || x.resolved || !x.tracking_number) return;
    const y = shared.get(`${x.brand}|${x.tracking_number.toUpperCase()}`);
    if (y && y !== x) order(x, `Sent together with order ${y.order_number}: ${y.carrier_name || 'The carrier'} ${y.tracking_number} was delivered.`, iso(y.deliveredAt ?? y.lastScan));
  });
  for (const parcels of group(live).values()) {
    const done = parcels.filter((x) => x.cat === 'delivered' || x.resolved?.outcome === 'delivered');
    const open = parcels.filter((x) => x.cat !== 'delivered' && !x.resolved);
    const word = parcels.find(amazonSaysDelivered);
    if (!done.length && word) { open.forEach((x) => order(x, `Amazon says "${(word.amazon_status || '').slice(0, 80)}".`, word.amazon_at)); continue; }
    if (!done.length) continue;
    const times = done.map((x) => x.deliveredAt ?? x.lastScan).filter((t) => t !== null);
    const last = times.length ? Math.max(...times) : null;
    const what = done.filter((x) => x.tracking_number).map((x) => `${x.carrier_name || 'Unknown'} ${x.tracking_number}`).join(', ') || 'another parcel';
    open.forEach((x) => order(x, `The order was delivered (${what})${last ? `, last on ${day(last)}` : ''}. ${x.missingTracking ? 'This parcel has no tracking number' : 'This parcel is still open'} in Shopify or Amazon.`, iso(last)));
  }
}

/** Each active parcel's own section, then every active parcel of an order moves to the order's first section. */
function assignSections(rows, now) {
  const active = rows.filter((x) => x.cat !== 'delivered');
  const dup = {};
  active.forEach((x) => { if (x.tracking_number) { const k = x.tracking_number.toUpperCase(); dup[k] = (dup[k] || 0) + 1; } });
  active.forEach((x) => {
    const issues = [];
    const tn = x.tracking_number ? ` (tracking ${x.tracking_number})` : '';
    if (x.missingTracking) issues.push(['missing_tracking', `Dispatched ${x.days ?? 0} days ago with no tracking number. Add it in Shopify.`]);
    else if (x.invalid) issues.push(['invalid_tracking', `${x.carrier_name || 'The carrier'} has reported nothing on ${x.tracking_number} since it was dispatched ${x.days ?? 0} days ago. Check the number.`]);
    if (x.row_kind === 'amazon' && x.amazon_extra?.length) issues.push(['amazon_tracking_missing', `Amazon (MCF) sent a parcel${tn} that is not on the Shopify order, which lists ${x.amazon_extra.join(', ')}. Check whether the order was split or sent twice, and add the Amazon tracking number to the Shopify order.`]);
    else if (x.row_kind === 'amazon') issues.push(['amazon_not_in_shopify', `Amazon shipped it ${completeDays(x.shipped, now) ?? 0} days ago${tn}; Shopify still shows the order unfulfilled. Mark it fulfilled in Shopify.`]);
    if (x.tracking_number && dup[x.tracking_number.toUpperCase()] > 1) issues.push(['duplicate_tracking', `Tracking number ${x.tracking_number} is used on ${dup[x.tracking_number.toUpperCase()]} parcels.`]);
    x.issues = issues;
    x.ownCat = x.cat = issues.reduce((best, [k]) => (RANK[EXC_TYPES[k].section] < RANK[best] ? EXC_TYPES[k].section : best), x.band);
  });
  for (const parcels of group(active).values()) {
    const top = parcels.reduce((best, x) => (RANK[x.cat] < RANK[best] ? x.cat : best), parcels[0].cat);
    parcels.forEach((x) => { x.cat = top; });
  }
}

function buildDataset(db, brand, now = Date.now()) {
  const inScope = (x) => !brand || x.brand === brand;
  const checks = db.shipping.checks.filter(inScope);
  const annotations = db.shipping.annotations;
  const excluded = new Map(checks.filter((c) => c.cancelled || c.financial_status === 'REFUNDED').map((c) => [c.order_number, c.cancelled ? 'cancelled' : 'refunded']));
  const everything = db.shipping.shipments.filter(inScope).map((s) => enrich(s, now, excluded)).filter(Boolean);
  markResolved(everything, annotations);
  markOrderDelivered(everything);
  everything.forEach((x) => {                         // delivered by any evidence: delivered, never "resolved"
    if (x.resolved?.outcome === 'delivered') { x.deliveredBy = x.resolved; delete x.resolved; x.cat = 'delivered'; x.reshipped = null; }
  });
  const rows = everything.filter((x) => !x.excluded && !x.reshipped && !x.resolved);
  assignSections(rows, now);
  const reshipped = everything.filter((x) => !x.excluded && x.reshipped && !x.resolved && x.cat !== 'delivered');
  const resolved = everything.filter((x) => !x.excluded && x.resolved);
  return { rows, everything, reshipped, resolved, checks, now, brand, annotations, active: rows.filter((x) => x.cat !== 'delivered') };
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
    source: { state: 'ok', reason: '', asOf, parts: {}, demo: true, freshness: { state: 'fresh', message: '', lastChecked: asOf, staleAfterHours: 2, stores: [] }, amazonMcf: { loaded: false } },
    notConfigured: [], ...payload,
  };
}

/* ------------------------------------------------------------------ reports */
const flagged = (d, x) => !!d.annotations[x.order_number]?.flagged;
const countBy = (list, f) => { const m = {}; list.forEach((x) => { const k = f(x); m[k] = (m[k] || 0) + 1; }); return m; };
const orders = (list) => new Set(list.map(orderKey)).size;

function valueAtRisk(d) {
  const totals = new Map();
  d.rows.forEach((x) => { if (x.cat === 'red' && x.order_total !== null && !totals.has(x.order_number)) totals.set(x.order_number, x.order_total); });
  if (!totals.size) return { available: true, orders: 0, total: null, currency: '' };
  return { available: true, orders: totals.size, total: Math.round([...totals.values()].reduce((s, v) => s + v, 0) * 100) / 100, currency: 'USD', note: '' };
}

/** Every hand-check issue of the parcels in the Tracking missing, Invalid tracking and Fix in Shopify sections. */
function exceptionRows(d) {
  const out = [];
  d.active.filter((x) => HAND_CHECKS.includes(x.cat)).forEach((x) => x.issues.forEach(([type, detail]) => out.push({
    order: x.order_number, key: x.key, type, label: EXC_TYPES[type].label, severity: EXC_TYPES[type].severity, detail, carrier: x.carrier_name || 'Unknown',
    tracking: x.missingTracking ? '' : x.tracking_number, days: x.days, brand: x.brand, shopifyUrl: '', section: x.cat })));
  const sev = { high: 0, medium: 1 };
  return out.sort((a, b) => RANK[a.section] - RANK[b.section] || sev[a.severity] - sev[b.severity] || (b.days ?? 0) - (a.days ?? 0) || a.order.localeCompare(b.order));
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

function reshippedReport(d) {
  const rows = [...d.reshipped].sort((a, b) => (b.days || 0) - (a.days || 0)).map((x) => {
    const rs = x.reshipped;
    return { order: x.order_number, key: x.key, brand: x.brand, carrier: x.carrier_name || '—', shopifyUrl: '', tracking: x.missingTracking ? '' : x.tracking_number,
      oldCat: x.band, oldStatus: x.normalized_tracking_status || '', lastScan: x.last_scan_description || '', days: x.days, stage: x.stage,
      how: rs.how, howLabel: RESHIP_HOW[rs.how] ?? rs.how, detail: rs.detail, newOrder: rs.newOrder ?? null, newTracking: rs.newTracking ?? null,
      newCarrier: rs.newCarrier ?? null, newStatus: rs.newStatus ?? null, newAt: rs.newAt ?? null,
      action: 'Close the old fulfilment in Shopify (or cancel the Amazon MCF order) so it stops showing as open.' };
  });
  return { total: rows.length, rows, counts: Object.fromEntries(Object.keys(RESHIP_HOW).map((k) => [k, rows.filter((x) => x.how === k).length])),
    rule: 'A parcel that never arrived but was sent again: a replacement order names it, a later parcel of the same order carries the same items, the order note says it was reshipped, a second Amazon order was sent, or another parcel delivered the order. These are left out of every delay figure.' };
}

function checks(d) {
  const issues = exceptionRows(d);
  const rows = exceptionOrders(issues);
  return {
    reshipped: reshippedReport(d),
    counts: Object.fromEntries(HAND_CHECKS.map((s) => [s, orders(d.active.filter((x) => x.cat === s))])),
    // total = orders (one row each); counts = orders with that type, so an order with two tags counts in both
    exceptions: { total: rows.length, issues: issues.length, counts: Object.fromEntries(Object.keys(EXC_TYPES).map((k) => [k, rows.filter((x) => x.types.includes(k)).length])),
      types: Object.entries(EXC_TYPES).map(([key, v]) => ({ key, label: v.label, severity: v.severity })), rows },
  };
}

function kpis(d) {
  const counts = countBy(d.active, (x) => x.cat);
  const values = { '': d.active.length, reshipped: d.reshipped.length };
  return [['', 'Total active shipments', 'neutral'], ['on_track', 'On track (0-3 days)', 'good'], ['yellow', 'Yellow 4-5 days', 'warn'], ['orange', 'Orange 6-8 days', 'orange'],
    ['red', 'Critical 9+ days', 'bad'], ['tracking_missing', 'Tracking missing', 'bad'], ['invalid', 'Invalid tracking', 'info'], ['checks', 'Fix in Shopify', 'warn'],
    ['reshipped', 'Reshipped, old parcel still open', 'info']]
    .map(([key, label, tone]) => ({ key, label, value: key in values ? values[key] : counts[key] || 0, tone }));
}

const AWAITING_SCAN = ['', 'pending', 'info_received'];

/** Where every dispatched parcel is, for the Overview journey strip; the three parcel stages add up to the active total. */
function journey(d) {
  const waiting = d.active.filter((x) => AWAITING_SCAN.includes(x.normalized_tracking_status));
  const out = d.active.filter((x) => x.normalized_tracking_status === 'out_for_delivery');
  const moving = d.active.filter((x) => !AWAITING_SCAN.includes(x.normalized_tracking_status) && x.normalized_tracking_status !== 'out_for_delivery');
  const flag = (label, n, tone, cat) => (n ? [{ label, value: n, tone, cat }] : []);
  const flags = (list) => [...flag('tracking missing', list.filter((x) => x.cat === 'tracking_missing').length, 'crit', 'tracking_missing'),
    ...flag('invalid tracking', list.filter((x) => x.cat === 'invalid').length, 'info', 'invalid'),
    ...flag('critical', list.filter((x) => x.cat === 'red').length, 'crit', 'red')];
  return [
    { key: 'dispatched', label: 'Sent, no carrier scan yet', value: waiting.length, flags: flags(waiting) },
    { key: 'in_transit', label: 'In transit', value: moving.length, flags: flags(moving) },
    { key: 'out_for_delivery', label: 'Out for delivery', value: out.length, flags: flags(out) },
    // same rule as deliveryReport(d, 30), so it matches the Overview's "Delivered, last 30 days"
    { key: 'delivered', label: 'Delivered, last 30 days', value: deliveryReport(d, 30).delivered, flags: [] },
  ];
}

function summary(d) {
  const critical = d.active.filter((x) => x.cat === 'red').length;
  const c = checks(d);
  const dr = deliveryReport(d, 30);
  const delivered = d.rows.filter((x) => x.cat === 'delivered').length;
  return {
    journey: journey(d),
    delivery30: { delivered: dr.delivered, onTimePct: dr.onTimePct, avgDays: dr.avgDays, withPromisedDate: dr.withPromisedDate },
    kpis: kpis(d), activeTotal: d.active.length, critical, delivered,
    stage: { dispatched: d.active.length, delivered },
    banner: critical ? `CRITICAL: ${critical} shipment(s) have had no carrier update for ${THRESH.red}+ days. Escalate today.` : '',
    valueAtRisk: valueAtRisk(d), checks: c.counts, exceptions: c.exceptions.total,
    thresholds: { ...THRESH, noScanGrace: NO_SCAN_GRACE_DAYS }, totals: { shipments: d.everything.length, afterExclusions: d.rows.length },
    deliveredWindowDays: DELIVERED_KEEP_DAYS,
  };
}

function carriersReport(d) {
  const by = new Map();
  d.active.forEach((x) => {
    const name = x.carrier_name || 'Unknown';
    if (!by.has(name)) by.set(name, { n: 0, crit: 0, hand: 0, days: [], cats: {} });
    const c = by.get(name);
    c.n += 1; c.cats[x.cat] = (c.cats[x.cat] || 0) + 1;
    if (x.days !== null) c.days.push(x.days);
    if (x.cat === 'red') c.crit += 1;
    if (HAND_CHECKS.includes(x.cat)) c.hand += 1;
  });
  const scored = [...by.entries()].sort((a, b) => b[1].n - a[1].n).map(([name, c]) => {
    const pct = Math.round((c.crit / c.n) * 100);
    return { carrier: name, active: c.n, critical: c.crit, criticalPct: pct, handChecks: c.hand,
      avgDays: c.days.length ? Math.round(c.days.reduce((s, v) => s + v, 0) / c.days.length) : null,
      health: pct > 50 ? 'bad' : pct > 20 ? 'warn' : 'ok', healthLabel: pct > 50 ? 'Needs action' : pct > 20 ? 'Watch' : 'Healthy',
      cats: Object.fromEntries(AGING_KEYS.map((k) => [k, c.cats[k] || 0])) };
  });
  return { scorecard: scored, heatmap: scored.slice(0, 8), categories: AGING_KEYS.map((k) => ({ key: k, label: AGING_LABELS[k] })) };
}

const weekStart = (t) => { const x = new Date(t); const dow = (x.getUTCDay() + 6) % 7; return new Date(Date.UTC(x.getUTCFullYear(), x.getUTCMonth(), x.getUTCDate() - dow)).toISOString().slice(0, 10); };

/** Parcels delivered in the last `period` days, dispatch to delivery. On time = by the end of the promised day; parcels
 *  without a promised date are left out of the on-time share (counted in delivered and average days). */
function deliveryReport(d, period) {
  const since = d.now - period * D;
  const done = d.rows.filter((x) => x.cat === 'delivered' && x.deliveredAt && x.deliveredAt >= since && x.shipped);
  const days = (x) => Math.max(0, (x.deliveredAt - x.shipped) / D);
  const dayEnd = (t) => { const x = new Date(t); return Date.UTC(x.getUTCFullYear(), x.getUTCMonth(), x.getUTCDate(), 23, 59, 59); };
  const pct = (list) => { const p = list.filter((x) => x.expected); return p.length ? Math.round((p.filter((x) => x.deliveredAt <= dayEnd(x.expected)).length / p.length) * 100) : null; };
  const avg = (list) => (list.length ? Math.round((list.reduce((s, x) => s + days(x), 0) / list.length) * 10) / 10 : null);
  const buckets = [['1-2 days', 0, 3], ['3-4 days', 3, 5], ['5-6 days', 5, 7], ['7-8 days', 7, 9], ['9+ days', 9, 1e9]];
  const grouped = (keyFn) => {
    const m = new Map();
    done.forEach((x) => { const k = keyFn(x); if (!m.has(k)) m.set(k, []); m.get(k).push(x); });
    return [...m.entries()].map(([k, list]) => ({ name: k, delivered: list.length, onTimePct: pct(list), avgDays: avg(list) })).sort((a, b) => b.delivered - a.delivered);
  };
  const weeks = new Map();
  done.forEach((x) => { const w = weekStart(x.deliveredAt); if (!weeks.has(w)) weeks.set(w, []); weeks.get(w).push(x); });
  return {
    period, delivered: done.length, onTimePct: pct(done), avgDays: avg(done), withPromisedDate: done.filter((x) => x.expected).length,
    distribution: buckets.map(([label, lo, hi]) => ({ key: label, label, value: done.filter((x) => days(x) >= lo && days(x) < hi).length })),
    byCarrier: grouped((x) => x.carrier_name || 'Unknown').map((g) => ({ carrier: g.name, delivered: g.delivered, onTimePct: g.onTimePct, avgDays: g.avgDays })),
    byRegion: grouped((x) => x.state || 'Unknown').slice(0, 8).map((g) => ({ region: g.name, delivered: g.delivered, onTimePct: g.onTimePct, avgDays: g.avgDays })),
    trend: [...weeks.entries()].sort((a, b) => (a[0] < b[0] ? -1 : 1)).map(([week, list]) => ({ week, onTimePct: pct(list), delivered: list.length })),
  };
}

function analytics(d, query) {
  const active = d.active;
  const crit = active.filter((x) => x.cat === 'red').length;
  const hand = active.filter((x) => HAND_CHECKS.includes(x.cat)).length;
  const dayList = active.filter((x) => x.days !== null).map((x) => x.days);
  const count = countBy(active, (x) => x.cat);
  const weeks = countBy(active.filter((x) => x.created), (x) => weekStart(x.created));
  const weekRows = Object.entries(weeks).sort((a, b) => (a[0] < b[0] ? -1 : 1)).slice(-12);
  const cr = carriersReport(d);
  const car = cr.scorecard.slice(0, 8);
  const dispatch = {}; const dispatchCrit = {};
  active.forEach((x) => {
    const wd = x.shipped ? WEEKDAYS[(new Date(x.shipped + 5.5 * H).getUTCDay() + 6) % 7] : 'No date';   // India time
    dispatch[wd] = (dispatch[wd] || 0) + 1;
    if (x.cat === 'red') dispatchCrit[wd] = (dispatchCrit[wd] || 0) + 1;
  });
  const dayLabels = [...WEEKDAYS.filter((w) => dispatch[w]), ...(dispatch['No date'] ? ['No date'] : [])];
  const tips = [];
  if (crit) tips.push(`${crit} active shipments have had no carrier update for ${THRESH.red}+ days. Escalate these first (filter: Critical).`);
  const worst = car.reduce((m, c) => (!m || c.critical > m.critical ? c : m), null);
  if (worst && worst.critical) tips.push(`${worst.carrier} has the most critical shipments (${worst.critical}). Check them with this carrier first.`);
  if (count.tracking_missing) tips.push(`${count.tracking_missing} parcels were dispatched without a tracking number. Add it in Shopify.`);
  if (count.invalid) tips.push(`${count.invalid} parcels have a tracking number no carrier has reported anything on. Check the numbers.`);
  if (count.checks) tips.push(`${count.checks} parcels need a fix in Shopify (Amazon shipments Shopify does not know about, or a tracking number used twice).`);
  const period = query.period === '90' ? 90 : 30;
  return {
    kpis: { active: active.length, critical: crit, criticalPct: active.length ? Math.round((crit / active.length) * 100) : 0,
      onTrackPct: active.length ? Math.round(((count.on_track || 0) / active.length) * 100) : 0,
      avgDays: dayList.length ? Math.round(dayList.reduce((s, v) => s + v, 0) / dayList.length) : null, handChecks: hand,
      carriersInUse: new Set(active.map((x) => x.carrier_name || 'Unknown')).size, valueAtRisk: valueAtRisk(d) },
    aging: AGING_KEYS.map((k) => ({ key: k, label: AGING_LABELS[k], value: count[k] || 0 })),
    weeks: weekRows.map(([week, value]) => ({ week, value })),
    carriers: car.map((c) => ({ carrier: c.carrier, critical: c.critical, other: c.active - c.critical })),
    stage: [{ label: 'Dispatched (active)', value: active.length },
      { label: `Delivered (last ${DELIVERED_KEEP_DAYS} days)`, value: d.rows.filter((x) => x.cat === 'delivered').length }],
    dispatchDay: dayLabels.map((wd) => ({ day: wd, critical: dispatchCrit[wd] || 0, other: dispatch[wd] - (dispatchCrit[wd] || 0) })),
    insights: tips, carriersReport: cr, delivery: deliveryReport(d, period),
  };
}

/* ------------------------------------------------------------------ list, detail */
const cmp = (a, b) => { for (let i = 0; i < a.length; i += 1) if (a[i] !== b[i]) return a[i] < b[i] ? -1 : 1; return 0; };
const orderDigits = (n) => Number(n.replace(/\D/g, '')) || 0;
const SORT_KEYS = {
  priority: (x) => [RANK[x.cat] ?? 9, -(x.days || 0)],
  order: (x) => [orderDigits(x.order_number), x.order_number],
  oldest: (x) => [-(x.days ?? -1)],
};

function selectRows(d, f) {
  const needle = (f.q || '').trim().toLowerCase();
  const orderDays = Number(f.days) || 0;
  const cutoff = orderDays ? d.now - orderDays * D : 0;
  const source = f.cat === 'reshipped' ? d.reshipped : f.cat === 'resolved' ? d.resolved : d.rows;
  const out = source.filter((x) => {
    if (x.cat === 'delivered') return false;
    if (cutoff && (!x.created || x.created < cutoff)) return false;
    if (f.cat === 'reshipped' || f.cat === 'resolved') { /* the whole list, filtered only by the fields below */ }
    else if (f.cat === 'flagged') { if (!flagged(d, x)) return false; }
    else if (f.cat && x.cat !== f.cat) return false;
    if (f.carrier && x.carrier_name !== f.carrier) return false;
    if (f.status && x.normalized_tracking_status !== f.status) return false;
    if (needle && !x.order_number.toLowerCase().includes(needle) && !x.tracking_number.toLowerCase().includes(needle)) return false;
    return true;
  });
  const key = SORT_KEYS[f.sort] || SORT_KEYS.priority;
  return out.sort((a, b) => cmp(key(a), key(b)));
}

/** What the browser receives for one parcel (as board.public_row): city and state only, never the note text. */
function publicRow(x, d, packages) {
  const cat = x.cat === 'delivered' ? 'delivered' : x.resolved ? 'resolved' : x.reshipped ? 'reshipped' : x.cat;
  const own = x.ownCat || x.band;
  let label = cat === 'delivered' ? LABELS.delivered : cat === 'resolved' ? `Resolved: ${x.resolved.label}` : cat === 'reshipped' ? 'Reshipped (old parcel)' : LABELS[cat] ?? cat;
  if (SECTIONS.includes(cat) && own !== cat) label += ` (this parcel: ${LABELS[own] ?? own})`;     // listed with the rest of its order
  return {
    key: x.key, order: x.order_number, tracking: x.tracking_number, carrier: x.carrier_name, cat, band: x.band, ownCat: own, agingCat: x.band, label,
    days: x.days, stage: x.stage, exception: x.exc, scanAge: x.scanAge, status: x.normalized_tracking_status, orderCreatedAt: x.order_created_at,
    dispatchedAt: x.fulfilled_at, lastScanAt: x.last_scan_at, lastScan: x.last_scan_description, expectedAt: x.expected_delivery_at, trackUrl: '', shopifyUrl: '',
    manual: x.manual, packages: packages[x.order_number] ?? 1, missingTracking: x.missingTracking, invalid: x.invalid, flagged: flagged(d, x),
    brand: x.brand, city: x.city, state: x.state, trackingId: x.trackingId, kind: x.row_kind === 'amazon' ? 'mcf' : null, rowKind: x.row_kind,
    amazonStatus: x.amazon_status ?? null, amazonAt: x.amazon_at ?? null, amazonRef: x.amazon_ref ?? null, amazonTracking: x.amazon_tracking ?? null,
    reshipped: x.reshipped ?? null, resolved: x.resolved ?? null, deliveredBy: x.deliveredBy ?? null,
    issues: (x.issues || []).map(([type, detail]) => ({ type, label: EXC_TYPES[type].label, detail })), delayReason: x.delay_reason,
  };
}

function packageCounts(d) {
  const p = {};
  d.rows.forEach((x) => { p[x.order_number] = (p[x.order_number] || 0) + 1; });
  return p;
}

const filtersOf = (query) => ({ q: (query.q || '').slice(0, 100), carrier: query.carrier || '', cat: (query.cat || '').slice(0, 20), status: query.status || '', days: query.days || '', sort: query.sort || 'priority' });

function listRows(d, query) {
  const out = selectRows(d, filtersOf(query));
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
  const outcome = TEAM_OUTCOMES.includes(a?.outcome) ? a.outcome : null;
  return { reviewedAt: a?.reviewedAt ?? null, reviewedBy: a?.reviewedBy ?? null, flagged: !!a?.flagged, flaggedAt: a?.flaggedAt ?? null, notes: a?.notes ?? [],
    outcome, outcomeLabel: outcome ? OUTCOMES[outcome] : null, outcomeAt: outcome ? a.outcomeAt ?? null : null, outcomeBy: outcome ? a.outcomeBy ?? null : null };
}

function action(x) {
  if (x.cat === 'delivered') return x.deliveredBy?.detail ? `Delivered. ${x.deliveredBy.detail}` : ACTIONS.delivered;
  if (x.resolved) {
    const rs = x.resolved;
    const who = rs.by === 'team' ? `the team${rs.who ? ` (${rs.who})` : ''}` : `the carrier (${rs.detail || 'last update'})`;
    return `Resolved as ${rs.label.toLowerCase()} by ${who}, so it is out of Critical and the delay figures. Nothing more to do here.`;
  }
  if (x.reshipped) return `Sent again: ${x.reshipped.detail} Close the old fulfilment in Shopify so it stops showing as open.`;
  if (x.issues?.length) return x.issues.map(([, detail]) => detail).join(' ');
  return ACTIONS[x.band] ?? 'Review manually.';
}

function orderDetail(d, order) {
  const pkgs = d.everything.filter((x) => x.order_number === order);
  if (!pkgs.length) throw new DemoError(404, 'No shipment found for that order.');
  const first = pkgs[0];
  const check = d.checks.find((c) => c.order_number === order) ?? null;
  const counts = { [order]: pkgs.length };
  return {
    order, excluded: first.excluded, brand: first.brand, shopifyUrl: '', destination: { city: first.city, state: first.state }, items: first.items,
    packages: pkgs.map((x) => ({
      ...publicRow(x, d, counts), action: action(x), location: x.last_scan_location, source: 'demo', checkedAt: iso(d.now - 3 * H),
      scanDescription: x.last_scan_description, events: x.events, promisedAt: x.expected_delivery_at, deliveredAt: iso(x.deliveredAt), rowKind: x.row_kind,
    })),
    check: check && { fulfillment: check.fulfillment_status, financial: check.financial_status, cancelled: check.cancelled, notesSayDone: check.says_done,
      createdAt: check.order_created_at, total: check.order_total, currency: check.order_currency,
      amazon: first.amazon_status ?? null, amazonAt: first.amazon_at ?? null, amazonRef: first.amazon_ref ?? null, amazonKnown: true },
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
  const act = body.action;
  if (act === 'check') { a.reviewedAt = at; a.reviewedBy = 'Demo Admin'; }
  else if (act === 'uncheck') { a.reviewedAt = null; a.reviewedBy = null; }
  else if (act === 'flag') { a.flagged = true; a.flaggedAt = at; }
  else if (act === 'unflag') { a.flagged = false; a.flaggedAt = null; }
  else if (act === 'note') {
    const text = String(body.text ?? '').trim();
    if (!text) throw new DemoError(400, 'Write a note first.');
    a.notes = [{ at, by: 'Demo Admin', text: text.slice(0, 500) }, ...a.notes];
  } else if (act === 'outcome') {
    const outcome = String(body.text ?? '').trim().toLowerCase();
    if (!TEAM_OUTCOMES.includes(outcome)) throw new DemoError(400, `Outcome must be one of: ${TEAM_OUTCOMES.join(', ')}.`);
    Object.assign(a, { outcome, outcomeAt: at, outcomeBy: 'Demo Admin' });
  } else if (act === 'clear_outcome') Object.assign(a, { outcome: null, outcomeAt: null, outcomeBy: null });
  else throw new DemoError(400, 'Unknown action.');
  return orderDetail(buildDataset(db, brandOf(query)), order);   // an outcome moves parcels between lists: build again
}

/* ------------------------------------------------------------------ import preview (as board.preview_import) */
const importCarriers = (d) => [...new Set(d.everything.map((x) => x.carrier_name).filter(Boolean))].sort();

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
  d.active.forEach((x) => { if (!byOrder.has(x.order_number)) byOrder.set(x.order_number, []); byOrder.get(x.order_number).push(x); });
  const dup = {};
  sheet.forEach((s) => { if (s.order) dup[`${s.order}|${s.tracking}`] = (dup[`${s.order}|${s.tracking}`] || 0) + 1; });
  const carriers = importCarriers(d);
  const allowed = Object.fromEntries(carriers.map((c) => [c.toLowerCase(), c]));
  const check = (s) => {
    if (!s.order) return ['error', 'Order number is missing.'];
    if (dup[`${s.order}|${s.tracking}`] > 1) return ['error', 'Duplicate row in this sheet.'];
    if (!s.tracking) return ['error', 'Tracking number is missing.'];
    if (!/^[A-Za-z0-9][A-Za-z0-9-]{5,39}$/.test(s.tracking)) return ['error', 'Tracking number looks wrong (letters, digits and dashes, 6 to 40 characters).'];
    if (!allowed[s.carrier.toLowerCase()]) return ['error', `Carrier must be one of: ${carriers.join(', ')}.`];
    const pk = byOrder.get(s.order);
    if (!pk) return ['error', 'Order not found among active parcels.'];
    const blank = pk.filter((p) => p.missingTracking);
    if (!blank.length) return ['skip_has_tracking', 'Every parcel of this order already has a tracking number.'];
    if (blank.length > 1) return ['ambiguous', `${blank.length} parcels of this order have no tracking number. Choose one.`];
    return ['will_update', 'Would add this tracking number to the one parcel without one (preview only).'];
  };
  const out = sheet.map((s) => { const [outcome, message] = check(s); return { ...s, carrier: allowed[s.carrier.toLowerCase()] ?? s.carrier, outcome, message }; });
  const counts = Object.fromEntries(['will_update', 'skip_has_tracking', 'ambiguous', 'error'].map((k) => [k, out.filter((o) => o.outcome === k).length]));
  return envelope(d, { previewOnly: true, rows: out, counts, carriers, note: 'Preview only (demo). Nothing was changed anywhere.' });
}

function sampleSheet(d) {
  const blank = d.active.filter((x) => x.row_kind === 'shipment' && x.missingTracking).slice(0, 3);
  const has = d.active.find((x) => x.tracking_number);
  const carrier = importCarriers(d)[0] ?? 'Standard Ground';
  const lines = ['order_number,tracking_number,carrier', ...blank.map((x, i) => `${x.order_number},EXAMPLE${1000001 + i},${x.carrier_name || carrier}`)];
  if (has) lines.push(`${has.order_number},EXAMPLE2000002,${has.carrier_name || carrier}`);
  lines.push(`#000000,EXAMPLE3000003,${carrier}`, `${blank[0]?.order_number ?? '#000001'},12,${carrier}`);
  return lines.join('\n');
}

/* ------------------------------------------------------------------ Home (as board.home_figures) */
/** Shipping figures for the Home page, from the same board the Shipping page shows: the brand's (or both brands')
 *  figures, and the problems (Critical, or waiting for a hand check), longest on the clock first. */
export function shippingHomeSummary(db, brandId) {
  const d = buildDataset(db, brandId || undefined);
  const active = d.active;
  const problem = (x) => x.cat === 'red' || HAND_CHECKS.includes(x.cat);
  const critical = active.filter((x) => x.cat === 'red').length;
  const top = active.filter(problem).sort((a, b) => (b.days || 0) - (a.days || 0) || (a.key < b.key ? -1 : 1)).slice(0, HOME_TOP);
  return {
    active: active.length, inTransit: active.length, delivered30d: deliveryReport(d, 30).delivered,
    problems: active.filter(problem).length, critical, handChecks: active.filter((x) => HAND_CHECKS.includes(x.cat)).length,
    red: critical,                                    // core.js alertsFor() reads `red`
    asOf: iso(d.now),
    top: top.map((x) => ({ order: x.order_number, brand: x.brand, carrier: x.carrier_name || 'Unknown', days: x.days, place: x.last_scan_location || '',
      trackingId: x.trackingId ?? x.key, label: LABELS[x.cat] ?? x.cat })),
  };
}

/* ------------------------------------------------------------------ routes */
const fileStamp = () => new Date().toISOString().slice(0, 10);

export const routes = [
  ['GET', '/shipping/summary', ({ query, db }) => { const d = ds(db, query); return envelope(d, summary(d)); }],
  ['GET', '/shipping/shipments', ({ query, db }) => listRows(ds(db, query), query)],
  ['GET', '/shipping/shipments/:order', ({ params, query, db }) => { const d = ds(db, query); return envelope(d, orderDetail(d, params.order)); }],
  ['POST', '/shipping/shipments/:order/note', (ctx) => envelope(ds(ctx.db, ctx.query), annotate(ctx))],
  // a team mark on one parcel (the order drawer's "Team mark"): delivered moves the whole order out, lost / failed to Resolved
  ['POST', '/shipping/shipments/:id/mark', ({ params, body, db }) => {
    const rec = db.shipping.shipments.find((x) => `demo-${x.id}` === params.id);
    if (!rec) throw new DemoError(404, 'Shipment not found.');
    const mark = body.mark || null;
    if (mark !== null && !TEAM_STATES.includes(mark)) throw new DemoError(400, `Mark must be one of: ${TEAM_STATES.join(', ')}.`);
    rec.manual = mark ? { status: mark, at: new Date().toISOString() } : null;
    return { ok: true, trackingId: params.id, mark };
  }],
  ['GET', '/shipping/analytics', ({ query, db }) => { const d = ds(db, query); return envelope(d, analytics(d, query)); }],
  ['GET', '/shipping/checks', ({ query, db }) => { const d = ds(db, query); return envelope(d, checks(d)); }],
  ['POST', '/shipping/import/preview', ({ query, body, db }) => previewImport(ds(db, query), body.text)],
  ['GET', '/shipping/import/sample', ({ query, db }) => { const d = ds(db, query); return { text: sampleSheet(d), carriers: importCarriers(d) }; }],
  ['GET', '/shipping/export/shipments', ({ query, db }) => {
    const d = ds(db, query);
    return csvDownload(`shipments-${fileStamp()}.csv`,
      ['brand', 'order_number', 'carrier_name', 'tracking_number', 'section', 'days_since_last_update', 'tracking_status', 'order_created_at', 'dispatched_at', 'last_scan_at', 'last_scan', 'promised_delivery', 'tracking_url'],
      selectRows(d, filtersOf(query)).map((x) => [x.brand, x.order_number, x.carrier_name, x.tracking_number, x.cat, x.days, x.normalized_tracking_status, x.order_created_at, x.fulfilled_at, x.last_scan_at, x.last_scan_description, x.expected_delivery_at, '']));
  }],
  ['GET', '/shipping/export/escalation', ({ query, db }) => {
    const d = ds(db, query);
    const rows = d.active.filter((x) => x.cat === 'red' || flagged(d, x)).sort((a, b) => (b.days || 0) - (a.days || 0));
    return csvDownload(`escalation-list-${fileStamp()}.csv`, ['brand', 'order_number', 'carrier_name', 'tracking_number', 'days_since_last_update', 'reason', 'last_scan_at', 'last_scan_description', 'tracking_url'],
      rows.map((x) => [x.brand, x.order_number, x.carrier_name, x.tracking_number, x.days, x.cat === 'red' ? 'critical' : 'flagged by team', x.last_scan_at, x.last_scan_description, '']));
  }],
];
