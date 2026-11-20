'use client';
import { useEffect, useRef } from 'react';
import { createAmbient } from './ambient.worker';

/**
 * The slow "thread" behind every page (drawing in ambient.worker.js). Purely decorative (aria-hidden, no pointer
 * events). It draws every frame with time-based motion, and where the browser allows it the drawing runs in a Web
 * Worker on an OffscreenCanvas, so loading a page never makes it stutter; elsewhere the same drawing runs here.
 * One still frame when the viewer asks for reduced motion; nothing is drawn while the tab is hidden.
 *
 * The canvas is created here rather than in JSX: a canvas handed to a worker can never be handed over again, and
 * React (strict mode) mounts effects twice in development, so each mount gets a fresh canvas.
 */
export function AmbientBackground() {
    const ref = useRef(null);
    useEffect(() => {
        const box = ref.current;
        if (!box)
            return undefined;
        const canvas = document.createElement('canvas');
        canvas.className = 'ambient-bg';
        box.appendChild(canvas);
        const still = typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
        const dims = () => ({ w: window.innerWidth, h: window.innerHeight, dpr: window.devicePixelRatio || 1 });
        let worker = null;
        let local = null;
        if (typeof canvas.transferControlToOffscreen === 'function' && typeof Worker === 'function') {
            try {
                worker = new Worker(new URL('./ambient.worker.js', import.meta.url), { type: 'module' });
                const off = canvas.transferControlToOffscreen();
                worker.postMessage({ type: 'start', canvas: off, still, ...dims() }, [off]);
            } catch {
                worker?.terminate();
                worker = null;
            }
        }
        if (!worker) {
            const { w, h, dpr } = dims();
            try { local = createAmbient(canvas, { w, h, dpr, still }); } catch { /* no 2D canvas: leave the background plain */ }
        }
        const send = (msg) => (worker ? worker.postMessage(msg) : null);
        const onResize = () => {
            const d = dims();
            if (worker) send({ type: 'resize', ...d });
            else local?.resize(d.w, d.h, d.dpr);
        };
        const onVis = () => {
            const type = document.hidden ? 'pause' : 'resume';
            if (worker) send({ type });
            else local?.[type]();
        };
        window.addEventListener('resize', onResize);
        document.addEventListener('visibilitychange', onVis);
        return () => {
            window.removeEventListener('resize', onResize);
            document.removeEventListener('visibilitychange', onVis);
            worker?.terminate();
            local?.stop();
            canvas.remove();
        };
    }, []);
    return <div ref={ref} aria-hidden="true"/>;
}
