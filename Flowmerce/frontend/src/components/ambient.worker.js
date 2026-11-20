/* The background "thread" drawing (components/AmbientBackground.jsx). Six coloured points drift on wide orbits,
 * joined by soft curves that bend through the middle of the screen.
 *
 * It runs in a Web Worker on an OffscreenCanvas, so page work (loading data, counting figures up) can never make it
 * stutter. Browsers without OffscreenCanvas import `createAmbient` and run the same drawing on the page instead.
 * Motion follows real elapsed time, not frame count, so it moves at the same speed at any frame rate and a late
 * frame never makes it jump. */

/* Module colours from the Flowmerce platform overview: SEO, shipping, Meta, creative, landing pages, WPO. */
const COLOURS = ['#2DBE86', '#F0A020', '#4B8BFF', '#A07BF5', '#FF6B4F', '#27C4D9'];
// Radians per millisecond for a point with s = 1 (the old speed: s * 0.3 per frame at 60 frames a second).
const SPEED = (0.3 * 60) / 1000;

const frame = (fn) => (typeof requestAnimationFrame === 'function' ? requestAnimationFrame(fn) : setTimeout(() => fn(performance.now()), 16));
const cancel = (id) => (typeof cancelAnimationFrame === 'function' ? cancelAnimationFrame(id) : clearTimeout(id));

/**
 * Draws on `canvas` (a page canvas or an OffscreenCanvas). Returns { resize(w, h, dpr), pause(), resume(), stop() }.
 * With `still` (the viewer asked for reduced motion) it draws one frame and redraws only on resize.
 */
export function createAmbient(canvas, { w, h, dpr, still }) {
    const x = canvas.getContext('2d');
    const pts = COLOURS.map((c) => ({ a: Math.random() * 6.28, r: 0.18 + Math.random() * 0.25, s: 0.003 + Math.random() * 0.004, c }));
    let W = w, H = h, id = 0, last = 0, running = false;
    const size = (nw, nh, ndpr) => {
        W = nw;
        H = nh;
        const d = Math.min(ndpr || 1, 2);
        canvas.width = Math.round(W * d);
        canvas.height = Math.round(H * d);
        x.setTransform(d, 0, 0, d, 0, 0);
    };
    const draw = () => {
        x.clearRect(0, 0, W, H);
        const xy = pts.map((p) => [W * (0.5 + Math.cos(p.a) * p.r * 1.6), H * (0.5 + Math.sin(p.a * 1.3) * p.r * 1.4)]);
        x.lineWidth = 1.2;
        for (let i = 0; i < pts.length; i++) {
            const a = xy[i], b = xy[(i + 1) % pts.length];
            const g = x.createLinearGradient(a[0], a[1], b[0], b[1]);
            g.addColorStop(0, `${pts[i].c}44`);
            g.addColorStop(1, `${pts[(i + 1) % pts.length].c}44`);
            x.strokeStyle = g;
            x.beginPath();
            x.moveTo(a[0], a[1]);
            x.quadraticCurveTo(W / 2, H / 2, b[0], b[1]);
            x.stroke();
            x.fillStyle = `${pts[i].c}77`;
            x.beginPath();
            x.arc(a[0], a[1], 4, 0, 6.28);
            x.fill();
        }
    };
    const loop = (t) => {
        // At most 100 ms of movement per frame, so coming back to the tab never makes the points leap.
        const dt = last ? Math.min(t - last, 100) : 0;
        last = t;
        for (const p of pts) p.a += p.s * SPEED * dt;
        draw();
        if (running) id = frame(loop);
    };
    const resume = () => {
        if (still) { draw(); return; }
        if (running) return;
        running = true;
        last = 0;
        id = frame(loop);
    };
    const pause = () => { running = false; cancel(id); };
    size(w, h, dpr);
    resume();
    return {
        resize: (nw, nh, ndpr) => { size(nw, nh, ndpr); draw(); },
        pause,
        resume,
        stop: pause,
    };
}

// When loaded as a worker: the page sends the canvas once, then resize / pause / resume messages.
if (typeof WorkerGlobalScope !== 'undefined' && self instanceof WorkerGlobalScope) {
    let ambient = null;
    self.onmessage = ({ data }) => {
        if (data.type === 'start') ambient = createAmbient(data.canvas, data);
        else if (!ambient) return;
        else if (data.type === 'resize') ambient.resize(data.w, data.h, data.dpr);
        else if (data.type === 'pause') ambient.pause();
        else if (data.type === 'resume') ambient.resume();
    };
}
