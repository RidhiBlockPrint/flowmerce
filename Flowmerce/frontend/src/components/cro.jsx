'use client';
/* Building blocks for the CRO page (views/Cro.jsx). */
import { useState } from 'react';
import Link from 'next/link';
import { Icon } from './Icon';
import { Dialog } from './overlays';
import { LineChart } from './charts';
import { CountUp } from './motion';
import { BRAND_COLOR } from './metrics';
import { Button, Card, Empty, ErrorState, LoadingBlock } from './ui';
import { RANGE_COMPARES, RANGE_PRESETS, effectiveCompare, explainError, money, pct, rangeDays, signedPct } from '../lib/cro';
import { useApi, qs } from '../lib/api';
import { fmtDate, fmtInt, timeAgo } from '../lib/format';

/** Loading, explained errors, then `children(data)` with the order-data note on top when the copy is incomplete. */
export function CroGate({ query, children, rows = 5 }) {
    const { data, error, reload, loading } = query;
    if (error) return <ExplainedError error={error} onRetry={reload}/>;
    if (!data) return <LoadingBlock rows={rows}/>;
    // Still showing the previous answer while a new one loads (another range): dim it, after a short delay.
    return (<div className={`col cro-page${loading ? ' cro-stale' : ''}`} style={{ gap: 16 }} aria-busy={loading || undefined}>
      <OrderDataNote state={data.order_data} from={data.from}/>
      {children(data)}
    </div>);
}

/** An API error with a plain explanation for the codes CRO knows (missing Shopify analytics access, setup). */
export function ExplainedError({ error, onRetry }) {
    const ex = explainError(error);
    if (!ex) return <ErrorState error={error} onRetry={onRetry}/>;
    return (<div className={`callout ${ex.tone}`} role="alert">
      <Icon name="alert"/>
      <div style={{ flex: 1 }}><b>{ex.title}.</b> {ex.text}</div>
      {onRetry ? <Button size="sm" icon="refresh" onClick={onRetry}>Retry</Button> : null}
    </div>);
}

/** Says when CRO's copy of the store's orders is incomplete or behind, so partial figures are never read as real. */
export function OrderDataNote({ state, from }) {
    if (state?.available_from && from && from < state.available_from) {
        return (<div className="callout warn"><Icon name="alert"/>
          <div>CRO&rsquo;s copy of this store&rsquo;s orders starts on <b>{fmtDate(state.available_from)}</b>, so order figures before that day are
            missing (sessions and conversion come from Shopify and are complete). History builds up from now on.</div></div>);
    }
    if (!state || (state.first_load_complete && !state.note)) return null;
    const tone = state.first_load_complete ? 'warn' : 'info';
    return (<div className={`callout ${tone}`}>
      <Icon name={state.first_load_complete ? 'alert' : 'loader'} className={state.first_load_complete ? '' : 'spin'}/>
      <div>
        {state.note}
        {state.synced_up_to ? <span className="muted"> Orders read up to {timeAgo(state.synced_up_to)}.</span> : null}
      </div>
    </div>);
}

/** A KPI card for one metric block from the API: value, baseline and change, or "too early to compare". */
export function KpiTile({ label, block, format, foot }) {
    const b = block || {};
    const change = b.change_pct;
    const tone = change === null || change === undefined || b.too_early ? 'flat' : change > 0 ? 'up' : change < 0 ? 'down' : 'flat';
    return (<div className="kpi">
      <div className="kpi-label">{label}</div>
      <div className={`kpi-value ${b.value === null || b.value === undefined ? 'na' : ''}`}>
        {b.value === null || b.value === undefined ? 'Unavailable' : <CountUp value={format(b.value)}/>}
      </div>
      <div className="kpi-foot">
        {b.too_early
            ? <span className="muted" title="Below about 20 orders or 500 sessions a % change is mostly noise">Too early to compare</span>
            : <><span className={`delta ${tone}`}>{signedPct(change)}</span> <span className="muted">{b.baseline_label}{b.baseline_value !== null && b.baseline_value !== undefined ? ` (${format(b.baseline_value)})` : ''}</span></>}
        {foot ? <div className="muted xs">{foot}</div> : null}
      </div>
    </div>);
}

/** A small segmented control: `options` are { key, label }. */
export function Seg({ options, value, onChange, label, size = 'sm' }) {
    return (<div className={`seg ${size}`} role="group" aria-label={label} style={{ flexWrap: 'wrap', maxWidth: '100%' }}>
      {options.map((o) => (<button key={o.key} type="button" aria-pressed={o.key === value} onClick={() => onChange(o.key)}>{o.label}</button>))}
    </div>);
}

/** Empty state for lists, with the order-data note when the reason is an unfinished first load. */
export function CroEmpty({ title, children, icon = 'inbox' }) {
    return <Empty icon={icon} title={title}>{children}</Empty>;
}

/* ------------------------------------------------------------------ date range */
/** Quick picks, a calendar for any range, and the comparison. `value` is { r, from, to, cmp }. */
export function RangeBar({ value, onChange, today }) {
    const [custom, setCustom] = useState(false);
    const n = rangeDays(value.from, value.to);
    const cmp = effectiveCompare(value.cmp, value.from, value.to);
    return (<div className="col" style={{ gap: 8 }}>
      <div className="row" style={{ flexWrap: 'wrap', gap: 8 }}>
        <Seg label="Date range" options={RANGE_PRESETS} value={value.r} onChange={(r) => onChange({ r })}/>
        <Button size="sm" icon="calendar" variant={value.r === 'custom' ? 'primary' : 'secondary'} onClick={() => setCustom(true)}>
          {value.r === 'custom' ? `${fmtDate(value.from)} – ${fmtDate(value.to)}` : 'Pick dates…'}
        </Button>
        <label className="row small" style={{ gap: 6 }}>
          <span className="muted nowrap">Compare with</span>
          <select className="select sm" value={cmp} onChange={(e) => onChange({ cmp: e.target.value })}>
            {RANGE_COMPARES.filter((c) => !c.single || n === 1).map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
          </select>
        </label>
      </div>
      <div className="muted small">
        {n === 1 ? fmtDate(value.from) : `${fmtDate(value.from)} – ${fmtDate(value.to)} · ${n} days`}
        {value.to >= today ? ' · today is still running' : ''}
      </div>
      {custom ? <CustomRangeDialog value={value} today={today} onClose={() => setCustom(false)} onApply={(from, to) => { onChange({ r: 'custom', from, to }); setCustom(false); }}/> : null}
    </div>);
}

function CustomRangeDialog({ value, today, onClose, onApply }) {
    const [from, setFrom] = useState(value.from);
    const [to, setTo] = useState(value.to);
    const bad = !from || !to || from > to || from > today;
    const long = !bad && rangeDays(from, to) > 366;
    return (<Dialog title="Pick dates" sub="Store days. Pick the same day twice to see a single day." onClose={onClose}
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button variant="primary" disabled={bad || long} onClick={() => onApply(from, to)}>Apply</Button></>}>
      <div className="form-grid">
        <div className="field"><label htmlFor="cro-from">From</label><input id="cro-from" type="date" className="input" value={from} max={to || today} onChange={(e) => setFrom(e.target.value)}/></div>
        <div className="field"><label htmlFor="cro-to">To</label><input id="cro-to" type="date" className="input" value={to} min={from} max={today} onChange={(e) => setTo(e.target.value)}/></div>
      </div>
      {bad ? <p className="small" style={{ color: 'var(--crit)' }}>The start must be on or before the end, and not in the future.</p> : null}
      {long ? <p className="small" style={{ color: 'var(--crit)' }}>Pick at most 366 days.</p> : null}
    </Dialog>);
}

/* ------------------------------------------------------------------ Home */
/** Sales at the top of Home: yesterday and today so far per store (orders and net sales against their
 *  comparison), yesterday's conversion rate, and the last 14 days. Loads on its own, so a CRO problem never
 *  breaks Home. `brand` undefined = both stores, kept separate. */
export function SalesDashboard({ brand, brands }) {
    const q = useApi(`/cro/home${qs({ brand })}`);
    const name = (id) => brands?.find((b) => b.id === id)?.short ?? id;
    const color = (id) => BRAND_COLOR?.[id] ?? 'var(--accent)';
    let body;
    if (q.error) body = <ExplainedError error={q.error} onRetry={q.reload}/>;
    else if (!q.data) body = <LoadingBlock rows={4}/>;
    else {
        const ok = q.data.stores.filter((s) => s.state === 'ok');
        const several = q.data.stores.length > 1;
        body = (<div className="col" style={{ gap: 14 }}>
          {q.data.stores.map((s) => (s.state === 'ok' ? <StoreSales key={s.brand} s={s} label={several ? name(s.brand) : null}/>
              : <div key={s.brand} className="callout warn"><Icon name="alert"/><div><b>{name(s.brand)}: sales are unavailable.</b> {s.reason}</div></div>))}
          {ok.length ? (<div className="grid cols-2">
            <div><div className="muted xs">Net sales, last 14 days</div>
              <LineChart ariaLabel="Net sales by day" height={150} yFormat={(v) => money(v, 'USD', 0)}
                series={ok.map((s) => ({ key: s.brand, label: name(s.brand), color: color(s.brand), points: s.trend.map((d) => ({ x: d.date, y: d.net })) }))}/></div>
            <div><div className="muted xs">Orders, last 14 days</div>
              <LineChart ariaLabel="Orders by day" height={150} yFormat={fmtInt}
                series={ok.map((s) => ({ key: s.brand, label: name(s.brand), color: color(s.brand), points: s.trend.map((d) => ({ x: d.date, y: d.orders })) }))}/></div>
          </div>) : null}
        </div>);
    }
    return (<Card title="Sales" sub="Daily orders and net sales (after discounts and refunds), in store time."
      actions={<Link className="btn ghost sm" href="/cro">Open Conversion (CRO)</Link>}>{body}</Card>);
}

function Change({ b }) {
    if (b.too_early) return <span className="muted">too early to compare</span>;
    const tone = b.change_pct > 0 ? 'up' : b.change_pct < 0 ? 'down' : 'flat';
    return <><span className={`delta ${tone}`}>{signedPct(b.change_pct)}</span> <span className="muted">{b.baseline_label}</span></>;
}

function StoreSales({ s, label }) {
    const y = s.yesterday;
    const t = s.today;
    return (<div>
      {label ? (<div className="row" style={{ marginBottom: 6 }}><span className={`brand-dot ${s.brand}`}/><b>{label}</b>
        {s.order_data && !s.order_data.first_load_complete ? <span className="muted xs">· first order load still running</span> : null}</div>) : null}
      <div className="kpis" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(135px, 1fr))' }}>
        <div className="kpi"><div className="kpi-label">Orders yesterday</div><div className="kpi-value">{fmtInt(y.orders.value)}</div><div className="kpi-foot"><Change b={y.orders}/></div></div>
        <div className="kpi"><div className="kpi-label">Net sales yesterday</div><div className="kpi-value">{money(y.net_sales.value, 'USD', 0)}</div><div className="kpi-foot"><Change b={y.net_sales}/></div></div>
        <div className="kpi"><div className="kpi-label">Today so far</div>
          <div className="kpi-value">{fmtInt(t.orders.value)} <span className="muted small">orders · {money(t.net_sales.value, 'USD', 0)}</span></div>
          <div className="kpi-foot"><Change b={t.net_sales}/></div></div>
        <div className="kpi"><div className="kpi-label">Conversion yesterday</div><div className="kpi-value">{s.conversion ? pct(s.conversion.value) : '—'}</div>
          <div className="kpi-foot muted">{s.conversion ? `Day before: ${pct(s.conversion.previous)}` : s.conversion_state === 'reports_access_missing' ? 'Shopify analytics access missing' : 'Not available'}</div></div>
      </div>
    </div>);
}
