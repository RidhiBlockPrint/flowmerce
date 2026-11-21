// Run with: node --test tests/cro-batch3.test.mjs   (from the frontend folder; no packages needed)
// CRO batch 3 and the approved screens: Site health, Recommendations and Experiments under Advanced, recommendation
// status, experiments, the free-shipping amount, and the demo answers the new screens read (same shapes as the API).
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { TABS } from '../src/lib/cro.js';
import { NAV } from '../src/lib/routes.mjs';
import { demoRequest, resetDemo } from '../src/demo/index.js';

const get = (p) => demoRequest('GET', p);

test('Site health, Recommendations and Experiments sit under Advanced, on the page and in the menu', () => {
    const adv = TABS.filter((t) => t.advanced).map((t) => t.key);
    for (const k of ['site', 'recommendations', 'experiments']) assert.ok(adv.includes(k), k);
    assert.ok(!adv.includes('landing') && !adv.includes('overview'));
    const cro = NAV.find((e) => e.id === 'cro');
    assert.deepEqual(cro.advanced.slice(0, 3).map((i) => i.tab), ['site', 'recommendations', 'experiments']);
    assert.ok(cro.items.some((i) => i.tab === 'landing'));
});

test('recommendations are ranked by impact, and a status sticks', async () => {
    resetDemo();
    const r = await get('/cro/recommendations?brand=ridhi');
    const est = r.recommendations.filter((x) => x.impact !== null).map((x) => x.impact);
    assert.deepEqual(est, [...est].sort((a, b) => b - a));
    assert.equal(r.recommendations.at(-1).impact, null);   // checks without an estimate come last
    for (const x of r.recommendations) assert.ok(x.key && x.action && x.status === 'open' && Array.isArray(x.evidence_list), x.key);
    const key = r.recommendations[0].key;
    await demoRequest('POST', '/cro/recommendations/status?brand=ridhi', { key, status: 'done' });
    const again = await get('/cro/recommendations?brand=ridhi');
    assert.equal(again.recommendations.find((x) => x.key === key).status, 'done');
    assert.ok(again.total_open_impact < r.total_open_impact);
    await assert.rejects(demoRequest('POST', '/cro/recommendations/status?brand=ridhi', { key, status: 'finished' }), (e) => e.status === 400);
});

test('experiments: results, tiles, add, edit and delete', async () => {
    resetDemo();
    const list = await get('/cro/experiments?brand=ridhi');
    assert.equal(list.summary.total, 3);
    const states = Object.fromEntries(list.experiments.map((e) => [e.metric, e.result.state]));
    assert.deepEqual(states, { conversion_rate: 'running', aov: 'finished', bounce_rate: 'planned' });
    const running = list.experiments.find((e) => e.metric === 'conversion_rate').result;
    assert.ok(running.before_n > 0 && running.during_n > 0 && running.change_unit === 'pts');
    const made = await demoRequest('POST', '/cro/experiments?brand=ridhi', { name: 'Test', hypothesis: 'Lifts it', metric: 'aov', start_date: '2026-01-01', page_path: '/x' });
    assert.equal(made.page_path, null);   // order value is for the whole store
    const edited = await demoRequest('PATCH', `/cro/experiments/${made.id}?brand=ridhi`, { name: 'Test 2', hypothesis: 'Lifts it', metric: 'conversion_rate', start_date: '2026-01-01' });
    assert.equal(edited.name, 'Test 2');
    await demoRequest('DELETE', `/cro/experiments/${made.id}?brand=ridhi`);
    assert.equal((await get('/cro/experiments?brand=ridhi')).summary.total, 3);
    await assert.rejects(demoRequest('POST', '/cro/experiments?brand=ridhi', { name: '', hypothesis: 'x', metric: 'aov', start_date: '2026-01-01' }), (e) => e.status === 400);
});

test('the free-shipping amount is saved per store and marks the order values', async () => {
    resetDemo();
    await demoRequest('PATCH', '/cro/settings?brand=cpc', { free_shipping_threshold: 75 });
    assert.equal((await get('/cro/settings?brand=cpc')).free_shipping_threshold, 75);
    const c = await get('/cro/checkout-extras?brand=cpc');
    assert.equal(c.order_values.threshold, 75);
    assert.ok(c.order_values.bars.some((b) => b.near_threshold));
    assert.ok(c.previous_order_values && c.payments.previous_methods.length);
    await assert.rejects(demoRequest('PATCH', '/cro/settings?brand=cpc', { free_shipping_threshold: -1 }), (e) => e.status === 400);
});

test('the screens get the comparison days and the grid totals they draw', async () => {
    resetDemo();
    const conv = await get('/cro/conversion?brand=ridhi');
    assert.equal(conv.baseline_trend.length, conv.trend.length);
    const g = await get('/cro/landing-grids?brand=ridhi');
    const grid = g.page_by_source;
    assert.equal(grid.row_totals.length, grid.rows.length);
    assert.equal(grid.column_totals.length, grid.columns.length);
    for (const k of ['conversion_rate', 'added_to_cart_rate', 'bounce_rate']) assert.ok(k in grid.total, k);
});
