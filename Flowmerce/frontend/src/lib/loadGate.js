/**
 * The page load gate's bookkeeping (components/LoadGate.jsx): every page appears all at once, when the data it asked
 * for on opening has answered, instead of part by part.
 *
 * useApi (lib/api.js) calls `track()` before the first paint when a page's request will start with nothing to show
 * yet, and the returned `done()` when it answers or fails. The gate calls `start()` once the page has mounted (React
 * runs the page's layout effects first, so its first requests are already counted; with none, the page shows at once
 * without the placeholder ever being painted). Otherwise the page is revealed when nothing has been pending for
 * `settleMs` (so a request that only starts after another one answered is still waited for), or after `maxWaitMs`
 * whatever is still loading, so one slow source never hides a page. Once revealed it stays revealed.
 *
 * Plain JavaScript with no React, so it can be tested on its own (tests/load-gate.test.mjs).
 */
export function createLoadTracker({ onReveal, settleMs = 60, maxWaitMs = 10000, setTimer = setTimeout, clearTimer = clearTimeout }) {
    let pending = 0;
    let revealed = false;
    let started = false;
    let settle = null;
    let cap = null;
    const reveal = () => {
        if (revealed) return;
        revealed = true;
        clearTimer(settle);
        clearTimer(cap);
        onReveal();
    };
    const check = () => {
        clearTimer(settle);
        settle = null;
        if (started && !revealed && pending === 0) settle = setTimer(reveal, settleMs);
    };
    return {
        /** Count one request; call the returned function once when it answers, fails or is cancelled. */
        track() {
            if (revealed) return () => {};
            pending += 1;
            clearTimer(settle);
            settle = null;
            let done = false;
            return () => {
                if (done) return;
                done = true;
                pending -= 1;
                check();
            };
        },
        /**
         * The page has mounted: begin waiting (safe to call again after stop(), as React does in development). With
         * nothing pending it reveals at once, so a page or tab that needs no new data never shows the placeholder.
         */
        start() {
            if (revealed) return;
            started = true;
            if (pending === 0) { reveal(); return; }
            clearTimer(cap);
            cap = setTimer(reveal, maxWaitMs);
            check();
        },
        /** The page is going away: drop the timers. */
        stop() {
            started = false;
            clearTimer(settle);
            clearTimer(cap);
        },
        get revealed() { return revealed; },
        get pending() { return pending; },
    };
}
