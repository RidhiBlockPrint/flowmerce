// Run with: node --test tests/cro-dates.test.mjs   (from the frontend folder; no packages needed)
// The CRO date picker's ranges and comparisons (src/lib/cro.js, 2026-11-24): Shopify's presets, "Last N" in days,
// weeks, months, quarters and years, period to date, Black Friday Cyber Monday, quarters, labels and comparisons;
// and the demo's answers to the new comparisons.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { RANGE_COMPARES, bfcm, compareRange, effectiveCompare, fmtSpan, isRangeKey, presetRange, rangeLabel } from '../src/lib/cro.js';
import { demoRequest, resetDemo } from '../src/demo/index.js';

const TODAY = '2026-11-24';   // a Tuesday
const r = (key) => presetRange(key, TODAY);

test('today, yesterday and "last N days" with or without today', () => {
    assert.deepEqual(r('today'), { from: TODAY, to: TODAY });
    assert.deepEqual(r('yesterday'), { from: '2026-11-23', to: '2026-11-23' });
    assert.deepEqual(r('last-7-days'), { from: '2026-11-17', to: '2026-11-23' });
    assert.deepEqual(r('last-7-days-t'), { from: '2026-11-18', to: TODAY });
    assert.deepEqual(r('last7'), r('last-7-days'));   // older links keep working
});

test('"last N" weeks, months, quarters and years are whole periods before this one', () => {
    assert.deepEqual(r('last-1-weeks'), { from: '2026-11-15', to: '2026-11-21' });   // weeks start on Sunday
    assert.deepEqual(r('last-1-months'), { from: '2026-10-01', to: '2026-10-31' });
    assert.deepEqual(r('last-3-months'), { from: '2026-08-01', to: '2026-10-31' });
    assert.deepEqual(r('last-2-months-t'), { from: '2026-10-01', to: TODAY });
    assert.deepEqual(r('last-1-quarters'), { from: '2026-07-01', to: '2026-09-30' });
    assert.deepEqual(r('last-1-years'), { from: '2025-01-01', to: '2025-12-31' });
    assert.deepEqual(r('last_month'), r('last-1-months'));
});

test('period to date, quarters and Black Friday Cyber Monday', () => {
    assert.deepEqual(r('wtd'), { from: '2026-11-22', to: TODAY });
    assert.deepEqual(r('mtd'), { from: '2026-11-01', to: TODAY });
    assert.deepEqual(r('qtd'), { from: '2026-10-01', to: TODAY });
    assert.deepEqual(r('ytd'), { from: '2026-01-01', to: TODAY });
    assert.deepEqual(r('this_month'), r('mtd'));
    assert.deepEqual(r('q-2026-3'), { from: '2026-07-01', to: '2026-09-30' });
    assert.deepEqual(r('q-2026-4'), { from: '2026-10-01', to: TODAY });   // the current quarter stops today
    assert.deepEqual(bfcm(2026), { from: '2026-11-27', to: '2026-11-30' });
    assert.deepEqual(bfcm(2025), { from: '2025-11-28', to: '2025-12-01' });
    assert.deepEqual(r('bfcm-2025'), { from: '2025-11-28', to: '2025-12-01' });
});

test('labels, keys and spans', () => {
    assert.equal(rangeLabel('yesterday'), 'Yesterday');
    assert.equal(rangeLabel('last-7-days'), 'Last 7 days');
    assert.equal(rangeLabel('last-1-months'), 'Last month');
    assert.equal(rangeLabel('last-1-quarters'), 'Last quarter');
    assert.equal(rangeLabel('last-90-days'), 'Last 90 days');
    assert.equal(rangeLabel('last-30-days-t'), 'Last 30 days (incl. today)');
    assert.equal(rangeLabel('q-2026-3'), 'Q3 2026');
    assert.equal(rangeLabel('bfcm-2025'), 'BFCM 2025');
    assert.equal(rangeLabel('custom', '2026-11-01', '2026-11-15'), 'Nov 1 – 15, 2026');
    assert.equal(fmtSpan('2026-10-28', '2026-11-03'), 'Oct 28 – Nov 3, 2026');
    assert.equal(fmtSpan('2026-11-23', '2026-11-23'), 'Nov 23, 2026');
    for (const k of ['today', 'last-7-days', 'last-2-quarters-t', 'mtd', 'bfcm-2025', 'q-2026-1', 'custom', 'last14']) assert.ok(isRangeKey(k), k);
    for (const k of ['', 'last-0x-days', 'q-2026-5', 'nonsense']) assert.ok(!isRangeKey(k), k);
});

test('comparisons: previous period, previous year (dates or weekdays), custom and the fall-backs', () => {
    assert.deepEqual(compareRange('previous', '2026-11-01', '2026-11-15'), { from: '2026-10-17', to: '2026-10-31' });
    assert.deepEqual(compareRange('previous_year', '2026-11-01', '2026-11-15'), { from: '2025-11-01', to: '2025-11-15' });
    assert.deepEqual(compareRange('previous_year_dow', '2026-11-19', '2026-11-19'), { from: '2025-11-20', to: '2025-11-20' });
    assert.deepEqual(compareRange('custom', '2026-11-10', '2026-11-16', '2026-09-01'), { from: '2026-09-01', to: '2026-09-07' });
    assert.equal(compareRange('none', '2026-11-10', '2026-11-16'), null);
    assert.equal(effectiveCompare('4week_avg', '2026-11-10', '2026-11-16'), 'previous');   // one day only
    assert.equal(effectiveCompare('custom', '2026-11-10', '2026-11-16'), 'previous');      // no first day
    assert.equal(effectiveCompare('custom', '2026-11-10', '2026-11-16', '2026-09-01'), 'custom');
    assert.equal(effectiveCompare('custom', '2026-11-10', '2026-11-16', '2026-11-12'), 'previous');   // must start before
    assert.equal(effectiveCompare('previous_year', '2026-11-10', '2026-11-16'), 'previous_year');
});

test("the picker offers Shopify's five comparisons; older ones only open old links", () => {
    assert.deepEqual(RANGE_COMPARES.filter((c) => !c.hidden).map((c) => c.label),
        ['Previous period', 'Previous year', 'Previous year (match day of week)', 'Custom', 'No comparison']);
    assert.equal(effectiveCompare('last_week', '2026-11-10', '2026-11-16'), 'last_week');
});

test('the demo answers the new comparisons', async () => {
    resetDemo();
    const days = await demoRequest('GET', '/cro/sales-trend?brand=ridhi&days=7');
    const to = days.to;
    const from = days.from;
    const y = await demoRequest('GET', `/cro/overview?brand=ridhi&from=${from}&to=${to}&compare=previous_year`);
    assert.equal(y.baseline_label, 'vs same dates last year');
    const cfrom = new Date(Date.parse(`${from}T00:00:00Z`) - 21 * 864e5).toISOString().slice(0, 10);
    const c = await demoRequest('GET', `/cro/overview?brand=ridhi&from=${from}&to=${to}&compare=custom&cfrom=${cfrom}`);
    assert.equal(c.compare, 'custom');
    assert.ok(c.baseline_label.startsWith('vs '));
    await assert.rejects(demoRequest('GET', `/cro/overview?brand=ridhi&from=${from}&to=${to}&compare=custom&cfrom=${to}`), (e) => e.status === 400);
});
