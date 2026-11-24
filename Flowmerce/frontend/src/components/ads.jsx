'use client';
/* Building blocks for the Ads page (views/Ads.jsx): loading and explained errors, the date range, tiles, verdict and
 * status chips, the scaling gate, the coloured day strip, video drop-off bars, funnel bars and sortable table heads.
 * Only existing styles are used (app/globals.css); anything specific is a small inline style. */
import { useState } from 'react';
import { Icon } from './Icon';
import { ComparePicker, DateRangePicker } from './croDates';
import { CountUp } from './motion';
import { Button, ErrorState, LoadingBlock, Pill } from './ui';
import { AD_STATUS, GAP_VERDICTS, PLATFORM_LABEL, VERDICTS, explainAdsError, pct1, ratioTone, sortRows, usd, x2 } from '../lib/ads';
import { rangeDays, signedPct } from '../lib/cro';
import { fmtDate, fmtInt } from '../lib/format';

const TONE_COLOR = { ok: 'var(--ok)', warn: 'var(--warn)', crit: 'var(--crit)' };

/* ------------------------------------------------------------------ loading and errors */
/** An API error with a plain explanation where Ads has one (not connected yet, expired sign-in). */
export function AdsError({ error, onRetry }) {
    const ex = explainAdsError(error);
    if (!ex) return <ErrorState error={error} onRetry={onRetry}/>;
    return (<div className={`callout ${ex.tone}`} role="alert">
      <Icon name={ex.tone === 'info' ? 'info' : 'alert'}/>
      <div style={{ flex: 1 }}><b>{ex.title}.</b> {ex.text}</div>
      {onRetry && ex.tone !== 'info' ? <Button size="sm" icon="refresh" onClick={onRetry}>Retry</Button> : null}
    </div>);
}

/** Loading, explained errors, then `children(data)`. While another range loads, the last answer stays on, dimmed. */
export function AdsGate({ query, children, rows = 5 }) {
    const { data, error, reload, loading } = query;
    if (error) return <AdsError error={error} onRetry={reload}/>;
    if (!data) return <LoadingBlock rows={rows}/>;
    return (<div className={`col cro-page${loading ? ' cro-stale' : ''}`} style={{ gap: 16 }} aria-busy={loading || undefined}>{children(data)}</div>);
}

/* ------------------------------------------------------------------ date range */
/** The date picker and "Compare to" menu, the same as on the CRO page. `value` is { r, from, to, cmp, cfrom }; onChange
 * gets { r, from, to } from the date picker or { cmp, cfrom } from the comparison menu. `compare` false hides the
 * comparison (tabs that do not compare). */
export function AdsRangeBar({ value, onChange, today, compare = true }) {
    const n = rangeDays(value.from, value.to);
    return (<div className="col" style={{ gap: 6 }}>
      <div className="row-wrap">
        <DateRangePicker value={value} today={today} onChange={onChange}/>
        {compare ? <ComparePicker range={value} value={{ cmp: value.cmp, cfrom: value.cfrom }} today={today} onChange={onChange}/> : null}
      </div>
      <div className="muted small">
        {n === 1 ? fmtDate(value.from) : `${fmtDate(value.from)} – ${fmtDate(value.to)} · ${n} days`} · in the ad account&rsquo;s time
        {value.to >= today ? ' · today is still running' : ''}
      </div>
    </div>);
}

/* ------------------------------------------------------------------ tiles and chips */
/**
 * A figure with its change against the comparison. `good` says which way is good: 'up', 'down', or 'none' for a
 * figure that is neither (spend), which shows the change without a colour.
 */
export function AdsKpi({ label, block, format, good = 'up', foot, tone, title }) {
    const b = block || {};
    const missing = b.value === null || b.value === undefined;
    const change = b.change_pct;
    const cls = change === null || change === undefined || good === 'none' || Math.abs(change) < 0.05 ? 'flat' : (change > 0) === (good === 'up') ? 'up' : 'down';
    return (<div className="kpi" title={title}>
      <div className="kpi-label">{label}</div>
      <div className={`kpi-value ${missing ? 'na' : ''}`} style={tone && TONE_COLOR[tone] ? { color: TONE_COLOR[tone] } : undefined}>
        {missing ? '—' : <CountUp value={format(b.value)}/>}
      </div>
      <div className="kpi-foot">
        {change === null || change === undefined ? null
            : <><span className={`delta ${cls}`}>{signedPct(change)}</span> <span className="muted">was {format(b.baseline_value)}</span></>}
        {foot ? <div className="muted xs" style={{ flexBasis: '100%' }}>{foot}</div> : null}
      </div>
    </div>);
}

export function VerdictPill({ verdict, reason }) {
    const v = VERDICTS[verdict] ?? { label: verdict, tone: 'neutral' };
    return <Pill tone={v.tone} title={[v.help, reason].filter(Boolean).join(' ')}>{v.label}</Pill>;
}
export function GapPill({ verdict }) {
    const v = GAP_VERDICTS[verdict] ?? { label: verdict, tone: 'neutral' };
    return <Pill tone={v.tone}>{v.label}</Pill>;
}
export function AdStatus({ status }) {
    const s = AD_STATUS[status] ?? { label: status, tone: 'neutral' };
    return <Pill tone={s.tone} dot>{s.label}</Pill>;
}
export const PlatformTag = ({ platform }) => <span className={`lane-chip ${platform === 'meta' ? 'lane-research' : 'lane-event'}`}>{PLATFORM_LABEL[platform] ?? platform}</span>;
export const Tag = ({ children, title }) => <span className="lane-chip plain" title={title}>{children}</span>;

/** A ROAS or MER coloured against its target (no colour without one). */
export function Ratio({ value, target, strong }) {
    const tone = ratioTone(value, target);
    return <span className="num" style={{ color: TONE_COLOR[tone], fontWeight: strong || tone ? 650 : undefined }}>{x2(value)}</span>;
}

/** A small change figure for table cells: green when it moved the good way. */
export function Change({ value, good = 'up' }) {
    if (value === null || value === undefined) return <span className="faint">—</span>;
    const cls = Math.abs(value) < 0.05 || good === 'none' ? 'flat' : (value > 0) === (good === 'up') ? 'up' : 'down';
    return <span className={`delta ${cls}`}>{signedPct(value)}</span>;
}

/* ------------------------------------------------------------------ video drop-off and funnel */
const Bar = ({ value, max = 100, color = 'var(--accent)', title, height = 6 }) => (
    <span title={title} style={{ display: 'block', height, borderRadius: height / 2, background: 'var(--surface-3)', overflow: 'hidden' }}>
      <span style={{ display: 'block', height: '100%', width: `${Math.max(0, Math.min(100, (value ?? 0) / max * 100))}%`, background: color }}/>
    </span>);

/** Four small bars: hook rate, then how many viewers stay from 25% to 50%, 50% to 75% and 75% to 95% of the video. */
export function DropOff({ video }) {
    if (!video) return <span className="faint xs">image</span>;
    const steps = [['Hook', video.hook_rate, 60], ['25→50', video.to_50, 100], ['50→75', video.to_75, 100], ['75→95', video.to_95, 100]];
    const weakest = steps.slice(1).reduce((a, b) => ((b[1] ?? 101) < (a[1] ?? 101) ? b : a));
    return (<div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 34px)', gap: 4 }} aria-label="Video drop-off">
      {steps.map(([label, v, max], i) => (<div key={label} title={`${label}: ${pct1(v)}`}>
        <Bar value={v} max={max} color={i === 0 ? (v < 20 ? 'var(--crit)' : 'var(--ok)') : label === weakest[0] ? 'var(--warn)' : 'var(--accent)'}/>
        <div className="xs num muted" style={{ textAlign: 'center', marginTop: 2 }}>{v === null || v === undefined ? '—' : Math.round(v)}</div>
      </div>))}
    </div>);
}

/** Funnel steps as bars: each step's count, the share that came through from the step before, and the change. */
export function FunnelSteps({ steps }) {
    const top = steps[0]?.value || 1;
    return (<div className="col" style={{ gap: 10 }}>
      {steps.map((s, i) => {
          const dropped = s.rate !== null && s.previous_rate !== null && s.previous_rate !== undefined && s.rate < s.previous_rate * 0.9;
          return (<div key={s.key}>
            <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
              <b>{s.label}</b>
              <span className="num">{fmtInt(s.value)}</span>
              <Change value={s.change_pct}/>
              <span className="spacer"/>
              {i ? <span className="small num" style={{ color: dropped ? 'var(--crit)' : 'var(--muted)', fontWeight: dropped ? 650 : undefined }}
                title={s.previous_rate === null || s.previous_rate === undefined ? undefined : `Before: ${pct1(s.previous_rate)}`}>
                {pct1(s.rate)} of the step before{s.previous_rate === null || s.previous_rate === undefined ? '' : ` (was ${pct1(s.previous_rate)})`}</span> : null}
            </div>
            {/* Square-root scale: a plain scale would leave every step after the first too thin to see. */}
            <div className="mt-4"><Bar value={Math.sqrt(s.value / top) * 100} color={dropped ? 'var(--crit)' : 'var(--accent)'} height={10}/></div>
          </div>);
      })}
    </div>);
}

/* ------------------------------------------------------------------ tables */
/** Sorting state for a table: `rows` sorted, and `th(key, label, extra)` to draw a clickable head cell. */
export function useSort(rows, initialKey, initialDir = 'desc') {
    const [sort, setSort] = useState({ key: initialKey, dir: initialDir });
    const th = (key, label, { right = true, className = '', title } = {}) => {
        const on = sort.key === key;
        return (<th key={key} className={`sortable ${right ? 'r' : ''} ${className}`} title={title} aria-sort={on ? (sort.dir === 'asc' ? 'ascending' : 'descending') : undefined}
          onClick={() => setSort({ key, dir: on && sort.dir === 'desc' ? 'asc' : 'desc' })}>
          {label}{on ? <Icon name={sort.dir === 'asc' ? 'arrowUp' : 'arrowDown'} size="sm"/> : null}
        </th>);
    };
    return { rows: sortRows(rows, sort.key, sort.dir), th, sort };
}

/** A labelled dropdown filter. `options` are { key, label }; the empty choice shows `all`. */
export function Pick({ label, value, onChange, options, all = 'All' }) {
    return (<label className="row small" style={{ gap: 6 }}>
      <span className="muted nowrap">{label}</span>
      <select className="select sm" value={value ?? ''} onChange={(e) => onChange(e.target.value || null)}>
        <option value="">{all}</option>
        {options.map((o) => <option key={o.key} value={o.key}>{o.label}</option>)}
      </select>
    </label>);
}

export function SearchBox({ value, onChange, placeholder }) {
    return (<div className="input-icon" style={{ minWidth: 200, flex: '1 1 200px', maxWidth: 320 }}>
      <Icon name="search" size="sm"/>
      <input className="input sm" type="search" value={value} placeholder={placeholder} aria-label={placeholder} onChange={(e) => onChange(e.target.value)} style={{ width: '100%' }}/>
    </div>);
}
