// Run with: node --test tests/demo-ads.test.mjs   (from the frontend folder; no packages needed)
// The Ads sample data (src/demo/modules/ads.js) and the page helpers (src/lib/ads.js): every screen's answer has the
// fields the page reads, the figures agree with each other, and the Rules tab really changes them.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { demoRequest, resetDemo } from '../src/demo/index.js';
import { DEFAULT_RANGE, filterAds, filterCampaigns, platformFor, ratioTone, sortRows, tabsFor } from '../src/lib/ads.js';
import { presetRange } from '../src/lib/cro.js';

const get = (p) => demoRequest('GET', p);
const close = (a, b, tol = 0.02) => Math.abs(a - b) <= tol * Math.max(1, Math.abs(b));

test('every Ads endpoint answers for both brands and every platform', async () => {
    resetDemo();
    for (const brand of ['ridhi', 'cpc']) {
        for (const p of ['/ads/settings', '/ads/gap', '/ads/rules', '/ads/creatives', '/ads/search-terms']) assert.ok(await get(`${p}?brand=${brand}`), `${p} ${brand}`);
        for (const platform of ['all', 'meta', 'google'])
            for (const p of ['/ads/overview', '/ads/campaigns', '/ads/funnel', '/ads/actions']) assert.ok(await get(`${p}?brand=${brand}&platform=${platform}`), `${p} ${brand} ${platform}`);
    }
});

test('one brand at a time: an unknown or combined brand is refused', async () => {
    await assert.rejects(get('/ads/overview?brand=all'), (e) => e.status === 400);
    await assert.rejects(get('/ads/overview'), (e) => e.status === 400);
});

test('the sample data never shows a real ad account name', async () => {
    for (const brand of ['ridhi', 'cpc']) {
        const s = await get(`/ads/settings?brand=${brand}`);
        for (const a of s.accounts) assert.match(a.name, /^Demo /);
    }
});

test('overview: MER is store sales over all ad spend, and platform sales are never added together', async () => {
    resetDemo();
    const all = await get('/ads/overview?brand=ridhi&platform=all');
    const m = all.metrics;
    assert.ok(close(m.mer.value, m.sales.value / m.total_spend.value));
    assert.ok(close(m.mer_ex_bulk.value, m.sales_ex_bulk.value / m.total_spend.value));
    assert.ok(!('roas' in m) && !('value' in m), 'no combined ROAS or combined claimed sales');
    assert.equal(all.platforms.length, 2);
    assert.ok(close(all.platforms.reduce((s, p) => s + p.spend, 0), m.spend.value, 0.001));
    const meta = await get('/ads/overview?brand=ridhi&platform=meta');
    assert.ok(close(meta.metrics.roas.value, meta.metrics.value.value / meta.metrics.spend.value));
    assert.ok(close(meta.metrics.total_spend.value, m.total_spend.value, 0.001), 'MER always uses all ad spend');
    assert.ok(['green', 'amber', 'red'].includes(all.gate.state));
    assert.ok(all.trend.length >= 14 && all.trend.every((d) => d.date && 'mer_ex_bulk' in d));
});

test('a bulk order counts in store sales but not in the excl. bulk figures; raising the limit puts it back', async () => {
    resetDemo();
    const wide = await get('/ads/overview?brand=ridhi&platform=all&from=2000-01-01&to=2099-12-31').catch(() => null);
    assert.equal(wide, null, 'a range of more than 366 days is refused');
    const s = await get('/ads/settings?brand=ridhi');
    const y = s.today;
    const from = new Date(Date.parse(`${y}T00:00:00Z`) - 14 * 864e5).toISOString().slice(0, 10);
    const to = new Date(Date.parse(`${y}T00:00:00Z`) - 864e5).toISOString().slice(0, 10);
    const o = await get(`/ads/overview?brand=ridhi&from=${from}&to=${to}`);
    assert.equal(o.bulk.orders, 1);
    assert.ok(close(o.metrics.sales.value - o.metrics.sales_ex_bulk.value, o.bulk.amount, 0.001));
    await demoRequest('PATCH', '/ads/rules?brand=ridhi', { bulk_order_min: 100000 });
    const after = await get(`/ads/overview?brand=ridhi&from=${from}&to=${to}`);
    assert.equal(after.bulk.orders, 0);
    assert.equal(after.metrics.sales.value, after.metrics.sales_ex_bulk.value);
    resetDemo();
});

test('the rupee rate changes Ridhi\'s Meta figures in dollars, and is refused when out of range', async () => {
    resetDemo();
    const before = await get('/ads/overview?brand=ridhi&platform=meta');
    await demoRequest('PATCH', '/ads/rules?brand=ridhi', { fx_rate: 95 });
    const after = await get('/ads/overview?brand=ridhi&platform=meta');
    assert.ok(close(after.metrics.spend.value, before.metrics.spend.value * 88 / 95, 0.001));
    assert.ok(close(after.metrics.roas.value, before.metrics.roas.value, 0.01), 'ROAS does not depend on the rate');
    assert.equal((await get('/ads/rules?brand=ridhi')).rules.fx_from, (await get('/ads/settings?brand=ridhi')).today);
    await assert.rejects(demoRequest('PATCH', '/ads/rules?brand=ridhi', { fx_rate: 0 }), (e) => e.status === 400);
    await assert.rejects(demoRequest('PATCH', '/ads/rules?brand=ridhi', { nonsense: 1 }), (e) => e.status === 400);
    await assert.rejects(demoRequest('PATCH', '/ads/rules?brand=ridhi', { cbo_min_ads: 9, cbo_max_ads: 8 }), (e) => e.status === 400);
    resetDemo();
});

test('creatives: every ad has a known verdict with a reason, and the test-spend rule is followed', async () => {
    resetDemo();
    const d = await get('/ads/creatives?brand=ridhi');
    assert.ok(d.ads.length > 30);
    const known = new Set(['scale', 'graduate', 'hold', 'iterate', 'stop', 'continue', 'testing']);
    for (const a of d.ads) {
        assert.ok(known.has(a.verdict), a.verdict);
        assert.ok(a.reason.length > 10);
        if (a.lifetime.spend < 110) assert.equal(a.verdict, 'testing', a.name);
        if (a.lifetime.spend >= 110 && a.lifetime.purchases === 0) assert.equal(a.verdict, 'stop', a.name);
        if (a.video) assert.ok(a.video.hook_rate >= 0 && a.video.hook_rate <= 100);
        else assert.equal(a.format, 'image');
    }
    const counts = Object.values(d.counts).reduce((s, n) => s + n, 0);
    assert.equal(counts, d.ads.length);
    assert.ok(d.winners.every((id) => d.ads.some((a) => a.id === id)));
});

test('a stricter stop line turns more ads into "stop"', async () => {
    resetDemo();
    const stops = async () => (await get('/ads/creatives?brand=cpc')).ads.filter((a) => a.verdict === 'stop').length;
    const before = await stops();
    await demoRequest('PATCH', '/ads/rules?brand=cpc', { stop_roas: 2.1 });
    assert.ok(await stops() > before);
    resetDemo();
});

test('CBO health and budget calls follow the rules; ABO campaigns have no single budget', async () => {
    resetDemo();
    const d = await get('/ads/campaigns?brand=ridhi&platform=meta');
    const cbos = d.campaigns.filter((c) => c.type === 'cbo');
    assert.ok(cbos.length >= 2 && cbos.every((c) => c.health && c.health.call));
    for (const c of cbos) {
        const { call } = c.health;
        if (call.key === 'increase') assert.ok(call.new_budget > c.daily_budget);
        if (call.key === 'decrease') assert.ok(call.new_budget < c.daily_budget);
    }
    assert.ok(cbos.some((c) => /72 hours/.test(c.health.call.why)), 'a budget changed recently is held');
    assert.ok(d.campaigns.filter((c) => c.type === 'abo').every((c) => c.daily_budget === null && c.health === null));
    const g = await get('/ads/campaigns?brand=ridhi&platform=google');
    assert.ok(g.campaigns.length && g.campaigns.every((c) => c.platform === 'google'));
    assert.ok(g.campaigns.some((c) => c.is_brand));
});

test('gap: an ad marked "add" passes the proven rule and is not already in the scaling campaign', async () => {
    resetDemo();
    const g = await get('/ads/gap?brand=ridhi');
    assert.equal(g.missing, g.pairs.reduce((s, p) => s + p.rows.filter((r) => r.verdict === 'add').length, 0));
    for (const p of g.pairs) for (const r of p.rows.filter((x) => x.verdict === 'add')) {
        assert.ok(p.scale_campaign);
        assert.ok(r.roas >= g.rule.roas && r.purchases >= g.rule.purchases && r.spend >= g.rule.spend, r.name);
    }
    assert.ok(g.pairs.some((p) => p.rows.some((r) => r.verdict === 'already')));
});

test('actions can be marked done, skipped and reopened, and each change is in the history', async () => {
    resetDemo();
    const d = await get('/ads/actions?brand=cpc');
    assert.ok(d.actions.length > 0 && d.actions.every((a) => a.status === 'open'));
    const a = d.actions[0];
    await demoRequest('PATCH', `/ads/actions/${encodeURIComponent(a.id)}?brand=cpc`, { status: 'done' });
    let now = await get('/ads/actions?brand=cpc');
    assert.equal(now.actions.find((x) => x.id === a.id).status, 'done');
    assert.equal(now.open, d.open - 1);
    assert.equal(now.history[0].status, 'done');
    await demoRequest('PATCH', `/ads/actions/${encodeURIComponent(a.id)}?brand=cpc`, { status: 'open' });
    now = await get('/ads/actions?brand=cpc');
    assert.equal(now.actions.find((x) => x.id === a.id).status, 'open');
    assert.equal(now.history.length, 2);
    await assert.rejects(demoRequest('PATCH', `/ads/actions/${encodeURIComponent(a.id)}?brand=cpc`, { status: 'maybe' }), (e) => e.status === 400);
    await assert.rejects(demoRequest('PATCH', '/ads/actions/nope?brand=cpc', { status: 'done' }), (e) => e.status === 404);
    assert.equal((await get('/ads/actions?brand=cpc&platform=google')).actions.length, 0, 'no Google rules are agreed yet');
    resetDemo();
});

test('funnel and search terms: Google has the short funnel, brand searches are marked', async () => {
    const f = await get('/ads/funnel?brand=ridhi&platform=all');
    assert.equal(f.meta.steps.length, 6);
    assert.deepEqual(f.google.steps.map((s) => s.key), ['impressions', 'clicks', 'purchases']);
    assert.equal((await get('/ads/funnel?brand=ridhi&platform=google')).meta, null);
    const s = await get('/ads/search-terms?brand=ridhi');
    assert.ok(s.keywords.some((k) => k.is_brand) && s.terms.some((t) => !t.is_brand) && s.products.length);
    assert.ok(s.brand_share.value <= s.brand_share.total_value);
});

test('the same day always shows the same figures', async () => {
    resetDemo();
    const a = await get('/ads/overview?brand=cpc');
    resetDemo();
    const b = await get('/ads/overview?brand=cpc');
    assert.deepEqual(a.metrics, b.metrics);
});

/* ------------------------------------------------------------------ page helpers */
test('a one-platform tab is hidden while the other platform is chosen, and forces its own platform', () => {
    const keys = (p) => tabsFor(p).map((t) => t.key);
    assert.ok(keys('all').includes('creatives') && keys('all').includes('search'));
    assert.ok(!keys('google').includes('creatives') && !keys('google').includes('gap'));
    assert.ok(!keys('meta').includes('search'));
    assert.equal(platformFor('creatives', 'google'), 'meta');
    assert.equal(platformFor('creatives', 'all'), 'all');
    assert.equal(platformFor('overview', 'nonsense'), 'all');
});

test('the default range is the last 7 complete days, picked with the shared date picker keys', () => {
    assert.equal(DEFAULT_RANGE, 'last-7-days');
    assert.deepEqual(presetRange(DEFAULT_RANGE, '2026-11-24'), { from: '2026-11-17', to: '2026-11-23' });
});

test('the demo answers every comparison the "Compare to" menu offers', async () => {
    resetDemo();
    const s = await get('/ads/settings?brand=cpc');
    const y = new Date(Date.parse(`${s.today}T00:00:00Z`) - 864e5).toISOString().slice(0, 10);
    const d = (n) => new Date(Date.parse(`${y}T00:00:00Z`) - n * 864e5).toISOString().slice(0, 10);
    const ask = (q) => get(`/ads/overview?brand=cpc&from=${d(6)}&to=${y}${q}`);
    assert.equal((await ask('')).compare.from, d(13));
    assert.equal((await ask('&compare=previous_year_dow')).compare.from, d(370));
    assert.equal((await ask('&compare=previous_year')).compare.from.slice(0, 4), String(Number(d(6).slice(0, 4)) - 1));
    const custom = await ask(`&compare=custom&cfrom=${d(40)}`);
    assert.equal(custom.compare.from, d(40));
    assert.equal(custom.compare.to, d(34));
    assert.equal((await ask('&compare=none')).compare, null);
    await assert.rejects(ask(`&compare=custom&cfrom=${d(2)}`), (e) => e.status === 400);
});

test('sorting puts empty values last; filters combine', () => {
    const rows = [{ n: 'a', v: 2 }, { n: 'b', v: null }, { n: 'c', v: 5 }];
    assert.deepEqual(sortRows(rows, 'v', 'desc').map((r) => r.n), ['c', 'a', 'b']);
    assert.deepEqual(sortRows(rows, 'v', 'asc').map((r) => r.n), ['a', 'c', 'b']);
    const ads = [
        { id: '1', name: 'DM1 | Hook', code: 'DM1', campaign: 'X', ad_set: 's', verdict: 'stop', campaign_id: 'x', product_line: 'quilt', format: 'video', status: 'ACTIVE', spend: 50, is_new: true, lifetime: { purchases: 0 } },
        { id: '2', name: 'DM2 | Other', code: 'DM2', campaign: 'Y', ad_set: 's', verdict: 'scale', campaign_id: 'y', product_line: 'round', format: 'image', status: 'PAUSED', spend: 500, is_new: false, lifetime: { purchases: 9 } },
    ];
    assert.deepEqual(filterAds(ads, { q: 'dm2' }).map((a) => a.id), ['2']);
    assert.deepEqual(filterAds(ads, { status: 'active', minSpend: 10 }).map((a) => a.id), ['1']);
    assert.deepEqual(filterAds(ads, { view: 'new' }).map((a) => a.id), ['1']);
    assert.deepEqual(filterAds(ads, { view: 'tests' }).map((a) => a.id), ['1']);
    assert.deepEqual(filterAds(ads, { view: 'winners' }, ['2']).map((a) => a.id), ['2']);
    assert.deepEqual(filterAds(ads, { line: 'round', format: 'video' }), []);
    assert.deepEqual(filterCampaigns([{ name: 'CBO A', type: 'cbo', product_line: 'quilt', status: 'ACTIVE' }, { name: 'ABO B', type: 'abo', product_line: 'quilt', status: 'PAUSED' }], { type: 'abo' }).map((c) => c.name), ['ABO B']);
});

test('a ratio is green at its target, amber close below, red further below', () => {
    assert.equal(ratioTone(2.2, 2.2), 'ok');
    assert.equal(ratioTone(1.7, 2.2), 'warn');
    assert.equal(ratioTone(1.0, 2.2), 'crit');
    assert.equal(ratioTone(null, 2.2), '');
    assert.equal(ratioTone(3, null), '');
});
