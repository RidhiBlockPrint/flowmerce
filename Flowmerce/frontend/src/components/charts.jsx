'use client';
/* Small SVG charts. Rules followed: one y-axis per chart (clicks and impressions are separate
 * charts, never dual-axis); 2px lines; recessive grid; legend for 2+ series plus direct end labels;
 * a crosshair tooltip on hover/touch; and a table view of the same numbers. Series colour follows the
 * brand, never its rank, so filtering does not repaint a line. */
import { useLayoutEffect, useMemo, useRef, useState } from 'react';
import { fmtCompact, fmtDay } from '../lib/format';
function useWidth() {
    const ref = useRef(null);
    const [w, setW] = useState(600);
    useLayoutEffect(() => {
        if (!ref.current)
            return;
        const ro = new ResizeObserver(([e]) => setW(Math.max(240, Math.floor(e.contentRect.width))));
        ro.observe(ref.current);
        return () => ro.disconnect();
    }, []);
    return [ref, w];
}
/** `integer`: the axis shows whole numbers (counts, rounded positions), so never use a step below 1: a step of 0.5
 *  would label 0, 0.5, 1, 1.5, 2 as "0, 1, 1, 2, 2". */
function niceTicks(max, count = 4, integer = false) {
    if (max <= 0)
        return [0, 1];
    const raw = max / count;
    const mag = Math.max(Math.pow(10, Math.floor(Math.log10(raw))), integer ? 1 : 0);
    const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).filter((s) => !integer || Number.isInteger(s)).find((s) => s >= raw) ?? Math.ceil(raw);
    const out = [];
    for (let v = 0; v <= max + step * 0.001; v += step)
        out.push(v);
    if (out[out.length - 1] < max)
        out.push(out[out.length - 1] + step);
    return out;
}
/**
 * Optional extras: `refLine` { y, label } draws a dashed reference (for example the typical store's rate); `area` fills
 * under the first solid series; `extremes` 'high' or 'low' says which end is good and marks the best day (green) and
 * the worst day (red) of the first series.
 */
export function LineChart({ series, height = 220, yFormat = fmtCompact, invertY, ariaLabel, refLine, area, extremes }) {
    const gid = useMemo(() => `lc${Math.random().toString(36).slice(2, 8)}`, []);
    const [ref, width] = useWidth();
    const [hover, setHover] = useState(null);
    const [asTable, setAsTable] = useState(false);
    const xs = useMemo(() => [...new Set(series.flatMap((s) => s.points.map((p) => p.x)))].sort(), [series]);
    const values = series.flatMap((s) => s.points.map((p) => p.y)).filter((v) => v !== null);
    const multi = series.length > 1;
    const labelRoom = multi && width > 480 ? 64 : 12;
    const m = { t: 10, r: labelRoom, b: 26, l: 44 };
    const iw = width - m.l - m.r;
    const ih = height - m.t - m.b;
    const yMin = invertY ? Math.max(0, Math.floor(Math.min(...values, 1))) : 0;
    const whole = yFormat === fmtCompact || !!invertY;
    const ticks = invertY ? niceTicks(Math.max(...values, 1) - yMin, 4, true).map((t) => t + yMin) : niceTicks(Math.max(...values, refLine?.y ?? 0, 0), 4, whole);
    const yMax = ticks[ticks.length - 1] || 1;
    const x = (i) => m.l + (xs.length <= 1 ? iw / 2 : (i / (xs.length - 1)) * iw);
    const y = (v) => invertY ? m.t + ((v - yMin) / (yMax - yMin || 1)) * ih : m.t + ih - (v / yMax) * ih;
    const xIndex = new Map(xs.map((d, i) => [d, i]));
    const labelEvery = Math.max(1, Math.ceil(xs.length / Math.max(2, Math.floor(iw / 80))));
    if (!values.length)
        return <div className="muted small" style={{ height, display: 'grid', placeItems: 'center' }}>No data points in this range</div>;
    const onMove = (clientX, rect) => {
        const px = clientX - rect.left - m.l;
        const i = Math.round((px / iw) * (xs.length - 1));
        setHover(Math.max(0, Math.min(xs.length - 1, i)));
    };
    const endLabels = series.map((s) => {
        const last = [...s.points].reverse().find((p) => p.y !== null);
        return last ? { s, yv: y(last.y) } : null;
    }).filter(Boolean);
    endLabels.sort((a, b) => a.yv - b.yv);
    for (let i = 1; i < endLabels.length; i++)
        if (endLabels[i].yv - endLabels[i - 1].yv < 14)
            endLabels[i].yv = endLabels[i - 1].yv + 14;
    return (<div className="chart" ref={ref}>
      <div className="row mb-8" style={{ minHeight: 20 }}>
        {multi ? (<div className="legend">
            {series.map((s) => <span key={s.key} className="legend-item"><span className={`legend-swatch ${s.dashed ? 'dashed' : ''}`} style={{ background: s.color, color: s.color }}/>{s.label}</span>)}
          </div>) : null}
        <button className="btn ghost xs" style={{ marginLeft: 'auto' }} onClick={() => setAsTable((v) => !v)} aria-pressed={asTable}>
          {asTable ? 'Chart' : 'Table'}
        </button>
      </div>
      {asTable ? (<div className="table-wrap" style={{ maxHeight: height + 20, overflowY: 'auto' }}>
          <table className="t compact">
            <thead><tr><th>Date</th>{series.map((s) => <th key={s.key} className="r">{s.label}</th>)}</tr></thead>
            <tbody>
              {xs.map((d) => (<tr key={d}><td>{fmtDay(d)}</td>{series.map((s) => { const p = s.points.find((q) => q.x === d); return <td key={s.key} className="r">{p?.y === null || p?.y === undefined ? '—' : yFormat(p.y)}</td>; })}</tr>))}
            </tbody>
          </table>
        </div>) : (<>
          <svg height={height} role="img" aria-label={ariaLabel} onMouseMove={(e) => onMove(e.clientX, e.currentTarget.getBoundingClientRect())} onTouchMove={(e) => onMove(e.touches[0].clientX, e.currentTarget.getBoundingClientRect())} onMouseLeave={() => setHover(null)} onTouchEnd={() => setHover(null)}>
            {ticks.map((t) => (<g key={t}>
                <line className="grid-line" x1={m.l} x2={m.l + iw} y1={y(t)} y2={y(t)}/>
                <text className="axis-text" x={m.l - 8} y={y(t) + 4} textAnchor="end">{yFormat(t)}</text>
              </g>))}
            {refLine ? (<g className="line-fade">
                <line x1={m.l} x2={m.l + iw} y1={y(refLine.y)} y2={y(refLine.y)} stroke="var(--ink-2)" strokeDasharray="4 4" strokeWidth={1.2} opacity={0.6}/>
                <text className="axis-text" x={m.l + iw} y={y(refLine.y) - 5} textAnchor="end" style={{ fill: 'var(--ink-2)', fontWeight: 600 }}>{refLine.label}</text>
              </g>) : null}
            {area && series[0] && !series[0].dashed ? (() => {
                const pts = series[0].points.filter((p) => p.y !== null);
                if (pts.length < 2)
                    return null;
                const base = y(invertY ? yMax : yMin);
                const d = pts.map((p, k) => `${k ? 'L' : 'M'}${x(xIndex.get(p.x)).toFixed(1)},${y(p.y).toFixed(1)}`).join('')
                    + `L${x(xIndex.get(pts[pts.length - 1].x)).toFixed(1)},${base}L${x(xIndex.get(pts[0].x)).toFixed(1)},${base}Z`;
                return (<><defs><linearGradient id={gid} x1="0" x2="0" y1="0" y2="1"><stop offset="0" stopColor={series[0].color} stopOpacity="0.24"/><stop offset="1" stopColor={series[0].color} stopOpacity="0"/></linearGradient></defs>
                  <path className="line-fade" d={d} fill={`url(#${gid})`}/></>);
            })() : null}
            {xs.map((d, i) => (i % labelEvery === 0 || i === xs.length - 1) && (i === xs.length - 1 || xs.length - 1 - i >= labelEvery * 0.6) ? (<text key={d} className="axis-text" x={x(i)} y={height - 6} textAnchor={i === 0 ? 'start' : i === xs.length - 1 ? 'end' : 'middle'}>{fmtDay(d)}</text>) : null)}
            {series.map((s) => {
                let dStr = '';
                let pen = false;
                for (const p of s.points) {
                    const i = xIndex.get(p.x);
                    if (p.y === null) {
                        pen = false;
                        continue;
                    }
                    dStr += `${pen ? 'L' : 'M'}${x(i).toFixed(1)},${y(p.y).toFixed(1)}`;
                    pen = true;
                }
                return <path key={s.key} className={s.dashed ? 'line-fade' : 'line-draw'} d={dStr} fill="none" stroke={s.color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" strokeDasharray={s.dashed ? '5 4' : undefined}/>;
            })}
            {extremes && series[0] ? (() => {
                const pts = series[0].points.filter((p) => p.y !== null);
                if (pts.length < 3)
                    return null;
                const hi = pts.reduce((a, b) => (b.y > a.y ? b : a));
                const lo = pts.reduce((a, b) => (b.y < a.y ? b : a));
                const [best, worst] = extremes === 'low' ? [lo, hi] : [hi, lo];
                return (<g className="line-fade">
                  <circle cx={x(xIndex.get(best.x))} cy={y(best.y)} r={5} fill="var(--ok)" stroke="var(--surface)" strokeWidth={2}><title>{`Best day: ${fmtDay(best.x)}, ${yFormat(best.y)}`}</title></circle>
                  <circle cx={x(xIndex.get(worst.x))} cy={y(worst.y)} r={5} fill="var(--crit)" stroke="var(--surface)" strokeWidth={2}><title>{`Worst day: ${fmtDay(worst.x)}, ${yFormat(worst.y)}`}</title></circle>
                </g>);
            })() : null}
            {multi && width > 480 ? endLabels.map(({ s, yv }) => (<text key={s.key} x={m.l + iw + 8} y={yv + 4} className="axis-text" style={{ fill: 'var(--ink-2)', fontWeight: 600 }}>{s.label}</text>)) : null}
            {hover !== null ? (<g>
                <line className="crosshair" x1={x(hover)} x2={x(hover)} y1={m.t} y2={m.t + ih}/>
                {series.map((s) => {
                    const p = s.points.find((q) => q.x === xs[hover]);
                    return p && p.y !== null ? <circle key={s.key} cx={x(hover)} cy={y(p.y)} r={4.5} fill={s.color} stroke="var(--surface)" strokeWidth={2}/> : null;
                })}
              </g>) : null}
          </svg>
          {hover !== null ? (<div className="chart-tip" style={{ left: Math.min(Math.max(x(hover), 90), width - 90), top: 26 }}>
              <div className="tt">{fmtDay(xs[hover])}</div>
              {series.map((s) => {
                    const p = s.points.find((q) => q.x === xs[hover]);
                    return <div key={s.key} className="tr"><span className="legend-swatch" style={{ background: s.color }}/>{s.label}<b>{p?.y === null || p?.y === undefined ? '—' : yFormat(p.y)}</b></div>;
                })}
            </div>) : null}
        </>)}
    </div>);
}
export function Sparkline({ values, color = 'var(--accent)', width = 90, height = 26 }) {
    if (values.length < 2)
        return null;
    const max = Math.max(...values, 1);
    const min = Math.min(...values, 0);
    const d = values.map((v, i) => `${i ? 'L' : 'M'}${((i / (values.length - 1)) * (width - 4) + 2).toFixed(1)},${(height - 3 - ((v - min) / (max - min || 1)) * (height - 6)).toFixed(1)}`).join('');
    return <svg width={width} height={height} aria-hidden style={{ display: 'block' }}><path className="line-draw" d={d} fill="none" stroke={color} strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round"/></svg>;
}
export function BarList({ rows, format = fmtCompact, empty = 'Nothing to show' }) {
    const max = Math.max(...rows.map((r) => r.value), 1);
    if (!rows.length)
        return <div className="muted small" style={{ padding: '12px 8px' }}>{empty}</div>;
    return (<div className="barlist">
      {rows.map((r) => {
            const inner = (<>
            <span className="bar-fill" style={{ width: `${Math.max(2, (r.value / max) * 100)}%` }}/>
            <span className="ellipsis" style={{ minWidth: 0 }}>{r.label}</span>
            <span className="row gap-12 num small nowrap"><span className="hide-sm">{r.extra}</span><b>{format(r.value)}</b></span>
          </>);
            return r.onClick ? (<a key={r.key} className="bar-row" href="#" onClick={(e) => { e.preventDefault(); r.onClick(); }}>{inner}</a>) : r.href ? (<a key={r.key} className="bar-row" href={r.href} target="_blank" rel="noopener">{inner}</a>) : <div key={r.key} className="bar-row">{inner}</div>;
        })}
    </div>);
}
/** Ring chart: `items` are { label, value, color }. Clicking a slice calls onSelect(item). */
export function ScoreRing({ value }) {
    const r = 19, c = 2 * Math.PI * r;
    const color = value >= 80 ? 'var(--ok)' : value >= 55 ? 'var(--saffron)' : 'var(--crit)';
    return (<svg className="score-ring" viewBox="0 0 46 46" role="img" aria-label={`SEO score ${value} of 100`}>
      <circle cx="23" cy="23" r={r} fill="none" stroke="var(--line)" strokeWidth="4"/>
      <circle cx="23" cy="23" r={r} fill="none" stroke={color} strokeWidth="4" strokeDasharray={`${(value / 100) * c} ${c}`} strokeLinecap="round" transform="rotate(-90 23 23)"/>
      <text x="23" y="27.5" textAnchor="middle" fontSize="13" fontWeight="700" fill="var(--ink)" fontFamily="var(--sans)">{value}</text>
    </svg>);
}
