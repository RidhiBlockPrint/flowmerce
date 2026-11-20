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
    ADVICE_AREA, AREAS, EFFORT_TONE, IMPACT_TONE, PERFORMANCE, PRIORITY_TONE, RANGE_PRESETS, RULE_KIND, STORES, TABS,
    areaLabel, conversionScale, effectiveCompare, money, pct, presetRange, rangeDays, seriesOf, shiftDay, signedPct, signedPts, todayIn,
} from '../lib/cro';
import { BarList, LineChart } from '../components/charts';
import { CroEmpty, CroGate, ExplainedError, KpiTile, RangeBar, Seg } from '../components/cro';
import { RingBody, RingCard } from '../components/dash';
import { Gauge } from '../components/motion';
import { DayStrip, GaugeCard, JourneyCard, OrdersCard, SalesChart, VisitsCard } from '../components/croOverview';
import { Icon } from '../components/Icon';
import { useToast } from '../components/overlays';
import { Button, Card, Field, LoadingBlock, PageHead, Paged, Pill, Skeleton, Tabs } from '../components/ui';

const RANGE_TABS = ['overview', 'conversion', 'checkout', 'products', 'sales'];

export default function Cro() {
    const [sp, setSp] = useSearchParams();
    const globalBrand = useBrandParam();
    const brand = globalBrand ?? (STORES.some((s) => s.key === sp.get('store')) ? sp.get('store') : 'ridhi');
    const tab = TABS.some((t) => t.key === sp.get('tab')) ? sp.get('tab') : 'overview';
    const [rev, setRev] = useState(0);
    const [syncing, setSyncing] = useState(false);
    const toast = useToast();
    // The store's own "today" (Shopify's timezone for the store) decides what "Yesterday" or "This month" means.
    const settings = useApi(`/cro/settings${qs({ brand })}`);
    const today = settings.data ? todayIn(settings.data.timezone) : null;
    const update = (patch) => {
        const next = new URLSearchParams(sp);
        for (const [k, v] of Object.entries(patch)) {
            if (v === null || v === '' || v === undefined) next.delete(k);
            else next.set(k, v);
        }
        setSp(next, { replace: true });
    };
    const r = sp.get('r') === 'custom' || RANGE_PRESETS.some((p) => p.key === sp.get('r')) ? sp.get('r') : 'yesterday';
    let range = null;
    if (today) {
        const fixed = r === 'custom' && /^\d{4}-\d{2}-\d{2}$/.test(sp.get('from') ?? '') && /^\d{4}-\d{2}-\d{2}$/.test(sp.get('to') ?? '')
            ? { from: sp.get('from'), to: sp.get('to') } : presetRange(r, today);
        const cmp = sp.get('cmp') || (rangeDays(fixed.from, fixed.to) === 1 ? (fixed.to < today ? '4week_avg' : 'last_week') : 'previous');
        range = { r: r === 'custom' && !sp.get('from') ? 'yesterday' : r, ...fixed, cmp: effectiveCompare(cmp, fixed.from, fixed.to) };
    }
    const setRange = (patch) => {
        if (patch.r && patch.r !== 'custom') update({ r: patch.r === 'yesterday' ? null : patch.r, from: null, to: null, cmp: null });
        else update({ ...patch, r: patch.r ?? sp.get('r') });
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
    const rq = range ? { brand, from: range.from, to: range.to, compare: range.cmp } : null;
    return (<>
      <PageHead title="Conversion (CRO)" sub="How visitors become orders, and what to do next."
        actions={<>
          {globalBrand ? null : <Seg label="Store" size="" options={STORES} value={brand} onChange={(s) => update({ store: s === 'ridhi' ? null : s })}/>}
          <Button icon="refresh" loading={syncing} onClick={syncNow} title="Read the latest orders for this store from Shopify now (it also runs every 15 minutes)">Sync now</Button>
        </>}/>
      <Tabs value={tab} onChange={(t) => update({ tab: t === 'overview' ? null : t })} tabs={TABS}/>
      <div className="mt-16 col" style={{ gap: 16 }} key={`${brand}-${rev}`}>
        {RANGE_TABS.includes(tab) ? (settings.error ? <ExplainedError error={settings.error} onRetry={settings.reload}/>
            : range ? <RangeBar value={range} today={today} onChange={setRange}/> : <LoadingBlock rows={1}/>) : null}
        {RANGE_TABS.includes(tab) && !rq ? null
            : tab === 'conversion' ? <ConversionTab rq={rq}/>
                : tab === 'checkout' ? <CheckoutTab rq={rq}/>
                    : tab === 'products' ? <ProductsTab rq={rq}/>
                        : tab === 'sales' ? <SalesTab rq={rq}/>
                            : tab === 'recommendations' ? <RecommendationsTab brand={brand}/>
                                : tab === 'alarms' ? <AlarmsTab brand={brand}/>
                                    : tab === 'changes' ? <ChangeLogTab brand={brand}/>
                                        : <OverviewTab key={qs(rq)} rq={rq} today={today} onTab={(t) => update({ tab: t })} onPickDay={(day) => setRange({ r: 'custom', from: day, to: day })}/>}
      </div>
    </>);
}

/** The trend chart needs at least two weeks of points: a short range is shown inside the 14 days ending on its last day. */
function trendRange(rq) {
    const n = rangeDays(rq.from, rq.to);
    return n >= 7 ? rq : { ...rq, from: shiftDay(rq.to, -13), compare: 'previous' };
}

/* ------------------------------------------------------------------ Overview */
/** How a plan's impact (Claude) or a rule's priority shows as a calendar-lane chip. */
const IMPACT_LANE = { High: 'lane-live', Medium: 'lane-research', Low: 'plain' };
const PRIORITY_LANE = { High: 'lane-due', Medium: 'lane-event', Low: 'plain' };

/**
 * Overview (design A2): the last 14 days as calendar tiles, then orders, conversion and visits side by side, the
 * sales chart, the shopper journey, the next actions and the monthly goal. The strip always shows the store's latest
 * 14 days; the gauge's bands, the orders blocks and the chart read the 28 days ending on the last chosen day (and the
 * 28 before, for the chart's comparison).
 *
 * The page appears all at once: one placeholder until every request has answered (or failed, which then shows in
 * its own card), rather than cards arriving one by one. It is keyed by the range, so a new range waits the same way;
 * answers already remembered in this tab show at once.
 */
function OverviewTab({ rq, today, onTab, onPickDay }) {
    const q = useApi(`/cro/overview${qs(rq)}`);
    const conv = useApi(`/cro/conversion${qs(rq)}`);
    const from28 = shiftDay(rq.to, -27);
    const conv28 = useApi(`/cro/conversion${qs({ brand: rq.brand, from: from28, to: rq.to, compare: 'previous' })}`);
    const trend = useApi(`/cro/sales-trend${qs({ brand: rq.brand, from: from28, to: rq.to, compare: 'previous' })}`);
    const cal = useApi(`/calendar${qs({ brand: rq.brand, from: shiftDay(rq.to, -55), to: rq.to })}`);
    const recs = useApi(`/cro/recommendations${qs({ brand: rq.brand })}`);
    const changes = useApi(`/cro/change-log${qs({ brand: rq.brand, days: 63 })}`);
    const advice = useApi(`/cro/ai-advice${qs({ brand: rq.brand })}`);
    const actions = advice.data?.advice?.actions?.length
        ? advice.data.advice.actions.slice(0, 3).map((a) => ({ title: a.title, why: a.evidence ? factsOf(a.evidence)[0] : firstSentence(a.why),
            tags: [{ label: `${a.impact} impact`, lane: IMPACT_LANE[a.impact] ?? 'plain' }, ...(ADVICE_AREA[a.area] ? [{ label: ADVICE_AREA[a.area], lane: 'lane-research' }] : [])] }))
        : (recs.data?.recommendations ?? []).slice(0, 3).map((r) => ({ title: r.title, why: r.evidence, tags: [{ label: r.priority, lane: PRIORITY_LANE[r.priority] ?? 'plain' }] }));
    const planKey = advice.data?.advice?.actions?.length ? `ai-${advice.data.generated_at}` : `rules-${rq.brand}-${actions.map((a) => a.title).join('|').length}`;
    // The strip always shows the store's latest 14 days (today included), so it stays put when a day is picked from it.
    const stripRq = { brand: rq.brand, from: shiftDay(today, -13), to: today, compare: 'none' };
    const stripSales = useApi(`/cro/sales-trend${qs(stripRq)}`);
    const stripConv = useApi(`/cro/conversion${qs(stripRq)}`);
    const history = conv28.data?.trend ?? [];
    const cvrByDate = new Map([...(stripConv.data?.trend ?? []), ...history].map((r) => [r.date, r.conversion_rate]));
    const stripDays = (stripSales.data?.current ?? []).map((r) => ({ date: r.date, orders: r.orders, cvr: cvrByDate.get(r.date) ?? null }));
    const days = (trend.data?.current ?? []).map((r) => ({ date: r.date, orders: r.orders, cvr: cvrByDate.get(r.date) ?? null }));
    // Calendar events (built-in ones apply to every store) shade the sales chart. No events is fine: the chart just has no bands.
    const events = (cal.data?.events ?? []).filter((e) => !e.brand_id || e.brand_id === rq.brand).map((e) => ({ date: e.date, name: e.name }));
    const month = presetRange('this_month', today);
    const mtd = useApi(`/cro/overview${qs({ brand: rq.brand, from: month.from, to: month.to, compare: 'previous' })}`);
    const goal = useApi(`/cro/goal${qs({ brand: rq.brand })}`, { remember: false });
    const all = [q, conv, conv28, trend, cal, recs, changes, advice, stripSales, stripConv, mtd, goal];
    if (!all.every((x) => x.data !== null || x.error || !x.loading))
        return <OverviewLoading/>;
    return (<div className="col" style={{ gap: 18 }}>
      <CroGate query={q}>
        {(d) => {
            const value = d.metrics.conversion_rate?.value ?? null;
            const scale = conversionScale(history.map((r) => r.conversion_rate), value);
            return (<>
              <DayStrip days={stripDays} from={rq.from} to={rq.to} scale={scale} onPick={onPickDay}/>
              <div className="muted small">{d.period_label} · {d.timezone} time{d.health.last_order_at ? ` · last order ${timeAgo(d.health.last_order_at)}` : ''}</div>
              <div className="ov-trio">
                <OrdersCard block={d.metrics.orders} days={days}/>
                <GaugeCard value={value} scale={scale} single={rq.from === rq.to} revenue={d.metrics.revenue} aov={d.metrics.aov}/>
                <VisitsCard trend={history} total={conv.data?.total} baseTotal={conv.data?.baseline_total} scale={scale}/>
              </div>
              {d.cvr_error ? <ExplainedError error={{ code: d.cvr_error.state, message: d.cvr_error.message }}/> : null}
            </>);
        }}
      </CroGate>
      <CroGate query={trend}>
        {(x) => <SalesChart current={x.current} previous={x.previous} events={events} changes={changes.data?.entries ?? []} lastDay={rq.to}/>}
      </CroGate>
      <div className="ov-two">
        <JourneyCard t={conv.data?.total}/>
        <Card title="What to do next" sub={advice.data?.advice ? `Claude's plan · ${timeAgo(advice.data.generated_at)}` : 'From the rule-based checks'}
          actions={<Button size="sm" variant="ghost" onClick={() => onTab('recommendations')}>See all</Button>}>
          {actions.length ? <ActionList actions={actions} storeKey={`cro-done:${rq.brand}:${planKey}`}/>
              : <div className="muted small">Nothing stands out in the current figures.</div>}
        </Card>
      </div>
      <Card title="Monthly goal" sub="This month's revenue against the goal you set, with today's pace."><GoalBar brand={rq.brand} today={today} mtd={mtd} g={goal}/></Card>
    </div>);
}

/** The Overview's one placeholder, shaped like the page: the strip, three cards and the chart. */
function OverviewLoading() {
    return (<div className="col" style={{ gap: 18 }} aria-busy="true" aria-label="Loading the overview">
      <Skeleton h={88} r={12}/>
      <div className="ov-trio"><Skeleton h={300} r={16}/><Skeleton h={420} r={22}/><Skeleton h={300} r={16}/></div>
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

/** The next actions as a list to tick off. What is ticked is remembered in this browser for this plan only. */
function ActionList({ actions, storeKey }) {
    const read = () => { try { return JSON.parse(window.localStorage.getItem(storeKey) || '[]'); } catch { return []; } };
    const [done, setDone] = useState([]);
    useEffect(() => { setDone(read()); }, [storeKey]); // eslint-disable-line react-hooks/exhaustive-deps
    const toggle = (i) => {
        const next = done.includes(i) ? done.filter((x) => x !== i) : [...done, i];
        setDone(next);
        try { window.localStorage.setItem(storeKey, JSON.stringify(next)); } catch { /* private window: not remembered */ }
    };
    return (<div className="todo-list stagger">
      {actions.map((a, i) => (<div key={i} className={`todo-row${done.includes(i) ? ' done' : ''}`}>
        <button type="button" className="todo-check" onClick={() => toggle(i)} aria-pressed={done.includes(i)} aria-label={done.includes(i) ? 'Mark as not done' : 'Mark as done'}><Icon name="check" size="sm"/></button>
        <div style={{ minWidth: 0 }}>
          <div className="strong todo-title">{a.title}</div>
          {a.why ? <div className="muted small">{a.why}</div> : null}
          {a.tags?.length ? <div className="row mt-4" style={{ gap: 6 }}>{a.tags.map((t) => <span key={t.label} className={`lane-chip ${t.lane}`}>{t.label}</span>)}</div> : null}
        </div>
      </div>))}
      {done.length && done.length === actions.length ? <div className="todo-cheer">All {actions.length} done. Check the figures again in a week to see the effect.</div> : null}
    </div>);
}

/* ------------------------------------------------------------------ Conversion */
function ConversionTab({ rq }) {
    const q = useApi(`/cro/conversion${qs(rq)}`);
    const bench = useApi('/cro/benchmarks');
    return (<CroGate query={q}>
      {(d) => {
          const t = d.total;
          const b = d.baseline_total;
          if (!d.trend.length) return <CroEmpty icon="calendar" title="No complete day in this range">Shopify reports sessions for complete days only. Pick a range that ends yesterday or earlier.</CroEmpty>;
          return (<>
            <div className="kpis">
              <div className="kpi"><div className="kpi-label">Conversion rate</div><div className="kpi-value">{pct(t.conversion_rate)}</div>
                <div className="kpi-foot">{b ? <><span className={`delta ${d.conversion_change_pct > 0 ? 'up' : d.conversion_change_pct < 0 ? 'down' : 'flat'}`}>{signedPct(d.conversion_change_pct)}</span> <span className="muted">{d.baseline_label} ({pct(b.conversion_rate)})</span></> : <span className="muted">{d.baseline_label}</span>}</div></div>
              <div className="kpi"><div className="kpi-label">Sessions</div><div className="kpi-value">{fmtInt(t.sessions)}</div><div className="kpi-foot muted">{b ? `Comparison: ${fmtInt(b.sessions)}` : ''}</div></div>
              <div className="kpi"><div className="kpi-label">Added to cart</div><div className="kpi-value">{pct(t.cart_rate, 1)}</div><div className="kpi-foot muted">of sessions{b ? ` · comparison ${pct(b.cart_rate, 1)}` : ''}</div></div>
              <div className="kpi"><div className="kpi-label">Reached checkout</div><div className="kpi-value">{pct(t.checkout_rate, 1)}</div><div className="kpi-foot muted">of sessions{b ? ` · comparison ${pct(b.checkout_rate, 1)}` : ''}</div></div>
            </div>
            {d.today_left_out ? <div className="muted small">Today is left out: Shopify reports sessions for complete days only.</div> : null}
            <div className="grid cols-2">
              <Card title="Conversion rate by day" sub="Completed checkouts ÷ sessions, store time.">
                <LineChart ariaLabel="Conversion rate by day" height={200} yFormat={(v) => pct(v, 1)} area extremes="high"
                  refLine={bench.data?.benchmarks?.conversion_rate ? { y: bench.data.benchmarks.conversion_rate.value, label: `Typical ${bench.data.benchmarks.conversion_rate.value}%` } : undefined}
                  series={[seriesOf(d.trend, 'conversion_rate', 'cvr', 'Conversion rate', 'var(--info)')]}/>
              </Card>
              <Card title="Sessions by day">
                <LineChart ariaLabel="Sessions by day" height={200} yFormat={fmtInt} area extremes="high" series={[seriesOf(d.trend, 'sessions', 'sessions', 'Sessions', 'var(--ok)')]}/>
              </Card>
            </div>
            <Card title="Funnel for the chosen days" sub="Sessions that reached each step.">
              <BarList format={fmtInt} rows={[
                  { key: 's', label: 'Sessions', value: t.sessions },
                  { key: 'c', label: 'Added to cart', value: t.added_to_cart, extra: pct(t.cart_rate, 1) },
                  { key: 'k', label: 'Reached checkout', value: t.reached_checkout, extra: pct(t.checkout_rate, 1) },
                  { key: 'p', label: 'Purchased', value: t.completed_checkout, extra: pct(t.conversion_rate) },
              ]}/>
            </Card>
            <Card title="Day by day" flush>
              <Paged rows={[...d.trend].reverse()} size={7}>
                {(rows) => (<div className="table-wrap"><table className="t compact">
                  <thead><tr><th>Day</th><th className="r">Sessions</th><th className="r">Cart</th><th className="r hide-sm">Checkout</th><th className="r">Orders</th><th className="r">Conversion</th></tr></thead>
                  <tbody>{rows.map((r) => (<tr key={r.date}><td>{fmtDate(r.date)}</td><td className="r">{fmtInt(r.sessions)}</td><td className="r">{pct(r.cart_rate, 1)}</td>
                    <td className="r hide-sm">{pct(r.checkout_rate, 1)}</td><td className="r">{fmtInt(r.completed_checkout)}</td><td className="r"><b>{pct(r.conversion_rate)}</b></td></tr>))}</tbody>
                </table></div>)}
              </Paged>
            </Card>
          </>);
      }}
    </CroGate>);
}

/* ------------------------------------------------------------------ Cart & checkout */
function CheckoutTab({ rq }) {
    const tr = trendRange(rq);
    const q = useApi(`/cro/conversion${qs(tr)}`);
    const bench = useApi('/cro/benchmarks');
    const b = bench.data?.benchmarks;
    return (<div className="col" style={{ gap: 16 }}>
      <CroGate query={q}>
        {(d) => (<>
          <CheckoutHealth d={d} b={b} rq={rq}/>
          <div className="grid cols-2">
          <Card title="Cart abandonment by day" sub={b ? `Reference: ${b.cart_abandonment_rate.value}% (${b.cart_abandonment_rate.source})` : 'Carts that did not end in a purchase.'}>
            <LineChart ariaLabel="Cart abandonment by day" height={200} yFormat={(v) => pct(v, 0)} area extremes="low"
              refLine={b ? { y: b.cart_abandonment_rate.value, label: `Typical ${b.cart_abandonment_rate.value}%` } : undefined}
              series={[seriesOf(d.trend, 'cart_abandonment_rate', 'cart', 'Cart abandonment', 'var(--info)')]}/>
          </Card>
          <Card title="Checkout abandonment by day" sub={b ? `Reference: ${b.checkout_abandonment_rate.value}% (${b.checkout_abandonment_rate.source})` : 'Checkouts that did not end in a purchase.'}>
            <LineChart ariaLabel="Checkout abandonment by day" height={200} yFormat={(v) => pct(v, 0)} area extremes="low"
              refLine={b ? { y: b.checkout_abandonment_rate.value, label: `Typical ${b.checkout_abandonment_rate.value}%` } : undefined}
              series={[seriesOf(d.trend, 'checkout_abandonment_rate', 'checkout', 'Checkout abandonment', 'var(--cpc)')]}/>
          </Card>
          </div>
        </>)}
      </CroGate>
      <div className="grid cols-2">
        <SegmentCard rq={rq} dimension="device" title="By device"/>
        <SegmentCard rq={rq} dimension="channel" title="By channel"/>
      </div>
    </div>);
}

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

/* ------------------------------------------------------------------ Products */
function ProductsTab({ rq }) {
    const q = useApi(`/cro/products${qs(rq)}`);
    return (<CroGate query={q}>
      {(d) => (d.products.length ? (<>
      <ProductMix products={d.products}/>
      <Card title={`Products sold: ${d.period_label}`} sub="Revenue is units × the item's price before discounts. Top / Low are the best and worst thirds by revenue; cancelled orders are left out." flush>
        <Paged rows={d.products} resetKey={`${rq.from}-${rq.to}`}>
          {(rows) => (<div className="table-wrap"><table className="t compact">
            <thead><tr><th>Product</th><th className="hide-sm">Type</th><th className="r">Units</th><th className="r hide-sm">Orders</th><th className="r">Revenue</th><th>Group</th></tr></thead>
            <tbody>{rows.map((p) => (<tr key={`${p.product_id}-${p.name}`}><td>{p.name}</td><td className="hide-sm muted">{p.product_type || '—'}</td>
              <td className="r">{fmtInt(p.quantity)}</td><td className="r hide-sm">{fmtInt(p.orders)}</td><td className="r"><b>{money(p.revenue)}</b></td>
              <td><Pill tone={PERFORMANCE[p.performance_status]?.tone}>{PERFORMANCE[p.performance_status]?.label ?? p.performance_status}</Pill></td></tr>))}</tbody>
          </table></div>)}
        </Paged>
      </Card></>) : <CroEmpty title="No products sold in these days"/>)}
    </CroGate>);
}

/** Where the revenue comes from: a ring of the top / middle / low thirds, and the best sellers as bars. */
function ProductMix({ products }) {
    const sum = (k) => products.filter((p) => p.performance_status === k).reduce((n, p) => n + (p.revenue || 0), 0);
    const total = products.reduce((n, p) => n + (p.revenue || 0), 0);
    const segments = [
        { key: 'top', name: 'Top third', value: Math.round(sum('top')), color: 'var(--ok)' },
        { key: 'average', name: 'Middle third', value: Math.round(sum('average')), color: 'var(--info)' },
        { key: 'low', name: 'Low third', value: Math.round(sum('low')), color: 'var(--warn)' },
    ];
    const best = [...products].sort((a, b) => (b.revenue || 0) - (a.revenue || 0)).slice(0, 6);
    return (<div className="ov-hero">
      <RingCard label="Revenue by product group" total={money(total, 'USD', 0)} centerLabel="revenue" segments={segments}
        pill={{ tone: 'info', label: `${fmtInt(products.length)} products` }}/>
      <Card title="Best sellers" sub="Revenue in the chosen days.">
        <BarList format={(v) => money(v, 'USD', 0)} rows={best.map((p) => ({ key: `${p.product_id}-${p.name}`, label: p.name, value: p.revenue || 0, extra: `${fmtInt(p.quantity)} sold` }))}/>
      </Card>
    </div>);
}

/* ------------------------------------------------------------------ Sales */
function SalesTab({ rq }) {
    const q = useApi(`/cro/sales-breakdown${qs(rq)}`);
    const health = useApi(`/cro/order-health${qs(rq)}`);
    return (<div className="grid cols-2">
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
    </div>);
}

/* ------------------------------------------------------------------ Recommendations */
function RecRow({ r, compact }) {
    return (<div className={compact ? '' : 'card'} style={compact ? undefined : { padding: 16 }}>
      <div className="row" style={{ alignItems: 'baseline' }}>
        <Pill tone={PRIORITY_TONE[r.priority]}>{r.priority}</Pill>
        <b>{r.title}</b>
      </div>
      {compact ? <div className="muted small">{r.evidence}</div> : (<>
        <p className="small" style={{ margin: '8px 0' }}>{r.explanation}</p>
        <div className="small"><span className="muted">Evidence:</span> {r.evidence}</div>
        <div className="small"><span className="muted">Suggested:</span> {r.suggested_action}</div>
      </>)}
    </div>);
}

/** Splits "a; b. C" into short facts: on semicolons, and on full stops that end a sentence (not 1.35%). */
const factsOf = (text) => String(text || '').split(/;\s+|\.\s+(?=[A-Z])/).map((x) => x.trim().replace(/\.$/, '')).filter(Boolean).slice(0, 5);
/** The first sentence only: the reason in one line. */
const firstSentence = (text) => (String(text || '').match(/^.*?[.!?](?=\s+[A-Z]|$)/)?.[0] ?? String(text || '')).trim();

/**
 * One action from Claude's plan, laid out to be read at a glance: its number and what to do as the heading, impact and
 * effort as tags, then "What to do" (numbered steps) beside "Why" (one line) and "The numbers" (short bullets).
 * `compact` is the one-line form on the Overview.
 */
function ActionRow({ a, n, compact }) {
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
    const facts = factsOf(a.evidence);
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
      <footer className="act-foot">{ADVICE_AREA[a.area] ?? a.area}{a.metric ? <> · improves <b>{a.metric.replace(/\s*\(.*$/, '')}</b></> : null}</footer>
    </article>);
}

/**
 * Claude's action plan for the store. Opening the tab asks for today's plan once (within the shared daily Claude limit);
 * "Refresh" asks again. While Claude works, the state is read every 4 seconds.
 */
function AiAdvice({ brand }) {
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
    const sub = plan ? `${plan.actions.length} actions from the last 30 days · ${timeAgo(data.generated_at)}` : 'Claude reads the last 30 days of this store\'s figures and says what to do next.';
    return (<Card className="advice-plan" title={<span className="row" style={{ gap: 8 }}><Icon name="sparkle"/>Claude&rsquo;s action plan</span>} sub={sub}
      actions={data.configured ? <Button size="sm" icon="refresh" loading={running} onClick={() => ask(false)} title={`Ask Claude again (about $${Number(data.estimate_usd ?? 0.3).toFixed(2)} of today's Claude limit)`}>{running ? 'Claude is reading…' : 'Refresh'}</Button> : null}>
      {!data.configured ? <div className="callout info"><Icon name="info"/><div>Set <b>ANTHROPIC_API_KEY</b> on the server (the same key SEO &amp; Blog uses) to get Claude&rsquo;s plan here.</div></div> : null}
      {data.error ? <div className="callout warn mb-12"><Icon name="alert"/><div>The last request did not finish: {data.error}</div></div> : null}
      {running && !plan ? (<div className="advice-wait"><Icon name="loader" className="spin"/><span>Claude is reading the store&rsquo;s figures. This takes about a minute.</span></div>) : null}
      {plan ? (<div className="col" style={{ gap: 12 }}>
          <div className="act-list stagger">{plan.actions.map((a, i) => <ActionRow key={`${a.title}-${i}`} a={a} n={i + 1}/>)}</div>
          {data.not_available?.length ? <div className="muted xs">Claude could not see: {data.not_available.join('; ')}.</div> : null}
        </div>) : null}
      {data.budget ? <div className="muted xs mt-8">Claude today: ${Number(data.budget.todayUsd ?? 0).toFixed(2)} of ${Number(data.budget.dailyLimitUsd ?? 0).toFixed(2)} used, shared with SEO &amp; Blog.</div> : null}
    </Card>);
}

function RecommendationsTab({ brand }) {
    const q = useApi(`/cro/recommendations${qs({ brand })}`);
    return (<div className="col" style={{ gap: 16 }}>
    <AiAdvice brand={brand}/>
    <div className="sec-mini">Rule-based checks</div>
    <CroGate query={q}>
      {(d) => (<>
        {d.recommendations.length
            ? <Paged rows={d.recommendations} size={8}>{(rows) => <div className="col gap-12">{rows.map((r, i) => <RecRow key={`${r.title}-${i}`} r={r}/>)}</div>}</Paged>
            : <CroEmpty icon="checkCircle" title="Nothing stands out">Recommendations only appear when the store's own figures support them.</CroEmpty>}
        {d.skipped.length ? <div className="muted small">Not checked: {d.skipped.join('; ')}.</div> : null}
      </>)}
    </CroGate>
    </div>);
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

