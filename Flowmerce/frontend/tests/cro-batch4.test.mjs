// Run with: node --test tests/cro-batch4.test.mjs   (from the frontend folder; no packages needed)
// CRO batch 4: the demo answers for the Products tab (Shopify sales and refunds, GA4 views, product groups, price
// bands, bought together) and the Sales tab's discount codes, in the same shapes as modules/cro/products.py.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { demoRequest, resetDemo } from '../src/demo/index.js';

const get = (p) => demoRequest('GET', p);
const GROUPS = ['star', 'hidden_gem', 'leaky', 'dead_weight'];

test('product insights: Shopify sales, GA4 views and the four groups for a store with enough GA4 days', async () => {
    resetDemo();
    const r = await get('/cro/product-insights?brand=ridhi');
    assert.equal(r.views.state, 'ready');
    assert.equal(r.sales_source, 'shopify');
    assert.ok(r.window.from && r.window.to);
    for (const p of r.products) {
        for (const k of ['product_id', 'name', 'category', 'orders', 'items', 'net_sales', 'views', 'add_to_cart_rate', 'conversion_rate', 'group']) assert.ok(k in p, k);
    }
    const sales = r.products.map((p) => p.net_sales);
    assert.deepEqual(sales, [...sales].sort((a, b) => b - a));
    assert.deepEqual(r.groups.groups.map((g) => g.group), GROUPS);
    assert.equal(r.groups.groups.reduce((a, g) => a + g.products, 0), r.products.filter((p) => p.group).length);
    const left = r.groups.fix_first.map((f) => f.left_on_table);
    assert.deepEqual(left, [...left].sort((a, b) => b - a));
    assert.ok(r.groups.fix_first.every((f) => r.products.find((p) => p.product_id === f.product_id).group === 'leaky'));
    assert.ok(r.products.some((p) => p.views && !p.orders));   // viewed but never bought
});

test('product insights: a store still collecting GA4 days shows no groups, but sales, refunds, bands and baskets', async () => {
    resetDemo();
    const r = await get('/cro/product-insights?brand=cpc');
    assert.equal(r.views.state, 'collecting');
    assert.ok(r.views.days < 7 && r.views.message.includes('once it has 7'));
    assert.equal(r.groups, null);
    assert.ok(r.products.every((p) => p.group === null));
    assert.ok(r.refunds.store_refund_rate > 0 && r.refunds.by_rate.every((x) => x.gross_sales >= r.refunds.min_gross_sales));
    assert.ok(r.price_bands.length && r.price_bands.every((b) => b.conversion_rate === null));
    assert.ok(r.bought_together.rows.every((x) => x.orders_together >= r.bought_together.min_orders_together));
});

test('discount codes: with vs without a code add up to all orders, with the comparison', async () => {
    resetDemo();
    const d = await get('/cro/discount-codes?brand=ridhi');
    assert.equal(d.with_code.orders + d.without_code.orders, d.total_orders);
    assert.ok(d.codes.length && d.code_count >= d.codes.length);
    for (const c of d.codes) for (const k of ['code', 'orders', 'aov', 'discount_given', 'discount_pct', 'share_of_orders']) assert.ok(k in c, k);
    assert.ok(d.previous && d.previous.with_code.orders > 0);
});

test('leaky products join the impact-ranked recommendations', async () => {
    resetDemo();
    const r = await get('/cro/recommendations?brand=ridhi');
    const leaky = r.recommendations.filter((x) => x.key.startsWith('product_leaky:'));
    assert.ok(leaky.length >= 1);
    assert.ok(leaky.every((x) => x.area === 'Products' && x.impact > 0 && x.evidence_list.length === 3));
    const est = r.recommendations.filter((x) => x.impact !== null).map((x) => x.impact);
    assert.deepEqual(est, [...est].sort((a, b) => b - a));
    const cpc = await get('/cro/recommendations?brand=cpc');
    assert.ok(!cpc.recommendations.some((x) => x.key.startsWith('product_leaky:')));
});
