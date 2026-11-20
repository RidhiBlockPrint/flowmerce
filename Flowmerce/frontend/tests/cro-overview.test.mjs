// Run with: node --test tests/cro-overview.test.mjs   (from the frontend folder; no packages needed)
// The CRO Overview's drawing helpers (src/lib/cro.js): the sales chart window, the conversion gauge's scale,
// the axis rounding and the CSV download.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { conversionBand, conversionScale, niceAxis, salesWindow, toCsv } from '../src/lib/cro.js';

const days = (n, start = 1) => Array.from({ length: n }, (_, i) => ({ date: `d${start + i}`, net: start + i }));

test('28 days compares with the 28 days before; a shorter window with the days just before it', () => {
    const cur = days(28, 29), prev = days(28, 1);
    const w28 = salesWindow(cur, prev, 28);
    assert.equal(w28.current, cur);
    assert.equal(w28.previous, prev);
    const w7 = salesWindow(cur, prev, 7);
    assert.deepEqual(w7.current.map((r) => r.net), [50, 51, 52, 53, 54, 55, 56]);
    assert.deepEqual(w7.previous.map((r) => r.net), [43, 44, 45, 46, 47, 48, 49]);
    const w14 = salesWindow(cur, prev, 14);
    assert.equal(w14.current.length, 14);
    assert.equal(w14.previous[13].net + 1, w14.current[0].net);   // the two periods meet with no gap
});

test('a short history still gives a window, never undefined lists', () => {
    assert.deepEqual(salesWindow(undefined, undefined, 14), { current: [], previous: [] });
    const w = salesWindow(days(5), [], 7);
    assert.equal(w.current.length, 5);
});

test('conversion scale: average, usual band and the rank of a day', () => {
    // The real Ridhi history behind the approved design: 28 days ending Thu 19 Nov 2026.
    const h = [1.94, 1.35, 1.64, 1.12, 1.32, 1.63, 1.82, 1.65, 2.07, 1.96, 1.81, 2.2, 1.67, 1.86, 2.16, 2.18, 1.85, 2.03, 2.02, 2.05, 2.28, 1.89, 1.97, 1.90, 1.88, 2.13, 2.51, 2.33];
    const s = conversionScale(h, 2.33);
    assert.equal(s.days, 28);
    assert.ok(Math.abs(s.avg - 1.9) < 0.01);
    assert.equal(s.beats, 26);                                   // only 2.51 and the day itself are not below it
    assert.ok(s.lo <= 1.12 && s.hi >= 2.51);
    assert.equal(conversionBand(2.33, s), 'high');
    assert.equal(conversionBand(1.9, s), 'mid');
    assert.equal(conversionBand(1.12, s), 'low');
    assert.equal(conversionBand(null, s), null);
});

test('conversion scale ignores missing days and needs some history', () => {
    assert.equal(conversionScale([], 2), null);
    assert.equal(conversionScale([null, undefined], 2), null);
    const s = conversionScale([2, null, 2], null);
    assert.equal(s.days, 2);
    assert.equal(s.beats, null);
});

test('axis tops are round numbers', () => {
    assert.deepEqual(niceAxis(13992), { top: 15000, step: 5000 });
    assert.deepEqual(niceAxis(9411), { top: 10000, step: 5000 });
    assert.deepEqual(niceAxis(87), { top: 100, step: 50 });       // orders: 0, 50, 100
    assert.equal(niceAxis(0).top > 0, true);
});

test('CSV quotes cells with commas and quotes, and leaves blanks for missing values', () => {
    assert.equal(toCsv([['Day', 'Note'], ['2026-11-19', 'a, "b"'], ['2026-11-18', null]]), 'Day,Note\n2026-11-19,"a, ""b"""\n2026-11-18,');
});
