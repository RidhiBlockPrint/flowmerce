'use client';
/* CRO (Conversion Rate Optimization): how each store turns visitors into orders, and what to look at next.
 * Every figure comes from /api/cro/...; this page only lays it out. One store at a time: when the top bar says "All",
 * the page shows its own Ridhi / CPC switch. The date range (quick picks or any calendar range) and its comparison
 * are kept in the address and apply to every tab that shows figures for a period. */
import { useEffect, useRef, useState } from 'react';
import { api, qs, useApi } from '../lib/api';
import { useBrandParam } from '../lib/app';
import { useSearchParams } from '../lib/nav';
import { fmtDate, fmtDateTime, fmtDay, fmtInt, isoDay, timeAgo } from '../lib/format';
import {
    ADVICE_AREA, AREAS, EFFORT_TONE, IMPACT_TONE, PRIORITY_TONE, RULE_KIND, STORES, TABS, storeTimezone,
    RATING, VITALS, areaLabel, conversionScale, effectiveCompare, fmtVital, heatLevel, isRangeKey, money, pct, presetRange, rangeDays, readable, seriesOf, shiftDay, signedPct,
    signedPts, todayIn,
} from '../lib/cro';
import { LineChart } from '../components/charts';
import { CroEmpty, CroGate, ExplainedError, KpiTile, RangeBar, Seg } from '../components/cro';
import { RingBody } from '../components/dash';
import { Gauge } from '../components/motion';
import { DayStrip, GaugeCard, HealthTile, HeatmapCard, JourneyCard, MoversCard, OrdersCard, SalesChart, SalesTile, TrendsRow, VisitsCard } from '../components/croOverview';
import { FunnelByPage, LandingCompare, PageDive, PagesDaily } from '../components/croLanding';
import { Icon } from '../components/Icon';
import { useToast } from '../components/overlays';
import { Button, Card, Field, LoadingBlock, PageHead, Paged, Pill, Skeleton } from '../components/ui';

const RANGE_TABS = ['overview', 'conversion', 'landing', 'checkout', 'products', 'sales', 'site'];

export default function Cro() {
    const [sp, setSp] = useSearchParams();
    const globalBrand = useBrandParam();
    const brand = globalBrand ?? (STORES.some((s) => s.key === sp.get('store')) ? sp.get('store') : 'ridhi');
    const tab = TABS.some((t) => t.key === sp.get('tab')) ? sp.get('tab') : 'overview';
    const [rev, setRev] = useState(0);
    const [syncing, setSyncing] = useState(false);
    const [draft, setDraft] = useState(null);   // an experiment started from a recommendation
    const toast = useToast();
    // The store's own "today" (Shopify's timezone for the store) decides what "Yesterday" or "This month" means. The
    // store's known zone is used until settings answers, so the page's requests start straight away.
    const settings = useApi(`/cro/settings${qs({ brand })}`);
    const today = todayIn(storeTimezone(brand, settings.data?.timezone));
    const update = (patch) => {
        const next = new URLSearchParams(sp);
        for (const [k, v] of Object.entries(patch)) {
            if (v === null || v === '' || v === undefined) next.delete(k);
            else next.set(k, v);
        }
        setSp(next, { replace: true });
    };
    const isDay = (v) => /^\d{4}-\d{2}-\d{2}$/.test(v ?? '');
    const r = isRangeKey(sp.get('r')) ? sp.get('r') : 'yesterday';
    let range = null;
    if (today) {
        const fixed = r === 'custom' && isDay(sp.get('from')) && isDay(sp.get('to')) ? { from: sp.get('from'), to: sp.get('to') } : presetRange(r, today);
        const cmp = sp.get('cmp') || 'previous';   // Shopify's default: the previous period
        const cfrom = isDay(sp.get('cfrom')) ? sp.get('cfrom') : null;
        range = { r: r === 'custom' && !sp.get('from') ? 'yesterday' : r, ...fixed, cmp: effectiveCompare(cmp, fixed.from, fixed.to, cfrom), cfrom };
    }
    // From the date picker ({ r, from, to }; a moving pick keeps only its key) or the comparison picker ({ cmp, cfrom }).
    // The comparison the team chose stays when the dates change, as in Shopify.
    const setRange = (patch) => {
        if ('cmp' in patch) update({ cmp: patch.cmp, cfrom: patch.cmp === 'custom' ? patch.cfrom : null });
        else if (patch.r && patch.r !== 'custom') update({ r: patch.r === 'yesterday' ? null : patch.r, from: null, to: null });
        else update({ r: 'custom', from: patch.from, to: patch.to });
    };
    const syncNow = async () => {
        setSyncing(true);
        try {
            const res = await api.post(`/cro/sync${qs({ brand })}`);
            if (res.state === 'ok') toast.ok(`Read ${fmtInt(res.orders_read)} changed orders from Shopify.`);
            else if (res.state === 'already_running') toast.ok('A sync for this store is already running.');
            else toast.error(new Error(res.error || `Sync ${res.state.replace('_', ' ')}.`));
            setRev((n) => n + 1);
        } catch (e) {
            toast.error(e);
        } finally {
            setSyncing(false);
        }
    };
    const rq = range ? { brand, from: range.from, to: range.to, compare: range.cmp, cfrom: range.cmp === 'custom' ? range.cfrom : undefined } : null;
    return (<>
      <PageHead title={tab === 'overview' ? 'Conversion (CRO)' : `Conversion (CRO) · ${TABS.find((t) => t.key === tab).label}`} sub="How visitors become orders, and what to do next."
        actions={<>
          {globalBrand ? null : <Seg label="Store" size="" options={STORES} value={brand} onChange={(s) => update({ store: s === 'ridhi' ? null : s })}/>}
          <Button icon="refresh" loading={syncing} onClick={syncNow} title="Read the latest orders for this store from Shopify now (it also runs every 15 minutes)">Sync now</Button>
        </>}/>
      <div className="mt-16 col" style={{ gap: 16 }} key={`${brand}-${rev}`}>
        {RANGE_TABS.includes(tab) ? (settings.error ? <ExplainedError error={settings.error} onRetry={settings.reload}/>
            : range ? <RangeBar value={range} today={today} onChange={setRange}/> : <LoadingBlock rows={1}/>) : null}
        {RANGE_TABS.includes(tab) && !rq ? null
            : tab === 'conversion' ? <ConversionTab rq={rq}/>
              : tab === 'landing' ? <LandingTab rq={rq}/>
              : tab === 'site' ? <SiteHealthTab rq={rq}/>
                : tab === 'checkout' ? <CheckoutTab rq={rq}/>
                    : tab === 'products' ? <ProductsTab rq={rq}/>
                        : tab === 'sales' ? <SalesTab rq={rq}/>
                            : tab === 'recommendations' ? <RecommendationsTab brand={brand} onExperiment={(d) => { setDraft(d); update({ tab: 'experiments' }); }}/>
                            : tab === 'experiments' ? (today ? <ExperimentsTab brand={brand} today={today} draft={draft} onDraftUsed={() => setDraft(null)}/> : <LoadingBlock rows={3}/>)
                                : tab === 'alarms' ? <AlarmsTab brand={brand}/>
                                    : tab === 'changes' ? <ChangeLogTab brand={brand}/>
                                        : <OverviewTab rq={rq} today={today} onTab={(t) => update({ tab: t })} onPickDay={(day) => setRange({ r: 'custom', from: day, to: day })}/>}
      </div>
    </>);
}

/** The trend chart needs at least two weeks of points: a short range is shown inside the 14 days ending on its last day. */
function trendRange(rq) {
    const n = rangeDays(rq.from, rq.to);
    return n >= 7 ? rq : { ...rq, from: shiftDay(rq.to, -13), compare: 'previous' };
}

/* ------------------------------------------------------------------ Overview */
/**
 * Overview (design A2): the last 14 days as calendar tiles, then orders, conversion and visits side by side, the
 * sales chart, the shopper journey and the monthly goal (the "What to do next" card was removed on 2026-11-24 at the
 * owner's request; the plan lives on the Recommendations tab). The strip always shows the store's latest
 * 14 days; the gauge's bands, the orders blocks and the chart read the 28 days ending on the last chosen day (and the
 * 28 before, for the chart's comparison).
 *
 * The page appears all at once: one placeholder until every request has answered (or failed, which then shows in
 * its own card), rather than cards arriving one by one. A new range keeps the current page on screen (dimmed) until
 * all of its answers are in and then changes at once; requests that do not depend on the range are not sent again.
 * Answers already remembered in this tab show at once.
 */
function OverviewTab({ rq: wanted, today, onTab, onPickDay }) {
    const wFrom28 = shiftDay(wanted.to, -27);
    const wStrip = { brand: wanted.brand, from: shiftDay(today, -13), to: today, compare: 'none' };
    const wMonth = presetRange('this_month', today);
    // Every request first, in a fixed order; the page is drawn from the last complete set (useSettled).
    const [{ q, conv, conv28, trend, cal, changes, stripSales, stripConv, mtd, goal, movers, heat, trends, breakdown, health }, rq, updating] = useSettled({
        q: useApi(`/cro/overview${qs(wanted)}`),
        conv: useApi(`/cro/conversion${qs(wanted)}`),
        conv28: useApi(`/cro/conversion${qs({ brand: wanted.brand, from: wFrom28, to: wanted.to, compare: 'previous' })}`),
        trend: useApi(`/cro/sales-trend${qs({ brand: wanted.brand, from: wFrom28, to: wanted.to, compare: 'previous' })}`),
        cal: useApi(`/calendar${qs({ brand: wanted.brand, from: shiftDay(wanted.to, -55), to: wanted.to })}`),
        changes: useApi(`/cro/change-log${qs({ brand: wanted.brand, days: 63 })}`),
        // The strip always shows the store's latest 14 days (today included), so it stays put when a day is picked from it.
        stripSales: useApi(`/cro/sales-trend${qs(wStrip)}`),
        stripConv: useApi(`/cro/conversion${qs(wStrip)}`),
        mtd: useApi(`/cro/overview${qs({ brand: wanted.brand, from: wMonth.from, to: wMonth.to, compare: 'previous' })}`),
        goal: useApi(`/cro/goal${qs({ brand: wanted.brand })}`, { remember: false }),
        movers: useApi(`/cro/traffic-changes${qs(wanted)}`),
        heat: useApi(`/cro/buy-heatmap${qs({ brand: wanted.brand, days: 28 })}`),
        trends: useApi(`/cro/overview-trends${qs({ brand: wanted.brand, from: wFrom28, to: wanted.to, compare: 'previous' })}`),
        // The side tiles: the range's sales breakdown, and page speed for the latest 7 days Shopify has published (2 days late).
        breakdown: useApi(`/cro/sales-breakdown${qs(wanted)}`),
        health: useApi(`/cro/site-health${qs({ brand: wanted.brand, from: shiftDay(today, -8), to: shiftDay(today, -2), compare: 'previous' })}`),
    }, wanted);
    const history = conv28.data?.trend ?? [];
    const cvrByDate = new Map([...(stripConv.data?.trend ?? []), ...history].map((r) => [r.date, r.conversion_rate]));
    const stripDays = (stripSales.data?.current ?? []).map((r) => ({ date: r.date, orders: r.orders, cvr: cvrByDate.get(r.date) ?? null }));
    const days = (trend.data?.current ?? []).map((r) => ({ date: r.date, orders: r.orders, cvr: cvrByDate.get(r.date) ?? null }));
    // Calendar events (built-in ones apply to every store) shade the sales chart. No events is fine: the chart just has no bands.
    const events = (cal.data?.events ?? []).filter((e) => !e.brand_id || e.brand_id === rq.brand).map((e) => ({ date: e.date, name: e.name }));
    const all = [q, conv, conv28, trend, cal, changes, stripSales, stripConv, mtd, goal, movers, heat, trends, breakdown, health];
    if (!all.every((x) => x.data !== null || x.error || !x.loading))
        return <OverviewLoading/>;
    return (<div className={`col cro-page${updating ? ' cro-stale' : ''}`} style={{ gap: 18 }} aria-busy={updating || undefined}>
      <CroGate query={q}>
        {(d) => {
            const value = d.metrics.conversion_rate?.value ?? null;
            const scale = conversionScale(history.map((r) => r.conversion_rate), value);
            return (<>
              <DayStrip days={stripDays} from={rq.from} to={rq.to} scale={scale} onPick={onPickDay}/>
              <div className="muted small">{d.period_label} · {d.timezone} time{d.health.last_order_at ? ` · last order ${timeAgo(d.health.last_order_at)}` : ''}</div>
              <div className="ov-trio">
                <div className="ov-side"><SalesTile q={breakdown} onOpen={() => onTab('sales')}/><OrdersCard block={d.metrics.orders} days={days}/></div>
                <GaugeCard value={value} scale={scale} single={rq.from === rq.to} revenue={d.metrics.revenue} aov={d.metrics.aov} perVisit={d.metrics.revenue_per_session}/>
                <div className="ov-side"><HealthTile q={health} onOpen={() => onTab('site')}/><VisitsCard trend={history} total={conv.data?.total} baseTotal={conv.data?.baseline_total} scale={scale}/></div>
              </div>
              {d.cvr_error ? <ExplainedError error={{ code: d.cvr_error.state, message: d.cvr_error.message }}/> : null}
            </>);
        }}
      </CroGate>
      <CroGate query={trend}>
        {(x) => <SalesChart current={x.current} previous={x.previous} events={events} changes={changes.data?.entries ?? []} lastDay={rq.to}/>}
      </CroGate>
      <MoversCard q={movers}/>
      <JourneyCard t={conv.data?.total}/>
      <div className="ov-two">
        <HeatmapCard q={heat}/>
        <TrendsRow q={trends}/>
      </div>
      <Card title="Monthly goal" sub="This month's revenue against the goal you set, with today's pace."><GoalBar brand={rq.brand} today={today} mtd={mtd} g={goal}/></Card>
    </div>);
}

/**
 * A page's requests as they were when all of them had last answered, with the range they belong to, and whether a newer
 * range is still loading. While it loads, the page keeps the previous answers so it changes all at once instead of
 * card by card; after UPDATE_WAIT it shows whatever has arrived. A background refresh of answers already shown (same
 * range) never holds anything back.
 */
const UPDATE_WAIT = 8000;
function useSettled(queries, rq) {
    const list = Object.values(queries);
    const ready = list.every((x) => !x.loading || x.error);
    const key = qs(rq);
    const kept = useRef(null);
    const [late, setLate] = useState('');
    useEffect(() => {
        if (ready) return undefined;
        const t = setTimeout(() => setLate(key), UPDATE_WAIT);
        return () => clearTimeout(t);
    }, [key, ready]);
    if (!kept.current || ready || late === key || qs(kept.current.rq) === key) kept.current = { queries, rq };
    return [kept.current.queries, kept.current.rq, qs(kept.current.rq) !== key];
}

/** The Overview's one placeholder, shaped like the page: the strip, three cards and the chart. */
function OverviewLoading() {
    return (<div className="col" style={{ gap: 18 }} aria-busy="true" aria-label="Loading the overview">
      <Skeleton h={88} r={12}/>
      <div className="ov-trio"><div className="ov-side"><Skeleton h={250} r={16}/><Skeleton h={260} r={16}/></div><Skeleton h={530} r={22}/><div className="ov-side"><Skeleton h={220} r={16}/><Skeleton h={290} r={16}/></div></div>
      <Skeleton h={380} r={16}/>
    </div>);
}

/**
 * This month's revenue against the store's monthly goal, with a mark where today's pace puts it. Set or change the
 * goal here. `mtd` (this month's overview) and `g` (the goal) are loaded by the Overview so the card arrives with it.
 */
function GoalBar({ brand, today, mtd, g }) {
    const toast = useToast();
    const [editing, setEditing] = useState(false);
    const [v, setV] = useState('');
    const goal = g.data?.monthly_revenue ?? 0;
    const save = async () => {
        try { await api.put(`/cro/goal${qs({ brand })}`, { monthly_revenue: Number(v) }); setEditing(false); toast.ok('Monthly goal saved.'); g.reload(); }
        catch (e) { toast.error(e); }
    };
    const day = Number(today.slice(8));
    const days = new Date(Number(today.slice(0, 4)), Number(today.slice(5, 7)), 0).getDate();
    const pace = day / days;
    const got = mtd.data?.metrics?.revenue?.value ?? null;
    const share = goal && got !== null ? got / goal : null;
    const monthName = new Date(`${today}T12:00:00`).toLocaleDateString('en-GB', { month: 'long' });
    if (!g.data)
        return null;
    if (!goal || editing) {
        return (<div className="goal">
          <div className="small strong">{goal ? `Change the goal for ${monthName}` : `Set a revenue goal for ${monthName}`}</div>
          <div className="row mt-8" style={{ gap: 8 }}>
            <input className="input sm" inputMode="decimal" placeholder={goal ? String(goal) : 'e.g. 190000'} value={v} onChange={(e) => setV(e.target.value.replace(/[^0-9.]/g, ''))} aria-label="Monthly revenue goal"/>
            <Button size="sm" variant="primary" disabled={!v} onClick={save}>Save goal</Button>
            {goal ? <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>Cancel</Button> : null}
          </div>
        </div>);
    }
    const ahead = share !== null ? Math.round((share - pace) * 100) : null;
    return (<div className="goal">
      <div className="goal-head"><span className="small">Goal for {monthName}: <b>{money(goal, 'USD', 0)}</b></span>
        <button type="button" className="link-btn xs" onClick={() => { setV(String(goal)); setEditing(true); }}>Change</button></div>
      <div className="goal-bar"><span className="goal-fill" style={{ width: `${Math.min(100, (share ?? 0) * 100)}%` }}/>
        <span className="goal-pace" style={{ left: `${pace * 100}%` }}><span>Today&rsquo;s pace</span></span></div>
      <div className="goal-meta"><span>{share === null ? 'Reading this month…' : `${Math.round(share * 100)}% reached (${money(got, 'USD', 0)}), ${ahead >= 0 ? `${ahead} pts ahead of` : `${-ahead} pts behind`} pace`}</span>
        <span>{days - day} day{days - day === 1 ? '' : 's'} left</span></div>
    </div>);
}

/* ------------------------------------------------------------------ Conversion */
/**
 * Conversion (approved design 2026-11-21, laid out like the new CRO prototype): three tiles, conversion and visits by
 * day, the full funnel against the comparison (grey bars) with a device switch, device and channel tables, the day
 * table, and conversion by country and US state.
 */
function ConversionTab({ rq }) {
    const q = useApi(`/cro/conversion${qs(rq)}`);
    const bench = useApi('/cro/benchmarks');
    const dev = useApi(`/cro/segments${qs({ ...rq, dimension: 'device' })}`);
    const chan = useApi(`/cro/segments${qs({ ...rq, dimension: 'channel' })}`);
    const moved = useApi(`/cro/traffic-changes${qs(rq)}`);
    const typical = bench.data?.benchmarks?.conversion_rate?.value;
    return (<div className="col" style={{ gap: 16 }}>
    <CroGate query={q}>
      {(d) => {
          const t = d.total;
          const b = d.baseline_total;
          if (!d.trend.length) return <CroEmpty icon="calendar" title="No complete day in this range">Shopify reports sessions for complete days only. Pick a range that ends yesterday or earlier.</CroEmpty>;
          const pts = b && t.conversion_rate !== null && b.conversion_rate !== null ? t.conversion_rate - b.conversion_rate : null;
          return (<>
            <div className="cro-three">
              <div className="cro-mini"><span className="k">Conversion rate</span><span className="v num">{pct(t.conversion_rate)}</span>
                {typical ? <span className={`lane-chip ${t.conversion_rate >= typical ? 'lane-live' : 'lane-event'}`} style={{ alignSelf: 'flex-start' }}>{t.conversion_rate >= typical ? 'Above' : 'Below'} the typical store ({typical}%)</span> : null}</div>
              <div className="cro-mini"><span className="k">{b ? d.baseline_label.replace(/^vs /, 'The ') : 'Comparison'}</span><span className="v num">{b ? pct(b.conversion_rate) : '—'}</span>
                <span className="s">{b ? `${fmtInt(b.sessions)} visits` : 'no comparison chosen'}</span></div>
              <div className="cro-mini"><span className="k">Change</span><span className={`v num ${pts === null ? '' : pts >= 0 ? 'up' : 'down'}`}>{pts === null ? '—' : signedPts(pts)}</span>
                <span className="s">{d.conversion_change_pct !== null ? `${signedPct(d.conversion_change_pct)} · ` : ''}{fmtInt(t.sessions)} visits</span></div>
            </div>
            {d.today_left_out ? <div className="muted small">Today is left out: Shopify reports sessions for complete days only.</div> : null}
            <div className="grid cols-2">
              <Card title="Conversion rate by day" sub="Completed checkouts ÷ visits, store time.">
                <LineChart ariaLabel="Conversion rate by day" height={200} yFormat={(v) => pct(v, 1)} area extremes="high"
                  refLine={typical ? { y: typical, label: `Typical ${typical}%` } : undefined}
                  series={[seriesOf(d.trend, 'conversion_rate', 'cvr', 'Conversion rate', 'var(--info)')]}/>
              </Card>
              <Card title="Visits by day">
                <LineChart ariaLabel="Visits by day" height={200} yFormat={fmtInt} area extremes="high" series={[seriesOf(d.trend, 'sessions', 'sessions', 'Visits', 'var(--ok)')]}/>
              </Card>
            </div>
            {d.funnel ? <FullFunnel f={d.funnel} base={d.baseline_funnel} baseLabel={d.baseline_label}/> : null}
            <SplitTable title="Split by device" sub={`${d.baseline_label} · click a column to sort`} q={dev} label="Device"/>
            <SplitTable title="Split by channel" sub="Revenue per visit uses the order's traffic source (Shopify's sales report)" q={chan} label="Channel" rps={moved.data?.channel}/>
            <Card title="Day by day" flush>
              <Paged rows={[...d.trend].reverse()} size={7}>
                {(rows) => (<div className="table-wrap"><table className="t compact">
                  <thead><tr><th>Day</th><th className="r">Visits</th><th className="r">Cart</th><th className="r hide-sm">Checkout</th><th className="r">Orders</th><th className="r">Conversion</th></tr></thead>
                  <tbody>{rows.map((r) => (<tr key={r.date}><td>{fmtDate(r.date)}</td><td className="r">{fmtInt(r.sessions)}</td><td className="r">{pct(r.cart_rate, 1)}</td>
                    <td className="r hide-sm">{pct(r.checkout_rate, 1)}</td><td className="r">{fmtInt(r.completed_checkout)}</td><td className="r"><b>{pct(r.conversion_rate)}</b></td></tr>))}</tbody>
                </table></div>)}
              </Paged>
            </Card>
          </>);
      }}
    </CroGate>
    <GeoCard rq={rq}/>
    </div>);
}

/** The chosen days' funnel for all devices or one, with "Viewed a product" when Shopify reports it. Blue bars: share of
 * visits; thin grey bars: the comparison. Each step shows its share of the step before and the change in points. */
const FUNNEL_LABEL = { viewed_product: 'Viewed a product', added_to_cart: 'Added to cart', reached_checkout: 'Reached checkout', completed_checkout: 'Purchased' };
function FullFunnel({ f, base, baseLabel }) {
    const [device, setDevice] = useState('all');
    const options = [{ key: 'all', label: 'All' }, ...f.devices.filter((x) => x.sessions > 0).slice(0, 3).map((x) => ({ key: x.label, label: x.label }))];
    const pick = (src) => (!src ? null : device === 'all' ? src.all : src.devices.find((x) => x.label === device) || null);
    const cur = pick(f) || f.all;
    const old = pick(base);
    const steps = [{ key: 'sessions', count: cur.sessions }, ...cur.steps.filter((s) => s.count !== null)];
    const oldCount = (key) => (key === 'sessions' ? old?.sessions : old?.steps.find((s) => s.key === key)?.count);
    return (<Card title="Full funnel" sub={`Bar: share of visits${old ? ` · grey: ${baseLabel.replace(/^vs /, '')}` : ''}${f.product_views_available ? '' : ' · Shopify did not report product views'}`}
      actions={options.length > 2 ? <Seg label="Device" options={options} value={device} onChange={setDevice}/> : null}>
      <div className="cro-funnel">
        {steps.map((s, i) => {
            const share = cur.sessions ? (s.count / cur.sessions) * 100 : 0;
            const before = oldCount(s.key);
            const was = before !== undefined && before !== null && old?.sessions ? (before / old.sessions) * 100 : null;
            const raw = i && was !== null ? share - was : null;
            const pts = raw !== null && Math.abs(raw) < 0.005 ? 0 : raw;   // no "−0.00"
            const prevStep = i ? steps[i - 1].count : null;
            return (<div key={s.key} className="cro-fstep">
              <div className="lr"><span>{i ? FUNNEL_LABEL[s.key] : 'Visits'}</span>
                <span className="num"><b>{fmtInt(s.count)}</b> <span className="muted">· {i ? `${pct(prevStep ? (s.count / prevStep) * 100 : null, 1)} of the step before` : '100%'}</span>
                  {pts !== null ? <> <span className={pts > 0 ? 'up' : pts < 0 ? 'down' : 'muted'}>{signedPts(pts)}</span></> : null}</span></div>
              <div className="bar"><span style={{ width: `${share}%` }}/></div>
              {was !== null ? <div className="prev"><span style={{ width: `${was}%` }}/><em className="num">{fmtInt(before)} · {pct(was, 1)}</em></div> : null}
            </div>);
        })}
      </div>
    </Card>);
}

/** Device or channel table: visits, add to cart, conversion, revenue per visit (channels only), orders and the change
 * against the comparison, sortable by any column. */
function SplitTable({ title, sub, q, label, rps }) {
    const [sort, setSort] = useState({ key: 'sessions', dir: -1 });
    const byKey = new Map((rps ?? []).map((r) => [String(r.key).toLowerCase(), r]));
    const cols = [['label', label], ['sessions', 'Visits'], ['added_to_cart_rate', 'Add to cart'], ['conversion_rate', 'Conversion'], ...(rps ? [['rps', 'Rev / visit']] : []), ['orders', 'Orders']];
    return (<Card title={title} sub={sub} flush>
      <CroGate query={q} rows={3}>
        {(d) => {
            const rows = d.rows.map((r) => {
                const m = byKey.get(String(r.label).toLowerCase());
                return { ...r, rps: m?.revenue_per_session ?? null, rps_change: m?.revenue_per_session_change_pct ?? null };
            }).sort((a, b) => {
                const x = a[sort.key], y = b[sort.key];
                if (typeof x === 'string' || typeof y === 'string') return sort.dir * String(x).localeCompare(String(y));
                return sort.dir * ((x ?? -1) - (y ?? -1));
            });
            const head = (k, l) => (<th key={k} className={k === 'label' ? '' : 'r'} aria-sort={sort.key === k ? (sort.dir > 0 ? 'ascending' : 'descending') : 'none'}>
              <button type="button" className="th-sort" onClick={() => setSort((s) => ({ key: k, dir: s.key === k ? -s.dir : -1 }))}>{l}{sort.key === k ? (sort.dir > 0 ? ' ↑' : ' ↓') : ''}</button></th>);
            return (<div className="table-wrap"><table className="t compact">
              <thead><tr>{cols.map(([k, l]) => head(k, l))}<th className="r">vs comparison</th></tr></thead>
              <tbody>{rows.map((r) => (<tr key={r.label} className={r.sessions < 100 ? 'fade' : ''}>
                <td><b>{readable(r.label)}</b></td><td className="r">{fmtInt(r.sessions)}</td><td className="r">{pct(r.added_to_cart_rate, 1)}</td>
                <td className="r"><b>{pct(r.conversion_rate)}</b></td>{rps ? <td className="r">{r.rps === null ? '—' : money(r.rps)}</td> : null}<td className="r">{fmtInt(r.orders)}</td>
                <td className="r"><div className="cro-stack">
                  <span className={r.conversion_rate_change_pts >= 0 ? 'up' : 'down'}>{r.conversion_rate_change_pts === null ? '—' : `${r.conversion_rate_change_pts >= 0 ? '↑' : '↓'} CVR ${signedPts(r.conversion_rate_change_pts)}`}</span>
                  {rps && r.rps_change !== null ? <span className={r.rps_change >= 0 ? 'up' : 'down'}>{r.rps_change >= 0 ? '↑' : '↓'} RPS {signedPct(r.rps_change)}</span> : null}
                  {r.sessions_change_pct !== null ? <span className="muted">visits {signedPct(r.sessions_change_pct)}</span> : null}
                </div></td>
              </tr>))}</tbody>
            </table></div>);
        }}
      </CroGate>
    </Card>);
}

/** Conversion by country and by US state side by side; the bar is green at or above the store's conversion, amber below. */
function GeoCard({ rq }) {
    const q = useApi(`/cro/geo${qs(rq)}`);
    return (<Card title="Split by country and US state" sub="Share of visits and conversion by place (complete days only)">
      <CroGate query={q} rows={4}>
        {(d) => {
            const all = d.countries.reduce((a, r) => a + r.sessions, 0);
            const store = all ? d.countries.reduce((a, r) => a + r.orders, 0) / all * 100 : null;
            const table = (rows, head) => (rows.length ? (<div className="table-wrap"><table className="t compact">
              <thead><tr><th>{head}</th><th className="r">Visits</th><th className="r hide-sm">Add to cart</th><th className="r">Conversion</th><th className="r">Purchases</th></tr></thead>
              <tbody>{rows.slice(0, 8).map((r) => (<tr key={r.label} className={r.too_few_sessions ? 'fade' : ''}>
                <td>{r.label}</td><td className="r"><b>{fmtInt(r.sessions)}</b> <span className="muted xs">{pct(r.share_pct, 1)}</span></td>
                <td className="r hide-sm">{pct(r.cart_rate, 1)}</td>
                <td className="r nowrap"><span className="cro-mb"><span style={{ width: `${Math.min(100, ((r.conversion_rate ?? 0) / 4) * 100)}%`, background: store !== null && r.conversion_rate >= store ? 'var(--ok)' : 'var(--saffron)' }}/></span>
                  <b>{pct(r.conversion_rate)}</b> {r.too_few_sessions ? <span className="muted xs">few visits</span> : <PtsDelta v={r.conversion_change_pts}/>}</td>
                <td className="r">{fmtInt(r.orders)}</td>
              </tr>))}</tbody>
            </table></div>) : <div className="muted small">Shopify has no visits by place for these days.</div>);
            return (<>
              <WindowNote w={d.window} to={d.to}/>
              <div className="cro-two-wide mt-8">
                <div><div className="cro-cap">By country</div>{table(d.countries, 'Country')}</div>
                <div><div className="cro-cap">By US state</div>{table(d.us_states, 'State')}</div>
              </div>
            </>);
        }}
      </CroGate>
    </Card>);
}

/* ------------------------------------------------------------------ Cart & checkout: health and splits */
const avgOf = (rows, key) => {
    const v = rows.map((r) => r[key]).filter((x) => x !== null && x !== undefined);
    return v.length ? v.reduce((a, x) => a + x, 0) / v.length : null;
};

/**
 * Checkout health: one score out of 100 from four checks, each worth 25 points in proportion to how the store compares
 * with the typical store (cart kept, checkout finished, conversion rate) or with its own desktop (mobile conversion).
 * Below it, gauges with a mark at the typical store's figure: green when the store is better, red when it is behind.
 */
function CheckoutHealth({ d, b, rq }) {
    const dev = useApi(`/cro/segments${qs({ ...rq, dimension: 'device' })}`);
    const cart = avgOf(d.trend, 'cart_abandonment_rate');
    const check = avgOf(d.trend, 'checkout_abandonment_rate');
    const cvr = d.total?.conversion_rate ?? null;
    const rows = dev.data?.rows ?? [];
    const mob = rows.find((r) => /mobile/i.test(r.label))?.conversion_rate;
    const desk = rows.find((r) => /desktop/i.test(r.label))?.conversion_rate;
    const ratio = mob !== undefined && desk ? mob / desk : null;
    const checks = [
        cart !== null && b ? { k: 'cart', label: 'Carts kept', value: 100 - cart, typical: 100 - b.cart_abandonment_rate.value, show: `${Math.round(100 - cart)}%` } : null,
        check !== null && b ? { k: 'chk', label: 'Checkouts finished', value: 100 - check, typical: 100 - b.checkout_abandonment_rate.value, show: `${Math.round(100 - check)}%` } : null,
        cvr !== null && b ? { k: 'cvr', label: 'Visits that bought', value: cvr, typical: b.conversion_rate.value, show: pct(cvr) } : null,
        ratio !== null ? { k: 'mob', label: 'Mobile against desktop', value: ratio * 100, typical: 100, show: `${Math.round(ratio * 100)}% of desktop` } : null,
    ].filter(Boolean);
    if (!checks.length)
        return null;
    const points = checks.map((c) => 25 * Math.min(1, c.value / c.typical));
    const score = Math.round((points.reduce((a, x) => a + x, 0) / (checks.length * 25)) * 100);
    const word = score >= 75 ? 'good' : score >= 50 ? 'fair' : 'needs work';
    const gauges = [
        cart !== null && b ? { k: 'g1', label: 'Cart abandonment', value: cart, ref: b.cart_abandonment_rate.value, max: 100, show: pct(cart, 0), better: cart <= b.cart_abandonment_rate.value } : null,
        check !== null && b ? { k: 'g2', label: 'Checkout abandonment', value: check, ref: b.checkout_abandonment_rate.value, max: 100, show: pct(check, 0), better: check <= b.checkout_abandonment_rate.value } : null,
        cvr !== null && b ? { k: 'g3', label: 'Conversion rate', value: cvr, ref: b.conversion_rate.value, max: Math.max(5, b.conversion_rate.value * 2), show: pct(cvr), better: cvr >= b.conversion_rate.value } : null,
    ].filter(Boolean);
    return (<>
      <Card>
        <div className="health">
          <Gauge value={score} max={100} label={String(score)} sub={`of 100 · ${word}`} color={score >= 75 ? 'var(--ok)' : score >= 50 ? 'var(--saffron)' : 'var(--crit)'} width={170}/>
          <div style={{ minWidth: 0 }}>
            <b style={{ fontSize: 16 }}>Checkout health</b>
            <div className="muted small">Each check is worth 25 points, in proportion to how the store compares with the typical store.</div>
            <div className="health-checks">
              {checks.map((c, i) => {
                  const ahead = c.value >= c.typical;
                  return (<div key={c.k} className="health-check">
                    <span className="label">{c.label}</span>
                    <div className="num"><b>{c.show}</b> <span className={ahead ? 'chg-up' : 'chg-down'}>{ahead ? 'ahead' : 'behind'}</span></div>
                    <span className="health-bar"><span className="grow-x" style={{ width: `${Math.round(points[i] * 4)}%`, background: ahead ? 'var(--ok)' : 'var(--crit)', animationDelay: `${i * 80}ms` }}/></span>
                  </div>);
              })}
            </div>
          </div>
        </div>
      </Card>
      <div className="grid cols-3">
        {gauges.map((x) => (<Card key={x.k}>
          <div className="label">{x.label}</div>
          <div className="gauge-row">
            <Gauge value={x.value} max={x.max} mark={x.ref} label={x.show} color={x.better ? 'var(--ok)' : 'var(--crit)'} width={140}/>
            <div className="col" style={{ gap: 6, minWidth: 0 }}>
              <Pill tone={x.better ? 'ok' : 'crit'}>{x.better ? 'Better than typical' : 'Behind typical'}</Pill>
              <span className="muted xs">Mark = typical store ({x.ref}%). Average of the days shown.</span>
            </div>
          </div>
        </Card>))}
      </div>
    </>);
}

const SEG_COLORS = ['var(--info)', 'var(--ok)', 'var(--cpc)', 'var(--saffron)', '#4f7aa6', '#3f7d58', 'var(--ink-2)'];

/** Device or channel split: each row's share of sessions as a coloured bar, its conversion rate, and the change. */
function SegmentCard({ rq, dimension, title }) {
    const q = useApi(`/cro/segments${qs({ ...rq, dimension })}`);
    return (<Card title={title} sub="Share of sessions and conversion, against the comparison (complete days only).">
      <CroGate query={q} rows={3}>
        {(d) => {
            const total = d.rows.reduce((n, r) => n + (r.sessions || 0), 0) || 1;
            const best = Math.max(...d.rows.map((r) => r.conversion_rate ?? 0));
            return (<>
              <Paged rows={d.rows} size={6}>
                {(rows) => (<div className="segbars">
                  {rows.map((r, i) => {
                      const share = (r.sessions || 0) / total;
                      return (<div key={r.label} className="segbar" title={`${r.label}: ${fmtInt(r.sessions)} sessions (${Math.round(share * 100)}%), conversion ${pct(r.conversion_rate)}`}>
                        <span className="segbar-label">{r.label}</span>
                        <span className="segbar-track"><span className="grow-x" style={{ width: `${Math.max(1.5, share * 100)}%`, background: SEG_COLORS[i % SEG_COLORS.length], animationDelay: `${i * 60}ms` }}/></span>
                        <span className="segbar-share muted">{Math.round(share * 100)}%</span>
                        <span className="segbar-cvr"><b>{pct(r.conversion_rate)}</b>{r.conversion_rate === best && rows.length > 1 ? <Pill tone="ok">best</Pill> : null}</span>
                        <span className="segbar-ch muted hide-sm">{signedPts(r.conversion_rate_change_pts)}</span>
                      </div>);
                  })}
                </div>)}
              </Paged>
              <div className="muted xs" style={{ marginTop: 8 }}>{d.revenue_note}</div>
            </>);
        }}
      </CroGate>
    </Card>);
}

/* ------------------------------------------------------------------ shared bits for Shopify session reports */
/** What a Shopify session report is compared with, and its days when they differ from the range (today left out). */
function WindowNote({ w, to, extra }) {
    if (!w) return null;
    const span = (a, b) => (a === b ? fmtDate(a) : `${fmtDate(a)} – ${fmtDate(b)}`);
    const parts = [
        w.to !== to ? `Shopify figures for ${span(w.from, w.to)} (today is not complete yet)` : null,
        w.base_from ? `compared with ${span(w.base_from, w.base_to)}` : 'no comparison',
        extra,
    ].filter(Boolean);
    const text = parts.join(' · ');
    return <div className="muted small">{text.charAt(0).toUpperCase() + text.slice(1)}</div>;
}

/** A change in points, coloured; `goodWhenUp` false for rates where lower is better (bounce, abandonment). */
function PtsDelta({ v, goodWhenUp = true }) {
    if (v === null || v === undefined) return <span className="muted">—</span>;
    const good = goodWhenUp ? v > 0 : v < 0;
    return <span className={`delta ${v === 0 ? 'flat' : good ? 'up' : 'down'}`}>{signedPts(v)}</span>;
}

/** A change chip like "▲ +0.4 pts" or "▼ 12%": green when the move is good for the store, red when bad, grey when
 * the figure is only context (`neutral`). */
function ChangeChip({ v, unit = 'pts', goodWhenUp = true, neutral }) {
    if (v === null || v === undefined || Number.isNaN(v)) return null;
    const lane = neutral || v === 0 ? 'plain' : (goodWhenUp ? v > 0 : v < 0) ? 'lane-live' : 'lane-due';
    const text = unit === 'pts' ? signedPts(v).replace(' pts', '') + ' pts' : signedPct(v);
    return <span className={`lane-chip ${lane}`}>{v > 0 ? '▲' : v < 0 ? '▼' : ''} {text}</span>;
}

/** Shopify's partial answers: which extra figures it could not give. */
function MissingNote({ errors, names }) {
    const missing = Object.keys(errors ?? {}).map((k) => names[k]).filter(Boolean);
    if (!missing.length) return null;
    return <div className="muted xs">Shopify did not answer: {[...new Set(missing)].join(', ')}.</div>;
}

const pctChange = (a, b) => (a === null || a === undefined || !b ? null : ((a - b) / b) * 100);

/* ------------------------------------------------------------------ Landing pages */
/**
 * Landing pages (approved design 2026-11-21): how bounce is counted, three tiles (the "bounce worse than usual" tile
 * filters the table), page types, bounce by source and by device, the landing-page table with search, type filter and
 * sort, and a pages × traffic source (or page type × device) grid coloured against the grid's own average.
 */
/* The Landing pages tab's six views (owner request 2026-11-23, numbered like the CRO prototype). 1, 5 and 6 follow the
 * date range above; 2, 3 and 4 use their own fixed windows of complete days. */
const LANDING_VIEWS = [
    { key: 'all', label: '1. All landing pages' }, { key: 'compare', label: '2. Week / Month compare' }, { key: 'funnel', label: '3. Funnel by page' },
    { key: 'daily', label: '4. Date-wise' }, { key: 'segments', label: '5. Page type, source, device' }, { key: 'grids', label: '6. Page × source grids' },
];

/** The Landing pages tab: six views of the store's landing pages; every page name opens its deep dive in the left-side
 * panel. */
function LandingTab({ rq }) {
    const [view, setView] = useState('all');
    const [dive, setDive] = useState(null);   // { path, type } of the page whose deep dive is open
    const open = (path, type) => setDive({ path, type });
    return (<div className="col" style={{ gap: 16 }}>
      <div className="lp-views"><Seg label="Landing pages view" size="" options={LANDING_VIEWS} value={view} onChange={setView}/></div>
      {view === 'compare' ? <LandingCompare brand={rq.brand} onOpen={open}/>
          : view === 'funnel' ? <FunnelByPage brand={rq.brand} onOpen={open}/>
            : view === 'daily' ? <PagesDaily brand={rq.brand} onOpen={open}/>
              : view === 'grids' ? <GridCard rq={rq}/>
                : <LandingReport rq={rq} part={view} onOpen={open}/>}
      {dive ? <PageDive brand={rq.brand} path={dive.path} type={dive.type} onClose={() => setDive(null)}/> : null}
    </div>);
}

/** Views 1 (every page, with the tiles) and 5 (page types, sources, devices) of the range's landing page report. */
function LandingReport({ rq, part, onOpen }) {
    const q = useApi(`/cro/landing-pages${qs(rq)}`);
    const [flagOnly, setFlagOnly] = useState(false);
    return (<CroGate query={q}>
      {(d) => {
          if (!d.pages.length) return <CroEmpty icon="calendar" title="No visits in this range">Shopify reports landing pages for complete days. Pick a range that ends yesterday or earlier.</CroEmpty>;
          const flagged = d.pages.filter((p) => p.bounce_flag);
          const judged = d.pages.filter((p) => !p.too_few_sessions).length;
          const top = d.pages[0];
          const context = <div className="cro-ctx"><b>Showing: {fmtDate(d.window.from)} – {fmtDate(d.window.to)}</b>{d.window.base_from ? <span className="muted"> · changes (pts) are against {fmtDate(d.window.base_from)} – {fmtDate(d.window.base_to)}</span> : null}</div>;
          if (part === 'segments') {
              return (<>
                {context}
                <BounceTable title="By page type" rows={d.page_types} head="Page type" share/>
                <div className="cro-two-wide">
                  <BounceTable title="Bounce by traffic source" rows={d.by_source} head="Source"/>
                  <BounceTable title="Bounce by device" rows={d.by_device} head="Device"/>
                </div>
              </>);
          }
          return (<>
            <div className="callout info"><Icon name="info"/><div><b>Bounce</b> is Shopify&rsquo;s: a visit that saw only one page. Pages with fewer than {fmtInt(d.min_sessions)} visits are marked &ldquo;few visits&rdquo; and are not compared.</div></div>
            {context}
            <div className="cro-three">
              <div className="cro-mini"><span className="k">Landing pages with visits</span><span className="v num">{d.pages.length >= 200 ? '200+' : fmtInt(d.pages.length)}</span><span className="s">{fmtInt(judged)} with {fmtInt(d.min_sessions)}+ visits</span></div>
              <button type="button" className={`cro-mini as-btn${flagOnly ? ' on' : ''}`} aria-pressed={flagOnly} onClick={() => setFlagOnly((f) => !f)} disabled={!flagged.length}>
                <span className="k"><Icon name="alert" size="sm"/>Bounce worse than usual</span><span className={`v num${flagged.length ? ' down' : ''}`}>{flagged.length}</span>
                <span className="s">pages {d.bounce_flag_pts}+ pts above their last period{flagged.length ? ' · click to show only these' : ''}</span></button>
              <div className="cro-mini"><span className="k">Top landing page</span><span className="v" style={{ fontSize: 17 }} title={top.path}><span className="ellipsis" style={{ display: 'block' }}>{top.path}</span></span><span className="s">{fmtInt(top.sessions)} visits · bounce {pct(top.bounce_rate, 1)}</span></div>
            </div>
            <LandingTable d={d} flagOnly={flagOnly} onOpen={onOpen}/>
            <MissingNote errors={d.errors} names={{ page_sales: 'revenue by page', page_sources: 'top source', pages_prev: 'the comparison' }}/>
          </>);
      }}
    </CroGate>);
}

/** A bounce rate as a small amber bar, the figure and its change (lower is better). */
function BounceCell({ r, usual }) {
    return (<span className="cro-bounce"><span className="cro-mb amber"><span style={{ width: `${Math.min(100, r.bounce_rate ?? 0)}%` }}/></span>
      {pct(r.bounce_rate, 1)} <PtsDelta v={r.bounce_change_pts} goodWhenUp={false}/>
      {usual ? <em className="down">usually {pct(r.previous_bounce_rate, 1)}</em> : null}</span>);
}

function BounceTable({ title, rows, head, share }) {
    return (<Card title={title} flush>
      {rows.length ? (<div className="table-wrap"><table className="t compact">
        <thead><tr><th>{head}</th><th className="r">Visits</th>{share ? <th className="r">Share</th> : null}<th>Bounce rate</th>{share ? <th className="r hide-sm">Add to cart</th> : null}<th className="r">Conversion</th></tr></thead>
        <tbody>{rows.slice(0, 8).map((r) => (<tr key={r.label} className={r.too_few_sessions ? 'fade' : ''}>
          <td><b>{readable(r.label)}</b></td><td className="r">{fmtInt(r.sessions)}</td>{share ? <td className="r">{pct(r.share_of_sessions, 1)}</td> : null}
          <td><BounceCell r={r}/></td>{share ? <td className="r hide-sm">{pct(r.added_to_cart_rate, 1)}</td> : null}
          <td className="r"><b>{pct(r.conversion_rate)}</b> <PtsDelta v={r.conversion_change_pts}/></td>
        </tr>))}</tbody>
      </table></div>) : <div className="pad-x muted small" style={{ paddingBottom: 12 }}>Nothing for these days.</div>}
    </Card>);
}

const LANDING_SORT = [
    { key: 'sessions', label: 'Visits' }, { key: 'bounce_rate', label: 'Bounce rate' }, { key: 'bounce_change_pts', label: 'Bounce change' },
    { key: 'conversion_rate', label: 'Conversion' }, { key: 'revenue_per_session', label: 'Revenue / visit' },
];
function LandingTable({ d, flagOnly, onOpen }) {
    const [search, setSearch] = useState('');
    const [type, setType] = useState('');
    const [sort, setSort] = useState('sessions');
    const [all, setAll] = useState(false);
    const types = [...new Set(d.pages.map((p) => p.page_type))].sort();
    const s = search.trim().toLowerCase();
    const rows = d.pages.filter((p) => (!flagOnly || p.bounce_flag) && (!type || p.page_type === type) && (!s || p.path.includes(s)))
        .sort((a, b) => (b[sort] ?? -Infinity) - (a[sort] ?? -Infinity));
    const shown = all ? rows : rows.slice(0, 25);
    return (<Card title="Landing pages" sub={`${d.revenue_note} Click a page for its deep dive.`} flush
      actions={<div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
        <label className="cro-search"><Icon name="search" size="sm"/><input className="input sm" placeholder="Search page" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Search page"/></label>
        <select className="input sm" value={type} onChange={(e) => setType(e.target.value)} aria-label="Page type"><option value="">All page types</option>{types.map((t) => <option key={t} value={t}>{t}</option>)}</select>
        <select className="input sm" value={sort} onChange={(e) => setSort(e.target.value)} aria-label="Sort by">{LANDING_SORT.filter((o) => o.key !== 'revenue_per_session' || d.revenue_available).map((o) => <option key={o.key} value={o.key}>Sort: {o.label}</option>)}</select>
      </div>}>
      {shown.length ? (<div className="table-wrap"><table className="t compact">
        <thead><tr><th>Page</th><th className="r">Visits</th><th>Bounce rate</th><th className="r hide-sm">Add to cart</th><th className="r">Conversion</th>
          {d.revenue_available ? <><th className="r hide-sm">Revenue</th><th className="r">Rev / visit</th></> : null}<th className="hide-sm">Top source</th></tr></thead>
        <tbody>{shown.map((p) => (<tr key={p.path} className={p.bounce_flag ? 'flag' : p.too_few_sessions ? 'fade' : ''}>
          <td style={{ maxWidth: 280 }}><button type="button" className="link-btn lp-path strong" title={`${p.path} · click for this page's deep dive (week on week, month on month)`} onClick={() => onOpen(p.path, p.page_type)}>{p.bounce_flag ? <Icon name="alert" size="sm" className="down"/> : null} {p.path === '/' ? '/ (homepage)' : p.path}</button><span className="lane-chip plain">{p.page_type}</span></td>
          <td className="r">{fmtInt(p.sessions)}</td><td><BounceCell r={p} usual={p.bounce_flag}/></td><td className="r hide-sm">{pct(p.added_to_cart_rate, 1)}</td>
          <td className="r">{p.too_few_sessions ? <span className="muted xs">few visits</span> : <><b>{pct(p.conversion_rate)}</b> <PtsDelta v={p.conversion_change_pts}/></>}</td>
          {d.revenue_available ? <><td className="r hide-sm"><b>{p.revenue === null ? '—' : money(p.revenue, 'USD', 0)}</b></td><td className="r">{p.revenue_per_session === null ? '—' : money(p.revenue_per_session)}</td></> : null}
          <td className="hide-sm">{p.top_source ? <>{readable(p.top_source)} <span className="muted xs">({pct(p.top_source_share, 0)})</span></> : '—'}</td>
        </tr>))}</tbody>
      </table></div>) : <div className="pad-x muted small" style={{ paddingBottom: 12 }}>No pages match.</div>}
      {rows.length > 25 ? <div className="pad-x" style={{ paddingBottom: 10 }}><button type="button" className="link-btn" onClick={() => setAll((a) => !a)}>{all ? 'Show the top 25' : `Show all ${fmtInt(rows.length)} pages`}</button></div> : null}
    </Card>);
}

/** Pages × traffic source or page types × device: each cell's rate against the grid's own "All" figure. Green better,
 * red worse (lower is better for bounce), grey under 30 visits. */
const GRID_METRICS = [{ key: 'conversion_rate', label: 'Conversion' }, { key: 'added_to_cart_rate', label: 'Add to cart' }, { key: 'bounce_rate', label: 'Bounce' }];
function GridCard({ rq }) {
    const q = useApi(`/cro/landing-grids${qs(rq)}`);
    const [kind, setKind] = useState('page_by_source');
    const [metric, setMetric] = useState('conversion_rate');
    const lowerBetter = metric === 'bounce_rate';
    const tone = (v, avg) => {
        if (v === null || v === undefined) return 'g-none';
        if (!avg) return '';
        const r = (v / avg) * (lowerBetter ? -1 : 1) + (lowerBetter ? 2 : 0);
        return r >= 1.25 ? 'g-great' : r >= 1.1 ? 'g-good' : r <= 0.75 ? 'g-worse' : r <= 0.9 ? 'g-bad' : '';
    };
    return (<Card title={kind === 'page_by_source' ? 'Landing page × traffic source' : 'Device × page type'} sub="Green: better than the grid's average, red: worse; grey: under 30 visits"
      actions={<div className="row" style={{ gap: 8 }}><Seg label="Metric" options={GRID_METRICS} value={metric} onChange={setMetric}/>
        <Seg label="Grid" options={[{ key: 'page_by_source', label: 'Pages' }, { key: 'type_by_device', label: 'Types' }]} value={kind} onChange={setKind}/></div>}>
      <CroGate query={q} rows={4}>
        {(d) => {
            const grid = d[kind];
            if (!grid?.rows?.length) return <div className="muted small">Shopify did not return this split.</div>;
            const avg = grid.total?.[metric];
            const cell = (c, key) => (<div key={key} className={`cro-gc ${tone(c?.[metric], avg)}`} title={`${fmtInt(c?.sessions ?? 0)} visits`}><b>{c?.[metric] === null || c?.[metric] === undefined ? '—' : pct(c[metric], 1)}</b><span>{fmtInt(c?.sessions ?? 0)}</span></div>);
            return (<div className="table-wrap"><div className="cro-grid" style={{ gridTemplateColumns: `minmax(150px, 1.6fr) repeat(${grid.columns.length + 1}, minmax(78px, 1fr))` }}>
              <span className="gh">{kind === 'page_by_source' ? 'Landed on' : 'Page type'}</span>{grid.columns.map((c) => <span key={c} className="gh">{readable(c)}</span>)}<span className="gh">All</span>
              {grid.rows.map((rk, i) => (<div key={rk} className="cro-grid-row">
                <span className="gr" title={rk}>{rk === '/' ? '/ (homepage)' : readable(rk)}</span>
                {grid.cells[i].map((c, j) => cell(c, j))}{cell(grid.row_totals?.[i], 'all')}
              </div>))}
              <span className="gr strong">All</span>{(grid.column_totals ?? []).map((c, j) => cell(c, `t${j}`))}{cell(grid.total, 'tt')}
            </div></div>);
        }}
      </CroGate>
    </Card>);
}

/* ------------------------------------------------------------------ Site health */
/**
 * Site health (approved design 2026-11-21, under Advanced): mobile page speed as three tiles coloured by Google's
 * rating, the daily loading-time chart against the 2.5 s limit, speed by page type and for the busiest mobile pages,
 * and site search.
 */
function SiteHealthTab({ rq }) {
    const q = useApi(`/cro/site-health${qs(rq)}`);
    return (<CroGate query={q}>
      {(d) => {
          const mob = d.devices.Mobile || Object.values(d.devices)[0];
          const desk = d.devices.Desktop;
          return (<>
            <WindowNote w={d.window} to={d.to}/>
            {d.late_note ? <div className="callout info"><Icon name="clock"/><div>{d.late_note}</div></div> : null}
            <Card title="Mobile page speed" sub={mob ? `What 3 in 4 mobile visits experience (Google's 75th percentile) · ${fmtInt(mob.page_loads)} page loads` : 'Page speed'}>
              {mob ? (<>
                <div className="cro-three">{VITALS.map((m) => <VitalTile key={m.key} metric={m} v={mob[m.key]}/>)}</div>
                {desk ? <p className="muted small" style={{ margin: '12px 0 0' }}>Desktop: {VITALS.map((m) => `${m.key.toUpperCase()} ${fmtVital(m.key, desk[m.key]?.p75)}`).join(' · ')}.</p> : null}
                {d.trend.length > 1 ? (<div className="mt-16"><div className="small strong">Mobile loading time (LCP) by day · dashed line = Google&rsquo;s 2.5 s limit</div>
                  <LineChart ariaLabel="Mobile loading time by day" height={200} yFormat={(v) => `${v.toFixed(1)} s`} extremes="low"
                    refLine={{ y: 2.5, label: 'Good: 2.5 s' }} series={[seriesOf(d.trend, 'lcp_s', 'lcp', 'Loading time', 'var(--info)')]}/></div>) : null}
              </>) : <div className="muted small">Shopify has no page speed for these days yet.</div>}
            </Card>
            {d.speed_available ? (<Card title="Mobile speed by page type" flush>
              <VitalsTable rows={d.page_types} head="Page type" pick={(r) => r.label}/>
              <div className="pad-x small strong" style={{ paddingTop: 12 }}>Most-visited mobile pages</div>
              <VitalsTable rows={d.pages} head="Page" pick={(r) => r.path}/>
            </Card>) : null}
            <SearchCard s={d.search}/>
            <div className="callout"><Icon name="info"/><div><b>Not shown yet.</b> JavaScript errors and 404 pages (Shopify does not record them); rage clicks and scroll depth (need Microsoft Clarity).</div></div>
            <MissingNote errors={d.errors} names={{ device: 'page speed', page_type: 'speed by page type', pages: 'speed by page', trend: 'the speed trend',
                search_conv: 'site search', top_terms: 'top searches', zero_terms: 'searches with no results', term_clicks: 'search click rates' }}/>
          </>);
      }}
    </CroGate>);
}

/** One Core Web Vital as a tile tinted by Google's rating, with its change against the comparison. */
function VitalTile({ metric, v }) {
    const r = RATING[v?.rating];
    const tint = v?.rating === 'good' ? 'good' : v?.rating === 'poor' ? 'poor' : v?.rating ? 'work' : '';
    const ch = v?.change;
    const chText = ch === null || ch === undefined ? 'no comparison' : ch === 0 ? 'no change vs before'
        : `${ch > 0 ? '+' : '−'}${metric.key === 'cls' ? Math.abs(ch).toFixed(2) : metric.key === 'lcp' ? `${(Math.abs(ch) / 1000).toFixed(2)} s` : `${Math.abs(ch)} ms`} ${ch > 0 ? 'slower' : 'faster'} than before`;
    return (<div className={`cro-vital ${tint}`} title={metric.help}>
      <div className="top"><span>{metric.label}</span>{r ? <span className={`lane-chip ${r.lane}`}>{r.label}</span> : null}</div>
      <span className="v num">{fmtVital(metric.key, v?.p75)}</span>
      <span className={ch > 0 ? 'down' : ch < 0 ? 'up' : 'muted'} style={{ fontSize: 12 }}>{chText.replace('slower', metric.key === 'cls' ? 'more shift' : 'slower').replace('faster', metric.key === 'cls' ? 'steadier' : 'faster')}</span>
      {v?.good_share !== null && v?.good_share !== undefined ? <span className="s">{pct(v.good_share, 1)} of loads good · {pct(v.poor_share, 1)} poor</span> : null}
    </div>);
}

function VitalsTable({ rows, head, pick }) {
    const cell = (m, v) => { const r = v?.rating; return <span className={`cro-vd ${r === 'good' ? 'up' : r === 'poor' ? 'down' : r ? 'cro-warn' : 'muted'}`}><i/>{fmtVital(m, v?.p75)}</span>; };
    return (<div className="table-wrap"><table className="t compact">
      <thead><tr><th>{head}</th><th className="r">Page loads</th>{VITALS.map((v) => <th key={v.key} className="r" title={v.help}>{v.key.toUpperCase()}</th>)}</tr></thead>
      <tbody>{rows.slice(0, 15).map((r) => (<tr key={pick(r)}><td style={{ maxWidth: 260 }}><div className="ellipsis strong" title={pick(r)}>{pick(r)}</div></td><td className="r">{fmtInt(r.page_loads)}</td>
        {VITALS.map((m) => <td key={m.key} className="r">{cell(m.key, r[m.key])}</td>)}</tr>))}</tbody>
    </table></div>);
}

/** Site search: how many visits search, how searchers convert, what they look for and what finds nothing. */
function SearchCard({ s }) {
    if (!s) return (<Card title="Site search"><div className="muted small">Shopify has no site search figures for these days.</div></Card>);
    return (<Card title="Site search" sub="Visits that used the store's search box">
      <div className="cro-four">
        <div className="cro-mini"><span className="k">Visits that searched</span><span className="v num">{pct(s.share_of_sessions, 1)}</span><span className="s">{fmtInt(s.sessions_with_searches)} visits</span></div>
        <div className="cro-mini"><span className="k">Conversion: searchers vs others</span><span className="v num">{pct(s.searcher_conversion_rate)} <span className="muted" style={{ fontSize: 14 }}>vs {pct(s.non_searcher_conversion_rate)}</span></span>
          <span className="s">{s.non_searcher_conversion_rate ? `searchers buy ${(s.searcher_conversion_rate / s.non_searcher_conversion_rate).toFixed(1)} times as often` : ''}</span></div>
        <div className="cro-mini"><span className="k">Searchers who clicked a result</span><span className="v num">{pct(s.search_click_rate, 1)}</span><span className="s">{pct(s.search_added_to_cart_rate, 1)} added to cart</span></div>
        <div className={`cro-mini${(s.zero_result_share ?? 0) >= 10 ? ' bad' : ''}`}><span className="k">Searches with no results</span><span className="v num">{pct(s.zero_result_share, 1)}</span><span className="s">{fmtInt(s.zero_result_searches ?? 0)} of {fmtInt(s.searches ?? 0)} searches</span></div>
      </div>
      <div className="grid cols-2 mt-16">
        <div><div className="cro-cap">Top search terms</div><div className="table-wrap"><table className="t compact"><thead><tr><th>Term</th><th className="r">Searches</th><th className="r">Clicked a result</th></tr></thead>
          <tbody>{s.top_terms.slice(0, 10).map((t) => <tr key={t.term}><td>{t.term}</td><td className="r">{fmtInt(t.searches)}</td><td className="r">{pct(t.click_rate, 1)}</td></tr>)}</tbody></table></div></div>
        <div><div className="cro-cap">Searches that found nothing · fix these first</div>
          {s.zero_result_terms.length ? (<div className="table-wrap"><table className="t compact"><thead><tr><th>Term</th><th className="r">Searches</th></tr></thead>
            <tbody>{s.zero_result_terms.slice(0, 10).map((t) => <tr key={t.term}><td className="down strong">{t.term}</td><td className="r">{fmtInt(t.searches)}</td></tr>)}</tbody></table></div>) : <div className="muted small">Every search found something.</div>}
          {s.zero_result_terms.length ? <div className="muted xs mt-8">Add these words to product titles or tags, or set up a search redirect.</div> : null}</div>
      </div>
    </Card>);
}

/* ------------------------------------------------------------------ Cart & checkout */
/**
 * Cart & checkout (approved design 2026-11-21 plus the owner's four improvements): checkout health and the device and
 * channel splits as before; the abandonment trend with a tooltip per day, change-log markers and the earlier days
 * dashed; payments as share bars with a success chip each; order values (with a free-shipping line) and items per
 * order side by side.
 */
function CheckoutTab({ rq }) {
    const tr = trendRange(rq);
    const q = useApi(`/cro/conversion${qs(tr)}`);
    const bench = useApi('/cro/benchmarks');
    const b = bench.data?.benchmarks;
    return (<div className="col" style={{ gap: 16 }}>
      <div className="cro-sec">Checkout health</div>
      <CroGate query={q}>{(d) => <CheckoutHealth d={d} b={b} rq={rq}/>}</CroGate>
      <div className="grid cols-2">
        <SegmentCard rq={rq} dimension="device" title="By device"/>
        <SegmentCard rq={rq} dimension="channel" title="By channel"/>
      </div>
      <div className="cro-sec">Abandonment</div>
      <AbandonmentCard rq={rq} b={b}/>
      <CheckoutExtras rq={rq}/>
    </div>);
}

/** Cart and checkout abandonment by day for the last 7, 14 or 30 complete days of the range, the days before dashed. */
function AbandonmentCard({ rq, b }) {
    const [span, setSpan] = useState(14);
    const q = useApi(`/cro/conversion${qs({ brand: rq.brand, from: shiftDay(rq.to, -(span - 1)), to: rq.to, compare: 'previous' })}`);
    const log = useApi(`/cro/change-log${qs({ brand: rq.brand, days: 90 })}`);
    return (<Card title="Abandonment rate trend" sub={b ? `Typical store: carts ${b.cart_abandonment_rate.value}%, checkouts ${b.checkout_abandonment_rate.value}% (${b.cart_abandonment_rate.source})` : 'Carts and checkouts that did not end in a purchase'}
      actions={<Seg label="Days" options={[{ key: 7, label: '7 days' }, { key: 14, label: '14 days' }, { key: 30, label: '30 days' }]} value={span} onChange={setSpan}/>}>
      <CroGate query={q} rows={4}>
        {(d) => {
            const t = d.total, base = d.baseline_total;
            const panel = (label, key) => (<div className="cro-panel"><div className="muted small strong">{label} · {d.trend.length} days</div>
              <div className="row" style={{ gap: 8 }}><span className="num" style={{ fontSize: 20, fontWeight: 700 }}>{pct(t[key], 1)}</span>
                <ChangeChip v={base && t[key] !== null && base[key] !== null ? t[key] - base[key] : null} goodWhenUp={false}/>
                {base ? <span className="muted small">vs {pct(base[key], 1)} before</span> : null}</div></div>);
            if (!d.trend.length) return <div className="muted small">No complete day in this range.</div>;
            return (<>
              <div className="grid cols-2" style={{ marginBottom: 12 }}>{panel('Cart abandonment', 'cart_abandonment_rate')}{panel('Checkout abandonment', 'checkout_abandonment_rate')}</div>
              <AbandonChart cur={d.trend} prev={d.baseline_trend ?? []} changes={log.data?.entries ?? []}/>
            </>);
        }}
      </CroGate>
    </Card>);
}

/** Two abandonment lines (cart amber, checkout umber) over a light area, the days before dashed, change-log days marked;
 * pointing at a day shows its figures. Drawn at 1:1 in a fixed 1000-wide box that scales with the card. */
function AbandonChart({ cur, prev, changes }) {
    const [hover, setHover] = useState(null);
    const W = 1000, H = 250, L = 52, R = 12, T = 16, B = 32;
    const n = cur.length;
    const x = (i) => (n === 1 ? (L + W - R) / 2 : L + (i * (W - L - R)) / (n - 1));
    const vals = [...cur, ...prev].flatMap((r) => [r.cart_abandonment_rate, r.checkout_abandonment_rate]).filter((v) => v !== null && v !== undefined);
    const top = Math.min(100, Math.ceil((Math.max(60, ...vals) + 5) / 10) * 10);
    const y = (v) => T + (1 - v / top) * (H - T - B);
    const line = (rows, key) => rows.map((r, i) => (r[key] === null || r[key] === undefined ? null : `${x(i).toFixed(1)},${y(r[key]).toFixed(1)}`)).filter(Boolean).map((p, i) => `${i ? 'L' : 'M'}${p}`).join(' ');
    const area = (key) => { const l = line(cur, key); return l ? `${l} L${x(n - 1).toFixed(1)},${H - B} L${x(0).toFixed(1)},${H - B} Z` : ''; };
    const byDay = new Map();
    for (const c of changes) if (!byDay.has(c.entry_date)) byDay.set(c.entry_date, c);
    const marks = cur.map((r, i) => ({ i, c: byDay.get(r.date) })).filter((m) => m.c);
    const h = hover !== null ? cur[hover] : null;
    const ph = hover !== null ? prev[hover] : null;
    const onMove = (e) => {
        const box = e.currentTarget.getBoundingClientRect();
        const fx = ((e.clientX - box.left) / box.width) * W;
        setHover(Math.max(0, Math.min(n - 1, Math.round(((fx - L) / (W - L - R)) * (n - 1)))));
    };
    return (<div className="cro-abn">
      <div className="legend" style={{ marginBottom: 6 }}><span className="legend-item"><span className="legend-swatch" style={{ background: 'var(--saffron)' }}/>Cart abandonment</span>
        <span className="legend-item"><span className="legend-swatch" style={{ background: 'var(--cpc)' }}/>Checkout abandonment</span>
        <span className="legend-item"><span className="legend-swatch dashed" style={{ color: 'var(--faint)' }}/>Days before (dashed)</span>
        {marks.length ? <span className="legend-item"><span className="lane-chip lane-event">◆</span>Change log</span> : null}</div>
      <div className="cro-abn-box" onMouseMove={onMove} onMouseLeave={() => setHover(null)}>
        <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Cart abandonment ${pct(cur[n - 1]?.cart_abandonment_rate, 0)} and checkout abandonment ${pct(cur[n - 1]?.checkout_abandonment_rate, 0)} on the last day`}>
          {[0, 0.25, 0.5, 0.75, 1].map((f) => <g key={f}><line x1={L} x2={W - R} y1={y(top * f)} y2={y(top * f)} className="grid-line"/><text x={0} y={y(top * f) + 5} className="axis-text">{Math.round(top * f)}%</text></g>)}
          <path d={area('cart_abandonment_rate')} style={{ fill: 'var(--saffron)', opacity: 0.07 }}/>
          <path d={line(prev, 'cart_abandonment_rate')} style={{ fill: 'none', stroke: 'var(--saffron)', strokeWidth: 2, strokeDasharray: '6 5', opacity: 0.55 }}/>
          <path d={line(prev, 'checkout_abandonment_rate')} style={{ fill: 'none', stroke: 'var(--cpc)', strokeWidth: 2, strokeDasharray: '6 5', opacity: 0.55 }}/>
          <path d={line(cur, 'cart_abandonment_rate')} style={{ fill: 'none', stroke: 'var(--saffron)', strokeWidth: 2.6 }}/>
          <path d={line(cur, 'checkout_abandonment_rate')} style={{ fill: 'none', stroke: 'var(--cpc)', strokeWidth: 2.6 }}/>
          {marks.map((m) => <g key={m.i}><line x1={x(m.i)} x2={x(m.i)} y1={T} y2={H - B} style={{ stroke: 'var(--saffron)', strokeDasharray: '2 4' }}/><path d={`M${x(m.i)},${T - 2} l5,5 l-5,5 l-5,-5 z`} style={{ fill: 'var(--saffron)' }}><title>{`${fmtDate(m.c.entry_date)}: ${m.c.change}`}</title></path></g>)}
          {hover !== null ? <line x1={x(hover)} x2={x(hover)} y1={T} y2={H - B} style={{ stroke: 'var(--ink)', strokeDasharray: '3 3' }}/> : null}
          {cur.map((r, i) => (i % Math.ceil(n / 8) === 0 || i === n - 1 ? <text key={r.date} x={x(i)} y={H - 8} textAnchor="middle" className="axis-text">{fmtDay(r.date)}</text> : null))}
        </svg>
        {h ? (<div className="cro-tip" style={{ left: `${(x(hover) / W) * 100}%`, transform: hover > n / 2 ? 'translateX(calc(-100% - 12px))' : 'translateX(12px)' }}>
          <b>{fmtDate(h.date)}</b>
          <div>Cart <b>{pct(h.cart_abandonment_rate, 1)}</b> <span className="muted">{ph ? `(${pct(ph.cart_abandonment_rate, 1)} on ${fmtDay(ph.date)})` : ''}</span></div>
          <div>Checkout <b>{pct(h.checkout_abandonment_rate, 1)}</b> <span className="muted">{ph ? `(${pct(ph.checkout_abandonment_rate, 1)})` : ''}</span></div>
          {byDay.get(h.date) ? <div className="lane-chip lane-event" style={{ marginTop: 4, whiteSpace: 'normal' }}>{byDay.get(h.date).change}</div> : null}
        </div>) : null}
      </div>
    </div>);
}

function CheckoutExtras({ rq }) {
    const q = useApi(`/cro/checkout-extras${qs(rq)}`);
    return (<CroGate query={q}>
      {(d) => (<>
        <div className="row" style={{ justifyContent: 'space-between', alignItems: 'flex-end' }}>
          <div className="cro-sec" style={{ margin: 0 }}>Payments, order values and basket size</div>
          <WindowNote w={d.window} to={d.to}/>
        </div>
        <PaymentsCard p={d.payments} error={d.payments_error}/>
        <div className="grid cols-2">
          <OrderValuesCard v={d.order_values} prev={d.previous_order_values} brand={rq.brand} onSaved={q.reload}/>
          <ItemsCard v={d.order_values} prev={d.previous_order_values}/>
        </div>
      </>)}
    </CroGate>);
}

function PaymentsCard({ p, error }) {
    if (!p) return (<Card title="Payment methods and failed payments">{error ? <ExplainedError error={{ code: error.state, message: error.message }}/> : <div className="muted small">No payment figures.</div>}</Card>);
    const top = p.methods[0];
    return (<Card title="Payment methods and failed payments" sub="Success = payments that went through ÷ purchase attempts (a retry of the same purchase counts once)">
      <div className="cro-three">
        <div className="cro-mini"><span className="k">Payment success rate</span><div className="row" style={{ gap: 8 }}><span className="v num">{pct(p.success_rate, 1)}</span>
          <ChangeChip v={p.previous_success_rate !== null && p.success_rate !== null ? p.success_rate - p.previous_success_rate : null}/></div>
          <span className="s">{fmtInt(p.successful)} of {fmtInt(p.attempts)} purchase attempts</span></div>
        <div className="cro-mini"><span className="k">Failed payment attempts</span><div className="row" style={{ gap: 8 }}><span className="v num">{fmtInt(p.failed_attempts)}</span>
          <ChangeChip v={pctChange(p.failed_attempts, p.previous_failed_attempts)} unit="%" goodWhenUp={false}/></div><span className="s">includes retries of the same purchase</span></div>
        <div className="cro-mini"><span className="k">Most used method</span><div className="row" style={{ gap: 8 }}><span className="v" style={{ fontSize: 20 }}>{top ? readable(top.label) : '—'}</span>
          {top ? <span className="lane-chip plain">{pct(top.share_of_payments, 0)}</span> : null}</div><span className="s">{p.wallets[0] ? `${readable(p.wallets[0].label)} is the top wallet (${pct(p.wallets[0].share_of_payments, 0)})` : ''}</span></div>
      </div>
      {p.attempts ? (<div className="grid cols-2 mt-16">
        <PayBars title="Method" rows={p.methods} prev={p.previous_methods} overall={p.success_rate}/>
        <PayBars title="Wallet (Shop Pay, Apple Pay…)" rows={p.wallets} prev={p.previous_wallets} overall={p.success_rate}/>
      </div>) : <div className="muted small mt-8">Shopify has no payment attempts for these days{p.latest_day_with_data ? ` (latest: ${fmtDate(p.latest_day_with_data)})` : ''}.</div>}
    </Card>);
}

/** Payment methods as share bars; each with its success chip (green near the store's rate, amber a little below, red
 * 5+ points below) and its attempts, failures and change in share. */
function PayBars({ title, rows, prev, overall }) {
    const before = new Map((prev ?? []).map((r) => [r.label, r]));
    if (!rows.length) return <div><div className="cro-cap">{title}</div><div className="muted small">No split for these days.</div></div>;
    return (<div><div className="cro-cap">{title}</div>
      <div className="cro-pays">{rows.slice(0, 6).map((r) => {
          const b = before.get(r.label);
          const lane = r.success_rate === null ? 'plain' : r.success_rate >= overall - 1 ? 'lane-live' : r.success_rate >= overall - 5 ? 'lane-event' : 'lane-due';
          return (<div key={r.label} className="cro-pay">
            <div className="lr"><b>{readable(r.label)}</b><span className="row" style={{ gap: 6 }}><span className="num">{pct(r.share_of_payments, 1)}</span><span className={`lane-chip ${lane}`}>{pct(r.success_rate, 1)} ok</span></span></div>
            <div className="bar"><span style={{ width: `${r.share_of_payments ?? 0}%` }}/></div>
            <div className="muted xs">{fmtInt(r.attempts)} attempts · {fmtInt(r.failed_attempts)} failed{b && b.share_of_payments !== null ? ` · share ${signedPts(r.share_of_payments - b.share_of_payments)}` : ''}</div>
          </div>);
      })}</div></div>);
}

/** Order values in $25 bars with a line at the store's free-shipping amount (saved in CRO settings for everyone);
 * bars just under it are amber. Pointing at a bar shows its orders. */
function OrderValuesCard({ v, prev, brand, onSaved }) {
    const toast = useToast();
    const [amount, setAmount] = useState(v.threshold ? String(v.threshold) : '');
    const [saving, setSaving] = useState(false);
    const [hover, setHover] = useState(null);
    const save = async () => {
        setSaving(true);
        try { await api.patch(`/cro/settings${qs({ brand })}`, { free_shipping_threshold: amount === '' ? null : Number(amount) }); toast.ok(amount ? 'Free-shipping amount saved for this store.' : 'Free-shipping amount cleared.'); onSaved(); }
        catch (e) { toast.error(e); }
        finally { setSaving(false); }
    };
    const max = Math.max(1, ...v.bars.map((b) => b.orders));
    const step = v.bars.length > 1 ? v.bars[1].from - v.bars[0].from : 25;
    const lineAt = v.threshold ? Math.min(1, v.threshold / (step * v.bars.length)) : null;
    const h = hover !== null ? v.bars[hover] : null;
    return (<Card title="Order values and free shipping" sub="Order value = subtotal after discounts, before shipping and tax"
      actions={<label className="row small" style={{ gap: 6 }}>Free shipping from<input className="input sm" inputMode="decimal" style={{ width: 90 }} placeholder="e.g. 100" value={amount}
        onChange={(e) => setAmount(e.target.value.replace(/[^0-9.]/g, ''))} aria-label="Free shipping from (store currency)"/><Button size="sm" loading={saving} onClick={save}>Save</Button></label>}>
      <div className="cro-stats">
        <Stat k="Average / median order" s={`${fmtInt(v.orders)} orders`} v={v.average === null ? '—' : `${money(v.average, 'USD', 0)} / ${money(v.median, 'USD', 0)}`} chip={<ChangeChip v={pctChange(v.average, prev?.average)} unit="%"/>}/>
        <Stat k="Just below free shipping" warm={!!v.threshold} v={v.threshold ? pct(v.near_threshold_share, 1) : '—'}
          s={v.threshold ? `${fmtInt(v.near_threshold_orders)} orders from ${money(v.near_threshold_from, 'USD', 0)} to just under ${money(v.threshold, 'USD', 0)}` : 'Enter the free-shipping amount above'}
          chip={v.threshold ? <ChangeChip v={prev?.near_threshold_share !== null && prev?.near_threshold_share !== undefined ? v.near_threshold_share - prev.near_threshold_share : null} goodWhenUp={false}/> : null}/>
        <Stat k="Orders that qualified" v={v.threshold ? pct(v.at_or_above_threshold_share, 1) : '—'} s={v.threshold ? `orders of ${money(v.threshold, 'USD', 0)} or more` : ''}
          chip={v.threshold ? <ChangeChip v={prev?.at_or_above_threshold_share !== null && prev?.at_or_above_threshold_share !== undefined ? v.at_or_above_threshold_share - prev.at_or_above_threshold_share : null}/> : null}/>
      </div>
      <div className="cro-hist" role="img" aria-label="Orders by order value in $25 bands" onMouseLeave={() => setHover(null)}>
        {v.bars.map((b, i) => (<div key={b.label} className={`hb${b.near_threshold ? ' near' : ''}${hover === i ? ' on' : ''}`} onMouseEnter={() => setHover(i)}>
          <i style={{ height: `${(b.orders / max) * 100}%` }}/></div>))}
        {lineAt !== null ? <span className="cro-fs" style={{ left: `${lineAt * 100}%` }}><em>Free shipping {money(v.threshold, 'USD', 0)}</em></span> : null}
        {h ? <div className="cro-tip" style={{ left: `${((hover + 0.5) / v.bars.length) * 100}%`, top: 0, transform: hover > v.bars.length / 2 ? 'translateX(calc(-100% - 8px))' : 'translateX(8px)' }}><b>{h.label}</b><div>{fmtInt(h.orders)} orders ({pct(h.share, 1)})</div></div> : null}
      </div>
      <div className="cro-hist-l">{v.bars.map((b, i) => <span key={b.label}>{i % 2 && i !== v.bars.length - 1 ? '' : b.label.replace(/-\d+$/, '')}</span>)}</div>
    </Card>);
}

/** One figure as a compact row: label (and a note) on the left, value and change chip on the right. */
function Stat({ k, v, s: note, chip, warm }) {
    return (<div className={`cro-stat${warm ? ' warm' : ''}`}><div style={{ minWidth: 0 }}><div className="k">{k}</div>{note ? <div className="s">{note}</div> : null}</div>
      <div className="vv"><span className="v num">{v}</span>{chip}</div></div>);
}

function ItemsCard({ v, prev }) {
    const it = v.items;
    const max = Math.max(1, ...it.bars.map((b) => b.share));
    return (<Card title="Items per order" sub="Pieces in each order, cancelled orders left out">
      <div className="cro-stats">
        <Stat k="Average items per order" v={it.average ?? '—'} chip={<ChangeChip v={pctChange(it.average, prev?.items?.average)} unit="%"/>}/>
        <Stat k="Single-item orders" v={pct(it.single_item_share, 1)}
          chip={<ChangeChip v={prev?.items?.single_item_share !== null && prev?.items?.single_item_share !== undefined ? it.single_item_share - prev.items.single_item_share : null} goodWhenUp={false}/>}/>
      </div>
      <div className="cro-ibars" role="img" aria-label={it.bars.map((b) => `${b.share}% of orders have ${b.label} item${b.label === '1' ? '' : 's'}`).join(', ')}>
        {it.bars.map((b) => <div key={b.label}><span>{pct(b.share, 0)}</span><i style={{ height: `${(b.share / max) * 85}%` }}/><em>{b.label}</em></div>)}
      </div>
      <div className="muted xs" style={{ textAlign: 'center' }}>items in the order</div>
    </Card>);
}

/* ------------------------------------------------------------------ Products */
/**
 * Products (approved design 2026-11-21, batch 4). Money and orders from Shopify, product views and add-to-carts from
 * GA4 (matched by product id): the four product groups (each product against its own category; clicking one filters
 * the table), the leaky pages to fix first, refunds per product, price bands, products bought together, and every
 * product with its figures. When GA4 has too few days the groups wait and say so; the rest still shows.
 */
const GROUP_META = {
    star: { label: 'Stars', act: 'Keep in stock, use in ads', cls: 'star', lane: 'lane-live' },
    hidden_gem: { label: 'Hidden gems', act: 'Send more traffic', cls: 'gem', lane: 'lane-research' },
    leaky: { label: 'Leaky', act: 'Fix the product page first', cls: 'leaky', lane: 'lane-event' },
    dead_weight: { label: 'Dead weight', act: 'Rework or drop', cls: 'dead', lane: 'plain' },
};

function ProductsTab({ rq }) {
    const q = useApi(`/cro/product-insights${qs(rq)}`);
    const [group, setGroup] = useState(null);
    return (<CroGate query={q}>
      {(d) => (d.products.length ? (<>
        <ProductSources d={d}/>
        <GroupsCard d={d} group={group} onGroup={setGroup}/>
        {d.groups?.fix_first.length ? <FixFirstCard g={d.groups}/> : null}
        <div className="cro-two-wide">
          <RefundsCard r={d.refunds} error={d.sales_error}/>
          <PriceBandsCard bands={d.price_bands} withViews={!!d.groups}/>
        </div>
        <BoughtTogetherCard b={d.bought_together}/>
        <ProductTable d={d} group={group} onGroup={setGroup} resetKey={`${rq.from}-${rq.to}`}/>
      </>) : <CroEmpty title="No products sold or viewed in these days"/>)}
    </CroGate>);
}

/** Which days, and where each kind of figure comes from. */
function ProductSources({ d }) {
    const v = d.views;
    const views = d.views_source !== 'ga4' ? 'Views: GA4 not available'
        : v.state === 'ready' ? `Views and add-to-carts: GA4 · ${v.days} of ${v.window_days} days` : `Views: GA4 · ${v.days} of ${v.window_days} days so far`;
    return (<div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
      <span className="cro-ctx"><b>Showing: {fmtDate(d.window.from)} – {fmtDate(d.window.to)}</b><span className="muted"> · complete days</span></span>
      <span className="lane-chip plain">{d.sales_source === 'shopify' ? 'Sales, orders, refunds: Shopify' : 'Sales: the order copy (Shopify’s report did not answer)'}</span>
      <span className={`lane-chip ${v.state === 'ready' ? 'lane-research' : 'plain'}`}>{views}</span>
    </div>);
}

function GroupsCard({ d, group, onGroup }) {
    const g = d.groups;
    const seen = d.products.filter((p) => p.views).length;
    if (!g) {
        const v = d.views;
        return (<Card title="Product groups" sub="Stars, Hidden gems, Leaky and Dead weight, each product against its own category">
          {v.state === 'not_configured' || v.state === 'ga4_error'
              ? <ExplainedError error={{ code: v.state, message: v.message }}/>
              : <div className="callout info"><Icon name="clock"/><div><b>Waiting for GA4 product views.</b> {v.message} Sales, refunds, price bands and products bought together below are complete.</div></div>}
        </Card>);
    }
    return (<Card title="Product groups" sub="Each product against its own category (quilts with quilts). Click a group to filter the table below."
      actions={<span className="muted small num">{fmtInt(seen)} products with views</span>}>
      <div className="cro-quad">
        <div className="ay" aria-hidden="true"><span>Below its category</span><span>At or above its category</span></div>
        {g.groups.map((x) => {
            const m = GROUP_META[x.group];
            const on = group === x.group;
            return (<button key={x.group} type="button" className={`cro-gt ${m.cls}${on ? ' on' : ''}`} aria-pressed={on} onClick={() => onGroup(on ? null : x.group)}>
              <span className="hd"><b>{m.label}</b><span>{m.act}</span></span>
              <span className="gv num"><span><b>{fmtInt(x.products)}</b> products</span><span><b>{fmtInt(x.views)}</b> views</span><span><b>{money(x.net_sales, 'USD', 0)}</b> net sales</span></span>
              <span className="gx">{x.top.join(' · ') || 'No products'}</span>
            </button>);
        })}
        <span/><div className="ax" aria-hidden="true"><span>Many views</span><span>Few views</span></div>
      </div>
      <div className="muted xs mt-8">Adjusted for low traffic: (orders + 200 × category rate) ÷ (views + 200). Many views = at or above the category&rsquo;s median. A category with fewer than 3 viewed products is compared with all products. {d.views.message}</div>
    </Card>);
}

function FixFirstCard({ g }) {
    return (<Card title="Fix first: leaky product pages" sub="Many views, converting below their category. Left on the table = views × conversion gap × price." flush
      actions={<div style={{ textAlign: 'right' }}><div className="num" style={{ fontSize: 22, fontWeight: 700 }}>{money(g.left_on_table, 'USD', 0)}</div><div className="muted xs">left on the table, top {g.fix_first.length}</div></div>}>
      <div className="table-wrap"><table className="t compact">
        <thead><tr><th>Product</th><th className="r">Views</th><th className="r hide-sm">Add to cart</th><th>Conversion vs category</th><th className="r hide-sm">Price</th><th className="r">Left on the table</th></tr></thead>
        <tbody>{g.fix_first.map((f) => {
            const top = Math.max(f.conversion_rate ?? 0, f.category_rate ?? 0) * 1.15 || 1;
            return (<tr key={f.product_id}>
              <td style={{ maxWidth: 300 }}><div className="ellipsis strong" title={f.name}>{f.name}</div><span className="muted xs">{f.compared_with === 'All products' ? `${f.category} · against all products` : f.category}</span></td>
              <td className="r">{fmtInt(f.views)}</td><td className="r hide-sm">{pct(f.add_to_cart_rate, 1)}</td>
              <td><div className="cro-cvs"><span className="cvb" role="img" aria-label={`${pct(f.conversion_rate)} against ${pct(f.category_rate)}`}>
                <i style={{ width: `${((f.conversion_rate ?? 0) / top) * 100}%` }}/><b style={{ left: `${((f.category_rate ?? 0) / top) * 100}%` }}/></span>
                <span className="num">{pct(f.conversion_rate)} <span className="muted">vs {pct(f.category_rate)}</span></span></div></td>
              <td className="r hide-sm">{money(f.price)}</td><td className="r"><b>{money(f.left_on_table, 'USD', 0)}</b></td>
            </tr>);
        })}</tbody>
      </table></div>
      <div className="pad-x muted xs" style={{ paddingBottom: 12 }}>Bar: the product&rsquo;s conversion; black mark: its category. The top five also appear in Recommendations, ranked by the same money figure.</div>
    </Card>);
}

const REFUND_SORT = [{ key: 'by_rate', label: 'Highest rate' }, { key: 'by_amount', label: 'Most refunded' }];
function RefundsCard({ r, error }) {
    const [sort, setSort] = useState('by_rate');
    if (!r) return (<Card title="Refunds per product"><div className="muted small">Shopify&rsquo;s sales report did not answer, so refunds per product cannot be shown{error ? `: ${error}` : '.'}</div></Card>);
    const rows = r[sort];
    return (<Card title="Refunds per product" sub="Refunded in these days, as a share of the product's gross sales">
      <div className="cro-three tight">
        <div className="cro-mini"><span className="k">Refund rate</span><span className="v num">{pct(r.store_refund_rate, 1)}</span><span className="s">of gross sales</span></div>
        <div className="cro-mini"><span className="k">Refunded</span><span className="v num">{money(r.total_refunded, 'USD', 0)}</span><span className="s">{fmtInt(r.products_with_refunds)} products</span></div>
        <div className="cro-mini"><span className="k">Not tied to a product</span><span className="v num">{money(r.refunded_without_product, 'USD', 0)}</span><span className="s">shipping, custom items</span></div>
      </div>
      <Seg label="Sort refunds" options={REFUND_SORT} value={sort} onChange={setSort}/>
      {rows.length ? (<div className="table-wrap mt-8"><table className="t compact">
        <thead><tr><th>Product</th><th className="r hide-sm">Gross sales</th><th className="r">Refunded</th><th className="r">Rate</th></tr></thead>
        <tbody>{rows.slice(0, 8).map((x) => (<tr key={x.product_id ?? x.name}>
          <td style={{ maxWidth: 240 }}><div className="ellipsis strong" title={x.name}>{x.name}</div><span className="muted xs">{x.category}</span></td>
          <td className="r hide-sm">{money(x.gross_sales, 'USD', 0)}</td><td className="r">{money(x.refunded, 'USD', 0)}</td>
          <td className="r"><span className={`lane-chip ${x.refund_rate >= 15 ? 'lane-due' : x.refund_rate >= 7 ? 'lane-event' : 'plain'}`}>{pct(x.refund_rate, 1)}</span></td>
        </tr>))}</tbody>
      </table></div>) : <div className="muted small mt-8">No product with ${fmtInt(r.min_gross_sales)}+ of gross sales had a refund.</div>}
      <div className="muted xs mt-8">Products with less than {money(r.min_gross_sales, 'USD', 0)} of gross sales are left out. Shopify counts a refund on the day it is made.</div>
    </Card>);
}

function PriceBandsCard({ bands, withViews }) {
    const top = Math.max(...bands.map((b) => b.share_of_sales ?? 0), 1);
    return (<Card title="Price bands" sub={'Products by their "from" price · bar = share of net sales'}>
      {bands.length ? (<>
        <div className="cro-band hd"><span>Band</span><span>Share of sales</span><span className="r">Products</span><span className="r">Orders</span>{withViews ? <span className="r">Conversion</span> : null}</div>
        {bands.map((b) => (<div key={b.band} className={`cro-band num${withViews ? '' : ' nov'}`}>
          <b>{b.band}</b>
          <span className="bar"><i style={{ width: `${Math.max(1, ((b.share_of_sales ?? 0) / top) * 100)}%` }}/><em className={(b.share_of_sales ?? 0) / top < 0.25 ? 'out' : ''}>{pct(b.share_of_sales, 1)}</em></span>
          <span className="r">{fmtInt(b.products)}</span><span className="r">{fmtInt(b.orders)}</span>{withViews ? <span className="r">{b.views >= 100 ? pct(b.conversion_rate) : '—'}</span> : null}
        </div>))}
        <div className="muted xs mt-8">An order counts once in each band it has a product from.{withViews ? ' Conversion = orders ÷ product views (GA4) in the band; under 100 views is not shown.' : ' Conversion per band shows once GA4 has enough days of views.'}</div>
      </>) : <div className="muted small">No product prices for these days.</div>}
    </Card>);
}

function BoughtTogetherCard({ b }) {
    const max = Math.max(...b.rows.map((x) => x.pct_of_a ?? 0), 1);
    return (<Card title="Bought together" sub="Pairs of products in the same order · cancelled orders left out · pairs seen only once left out" flush
      actions={<div style={{ textAlign: 'right' }}><div className="num" style={{ fontSize: 22, fontWeight: 700 }}>{pct(b.multi_share, 1)}</div><div className="muted xs">of orders had 2+ products ({fmtInt(b.multi_product_orders)} of {fmtInt(b.orders)})</div></div>}>
      {b.rows.length ? (<div className="table-wrap"><table className="t compact">
        <thead><tr><th>Product</th><th>Also in the order</th><th className="r">Orders together</th><th className="r">Share of the first product&rsquo;s orders</th><th className="r hide-sm">vs chance</th></tr></thead>
        <tbody>{b.rows.map((x) => (<tr key={`${x.a}|${x.b}`}>
          <td style={{ maxWidth: 260 }}><div className="ellipsis strong" title={x.a}>{x.a}</div></td><td style={{ maxWidth: 260 }}><div className="ellipsis" title={x.b}>{x.b}</div></td>
          <td className="r">{fmtInt(x.orders_together)}</td>
          <td className="r"><span className="cro-share"><i style={{ width: `${((x.pct_of_a ?? 0) / max) * 70}px` }}/><span className="num">{pct(x.pct_of_a, 1)}</span></span></td>
          <td className="r hide-sm">{x.lift ? <span className="lane-chip lane-research">×{x.lift}</span> : '—'}</td>
        </tr>))}</tbody>
      </table></div>) : <div className="pad-x muted small" style={{ paddingBottom: 12 }}>No two products were bought together more than once in these days.</div>}
      <div className="pad-x muted xs" style={{ paddingBottom: 12 }}>&ldquo;vs chance&rdquo;: how many times more often the two are bought together than if buyers picked them independently.</div>
    </Card>);
}

function ProductTable({ d, group, onGroup, resetKey }) {
    const [search, setSearch] = useState('');
    const s = search.trim().toLowerCase();
    const views = d.views_source === 'ga4';
    const rows = d.products.filter((p) => (!group || p.group === group) && (!s || p.name.toLowerCase().includes(s)));
    return (<Card title="All products" sub={`Net sales, items and orders from ${d.sales_source === 'shopify' ? 'Shopify' : 'the order copy'}${views ? '; views and add to cart from GA4' : ''}`} flush
      actions={<div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
        <label className="cro-search"><Icon name="search" size="sm"/><input className="input sm" placeholder="Search products" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Search products"/></label>
        {d.groups ? <select className="input sm" value={group ?? ''} onChange={(e) => onGroup(e.target.value || null)} aria-label="Group"><option value="">All groups</option>{Object.entries(GROUP_META).map(([k, m]) => <option key={k} value={k}>{m.label}</option>)}</select> : null}
      </div>}>
      {rows.length ? (<Paged rows={rows} resetKey={`${resetKey}-${group}-${s}`}>
        {(page) => (<div className="table-wrap"><table className="t compact">
          <thead><tr><th>Product</th><th className="hide-sm">Category</th><th className="r">Orders</th><th className="r">Net sales</th><th className="r hide-sm">Refund</th>
            {views ? <><th className="r">Views</th><th className="r hide-sm">Add to cart</th><th className="r">Conversion</th></> : null}{d.groups ? <th>Group</th> : null}</tr></thead>
          <tbody>{page.map((p) => (<tr key={p.product_id ?? `t-${p.name}`}>
            <td style={{ maxWidth: 300 }}><div className="ellipsis strong" title={p.name}>{p.name}</div></td><td className="hide-sm muted">{p.category}</td>
            <td className="r">{fmtInt(p.orders)}</td><td className="r"><b>{money(p.net_sales, 'USD', 0)}</b></td><td className="r hide-sm">{p.refund_rate === null ? '—' : pct(p.refund_rate, 1)}</td>
            {views ? <><td className="r">{p.views === null ? '—' : fmtInt(p.views)}</td><td className="r hide-sm">{p.add_to_cart_rate === null ? '—' : pct(p.add_to_cart_rate, 1)}</td>
              <td className="r">{p.conversion_rate === null ? '—' : pct(p.conversion_rate)}</td></> : null}
            {d.groups ? <td>{p.group ? <span className={`lane-chip ${GROUP_META[p.group].lane}`}>{GROUP_META[p.group].label}</span> : <span className="muted xs">no views</span>}</td> : null}
          </tr>))}</tbody>
        </table></div>)}
      </Paged>) : <div className="pad-x muted small" style={{ paddingBottom: 12 }}>No products match.</div>}
      {group ? <div className="pad-x" style={{ paddingBottom: 10 }}><button type="button" className="link-btn" onClick={() => onGroup(null)}>Show all groups</button></div> : null}
    </Card>);
}

/* ------------------------------------------------------------------ Sales */
function SalesTab({ rq }) {
    const q = useApi(`/cro/sales-breakdown${qs(rq)}`);
    const health = useApi(`/cro/order-health${qs(rq)}`);
    return (<><div className="grid cols-2">
      <Card title="Total sales breakdown" flush>
        <CroGate query={q}>
          {(d) => (<>
            <div className="table-wrap"><table className="t compact">
              <thead><tr><th>{d.period_label}</th><th className="r">Amount</th><th className="r">Comparison</th><th className="r">Change</th></tr></thead>
              <tbody>{d.rows.map((r) => (<tr key={r.key}><td>{r.key === 'total' ? <b>{r.label}</b> : r.label}</td><td className="r">{r.key === 'total' ? <b>{money(r.value)}</b> : money(r.value)}</td>
                <td className="r muted">{money(r.baseline_value)}</td><td className="r">{r.too_early ? <span className="muted">too early</span> : signedPct(r.change_pct)}</td></tr>))}</tbody>
            </table></div>
            <div className="muted xs" style={{ padding: '8px 16px 12px' }}>{d.baseline_label}. {d.note}</div>
          </>)}
        </CroGate>
      </Card>
      <Card title="Order health" sub="A rising refund or cancellation rate often points to checkout, payment or trust problems.">
        <CroGate query={health} rows={3}>
          {(h) => (<>
            <div className="muted small">{h.period_label}</div>
            <RingBody total={h.total_orders} centerLabel="orders" compact segments={[
                { key: 'paid', name: 'Paid', value: h.paid.count, color: 'var(--ok)' },
                { key: 'refunded', name: 'Refunded', value: h.refunded.count, color: 'var(--warn)' },
                { key: 'cancelled', name: 'Cancelled', value: h.cancelled.count, color: 'var(--crit)' },
                { key: 'pending', name: 'Other (pending…)', value: h.pending.count, color: 'var(--info)' },
            ]}/>
          </>)}
        </CroGate>
      </Card>
    </div>
    <DiscountCodesCard rq={rq}/>
    <CustomersCards rq={rq}/></>);
}

/** Discount codes (approved design 2026-11-21, batch 4): orders with vs without a code, against the comparison, and
 * the top codes. From Shopify's sales report; an order with two codes is under both codes. */
const CODE_SORT = [{ key: 'orders', label: 'Most orders' }, { key: 'aov', label: 'Highest average order' }];
function DiscountCodesCard({ rq }) {
    const q = useApi(`/cro/discount-codes${qs(rq)}`);
    const [sort, setSort] = useState('orders');
    return (<Card title="Discount codes" sub="From Shopify's sales report. Average order = order value after discounts, before shipping and tax.">
      <CroGate query={q} rows={4}>
        {(d) => {
            if (!d.total_orders) return <div className="muted small">No orders in these days.</div>;
            const w = d.with_code;
            const wo = d.without_code;
            const p = d.previous;
            const codes = sort === 'orders' ? d.codes : [...d.codes].sort((a, b) => (b.aov ?? 0) - (a.aov ?? 0));
            const maxShare = Math.max(...d.codes.map((c) => c.share_of_orders ?? 0), 1);
            const side = (k, x, prev, cls) => (<div className={`cro-side${cls ? ` ${cls}` : ''}`}>
              <span className="k">{k}</span>
              <div className="row" style={{ gap: 8 }}><span className="big num">{fmtInt(x.orders)}</span><span className="muted small" style={{ marginLeft: -4 }}>orders</span><span className="lane-chip plain">{pct(x.share_of_orders, 1)} of orders</span>
                {prev && cls ? <ChangeChip v={x.share_of_orders - prev.share_of_orders} neutral/> : null}</div>
              <div className="facts num">
                <div><span>Average order</span><b>{x.aov === null ? '—' : money(x.aov)}</b><ChangeChip v={prev ? pctChange(x.aov, prev.aov) : null} unit="%"/></div>
                <div><span>Discount given</span><b>{money(x.discount_given, 'USD', 0)}</b><span>{pct(x.discount_pct, 1)} of gross{cls ? '' : ' · automatic discounts'}</span></div>
                <div><span>Net sales</span><b>{money(x.net_sales, 'USD', 0)}</b></div>
              </div>
            </div>);
            return (<>
              <WindowNote w={d.window} to={d.to} extra={`${fmtInt(d.total_orders)} orders`}/>
              <div className="cro-stack" role="img" aria-label={`${pct(w.share_of_orders, 1)} of orders used a discount code`}><i style={{ width: `${w.share_of_orders ?? 0}%` }}/><i className="no" style={{ width: `${wo.share_of_orders ?? 0}%` }}/></div>
              <div className="cro-vs">
                {side('With a discount code', w, p?.with_code, 'code')}
                {side('Without a code', wo, p?.without_code, '')}
              </div>
              {d.codes.length ? (<>
                <div className="row" style={{ justifyContent: 'space-between', gap: 8, margin: '14px 0 6px', flexWrap: 'wrap' }}>
                  <div><b>Top codes</b> <span className="muted small">· {fmtInt(d.codes.length)} of {fmtInt(d.code_count)} codes used</span></div>
                  <Seg label="Sort codes" options={CODE_SORT} value={sort} onChange={setSort}/>
                </div>
                <div className="table-wrap"><table className="t compact">
                  <thead><tr><th>Code</th><th className="r">Orders</th><th className="r">Share of orders</th><th className="r">Average order vs no code</th><th className="r hide-sm">Discount given</th><th className="r hide-sm">Discount</th></tr></thead>
                  <tbody>{codes.map((c) => (<tr key={c.code}>
                    <td><span className="cro-code">{c.code}</span></td><td className="r"><b>{fmtInt(c.orders)}</b></td>
                    <td className="r"><span className="cro-share warm"><i style={{ width: `${((c.share_of_orders ?? 0) / maxShare) * 60}px` }}/><span className="num">{pct(c.share_of_orders, 1)}</span></span></td>
                    <td className="r num">{c.aov === null ? '—' : money(c.aov)} <ChangeChip v={pctChange(c.aov, wo.aov)} unit="%"/></td>
                    <td className="r hide-sm">{money(c.discount_given, 'USD', 0)}</td><td className="r hide-sm">{pct(c.discount_pct, 1)}</td>
                  </tr>))}</tbody>
                </table></div>
              </>) : <div className="muted small mt-8">No discount codes were used in these days.</div>}
              <div className="muted xs mt-8">An order that used two codes is counted under both codes, so &ldquo;with a code&rdquo; is all orders minus the orders without one. &ldquo;Without a code&rdquo; can still have automatic discounts.</div>
            </>);
        }}
      </CroGate>
    </Card>);
}

/** New vs returning customers (approved design 2026-11-21, batch 5). Shopify decides who is new or returning; no
 * customer is read. */
function CustomersCards({ rq }) {
    const q = useApi(`/cro/customers${qs(rq)}`);
    return (<CroGate query={q} rows={4}>
      {(d) => (<>
        <NewReturningCard d={d}/>
      </>)}
    </CroGate>);
}

function NewReturningCard({ d }) {
    const nr = d.new_vs_returning;
    if (!nr) return (<Card title="New vs returning customers">{d.new_vs_returning_error ? <ExplainedError error={{ code: d.new_vs_returning_error.state, message: d.new_vs_returning_error.message }}/> : <div className="muted small">No figures.</div>}</Card>);
    const prev = nr.previous;
    const side = (k, x, before, cls) => (<div className={`cro-side ${cls}`}>
      <span className="k">{k}</span>
      <div className="row" style={{ gap: 8 }}><span className="big num">{fmtInt(x.orders)}</span><span className="muted small" style={{ marginLeft: -4 }}>orders</span><span className="lane-chip plain">{pct(x.share_of_orders, 1)}</span></div>
      <div className="facts num" style={{ gridTemplateColumns: 'repeat(2, minmax(0, 1fr))' }}>
        <div><span>Average order</span><b>{x.aov === null ? '—' : money(x.aov)}</b><ChangeChip v={before ? pctChange(x.aov, before.aov) : null} unit="%"/></div>
        <div><span>Net sales</span><b>{money(x.net_sales, 'USD', 0)}</b></div>
      </div>
    </div>);
    return (<Card title="New vs returning customers" sub="Shopify decides who is new or returning; Flowmerce reads nothing about the customer.">
      <WindowNote w={d.window} to={d.to} extra={`${fmtInt(nr.orders)} orders`}/>
      {nr.orders ? (<>
        <div className="cro-stack mt-8" role="img" aria-label={`${pct(nr.new.share_of_orders, 1)} of orders from new customers`}><i className="new" style={{ width: `${nr.new.share_of_orders ?? 0}%` }}/><i className="ret" style={{ width: `${nr.returning.share_of_orders ?? 0}%` }}/></div>
        <div className="cro-legend"><span><i className="new"/>New {pct(nr.new.share_of_orders, 1)}</span><span><i className="ret"/>Returning {pct(nr.returning.share_of_orders, 1)}{prev ? ` (${pct(prev.returning.share_of_orders, 1)} before)` : ''}</span></div>
        <div className="cro-vs three mt-8">
          {side('New customers', nr.new, prev?.new, 'new')}
          {side('Returning customers', nr.returning, prev?.returning, 'ret')}
          <div className="cro-side"><span className="k">Returning customer rate</span>
            <div className="row" style={{ gap: 8 }}><span className="big num">{pct(nr.returning_customer_rate, 1)}</span>
              <ChangeChip v={prev && nr.returning_customer_rate !== null && prev.returning_customer_rate !== null ? nr.returning_customer_rate - prev.returning_customer_rate : null}/></div>
            <span className="muted xs">Shopify&rsquo;s figure: the share of customers in these days who had ordered before.{prev && prev.returning_customer_rate !== null ? ` ${pct(prev.returning_customer_rate, 1)} in the comparison days.` : ''}</span></div>
        </div>
      </>) : <div className="muted small mt-8">No orders in these days.</div>}
    </Card>);
}

/* ------------------------------------------------------------------ Recommendations: Claude's plan */
/** Splits "a; b. C" into short facts: on semicolons, and on full stops that end a sentence (not 1.35%). */
const factsOf = (text) => String(text || '').split(/;\s+|\.\s+(?=[A-Z])/).map((x) => x.trim().replace(/\.$/, '')).filter(Boolean).slice(0, 5);
/** The first sentence only: the reason in one line. */
const firstSentence = (text) => (String(text || '').match(/^.*?[.!?](?=\s+[A-Z]|$)/)?.[0] ?? String(text || '')).trim();
/** An action's figures as lines: a list in the deep-dive plan, one "a; b" string in plans made before 2026-11-23. */
const adviceFacts = (a) => (Array.isArray(a.evidence) ? a.evidence : factsOf(a.evidence));
/** The plan's areas: those shared with the Overview (lib/cro.js) and the ones the deep-dive plan added. */
const AREA_LABEL = { ...ADVICE_AREA, landing_page: 'Landing page', payments: 'Payments', search: 'Site search', site_speed: 'Page speed' };
const TARGET_LABEL = {
    page: 'Page', product: 'Product', collection: 'Collection', device: 'Device', channel: 'Channel', country: 'Country', discount_code: 'Discount code',
    checkout_step: 'Checkout step', payment_method: 'Payment method', search_term: 'Search term', store: 'Whole store',
};
const CONFIDENCE_TONE = { High: 'ok', Medium: 'info', Low: 'warn' };

/**
 * One action from Claude's plan, laid out to be read at a glance: its number and what to do as the heading, the money
 * at stake, effort and Claude's confidence as tags, and the exact target; then "What to do" (numbered steps) beside
 * "Diagnosis" and "The numbers"; then the estimate's arithmetic, how to measure the result and what to check first.
 * "Start experiment" opens the Experiments tab with the form filled in. Plans made before the deep dive (no
 * `diagnosis`) keep their older, shorter layout. `compact` is the one-line form on the Overview.
 */
function ActionRow({ a, n, compact, onExperiment, open }) {
    if (compact) {
        return (<div className="act-mini">
          <span className={`act-n impact-${a.impact}`}>{n}</span>
          <div style={{ minWidth: 0 }}>
            <div className="strong">{a.title}</div>
            <div className="muted small">{firstSentence(a.why)}</div>
          </div>
          <Pill tone={IMPACT_TONE[a.impact]}>{a.impact}</Pill>
        </div>);
    }
    const facts = adviceFacts(a);
    if (a.diagnosis) {
        // One fixed order for every action, folded to its heading line so the plan reads as a list:
        // heading (what, where, money) -> problem -> check first -> steps -> how to measure -> the numbers behind it.
        const m = a.measure ?? {};
        return (<details className={`act2 impact-${a.impact}`} open={open}>
          <summary className="act2-head">
            <span className={`act-n impact-${a.impact}`}>{n}</span>
            <span className="act2-titles">
              <span className="act2-title">{a.title}</span>
              <span className="act2-meta">
                {a.target?.name ? <span className="lane-chip lane-research act2-target" title={a.target.name}>{TARGET_LABEL[a.target.kind] ?? 'Target'}: {a.target.name}</span> : null}
                <Pill tone={EFFORT_TONE[a.effort]}>{a.effort} effort</Pill>
                <Pill tone={CONFIDENCE_TONE[a.confidence]}>{a.confidence} confidence</Pill>
                <span className="lane-chip plain">{AREA_LABEL[a.area] ?? a.area}</span>
              </span>
            </span>
            <span className="act2-money">
              <b className="num">{a.impact_usd ? `≈ ${money(a.impact_usd, 'USD', 0)}` : '—'}</b>
              <span>{a.impact_usd ? 'extra sales / 30 days' : 'not estimated'}</span>
            </span>
            <Icon name="chevronDown" size="sm" className="act2-chev"/>
          </summary>
          <div className="act2-body">
            <p className="act2-problem"><b>Problem.</b> {a.diagnosis}</p>
            {a.assumptions ? <div className="act2-check"><Icon name="alert" size="sm"/><span><b>Check first:</b> {a.assumptions}</span></div> : null}
            <div>
              <div className="act-label"><Icon name="checkCircle" size="sm"/>What to do</div>
              <ol className="act-steps">{(a.steps ?? []).map((x, i) => <li key={i}>{x}</li>)}</ol>
            </div>
            <div className="act2-measure">
              <span><b>Measure:</b> {m.metric || '—'} · now <b>{m.baseline || '—'}</b> → goal <b>{m.goal || '—'}</b> · check after {m.check_after_days ?? 14} days</span>
              {onExperiment ? <Button size="sm" icon="flag" onClick={() => onExperiment(a)}>Start experiment</Button> : null}
            </div>
            {facts.length || a.impact_math ? (<details className="act2-more">
              <summary>The numbers behind this{a.impact_math ? ' and how the money is worked out' : ''}</summary>
              {facts.length ? <ul className="act-facts">{facts.map((f, i) => <li key={i}>{f}</li>)}</ul> : null}
              {a.impact_math ? <p className="act2-math"><b>Money:</b> {a.impact_math}</p> : null}
            </details>) : null}
          </div>
        </details>);
    }
    return (<article className={`act impact-${a.impact}`}>
      <header className="act-head">
        <span className={`act-n impact-${a.impact}`}>{n}</span>
        <h3 className="act-title">{a.title}</h3>
        <div className="act-tags">
          <Pill tone={IMPACT_TONE[a.impact]}>{a.impact} impact</Pill>
          <Pill tone={EFFORT_TONE[a.effort]}>{a.effort} effort</Pill>
        </div>
      </header>
      <div className="act-body">
        <section className="act-do">
          <div className="act-label"><Icon name="checkCircle" size="sm"/>What to do</div>
          <ol className="act-steps">{(a.steps ?? []).map((x, i) => <li key={i}>{x}</li>)}</ol>
        </section>
        <section className="act-why">
          <div className="act-label"><Icon name="info" size="sm"/>Why</div>
          <p>{firstSentence(a.why)}</p>
          {facts.length ? (<>
            <div className="act-label"><Icon name="trend" size="sm"/>The numbers</div>
            <ul className="act-facts">{facts.map((f, i) => <li key={i}>{f}</li>)}</ul>
          </>) : null}
        </section>
      </div>
      <footer className="act-foot">{AREA_LABEL[a.area] ?? a.area}{a.metric ? <> · improves <b>{a.metric.replace(/\s*\(.*$/, '')}</b></> : null}</footer>
    </article>);
}

/**
 * Claude's action plan for the store: a deep dive into the last 30 days of every CRO report, with the team's store notes.
 * Opening the tab asks for today's plan once (within the shared daily Claude limit); "Refresh" asks again. While Claude
 * works, the state is read every 4 seconds. `onExperiment` gets an action to turn into an experiment.
 */
function AiAdvice({ brand, onExperiment }) {
    const q = useApi(`/cro/ai-advice${qs({ brand })}`, { remember: false });
    const toast = useToast();
    const [asking, setAsking] = useState(false);
    const asked = useRef('');
    const { data, reload } = q;
    const ask = async (auto) => {
        setAsking(true);
        try { await api.post(`/cro/ai-advice${qs({ brand })}`, { auto }); }
        catch (e) { if (!auto) toast.error(e); }
        finally { setAsking(false); reload(); }
    };
    useEffect(() => {
        if (data && data.configured && !data.fresh && data.status !== 'running' && asked.current !== brand) {
            asked.current = brand;
            ask(true);
        }
    }, [data, brand]); // eslint-disable-line react-hooks/exhaustive-deps
    useEffect(() => {
        if (data?.status !== 'running')
            return undefined;
        const t = setInterval(reload, 4000);
        return () => clearInterval(t);
    }, [data?.status, reload]);
    if (q.error)
        return <ExplainedError error={q.error} onRetry={reload}/>;
    if (!data)
        return <LoadingBlock rows={3}/>;
    const running = data.status === 'running' || asking;
    const plan = data.advice;
    const deep = data.version >= 2;
    const total = deep ? plan?.actions.reduce((s, a) => s + (a.impact_usd || 0), 0) : 0;
    const sub = plan ? `${plan.actions.length} actions from the last 30 days · ${timeAgo(data.generated_at)}${total ? ` · about ${money(total, 'USD', 0)} at stake over 30 days` : ''}`
        : 'Claude reads the last 30 days of every report on this page, with your store notes, and says what to change.';
    return (<Card className="advice-plan" title={<span className="row" style={{ gap: 8 }}><Icon name="sparkle"/>Claude&rsquo;s action plan</span>} sub={sub}
      actions={data.configured ? <Button size="sm" icon="refresh" loading={running} onClick={() => ask(false)} title={`Ask Claude again (about $${Number(data.estimate_usd ?? 0.3).toFixed(2)} of today's Claude limit)`}>{running ? 'Claude is reading…' : 'Refresh'}</Button> : null}>
      {!data.configured ? <div className="callout info"><Icon name="info"/><div>Set <b>ANTHROPIC_API_KEY</b> on the server (the same key SEO &amp; Blog uses) to get Claude&rsquo;s plan here.</div></div> : null}
      {data.error ? <div className="callout warn mb-12"><Icon name="alert"/><div>The last request did not finish: {data.error}</div></div> : null}
      {running && !plan ? (<div className="advice-wait"><Icon name="loader" className="spin"/><span>Claude is reading the store&rsquo;s figures. This takes about a minute.</span></div>) : null}
      {plan ? (<div className="col" style={{ gap: 12 }}>
          {!deep && !running ? <div className="callout info"><Icon name="info"/><div>This is the older, shorter plan. Press <b>Refresh</b> for the deep dive: root cause, money at stake and how to measure each action.</div></div> : null}
          {deep && plan.summary ? <p className="act-summary">{plan.summary}</p> : null}
          <div className="act-list stagger">{plan.actions.map((a, i) => <ActionRow key={`${a.title}-${i}`} a={a} n={i + 1} open={i === 0} onExperiment={onExperiment}/>)}</div>
          {deep && plan.actions.length > 1 ? <div className="muted xs">Click an action to open or fold it. The first one is open.</div> : null}
          {data.not_available?.length ? <div className="muted xs">Claude could not see: {data.not_available.join('; ')}.</div> : null}
        </div>) : null}
      {data.budget ? <div className="muted xs mt-8">Claude today: ${Number(data.budget.todayUsd ?? 0).toFixed(2)} of ${Number(data.budget.dailyLimitUsd ?? 0).toFixed(2)} used, shared with SEO &amp; Blog{data.cost_usd ? ` · this plan cost $${Number(data.cost_usd).toFixed(2)}` : ''}.</div> : null}
    </Card>);
}

/** The experiment form's fields from one of Claude's actions. */
function experimentFrom(a) {
    const m = a.measure ?? {};
    const goal = m.metric ? ` Measure ${m.metric}: ${m.baseline || 'now'} → ${m.goal || 'better'}, check after ${m.check_after_days ?? 14} days.` : '';
    return { name: a.title.slice(0, 200), metric: a.experiment_metric || 'conversion_rate', page_path: a.page_path || '', rec_key: `ai:${a.title}`.slice(0, 300),
        hypothesis: `${a.diagnosis || firstSentence(a.why)}${goal}`.slice(0, 2000) };
}

const NOTES_HINT = 'For example: what you sell and the usual price range; the free-shipping amount; apps already in use (reviews, email, '
    + 'abandoned-checkout emails, upsell); what you tried before and how it went; anything the figures cannot show (stock problems, '
    + 'slow suppliers, a sale coming up).';

/** The team's notes about the store, which Claude reads with the figures so it does not recommend what is already in
 * place. Saved for everyone (not per browser). Shown open while empty, folded to the first lines once written. */
function StoreNotes({ brand }) {
    const q = useApi(`/cro/store-notes${qs({ brand })}`, { remember: false });
    const toast = useToast();
    const [text, setText] = useState(null);   // null = not editing
    const [saving, setSaving] = useState(false);
    const saved = q.data?.text ?? '';
    const editing = text !== null || (q.data && !saved);
    const value = text ?? saved;
    const save = async () => {
        setSaving(true);
        try { await api.put(`/cro/store-notes${qs({ brand })}`, { text: value }); toast.ok(value.trim() ? 'Store notes saved. Claude reads them on the next Refresh.' : 'Store notes cleared.'); setText(null); q.reload(); }
        catch (e) { toast.error(e); }
        finally { setSaving(false); }
    };
    if (q.error?.code === 'demo_not_found')
        return null;   // the demo has no store notes yet
    return (<Card title="Store notes for Claude" sub="What the figures cannot show. Claude reads these with the figures, so it does not suggest what you already have."
      actions={!editing ? <Button size="sm" variant="ghost" icon="edit" onClick={() => setText(saved)}>Edit</Button> : null}>
      {q.error ? <ExplainedError error={q.error} onRetry={q.reload}/> : !q.data ? <LoadingBlock rows={2}/> : editing ? (<>
        <textarea className="input" rows={6} style={{ width: '100%' }} value={value} maxLength={q.data.max_length} placeholder={NOTES_HINT}
          onChange={(e) => setText(e.target.value)} aria-label="Store notes for Claude"/>
        <div className="row mt-8" style={{ gap: 8, justifyContent: 'space-between', flexWrap: 'wrap' }}>
          <span className="muted xs">{value.length.toLocaleString()} of {q.data.max_length.toLocaleString()} characters · seen by everyone on the team</span>
          <div className="row" style={{ gap: 8 }}>
            {saved ? <Button size="sm" variant="ghost" onClick={() => setText(null)}>Cancel</Button> : null}
            <Button size="sm" variant="primary" loading={saving} disabled={value === saved} onClick={save}>Save notes</Button>
          </div>
        </div>
      </>) : (<>
        <p className="act-notes">{saved}</p>
        <div className="muted xs">Saved {q.data.updated_at ? timeAgo(q.data.updated_at) : ''}{q.data.updated_by ? ` by ${q.data.updated_by}` : ''}.</div>
      </>)}
    </Card>);
}

/* ------------------------------------------------------------------ Recommendations */
const ACTION_META = {
    fix: { label: 'Fix', lane: 'lane-due', icon: 'edit', bar: 'var(--crit)' },
    promote: { label: 'Promote', lane: 'lane-live', icon: 'trend', bar: 'var(--ok)' },
    test: { label: 'Test', lane: 'lane-draft', icon: 'flag', bar: 'var(--cpc)' },
};
const EFFORT_LANE = { Low: 'lane-live', Medium: 'lane-event', High: 'lane-due' };
const REC_STATUS = [{ key: 'open', label: 'Open' }, { key: 'in_progress', label: 'In progress' }, { key: 'done', label: 'Done' }, { key: 'ignored', label: 'Ignore' }];
const REC_FILTERS = [['open', 'All open'], ['fix', 'Fix'], ['promote', 'Promote'], ['test', 'Test'], ['closed', 'Done / ignored']];
const EXP_METRIC = { conversion_rate: 'conversion_rate', added_to_cart_rate: 'added_to_cart_rate', bounce_rate: 'bounce_rate' };

/**
 * Recommendations (approved design 2026-11-21, under Advanced): Claude's plan on top, then every check ranked by its
 * estimated money impact over the last 28 days. Each card ends in an action (fix, promote or test) and a status the
 * whole team sees; "Start experiment" opens the Experiments tab with the form filled in.
 */
function RecommendationsTab({ brand, onExperiment }) {
    const q = useApi(`/cro/recommendations${qs({ brand })}`);
    const toast = useToast();
    const [filter, setFilter] = useState('open');
    const [saving, setSaving] = useState(null);
    const setStatus = async (r, status) => {
        setSaving(r.key);
        const prev = r.status;
        q.setData((d) => ({ ...d, recommendations: d.recommendations.map((x) => (x.key === r.key ? { ...x, status } : x)) }));
        try { await api.post(`/cro/recommendations/status${qs({ brand })}`, { key: r.key, status }); }
        catch (e) { q.setData((d) => ({ ...d, recommendations: d.recommendations.map((x) => (x.key === r.key ? { ...x, status: prev } : x)) })); toast.error(e); }
        finally { setSaving(null); }
    };
    return (<div className="col" style={{ gap: 16 }}>
    <AiAdvice brand={brand} onExperiment={(a) => onExperiment(experimentFrom(a))}/>
    <StoreNotes brand={brand}/>
    <div className="cro-sec">Ranked checks</div>
    <CroGate query={q}>
      {(d) => {
          const isOpen = (r) => !['done', 'ignored'].includes(r.status);
          const open = d.recommendations.filter(isOpen);
          const count = (a) => open.filter((r) => r.action === a).length;
          const shown = d.recommendations.filter((r) => (filter === 'open' ? isOpen(r) : filter === 'closed' ? !isOpen(r) : isOpen(r) && r.action === filter));
          const best = open.filter((r) => r.impact !== null)[0];
          const total = open.reduce((a, r) => a + (r.impact ?? 0), 0);
          return (<>
            <div className="muted small">Based on <b>{fmtDate(d.window.from)} – {fmtDate(d.window.to)}</b> · ranked by estimated impact</div>
            <div className="cro-tiles">
              <div className="cro-tile lane-due"><span className="lbl">Open items</span><span className="v num">{open.length}</span><span className="s">{count('fix')} fix · {count('promote')} promote · {count('test')} test</span></div>
              <div className="cro-tile lane-live"><span className="lbl">Biggest opportunity</span><span className="v num">{best ? money(best.impact, 'USD', 0) : '—'}</span><span className="s ellipsis">{best ? best.segment : 'nothing estimated'}</span></div>
              <div className="cro-tile lane-research"><span className="lbl">Store conversion</span><span className="v num">{pct(d.store_conversion_rate)}</span><span className="s">{fmtInt(d.sessions)} visits</span></div>
              <div className="cro-tile lane-event"><span className="lbl">Average order</span><span className="v num">{d.aov ? money(d.aov, 'USD', 0) : '—'}</span><span className="s">{fmtInt(d.orders)} orders</span></div>
            </div>
            {!d.statuses_available ? <div className="callout warn"><Icon name="alert"/><div>{d.status_error?.message || 'Statuses cannot be saved right now.'}</div></div> : null}
            {d.skipped.length ? <div className="callout"><Icon name="info"/><div>Some data could not be read: {d.skipped.join('; ')}.</div></div> : null}
            <div className="row" style={{ justifyContent: 'space-between' }}>
              <div className="row" style={{ gap: 6 }} role="group" aria-label="Filter">
                {REC_FILTERS.map(([k, label]) => <button key={k} type="button" className={`cro-pill${filter === k ? ' on' : ''}`} aria-pressed={filter === k} onClick={() => setFilter(k)}>
                  {label} ({k === 'open' ? open.length : k === 'closed' ? d.recommendations.length - open.length : count(k)})</button>)}
              </div>
              {total ? <span className="muted small">Open items together: about <b>{money(total, 'USD', 0)}</b> over 28 days if each closed its gap</span> : null}
            </div>
            {shown.length ? (<Paged rows={shown} size={10} resetKey={filter}>
              {(rows) => <div className="col" style={{ gap: 10 }}>{rows.map((r, i) => <RecCard key={r.key} r={r} open={i === 0 && filter === 'open'} saving={saving === r.key} canSave={d.statuses_available}
                onStatus={(s) => setStatus(r, s)} onExperiment={() => onExperiment(experimentFromRec(r))}/>)}</div>}
            </Paged>) : <CroEmpty icon="checkCircle" title={filter === 'closed' ? 'Nothing marked done or ignored yet' : 'Nothing flagged for these days'}>Recommendations only appear when the store&rsquo;s own figures support them.</CroEmpty>}
            <div className="muted xs">Impacts are estimates to rank the list (visits × conversion gap × average order over the 28 days), not promises. Checks without an estimate rank after them by priority.</div>
          </>);
      }}
    </CroGate>
    </div>);
}

/** The experiment form's fields from one ranked check: its own metric and page when the check gives them. */
function experimentFromRec(r) {
    const m = r.measure;
    const goal = m?.metric ? ` Measure ${m.metric}: ${m.baseline} → ${m.goal}.` : '';
    return { name: r.title.slice(0, 200), metric: r.experiment_metric || 'conversion_rate',
        page_path: r.page_path ?? (r.key.startsWith('landing_') ? r.key.split(':').slice(1).join(':') : ''), rec_key: r.key,
        hypothesis: `${r.diagnosis || r.title}${goal}`.slice(0, 2000) };
}

const REC_STATUS_TONE = { in_progress: 'info', done: 'ok', ignored: 'neutral' };

/**
 * One ranked check, folded to its heading line like the actions of Claude's plan: rank, the check, its target, kind of
 * action, effort and estimated money. Opened: problem, what to do, how to measure with "Start experiment", the team's
 * status, and the numbers behind it. Checks from before the deep checks (no `diagnosis`) show their evidence instead.
 */
function RecCard({ r, open, saving, canSave, onStatus, onExperiment }) {
    const a = ACTION_META[r.action] ?? ACTION_META.fix;
    const closed = r.status === 'done' || r.status === 'ignored';
    const m = r.measure;
    const steps = r.steps?.length ? r.steps : r.suggested_action ? [r.suggested_action] : [];
    const status = REC_STATUS.find((s) => s.key === r.status);
    return (<details className={`act2 rec2${closed ? ' dim' : ''}`} open={open}>
      <summary className="act2-head">
        <span className="act-n rec-n">{r.rank}</span>
        <span className="act2-titles">
          <span className={`act2-title${r.status === 'done' ? ' done' : ''}`}>{r.title}</span>
          <span className="act2-meta">
            <span className={`lane-chip ${a.lane}`}><Icon name={a.icon} size="sm"/>{a.label}</span>
            {r.segment ? <span className="lane-chip lane-research act2-target" title={r.segment}>{r.segment}</span> : null}
            <span className={`lane-chip ${EFFORT_LANE[r.effort] ?? 'plain'}`}>{r.effort} effort</span>
            {r.status && r.status !== 'open' ? <Pill tone={REC_STATUS_TONE[r.status]}>{status?.label ?? r.status}</Pill> : null}
          </span>
        </span>
        <span className="act2-money">
          <b className="num">{r.impact === null ? '—' : `≈ ${money(r.impact, 'USD', 0)}`}</b>
          <span>{r.impact === null ? 'not estimated' : 'est. / 28 days'}</span>
        </span>
        <Icon name="chevronDown" size="sm" className="act2-chev"/>
      </summary>
      <div className="act2-body">
        {r.diagnosis ? <p className="act2-problem"><b>Problem.</b> {r.diagnosis}</p> : null}
        {steps.length ? (<div>
          <div className="act-label"><Icon name="checkCircle" size="sm"/>What to do</div>
          <ol className="act-steps">{steps.map((x, i) => <li key={i}>{x}</li>)}</ol>
        </div>) : null}
        <div className="act2-measure">
          <span>{m?.metric ? <><b>Measure:</b> {m.metric} · now <b>{m.baseline}</b> → goal <b>{m.goal}</b> · check after {m.check_after_days ?? 14} days</>
              : <span className="muted">Mark its status so the whole team sees it.</span>}</span>
          <span className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
            <Button size="sm" icon="flag" onClick={onExperiment}>Start experiment</Button>
            <span className={`seg sm${saving ? ' busy' : ''}`} role="group" aria-label="Status">
              {REC_STATUS.map((s) => <button key={s.key} type="button" aria-pressed={r.status === s.key} disabled={saving || !canSave} onClick={() => onStatus(s.key)}>{s.label}</button>)}
            </span>
          </span>
        </div>
        <details className="act2-more" open={!r.diagnosis}>
          <summary>The numbers behind this{r.impact_formula ? ' and how the money is worked out' : ''}</summary>
          <ul className="act-facts">{(r.evidence_list ?? [r.evidence]).map((e) => <li key={e}>{e}</li>)}</ul>
          {r.impact_formula ? <p className="act2-math"><b>Money:</b> {r.impact_formula}</p> : null}
        </details>
      </div>
    </details>);
}

/* ------------------------------------------------------------------ Experiments */
const VERDICT = {
    win: { label: 'Win', lane: 'lane-live' }, win_so_far: { label: 'Win so far', lane: 'lane-live' }, better: { label: 'Better', lane: 'lane-live' },
    loss: { label: 'Loss', lane: 'lane-due' }, loss_so_far: { label: 'Loss so far', lane: 'lane-due' }, worse: { label: 'Worse', lane: 'lane-due' },
    running: { label: 'Running', lane: 'lane-research' }, early: { label: 'Running', lane: 'lane-research' },
    no_clear_result: { label: 'No clear result', lane: 'plain' }, flat: { label: 'No change', lane: 'plain' },
    too_few: { label: 'Too few visits', lane: 'lane-event' }, planned: { label: 'Planned', lane: 'lane-draft' },
    no_data: { label: 'No data', lane: 'plain' }, error: { label: 'Could not load', lane: 'lane-due' },
};
const EXP_BLANK = { name: '', metric: 'conversion_rate', hypothesis: '', start_date: '', end_date: '', page_path: '', owner: '', rec_key: '' };

/**
 * Experiments (approved design 2026-11-21, under Advanced): the team writes the plan; the result comes from Shopify,
 * comparing the test days with the same number of days just before. Change-log entries from those days sit next to
 * each result, because a before-and-after comparison also moves with anything else that changed.
 */
function ExperimentsTab({ brand, today, draft, onDraftUsed }) {
    const q = useApi(`/cro/experiments${qs({ brand })}`);
    const toast = useToast();
    const [form, setForm] = useState(null);   // null = closed; otherwise the fields (with `id` when editing)
    useEffect(() => {
        if (draft) { setForm({ ...EXP_BLANK, start_date: today, ...draft }); onDraftUsed(); }
    }, [draft]); // eslint-disable-line react-hooks/exhaustive-deps
    const remove = async (e) => {
        if (!window.confirm(`Delete "${e.name}"? This cannot be undone.`)) return;
        try { await api.del(`/cro/experiments/${e.id}${qs({ brand })}`); toast.ok('Experiment deleted.'); q.reload(); }
        catch (err) { toast.error(err); }
    };
    return (<div className="col" style={{ gap: 16 }}>
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <div className="muted small">Each test is compared with the same number of days just before it started, from Shopify.</div>
        {form ? null : <Button variant="primary" icon="plus" onClick={() => setForm({ ...EXP_BLANK, start_date: today })}>New experiment</Button>}
      </div>
      <CroGate query={q}>
        {(d) => (<>
          <div className="cro-tiles">
            <div className="cro-tile lane-draft"><span className="lbl">Experiments</span><span className="v num">{d.summary.total}</span><span className="s">{d.summary.planned} planned</span></div>
            <div className="cro-tile lane-research"><span className="lbl">Running now</span><span className="v num">{d.summary.running}</span><span className="s">measured up to yesterday</span></div>
            <div className="cro-tile lane-live"><span className="lbl">Finished</span><span className="v num">{d.summary.finished}</span><span className="s">{d.summary.won} won</span></div>
            <div className="cro-tile lane-event"><span className="lbl">Win rate</span><span className="v num">{d.summary.win_rate === null ? '—' : `${d.summary.win_rate}%`}</span><span className="s">of finished tests</span></div>
          </div>
          {form ? <ExperimentForm brand={brand} metrics={d.metrics} value={form} onCancel={() => setForm(null)} onSaved={() => { setForm(null); q.reload(); }}/> : null}
          {d.experiments.length ? d.experiments.map((e) => <ExperimentCard key={e.id} e={e} log={d.change_log} onEdit={() => setForm({ ...EXP_BLANK, ...e, end_date: e.end_date ?? '', page_path: e.page_path ?? '', owner: e.owner ?? '' })} onDelete={() => remove(e)}/>)
              : form ? null : <CroEmpty icon="flag" title="No experiments yet">Start one here, or from a &ldquo;Test&rdquo; item on the Recommendations tab.</CroEmpty>}
        </>)}
      </CroGate>
    </div>);
}

function ExperimentForm({ brand, metrics, value, onCancel, onSaved }) {
    const toast = useToast();
    const [f, setF] = useState(value);
    const [saving, setSaving] = useState(false);
    const set = (k) => (e) => setF((x) => ({ ...x, [k]: e.target.value }));
    const ok = f.name.trim() && f.hypothesis.trim() && f.start_date;
    const save = async () => {
        setSaving(true);
        const body = { name: f.name, hypothesis: f.hypothesis, metric: f.metric, start_date: f.start_date, end_date: f.end_date || null, page_path: f.page_path || null, owner: f.owner || null, rec_key: f.rec_key || null };
        try {
            if (f.id) await api.patch(`/cro/experiments/${f.id}${qs({ brand })}`, body);
            else await api.post(`/cro/experiments${qs({ brand })}`, body);
            toast.ok('Experiment saved.');
            onSaved();
        } catch (e) { toast.error(e); }
        finally { setSaving(false); }
    };
    return (<Card title={f.id ? 'Edit experiment' : 'New experiment'} sub={f.rec_key ? 'From a recommendation. The result is worked out from Shopify; you only describe the test.' : 'The result is worked out from Shopify; you only describe the test.'} className="cro-form">
      <div className="form-grid">
        <Field label="Name"><input className="input" value={f.name} onChange={set('name')} placeholder="Sticky add-to-cart on mobile" maxLength={200}/></Field>
        <Field label="Metric"><select className="input" value={f.metric} onChange={set('metric')}>{metrics.map((m) => <option key={m.key} value={m.key}>{m.label}</option>)}</select></Field>
        <Field label="What do you expect to happen?" full><textarea className="input" rows={3} value={f.hypothesis} onChange={set('hypothesis')} maxLength={2000}/></Field>
        <Field label="Start date"><input className="input" type="date" value={f.start_date} onChange={set('start_date')}/></Field>
        <Field label="End date (empty = still running)"><input className="input" type="date" value={f.end_date} onChange={set('end_date')}/></Field>
        <Field label="Landing page (empty = whole store)" hint={f.metric === 'aov' ? 'Average order value is for the whole store.' : undefined}>
          <input className="input" value={f.page_path} onChange={set('page_path')} placeholder="/collections/quilts" disabled={f.metric === 'aov'}/></Field>
        <Field label="Owner"><input className="input" value={f.owner} onChange={set('owner')} placeholder="Team or role" maxLength={200}/></Field>
      </div>
      <div className="row mt-16" style={{ gap: 8 }}><Button variant="primary" loading={saving} disabled={!ok} onClick={save}>Save experiment</Button><Button onClick={onCancel}>Cancel</Button></div>
    </Card>);
}

function ExperimentCard({ e, log, onEdit, onDelete }) {
    const r = e.result ?? {};
    const v = VERDICT[r.verdict] ?? VERDICT.no_data;
    const fmtVal = (x) => (x === null || x === undefined ? '—' : e.metric === 'aov' ? money(x) : pct(x));
    const good = r.change !== undefined && r.change !== null ? (e.better === 'up' ? r.change > 0 : r.change < 0) : null;
    const until = e.end_date ?? isoDay(new Date());
    const nearby = (log ?? []).filter((c) => c.entry_date >= String(e.start_date).slice(0, 10) && c.entry_date <= until).slice(0, 3);
    return (<article className="card cro-exp">
      <div className="top">
        <div style={{ minWidth: 0 }}>
          <div className="row" style={{ gap: 6 }}><span className={`lane-chip ${v.lane}`}>{v.label}</span><span className="lane-chip lane-research">{e.metric_label}</span><span className="lane-chip plain">{e.page_path || 'Whole store'}</span></div>
          <h3 className="title">{e.name}</h3>
          <div className="small" style={{ color: 'var(--ink-2)' }}>{e.hypothesis}</div>
          <div className="muted small mt-4">{fmtDate(e.start_date)} → {e.end_date ? fmtDate(e.end_date) : r.state === 'planned' ? 'no end date yet' : 'running'}{e.owner ? ` · ${e.owner}` : ''}</div>
        </div>
        <div className="row" style={{ gap: 2, flex: 'none' }}><Button size="sm" variant="ghost" icon="edit" iconOnly aria-label={`Edit ${e.name}`} onClick={onEdit}/><Button size="sm" variant="ghost" icon="x" iconOnly aria-label={`Delete ${e.name}`} onClick={onDelete}/></div>
      </div>
      {r.state === 'planned' ? <div className="muted small">{r.summary}</div> : r.state === 'error' ? <div className="down small">{r.error}</div> : (<>
        <div className="cro-four">
          <div className="cro-box"><span className="k">Before · {r.before_label}</span><span className="v num">{fmtVal(r.before)}</span><span className="muted xs">{fmtInt(r.before_n)} {r.n_unit}</span></div>
          <div className="cro-box"><span className="k">During · {r.during_label}</span><span className="v num">{fmtVal(r.during)}</span><span className="muted xs">{fmtInt(r.during_n)} {r.n_unit}</span></div>
          <div className="cro-box"><span className="k">Change</span><span className={`v num ${good === null ? '' : good ? 'up' : 'down'}`}>{r.change === null || r.change === undefined ? '—' : r.change_unit === '%' ? signedPct(r.change) : signedPts(r.change)}</span><span className="muted xs">{e.better === 'up' ? 'higher is better' : 'lower is better'}</span></div>
          <div className="cro-box"><span className="k">Confidence</span><span className="v num">{r.confidence === null || r.confidence === undefined ? '—' : `${r.confidence}%`}</span>
            {r.confidence !== null && r.confidence !== undefined ? <div className="ibar"><span style={{ width: `${r.confidence}%`, background: r.confidence >= 95 ? 'var(--ok)' : 'var(--info)' }}/></div> : <span className="muted xs">not given for order value</span>}</div>
        </div>
        <div className="cro-cl"><span className="lane-chip lane-event">Change log</span>{nearby.length ? nearby.map((c) => `${fmtDate(c.entry_date)} · ${areaLabel(c.area)}: ${c.change}`).join(' · ') : 'No other changes logged in these days'}</div>
      </>)}
    </article>);
}

/* ------------------------------------------------------------------ Alarms */
function AlarmsTab({ brand }) {
    const rules = useApi(`/cro/alarms${qs({ brand })}`);
    const alerts = useApi(`/cro/alerts${qs({ brand, limit: 100 })}`);
    const toast = useToast();
    const act = async (fn, done) => {
        try { await fn(); toast.ok(done); rules.reload(); } catch (e) { toast.error(e); }
    };
    return (<div className="col" style={{ gap: 16 }}>
      <CroGate query={rules}>
        {(d) => (<>
          <div className="row gap-12" style={{ alignItems: 'center' }}>
            <span className="small">Alarms for this store are <b>{d.alarms_enabled ? 'on' : 'off'}</b>. They are checked every 15 minutes and shown here; no email is sent.</span>
            <span className="spacer"/>
            <Button size="sm" onClick={() => act(() => api.patch(`/cro/settings${qs({ brand })}`, { alarms_enabled: !d.alarms_enabled }), `Alarms switched ${d.alarms_enabled ? 'off' : 'on'}.`)}>
              {d.alarms_enabled ? 'Switch all off' : 'Switch all on'}
            </Button>
          </div>
          <Card title="Rules" flush>
            <div className="table-wrap"><table className="t compact">
              <thead><tr><th>Rule</th><th>Alarm at</th><th className="hide-sm">Last checked</th><th>Status</th><th/></tr></thead>
              <tbody>{d.rules.map((r) => <RuleRow key={r.id} r={r} brand={brand} act={act}/>)}</tbody>
            </table></div>
          </Card>
          <NewRuleCard brand={brand} act={act}/>
        </>)}
      </CroGate>
      <Card title="Alert history" flush>
        <CroGate query={alerts} rows={3}>
          {(a) => (a.alerts.length ? (<Paged rows={a.alerts}>
            {(rows) => (<div className="table-wrap"><table className="t compact">
              <thead><tr><th>When</th><th className="hide-sm">Rule</th><th>What happened</th><th>State</th></tr></thead>
              <tbody>{rows.map((x) => (<tr key={x.id}><td className="nowrap">{fmtDateTime(x.triggered_at)}</td><td className="hide-sm">{x.rule}</td><td className="small">{x.message}</td>
                <td>{x.resolved_at ? <Pill tone="ok">Resolved {timeAgo(x.resolved_at)}</Pill> : <Pill tone="crit" dot>Open</Pill>}</td></tr>))}</tbody>
            </table></div>)}
          </Paged>) : <div className="muted small" style={{ padding: 16 }}>No alarm has fired for this store.</div>)}
        </CroGate>
      </Card>
    </div>);
}

function RuleRow({ r, brand, act }) {
    const kind = RULE_KIND[r.kind] ?? { label: r.kind, unit: '' };
    const [editing, setEditing] = useState(false);
    const [threshold, setThreshold] = useState(String(Number(r.threshold)));
    const [keyword, setKeyword] = useState(r.product_keyword ?? '');
    const [title, setTitle] = useState(r.title);
    const save = () => act(async () => {
        const body = { threshold: Number(threshold), title };
        if (r.kind === 'no_product_orders') body.product_keyword = keyword;
        await api.patch(`/cro/alarms/${r.id}${qs({ brand })}`, body);
        setEditing(false);
    }, 'Rule saved.');
    return (<tr>
      <td>{editing ? <input className="input sm" style={{ width: '100%', minWidth: 160 }} value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} aria-label="Rule name"/> : <b>{r.title}</b>}<div className="muted xs">{kind.label}{r.product_keyword ? ` · products matching "${r.product_keyword}"` : ''}</div></td>
      <td className="nowrap">{editing ? (<div className="row">
          <input className="input sm" style={{ width: 80 }} type="number" min="0" step="0.5" value={threshold} onChange={(e) => setThreshold(e.target.value)} aria-label="Threshold"/>
          <span className="muted xs">{kind.unit}</span>
          {r.kind === 'no_product_orders' ? <input className="input sm" style={{ width: 110 }} value={keyword} onChange={(e) => setKeyword(e.target.value)} aria-label="Product keyword"/> : null}
        </div>) : `${Number(r.threshold)} ${kind.unit}`}</td>
      <td className="hide-sm muted small">{r.last_checked_at ? timeAgo(r.last_checked_at) : 'not yet'}</td>
      <td>{!r.is_active ? <Pill>Off</Pill> : r.open_alert ? <Pill tone="crit" dot>Alarm</Pill> : <Pill tone="ok">Normal</Pill>}</td>
      <td className="r nowrap">
        {editing ? <><Button size="sm" variant="primary" onClick={save}>Save</Button> <Button size="sm" onClick={() => setEditing(false)}>Cancel</Button></>
            : <><Button size="sm" variant="ghost" icon="edit" onClick={() => setEditing(true)}>Edit</Button>{' '}
              <Button size="sm" onClick={() => act(() => api.patch(`/cro/alarms/${r.id}${qs({ brand })}`, { is_active: !r.is_active }), r.is_active ? 'Rule switched off.' : 'Rule switched on.')}>{r.is_active ? 'Switch off' : 'Switch on'}</Button></>}
      </td>
    </tr>);
}

function NewRuleCard({ brand, act }) {
    const [f, setF] = useState({ title: '', keyword: '', hours: '12' });
    const set = (k, v) => setF((x) => ({ ...x, [k]: v }));
    const add = () => act(async () => {
        await api.post(`/cro/alarms${qs({ brand })}`, { kind: 'no_product_orders', title: f.title || `No ${f.keyword} orders for ${f.hours} hours`, threshold: Number(f.hours), product_keyword: f.keyword });
        setF({ title: '', keyword: '', hours: '12' });
    }, 'Rule added.');
    return (<Card title="Add a product alarm" sub={RULE_KIND.no_product_orders.help}>
      <div className="row gap-12" style={{ flexWrap: 'wrap', alignItems: 'flex-end' }}>
        <Field label="Product keyword"><input className="input" value={f.keyword} onChange={(e) => set('keyword', e.target.value)} placeholder="e.g. tablecloth"/></Field>
        <Field label="Hours without an order"><input className="input" type="number" min="1" value={f.hours} onChange={(e) => set('hours', e.target.value)} style={{ width: 120 }}/></Field>
        <Field label="Name (optional)"><input className="input" value={f.title} onChange={(e) => set('title', e.target.value)} placeholder={f.keyword ? `No ${f.keyword} orders for ${f.hours} hours` : ''}/></Field>
        <Button variant="primary" icon="plus" disabled={!f.keyword.trim() || !(Number(f.hours) > 0)} onClick={add}>Add alarm</Button>
      </div>
    </Card>);
}

/* ------------------------------------------------------------------ Change log */
function ChangeLogTab({ brand }) {
    const q = useApi(`/cro/change-log${qs({ brand, days: 365 })}`);
    const toast = useToast();
    const [f, setF] = useState({ entry_date: isoDay(new Date()), area: 'theme', change: '', owner: '' });
    const [saving, setSaving] = useState(false);
    const set = (k, v) => setF((x) => ({ ...x, [k]: v }));
    const add = async () => {
        setSaving(true);
        try {
            await api.post(`/cro/change-log${qs({ brand })}`, f);
            toast.ok('Change logged.');
            setF((x) => ({ ...x, change: '' }));
            q.reload();
        } catch (e) { toast.error(e); } finally { setSaving(false); }
    };
    const remove = async (id) => {
        try { await api.del(`/cro/change-log/${id}${qs({ brand })}`); toast.ok('Entry removed.'); q.reload(); } catch (e) { toast.error(e); }
    };
    return (<div className="col" style={{ gap: 16 }}>
      <Card title="Log a store change" sub="Theme edits, new apps, price changes, promotions and ads: anything that could move conversion. It helps explain jumps in the charts.">
        <div className="row gap-12" style={{ flexWrap: 'wrap', alignItems: 'flex-end' }}>
          <Field label="Date"><input className="input" type="date" value={f.entry_date} onChange={(e) => set('entry_date', e.target.value)}/></Field>
          <Field label="Area"><select className="select" value={f.area} onChange={(e) => set('area', e.target.value)}>{AREAS.map((a) => <option key={a.key} value={a.key}>{a.label}</option>)}</select></Field>
          <div style={{ flex: '1 1 280px', minWidth: 0 }}>
            <Field label="What changed"><input className="input" style={{ width: '100%' }} value={f.change} maxLength={1000} onChange={(e) => set('change', e.target.value)} placeholder="e.g. New product page layout on quilts"/></Field>
          </div>
          <Field label="Who made it"><input className="input" value={f.owner} maxLength={200} onChange={(e) => set('owner', e.target.value)}/></Field>
          <Button variant="primary" icon="plus" loading={saving} disabled={!f.change.trim()} onClick={add}>Add</Button>
        </div>
      </Card>
      <Card title="Changes in the last 12 months" flush>
        <CroGate query={q} rows={3}>
          {(d) => (d.entries.length ? (<Paged rows={d.entries}>
            {(rows) => (<div className="table-wrap"><table className="t compact">
              <thead><tr><th>Date</th><th>Area</th><th>Change</th><th className="hide-sm">Who</th><th/></tr></thead>
              <tbody>{rows.map((e) => (<tr key={e.id}><td className="nowrap">{fmtDate(e.entry_date)}</td><td><Pill>{areaLabel(e.area)}</Pill></td><td>{e.change}</td>
                <td className="hide-sm muted">{e.owner || e.created_by || '—'}</td>
                <td className="r"><Button size="sm" variant="ghost" iconOnly icon="x" title="Remove this entry" aria-label="Remove this entry" onClick={() => remove(e.id)}/></td></tr>))}</tbody>
            </table></div>)}
          </Paged>) : <div className="muted small" style={{ padding: 16 }}>Nothing logged yet.</div>)}
        </CroGate>
      </Card>
    </div>);
}

