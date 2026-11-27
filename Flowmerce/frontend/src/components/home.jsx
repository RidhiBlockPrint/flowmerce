'use client';
import Link from 'next/link';
import { Icon } from './Icon';
import { BrandTag, Empty } from './ui';
import { LineChart } from './charts';
import { CountUp } from './motion';
import { PLATFORM_LABEL, explainAdsError, ratioTone, usd, x2 } from '../lib/ads';
import { conversionBand, pct } from '../lib/cro';
import { fmtDay, fmtInt, timeAgo } from '../lib/format';

/** A titled list on Home with a real empty state and an optional link to the full page. */
export function ListCard({ title, sub, to, linkLabel, emptyTitle, emptyText, icon, children }) {
    const has = !!children && children.length > 0;
    return (<section className="card flush">
      <div className="card-head">
        <div style={{ minWidth: 0 }}>
          <h2 className="card-title">{title}</h2>
          {sub ? <div className="card-sub">{sub}</div> : null}
        </div>
        <div className="row" style={{ marginLeft: 'auto' }}></div>
      </div>
      <div className="card-body">
        {has ? <div className="alert-list">{children}</div> : <Empty icon={icon} title={emptyTitle}>{emptyText}</Empty>}
      </div>
      {to ? (<div className="card-foot">
        <Link href={to} className="strong">{linkLabel} <Icon name="arrowRight" size="sm"/></Link>
      </div>) : null}
    </section>);
}
/** A row inside a ListCard. With `to` the whole row is a link, so it stays keyboard reachable. */
export function ListRow({ icon, tone, title, meta, brand, brands, showBrand, trailing, to }) {
    const inner = (<>
      <span className={`list-icon ${tone ?? ''}`}><Icon name={icon}/></span>
      <span style={{ minWidth: 0, flex: 1 }}>
        <span className="strong small" style={{ display: 'block' }}>{title}</span>
        <span className="muted xs" style={{ display: 'block', overflowWrap: 'anywhere' }}>{meta}</span>
      </span>
      {trailing}
      {showBrand && brand ? <BrandTag id={brand} brands={brands}/> : null}
    </>);
    return to ? <Link href={to} className="alert-item list-row">{inner}</Link> : <div className="alert-item list-row">{inner}</div>;
}
export function brandLabel(filter, brands) {
    if (filter === 'all')
        return brands.map((b) => b.name).join(' and ');
    return brands.find((b) => b.id === filter)?.name ?? filter;
}

/* ------------------------------------------------------------------ the CEO view, layout "A · Bento" (owner, 2026-11-27)
 * Chosen from design-mockups/home-ceo/a-bento.html. One dashboard for All, Ridhi and CPC, for a period against the one
 * before: a large Sales tile (the days drawn against the days before), four smaller tiles (orders, average order,
 * conversion, visits), a wide Ads tile, the brands' (or channels') shares, the month's goal, and a small row of
 * operations figures. Figures only: no headline sentence and no advice; definitions in tooltips. Size shows importance.
 * Colours are the dashboard theme (--theme-* in globals.css). On All both brands are added on the server. */

const has = (v) => v !== null && v !== undefined;
const WEEKDAY = ['S', 'M', 'T', 'W', 'T', 'F', 'S'];
const weekday = (iso) => WEEKDAY[new Date(`${iso}T12:00:00Z`).getUTCDay()];
const BAND_COLOR = { high: 'var(--theme-good)', mid: 'var(--theme-usual)', low: 'var(--theme-low)' };

/** A change as a chip: green when it moved the good way, red when not, plain for a figure that is neither (spend).
 *  `good`: 'up', 'down' or 'none'. Nothing while it is too early to compare. */
export function Chip({ v, good = 'up' }) {
    if (!has(v)) return null;
    const flat = Math.abs(v) < 0.05;
    const tone = flat || good === 'none' ? 'flat' : (v > 0) === (good === 'up') ? 'good' : 'bad';
    return <span className={`hb-chip ${tone}`}>{flat ? '' : v > 0 ? '▲ ' : '▼ '}{Math.abs(v).toFixed(1)}%</span>;
}
const change = (b) => (b && !b.too_early ? b.change_pct : null);

/** What a figure was in the period before. */
function Was({ block, format }) {
    if (!has(block?.baseline_value)) return null;
    return <div className="hb-was">was <b>{format(block.baseline_value)}</b></div>;
}

/** A line that stretches to its tile's width (the newest point is always at the right edge). */
function Spark({ values, color = 'var(--theme-primary)', height = 34 }) {
    const vals = values.map((v) => (has(v) ? Number(v) : null));
    const known = vals.filter(has);
    if (known.length < 2) return null;
    const W = 100, H = 30;
    const max = Math.max(...known), min = Math.min(...known);
    const x = (i) => (i / (vals.length - 1)) * W;
    const y = (v) => H - 3 - ((v - min) / (max - min || 1)) * (H - 6);
    const d = vals.map((v, i) => (has(v) ? `${i && has(vals[i - 1]) ? 'L' : 'M'}${x(i).toFixed(2)},${y(v).toFixed(2)}` : '')).join('');
    const last = vals.length - 1;
    return (<svg className="hb-spark" style={{ height }} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-hidden="true">
      <path className="line-draw" d={d} fill="none" stroke={color} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" vectorEffect="non-scaling-stroke"/>
      {has(vals[last]) ? <circle cx={x(last)} cy={y(vals[last])} r="1.6" fill={color} vectorEffect="non-scaling-stroke"/> : null}
    </svg>);
}

/** Columns for the last days, the last one in navy; `colors` overrides a column's colour. */
function Columns({ days, value, colors, height = 56, letters = true }) {
    const max = Math.max(1, ...days.map((d) => value(d) || 0));
    return (<div>
      <div className="hb-cols" style={{ height }}>
        {days.map((d, i) => (<span key={d.date} title={`${fmtDay(d.date)}: ${fmtInt(value(d))}`}
          style={{ height: `${Math.max(3, ((value(d) || 0) / max) * 100)}%`, background: i === days.length - 1 ? 'var(--theme-primary)' : colors?.[i] ?? 'var(--theme-primary-soft)' }}/>))}
      </div>
      {letters ? <div className="hb-cols-l">{days.map((d) => <span key={d.date}>{weekday(d.date)}</span>)}</div> : null}
    </div>);
}

/** A track with the theme's three zones (below usual, usual, good), a navy bar to the value and a tick at the mark. */
function Bullet({ value, lo, hi, low, high, mark, format, markLabel }) {
    const at = (v) => `${Math.max(0, Math.min(100, ((v - lo) / (hi - lo || 1)) * 100))}%`;
    return (<div className="hb-bullet-wrap">
      <div className="hb-bullet" role="img" aria-label={`${format(value)}; ${markLabel} ${format(mark)}`}>
        {has(low) ? <><span className="z" style={{ left: 0, width: at(low), background: 'var(--theme-low)' }}/>
          <span className="z" style={{ left: at(low), width: `calc(${at(high)} - ${at(low)})`, background: 'var(--theme-usual)' }}/>
          <span className="z" style={{ left: at(high), right: 0, background: 'var(--theme-good)' }}/></> : null}
        {has(value) ? <span className="v" style={{ width: at(value) }}/> : null}
        {has(mark) ? <span className="t" style={{ left: at(mark) }}/> : null}
      </div>
      <div className="hb-bullet-s"><span>{format(lo)}</span>{has(mark) ? <span>{markLabel} {format(mark)}</span> : <span/>}<span>{format(hi)}</span></div>
    </div>);
}

/** A ring of parts ([{ value, color }]) with a figure in its middle. */
function Ring({ parts, size = 104, stroke = 14, center, sub }) {
    const r = (size - stroke) / 2;
    const C = 2 * Math.PI * r;
    const total = parts.reduce((n, p) => n + Math.max(0, p.value || 0), 0) || 1;
    let at = 0;
    return (<svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="hb-ring" aria-hidden="true">
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--line-2)" strokeWidth={stroke}/>
      {parts.map((p, i) => {
          const len = (Math.max(0, p.value || 0) / total) * C;
          const el = <circle key={i} className="ring-arc" cx={size / 2} cy={size / 2} r={r} fill="none" stroke={p.color} strokeWidth={stroke}
            strokeDasharray={`${Math.max(len - 2, 0.5)} ${C}`} strokeDashoffset={-at} transform={`rotate(-90 ${size / 2} ${size / 2})`}/>;
          at += len;
          return el;
      })}
      <text x={size / 2} y={size / 2 + 2} textAnchor="middle" className="hb-ring-n">{center}</text>
      {sub ? <text x={size / 2} y={size / 2 + 17} textAnchor="middle" className="hb-ring-s">{sub}</text> : null}
    </svg>);
}

const HELP = {
    sales: 'Total sales: Shopify’s total sales for the period, in each store’s own time zone, against the period just before.',
    orders: 'Orders placed in the period (cancelled and test orders left out).',
    aov: 'Average order: total sales divided by orders.',
    conversion: 'Share of store visits that ended in an order (complete days only: Shopify reports visits a day late). Band: the last 28 days’ usual range.',
    visits: 'Store visits from every channel (complete days only). Columns: visits by day, coloured by how the day converted.',
    spend: 'What Meta and Google charged for the period, against the period before.',
    mer: 'Store sales (order totals, bulk orders left out) for every $1 of ad spend: MER. Zones: cut back, hold, grow, as on the Ads page.',
    cpo: 'Ad spend divided by every store order.',
};

/** The large Sales tile: total sales against the period before, the days drawn against the days before, and where the
 *  gross sales went. `h` is /cro/home-period's answer. */
export function SalesHero({ h, scope }) {
    const m = h.metrics;
    const cur = h.chart?.current ?? [];
    const prev = h.chart?.previous ?? [];
    const n = cur.length;
    const series = [
        { key: 'cur', label: 'Sales', color: 'var(--theme-primary)', points: cur.map((d) => ({ x: d.date, y: d.revenue })) },
        // The days before, drawn on the same dates so the two lines can be compared day by day.
        ...(prev.length === n && n ? [{ key: 'prev', label: 'Before', color: 'var(--faint)', dashed: true, points: cur.map((d, i) => ({ x: d.date, y: prev[i].revenue })) }] : []),
    ];
    const row = (k) => h.breakdown?.rows?.find((r) => r.key === k)?.value ?? null;
    const gross = row('gross');
    const share = (v) => (gross && has(v) ? `${((Math.max(0, v) / gross) * 100).toFixed(1)}%` : '—');
    return (<section className="card hb-tile hb-hero" title={HELP.sales}>
      <div className="hb-head"><h2 className="hb-title">Sales</h2><span className="hb-sub">total sales · {scope}{n ? ` · ${fmtDay(cur[0].date)} to ${fmtDay(cur[n - 1].date)} against the ${n} days before` : ''}</span></div>
      <div className="hb-fig"><span className="hb-huge num">{has(m.revenue?.value) ? <CountUp value={usd(m.revenue.value)}/> : '—'}</span><Chip v={change(m.revenue)}/></div>
      <Was block={m.revenue} format={(v) => usd(v)}/>
      <div className="hb-hero-chart">
        {n ? <LineChart ariaLabel="Total sales by day against the days before" height={190} yFormat={(v) => usd(v)} series={series} area/>
          : <Empty icon="analytics" title="No days yet">Daily sales appear once orders are read.</Empty>}
      </div>
      {gross ? (<div className="hb-legend">
        <span><i style={{ background: 'var(--theme-primary)' }}/>net {usd(row('net'))}</span>
        <span><i style={{ background: 'var(--theme-low)' }}/>returns {share(row('returns'))}</span>
        <span><i style={{ background: 'var(--theme-usual)' }}/>discounts {share(row('discounts'))}</span>
      </div>) : null}
    </section>);
}

/** A smaller tile: label, the figure, its change, what it was, and a small chart at the bottom. */
function Tile({ label, help, block, format, good = 'up', foot, children }) {
    return (<section className="card hb-tile" title={help}>
      <div className="hb-label">{label}</div>
      <div className="hb-fig"><span className="hb-num num">{has(block?.value) ? <CountUp value={format(block.value)}/> : '—'}</span><Chip v={change(block)} good={good}/></div>
      {foot ?? <Was block={block} format={format}/>}
      <div className="hb-tile-viz">{children}</div>
    </section>);
}

/** Orders, average order, conversion and visits, each with its small chart. `scale` is conversionScale() of the last 28
 *  days. */
export function StoreTiles({ h, scale }) {
    const m = h.metrics;
    const chart = h.chart?.current ?? [];
    const days = (h.days ?? []).filter((d) => d.date <= h.to);
    const reported = days.filter((d) => has(d.sessions));
    const lastVisits = reported.slice(-6);
    const cvr = m.conversion_rate;
    return (<>
      <Tile label="Orders" help={HELP.orders} block={m.orders} format={fmtInt}>
        <Columns days={chart.slice(-7)} value={(d) => d.orders}/>
      </Tile>
      <Tile label="Average order" help={HELP.aov} block={m.aov} format={(v) => usd(v, 2)}>
        <Spark values={days.slice(-Math.max(14, chart.length)).map((d) => d.aov)}/>
      </Tile>
      <Tile label="Conversion" help={HELP.conversion} block={cvr} format={(v) => pct(v)}
        foot={<div className="hb-was">{has(cvr?.sessions) ? `from ${fmtInt(cvr.sessions)} visits` : 'complete days only'}</div>}>
        {scale ? <Bullet value={cvr?.value} lo={scale.lo} hi={scale.hi} low={scale.low} high={scale.high} mark={scale.avg} markLabel="usual" format={(v) => pct(v)}/> : null}
      </Tile>
      <Tile label="Visits" help={HELP.visits} block={m.sessions} format={fmtInt}
        foot={has(m.sessions?.value) ? undefined : <div className="hb-was">complete days only</div>}>
        {lastVisits.length ? <Columns days={lastVisits} value={(d) => d.sessions} letters={false}
          colors={lastVisits.map((d) => BAND_COLOR[conversionBand(d.conversion_rate, scale)] ?? 'var(--line)')}/> : null}
      </Tile>
    </>);
}

/** The wide Ads tile: ad spend and its Meta / Google split, sales per $1 of ads on the cut back / hold / grow zones with
 *  the target, and ad cost per order. `ads` is useHomeAds' data. */
export function AdsTile({ ads, error, scope }) {
    const note = error ? explainAdsError(error) : null;
    const m = ads?.metrics;
    const ready = (ads?.brands ?? []).filter((b) => b.ready);
    const same = (f) => (ready.length && ready.every((b) => f(b) === f(ready[0])) ? f(ready[0]) : null);
    const target = same((b) => b.targets?.mer);
    const red = same((b) => b.gate_lines?.red);
    const green = same((b) => b.gate_lines?.green);
    const mer = m?.mer_ex_bulk?.value;
    const top = Math.max(3.5, (target ?? 0) + 0.5, (mer ?? 0) + 0.3);
    const split = (ads?.platforms ?? []).filter((p) => p.spend > 0);
    const colors = ['var(--theme-primary)', 'var(--theme-primary-soft)'];
    return (<section className="card hb-tile hb-ads">
      <div className="hb-head"><h2 className="hb-title">Ads</h2><span className="hb-sub">Meta and Google · {scope}</span></div>
      {note ? <div className={`callout ${note.tone}`}><Icon name="info"/><div><b>{note.title}.</b> {note.text}</div></div>
        : error ? <div className="muted small">Ad figures could not be read.</div>
        : !m ? <div className="muted small">Reading the ad accounts…</div> : (<div className="hb-ads-grid">
          <div title={HELP.spend}>
            <div className="hb-label">Ad spend</div>
            <div className="hb-fig"><span className="hb-num num">{has(m.spend?.value) ? <CountUp value={usd(m.spend.value)}/> : '—'}</span><Chip v={change(m.spend)} good="none"/></div>
            {split.length ? (<>
              <div className="hb-split">{split.map((p, i) => <span key={p.platform} style={{ width: `${p.share_of_spend ?? 0}%`, background: colors[i % 2] }}/>)}</div>
              <div className="hb-was">{split.map((p) => `${PLATFORM_LABEL[p.platform] ?? p.platform} ${Math.round(p.share_of_spend ?? 0)}%`).join(' · ')}</div>
            </>) : null}
          </div>
          <div className="hb-well" title={HELP.mer}>
            <div className="hb-label">Sales per $1 of ads</div>
            <div className="hb-fig"><span className={`hb-mid num t-${ratioTone(mer, target) || 'none'}`}>{x2(mer)}</span><Chip v={change(m.mer_ex_bulk)}/></div>
            {has(mer) ? <Bullet value={mer} lo={0} hi={top} low={red} high={green} mark={target} markLabel="target" format={(v) => x2(v)}/> : null}
          </div>
          <div className="hb-well" title={HELP.cpo}>
            <div className="hb-label">Ad cost per order</div>
            <div className="hb-fig"><span className="hb-mid num">{has(m.cost_per_order?.value) ? usd(m.cost_per_order.value, 2) : '—'}</span><Chip v={change(m.cost_per_order)} good="down"/></div>
            <Spark values={(ads.trend ?? []).map((d) => d.spend)} color="var(--theme-usual-strong)" height={28}/>
            <div className="hb-mini">ad spend by day</div>
          </div>
        </div>)}
    </section>);
}

/** On All: each brand's share of sales, with its sales per $1 of ads. On one brand: Meta's and Google's share of the ad
 *  spend, with each one's return. */
export function MixTile({ h, ads, brands, oneBrand }) {
    const name = (id) => brands.find((b) => b.id === id)?.short ?? id;
    const colors = ['var(--theme-primary)', 'var(--theme-primary-soft)'];
    if (!oneBrand) {
        const rows = h.by_brand ?? [];
        const merOf = (id) => ads?.brands?.find((b) => b.brand === id)?.metrics?.mer_ex_bulk?.value;
        const lead = rows[0];
        return (<section className="card hb-tile">
          <div className="hb-label">Brands · share of sales</div>
          <div className="hb-mix">
            <Ring parts={rows.map((r, i) => ({ value: r.revenue, color: colors[i % 2] }))} center={lead ? `${Math.round(lead.share ?? 0)}%` : '—'} sub={lead ? name(lead.brand) : ''}/>
            <div className="hb-mix-list">{rows.map((r, i) => (<div key={r.brand}>
              <div className="hb-kv"><span><i style={{ background: colors[i % 2] }}/>{name(r.brand)}</span><b>{usd(r.revenue)}</b></div>
              <div className="hb-mini">{has(merOf(r.brand)) ? `${x2(merOf(r.brand))} per $1 of ads` : `${fmtInt(r.orders)} orders`}</div>
            </div>))}</div>
          </div>
        </section>);
    }
    const rows = ads?.platforms ?? [];
    const lead = rows[0];
    return (<section className="card hb-tile">
      <div className="hb-label">Channels · share of ad spend</div>
      {rows.length ? (<div className="hb-mix">
        <Ring parts={rows.map((r, i) => ({ value: r.spend, color: colors[i % 2] }))} center={lead ? `${Math.round(lead.share_of_spend ?? 0)}%` : '—'} sub={lead ? PLATFORM_LABEL[lead.platform] : ''}/>
        <div className="hb-mix-list">{rows.map((r, i) => (<div key={r.platform}>
          <div className="hb-kv"><span><i style={{ background: colors[i % 2] }}/>{PLATFORM_LABEL[r.platform] ?? r.platform}</span><b>{usd(r.spend)}</b></div>
          <div className="hb-mini">ROAS {x2(r.roas)} (the platform's own count)</div>
        </div>))}</div>
      </div>) : <div className="hb-was">No ad spend in these days.</div>}
    </section>);
}

/** The month's sales goal: how much of it is reached, and the pace (sales so far against the goal's share for the days
 *  gone). The goal is set per store on the CRO page; on All both stores' goals are added. */
export function GoalTile({ goal }) {
    if (!goal) return (<section className="card hb-tile">
      <div className="hb-label">Monthly goal</div>
      <div className="hb-was" style={{ margin: '8px 0 10px' }}>No monthly sales goal yet{' '}for every store.</div>
      <Link className="btn sm" href="/cro">Set it on the CRO page</Link>
    </section>);
    const tone = goal.pace_pct >= 100 ? 'good' : goal.pace_pct >= 90 ? 'usual' : 'bad';
    const k = (v) => (v >= 10000 ? `$${(v / 1000).toFixed(1)}k` : usd(v));
    return (<section className="card hb-tile" title="Sales this month against the monthly goal set on the CRO page; pace: against the goal's share for the days gone">
      <div className="hb-label">{goal.month} goal</div>
      <div className="hb-mix">
        <Ring parts={[{ value: Math.min(goal.pct, 100), color: 'var(--theme-good-strong)' }, { value: Math.max(0, 100 - goal.pct), color: 'var(--line-2)' }]}
          center={`${Math.round(goal.pct)}%`} sub={`of ${k(goal.goal)}`}/>
        <div>
          <div className="hb-mid num">{k(goal.sales)}</div>
          <div className="hb-mini">so far, day {goal.day} of {goal.days}</div>
          <span className={`hb-chip ${tone === 'usual' ? 'flat' : tone}`} style={{ marginTop: 6 }}>pace {Math.round(goal.pace_pct)}%</span>
        </div>
      </div>
    </section>);
}

/** The small row of operations figures: delivery problems, on-time delivery, decisions waiting, data freshness. */
export function OpsRow({ shipProblems, shipSummary, waiting, ordersSyncedAt, adsBrands }) {
    const oldest = (vals) => vals.filter(Boolean).sort()[0] ?? null;
    const adsTo = oldest((adsBrands ?? []).map((b) => b.meta_saved_to));
    const onTime = shipSummary?.delivery30?.onTimePct;
    const op = (label, sub, value, tone, to) => (<Link href={to} className="card hb-op">
      <span><span className="hb-label">{label}</span><span className="hb-mini">{sub}</span></span>
      <span className={`hb-op-n num t-${tone || 'none'}`}>{value}</span>
    </Link>);
    return (<div className="hb-ops">
      {op('Delivery problems', `${fmtInt(shipSummary?.activeTotal)} parcels on the way`, fmtInt(shipProblems), shipProblems ? 'crit' : '', '/shipping')}
      {op('On time · 30 days', 'delivered parcels', has(onTime) ? `${onTime}%` : '—', has(onTime) ? (onTime >= 90 ? 'ok' : onTime >= 75 ? 'warn' : 'crit') : '', '/shipping')}
      {op('Waiting for you', 'SEO & Blog decisions', fmtInt(waiting), waiting ? 'warn' : '', '/publishing')}
      {op('Data as of', adsTo ? `orders · ads to ${fmtDay(adsTo)}` : 'store orders', ordersSyncedAt ? timeAgo(ordersSyncedAt).replace(' ago', '') : '—', '', '/settings/data')}
    </div>);
}
