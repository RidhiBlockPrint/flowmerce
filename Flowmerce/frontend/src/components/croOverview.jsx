'use client';
/* The CRO Overview's pieces (views/Cro.jsx, Overview tab), design A2: the 14-day strip, the orders blocks, the
 * conversion gauge, visits by day, the sales chart and the shopper journey. Colours are the content calendar's
 * lanes (.lane-* in globals.css), so a colour means the same here as on the calendar: green good, saffron usual or
 * an event, red a drop, blue this period. Every figure comes from /api/cro/...; these components only draw it.
 * Above Orders and Visits sit the Sales and Site health tiles (approved 2026-11-21), so the three columns end level
 * with the conversion card. */
import { useLayoutEffect, useRef, useState } from 'react';
import { Icon } from './Icon';
import { CountUp } from './motion';
import { ExplainedError, Seg } from './cro';
import { BarList, LineChart } from './charts';
import { fmtDay, fmtInt } from '../lib/format';
import { RATING, VITALS, bestHours, conversionBand, fmtHour, fmtVital, heatLevel, money, niceAxis, pct, readable, salesWindow, seriesOf, toCsv } from '../lib/cro';

/** Width of an element, kept current as the window resizes (charts draw at 1:1 so text keeps its size). */
function useWidth(initial = 800) {
    const ref = useRef(null);
    const [w, setW] = useState(initial);
    useLayoutEffect(() => {
        if (!ref.current || typeof ResizeObserver === 'undefined') return undefined;
        const ro = new ResizeObserver(([e]) => setW(Math.max(260, Math.floor(e.contentRect.width))));
        ro.observe(ref.current);
        return () => ro.disconnect();
    }, []);
    return [ref, w];
}

const weekday = (iso) => new Date(`${iso}T12:00:00Z`).toLocaleDateString('en-GB', { weekday: 'short', timeZone: 'UTC' });
const dayNum = (iso) => Number(iso.slice(8));
const arrow = (v) => `${v >= 0 ? '▲' : '▼'} ${Math.abs(v).toFixed(1)}%`;
const changeOf = (b) => (b && !b.too_early && b.change_pct !== null && b.change_pct !== undefined ? b.change_pct : null);

/** A metric block's change as a calendar-style chip (green up, red down), or "too early to compare". */
export function ChangeChip({ block, v = changeOf(block) }) {
    if (v === null || v === undefined) return <span className="muted xs" title="Below about 20 orders or 500 sessions a % change is mostly noise">too early to compare</span>;
    return <span className={`lane-chip ${v >= 0 ? 'lane-live' : 'lane-due'}`}>{arrow(v)}</span>;
}

const InfoMark = ({ text }) => <span className="ov-info" title={text} aria-label={text} role="img"><Icon name="info" size="sm"/></span>;

/* ------------------------------------------------------------------ 14-day strip */
/**
 * The last 14 days as calendar tiles: orders, and a line coloured by how well the day converted. The chosen
 * day is dark; days inside a longer chosen range are outlined. Clicking a tile looks at that one day.
 */
export function DayStrip({ days, from, to, scale, onPick }) {
    const box = useRef(null);
    // On a narrow screen the strip scrolls sideways: start at the newest days, as the calendar does.
    useLayoutEffect(() => { if (box.current) box.current.scrollLeft = box.current.scrollWidth; }, [days.length]);
    if (!days.length) return null;
    return (<div className="ov-strip-wrap">
      <div className="ov-strip-head">
        <b>Last 14 days</b>
        <div className="row" style={{ gap: 6 }}>
          <span className="lane-chip lane-live">Converted well</span><span className="lane-chip lane-event">Usual</span><span className="lane-chip lane-due">Below usual</span>
        </div>
      </div>
      <div className="ov-strip" role="group" aria-label="Pick a day" ref={box}>
        {days.map((d) => {
            const one = from === to && d.date === from;
            const inRange = !one && d.date >= from && d.date <= to;
            const band = conversionBand(d.cvr, scale);
            return (<button key={d.date} type="button" className={`ov-day${one ? ' sel' : ''}${inRange ? ' in' : ''}`} aria-pressed={one}
              onClick={() => onPick(d.date)} title={`${weekday(d.date)} ${fmtDay(d.date)}: ${fmtInt(d.orders)} orders${d.cvr !== null ? `, ${pct(d.cvr)} converted` : ''}`}>
              <span className="w">{weekday(d.date)}</span>
              <span className="n">{dayNum(d.date)}</span>
              <span className="o">{fmtInt(d.orders)} orders</span>
              <span className={`ov-day-bar ${band ? `z-${band}` : 'z-none'}`}/>
            </button>);
        })}
      </div>
    </div>);
}

/* ------------------------------------------------------------------ orders */
/** Orders for the chosen days, and the last 7 days as columns of blocks (one block per `unit` orders). */
export function OrdersCard({ block, days }) {
    const last = days.slice(-7);
    const max = Math.max(1, ...last.map((d) => d.orders || 0));
    const unit = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000].find((u) => max / u <= 10) ?? Math.ceil(max / 10);
    return (<section className="card ov-card" aria-labelledby="ov-orders">
      <div className="ov-card-head"><h2 id="ov-orders">Orders <InfoMark text="Orders placed in the chosen days"/></h2></div>
      <div className="ov-orders">
        <div>
          <div className="ov-big num">{block?.value === null || block?.value === undefined ? '—' : <CountUp value={fmtInt(block.value)}/>}</div>
          <div style={{ marginTop: 8 }}><ChangeChip block={block}/></div>
          {changeOf(block) !== null ? <div className="muted xs" style={{ marginTop: 4 }}>{block.baseline_label}</div> : null}
          <div className="ov-key col">
            <span><i className="b-now"/>Last day</span><span><i className="b-before"/>Days before</span><span>1 block ≈ {fmtInt(unit)} {unit === 1 ? 'order' : 'orders'}</span>
          </div>
        </div>
        <div>
          <div className="ov-blocks" aria-label={`Orders per day, last ${last.length} days`}>
            {last.map((d, i) => (<div key={d.date} className={`ov-bcol${i === last.length - 1 ? ' now' : ''}`} title={`${weekday(d.date)} ${fmtDay(d.date)}: ${fmtInt(d.orders)} orders`}>
              {Array.from({ length: Math.round((d.orders || 0) / unit) }, (_, j) => <span key={j} className="ov-blk" style={{ animationDelay: `${i * 40 + j * 25}ms` }}/>)}
            </div>))}
          </div>
          <div className="ov-bdays">{last.map((d) => <span key={d.date}>{weekday(d.date).slice(0, 1)}</span>)}</div>
        </div>
      </div>
    </section>);
}

/* ------------------------------------------------------------------ conversion gauge */
/**
 * Conversion on a half-circle: the outer arc shows the store's own bands over recent weeks (below usual, usual,
 * strong), the inner arc the chosen days' rate, and a tick the average. Below: revenue, average order and, for
 * complete days, revenue per visit.
 */
export function GaugeCard({ value, scale, single, revenue, aov, perVisit }) {
    const cx = 160, cy = 170, R = 136, r = 112;
    const t = (v) => (scale ? Math.max(0, Math.min(1, (v - scale.lo) / (scale.hi - scale.lo || 1))) : 0);
    const pt = (rad, tt) => { const a = Math.PI * (1 - tt); return [cx + rad * Math.cos(a), cy - rad * Math.sin(a)]; };
    const arc = (rad, t0, t1) => { const a = pt(rad, t0), b = pt(rad, t1); return `M${a[0].toFixed(2)},${a[1].toFixed(2)} A${rad},${rad} 0 0 1 ${b[0].toFixed(2)},${b[1].toFixed(2)}`; };
    const has = value !== null && value !== undefined;
    const gap = 0.012;
    const k = has ? pt(r, t(value)) : null;
    const a1 = scale ? pt(R - 13, t(scale.avg)) : null, a2 = scale ? pt(R + 13, t(scale.avg)) : null;
    const note = !has ? 'Shopify reports visits for complete days only, so today has no conversion yet.'
        : scale && single && scale.beats !== null ? (scale.beats === scale.days ? `The best day of the last ${scale.days}.` : `Better than ${scale.beats} of the last ${scale.days} days.`)
            : scale ? `Average over the last ${scale.days} days: ${pct(scale.avg)}.` : null;
    return (<div className="ov-halo">
      <section className="card ov-card" aria-labelledby="ov-conv">
        <div className="ov-card-head"><h2 id="ov-conv" className="serif ov-serif">Store conversion</h2></div>
        <div className="ov-gauge">
          <svg viewBox="0 0 320 190" role="img" aria-label={has ? `Conversion ${pct(value)}${scale ? `; recent average ${pct(scale.avg)}` : ''}` : 'Conversion not available yet'}>
            {scale ? (<>
              <path d={arc(R, 0, t(scale.low) - gap)} className="ov-zone z-low"/>
              <path d={arc(R, t(scale.low) + gap, t(scale.high) - gap)} className="ov-zone z-mid butt"/>
              <path d={arc(R, t(scale.high) + gap, 1)} className="ov-zone z-high"/>
            </>) : <path d={arc(R, 0, 1)} className="ov-zone z-none"/>}
            <path d={arc(r, 0, 1)} className="ov-track"/>
            {has && t(value) > 0.005 ? <path d={arc(r, 0, t(value))} className="ov-prog"/> : null}
            {a1 ? <line x1={a1[0]} y1={a1[1]} x2={a2[0]} y2={a2[1]} className="ov-avg-tick"/> : null}
            {k ? <circle cx={k[0]} cy={k[1]} r="7" className="ov-knob"/> : null}
          </svg>
          {k ? <span className="ov-gchip" style={{ left: `${(k[0] / 320) * 100}%`, top: `${(k[1] / 190) * 100}%` }}><span className="dot"/>{single ? 'This day' : 'Chosen days'}</span> : null}
          <div className="ov-gmid">
            <div className="ov-big num" style={{ fontSize: 46 }}>{has ? <CountUp value={pct(value)}/> : '—'}</div>
            <div className="muted small">of visits ended in an order</div>
          </div>
        </div>
        {scale ? <div className="ov-gends"><span>{pct(scale.lo, 1)}</span><span>┃ average {pct(scale.avg)}</span><span>{pct(scale.hi, 1)}</span></div> : null}
        {scale ? (<div className="row" style={{ justifyContent: 'center', gap: 6, marginTop: 10 }}>
          <span className="lane-chip lane-due" title={`Under ${pct(scale.low)}`}>Below usual</span>
          <span className="lane-chip lane-event" title={`${pct(scale.low)} to ${pct(scale.high)}`}>Usual</span>
          <span className="lane-chip lane-live" title={`${pct(scale.high)} or more`}>Strong</span>
        </div>) : null}
        {note ? <p className="muted small" style={{ textAlign: 'center', margin: '10px 0 0' }}>{note}</p> : null}
        <div className="ov-wells">
          <div className="ov-well"><span className="lbl">Revenue</span><b className="num">{revenue?.value === null || revenue?.value === undefined ? '—' : <CountUp value={money(revenue.value, 'USD', 0)}/>}</b><ChangeChip block={revenue}/></div>
          <div className="ov-well"><span className="lbl">Average order</span><b className="num">{aov?.value === null || aov?.value === undefined ? '—' : <CountUp value={money(aov.value)}/>}</b><ChangeChip block={aov}/></div>
          {perVisit?.value !== null && perVisit?.value !== undefined ? (<div className="ov-well wide" title="Revenue ÷ visits, complete days only">
            <span className="lbl">Revenue per visit</span><b className="num"><CountUp value={money(perVisit.value)}/></b><ChangeChip block={perVisit}/></div>) : null}
        </div>
      </section>
    </div>);
}

/* ------------------------------------------------------------------ visits by day */
/** Visits per day as bars coloured by how well each day converted; pointing at a bar shows the day's figures. */
export function VisitsCard({ trend, total, baseTotal, scale }) {
    const [span, setSpan] = useState(14);
    const [hover, setHover] = useState(null);
    const rows = trend.slice(-span);
    const max = Math.max(1, ...rows.map((r) => r.sessions || 0));
    let busiest = 0;
    rows.forEach((r, i) => { if ((r.sessions || 0) > (rows[busiest]?.sessions || 0)) busiest = i; });
    const show = hover ?? (rows.length ? busiest : null);
    const s = show !== null ? rows[show] : null;
    const ch = total?.sessions !== undefined && baseTotal?.sessions ? ((total.sessions - baseTotal.sessions) / baseTotal.sessions) * 100 : null;
    return (<section className="card ov-card" aria-labelledby="ov-visits">
      <div className="ov-card-head">
        <h2 id="ov-visits">Visits by day <InfoMark text="Store visits from every channel, complete days only. Colour: how well the day converted."/></h2>
        <Seg label="Days shown" options={[{ key: 14, label: '14D' }, { key: 28, label: '28D' }]} value={span} onChange={(v) => { setSpan(v); setHover(null); }}/>
      </div>
      <div className="row" style={{ gap: 6, marginBottom: 4 }}>
        <span className="ov-big num" style={{ fontSize: 30 }}>{total?.sessions !== undefined ? <CountUp value={fmtInt(total.sessions)}/> : '—'}</span>
        <ChangeChip v={ch}/>
      </div>
      {rows.length ? (<>
        <div className="ov-vbars" onMouseLeave={() => setHover(null)}>
          {rows.map((r, i) => (<span key={r.date} className={`ov-vbar z-${conversionBand(r.conversion_rate, scale) ?? 'none'}${i === show ? ' on' : ''}`}
            style={{ height: `${((r.sessions || 0) / max) * 100}%` }} onMouseEnter={() => setHover(i)}/>))}
          {s ? (<div className="ov-vtip" style={{ left: `${Math.min(70, Math.max(0, ((show + 0.5) / rows.length) * 100 - 15))}%` }}>
            <b>{weekday(s.date)} {fmtDay(s.date)}</b>
            {fmtInt(s.sessions)} visits{hover === null ? ', the busiest day' : ''}<br/>{pct(s.conversion_rate)} converted · {fmtInt(s.completed_checkout)} checkouts completed
          </div>) : null}
        </div>
        <div className="ov-vdays">{rows.map((r, i) => <span key={r.date}>{span === 14 || (rows.length - 1 - i) % 4 === 0 ? weekday(r.date).slice(0, 1) : ''}</span>)}</div>
      </>) : <div className="muted small">No complete day in this range yet.</div>}
    </section>);
}

/* ------------------------------------------------------------------ side tiles (above Orders and Visits) */
const MONEY_PARTS = [
    { key: 'net', name: 'Net sales', color: 'var(--info)' },
    { key: 'returns', name: 'Returns', color: '#eaa39a' },
    { key: 'discounts', name: 'Discounts', color: 'var(--saffron)' },
];

/** Total sales for the chosen days against the comparison, and a ring of where the gross sales went (net sales,
 * returns, discounts), from the Sales tab's breakdown. */
export function SalesTile({ q, onOpen }) {
    const d = q.data;
    const row = (k) => d?.rows?.find((r) => r.key === k);
    const total = row('total');
    const gross = row('gross')?.value || 0;
    const parts = MONEY_PARTS.map((m) => ({ ...m, value: Math.max(0, row(m.key)?.value || 0) }));
    const C = 2 * Math.PI * 46;
    let at = 0;
    const arcs = gross ? parts.filter((x) => x.value).map((x) => {
        const len = (x.value / gross) * C;
        const a = { ...x, dash: `${Math.max(len - 2, 0.5)} ${C}`, off: -at };
        at += len;
        return a;
    }) : [];
    const tax = row('tax')?.value || 0;
    return (<section className="card ov-card ov-tile" aria-labelledby="ov-sales-tile">
      <div className="ov-card-head"><h2 id="ov-sales-tile" className="serif ov-serif">Sales</h2>{d ? <span className="muted xs">{d.baseline_label}</span> : null}</div>
      {q.error ? <ExplainedError error={q.error} onRetry={q.reload}/> : !total ? <div className="muted small">No sales figures for these days.</div> : (<>
        <div className="row" style={{ gap: 8 }}>
          <span className="ov-big num" style={{ fontSize: 34 }}><CountUp value={money(total.value, 'USD', 0)}/></span>
          {total.too_early ? <span className="muted xs">too early to compare</span> : <ChangeChip v={total.change_pct ?? null}/>}
        </div>
        <div className="muted xs">total sales · net {money(row('net')?.value ?? 0, 'USD', 0)}{tax ? ` + tax ${money(tax, 'USD', 0)}` : ''}{row('shipping')?.value ? ` + shipping ${money(row('shipping').value, 'USD', 0)}` : ''}</div>
        {gross ? (<div className="ov-money">
          <svg viewBox="0 0 120 120" role="img" aria-label={`Of ${money(gross, 'USD', 0)} gross sales: ${parts.map((x) => `${x.name.toLowerCase()} ${pct((x.value / gross) * 100, 0)}`).join(', ')}`}>
            <circle cx="60" cy="60" r="46" fill="none" stroke="var(--line-2)" strokeWidth="16"/>
            {arcs.map((a, i) => <circle key={a.key} className="ring-arc" style={{ animationDelay: `${i * 70}ms` }} cx="60" cy="60" r="46" fill="none" stroke={a.color} strokeWidth="16"
              strokeDasharray={a.dash} strokeDashoffset={a.off} transform="rotate(-90 60 60)"><title>{`${a.name}: ${money(a.value, 'USD', 0)}`}</title></circle>)}
            <text x="60" y="56" textAnchor="middle" className="ov-money-sub">gross</text>
            <text x="60" y="73" textAnchor="middle" className="ov-money-num">{money(gross, 'USD', 0)}</text>
          </svg>
          <div className="ov-money-lg">{parts.map((x) => (<div key={x.key}><i style={{ background: x.color }}/><span>{x.name}</span><b className="num">{pct((x.value / gross) * 100, 1)}</b></div>))}</div>
        </div>) : null}
        <button type="button" className="link-btn ov-tile-link" onClick={onOpen}>Where the gross sales went · Sales tab →</button>
      </>)}
    </section>);
}

/** Mobile page speed (LCP, INP, CLS at the 75th percentile, each with its share of good page loads as a ring) and
 * site search, for the latest days Shopify has published: it publishes them 1-2 days late, so this tile always reads
 * the 7 days ending two days ago, whatever range the page shows. */
export function HealthTile({ q, onOpen }) {
    const d = q.data;
    const devices = d?.devices ?? {};
    const name = devices.Mobile ? 'Mobile' : Object.keys(devices)[0];
    const dev = name ? devices[name] : null;
    const ratings = dev ? VITALS.map((v) => dev[v.key]?.rating).filter(Boolean) : [];
    const worst = ratings.includes('poor') ? 'poor' : ratings.includes('needs_improvement') ? 'needs_improvement' : ratings.length ? 'good' : null;
    const R = 2 * Math.PI * 26;
    const sr = d?.search;
    return (<section className="card ov-card ov-tile" aria-labelledby="ov-health-tile">
      <div className="ov-card-head"><h2 id="ov-health-tile" className="serif ov-serif">Site health <InfoMark text="Page speed at the 75th percentile: LCP (main content shows), INP (reacts to a tap), CLS (layout stays put). Each ring is the share of page loads Google rates good; its colour is the rating. Shopify publishes these 1-2 days late, so the tile shows the 7 days ending two days ago."/></h2>
        {worst ? <span className={`lane-chip ${RATING[worst].lane}`}>{worst === 'good' ? 'All good' : RATING[worst].label}</span> : null}</div>
      {q.error ? <ExplainedError error={q.error} onRetry={q.reload}/> : !d ? null : !dev || !d.speed_available ? (
        <div className="muted small">{d.late_note || 'Shopify has no page speed figures for these days yet.'}</div>
      ) : (<>
        <div className="muted xs">{name} page speed · {fmtDay(d.from)} – {fmtDay(d.to)}</div>
        <div className="ov-vitals">
          {VITALS.map((v) => {
              const m = dev[v.key] ?? {};
              const share = m.good_share ?? 0;
              const r = RATING[m.rating];
              const tone = m.rating === 'good' ? 'var(--z-high)' : m.rating === 'poor' ? 'var(--z-low)' : 'var(--z-mid)';
              return (<div key={v.key} title={v.help}>
                <svg viewBox="0 0 64 64" role="img" aria-label={`${v.label}: ${fmtVital(v.key, m.p75)}, ${pct(share, 0)} of page loads good`}>
                  <circle cx="32" cy="32" r="26" fill="none" stroke="var(--line-2)" strokeWidth="7"/>
                  <circle className="ring-arc" cx="32" cy="32" r="26" fill="none" stroke={tone} strokeWidth="7" strokeLinecap="round"
                    strokeDasharray={`${(R * share) / 100} ${R}`} transform="rotate(-90 32 32)"/>
                  <text x="32" y="36" textAnchor="middle" className="ov-vital-pct">{pct(share, 0)}</text>
                </svg>
                <span className="k">{v.key.toUpperCase()} <span className="v num">{fmtVital(v.key, m.p75)}</span></span>
                {r ? <span className="sr-only">{r.label}</span> : null}
              </div>);
          })}
        </div>
        {sr && sr.share_of_sessions ? (<div className="ov-search" title={`${pct(sr.share_of_sessions, 1)} of visits used site search`}>
          Searchers {sr.searcher_conversion_rate !== null ? <>convert <b className="num">{pct(sr.searcher_conversion_rate)}</b> vs {pct(sr.non_searcher_conversion_rate)}</> : 'made no order yet'}</div>) : null}
      </>)}
      <button type="button" className="link-btn ov-tile-link" onClick={onOpen}>Site health →</button>
    </section>);
}

/* ------------------------------------------------------------------ sales chart */
const FIELDS = [{ key: 'net', label: 'Net sales' }, { key: 'revenue', label: 'Total sales' }, { key: 'orders', label: 'Orders' }];
const MODES = [{ key: 'area', label: 'Area' }, { key: 'bars', label: 'Bars' }, { key: 'table', label: 'Table' }];
const WINDOWS = [{ key: 7, label: '7D' }, { key: 14, label: '14D' }, { key: 28, label: '28D' }];

function smooth(pts) {
    const f = (n) => n.toFixed(1);
    if (!pts.length) return '';
    let d = `M${f(pts[0][0])},${f(pts[0][1])}`;
    for (let i = 0; i < pts.length - 1; i++) {
        const a = pts[i - 1] || pts[i], b = pts[i], c = pts[i + 1], e = pts[i + 2] || c;
        d += ` C${f(b[0] + (c[0] - a[0]) / 6)},${f(b[1] + (c[1] - a[1]) / 6)} ${f(c[0] - (e[0] - b[0]) / 6)},${f(c[1] - (e[1] - b[1]) / 6)} ${f(c[0])},${f(c[1])}`;
    }
    return d;
}

/**
 * Sales by day for the last 7, 14 or 28 days of the chosen range, against the same number of days before.
 * Calendar events are shaded, the busiest day is labelled, the dotted line is the daily average, and pointing
 * at a day shows both periods. Area, bars or a table; the table downloads as CSV.
 * `current`/`previous`: the API's 28-day sales trend and the 28 days before. `events`: [{ date, name }].
 */
export function SalesChart({ current, previous, events, changes, lastDay }) {
    const [n, setN] = useState(28);
    const [mode, setMode] = useState('area');
    const [field, setField] = useState('net');
    const [showPrev, setShowPrev] = useState(true);
    const [showEv, setShowEv] = useState(true);
    const [hover, setHover] = useState(null);
    const [ref, W] = useWidth();
    const win = salesWindow(current, previous, n);
    const cur = win.current, prev = win.previous;
    const val = (r) => (r ? Number(r[field] ?? 0) : null);
    const fmt = field === 'orders' ? fmtInt : (v) => money(v, 'USD', 0);
    const axisFmt = field === 'orders' ? fmtInt : (v) => (v >= 1000 ? `$${Number((v / 1000).toFixed(1))}k` : `$${v}`);
    const total = cur.reduce((a, r) => a + val(r), 0);
    const ptotal = prev.length === cur.length ? prev.reduce((a, r) => a + val(r), 0) : null;
    const tch = ptotal ? ((total - ptotal) / ptotal) * 100 : null;
    const avg = cur.length ? total / cur.length : 0;
    const H = 270, X0 = 52, X1 = W - 14, Y0 = 26, Y1 = H - 30;
    const ax = niceAxis(Math.max(1, ...cur.map(val), ...(showPrev ? prev.map(val) : [])), 3);
    const m = cur.length;
    // Lines run edge to edge; bars sit in equal slots so the first and last bar are not cut in half.
    const slots = mode === 'bars' || m <= 1;
    const xs = slots ? (i) => X0 + ((i + 0.5) * (X1 - X0)) / Math.max(1, m) : (i) => X0 + (i * (X1 - X0)) / (m - 1);
    const ys = (v) => Y1 - (v / ax.top) * (Y1 - Y0);
    const line = smooth(cur.map((r, i) => [xs(i), ys(val(r))]));
    const prevLine = prev.length === m ? smooth(prev.map((r, i) => [xs(i), ys(val(r))])) : '';
    const stepW = slots ? (X1 - X0) / Math.max(1, m) : (X1 - X0) / (m - 1);
    const bw = Math.min(26, stepW * 0.5);
    let pk = 0;
    cur.forEach((r, i) => { if (val(r) > val(cur[pk])) pk = i; });
    const evByDate = new Map((events || []).map((e) => [e.date, e.name]));
    const evIdx = cur.map((r, i) => (evByDate.has(r.date) ? i : -1)).filter((i) => i >= 0);
    const every = Math.max(1, Math.ceil(m / Math.max(2, Math.floor((X1 - X0) / 64))));
    const h = hover !== null && hover < m ? hover : null;
    const pick = (e) => {
        const r = e.currentTarget.getBoundingClientRect();
        const f = (e.clientX - r.left - X0) / (X1 - X0);
        const i = slots ? Math.floor(f * m) : Math.round(f * (m - 1));
        setHover(Math.max(0, Math.min(m - 1, i)));
    };
    const tableRows = cur.map((r, i) => {
        const p = prev[i];
        const c = p && val(p) ? ((val(r) - val(p)) / val(p)) * 100 : null;
        return { date: r.date, v: val(r), p: p ? val(p) : null, c, orders: r.orders };
    });
    const download = () => {
        const label = FIELDS.find((x) => x.key === field).label;
        const csv = toCsv([['Day', label, `Previous ${label.toLowerCase()}`, 'Change %', 'Orders'],
            ...tableRows.map((r) => [r.date, r.v, r.p, r.c === null ? '' : r.c.toFixed(1), r.orders])]);
        const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
        const a = document.createElement('a');
        a.href = url;
        a.download = `cro-${field}-${cur[0]?.date ?? ''}-to-${cur[m - 1]?.date ?? ''}.csv`;
        a.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
    };
    // All 56 days (the 28 before and the 28 drawn) for the strip under the chart.
    const all = [...(previous || []), ...(current || [])];
    const aMax = Math.max(1, ...all.map(val));
    const strip = all.length > 1 ? `M0,40 ${all.map((r, i) => `L${((i / (all.length - 1)) * 1000).toFixed(1)},${(38 - (val(r) / aMax) * 32).toFixed(1)}`).join(' ')} L1000,40 Z` : '';
    const winLeft = all.length > 1 ? ((all.length - m) / (all.length - 1)) * 100 : 0;
    const inWindow = (changes || []).filter((c) => m && c.entry_date >= cur[0].date && c.entry_date <= cur[m - 1].date);

    return (<section className="card ov-card ov-sales" aria-labelledby="ov-sales">
      <div className="ov-card-head" style={{ alignItems: 'flex-start', flexWrap: 'wrap' }}>
        <div>
          <h2 id="ov-sales" style={{ fontSize: 15 }}>{FIELDS.find((x) => x.key === field).label} by day</h2>
          <div className="muted small">The {m} days ending {lastDay ? fmtDay(lastDay) : 'on the last chosen day'}, against the {m} days before. Point at a day for its figures.</div>
        </div>
        <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
          <span className="lane-chip lane-research"><span className="ov-swatch"/>This period</span>
          <button type="button" className={`lane-chip ov-toggle plain${showPrev ? '' : ' off'}`} aria-pressed={showPrev} onClick={() => setShowPrev(!showPrev)}><span className="ov-swatch dash"/>Previous</button>
          <button type="button" className={`lane-chip lane-event ov-toggle${showEv ? '' : ' off'}`} aria-pressed={showEv} onClick={() => setShowEv(!showEv)}><Icon name="star" size="sm"/>Events</button>
          <Seg label="Chart type" options={MODES} value={mode} onChange={setMode}/>
          <button type="button" className="ov-ibtn" onClick={download} aria-label="Download these days as CSV" title="Download these days as CSV"><Icon name="download" size="sm"/></button>
        </div>
      </div>
      <div className="row" style={{ justifyContent: 'space-between', gap: 10, margin: '0 0 8px', flexWrap: 'wrap' }}>
        <div className="row" style={{ gap: 10 }}>
          <span className="ov-big num" style={{ fontSize: 28 }}>{fmt(total)}</span>
          {tch !== null ? <span className={`lane-chip ${tch >= 0 ? 'lane-live' : 'lane-due'}`}>{arrow(tch)}</span> : null}
          {ptotal !== null ? <span className="muted small">vs the {m} days before ({fmt(ptotal)})</span> : null}
        </div>
        <Seg label="Measure" options={FIELDS} value={field} onChange={setField}/>
      </div>

      {!m ? <div className="muted small">No sales in these days yet.</div> : mode === 'table' ? (
        <div className="ov-table-wrap"><table className="t compact">
          <thead><tr><th>Day</th><th className="r">{FIELDS.find((x) => x.key === field).label}</th><th className="r">Previous</th><th className="r">Change</th><th className="r">Orders</th></tr></thead>
          <tbody>{[...tableRows].reverse().map((r) => (<tr key={r.date}><td>{weekday(r.date)} {fmtDay(r.date)}{evByDate.has(r.date) ? <> <span className="lane-chip lane-event">{evByDate.get(r.date)}</span></> : null}</td>
            <td className="r num">{fmt(r.v)}</td><td className="r num">{r.p === null ? '—' : fmt(r.p)}</td>
            <td className={`r num ${r.c === null ? '' : r.c >= 0 ? 'chg-up' : 'chg-down'}`}>{r.c === null ? '—' : arrow(r.c)}</td><td className="r num">{fmtInt(r.orders)}</td></tr>))}</tbody>
        </table></div>
      ) : (
        <div className="ov-chart" ref={ref}>
          <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} role="img" onPointerMove={pick} onPointerLeave={() => setHover(null)}
            aria-label={`${FIELDS.find((x) => x.key === field).label} per day for ${m} days, average ${fmt(avg)} a day, highest ${fmt(val(cur[pk]))} on ${fmtDay(cur[pk].date)}`}>
            {showEv ? evIdx.map((i) => <rect key={i} x={xs(i) - Math.max(stepW / 2, 9)} y={Y0} width={Math.max(stepW, 18)} height={Y1 - Y0} className="ov-band"/>) : null}
            {[0, 1, 2, 3].map((k) => k * ax.step <= ax.top + 1e-9 ? (<g key={k}>
              <line x1={X0} x2={X1} y1={ys(k * ax.step)} y2={ys(k * ax.step)} className="ov-grid"/>
              <text x={X0 - 8} y={ys(k * ax.step) + 4} className="ov-ylab">{axisFmt(k * ax.step)}</text>
            </g>) : null)}
            {mode === 'bars' ? (<>
              {showPrev && prev.length === m ? prev.map((r, i) => <rect key={`p${i}`} x={xs(i) - bw / 2 - 3} y={ys(val(r))} width={bw + 6} height={Y1 - ys(val(r))} className="ov-pbar"/>) : null}
              {cur.map((r, i) => <rect key={`c${i}`} x={xs(i) - bw / 2} y={ys(val(r))} width={bw} height={Math.max(0, Y1 - ys(val(r)))} rx="3" className={`ov-cbar${h === i ? ' on' : ''}`}/>)}
            </>) : (<>
              <path d={`${line} L${xs(m - 1)},${Y1} L${xs(0)},${Y1} Z`} className="ov-area"/>
              {showPrev && prevLine ? <path d={prevLine} className="ov-pline"/> : null}
              <path d={line} className="ov-line"/>
            </>)}
            <line x1={X0} x2={X1} y1={ys(avg)} y2={ys(avg)} className="ov-avg"/>
            <text x={X0 + 6} y={ys(avg) - 6} className="ov-avg-lab">Avg {fmt(avg)} a day</text>
            {cur.map((r, i) => (i % every === (m - 1) % every ? <text key={r.date} x={xs(i)} y={H - 10} className="ov-xlab">{fmtDay(r.date)}</text> : null))}
            {h !== null ? (<>
              <line x1={xs(h)} x2={xs(h)} y1={Y0} y2={Y1} className="ov-cross"/>
              <circle cx={xs(h)} cy={ys(val(cur[h]))} r="5" className="ov-dot"/>
            </>) : <circle cx={xs(pk)} cy={ys(val(cur[pk]))} r="5" className="ov-dot"/>}
          </svg>
          <span className="ov-peak" style={{ left: xs(pk), top: ys(val(cur[pk])) }}>{fmt(val(cur[pk]))}</span>
          {showEv ? evIdx.map((i) => <span key={i} className="lane-chip lane-event ov-evlab" style={{ left: xs(i), top: Y1 - 26 }}><Icon name="star" size="sm"/>{evByDate.get(cur[i].date)}</span>) : null}
          {h !== null ? (() => {
              const p = prev[h];
              const c = p && val(p) ? ((val(cur[h]) - val(p)) / val(p)) * 100 : null;
              const right = xs(h) > W * 0.62;
              return (<div className="ov-tip" style={{ left: xs(h), transform: right ? 'translateX(calc(-100% - 14px))' : 'translateX(14px)' }}>
                <div className="d">{weekday(cur[h].date)}, {fmtDay(cur[h].date)}{evByDate.has(cur[h].date) ? <span className="lane-chip lane-event">{evByDate.get(cur[h].date)}</span> : null}</div>
                <div className="r"><span className="ov-swatch"/><span>This period</span><b className="num">{fmt(val(cur[h]))}</b></div>
                {p ? <div className="r muted"><span className="ov-swatch dash"/><span>Previous{p.date ? ` (${fmtDay(p.date)})` : ''}</span><span className="num">{fmt(val(p))}</span></div> : null}
                {c !== null ? <div className={c >= 0 ? 'chg-up' : 'chg-down'} style={{ marginTop: 6 }}>{arrow(c)} vs previous</div> : null}
              </div>);
          })() : null}
        </div>
      )}

      {strip ? (<div className="ov-brush" aria-hidden="true">
        <svg viewBox="0 0 1000 40" preserveAspectRatio="none"><path d={strip}/></svg>
        <span className="ov-win" style={{ left: `${winLeft}%` }}/>
      </div>) : null}
      <div className="row" style={{ justifyContent: 'space-between', marginTop: 8 }}>
        <span className="muted xs">The strip shows {all.length} days; the highlighted part is drawn above.</span>
        <Seg label="Days shown" options={WINDOWS} value={n} onChange={(v) => { setN(v); setHover(null); }}/>
      </div>
      {inWindow.length ? (<div className="small" style={{ marginTop: 10 }}><span className="muted">Store changes in these days:</span>
        <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>{inWindow.slice(0, 6).map((e) => <li key={e.id}><b>{fmtDay(e.entry_date)}</b> · {e.change}</li>)}</ul></div>) : null}
    </section>);
}

/* ------------------------------------------------------------------ journey */
const STEPS = [
    { k: 'v', label: 'Visited', lane: 'lane-research', color: 'var(--info)', value: (t) => t.sessions, prev: () => null, left: (t) => t.sessions - t.added_to_cart, leftLabel: 'left without a cart' },
    { k: 'c', label: 'Added to cart', lane: 'lane-draft', color: 'var(--cpc)', value: (t) => t.added_to_cart, prev: (t) => t.sessions, left: (t) => t.added_to_cart - t.reached_checkout, leftLabel: 'left the cart' },
    { k: 'k', label: 'Reached checkout', lane: 'lane-event', color: 'var(--saffron)', value: (t) => t.reached_checkout, prev: (t) => t.added_to_cart, left: (t) => t.reached_checkout - t.completed_checkout, leftLabel: 'left at payment' },
    { k: 'p', label: 'Bought', lane: 'lane-live', color: 'var(--ok)', value: (t) => t.completed_checkout, prev: (t) => t.reached_checkout, left: () => null },
];

/** The shopper journey as four steps; each bar is the share of the step before that got through. */
export function JourneyCard({ t }) {
    if (!t || !t.sessions) return null;
    return (<section className="card ov-card" aria-labelledby="ov-journey">
      <div className="ov-card-head"><h2 id="ov-journey">Shopper journey</h2><span className="muted xs">Bar: share of the step before</span></div>
      <div className="ov-steps" role="list">
        {STEPS.map((s) => {
            const v = s.value(t), p = s.prev(t);
            const share = p ? Math.max(0, Math.min(1, v / p)) : 1;
            const left = s.left(t);
            return (<div key={s.k} className="ov-step" role="listitem">
              <span className={`lane-chip ${s.lane}`}>{s.label}</span>
              <b className="num"><CountUp value={fmtInt(v)}/></b>
              <span className="ov-step-bar" title={p ? `${Math.round(share * 100)}% of the step before` : 'All visits'}><span style={{ width: `${share * 100}%`, background: s.color }}/></span>
              {left !== null ? <span className="lane-chip lane-due">{fmtInt(Math.max(0, left))} {s.leftLabel}</span> : <span className="muted xs">{pct(t.conversion_rate)} of visits</span>}
            </div>);
        })}
      </div>
    </section>);
}

/* ------------------------------------------------------------------ what changed */
/**
 * The biggest reasons orders moved against the comparison, as sentences: more or fewer visits from a device or source
 * (traffic) or the same visitors buying more or less often (conversion). From /api/cro/traffic-changes.
 */
export function MoversCard({ q }) {
    if (q.error) return <ExplainedError error={q.error} onRetry={q.reload}/>;
    const d = q.data;
    if (!d) return null;
    return (<section className="card ov-card" aria-labelledby="ov-movers">
      <div className="ov-card-head"><h2 id="ov-movers">What moved orders <InfoMark text="Each change in purchases is split into a visits part (more or fewer visitors) and a conversion part (the same visitors buying more or less often). Bots left out."/></h2></div>
      {d.too_early ? <div className="muted small">Fewer than 500 visits in these days: too early to say what moved orders.</div>
          : d.movers.length ? (<div className="ov-movers">
            {d.movers.map((m) => (<div key={`${m.dimension}-${m.segment}-${m.kind}`} className="ov-mover">
              <span className={`lane-chip ${m.good ? 'lane-live' : 'lane-due'}`}>{m.good ? '▲' : '▼'} {Math.abs(Math.round(m.effect))}</span>
              <span>{m.text}</span>
              <span className="muted xs">{m.kind === 'traffic' ? 'visits' : 'conversion'} · {m.dimension}</span>
            </div>))}
          </div>) : <div className="muted small">No device or source changed purchases by one or more against the comparison.</div>}
    </section>);
}

/* ------------------------------------------------------------------ best hours */
const DAY_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

/** Conversion by weekday and hour (store time) over the last 28 complete days, shaded against the average. */
export function HeatmapCard({ q }) {
    if (q.error) return <ExplainedError error={q.error} onRetry={q.reload}/>;
    const d = q.data;
    if (!d) return null;
    const byOrders = d.metric === 'orders';
    const maxOrders = Math.max(1, ...d.cells.map((c) => c.orders));
    const level = (c) => (byOrders ? (c.orders ? Math.min(4, Math.floor((c.orders / maxOrders) * 5)) : null) : heatLevel(c.cvr, d.average_cvr));
    const best = byOrders ? [] : bestHours(d.cells, 3);
    const at = (w, h) => d.cells[w * 24 + h];
    const info = `Last ${d.days} complete days, store time. ${byOrders ? 'Orders placed per hour.' : 'Conversion per weekday-hour against the average; hours with under 20 visits are left blank.'}`;
    return (<section className="card ov-card" aria-labelledby="ov-heat">
      <div className="ov-card-head"><h2 id="ov-heat">Best hours to sell <InfoMark text={info}/></h2></div>
      {d.note ? <div className="muted xs" style={{ marginBottom: 8 }}>{d.note}</div> : null}
      {best.length ? <div className="small" style={{ marginBottom: 8 }}>Best: {best.map((c) => `${DAY_NAMES[c.weekday]} ${fmtHour(c.hour)} (${pct(c.cvr, 1)})`).join(' · ')}{d.average_cvr !== null ? <span className="muted"> · average {pct(d.average_cvr)}</span> : null}</div> : null}
      <div className="heatmap-wrap">
        <div className="heatmap" role="img" aria-label={byOrders ? 'Orders by weekday and hour' : 'Conversion by weekday and hour'}>
          <div className="hm-row"><span className="hm-d"/>{Array.from({ length: 24 }, (_, h) => <span key={h} className="hm-h">{h % 3 === 0 ? h : ''}</span>)}</div>
          {DAY_NAMES.map((day, w) => (<div key={day} className="hm-row">
            <span className="hm-d">{day}</span>
            {Array.from({ length: 24 }, (_, h) => {
                const c = at(w, h);
                const lvl = c ? level(c) : null;
                const tip = c ? `${day} ${fmtHour(h)}: ${byOrders ? `${c.orders} orders` : `${fmtInt(c.sessions)} visits, ${c.cvr === null ? 'too few for a rate' : `${pct(c.cvr)} converted`}`}` : '';
                return <span key={h} className={`hm-c${lvl === null ? '' : ` h${lvl}`}`} title={tip}/>;
            })}
          </div>))}
        </div>
      </div>
      <div className="hm-legend muted xs"><span className="hm-c h0"/>{byOrders ? 'fewest' : 'well below'}<span className="hm-c h2"/>{byOrders ? '' : 'average'}<span className="hm-c h4"/>{byOrders ? 'most orders' : 'well above'}</div>
    </section>);
}

/* ------------------------------------------------------------------ order value and channels */
/** Average order value by day (against the days before) and sales by sales channel, from Shopify's sales report. */
export function TrendsRow({ q }) {
    if (q.error) return <ExplainedError error={q.error} onRetry={q.reload}/>;
    const d = q.data;
    if (!d) return null;
    const prev = d.previous_aov.map((r, i) => ({ ...r, date: d.aov[i]?.date ?? r.date }));
    return (<section className="card ov-card" aria-labelledby="ov-aov">
      <div className="ov-card-head"><h2 id="ov-aov">Average order and channels <InfoMark text="Shopify's average order value per day (gross sales less discounts, per order), and total sales by sales channel."/></h2></div>
      {d.aov.length > 1 ? <LineChart ariaLabel="Average order value by day" height={170} yFormat={(v) => money(v, 'USD', 0)}
        series={[seriesOf(d.aov, 'aov', 'aov', 'Average order', 'var(--info)'), ...(prev.length ? [seriesOf(prev, 'aov', 'prev', 'Days before', 'var(--line)')] : [])]}/>
        : <div className="muted small">Needs at least two days.</div>}
      <div className="small strong mt-8">Sales by channel</div>
      <BarList format={(v) => money(v, 'USD', 0)} rows={d.channels.map((c) => ({ key: c.label, label: readable(c.label), value: c.total_sales, extra: `${pct(c.share_pct, 0)} · ${fmtInt(c.orders)} orders` }))}/>
    </section>);
}
