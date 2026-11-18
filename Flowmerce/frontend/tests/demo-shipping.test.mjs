// Run with: node --test tests/demo-shipping.test.mjs   (from the frontend folder; no packages needed)
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { demoRequest, demoDownload, resetDemo } from '../src/demo/index.js';
import { seed, shippingHomeSummary } from '../src/demo/modules/shipping.js';

const get = (p) => demoRequest('GET', p);
const kpi = (s, key) => s.kpis.find((k) => k.key === key).value;
const note = (order, body) => demoRequest('POST', `/shipping/shipments/${encodeURIComponent(order)}/note`, body);

test('summary, list and checks agree with each other', async () => {
    resetDemo();
    const s = await get('/shipping/summary');
    assert.equal(s.source.state, 'ok');
    assert.ok(s.activeTotal > 80 && s.delivered > 50);
    assert.equal(kpi(s, ''), s.activeTotal);
    assert.equal(s.stage.preDispatch + s.stage.dispatched, s.activeTotal);
    const all = await get('/shipping/shipments?size=200');
    assert.equal(all.total, s.activeTotal);
    for (const key of ['red', 'orange', 'yellow', 'grey', 'on_track', 'unconfirmed', 'nomove', 'exception']) {
        const l = await get(`/shipping/shipments?cat=${key}&size=200`);
        assert.equal(l.total, kpi(s, key), key);
    }
    const c = await get('/shipping/checks');
    assert.equal(c.verify.total, s.checks.toVerify);
    assert.equal(c.verify.missingTracking, s.checks.missingTracking);
    assert.equal(c.exceptions.counts.stuck, kpi(s, 'nomove'));
    assert.equal(c.exceptions.counts.carrier_exception, kpi(s, 'exception'));
    assert.equal(c.exceptions.counts.missing_tracking, c.verify.missingTracking);
    assert.equal(c.exceptions.total, c.exceptions.rows.length);
    assert.equal(s.exceptions, c.exceptions.total);
    assert.equal(Object.values(c.exceptions.counts).reduce((a, b) => a + b, 0), c.exceptions.total);
    assert.equal(c.mcf.rows.length, Object.values(c.mcf.counts).reduce((a, b) => a + b, 0));
    assert.deepEqual(s.checks.mcf, c.mcf.counts);
    assert.ok(c.exceptions.counts.duplicate_tracking > 0 && c.exceptions.counts.delivered_not_marked > 0);
    const v = c.verify.team;
    assert.equal(v.delivered + v.lost + v.failed + v.inTransit + v.notChecked, c.verify.total);
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
    const first = p0.rows[0];
    assert.ok(first.exception || first.noMove || first.cat === 'red');
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
    const stuck = await get('/shipping/shipments?sort=stuck&size=5');
    assert.ok(stuck.rows[0].noMove);
    const week = await get('/shipping/shipments?days=7&size=200');
    assert.ok(week.total < p0.total);
    const noscan = await get('/shipping/shipments?cat=noscan&size=200');
    assert.ok(noscan.rows.every((x) => !x.lastScanAt));
    const none = await get('/shipping/shipments?q=zzzz-nothing');
    assert.equal(none.total, 0);
    assert.equal(none.pages, 1);
});

test('order detail: timeline, items, city and state only, actions persist', async () => {
    const top = (await get('/shipping/shipments?size=1&cat=nomove')).rows[0];
    const d = await get(`/shipping/shipments/${encodeURIComponent(top.order)}`);
    const pkg = d.packages[0];
    assert.ok(pkg.events.length >= 2 && pkg.promisedAt && pkg.delayReason !== undefined && pkg.action);
    assert.ok(d.items.length && d.destination.city && d.destination.state && !('address' in d.destination));
    assert.ok(d.check && d.annotation);
    const n = await note(top.order, { action: 'note', text: 'Called the carrier.' });
    assert.equal(n.annotation.notes[0].text, 'Called the carrier.');
    await note(top.order, { action: 'flag' });
    await note(top.order, { action: 'check' });
    const again = await get(`/shipping/shipments/${encodeURIComponent(top.order)}`);
    assert.ok(again.annotation.flagged && again.annotation.reviewedAt);
    const flagged = await get('/shipping/shipments?cat=flagged&size=200');
    assert.ok(flagged.rows.some((x) => x.order === top.order && x.flagged));
    await assert.rejects(() => note(top.order, { action: 'note', text: '  ' }), /note/);
    await assert.rejects(() => get('/shipping/shipments/DEMO-nope'), /No shipment/);
});

test('analytics has what the page draws, including delivery performance', async () => {
    const s = await get('/shipping/summary');
    const a = await get('/shipping/analytics?period=30');
    assert.equal(a.kpis.active, s.activeTotal);
    assert.equal(a.aging.length, 6);
    assert.ok(a.carriersReport.scorecard.length && a.carriersReport.heatmap.length && a.insights.length);
    const d30 = a.delivery;
    const d90 = (await get('/shipping/analytics?period=90')).delivery;
    assert.equal(d30.period, 30);
    assert.equal(d90.period, 90);
    assert.ok(d90.delivered > d30.delivered && d30.delivered > 10);
    assert.ok(d30.onTimePct > 50 && d30.onTimePct <= 100);
    assert.equal(d30.distribution.reduce((t, x) => t + x.value, 0), d30.delivered);
    assert.equal(d30.byCarrier.reduce((t, x) => t + x.delivered, 0), d30.delivered);
    assert.ok(d30.trend.length >= 3 && d30.byRegion.length);
});

test('exports and the import preview', async () => {
    for (const kind of ['escalation', 'shipments', 'verify']) {
        const f = await demoDownload(`/shipping/export/${kind}?brand=ridhi`);
        assert.match(f.filename, /\.csv$/);
        const text = await f.blob.text();
        assert.ok(text.split('\r\n').length > 1, kind);
    }
    const sample = await get('/shipping/import/sample');
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
    assert.equal(r.total + c.total, all.total);
    for (const k of ['total', 'inTransit', 'delayed', 'red', 'delivered']) assert.equal(typeof all[k], 'number');
    assert.ok(all.onTimePct > 0 && all.asOf);
    assert.ok(all.topDelayed.length > 0 && all.topDelayed.length <= 4);
    assert.deepEqual(Object.keys(all.topDelayed[0]), ['order', 'brand', 'carrier', 'daysLate', 'customerCity']);
    assert.ok(r.topDelayed.every((x) => x.brand === 'ridhi'));
    const s = await get('/shipping/summary');
    assert.equal(all.red, s.critical);
});
