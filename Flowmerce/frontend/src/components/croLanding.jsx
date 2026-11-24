'use client';
/* Landing pages week on week / month on month, and one page's deep dive in a left-side panel (owner request
 * 2026-11-23, laid out like the CRO prototype's "Week / Month compare" and page deep dive). Every figure comes from
 * /api/cro/landing-compare and /api/cro/landing-page (modules/cro/landing_detail.py); this file only lays it out.
 * Both use their own fixed windows of complete days: the last 7 against the 7 before, the last 30 against the 30
 * before, whatever range the tab's date bar shows. */
import { useState } from 'react';
import { qs, useApi } from '../lib/api';
import { fmtDay, fmtInt } from '../lib/format';
import { money, pct, readable, seriesOf, signedPct, toCsv } from '../lib/cro';
import { LineChart } from './charts';
import { CroGate, ExplainedError, Seg } from './cro';
import { Icon } from './Icon';
import { Drawer } from './overlays';
import { Button, Card, LoadingBlock } from './ui';

const MODES = [{ key: 'week', label: 'Week on week' }, { key: 'month', label: 'Month on month' }];
const SORTS = [
    { key: 'sessions', label: 'Sessions', by: (p) => p.now.sessions },
    { key: 'traffic', label: 'Biggest traffic change', by: (p) => Math.abs(p.change.sessions) },
    { key: 'cvr_drop', label: 'Biggest conversion drop', by: (p) => (p.low_data || p.change.conversion_pts === null ? -Infinity : -p.change.conversion_pts) },
    { key: 'bounce_rise', label: 'Biggest bounce rise', by: (p) => (p.low_data || p.change.bounce_pts === null ? -Infinity : p.change.bounce_pts) },
    { key: 'revenue', label: 'Revenue', by: (p) => p.now.revenue },
    { key: 'revenue_change', label: 'Biggest revenue change', by: (p) => Math.abs(p.change.revenue) },
];
const span = (s) => (s ? `${fmtDay(s.from)} – ${fmtDay(s.to)}` : '');
const signedInt = (v) => (v === null || v === undefined ? '—' : `${v > 0 ? '+' : ''}${fmtInt(v)}`);
const signedMoney = (v) => (v === null || v === undefined ? '—' : `${v > 0 ? '+' : v < 0 ? '−' : ''}${money(Math.abs(v), 'USD', 0)}`);
const pts = (v) => (v === null || v === undefined ? '—' : `${v > 0 ? '+' : ''}${Number(v).toFixed(2)} pts`);

/** A change, coloured green when it is good for the store and red when bad (`down` true for rates where lower is
 * better, like bounce). Grey "low data" when either period had too few visits. */
function Chg({ text, v, down, low }) {
    if (low) return <span className="lp-chg muted">low data</span>;
    if (v === null || v === undefined || v === 0) return <span className="lp-chg muted">{text}</span>;
    const good = down ? v < 0 : v > 0;
    return <span className={`lp-chg ${good ? 'up' : 'down'}`}>{text}</span>;
}

/** One figure of the compare table: the value now, its change and what it was. */
function Cell({ now, was, change, v, down, low }) {
    return (<td className="r lp-cell"><b className="num">{now}</b><Chg text={change} v={v} down={down} low={low}/><span className="muted xs">was {was}</span></td>);
}

/**
 * Every landing page week on week or month on month: sessions, bounce, add to cart, conversion, orders, revenue and
 * revenue per visit, each with its change and earlier value; filter by page type, sort, and "Deep dive" per page.
 */
export function LandingCompare({ brand, onOpen }) {
    const [mode, setMode] = useState('week');
    const [type, setType] = useState('');
    const [sort, setSort] = useState('sessions');
    const [all, setAll] = useState(false);
    const q = useApi(`/cro/landing-compare${qs({ brand, mode })}`);
    return (<Card title="Week on week & month on month" flush
      sub={q.data ? `${span(q.data.current)} vs ${span(q.data.previous)} · complete days, whatever range is picked above` : 'Complete days'}
      actions={<Seg label="Compare" options={MODES} value={mode} onChange={(m) => { setMode(m); setAll(false); }}/>}>
      <CroGate query={q} rows={6}>
        {(d) => {
            const types = [...new Set(d.pages.map((p) => p.page_type))].sort();
            const by = SORTS.find((s) => s.key === sort) ?? SORTS[0];
            const rows = d.pages.filter((p) => !type || p.page_type === type).sort((a, b) => by.by(b) - by.by(a));
            const shown = all ? rows : rows.slice(0, 30);
            return (<>
              <div className="row pad-x lp-tools">
                <select className="input sm" value={type} onChange={(e) => setType(e.target.value)} aria-label="Page type"><option value="">All page types</option>{types.map((t) => <option key={t} value={t}>{t}</option>)}</select>
                <select className="input sm" value={sort} onChange={(e) => setSort(e.target.value)} aria-label="Sort by">{SORTS.map((s) => <option key={s.key} value={s.key}>Sort: {s.label}</option>)}</select>
                <span className="muted xs">Pages under {fmtInt(d.min_sessions)} visits in either period are marked &ldquo;low data&rdquo;.</span>
              </div>
              <div className="table-wrap"><table className="t compact lp-table">
                <thead><tr><th>Page</th><th className="r">Sessions</th><th className="r">Bounce</th><th className="r">Add to cart</th><th className="r">Conversion</th>
                  <th className="r">Orders</th><th className="r">Revenue</th><th className="r">Rev / session</th><th/></tr></thead>
                <tbody>{shown.map((p) => {
                    const n = p.now, b = p.before, c = p.change, low = p.low_data;
                    return (<tr key={p.path}>
                      <td style={{ maxWidth: 280 }}><button type="button" className="link-btn lp-path" title={p.path} onClick={() => onOpen(p.path, p.page_type)}>{p.path === '/' ? '/ (homepage)' : p.path}</button>
                        <span className="lane-chip plain">{p.page_type}</span></td>
                      <Cell now={fmtInt(n.sessions)} was={fmtInt(b.sessions)} change={`${signedInt(c.sessions)}${c.sessions_pct !== null ? ` (${signedPct(c.sessions_pct)})` : ''}`} v={c.sessions}/>
                      <Cell now={pct(n.bounce_rate)} was={pct(b.bounce_rate)} change={pts(c.bounce_pts)} v={c.bounce_pts} down low={low}/>
                      <Cell now={pct(n.added_to_cart_rate)} was={pct(b.added_to_cart_rate)} change={pts(c.added_to_cart_pts)} v={c.added_to_cart_pts} low={low}/>
                      <Cell now={pct(n.conversion_rate)} was={pct(b.conversion_rate)} change={pts(c.conversion_pts)} v={c.conversion_pts} low={low}/>
                      <Cell now={fmtInt(n.orders)} was={fmtInt(b.orders)} change={signedInt(c.orders)} v={c.orders} low={low}/>
                      <Cell now={money(n.revenue, 'USD', 0)} was={money(b.revenue, 'USD', 0)} change={`${signedMoney(c.revenue)}${c.revenue_pct !== null ? ` (${signedPct(c.revenue_pct)})` : ''}`} v={c.revenue} low={low}/>
                      <Cell now={money(n.revenue_per_session)} was={money(b.revenue_per_session)} change={signedPct(c.revenue_per_session_pct)} v={c.revenue_per_session_pct} low={low}/>
                      <td className="r"><Button size="sm" variant="ghost" onClick={() => onOpen(p.path, p.page_type)}>Deep dive</Button></td>
                    </tr>);
                })}</tbody>
              </table></div>
              {rows.length > 30 ? <div className="pad-x" style={{ paddingBottom: 10 }}><button type="button" className="link-btn" onClick={() => setAll((x) => !x)}>{all ? 'Show the first 30' : `Show all ${fmtInt(rows.length)} pages`}</button></div> : null}
              {d.errors && Object.keys(d.errors).length ? <div className="pad-x muted xs" style={{ paddingBottom: 10 }}>Shopify did not answer: {Object.keys(d.errors).join(', ')}.</div> : null}
            </>);
        }}
      </CroGate>
    </Card>);
}

/* ------------------------------------------------------------------ one page's deep dive */
const METRIC_ROWS = [
    { key: 'sessions', label: 'Sessions', show: (v) => fmtInt(v), change: (c) => `${signedInt(c.sessions)} (${signedPct(c.sessions_pct)})`, v: (c) => c.sessions },
    { key: 'bounce_rate', label: 'Bounce rate', show: (v) => pct(v), change: (c) => pts(c.bounce_pts), v: (c) => c.bounce_pts, down: true },
    { key: 'added_to_cart_rate', label: 'Add-to-cart rate', show: (v) => pct(v), change: (c) => pts(c.added_to_cart_pts), v: (c) => c.added_to_cart_pts },
    { key: 'conversion_rate', label: 'Conversion rate', show: (v) => pct(v), change: (c) => pts(c.conversion_pts), v: (c) => c.conversion_pts },
    { key: 'orders', label: 'Orders', show: (v) => fmtInt(v), change: (c) => `${signedInt(c.orders)} (${signedPct(c.orders_pct)})`, v: (c) => c.orders },
    { key: 'revenue', label: 'Revenue', show: (v) => money(v, 'USD', 0), change: (c) => `${signedMoney(c.revenue)} (${signedPct(c.revenue_pct)})`, v: (c) => c.revenue },
    { key: 'revenue_per_session', label: 'Revenue / session', show: (v) => money(v), change: (c) => signedPct(c.revenue_per_session_pct), v: (c) => c.revenue_per_session_pct },
    { key: 'aov', label: 'Avg order value', show: (v) => money(v), change: (c) => signedPct(c.aov_pct), v: (c) => c.aov_pct },
];
const DAY_SPANS = [{ key: 7, label: '7d' }, { key: 14, label: '14d' }, { key: 30, label: '30d' }, { key: 60, label: '60d' }];

const PAGE_STEPS = { viewed_product: 'Viewed a product', added_to_cart: 'Added to cart', reached_checkout: 'Reached checkout', completed_checkout: 'Purchased' };

/**
 * This page's funnel: visits, viewed a product, added to cart, reached checkout, purchased. Blue bar: share of the
 * page's visits; thin grey bar: the same step in the other period (WoW or MoM). All devices or one device.
 */
function PageFunnel({ f, week, month }) {
    const [mode, setMode] = useState('week');
    const [device, setDevice] = useState('all');
    const pair = f?.[mode];
    if (!pair?.now) return (<Card title="Funnel for this page"><div className="muted small">Shopify did not answer the funnel for this page.</div></Card>);
    const pick = (src) => (!src ? null : device === 'all' ? src.all : src.devices.find((x) => x.label === device) ?? null);
    const cur = pick(pair.now) ?? pair.now.all;
    const old = pick(pair.before);
    const devices = pair.now.devices.filter((x) => x.sessions > 0);
    const w = mode === 'week' ? week : month;
    const rows = [{ key: 'sessions', label: 'Visits', count: cur.sessions, pct: cur.sessions ? 100 : null, step: null }, ...cur.steps.map((s) => ({ key: s.key, label: PAGE_STEPS[s.key], count: s.count, pct: s.pct_of_sessions, step: s.step_pct }))];
    const was = (key) => {
        if (!old) return null;
        if (key === 'sessions') return { count: old.sessions, pct: old.sessions ? 100 : null };
        const s = old.steps.find((x) => x.key === key);
        return s ? { count: s.count, pct: s.pct_of_sessions } : null;
    };
    return (<Card title="Funnel for this page" sub={`${span(w.current)} vs ${span(w.previous)} · blue: share of the page's visits · grey: ${mode === 'week' ? 'last week' : 'the 30 days before'}`}
      actions={<div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
        {devices.length > 1 ? <Seg label="Device" options={[{ key: 'all', label: 'All' }, ...devices.slice(0, 3).map((x) => ({ key: x.label, label: x.label }))]} value={device} onChange={setDevice}/> : null}
        <Seg label="Compare" options={[{ key: 'week', label: 'WoW' }, { key: 'month', label: 'MoM' }]} value={mode} onChange={setMode}/>
      </div>}>
      <div className="cro-funnel">
        {rows.map((r, i) => {
            const before = was(r.key);
            const change = i && before?.pct !== null && before?.pct !== undefined && r.pct !== null ? r.pct - before.pct : null;
            return (<div key={r.key} className="cro-fstep">
              <div className="lr"><span>{r.label}</span>
                <span className="num"><b>{fmtInt(r.count)}</b> <span className="muted">· {i ? `${pct(r.pct)} of visits · ${r.step === null || r.step === undefined ? '—' : `${r.step}%`} of the step before` : '100%'}</span>
                  {change !== null ? <> <Chg text={pts(change)} v={Math.abs(change) < 0.005 ? 0 : change}/></> : null}</span></div>
              <div className="bar"><span style={{ width: `${r.pct ?? 0}%` }}/></div>
              {before?.pct !== null && before?.pct !== undefined ? <div className="prev"><span style={{ width: `${before.pct}%` }}/><em className="num">{fmtInt(before.count)} · {pct(before.pct)}</em></div> : null}
            </div>);
        })}
      </div>
      {cur.checkout_abandonment !== null && cur.checkout_abandonment !== undefined ? <div className="muted xs mt-8">Checkout abandonment {pct(cur.checkout_abandonment, 1)} · purchase rate {pct(cur.purchase_rate)}{device !== 'all' ? ` · ${device}` : ''}.</div> : null}
    </Card>);
}

/** The page's figures this week against last week, and the last 30 days against the 30 before, side by side. */
function WowMom({ d }) {
    const w = d.week, m = d.month;
    return (<Card title="Week on week & month on month" sub={`This week ${span(w.current)} · last 30 days ${span(m.current)}`} flush>
      <div className="table-wrap"><table className="t compact lp-wm">
        <thead><tr><th>Metric</th><th className="r">This week</th><th className="r">Last week</th><th className="r">WoW</th>
          <th className="r lp-sep">Last 30 days</th><th className="r">Previous 30</th><th className="r">MoM</th></tr></thead>
        <tbody>{METRIC_ROWS.map((r) => (<tr key={r.key}>
          <td>{r.label}</td><td className="r"><b>{r.show(w.now[r.key])}</b></td><td className="r muted">{r.show(w.before[r.key])}</td>
          <td className="r"><Chg text={r.change(w.change)} v={r.v(w.change)} down={r.down}/></td>
          <td className="r lp-sep"><b>{r.show(m.now[r.key])}</b></td><td className="r muted">{r.show(m.before[r.key])}</td>
          <td className="r"><Chg text={r.change(m.change)} v={r.v(m.change)} down={r.down}/></td>
        </tr>))}</tbody>
      </table></div>
    </Card>);
}

/** Day by day for the last 7, 14, 30 or 60 complete days, newest first, with a total row; downloads as CSV. */
function DateWise({ d }) {
    const [n, setN] = useState(30);
    const rows = d.daily.slice(-n);
    const sum = (k) => rows.reduce((a, r) => a + (r[k] || 0), 0);
    const visits = sum('sessions');
    const avg = (k) => (visits ? rows.reduce((a, r) => a + (r[k] || 0) * r.sessions, 0) / visits : null);
    const revenue = sum('revenue');
    const download = () => {
        const csv = toCsv([['Date', 'Sessions', 'Bounce %', 'Add to cart %', 'Conversion %', 'Orders', 'Revenue', 'Revenue per session'],
            ...[...rows].reverse().map((r) => [r.date, r.sessions, r.bounce_rate, r.added_to_cart_rate, r.conversion_rate, r.orders, r.revenue, r.revenue_per_session])]);
        const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
        const a = document.createElement('a');
        a.href = url;
        a.download = `landing${d.path.replace(/[^a-z0-9]+/gi, '-')}-${rows[0]?.date ?? ''}-to-${rows[rows.length - 1]?.date ?? ''}.csv`;
        a.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
    };
    return (<Card title="Date-wise (day by day)" flush
      actions={<div className="row" style={{ gap: 8 }}><Seg label="Days" options={DAY_SPANS} value={n} onChange={setN}/>
        <Button size="sm" icon="download" onClick={download}>CSV</Button></div>}>
      <div className="table-wrap lp-days"><table className="t compact">
        <thead><tr><th>Date</th><th className="r">Sessions</th><th className="r">Bounce</th><th className="r">Add to cart</th><th className="r">Conversion</th>
          <th className="r">Orders</th><th className="r">Revenue</th><th className="r">Rev / session</th></tr></thead>
        <tbody>{[...rows].reverse().map((r) => (<tr key={r.date}>
          <td className="nowrap">{new Date(`${r.date}T12:00:00Z`).toLocaleDateString('en-GB', { weekday: 'short', timeZone: 'UTC' })} {fmtDay(r.date)}</td>
          <td className="r">{fmtInt(r.sessions)}</td><td className="r">{pct(r.bounce_rate)}</td><td className="r">{pct(r.added_to_cart_rate)}</td>
          <td className="r"><b>{pct(r.conversion_rate)}</b></td><td className="r">{fmtInt(r.orders)}</td><td className="r">{money(r.revenue, 'USD', 0)}</td>
          <td className="r">{money(r.revenue_per_session)}</td>
        </tr>))}</tbody>
        <tfoot><tr><th>Total / avg</th><th className="r">{fmtInt(visits)}</th><th className="r">{pct(avg('bounce_rate'))}</th><th className="r">{pct(avg('added_to_cart_rate'))}</th>
          <th className="r">{pct(avg('conversion_rate'))}</th><th className="r">{fmtInt(sum('orders'))}</th><th className="r">{money(revenue, 'USD', 0)}</th>
          <th className="r">{visits ? money(revenue / visits) : '—'}</th></tr></tfoot>
      </table></div>
    </Card>);
}

/** The page's traffic sources or devices this period against the one before (WoW or MoM switch). */
function SegmentCard({ d, kind, title }) {
    const [mode, setMode] = useState('week');
    const rows = d[`${kind}_${mode}`] ?? [];
    const w = d[mode];
    return (<Card title={title} sub={`${span(w.current)} vs ${span(w.previous)}`} flush
      actions={<Seg label="Compare" options={[{ key: 'week', label: 'WoW' }, { key: 'month', label: 'MoM' }]} value={mode} onChange={setMode}/>}>
      <SegTable rows={rows}/>
    </Card>);
}

function SegTable({ rows }) {
    if (!rows.length) return <div className="pad-x muted small" style={{ paddingBottom: 12 }}>No visits in these days.</div>;
    return (<div className="table-wrap"><table className="t compact">
      <thead><tr><th>Segment</th><th className="r">Sessions</th><th className="r">Share</th><th className="r">Bounce</th><th className="r">Add to cart</th><th className="r">Conversion</th></tr></thead>
      <tbody>{rows.map((r) => (<tr key={r.label}>
        <td><b>{readable(r.label)}</b></td>
        <td className="r lp-cell"><b className="num">{fmtInt(r.sessions)}</b><Chg text={`${signedInt(r.sessions_change)}${r.sessions_change_pct !== null ? ` (${signedPct(r.sessions_change_pct)})` : ''}`} v={r.sessions_change}/></td>
        <td className="r">{pct(r.share, 1)}</td>
        <td className="r lp-cell"><b className="num">{pct(r.bounce_rate)}</b><Chg text={pts(r.bounce_change_pts)} v={r.bounce_change_pts} down low={r.low_data}/></td>
        <td className="r lp-cell"><b className="num">{pct(r.added_to_cart_rate)}</b><Chg text={pts(r.added_to_cart_change_pts)} v={r.added_to_cart_change_pts} low={r.low_data}/></td>
        <td className="r lp-cell"><b className="num">{pct(r.conversion_rate)}</b><Chg text={pts(r.conversion_change_pts)} v={r.conversion_change_pts} low={r.low_data}/></td>
      </tr>))}</tbody>
    </table></div>);
}

/**
 * One landing page's deep dive over the whole window (owner 2026-11-24): what changed, its funnel, week on week and
 * month on month, day by day (with CSV), the 60-day trend, traffic sources and devices (WoW / MoM). Escape or the cross
 * closes it.
 */
export function PageDive({ brand, path, type, onClose }) {
    const q = useApi(`/cro/landing-page${qs({ brand, path })}`);
    return (<Drawer title={<span className="lp-head"><span className="muted xs">Landing page deep dive</span><span className="lp-title" title={path}>{path === '/' ? '/ (homepage)' : path}</span></span>} onClose={onClose}>
      <div className="lp-dive col">
        {q.error ? <ExplainedError error={q.error} onRetry={q.reload}/> : !q.data ? <LoadingBlock rows={8}/> : (() => {
            const d = q.data;
            return (<>
              <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
                {type ? <span className="lane-chip plain">{type}</span> : null}
                <span className="muted small">This week {span(d.week.current)} · last 30 days {span(d.month.current)} · today left out</span>
              </div>
              <Card title={<span className="row" style={{ gap: 8 }}><Icon name="info"/>What changed</span>}>
                {d.what_changed.length ? (<ul className="lp-changes">{d.what_changed.map((c, i) => <li key={i} className={`t-${c.tone}`}>{c.text}</li>)}</ul>)
                    : <div className="muted small">Nothing moved much: the week and month look like the ones before.</div>}
              </Card>
              <PageFunnel f={d.funnel} week={d.week} month={d.month}/>
              <WowMom d={d}/>
              <DateWise d={d}/>
              <Card title={`Daily trend (last ${d.days} days)`} sub="Sessions, and conversion rate below">
                <LineChart ariaLabel="Sessions by day" height={150} yFormat={fmtInt} area series={[seriesOf(d.daily, 'sessions', 'sessions', 'Sessions', 'var(--info)')]}/>
                <LineChart ariaLabel="Conversion rate by day" height={150} yFormat={(v) => pct(v, 1)} series={[seriesOf(d.daily, 'conversion_rate', 'cvr', 'Conversion rate', 'var(--ok)')]}/>
              </Card>
              <SegmentCard d={d} kind="sources" title="Traffic sources for this page"/>
              <SegmentCard d={d} kind="devices" title="Devices for this page"/>
              {d.errors && Object.keys(d.errors).length ? <div className="muted xs">Shopify did not answer: {Object.keys(d.errors).join(', ')}.</div> : null}
              <div className="muted xs">Figures are for visits that started on exactly {path}; bots left out. Revenue = total sales of orders whose visit started here.</div>
            </>);
        })()}
      </div>
    </Drawer>);
}

/* ------------------------------------------------------------------ funnel by page */
const FUNNEL_COLS = [
    { key: 'viewed_product', label: 'Viewed a product' }, { key: 'added_to_cart', label: 'Added to cart' },
    { key: 'reached_checkout', label: 'Reached checkout' }, { key: 'completed_checkout', label: 'Purchased' },
];
const stepOf = (f, key) => f.steps.find((s) => s.key === key) ?? {};
const FUNNEL_SORTS = [
    { key: 'sessions', label: 'Sessions', by: (p) => p.now.sessions },
    { key: 'best', label: 'Best purchase rate', by: (p) => (p.low_data ? -Infinity : p.now.purchase_rate ?? -Infinity) },
    { key: 'purchase_drop', label: 'Biggest purchase-rate drop', by: (p) => (p.low_data || p.step_change_pts.completed_checkout === null ? -Infinity : -p.step_change_pts.completed_checkout) },
    { key: 'cart_drop', label: 'Biggest add-to-cart drop', by: (p) => (p.low_data || p.step_change_pts.added_to_cart === null ? -Infinity : -p.step_change_pts.added_to_cart) },
    { key: 'abandon', label: 'Most checkout abandonment', by: (p) => (p.low_data || !stepOf(p.now, 'reached_checkout').count ? -Infinity : p.now.checkout_abandonment ?? -Infinity) },
];

/**
 * Every landing page's funnel: sessions, viewed a product, added to cart, reached checkout and purchased. Each step shows
 * its share of sessions with the change against the other period, and its count with the share of the step before.
 */
export function FunnelByPage({ brand, onOpen }) {
    const [mode, setMode] = useState('week');
    const [sort, setSort] = useState('sessions');
    const [all, setAll] = useState(false);
    const q = useApi(`/cro/landing-funnel${qs({ brand, mode })}`);
    return (<Card title="Funnel by landing page" flush
      sub={q.data ? `${span(q.data.current)} vs ${span(q.data.previous)} · sessions → product view → cart → checkout → purchase · complete days` : 'Complete days'}
      actions={<Seg label="Compare" options={MODES} value={mode} onChange={(m) => { setMode(m); setAll(false); }}/>}>
      <CroGate query={q} rows={6}>
        {(d) => {
            const by = FUNNEL_SORTS.find((s) => s.key === sort) ?? FUNNEL_SORTS[0];
            const rows = [...d.pages].sort((a, b) => by.by(b) - by.by(a));
            const shown = all ? rows : rows.slice(0, 30);
            return (<>
              <div className="row pad-x lp-tools">
                <select className="input sm" value={sort} onChange={(e) => setSort(e.target.value)} aria-label="Sort by">{FUNNEL_SORTS.map((s) => <option key={s.key} value={s.key}>Sort: {s.label}</option>)}</select>
                <span className="muted xs">Big figure: share of sessions · small: count and share of the step before. Pages under {fmtInt(d.min_sessions)} visits in either period are &ldquo;low data&rdquo;.</span>
              </div>
              <div className="table-wrap"><table className="t compact lp-table">
                <thead><tr><th>Page</th><th className="r">Sessions</th>{FUNNEL_COLS.map((c) => <th key={c.key} className="r">{c.label}</th>)}<th/></tr></thead>
                <tbody>{shown.map((p) => (<tr key={p.path}>
                  <td style={{ maxWidth: 260 }}><button type="button" className="link-btn lp-path" title={p.path} onClick={() => onOpen(p.path, p.page_type)}>{p.path === '/' ? '/ (homepage)' : p.path}</button>
                    <span className="lane-chip plain">{p.page_type}</span></td>
                  <td className="r lp-cell"><b className="num">{fmtInt(p.now.sessions)}</b>
                    <Chg text={`${signedInt(p.sessions_change)}${p.sessions_change_pct !== null ? ` (${signedPct(p.sessions_change_pct)})` : ''}`} v={p.sessions_change}/></td>
                  {FUNNEL_COLS.map((c) => {
                      const s = stepOf(p.now, c.key);
                      return (<td key={c.key} className="r lp-cell"><b className="num">{pct(s.pct_of_sessions)}</b>
                        <Chg text={pts(p.step_change_pts[c.key])} v={p.step_change_pts[c.key]} low={p.low_data}/>
                        <span className="muted xs">{fmtInt(s.count)} · step {s.step_pct === null || s.step_pct === undefined ? '—' : `${s.step_pct}%`}</span></td>);
                  })}
                  <td className="r"><Button size="sm" variant="ghost" onClick={() => onOpen(p.path, p.page_type)}>Deep dive</Button></td>
                </tr>))}</tbody>
              </table></div>
              {rows.length > 30 ? <div className="pad-x" style={{ paddingBottom: 10 }}><button type="button" className="link-btn" onClick={() => setAll((x) => !x)}>{all ? 'Show the first 30' : `Show all ${fmtInt(rows.length)} pages`}</button></div> : null}
            </>);
        }}
      </CroGate>
    </Card>);
}

/* ------------------------------------------------------------------ pages day by day */
const DAILY_METRICS = [
    { key: 'sessions', label: 'Sessions', show: (v) => fmtInt(v), kind: 'sum' },
    { key: 'conversion_rate', label: 'Conversion rate', show: (v) => pct(v), kind: 'rate' },
    { key: 'bounce_rate', label: 'Bounce rate', show: (v) => pct(v), kind: 'rate' },
    { key: 'added_to_cart_rate', label: 'Add-to-cart rate', show: (v) => pct(v), kind: 'rate' },
    { key: 'orders', label: 'Orders', show: (v) => fmtInt(v), kind: 'sum' },
    { key: 'revenue', label: 'Revenue', show: (v) => money(v, 'USD', 0), kind: 'sum' },
    { key: 'revenue_per_session', label: 'Revenue / session', show: (v) => money(v), kind: 'rps' },
];

/** One page's figure over the days shown: a sum, a visit-weighted rate, or revenue per visit. */
function columnTotal(rows, m) {
    const visits = rows.reduce((a, r) => a + (r.sessions || 0), 0);
    if (m.kind === 'sum') return rows.reduce((a, r) => a + (r[m.key] || 0), 0);
    if (m.kind === 'rps') return visits ? rows.reduce((a, r) => a + (r.revenue || 0), 0) / visits : null;
    return visits ? rows.reduce((a, r) => a + (r[m.key] || 0) * (r.sessions || 0), 0) / visits : null;
}

/**
 * Landing pages side by side, day by day: dates down, pages across, one metric at a time, for the last 7, 14, 30 or 60
 * complete days. The busiest 8 pages of the last 30 days to start with; remove a page with its ×, add one from the
 * search box (up to 12). Downloads as CSV.
 */
export function PagesDaily({ brand, onOpen }) {
    const [paths, setPaths] = useState(null);   // null = the busiest 8
    const [metric, setMetric] = useState('sessions');
    const [n, setN] = useState(30);
    const [find, setFind] = useState('');
    const q = useApi(`/cro/landing-daily${qs({ brand, paths: paths ? paths.join(',') : '' })}`);
    const m = DAILY_METRICS.find((x) => x.key === metric) ?? DAILY_METRICS[0];
    const current = q.data?.pages.map((p) => p.path) ?? [];
    const remove = (path) => setPaths(current.filter((x) => x !== path));
    const add = (path) => {
        if (path && !current.includes(path) && current.length < 12) setPaths([...current, path]);
        setFind('');
    };
    return (<Card title="Date-wise comparison" flush
      sub={q.data ? `${fmtDay(q.data.pages[0]?.rows.slice(-n)[0]?.date ?? q.data.from)} – ${fmtDay(q.data.to)} · dates down, landing pages across` : 'Dates down, landing pages across'}
      actions={<div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
        <select className="input sm" value={metric} onChange={(e) => setMetric(e.target.value)} aria-label="Metric">{DAILY_METRICS.map((x) => <option key={x.key} value={x.key}>{x.label}</option>)}</select>
        <Seg label="Days" options={DAY_SPANS} value={n} onChange={setN}/>
        <Button size="sm" icon="download" disabled={!q.data} onClick={() => downloadDaily(q.data, m, n)}>CSV</Button>
      </div>}>
      <CroGate query={q} rows={8}>
        {(d) => {
            const cols = d.pages.map((p) => ({ ...p, rows: p.rows.slice(-n) }));
            const days = cols[0]?.rows.map((r) => r.date) ?? [];
            const left = d.choices.filter((c) => !current.includes(c.path));
            const s = find.trim().toLowerCase();
            const hits = s ? left.filter((c) => c.path.includes(s)).slice(0, 8) : [];
            return (<>
              <div className="pad-x lp-chips">
                {cols.map((p) => (<span key={p.path} className="lp-chip" title={p.path}>
                  <button type="button" className="link-btn" onClick={() => onOpen(p.path, p.page_type)}>{p.path === '/' ? '/ (homepage)' : p.path}</button>
                  {cols.length > 1 ? <button type="button" className="lp-x" aria-label={`Remove ${p.path}`} onClick={() => remove(p.path)}>×</button> : null}
                </span>))}
                {cols.length < 12 ? (<span className="lp-find">
                  <Icon name="search" size="sm"/>
                  <input className="input sm" placeholder="Search & add a landing page…" value={find} onChange={(e) => setFind(e.target.value)} aria-label="Search and add a landing page"
                    onKeyDown={(e) => { if (e.key === 'Enter' && hits[0]) add(hits[0].path); }}/>
                  {hits.length ? <span className="lp-hits">{hits.map((c) => <button type="button" key={c.path} onClick={() => add(c.path)}>{c.path} <span className="muted xs">{fmtInt(c.sessions)} visits</span></button>)}</span> : null}
                </span>) : null}
              </div>
              <div className="table-wrap lp-days"><table className="t compact lp-grid">
                <thead><tr><th>Date</th>{cols.map((p) => <th key={p.path} className="r" title={p.path}><span className="lp-colname">{p.path === '/' ? '/ (homepage)' : p.path}</span><span className="muted xs">{p.page_type}</span></th>)}</tr></thead>
                <tbody>{[...days].reverse().map((day, i) => {
                    const at = days.length - 1 - i;
                    return (<tr key={day}><td className="nowrap">{new Date(`${day}T12:00:00Z`).toLocaleDateString('en-GB', { weekday: 'short', timeZone: 'UTC' })} {fmtDay(day)}</td>
                      {cols.map((p) => <td key={p.path} className="r num">{m.show(p.rows[at]?.[m.key] ?? null)}</td>)}</tr>);
                })}</tbody>
                <tfoot><tr><th>Total / avg</th>{cols.map((p) => <th key={p.path} className="r">{m.show(columnTotal(p.rows, m))}</th>)}</tr></tfoot>
              </table></div>
              {d.errors && Object.keys(d.errors).length ? <div className="pad-x muted xs" style={{ paddingBottom: 10 }}>Shopify did not answer: {Object.keys(d.errors).join(', ')}.</div> : null}
            </>);
        }}
      </CroGate>
    </Card>);
}

function downloadDaily(d, m, n) {
    const cols = d.pages.map((p) => ({ ...p, rows: p.rows.slice(-n) }));
    const days = cols[0]?.rows.map((r) => r.date) ?? [];
    const csv = toCsv([['Date', ...cols.map((p) => p.path)], ...[...days].reverse().map((day) => {
        const at = days.indexOf(day);
        return [day, ...cols.map((p) => p.rows[at]?.[m.key] ?? '')];
    })]);
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
    const a = document.createElement('a');
    a.href = url;
    a.download = `landing-pages-${m.key}-${days[0] ?? ''}-to-${days[days.length - 1] ?? ''}.csv`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
}
