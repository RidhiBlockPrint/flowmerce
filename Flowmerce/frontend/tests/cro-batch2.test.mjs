// Run with: node --test tests/cro-batch2.test.mjs   (from the frontend folder; no packages needed)
// CRO batch 2: the display helpers for landing pages, site health, payments and the best-hours grid (src/lib/cro.js),
// and the demo answers for the new /api/cro/... routes (same shapes as modules/cro/api.py).
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { RATING, TABS, VITALS, bestHours, fmtHour, fmtVital, heatLevel, readable } from '../src/lib/cro.js';
import { demoRequest, resetDemo } from '../src/demo/index.js';

const get = (p) => demoRequest('GET', p);

test('vitals read the way people say them', () => {
    assert.equal(fmtVital('lcp', 1416), '1.42 s');
    assert.equal(fmtVital('inp', 128.4), '128 ms');
    assert.equal(fmtVital('cls', 0.123), '0.12');
    assert.equal(fmtVital('lcp', null), '—');
    assert.deepEqual(VITALS.map((v) => v.key), ['lcp', 'inp', 'cls']);
    assert.ok(RATING.good && RATING.needs_improvement && RATING.poor);
});

test("Shopify's machine labels become words", () => {
    assert.equal(readable('shopify_pay'), 'Shop Pay');
    assert.equal(readable('credit_card'), 'Credit card');
    assert.equal(readable('social'), 'Social');
    assert.equal(readable(''), 'Other');
    assert.equal(readable(null), 'Other');
});

test('heat levels compare a cell with the average; too few visits stay blank', () => {
    assert.equal(heatLevel(null, 2), null);
    assert.equal(heatLevel(2, 0), null);
    assert.deepEqual([0.5, 1.5, 2, 2.8, 4].map((v) => heatLevel(v, 2)), [0, 1, 2, 3, 4]);
});

test('best hours skip cells without a rate and break ties by visits', () => {
    const cells = [
        { weekday: 0, hour: 9, cvr: 3, sessions: 50 },
        { weekday: 1, hour: 20, cvr: 3, sessions: 90 },
        { weekday: 2, hour: 3, cvr: null, sessions: 4 },
        { weekday: 3, hour: 12, cvr: 1, sessions: 400 },
    ];
    assert.deepEqual(bestHours(cells, 2).map((c) => c.weekday), [1, 0]);
    assert.deepEqual(bestHours(undefined), []);
    assert.equal(fmtHour(7), '07:00');
});

test('the new tabs are on the CRO page', () => {
    const keys = TABS.map((t) => t.key);
    assert.ok(keys.includes('landing') && keys.includes('site'));
    assert.ok(keys.indexOf('landing') < keys.indexOf('checkout'));
});

test('demo answers every new route with the API shapes', async () => {
    resetDemo();
    const rel = (p) => get(`${p}?brand=ridhi`);
    const moved = await rel('/cro/traffic-changes');
    assert.ok(Array.isArray(moved.device) && Array.isArray(moved.channel) && moved.movers.length <= 3);
    assert.ok(moved.channel.every((r) => 'revenue_per_session' in r));
    const geo = await rel('/cro/geo');
    assert.ok(geo.countries.length && geo.us_states.length);
    const landing = await rel('/cro/landing-pages');
    assert.ok(landing.pages.some((p) => p.bounce_flag), 'one page is flagged so the warning shows in demo');
    const grids = await rel('/cro/landing-grids');
    assert.equal(grids.page_by_source.cells.length, grids.page_by_source.rows.length);
    const site = await rel('/cro/site-health');
    assert.ok(site.devices.Mobile.lcp.rating && site.search.top_terms.length);
    const trends = await rel('/cro/overview-trends');
    assert.ok(trends.aov.length && trends.channels.length);
    const extras = await rel('/cro/checkout-extras');
    assert.equal(extras.order_values.bars.length, 13);
    assert.ok(extras.payments.methods.length && extras.order_values.items.bars.length === 5);
    const heat = await get('/cro/buy-heatmap?brand=cpc&days=28');
    assert.equal(heat.cells.length, 7 * 24);
    assert.equal(heat.days, 28);
});

test('demo conversion has the device funnel and the overview has the visit tiles', async () => {
    resetDemo();
    const c = await get('/cro/conversion?brand=ridhi');
    assert.equal(c.funnel.all.sessions, c.total.sessions);
    assert.deepEqual(c.funnel.all.steps.map((s) => s.key), ['viewed_product', 'added_to_cart', 'reached_checkout', 'completed_checkout']);
    assert.ok(c.funnel.devices.length === 3 && c.baseline_funnel);
    const o = await get('/cro/overview?brand=ridhi&period=last7');
    assert.ok(o.metrics.sessions && o.metrics.revenue_per_session);
    const today = await get('/cro/overview?brand=ridhi&period=today');
    assert.equal(today.metrics.revenue_per_session, undefined);   // today has revenue but no visits yet
});
