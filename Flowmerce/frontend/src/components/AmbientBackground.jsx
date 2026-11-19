'use client';
import { useEffect, useRef } from 'react';

/* Module colours from the Flowmerce platform overview: SEO, shipping, Meta, creative, landing pages, WPO. */
const COLOURS = ['#2DBE86', '#F0A020', '#4B8BFF', '#A07BF5', '#FF6B4F', '#27C4D9'];

/**
 * The slow "thread" behind every page: six coloured points drift on wide orbits, joined by soft curves that bend
 * through the middle of the screen. Purely decorative (aria-hidden, no pointer events). It draws one still frame
 * when the viewer asks for reduced motion, and stops while the tab is hidden.
 */
export function AmbientBackground() {
    const ref = useRef(null);
    useEffect(() => {
        const c = ref.current;
        const x = c?.getContext('2d');
        if (!x)
            return undefined;
        const reduce = typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
        const pts = COLOURS.map((col) => ({ a: Math.random() * 6.28, r: 0.18 + Math.random() * 0.25, s: 0.003 + Math.random() * 0.004, c: col }));
        let W = 0, H = 0, raf = 0;
        const size = () => {
            const dpr = Math.min(window.devicePixelRatio || 1, 2);
            W = window.innerWidth;
            H = window.innerHeight;
            c.width = W * dpr;
            c.height = H * dpr;
            x.setTransform(dpr, 0, 0, dpr, 0, 0);
        };
        const draw = () => {
            x.clearRect(0, 0, W, H);
            const xy = pts.map((p) => {
                if (!reduce)
                    p.a += p.s * 0.3;
                return [W * (0.5 + Math.cos(p.a) * p.r * 1.6), H * (0.5 + Math.sin(p.a * 1.3) * p.r * 1.4)];
            });
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
        const loop = () => { draw(); raf = requestAnimationFrame(loop); };
        const start = () => { cancelAnimationFrame(raf); if (reduce) draw(); else loop(); };
        const onVis = () => { if (document.hidden) cancelAnimationFrame(raf); else start(); };
        const onResize = () => { size(); if (reduce) draw(); };
        size();
        start();
        window.addEventListener('resize', onResize);
        document.addEventListener('visibilitychange', onVis);
        return () => {
            cancelAnimationFrame(raf);
            window.removeEventListener('resize', onResize);
            document.removeEventListener('visibilitychange', onVis);
        };
    }, []);
    return <canvas ref={ref} className="ambient-bg" aria-hidden="true"/>;
}
