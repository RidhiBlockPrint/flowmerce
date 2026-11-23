// Run with: node --test tests/demo-shipping.test.mjs   (from the frontend folder; no packages needed)
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { demoRequest, demoDownload, resetDemo } from '../src/demo/index.js';
import { seed, shippingHomeSummary } from '../src/demo/modules/shipping.js';

const get = (p) => demoRequest('GET', p);
const kpi = (s, key) => s.kpis.find((k) => k.key === key).value;
const note = (order, body) => demoRequest('POST', `/shipping/shipments/${encodeURIComponent(order)}/note`, body);
const SECTIONS = ['tracking_missing', 'invalid', 'checks', 'red', 'orange', 'yellow', 'on_track'];
const HAND = ['tracking_missing', 'invalid', 'checks'];

test('summary, list and checks agree with each other', async () => {
    resetDemo();
    const s = await get('/shipping/summary');
    assert.equal(s.source.state, 'ok');
    assert.ok(s.activeTotal > 80 && s.delivered > 50);
    assert.equal(kpi(s, ''), s.activeTotal);
    assert.equal(s.stage.dispatched, s.activeTotal);
    assert.deepEqual(s.kpis.map((k) => k.key), ['', 'on_track', 'yellow', 'orange', 'red', 'tracking_missing', 'invalid', 'checks', 'reshipped']);
    // every active parcel is in exactly one section, so the sections add up to the active total
    assert.equal(SECTIONS.reduce((t, k) => t + kpi(s, k), 0), s.activeTotal);
    for (const key of SECTIONS) assert.ok(kpi(s, key) > 0, `the demo shows some ${key}`);
    const all = await get('/shipping/shipments?size=200');
    assert.equal(all.total, s.activeTotal);
    // only dispatched, undelivered parcels are listed
    assert.ok(all.rows.every((r) => r.stage === 'dispatched' && r.dispatchedAt && SECTIONS.includes(r.cat)));
    for (const key of [...SECTIONS, 'reshipped']) {
        const l = await get(`/shipping/shipments?cat=${key}&size=200`);
        assert.equal(l.total, kpi(s, key), key);
    }
    const c = await get('/shipping/checks');
    assert.deepEqual(Object.keys(c).filter((k) => ['reshipped', 'counts', 'exceptions'].includes(k)).sort(), ['counts', 'exceptions', 'reshipped']);
    assert.deepEqual(c.counts, s.checks);
    assert.deepEqual(Object.keys(c.counts), HAND);
    // the hand-check counts are orders: the same orders the list shows in that section
    for (const key of HAND) {
        const l = await get(`/shipping/shipments?cat=${key}&size=200`);
        assert.equal(new Set(l.rows.map((r) => `${r.brand}|${r.order}`)).size, c.counts[key], key);
    }
    assert.equal(c.exceptions.total, c.exceptions.rows.length);
    assert.equal(s.exceptions, c.exceptions.total);
    // every order in a hand-check section is one row, and no other order is
    assert.equal(c.exceptions.total, HAND.reduce((t, k) => t + c.counts[k], 0));
    assert.ok(c.exceptions.rows.every((r) => HAND.includes(r.section)));
    const orders = c.exceptions.rows.map((r) => `${r.brand}|${r.order}`);
    assert.equal(new Set(orders).size, orders.length);
    assert.equal(c.exceptions.rows.reduce((a, r) => a + r.issues.length, 0), c.exceptions.issues);
    assert.deepEqual(c.exceptions.types.map((t) => t.key), ['missing_tracking', 'invalid_tracking', 'amazon_not_in_shopify', 'amazon_tracking_missing', 'duplicate_tracking']);
    for (const [k, n] of Object.entries(c.exceptions.counts)) {
        assert.equal(c.exceptions.rows.filter((r) => r.types.includes(k)).length, n, k);
        assert.ok(n > 0, `the demo shows some ${k}`);
    }
    assert.equal(c.reshipped.total, kpi(s, 'reshipped'));
    assert.equal(c.reshipped.rows.length, c.reshipped.total);
    // the journey: three parcel stages add up to the active total; delivered matches the 30-day delivery figure
    assert.deepEqual(s.journey.map((j) => j.key), ['dispatched', 'in_transit', 'out_for_delivery', 'delivered']);
    assert.equal(s.journey.slice(0, 3).reduce((t, j) => t + j.value, 0), s.activeTotal);
    assert.equal(s.journey[3].value, s.delivery30.delivered);
    assert.equal(s.thresholds.noScanGrace, 3);
});

test('an order is listed in one section only: the first that applies to any of its parcels', async () => {
    const all = await get('/shipping/shipments?size=200');
    const by = new Map();
    for (const r of all.rows) by.set(`${r.brand}|${r.order}`, new Set([...(by.get(`${r.brand}|${r.order}`) ?? []), r.cat]));
    assert.ok([...by.values()].every((cats) => cats.size === 1));
    const moved = all.rows.filter((r) => r.ownCat !== r.cat);
    assert.ok(moved.length > 0 && moved.every((r) => SECTIONS.indexOf(r.cat) < SECTIONS.indexOf(r.ownCat) && r.label.includes('this parcel')));
    // the clock is days since the last scan: the band follows it
    const band = (d) => (d >= 9 ? 'red' : d >= 6 ? 'orange' : d >= 4 ? 'yellow' : 'on_track');
    assert.ok(all.rows.every((r) => r.band === band(r.days)));
    const scanned = all.rows.filter((r) => r.lastScanAt && !r.missingTracking);
    assert.ok(scanned.every((r) => r.days === Math.floor((Date.now() - Math.max(Date.parse(r.lastScanAt), Date.parse(r.dispatchedAt))) / 864e5)));
    // invalid: a number with no carrier status or scan, 3+ days after dispatch
    const inv = await get('/shipping/shipments?cat=invalid&size=200');
    assert.ok(inv.rows.some((r) => r.invalid && !r.lastScanAt && ['', 'pending'].includes(r.status) && r.days >= 3));
    const tm = await get('/shipping/shipments?cat=tracking_missing&size=200');
    assert.ok(tm.rows.length && tm.rows.every((r) => r.missingTracking || r.ownCat !== 'tracking_missing'));
});

test('delivered by any evidence leaves every list; resolved and reshipped are kept apart', async () => {
    const all = (await get('/shipping/shipments?size=200')).rows;
    const resolved = (await get('/shipping/shipments?cat=resolved&size=200')).rows;
    const reshipped = (await get('/shipping/shipments?cat=reshipped&size=200')).rows;
    assert.ok(all.every((r) => !/^delivered/i.test(r.lastScan) && r.status !== 'delivered' && r.manual?.status !== 'delivered' && !r.resolved && !r.reshipped));
    assert.ok(resolved.length && resolved.every((r) => r.cat === 'resolved' && r.label.startsWith('Resolved: ')));
    assert.ok(resolved.some((r) => r.resolved.by === 'carrier') && resolved.some((r) => r.resolved.by === 'team'));
    assert.ok(reshipped.length && reshipped.every((r) => r.cat === 'reshipped' && r.reshipped.how));
    const keys = new Set(all.map((r) => r.key));
    assert.ok([...resolved, ...reshipped].every((r) => !keys.has(r.key)));
    // the team's outcome on a whole order moves it to Resolved, and undoing it brings it back
    const order = all.find((r) => r.cat === 'orange').order;
    const done = await note(order, { action: 'outcome', text: 'returned' });
    assert.equal(done.annotation.outcome, 'returned');
    assert.ok(done.packages.every((p) => p.cat === 'resolved'));
    assert.ok(!(await get('/shipping/shipments?size=200')).rows.some((r) => r.order === order));
    await assert.rejects(() => note(order, { action: 'outcome', text: 'maybe' }), /Outcome must be/);
    const back = await note(order, { action: 'clear_outcome' });
    assert.ok(back.packages.every((p) => p.cat !== 'resolved') && back.annotation.outcome === null);
    // a team mark "delivered" on any parcel delivers the whole order
    const multi = all.find((r) => r.packages > 1 && r.trackingId);
    await demoRequest('POST', `/shipping/shipments/${multi.trackingId}/mark`, { mark: 'delivered' });
    const after = await get(`/shipping/shipments/${encodeURIComponent(multi.order)}`);
    assert.ok(after.packages.every((p) => p.cat === 'delivered' || p.cat === 'reshipped' || p.cat === 'resolved'));
    assert.ok(after.packages.some((p) => p.deliveredBy?.by === 'order') || after.packages.length === 1);
    await demoRequest('POST', `/shipping/shipments/${multi.trackingId}/mark`, { mark: null });
});

test('brand filter splits the data and never adds brands together', async () => {
    const [a, r, k] = await Promise.all([get('/shipping/summary'), get('/shipping/summary?brand=ridhi'), get('/shipping/summary?brand=cpc')]);
    assert.equal(r.activeTotal + k.activeTotal, a.activeTotal);
    assert.equal(r.brand, 'ridhi');
    await assert.rejects(() => get('/shipping/summary?brand=nope'), /Unknown brand/);
});

test('list filters, search, sort and paging', async () => {
    const p0 = await get('/shipping/shipments?size=10&page=0');
    const p1 = await get('/shipping/shipments?size=10&page=1');
    assert.equal(p0.rows.length, 10);
    assert.ok(p0.pages > 2);
    assert.notEqual(p0.rows[0].key, p1.rows[0].key);
    assert.deepEqual(Object.keys(p0.facets), ['carriers', 'statuses']);
    // most urgent first: the section order, then the longest on the clock
    const prio = (await get('/shipping/shipments?size=200')).rows;
    assert.deepEqual(prio.map((r) => SECTIONS.indexOf(r.cat)), prio.map((r) => SECTIONS.indexOf(r.cat)).sort((x, y) => x - y));
    assert.equal(prio[0].cat, 'tracking_missing');
    const first = p0.rows[0];
    const carrier = p0.facets.carriers[0];
    const byCarrier = await get(`/shipping/shipments?carrier=${encodeURIComponent(carrier)}&size=200`);
    assert.ok(byCarrier.total > 0 && byCarrier.rows.every((x) => x.carrier === carrier));
    const q = await get(`/shipping/shipments?q=${encodeURIComponent(first.order.toLowerCase())}`);
    assert.ok(q.rows.some((x) => x.order === first.order));
    const status = p0.facets.statuses[0];
    const byStatus = await get(`/shipping/shipments?status=${status}&size=200`);
    assert.ok(byStatus.rows.every((x) => x.status === status));
    const ordered = await get('/shipping/shipments?sort=order&size=200');
    const nums = ordered.rows.map((x) => Number(x.order.replace(/\D/g, '')));
    assert.deepEqual(nums, [...nums].sort((x, y) => x - y));
    const oldest = (await get('/shipping/shipments?sort=oldest&size=200')).rows.map((x) => x.days);
    assert.deepEqual(oldest, [...oldest].sort((x, y) => y - x));
    const week = await get('/shipping/shipments?days=7&size=200');
    assert.ok(week.total < p0.total);
    const none = await get('/shipping/shipments?q=zzzz-nothing');
    assert.equal(none.total, 0);
    assert.equal(none.pages, 1);
});

test('order detail: timeline, items, city and state only, actions persist', async () => {
    const top = (await get('/shipping/shipments?size=1&cat=red')).rows[0];
    const d = await get(`/shipping/shipments/${encodeURIComponent(top.order)}`);
    const pkg = d.packages[0];
    assert.ok(pkg.events.length >= 2 && pkg.promisedAt && pkg.delayReason !== undefined && pkg.action && pkg.trackingId);
    assert.equal(pkg.action, 'Add to the urgent escalation list.');
    assert.ok(d.items.length && d.destination.city && d.destination.state && !('address' in d.destination));
    assert.ok(d.check && d.annotation && 'outcome' in d.annotation);
    const n = await note(top.order, { action: 'note', text: 'Called the carrier.' });
    assert.equal(n.annotation.notes[0].text, 'Called the carrier.');
    await note(top.order, { action: 'flag' });
    await note(top.order, { action: 'check' });
    const again = await get(`/shipping/shipments/${encodeURIComponent(top.order)}`);
    assert.ok(again.annotation.flagged && again.annotation.reviewedAt);
    const flagged = await get('/shipping/shipments?cat=flagged&size=200');
    assert.ok(flagged.rows.some((x) => x.order === top.order && x.flagged));
    const hand = (await get('/shipping/checks')).exceptions.rows[0];
    const hd = await get(`/shipping/shipments/${encodeURIComponent(hand.order)}`);
    assert.ok(hd.packages.some((p) => p.issues.length && p.action === p.issues.map((i) => i.detail).join(' ')));
    await assert.rejects(() => note(top.order, { action: 'note', text: '  ' }), /note/);
    await assert.rejects(() => get('/shipping/shipments/DEMO-nope'), /No shipment/);
});

test('analytics has what the page draws, including delivery performance', async () => {
    const s = await get('/shipping/summary');
    const a = await get('/shipping/analytics?period=30');
    assert.equal(a.kpis.active, s.activeTotal);
    assert.equal(a.kpis.handChecks, kpi(s, 'tracking_missing') + kpi(s, 'invalid') + kpi(s, 'checks'));
    assert.ok(!('stuck' in a.kpis));
    assert.deepEqual(a.aging.map((x) => x.key), SECTIONS);
    assert.equal(a.aging.reduce((t, x) => t + x.value, 0), s.activeTotal);
    assert.equal(a.stage.length, 2);
    assert.ok(a.carriersReport.scorecard.length && a.carriersReport.heatmap.length && a.insights.length);
    assert.ok(a.carriersReport.scorecard.every((c) => 'handChecks' in c && !('stuck' in c) && !('exceptions' in c)));
    assert.equal(a.carriersReport.scorecard.reduce((t, c) => t + c.active, 0), s.activeTotal);
    const d30 = a.delivery;
    const d90 = (await get('/shipping/analytics?period=90')).delivery;
    assert.equal(d30.period, 30);
    assert.equal(d90.period, 90);
    assert.ok(d90.delivered > d30.delivered && d30.delivered > 10);
    assert.ok(d30.onTimePct > 50 && d30.onTimePct <= 100);
    assert.equal(d30.distribution.reduce((t, x) => t + x.value, 0), d30.delivered);
    assert.equal(d30.byCarrier.reduce((t, x) => t + x.delivered, 0), d30.delivered);
    assert.ok(d30.trend.length >= 3 && d30.byRegion.length);
    assert.deepEqual(s.delivery30, { delivered: d30.delivered, onTimePct: d30.onTimePct, avgDays: d30.avgDays, withPromisedDate: d30.withPromisedDate });
});

test('exports and the import preview', async () => {
    for (const kind of ['escalation', 'shipments']) {
        const f = await demoDownload(`/shipping/export/${kind}?brand=ridhi`);
        assert.match(f.filename, /\.csv$/);
        const text = await f.blob.text();
        assert.ok(text.split('\r\n').length > 1, kind);
    }
    await assert.rejects(() => demoDownload('/shipping/export/verify'), /No demo data|not available/);
    await assert.rejects(() => get('/shipping/unfulfilled'), /No demo data/);
    const sample = await get('/shipping/import/sample');
    assert.ok(sample.carriers.length);
    const p = await demoRequest('POST', '/shipping/import/preview', { text: sample.text });
    assert.ok(p.previewOnly && p.counts.will_update > 0 && p.counts.error > 0);
    assert.equal(p.rows.length, Object.values(p.counts).reduce((a, b) => a + b, 0));
    await assert.rejects(() => demoRequest('POST', '/shipping/import/preview', { text: 'a,b\n1,2' }), /first row/);
    await assert.rejects(() => demoRequest('POST', '/shipping/import/preview', { text: '' }), /empty/);
});

test('shippingHomeSummary', async () => {
    resetDemo();
    const db = {};
    seed(db);
    const all = shippingHomeSummary(db);
    const r = shippingHomeSummary(db, 'ridhi');
    const c = shippingHomeSummary(db, 'cpc');
    assert.equal(r.active + c.active, all.active);
    for (const k of ['active', 'inTransit', 'delivered30d', 'problems', 'critical', 'handChecks']) assert.equal(typeof all[k], 'number', k);
    assert.equal(all.problems, all.critical + all.handChecks);
    assert.ok(all.delivered30d > 0 && all.asOf);
    assert.ok(all.top.length > 0 && all.top.length <= 4);
    assert.deepEqual(Object.keys(all.top[0]), ['order', 'brand', 'carrier', 'days', 'place', 'trackingId', 'label']);
    assert.ok(r.top.every((x) => x.brand === 'ridhi'));
    const s = await get('/shipping/summary');
    assert.equal(all.critical, s.critical);
    assert.equal(all.handChecks, kpi(s, 'tracking_missing') + kpi(s, 'invalid') + kpi(s, 'checks'));
});
