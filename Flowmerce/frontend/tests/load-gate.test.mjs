// Run with: node --test tests/load-gate.test.mjs   (from the frontend folder; no packages needed)
// The page load gate (src/lib/loadGate.js): a page is revealed once, when everything it asked for has answered.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createLoadTracker } from '../src/lib/loadGate.js';

/** A fake clock so the tests decide when timers fire. */
function clock() {
    let now = 0, id = 0;
    const timers = new Map();
    return {
        setTimer: (fn, ms) => { id += 1; timers.set(id, { fn, at: now + ms }); return id; },
        clearTimer: (t) => { timers.delete(t); },
        advance(ms) {
            now += ms;
            for (const [k, t] of [...timers].sort((a, b) => a[1].at - b[1].at)) {
                if (t.at <= now && timers.has(k)) { timers.delete(k); t.fn(); }
            }
        },
    };
}

const gate = (c, extra = {}) => {
    const g = { shown: 0 };
    g.t = createLoadTracker({ onReveal: () => { g.shown += 1; }, setTimer: c.setTimer, clearTimer: c.clearTimer, ...extra });
    return g;
};

test('waits for every request, then reveals once', () => {
    const c = clock(), g = gate(c);
    const a = g.t.track(), b = g.t.track();
    g.t.start();
    c.advance(500);
    a();
    c.advance(500);
    assert.equal(g.shown, 0, 'one request is still out');
    b();
    c.advance(59);
    assert.equal(g.shown, 0, 'waits a moment for requests that start right after');
    c.advance(1);
    assert.equal(g.shown, 1);
    c.advance(20000);
    assert.equal(g.shown, 1, 'never revealed twice');
});

test('a request that starts after another answered is still waited for', () => {
    const c = clock(), g = gate(c);
    const first = g.t.track();
    g.t.start();
    c.advance(100);
    first();
    c.advance(30);
    const second = g.t.track();      // e.g. a card that only asks once the first answer is in
    c.advance(1000);
    assert.equal(g.shown, 0);
    second();
    c.advance(60);
    assert.equal(g.shown, 1);
});

test('a page that asks for nothing appears at once, with no wait', () => {
    const c = clock(), g = gate(c);
    g.t.start();
    assert.equal(g.shown, 1);
});

test('one slow source never hides the page for longer than the cap', () => {
    const c = clock(), g = gate(c, { maxWaitMs: 10000 });
    g.t.track();
    g.t.start();
    c.advance(9999);
    assert.equal(g.shown, 0);
    c.advance(1);
    assert.equal(g.shown, 1);
});

test('done() twice, and requests after the reveal, change nothing', () => {
    const c = clock(), g = gate(c);
    const a = g.t.track();
    g.t.start();
    a();
    a();
    assert.equal(g.t.pending, 0);
    c.advance(60);
    const late = g.t.track();
    assert.equal(g.t.pending, 0, 'not counted once revealed');
    late();
    assert.equal(g.shown, 1);
});

test('stop() and start() again (React development mounts twice) still reveals', () => {
    const c = clock(), g = gate(c);
    const a = g.t.track();
    g.t.start();
    g.t.stop();
    g.t.start();
    assert.equal(g.shown, 0);
    a();
    c.advance(60);
    assert.equal(g.shown, 1);
});
