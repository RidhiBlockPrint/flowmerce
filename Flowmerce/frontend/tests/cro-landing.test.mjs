// Run with: node --test tests/cro-landing.test.mjs   (from the frontend folder; no packages needed)
// CRO landing pages (2026-11-23): the demo answers for week / month compare, funnel by page, date-wise, one page's
// deep dive and the store notes, in the same shapes as modules/cro/landing_detail.py and ai_advice.py.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { demoRequest, resetDemo } from '../src/demo/index.js';

const get = (p) => demoRequest('GET', p);
const STEPS = ['viewed_product', 'added_to_cart', 'reached_checkout', 'completed_checkout'];

test('week / month compare: every page with both periods and the change', async () => {
    resetDemo();
    for (const mode of ['week', 'month']) {
        const r = await get(`/cro/landing-compare?brand=ridhi&mode=${mode}`);
        assert.equal(r.mode, mode);
        assert.ok(r.current.from && r.previous.to < r.current.from);
        assert.ok(r.pages.length >= 5);
        const p = r.pages[0];
        for (const k of ['sessions', 'bounce_rate', 'added_to_cart_rate', 'conversion_rate', 'orders', 'revenue', 'revenue_per_session']) assert.ok(k in p.now && k in p.before, k);
        assert.equal(p.change.sessions, p.now.sessions - p.before.sessions);
        if (mode === 'week') assert.ok(r.pages.some((x) => x.low_data));   // /pages/about has too few visits in a week
    }
});

test('funnel by page: each step with its share of visits and of the step before', async () => {
    resetDemo();
    const r = await get('/cro/landing-funnel?brand=ridhi&mode=week');
    const p = r.pages.find((x) => x.path === '/products/demo-indigo-quilt');
    assert.deepEqual(p.now.steps.map((s) => s.key), STEPS);
    assert.equal(p.now.steps[0].count, p.now.sessions);   // a product page is a product view
    const counts = p.now.steps.map((s) => s.count);
    assert.ok(counts.every((c, i) => !i || c <= counts[i - 1]));   // the funnel only narrows
    assert.ok(STEPS.every((k) => k in p.step_change_pts));
});

test('date-wise: the busiest pages by default, chosen pages when asked', async () => {
    resetDemo();
    const r = await get('/cro/landing-daily?brand=cpc');
    assert.ok(r.pages.length >= 5 && r.choices.length >= r.pages.length);
    assert.equal(r.pages[0].path, r.choices[0].path);
    assert.equal(r.pages[0].rows.length, 60);
    const picked = await get('/cro/landing-daily?brand=cpc&paths=/,/collections/sale&days=14');
    assert.deepEqual(picked.pages.map((p) => p.path), ['/', '/collections/sale']);
    assert.equal(picked.pages[0].rows.length, 14);
});

test("one page's deep dive: week and month, days, sources, devices, funnel, what changed (no countries)", async () => {
    resetDemo();
    const d = await get('/cro/landing-page?brand=ridhi&path=/collections/quilts');
    assert.equal(d.daily.length, 60);
    assert.equal(d.week.now.sessions, d.daily.slice(-7).reduce((a, r) => a + r.sessions, 0));
    for (const k of ['sources_week', 'sources_month', 'devices_week', 'devices_month']) assert.ok(d[k].length, k);
    assert.equal(d.countries, undefined);   // removed on 2026-11-24
    for (const mode of ['week', 'month']) {
        const f = d.funnel[mode];
        assert.deepEqual(f.now.all.steps.map((s) => s.key), STEPS);
        assert.deepEqual(f.now.devices.map((x) => x.label), ['Mobile', 'Desktop', 'Tablet']);
        assert.ok(f.before.all.sessions > 0);
    }
    assert.ok(d.what_changed.length);
    await assert.rejects(get('/cro/landing-page?brand=ridhi&path=/nope'), (e) => e.status === 400);
});

test('store notes are kept per store and limited in length', async () => {
    resetDemo();
    assert.equal((await get('/cro/store-notes?brand=ridhi')).text, '');
    const saved = await demoRequest('PUT', '/cro/store-notes?brand=ridhi', { text: '  Reviews app is on.  ' });
    assert.equal(saved.text, 'Reviews app is on.');
    assert.equal((await get('/cro/store-notes?brand=cpc')).text, '');
    await assert.rejects(demoRequest('PUT', '/cro/store-notes?brand=ridhi', { text: 'x'.repeat(3001) }), (e) => e.status === 400);
});
