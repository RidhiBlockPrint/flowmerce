'use client';
/**
 * Small motion helpers shared by every page: numbers that count up to their value and a single-value progress ring.
 * They never hold up a page: the count-up writes straight into its own text node (no React re-render per frame),
 * runs for under a second, and is skipped when the computer asks for reduced motion.
 */
import { useLayoutEffect, useRef } from 'react';

const NUMBER = /-?\d[\d,]*(?:\.\d+)?/;
const reducedMotion = () => typeof window !== 'undefined' && !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
const ease = (t) => 1 - (1 - t) ** 3;

/** Splits "$1,071.50 left" into its prefix, number and suffix, and how the number is written. Null when there is none. */
export function parseFigure(text) {
    const m = String(text).match(NUMBER);
    if (!m)
        return null;
    const raw = m[0];
    const decimals = raw.includes('.') ? raw.split('.')[1].length : 0;
    return { prefix: String(text).slice(0, m.index), value: Number(raw.replace(/,/g, '')), suffix: String(text).slice(m.index + raw.length), decimals, commas: raw.includes(',') };
}

/** Writes a number the way the original figure was written (same decimals, thousands separators when it had them). */
export function formatLike(n, fig) {
    return fig.commas ? n.toLocaleString('en-US', { minimumFractionDigits: fig.decimals, maximumFractionDigits: fig.decimals }) : n.toFixed(fig.decimals);
}

/**
 * A figure that counts up from zero (or from its previous value) to `value`. `value` may be a number or an already
 * formatted string such as "$1,071", "96%" or "2.8 d"; anything that is not a figure is shown as it is.
 * `as="tspan"` for use inside SVG <text>.
 */
export function CountUp({ value, duration = 750, as: Tag = 'span', className }) {
    const ref = useRef(null);
    const last = useRef(null);
    const text = value === null || value === undefined ? '' : String(value);
    useLayoutEffect(() => {
        const el = ref.current;
        const fig = parseFigure(text);
        if (!el || !fig || !Number.isFinite(fig.value) || reducedMotion()) {
            last.current = fig?.value ?? null;
            return undefined;
        }
        const from = last.current ?? 0;
        last.current = fig.value;
        if (from === fig.value) {
            el.textContent = text;
            return undefined;
        }
        let raf = 0;
        const start = performance.now();
        const step = (t) => {
            const k = Math.min(1, (t - start) / duration);
            el.textContent = `${fig.prefix}${formatLike(from + (fig.value - from) * ease(k), fig)}${fig.suffix}`;
            if (k < 1)
                raf = requestAnimationFrame(step);
            else
                el.textContent = text;
        };
        el.textContent = `${fig.prefix}${formatLike(from, fig)}${fig.suffix}`;
        raf = requestAnimationFrame(step);
        return () => { cancelAnimationFrame(raf); el.textContent = text; };
    }, [text, duration]);
    if (value !== null && value !== undefined && typeof value === 'object')
        return value;   // already a React node: nothing to count
    return <Tag ref={ref} className={className}>{text}</Tag>;
}

/**
 * One value as a ring that draws itself: `value` of `max`, coloured by `color`, with `label` in the middle and `sub`
 * under it. Used for conversion rate against a reference, blog plan progress and the like.
 */
export function ProgressRing({ value, max = 100, color = 'var(--accent)', label, sub, size = 120, stroke = 3.2, title }) {
    const f = max > 0 ? Math.max(0, Math.min(1, (value || 0) / max)) : 0;
    const len = Math.max(f * 100, f > 0 ? 0.6 : 0);
    return (<svg className="progress-ring" viewBox="0 0 36 36" width={size} height={size} role="img" aria-label={title ?? `${label ?? ''} ${sub ?? ''}`.trim()}>
      <circle cx="18" cy="18" r="15.9155" fill="none" stroke="var(--line-2)" strokeWidth={stroke}/>
      {len ? <circle className="ring-arc" cx="18" cy="18" r="15.9155" fill="none" stroke={color} strokeWidth={stroke} strokeLinecap="round"
        strokeDasharray={`${len} ${100 - len}`} transform="rotate(-90 18 18)"/> : null}
      {label !== undefined ? <text x="18" y={sub ? 18.6 : 20} textAnchor="middle" className="age-ring-num"><CountUp value={label} as="tspan"/></text> : null}
      {sub ? <text x="18" y="23.2" textAnchor="middle" className="age-ring-sub">{sub}</text> : null}
    </svg>);
}

/**
 * A half-circle gauge: `value` of `max` sweeps in from the left; `mark` (optional) draws a tick at a reference value such
 * as the typical store's figure; `label` sits in the middle and `sub` under it.
 */
export function Gauge({ value, max = 100, mark, label, sub, color = 'var(--ok)', width = 150 }) {
    const L = 157.08;
    const f = max > 0 ? Math.max(0, Math.min(1, (value || 0) / max)) : 0;
    const at = (frac, r) => {
        const a = Math.PI * (1 - frac);
        return [60 + r * Math.cos(a), 62 - r * Math.sin(a)];
    };
    const m = mark !== undefined && mark !== null && max > 0 ? Math.max(0, Math.min(1, mark / max)) : null;
    const [x1, y1] = m !== null ? at(m, 41) : [0, 0];
    const [x2, y2] = m !== null ? at(m, 59) : [0, 0];
    return (<svg className="gauge" viewBox="0 0 120 72" width={width} role="img" aria-label={`${label ?? ''} ${sub ?? ''}`.trim()}>
      <path d="M10,62 A50,50 0 0 1 110,62" fill="none" stroke="var(--surface-3)" strokeWidth="12" strokeLinecap="round"/>
      {f > 0 ? <path className="gauge-arc" d="M10,62 A50,50 0 0 1 110,62" fill="none" stroke={color} strokeWidth="12" strokeLinecap="round" strokeDasharray={`${f * L} ${L}`}/> : null}
      {m !== null ? <line x1={x1} y1={y1} x2={x2} y2={y2} stroke="var(--ink)" strokeWidth="2.5" strokeLinecap="round"/> : null}
      {label !== undefined ? <text x="60" y={sub ? 52 : 58} textAnchor="middle" className="gauge-num"><CountUp value={label} as="tspan"/></text> : null}
      {sub ? <text x="60" y="66" textAnchor="middle" className="gauge-sub">{sub}</text> : null}
    </svg>);
}
