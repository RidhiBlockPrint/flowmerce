'use client';
import { useEffect, useState } from 'react';
import { More } from '../components/More';
import { api } from '../lib/api';
import { useSearchParams } from '../lib/nav';
import { tabLabel } from '../lib/routes.mjs';
import { useApi, qs, download } from '../lib/api';
import { useBrandParam } from '../lib/app';
import { fmtDateTime, fmtInt, timeAgo } from '../lib/format';
import { AGE_FILTERS, CAT, CHIPS, SORTS, ageSegments, dayText, fmtMoney } from '../lib/shipping';
import { Button, Card, Empty, ErrorState, LoadingBlock, PAGE_SIZE, PageHead, Paged, Pill } from '../components/ui';
import { useToast } from '../components/overlays';
import { Icon } from '../components/Icon';
import { BarList, LineChart } from '../components/charts';
import { Journey, MiniGrid, MiniStat, RingCard, SectionHead } from '../components/dash';
import { ImportPreview, OrderDrawer, ShipmentsTable, ShopifyOrderLink, SourceGate, Tile } from '../components/shipping';

/* The sections of the page. No tab bar: the sidebar's Shipping menu opens them (?tab=); the title names the open one. */
const TABS = [
    { key: 'overview', label: 'Overview' },
    { key: 'shipments', label: 'Shipments' },
    { key: 'checks', label: 'Hand checks' },
    // Read now and then, not every day: in the sidebar's Advanced group.
    { key: 'analytics', label: 'Analytics', advanced: true },
];

export default function Shipping() {
    const [sp, setSp] = useSearchParams();
    const tab = TABS.some((t) => t.key === sp.get('tab')) ? sp.get('tab') : 'overview';
    const brand = useBrandParam();
    const [open, setOpen] = useState(null);
    const [rev, setRev] = useState(0);
    const [refreshing, setRefreshing] = useState(false);
    const toast = useToast();
    const refresh = async () => {
        setRefreshing(true);
        try {
            const r = await api.post('/shipping/refresh');
            const x = r.result || {};
            const failed = (r.shopify || []).filter((s) => s.state === 'failed').map((s) => s.store);
            toast.ok(`Refreshed: ${fmtInt(x.tracking_changed ?? 0)} tracking changes, ${fmtInt(x.new_scans ?? 0)} new scans.${failed.length ? ` Shopify could not be read for ${failed.join(', ')}.` : ''}`);
            setRev((n) => n + 1);
        }
        catch (e) {
            toast.error(e);
        }
        finally {
            setRefreshing(false);
        }
    };
    const update = (patch) => {
        const next = new URLSearchParams(sp);
        for (const [k, v] of Object.entries(patch)) {
            if (v === null || v === '')
                next.delete(k);
            else
                next.set(k, v);
        }
        setSp(next, { replace: true });
    };
    return (<>
      <PageHead title={tab === 'overview' ? 'Shipping' : tabLabel('/shipping', tab)} crumbs={tab === 'overview' ? null : 'Shipping'}
        actions={<Button icon="refresh" loading={refreshing} onClick={refresh} title="Read the latest changes from Shopify into Flowmerce now">Refresh now</Button>}/>
      <div className="mt-16" key={rev}>
        {tab === 'shipments' ? <ShipmentsTab brand={brand} sp={sp} update={update} onOpen={setOpen}/>
            : tab === 'analytics' ? <AnalyticsTab brand={brand} update={update}/>
                : tab === 'checks' ? <ChecksTab brand={brand} onOpen={setOpen}/>
                    : <OverviewTab brand={brand} update={update} onOpen={setOpen} onChanged={() => setRev((n) => n + 1)}/>}
      </div>
      {open ? <OrderDrawer order={open} brand={brand} onClose={() => setOpen(null)}/> : null}
    </>);
}

/* ------------------------------------------------------------------ Overview */
function OverviewTab({ brand, update, onOpen, onChanged }) {
    const q = useApi(`/shipping/summary${qs({ brand })}`);
    const ck = useApi(`/shipping/checks${qs({ brand })}`);
    const an = useApi(`/shipping/analytics${qs({ brand, period: '30' })}`);
    const toast = useToast();
    return (<SourceGate query={q}>
      {(d) => (<>
          <div className="ov-hero">
            <AgeCard kpis={d.kpis} go={(cat) => update({ tab: 'shipments', cat: cat || null, page: null })}/>
            <HeadlineNumbers d={d} an={an.data} update={update}/>
          </div>
          <JourneyStrip steps={d.journey ?? []} update={update}/>
          <Triage query={ck} onOpen={onOpen} update={update}
            extra={d.critical ? <Button size="sm" icon="download" onClick={() => download(`/shipping/export/escalation${qs({ brand })}`).catch(toast.error)}
              title="Download the critical orders to send to the carriers">Escalation list (CSV)</Button> : null}/>
          <More id="ship-overview" label="Show hand checks and data source">
            <div className="grid cols-2">
              <Card title="Hand checks" sub="Orders a person has to look at, each in one list only">
                <div className="row-wrap">
                  <Pill tone="crit">{fmtInt(d.checks.tracking_missing ?? 0)} tracking missing</Pill>
                  <Pill tone="info">{fmtInt(d.checks.invalid ?? 0)} invalid tracking</Pill>
                  <Pill tone="warn">{fmtInt(d.checks.checks ?? 0)} fix in Shopify</Pill>
                </div>
                <div className="mt-8"><Button size="sm" onClick={() => update({ tab: 'checks' })}>Open hand checks</Button></div>
              </Card>
              <SyncCard source={d.source} onChanged={onChanged}/>
            </div>
          </More>
        </>)}
    </SourceGate>);
}

/** Active parcels by days in their current stage: the total in a ring of the bands, and a legend with each band's share. */
function AgeCard({ kpis, go }) {
    const { total, onTrack, segments } = ageSegments(kpis, go);
    return (<RingCard label="Active shipments" total={total} onTotal={() => go('')} pill={total ? { tone: 'ok', label: `${onTrack}% on track` } : null}
      segments={segments} centerLabel="active"/>);
}

const ON_TIME_GOAL = 90;
/* Chart colours are the dashboard theme (owner rule 2026-11-27, `--theme-*` in globals.css): green good, amber
   usual, salmon below; navy for the figure in focus, light blue for the rest. Text keeps the --ok / --warn / --crit inks. */
const TONE_FILL = { ok: 'var(--theme-good)', warn: 'var(--theme-usual)', crit: 'var(--theme-low)' };
const shortWeek = (iso) => new Date(`${iso}T12:00:00Z`).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', timeZone: 'UTC' });

/** Mini bar chart: rows [{ key, label, value }], tallest = full height; `lastColor` marks the latest row. */
function VizBars({ rows, color, lastColor, format = fmtInt }) {
    const max = Math.max(1, ...rows.map((r) => r.value || 0));
    return (<>
      <span className="viz-bars" role="img" aria-label={rows.map((r) => `${r.label}: ${format(r.value)}`).join(', ')}>
        {rows.map((r, i) => <span key={r.key} title={`${r.label}: ${format(r.value)}`}><i style={{ height: `${Math.max(((r.value || 0) / max) * 100, 4)}%`, background: lastColor && i === rows.length - 1 ? lastColor : color }}/></span>)}
      </span>
      <span className="viz-labels">{rows.map((r) => <span key={r.key}>{r.short ?? r.label}</span>)}</span>
    </>);
}

/** Four headline numbers beside the age card, each with a small picture from the 30-day analytics (`an`, may still
 *  be loading). Delivery figures cover parcels delivered in the last 30 days. */
function HeadlineNumbers({ d, an, update }) {
    const dl = d.delivery30 ?? {};
    const v = d.valueAtRisk;
    const risk = !v.available ? { value: '—', foot: 'Unavailable' } : v.orders === 0 ? { value: fmtMoney(0, v.currency), foot: 'No critical orders' }
        : v.total === null ? { value: '—', foot: v.note } : { value: fmtMoney(v.total, v.currency), foot: `${v.orders} critical order${v.orders === 1 ? '' : 's'}` };
    const has = (x) => x !== null && x !== undefined;
    const tone = !has(dl.onTimePct) ? undefined : dl.onTimePct >= 90 ? 'ok' : dl.onTimePct >= 75 ? 'warn' : 'crit';
    const toAnalytics = () => update({ tab: 'analytics' });
    const dist = an?.delivery?.distribution ?? [];
    const weeks = (an?.delivery?.trend ?? []).slice(-6);
    const critCarriers = (an?.carriers ?? []).filter((c) => c.critical).sort((a, b) => b.critical - a.critical);
    return (<MiniGrid>
      <MiniStat label="On-time delivery" value={has(dl.onTimePct) ? `${dl.onTimePct}%` : '—'} tone={tone}
        foot={dl.withPromisedDate ? `${fmtInt(dl.withPromisedDate)} of ${fmtInt(dl.delivered)} had a promised date` : 'No promised dates in 30 days'} onClick={toAnalytics}>
        {has(dl.onTimePct) ? (<>
            <span className="viz-meter" role="img" aria-label={`${dl.onTimePct}% on time; goal ${ON_TIME_GOAL}%`}>
              <span className="fill" style={{ width: `${dl.onTimePct}%`, background: TONE_FILL[tone ?? 'ok'] }}/>
              <span className="mark" style={{ left: `calc(${ON_TIME_GOAL}% - 1px)` }} title={`Goal ${ON_TIME_GOAL}%`}/>
            </span>
            <span className="viz-scale"><span>0%</span><span>Goal {ON_TIME_GOAL}%</span></span>
          </>) : null}
      </MiniStat>
      <MiniStat label="Average delivery time" value={has(dl.avgDays) ? `${dl.avgDays} d` : '—'} foot="Dispatch to delivery, 30 days" onClick={toAnalytics}>
        {dist.length ? <VizBars rows={dist.map((r) => ({ ...r, short: r.label.replace(/\s*days?$/, '').replace('-', '–') }))} color="var(--theme-primary-soft)"/> : null}
      </MiniStat>
      <MiniStat label="Value at risk" value={risk.value} tone={v.orders ? 'crit' : undefined} foot={risk.foot} onClick={() => update({ tab: 'shipments', cat: 'red', page: null })}>
        {an ? (<span className="viz-chips">
            {critCarriers.length ? critCarriers.slice(0, 4).map((c) => <span key={c.carrier} className="viz-chip crit">{c.carrier} {fmtInt(c.critical)}</span>)
                : <span className="viz-chip">No critical parcels</span>}
          </span>) : null}
      </MiniStat>
      <MiniStat label="Delivered" value={fmtInt(dl.delivered ?? 0)} foot="Last 30 days, by week" onClick={toAnalytics}>
        {weeks.length ? <VizBars rows={weeks.map((w) => ({ key: w.week, label: `Week of ${shortWeek(w.week)}`, short: shortWeek(w.week), value: w.delivered }))} color="var(--theme-primary-soft)" lastColor="var(--theme-primary)"/> : null}
      </MiniStat>
    </MiniGrid>);
}

/* Where each journey step leads. Steps without an exact list (no scan yet, delivered) are not links. */
const STEP_LINK = { in_transit: { tab: 'shipments', status: 'in_transit' }, out_for_delivery: { tab: 'shipments', status: 'out_for_delivery' } };

/** Sent → in transit → out for delivery → delivered, with the sections sitting in each step. */
function JourneyStrip({ steps, update }) {
    const go = (patch) => update({ cat: null, status: null, page: null, ...patch });
    return (<Journey label="Where orders are now" steps={steps.map((s) => ({
        key: s.key, label: s.label, value: s.value, done: s.key === 'delivered',
        calm: s.key === 'delivered' ? 'Left the active list' : 'Nothing stuck',
        onClick: STEP_LINK[s.key] ? () => go(STEP_LINK[s.key]) : undefined,
        flags: s.flags.map((f) => {
            const fl = f.cat ? { tab: 'shipments', cat: f.cat } : null;
            return { ...f, onClick: fl ? () => go(fl) : undefined };
        }),
    }))}/>);
}

/* The one-click next step for each kind of problem. Shopify fixes open the order in Shopify admin; the rest open the drawer. */
const NEXT_STEP = {
    missing_tracking: { label: 'Add tracking', shopify: true },
    invalid_tracking: { label: 'Check number' },
    amazon_not_in_shopify: { label: 'Mark fulfilled', shopify: true },
    amazon_tracking_missing: { label: 'Add tracking', shopify: true },
    duplicate_tracking: { label: 'Fix tracking', shopify: true },
};

/** Today's hand checks, most urgent first, each with its next step. The full list lives on the Hand checks tab. `extra`
 *  is a further action for the heading (the escalation list download). */
function Triage({ query, onOpen, update, extra }) {
    const [kind, setKind] = useState('');
    const head = <SectionHead title="Today’s triage" note="Most urgent first. Each row has its next step; open an order for its full tracking."
      action={<span className="row-wrap">{extra}<Button size="sm" onClick={() => update({ tab: 'checks' })}>All hand checks</Button></span>}/>;
    if (query.error)
        return <>{head}<Card><ErrorState error={query.error} onRetry={query.reload}/></Card></>;
    if (!query.data)
        return <>{head}<Card><LoadingBlock rows={4}/></Card></>;
    const ex = query.data.exceptions;
    const types = ex.types.filter((t) => ex.counts[t.key]);
    const shown = ex.rows.filter((r) => !kind || (r.types || [r.type]).includes(kind));
    return (<>
      {head}
      <div className="chips" role="group" aria-label="Filter by problem">
        <button className="chip" aria-pressed={kind === ''} onClick={() => setKind('')}>All <span className="chip-n">{ex.total}</span></button>
        {types.map((t) => <button key={t.key} className="chip" aria-pressed={kind === t.key} onClick={() => setKind(t.key)}>{t.label} <span className="chip-n">{ex.counts[t.key]}</span></button>)}
      </div>
      <Card flush className="triage">
        {!shown.length ? <Empty icon="checkCircle" title="Nothing to review">No open problems of this kind.</Empty> : (
            <Paged rows={shown} size={8} resetKey={kind}>{(page) => (<div className="triage-list">
              {page.map((r) => <TriageRow key={`${r.brand}|${r.order}`} r={r} onOpen={onOpen}/>)}
            </div>)}</Paged>)}
      </Card>
    </>);
}

function TriageRow({ r, onOpen }) {
    const issues = r.issues || [r];
    const tags = [...new Map(issues.map((i) => [i.type, i])).values()];
    const step = NEXT_STEP[r.type] ?? { label: 'Review' };
    const days = r.days ?? null;
    const tone = r.severity === 'high' ? 'crit' : 'warn';
    return (<div className="triage-row">
      <span className={`triage-age tone-${tone}`} title={days === null ? 'No day count' : `${days} days since the last update`}>{days === null ? '—' : `${days}d`}</span>
      <div className="triage-order">
        <button type="button" className="triage-num" onClick={() => onOpen(r.order)} title="Open this order">{r.order}</button>
        <span className="triage-meta">{r.carrier}{r.brand ? ` · ${r.brand === 'ridhi' ? 'Ridhi' : r.brand === 'cpc' ? 'CPC' : r.brand}` : ''}</span>
      </div>
      <div className="triage-why">
        <span className="triage-detail">{issues[0].detail}</span>
        {issues.length > 1 ? <span className="triage-more">{issues.slice(1).map((i) => i.detail).join(' ')}</span> : null}
      </div>
      <div className="triage-tags">{tags.slice(0, 2).map((i) => <Pill key={i.type} tone={i.severity === 'high' ? 'crit' : 'warn'}>{i.label}</Pill>)}</div>
      <div className="triage-acts">
        {step.shopify && r.shopifyUrl ? (<>
            <Button size="sm" variant="ghost" onClick={() => onOpen(r.order)}>Open</Button>
            <a className="btn sm dark" href={r.shopifyUrl} target="_blank" rel="noreferrer" title="Opens the order in Shopify admin">{step.label} <Icon name="external" size="sm"/></a>
          </>) : <button type="button" className="btn sm dark" onClick={() => onOpen(r.order)}>{step.label}</button>}
      </div>
    </div>);
}

const STORE_NAME = { RBP: 'Ridhi', CPC: 'CPC' };

function SyncCard({ source, onChanged }) {
    const f = source.freshness ?? {};
    return (<Card title="Data source" sub="Shopify, read by Flowmerce and merged in Supabase">
      <div className="small">Last merge: {f.lastChecked ? `${timeAgo(f.lastChecked)} (${fmtDateTime(f.lastChecked)})` : 'not recorded'}. Refreshes every 15 minutes; Refresh now does it at once.</div>
      {f.stores?.length ? (<ul className="small" style={{ margin: '8px 0 0', paddingLeft: 18 }}>
          {f.stores.map((s) => (<li key={s.store}>{STORE_NAME[s.store] ?? s.store}: {s.status === 'failed' ? <span style={{ color: 'var(--crit)' }}>last read failed{s.error ? ` (${s.error})` : ''}</span> : s.lastOkAt ? `read ${timeAgo(s.lastOkAt)}` : 'not read yet'}</li>))}
        </ul>) : null}
      <AmazonSource a={source.amazonMcf} onChanged={onChanged}/>
      <div className="muted xs mt-8">Delivery dates come from Shopify's copy of the carrier tracking, or from Amazon for MCF parcels.</div>
    </Card>);
}

function AmazonSource({ a, onChanged }) {
    const toast = useToast();
    const [busy, setBusy] = useState(false);
    const s = a?.sync ?? {};
    const syncNow = async () => {
        setBusy(true);
        try {
            const r = await api.post('/shipping/amazon-mcf/sync');
            if (r.state === 'ok') {
                toast.ok(`Copied ${fmtInt(r.rows)} rows from the MCF sheet into Supabase.`);
                onChanged?.();
            }
            else
                toast.error(r.error || 'The MCF sheet could not be copied.');
        }
        catch (e) {
            toast.error(e);
        }
        finally {
            setBusy(false);
        }
    };
    const from = a?.source === 'sheet' ? 'MCF tracking sheet' : a?.source === 'amazon_api' ? 'Amazon API data' : 'sheet and Amazon API data';
    return (<div className="small mt-8">
      {a?.loaded
            ? <>Amazon MCF ({from}, in Supabase): {fmtInt(a.orders)} orders, {fmtInt(a.delivered)} packages delivered{a.lastLoaded ? `, Amazon last checked ${timeAgo(a.lastLoaded)}` : ''}.</>
            : <>Amazon MCF: <span style={{ color: 'var(--warn)' }}>no data in Supabase yet.</span> Amazon parcels show Shopify's information only.</>}
      <div className="mt-4">Sheet copy: {s.schedule ?? 'daily'}{s.lastOkAt ? `; last copied ${timeAgo(s.lastOkAt)} (${fmtDateTime(s.lastOkAt)})` : '; not copied yet'}{s.nextAt ? `; next ${fmtDateTime(s.nextAt)}` : ''}.</div>
      {a?.problem ? (<div className="mt-4" style={{ color: 'var(--crit)' }}>Last copy failed: {a.problem}
          {a.serviceAccount ? <> Share the sheet (Viewer) with <code className="xs">{a.serviceAccount}</code>.</> : null}</div>) : null}
      <div className="mt-8"><Button size="sm" icon="refresh" loading={busy} onClick={syncNow} title="Copy the MCF tracking sheet into Supabase now">Sync MCF sheet now</Button></div>
    </div>);
}

/* ------------------------------------------------------------------ Shipments */
const PAGE = PAGE_SIZE;

function ShipmentsTab({ brand, sp, update, onOpen }) {
    const cat = sp.get('cat') ?? '';
    const carrier = sp.get('carrier') ?? '';
    const status = sp.get('status') ?? '';
    const sort = sp.get('sort') ?? 'priority';
    const days = sp.get('days') ?? '';
    const page = Number(sp.get('page') ?? '0');
    const [text, setText] = useState(sp.get('q') ?? '');
    const toast = useToast();
    useEffect(() => {
        const t = setTimeout(() => update({ q: text || null, page: null }), 250);
        return () => clearTimeout(t);
    }, [text]); // eslint-disable-line react-hooks/exhaustive-deps
    const filters = { brand, cat, carrier, status, sort, days, q: sp.get('q') };
    const q = useApi(`/shipping/shipments${qs({ ...filters, page, size: PAGE })}`);
    return (<SourceGate query={q}>
      {(d) => (<>
          <div className="chips" role="group" aria-label="Quick filters">
            {CHIPS.map((c) => <button key={c.key || 'all'} className="chip" aria-pressed={cat === c.key} onClick={() => update({ cat: c.key || null, page: null })}>{c.label}</button>)}
            {cat && !CHIPS.some((c) => c.key === cat) ? <button className="chip" aria-pressed onClick={() => update({ cat: null, page: null })}>{CAT[cat]?.label ?? cat} ✕</button> : null}
          </div>
          <div className="toolbar" style={{ marginBottom: 0 }}>
            <div className="input-icon" style={{ width: 240, maxWidth: '100%' }}><Icon name="search"/>
              <input className="input sm" placeholder="Order or tracking number" value={text} onChange={(e) => setText(e.target.value)} aria-label="Search orders and tracking numbers"/></div>
            <select className="select sm" style={{ width: 'auto' }} value={carrier} onChange={(e) => update({ carrier: e.target.value || null, page: null })} aria-label="Carrier">
              <option value="">All carriers</option>{d.facets.carriers.map((c) => <option key={c}>{c}</option>)}</select>
            <select className="select sm" style={{ width: 'auto' }} value={status} onChange={(e) => update({ status: e.target.value || null, page: null })} aria-label="Tracking status">
              <option value="">All tracking statuses</option>{d.facets.statuses.map((c) => <option key={c} value={c}>{c.replace(/_/g, ' ')}</option>)}</select>
            <select className="select sm" style={{ width: 'auto' }} value={days} onChange={(e) => update({ days: e.target.value || null, page: null })} aria-label="Order date">
              {AGE_FILTERS.map((a) => <option key={a.key} value={a.key}>{a.label}</option>)}</select>
            <select className="select sm" style={{ width: 'auto' }} value={sort} onChange={(e) => update({ sort: e.target.value === 'priority' ? null : e.target.value, page: null })} aria-label="Sort">
              {SORTS.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}</select>
            <span style={{ marginLeft: 'auto' }}/>
            <Button size="sm" icon="download" onClick={() => download(`/shipping/export/shipments${qs(filters)}`).catch(toast.error)}>Export CSV</Button>
          </div>
          <Card flush foot={(<div className="pager" style={{ display: 'contents' }}>
              <span className="muted small">{d.total === 0 ? 'No matches' : `${page * PAGE + 1}–${Math.min((page + 1) * PAGE, d.total)} of ${fmtInt(d.total)}`}</span><span className="spacer"/>
              <Button size="sm" icon="chevronLeft" disabled={d.page === 0} onClick={() => update({ page: String(d.page - 1) })}>Previous</Button>
              <span className="small muted">Page {d.page + 1} of {d.pages}</span>
              <Button size="sm" disabled={d.page >= d.pages - 1} onClick={() => update({ page: String(d.page + 1) })}>Next <Icon name="chevronRight" size="sm"/></Button>
            </div>)}>
            <ShipmentsTable rows={d.rows} onOpen={onOpen}/>
          </Card>
          <div className="muted xs">Only dispatched parcels are listed. Delivered orders (by any source), orders not sent yet, and cancelled or refunded orders are not shown. Days count from the last carrier scan (from dispatch while there is none). Every order is in one section only.</div>
        </>)}
    </SourceGate>);
}

/* ------------------------------------------------------------------ Analytics */
function AnalyticsTab({ brand, update }) {
    const [period, setPeriod] = useState('30');
    const q = useApi(`/shipping/analytics${qs({ brand, period })}`);
    return (<SourceGate query={q}>
      {(d) => {
            const k = d.kpis;
            const go = (patch) => update({ tab: 'shipments', page: null, ...patch });
            return (<>
          <div className="kpis kpis-7">
            <Tile label="Active shipments" value={k.active}/>
            <Tile label="Critical" value={`${fmtInt(k.critical)} (${k.criticalPct}%)`} tone="crit"/>
            <Tile label="On track share" value={`${k.onTrackPct}%`} tone="ok"/>
            <Tile label="Average days since update" value={k.avgDays === null ? '—' : `${k.avgDays} d`}/>
            <Tile label="Hand checks" value={k.handChecks} tone="warn" onClick={() => update({ tab: 'checks' })}/>
            <Tile label="Carriers in use" value={k.carriersInUse}/>
            <Tile label="Value at risk" value={k.valueAtRisk.available ? (k.valueAtRisk.total === null ? '—' : fmtMoney(k.valueAtRisk.total, k.valueAtRisk.currency)) : ''} na={!k.valueAtRisk.available} foot={k.valueAtRisk.available ? 'Critical orders, once each' : k.valueAtRisk.reason}/>
          </div>
          <DeliveryPerformance dp={d.delivery} period={period} setPeriod={setPeriod}/>
          <div className="grid cols-2">
            <Card title="Shipments by age" sub="Click a bar to see those shipments">
              <BarList rows={d.aging.map((a) => ({ key: a.key, label: a.label, value: a.value, onClick: () => go({ cat: a.key }) }))} format={fmtInt}/>
            </Card>
            <Card title="Active shipments by week created"><LineChart ariaLabel="Active shipments by week created" height={200} yFormat={fmtInt}
                series={[{ key: 'active', label: 'Active', color: 'var(--theme-primary)', points: d.weeks.map((w) => ({ x: w.week, y: w.value })) }]}/></Card>
          </div>
          <div className="grid cols-2">
            <Card title="Critical by carrier" sub="Top carriers by active shipments">
              <BarList rows={d.carriers.map((c) => ({ key: c.carrier, label: c.carrier, value: c.critical, extra: `${c.other} other active`, onClick: () => go({ carrier: c.carrier === 'Unknown' ? null : c.carrier, cat: 'red' }) }))} format={fmtInt} empty="No active shipments."/>
            </Card>
            <Card title="Where shipments are">
              <BarList rows={d.stage.map((s) => ({ key: s.label, label: s.label, value: s.value }))} format={fmtInt}/>
              <div className="muted xs mt-8">Dispatched on (India time): critical vs other</div>
              <BarList rows={d.dispatchDay.map((x) => ({ key: x.day, label: x.day, value: x.critical + x.other, extra: `${x.critical} critical` }))} format={fmtInt} empty="No dispatch dates."/>
            </Card>
          </div>
          <Card title="Carrier scorecard" flush>
            {d.carriersReport.scorecard.length ? (<div className="table-wrap"><table className="t compact">
                <thead><tr><th>Carrier</th><th>Active</th><th>Critical</th><th className="hide-sm">Critical %</th><th>Hand checks</th><th className="hide-sm">Avg days</th><th>Health</th></tr></thead>
                <tbody>{d.carriersReport.scorecard.map((c) => (<tr key={c.carrier}><td><b>{c.carrier}</b></td><td>{fmtInt(c.active)}</td><td>{fmtInt(c.critical)}</td><td className="hide-sm">{c.criticalPct}%</td><td>{fmtInt(c.handChecks)}</td><td className="hide-sm">{c.avgDays === null ? '—' : `${c.avgDays} d`}</td>
                    <td><Pill tone={c.health === 'bad' ? 'crit' : c.health === 'warn' ? 'warn' : 'ok'}>{c.healthLabel}</Pill></td></tr>))}</tbody>
              </table></div>) : <Empty icon="truck" title="No active shipments">Nothing to score yet.</Empty>}
          </Card>
          <Card title="Aging by carrier" sub="Click a cell to open those shipments" flush>
            {d.carriersReport.heatmap.length ? (<div className="table-wrap"><table className="t compact">
                <thead><tr><th>Carrier</th>{d.carriersReport.categories.map((c) => <th key={c.key} style={{ textAlign: 'center' }}>{c.label}</th>)}</tr></thead>
                <tbody>{d.carriersReport.heatmap.map((c) => (<tr key={c.carrier}><td><b>{c.carrier}</b></td>
                    {d.carriersReport.categories.map((cat) => (<td key={cat.key} style={{ textAlign: 'center' }}>{c.cats[cat.key] ? <Button size="xs" variant="ghost" onClick={() => go({ carrier: c.carrier === 'Unknown' ? null : c.carrier, cat: cat.key })}>{c.cats[cat.key]}</Button> : <span className="faint">·</span>}</td>))}</tr>))}</tbody>
              </table></div>) : <Empty icon="truck" title="No data yet">No active shipments.</Empty>}
          </Card>
          <Card title="What to do today">{d.insights.length ? <ul style={{ margin: 0, paddingLeft: 18 }}>{d.insights.map((t) => <li key={t} className="small">{t}</li>)}</ul> : <div className="muted small">Nothing urgent right now.</div>}</Card>
        </>);
        }}
    </SourceGate>);
}

function DeliveryPerformance({ dp, period, setPeriod }) {
    const table = (title, rows, key) => (<Card title={title} flush>
      {rows.length ? (<div className="table-wrap"><table className="t compact">
          <thead><tr><th>{key === 'carrier' ? 'Carrier' : 'Destination state'}</th><th>Delivered</th><th>On time</th><th className="hide-sm">Avg days</th></tr></thead>
          <tbody>{rows.map((r) => (<tr key={r[key]}><td><b>{r[key]}</b></td><td>{fmtInt(r.delivered)}</td><td>{r.onTimePct === null ? <span className="faint">No promised date</span> : <Pill tone={r.onTimePct >= 90 ? 'ok' : r.onTimePct >= 75 ? 'warn' : 'crit'}>{r.onTimePct}%</Pill>}</td><td className="hide-sm">{r.avgDays} d</td></tr>))}</tbody>
        </table></div>) : <Empty icon="truck" title="No deliveries">Nothing was delivered in this period.</Empty>}
    </Card>);
    return (<>
      <Card title="Delivery performance" sub="Parcels delivered in the period, dispatch to delivery. On time means delivered by the end of the promised day; parcels without a promised date are not in the on-time share."
        actions={<div className="seg" role="group" aria-label="Period">{['30', '90'].map((p) => <button key={p} aria-pressed={period === p} onClick={() => setPeriod(p)}>Last {p} days</button>)}</div>}>
        <div className="kpis" style={{ marginBottom: 12 }}>
          <Tile label="Delivered" value={dp.delivered}/>
          <Tile label="On-time delivery" value={dp.onTimePct === null ? '—' : `${dp.onTimePct}%`} tone={dp.onTimePct === null ? undefined : dp.onTimePct >= 90 ? 'ok' : dp.onTimePct >= 75 ? 'warn' : 'crit'} foot={`${fmtInt(dp.withPromisedDate)} of ${fmtInt(dp.delivered)} had a promised date`}/>
          <Tile label="Average delivery time" value={dp.avgDays === null ? '—' : `${dp.avgDays} d`}/>
        </div>
        <div className="grid cols-2">
          <div><div className="muted xs">Delivery time (days from dispatch)</div><BarList rows={dp.distribution} format={fmtInt} empty="No deliveries in this period."/></div>
          <div><div className="muted xs">On-time delivery by week</div>
            <LineChart ariaLabel="On-time delivery percentage by week" height={180} yFormat={(v) => `${Math.round(v)}%`}
              series={[{ key: 'ontime', label: 'On time %', color: 'var(--theme-primary)', points: dp.trend.map((w) => ({ x: w.week, y: w.onTimePct })) }]}/></div>
        </div>
      </Card>
      <div className="grid cols-2">{table('Delivery by carrier', dp.byCarrier, 'carrier')}{table('Delivery by region', dp.byRegion, 'region')}</div>
    </>);
}

/* ------------------------------------------------------------------ Reshipped */
function ReshippedCard({ rs, onOpen }) {
    if (!rs)
        return null;
    return (<Card title="Reshipped: old parcel still open" sub={`${rs.rule} ${fmtInt(rs.total)} found.`} flush>
      {!rs.rows.length ? <Empty icon="checkCircle" title="No reshipped parcels found">No old parcel is waiting to be closed.</Empty> : (<Paged rows={rs.rows}>{(page) => (<div className="table-wrap"><table className="t compact">
          <thead><tr><th>Order</th><th>Old parcel</th><th>How we know</th><th>Sent again as</th><th className="hide-sm">Next step</th></tr></thead>
          <tbody>{page.map((r) => (<tr key={r.key}>
              <td className="nowrap"><Button size="xs" variant="ghost" onClick={() => onOpen(r.order)} title="Open this order">{r.order}</Button><ShopifyOrderLink url={r.shopifyUrl}/></td>
              <td className="small">{r.carrier}{r.tracking ? <span className="mono faint"> {r.tracking}</span> : null}<div className="faint xs">{r.oldStatus.replace(/_/g, ' ') || '—'}{r.days !== null ? ` · ${dayText(r.days)} since update` : ''}</div></td>
              <td className="small"><Pill tone="info">{r.howLabel}</Pill><div className="faint xs">{r.detail}</div></td>
              <td className="small">{r.newOrder && r.newOrder !== r.order ? <Button size="xs" variant="ghost" onClick={() => onOpen(r.newOrder)}>{r.newOrder}</Button> : null}{r.newCarrier ? <div className="faint xs">{r.newCarrier}{r.newTracking ? ` ${r.newTracking}` : ''}{r.newStatus ? ` · ${CAT[r.newStatus]?.label ?? r.newStatus}` : ''}</div> : <div className="faint xs">not dispatched yet</div>}</td>
              <td className="small hide-sm">{r.action}</td>
            </tr>))}</tbody>
        </table></div>)}</Paged>)}
    </Card>);
}

/* ------------------------------------------------------------------ Checks */
function ChecksTab({ brand, onOpen }) {
    const q = useApi(`/shipping/checks${qs({ brand })}`);
    const [kind, setKind] = useState('');
    return (<SourceGate query={q}>
      {(d) => {
            const ex = d.exceptions;
            const shown = ex.rows.filter((r) => !kind || (r.types || [r.type]).includes(kind));
            return (<>
          <Card title="Hand checks" sub={`${fmtInt(ex.total)} orders: tracking missing, invalid tracking, or a fix needed in Shopify. Each order is listed once, and is not in the Critical / Orange / Yellow lists. Click an order to see its tracking.`}
            actions={<select className="select sm" style={{ width: 'auto' }} value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Type of check">
              <option value="">All types ({ex.total})</option>{ex.types.map((t) => <option key={t.key} value={t.key}>{t.label} ({ex.counts[t.key]})</option>)}</select>} flush>
            {!shown.length ? <Empty icon="checkCircle" title="Nothing to check">No orders of this type.</Empty> : (<Paged rows={shown} resetKey={kind}>{(page) => (<div className="table-wrap"><table className="t compact">
                <thead><tr><th>Order</th><th>Type</th><th className="hide-sm">Carrier</th><th>What is wrong</th></tr></thead>
                <tbody>{page.map((r) => {
                    const issues = r.issues || [r];
                    return (<tr key={`${r.brand}|${r.order}`}>
                    <td className="nowrap"><Button size="xs" variant="ghost" onClick={() => onOpen(r.order)} title="Open this order">{r.order}</Button><ShopifyOrderLink url={r.shopifyUrl}/></td>
                    <td><div className="row" style={{ gap: 4, flexWrap: 'wrap' }}>{[...new Map(issues.map((i) => [i.type, i])).values()].map((i) => (
                        <Pill key={i.type} tone={i.severity === 'high' ? 'crit' : 'warn'}>{i.label}</Pill>))}</div></td>
                    <td className="hide-sm small">{r.carrier}</td>
                    <td className="small">{issues.length === 1 ? issues[0].detail : issues.map((i) => <div key={`${i.type}|${i.key}`}>{i.detail}</div>)}</td></tr>);
                })}</tbody>
              </table></div>)}</Paged>)}
          </Card>
          <ReshippedCard rs={d.reshipped} onOpen={onOpen}/>
          <ImportPreview brand={brand}/>
        </>);
        }}
    </SourceGate>);
}
