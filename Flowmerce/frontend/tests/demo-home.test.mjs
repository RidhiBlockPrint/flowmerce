// Run with: node --test tests/demo-home.test.mjs   (from the frontend folder; no packages needed)
// Home, the CEO view (layout "A · Bento", 2026-11-27): one dashboard for All, Ridhi and CPC, for a period. The sample
// GET /cro/home-period follows the same rules as the Python module (cro/company.py): one store passes through unchanged;
// both stores are added up (orders, sales, visits, checkouts, goals) and rates are worked out again from the sums,
// never averaged. The ads answers Home reads for the same days carry every field the page uses.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { demoRequest, resetDemo } from '../src/demo/index.js';

const get = (p) => demoRequest('GET', p);
const close = (a, b, tol = 0.011) => Math.abs(a - b) <= tol;
const isBlock = (b) => b && 'value' in b && 'baseline_value' in b && 'change_pct' in b;

test('one store: the CRO page’s own figures for the period', async () => {
    resetDemo();
    const h = await get('/cro/home-period?brand=ridhi&period=7d');
    const o = await get(`/cro/overview?brand=ridhi&from=${h.from}&to=${h.to}&compare=previous`);
    assert.deepEqual(h.brands, ['ridhi']);
    assert.deepEqual(h.metrics, o.metrics);
    assert.equal(h.by_brand.length, 0);
    for (const k of ['gross', 'discounts', 'returns', 'net', 'total']) assert.ok(h.breakdown.rows.some((r) => r.key === k), k);
});

test('both stores: counts and money added, rates worked out again from the sums', async () => {
    const h = await get('/cro/home-period?period=yesterday');
    const [r, c] = await Promise.all(['ridhi', 'cpc'].map((b) => get(`/cro/home-period?brand=${b}&period=yesterday`)));
    const m = h.metrics;
    assert.equal(m.orders.value, r.metrics.orders.value + c.metrics.orders.value);
    assert.ok(close(m.revenue.value, r.metrics.revenue.value + c.metrics.revenue.value));
    assert.ok(close(m.aov.value, m.revenue.value / m.orders.value));
    const sessions = r.metrics.conversion_rate.sessions + c.metrics.conversion_rate.sessions;
    assert.equal(m.conversion_rate.sessions, sessions);
    const on = (x) => x.days.find((d) => d.date === h.to);
    assert.ok(close(m.conversion_rate.value, ((on(r).completed_checkout + on(c).completed_checkout) / sessions) * 100), 'checkouts / visits');
    for (const row of h.breakdown.rows) {
        const add = [r, c].reduce((n, x) => n + x.breakdown.rows.find((y) => y.key === row.key).value, 0);
        assert.ok(close(row.value, add), row.key);
    }
    h.chart.current.forEach((d, i) => assert.equal(d.orders, r.chart.current[i].orders + c.chart.current[i].orders, d.date));
    assert.equal(h.chart.current.length, h.chart.previous.length);
    assert.ok(close(h.by_brand.reduce((n, b) => n + b.share, 0), 100, 0.05));
    assert.equal(h.goal.goal, r.goal.goal + c.goal.goal);
    assert.ok(close(h.goal.sales, r.goal.sales + c.goal.sales, 0.05));
});

test('every period answers, compared with the period before; today has no conversion yet', async () => {
    const expect = { today: 1, yesterday: 1, '7d': 7, '30d': 30 };
    for (const period of ['today', 'yesterday', '7d', '30d', 'mtd']) {
        const h = await get(`/cro/home-period?period=${period}`);
        const days = Math.round((Date.parse(h.to) - Date.parse(h.from)) / 864e5) + 1;
        if (expect[period]) assert.equal(days, expect[period], period);
        else assert.equal(h.from.slice(8), '01', 'month to date starts on the 1st');
        assert.ok(h.chart.current.length >= 14 && h.chart.current.at(-1).date === h.to, `${period} chart`);
        assert.equal(h.is_partial, h.to === h.today, period);
    }
    const t = await get('/cro/home-period?period=today');
    assert.equal(t.metrics.conversion_rate.value, null);
    await assert.rejects(get('/cro/home-period?period=week'), (e) => e.status === 400);
    await assert.rejects(get('/cro/home-period?brand=all'), (e) => e.status === 400);
});

test('the ads answers for the same days have every field Home reads', async () => {
    const h = await get('/cro/home-period?period=7d');
    const c = await get(`/ads/company?from=${h.from}&to=${h.to}`);
    for (const k of ['spend', 'mer_ex_bulk', 'cost_per_order']) assert.ok(isBlock(c.metrics[k]), k);
    for (const b of c.brands) {
        assert.ok(b.ready && b.targets.mer > 0 && b.gate_lines, b.brand);
        assert.ok(isBlock(b.metrics.mer_ex_bulk), b.brand);
    }
    assert.ok(c.platforms.length && close(c.platforms.reduce((n, p) => n + p.share_of_spend, 0), 100, 0.2), 'Meta and Google split');
    assert.ok(close(c.platforms.reduce((n, p) => n + p.spend, 0), c.metrics.spend.value, 0.05), 'the split adds up to the spend');
    assert.ok(c.trend.every((d) => 'spend' in d));
    const o = await get(`/ads/overview?brand=cpc&platform=all&from=${h.from}&to=${h.to}`);
    assert.ok(o.gate && !Array.isArray(o.brands), 'a brand overview is told apart from the company answer by its gate');
    for (const p of o.platforms) for (const k of ['spend', 'roas', 'share_of_spend']) assert.ok(k in p, `${p.platform} ${k}`);
});
