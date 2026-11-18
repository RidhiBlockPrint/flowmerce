import assert from 'node:assert/strict';
import { test } from 'node:test';
import { fmtUtc, fmtZoned } from '../src/lib/time.mjs';

test('Shopify-scheduled article 39: 14:30 UTC is 8:00 PM IST on the same day', () => {
    assert.equal(fmtZoned('2026-11-16T14:30:00Z', 'Asia/Kolkata'), '16 November 2026, 8:00 PM IST');
});

test('Shopify-scheduled article 38: 20 November', () => {
    assert.equal(fmtZoned('2026-11-20T14:30:00Z', 'Asia/Kolkata'), '20 November 2026, 8:00 PM IST');
});

test('the same instant in UTC keeps its source value', () => {
    assert.equal(fmtUtc('2026-11-16T14:30:00Z'), '16 November 2026, 2:30 PM UTC');
});

test('conversion can change the calendar day', () => {
    assert.equal(fmtZoned('2026-11-16T20:00:00Z', 'Asia/Kolkata'), '17 November 2026, 1:30 AM IST');
    assert.equal(fmtZoned('2026-11-16T02:00:00Z', 'America/New_York'), '15 November 2026, 9:00 PM EST');
});

test('midnight and noon use 12, with AM and PM', () => {
    assert.equal(fmtZoned('2026-11-16T00:00:00Z', 'UTC'), '16 November 2026, 12:00 AM UTC');
    assert.equal(fmtZoned('2026-11-16T12:00:00Z', 'UTC'), '16 November 2026, 12:00 PM UTC');
});

test('a zone without an abbreviation shows its offset, never a bare time', () => {
    const s = fmtZoned('2026-11-16T14:30:00Z', 'Asia/Dubai');
    assert.match(s, /^16 November 2026, 6:30 PM UTC\+4$/);
});

test('missing or invalid input is a dash, not a wrong date', () => {
    assert.equal(fmtZoned(null), '—');
    assert.equal(fmtZoned('not a date'), '—');
});

test('daylight saving is applied for the date, not for today', () => {
    assert.equal(fmtZoned('2026-07-01T12:00:00Z', 'America/New_York'), '1 July 2026, 8:00 AM EDT');
});
