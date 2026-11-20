// Run with: node --test tests/demo-cro.test.mjs   (from the frontend folder; no packages needed)
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { demoRequest, resetDemo } from '../src/demo/index.js';

const get = (p) => demoRequest('GET', p);

test('overview has the four KPI blocks and respects the too-early rule', async () => {
    resetDemo();
    for (const period of ['yesterday', 'today', 'last7']) {
        const o = await get(`/cro/overview?brand=ridhi&period=${period}`);
        for (const k of ['orders', 'revenue', 'aov', 'conversion_rate']) assert.ok(k in o.metrics, `${period} ${k}`);
        for (const b of Object.values(o.metrics)) if (b.too_early) assert.equal(b.change_pct, null);
        assert.equal(o.order_data.first_load_complete, true);
    }
    const today = await get('/cro/overview?brand=ridhi&period=today');
    assert.equal(today.metrics.conversion_rate.value, null);      // sessions only exist for complete days
});

test('sales trend lines up the two periods and the breakdown adds up', async () => {
    const t = await get('/cro/sales-trend?brand=ridhi&days=14');
    assert.equal(t.current.length, 14);
    assert.equal(t.previous.length, 14);
    const b = await get('/cro/sales-breakdown?brand=ridhi');
    const v = Object.fromEntries(b.rows.map((r) => [r.key, r.value]));
    assert.ok(Math.abs(v.gross - v.discounts - (v.net + v.returns)) < 0.05);
});

test('one store at a time: an unknown brand is refused', async () => {
    await assert.rejects(get('/cro/overview?brand=all'), (e) => e.status === 400);
});

test('alarm rules can be added, changed and switched off; bad thresholds are refused', async () => {
    resetDemo();
    const rule = await demoRequest('POST', '/cro/alarms?brand=cpc', { kind: 'no_product_orders', title: 'No tablecloth orders', threshold: 24, product_keyword: 'tablecloth' });
    assert.equal(rule.store, 'CPC');
    await assert.rejects(demoRequest('POST', '/cro/alarms?brand=cpc', { kind: 'no_product_orders', title: 'x', threshold: 5, product_keyword: 'Tablecloth' }), (e) => e.status === 409);
    await demoRequest('PATCH', `/cro/alarms/${rule.id}?brand=cpc`, { is_active: false, threshold: 36 });
    const after = (await get('/cro/alarms?brand=cpc')).rules.find((r) => r.id === rule.id);
    assert.equal(after.is_active, false);
    assert.equal(after.threshold, 36);
    await assert.rejects(demoRequest('PATCH', '/cro/alarms/1?brand=ridhi', { threshold: 150 }), (e) => e.status === 400);
    await assert.rejects(demoRequest('PATCH', '/cro/alarms/1?brand=cpc', { threshold: 10 }), (e) => e.status === 404);   // rule 1 is Ridhi's
});

test('change log entries are added and removed per store', async () => {
    resetDemo();
    const e = await demoRequest('POST', '/cro/change-log?brand=ridhi', { change: 'New banner', area: 'theme', entry_date: '2026-11-19' });
    assert.ok((await get('/cro/change-log?brand=ridhi&days=365')).entries.some((x) => x.id === e.id));
    assert.ok(!(await get('/cro/change-log?brand=cpc&days=365')).entries.some((x) => x.id === e.id));
    await assert.rejects(demoRequest('DELETE', `/cro/change-log/${e.id}?brand=cpc`), (x) => x.status === 404);
    await demoRequest('DELETE', `/cro/change-log/${e.id}?brand=ridhi`);
    await assert.rejects(demoRequest('POST', '/cro/change-log?brand=ridhi', { change: '  ' }), (x) => x.status === 400);
});

const iso = (d) => d.toISOString().slice(0, 10);
const daysAgoIso = (n) => iso(new Date(Date.now() - n * 864e5));

test('any calendar range works, with each comparison', async () => {
    resetDemo();
    const from = daysAgoIso(15);
    const to = daysAgoIso(2);
    for (const compare of ['previous', 'last_week', 'none']) {
        const o = await get(`/cro/overview?brand=ridhi&from=${from}&to=${to}&compare=${compare}`);
        assert.equal(o.from, from);
        assert.equal(o.to, to);
        assert.equal(o.compare, compare);
        if (compare === 'none') assert.equal(o.metrics.orders.baseline_value, null);
        else assert.ok(o.metrics.orders.baseline_value > 0, compare);
    }
    const t = await get(`/cro/sales-trend?brand=ridhi&from=${from}&to=${to}`);
    assert.equal(t.current.length, 14);
    assert.equal(t.previous.length, 14);
    assert.ok(t.current.every((d) => 'net' in d));
    const c = await get(`/cro/conversion?brand=ridhi&from=${from}&to=${to}`);
    assert.equal(c.trend.length, 14);
    assert.ok(c.total.sessions > 0 && c.baseline_total.sessions > 0);
    const one = await get(`/cro/overview?brand=cpc&from=${to}&to=${to}`);
    assert.equal(one.compare, '4week_avg');                       // a single complete day: same weekday average
    await assert.rejects(get(`/cro/overview?brand=ridhi&from=${to}&to=${from}`), (e) => e.status === 400);
});

test('home shows both stores separately with yesterday, today and 14 days', async () => {
    const h = await get('/cro/home');
    assert.deepEqual(h.stores.map((s) => s.brand), ['ridhi', 'cpc']);
    for (const s of h.stores) {
        assert.equal(s.state, 'ok');
        assert.ok(s.yesterday.orders.value > 0 && s.yesterday.net_sales.value > 0);
        assert.ok('orders' in s.today && 'net_sales' in s.today);
        assert.equal(s.trend.length, 14);
    }
    assert.deepEqual((await get('/cro/home?brand=cpc')).stores.map((s) => s.brand), ['cpc']);
});
