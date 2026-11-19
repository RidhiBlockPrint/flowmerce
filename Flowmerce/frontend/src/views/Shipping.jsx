'use client';
import { useEffect, useState } from 'react';
import { api } from '../lib/api';
import { useSearchParams } from '../lib/nav';
import { useApi, qs, download } from '../lib/api';
import { useBrandParam } from '../lib/app';
import { fmtDateTime, fmtInt, timeAgo } from '../lib/format';
import { AGE_FILTERS, CAT, CHIPS, SORTS, dayText, fmtMoney } from '../lib/shipping';
import { Button, Card, Empty, ErrorState, LoadingBlock, PageHead, Pill, Tabs } from '../components/ui';
import { useToast } from '../components/overlays';
import { Icon } from '../components/Icon';
import { BarList, LineChart } from '../components/charts';
import { ImportPreview, OrderDrawer, ShipmentsTable, ShopifyOrderLink, SourceGate, TONE_VAR, Tile } from '../components/shipping';

const TABS = [
    { key: 'overview', label: 'Overview' },
    { key: 'shipments', label: 'Shipments' },
    { key: 'unfulfilled', label: 'Unfulfilled' },
    { key: 'checks', label: 'Checks and exceptions' },
    { key: 'analytics', label: 'Analytics' },
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
      <PageHead title="Shipping" sub="Where every parcel is, what is late and what needs a decision. Read from Shopify through Supabase, refreshed every 15 minutes. Figures follow the brand picker; All shows both brands, each parcel labelled."
        actions={<Button icon="refresh" loading={refreshing} onClick={refresh} title="Read the latest changes from Shopify into Flowmerce now">Refresh now</Button>}/>
      <Tabs value={tab} onChange={(t) => update({ tab: t === 'overview' ? null : t, page: null })} tabs={TABS}/>
      <div className="mt-16" key={rev}>
        {tab === 'shipments' ? <ShipmentsTab brand={brand} sp={sp} update={update} onOpen={setOpen}/>
            : tab === 'analytics' ? <AnalyticsTab brand={brand} update={update}/>
                : tab === 'checks' ? <ChecksTab brand={brand} onOpen={setOpen}/>
                : tab === 'unfulfilled' ? <UnfulfilledTab brand={brand} onOpen={setOpen}/>
                    : <OverviewTab brand={brand} update={update} onOpen={setOpen} onChanged={() => setRev((n) => n + 1)}/>}
      </div>
      {open ? <OrderDrawer order={open} brand={brand} onClose={() => setOpen(null)}/> : null}
    </>);
}

/* ------------------------------------------------------------------ Overview */
function OverviewTab({ brand, update, onOpen, onChanged }) {
    const q = useApi(`/shipping/summary${qs({ brand })}`);
    const top = useApi(`/shipping/shipments${qs({ brand, size: 6, sort: 'priority', cat: 'red' })}`);
    const toast = useToast();
    return (<SourceGate query={q}>
      {(d) => (<>
          {d.banner ? <div className="callout crit" role="alert"><Icon name="alert"/><div style={{ flex: 1 }}><b>{d.banner}</b></div>
            <Button size="sm" icon="download" onClick={() => download(`/shipping/export/escalation${qs({ brand })}`).catch(toast.error)}>Escalation list (CSV)</Button></div> : null}
          <div className="kpis">
            {d.kpis.map((k) => (<Tile key={k.key || 'all'} label={k.label} value={k.value} tone={k.key === '' ? undefined : TONE_VAR[k.tone]}
                onClick={() => update(k.key === 'unfulfilled' ? { tab: 'unfulfilled', page: null } : { tab: 'shipments', cat: k.key || null, page: null })}/>))}
          </div>
          <div className="grid main-side">
            <div className="col" style={{ gap: 16, minWidth: 0 }}>
              <Card title="Most critical" sub={`In stage ${d.thresholds.red}+ days`} actions={<Button size="sm" onClick={() => update({ tab: 'shipments', cat: 'red', page: null })}>See all critical</Button>} flush>
                {top.data?.rows?.length ? <ShipmentsTable rows={top.data.rows} onOpen={onOpen}/> : top.error ? <div className="card-body"><ErrorState error={top.error} onRetry={top.reload}/></div> : top.data ? <Empty icon="checkCircle" title="Nothing is critical">No active shipment has been in its stage for {d.thresholds.red}+ days.</Empty> : <div className="card-body"><LoadingBlock rows={3}/></div>}
              </Card>
              <div className="grid cols-3">
                <Card title="Not dispatched"><div className="kpi-value">{fmtInt(d.stage.preDispatch)}</div><div className="muted small">Clock runs from the order date</div></Card>
                <Card title="Dispatched"><div className="kpi-value">{fmtInt(d.stage.dispatched)}</div><div className="muted small">Clock runs from the dispatch date</div></Card>
                <Card title="Delivered"><div className="kpi-value">{fmtInt(d.delivered)}</div><div className="muted small">Last {d.deliveredWindowDays} days · left the active queue</div></Card>
              </div>
            </div>
            <div className="col" style={{ gap: 16, minWidth: 0 }}>
              <Card title="Value at risk" sub="Critical orders, each counted once">
                {!d.valueAtRisk.available ? <div className="muted small">Unavailable: {d.valueAtRisk.reason}</div>
                    : d.valueAtRisk.orders === 0 ? <div className="muted small">No critical orders.</div>
                        : d.valueAtRisk.total === null ? <div className="muted small">{d.valueAtRisk.note} ({d.valueAtRisk.orders} orders)</div>
                            : <><div className="kpi-value">{fmtMoney(d.valueAtRisk.total, d.valueAtRisk.currency)}</div><div className="muted small">{d.valueAtRisk.orders} order{d.valueAtRisk.orders === 1 ? '' : 's'}</div></>}
              </Card>
              <Card title="Order checks" sub="Orders whose note says DONE but the shop shows them as not fulfilled">
                {d.checks.mcf ? (<div className="row-wrap">
                    <Pill tone="crit">{d.checks.mcf.critical} critical</Pill><Pill tone="warn">{d.checks.mcf.watch} watch</Pill><Pill tone="info">{d.checks.mcf.alert} alert</Pill>
                  </div>) : <div className="muted small">Unavailable right now.</div>}
                <div className="small mt-8">{fmtInt(d.checks.toVerify)} parcels with no carrier updates to verify{d.checks.missingTracking ? ` (${d.checks.missingTracking} without tracking)` : ''}.</div>
                <div className="mt-8"><Button size="sm" onClick={() => update({ tab: 'checks' })}>Open checks</Button></div>
              </Card>
              <SyncCard source={d.source} onChanged={onChanged}/>
            </div>
          </div>
        </>)}
    </SourceGate>);
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
const PAGE = 25;

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
          <div className="muted xs">Delivered orders and orders cancelled or refunded are not listed. Marketplace and unknown carriers have no delivery data, so they are checked by hand and never counted as critical.</div>
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
          <div className="kpis">
            <Tile label="Active shipments" value={k.active}/>
            <Tile label="Critical" value={`${fmtInt(k.critical)} (${k.criticalPct}%)`} tone="crit"/>
            <Tile label="On track share" value={`${k.onTrackPct}%`} tone="ok"/>
            <Tile label="Average days in stage" value={k.avgDays === null ? '—' : `${k.avgDays} d`}/>
            <Tile label="No movement" value={k.stuck} tone="warn"/>
            <Tile label="Carriers in use" value={k.carriersInUse}/>
            <Tile label="Value at risk" value={k.valueAtRisk.available ? (k.valueAtRisk.total === null ? '—' : fmtMoney(k.valueAtRisk.total, k.valueAtRisk.currency)) : ''} na={!k.valueAtRisk.available} foot={k.valueAtRisk.available ? 'Critical orders, once each' : k.valueAtRisk.reason}/>
          </div>
          <DeliveryPerformance dp={d.delivery} period={period} setPeriod={setPeriod}/>
          <div className="grid cols-2">
            <Card title="Shipments by age" sub="Click a bar to see those shipments">
              <BarList rows={d.aging.map((a) => ({ key: a.key, label: a.label, value: a.value, onClick: () => go({ cat: a.key }) }))} format={fmtInt}/>
            </Card>
            <Card title="Active shipments by week created"><LineChart ariaLabel="Active shipments by week created" height={200} yFormat={fmtInt}
                series={[{ key: 'active', label: 'Active', points: d.weeks.map((w) => ({ x: w.week, y: w.value })) }]}/></Card>
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
                <thead><tr><th>Carrier</th><th>Active</th><th>Critical</th><th className="hide-sm">Critical %</th><th>No movement</th><th className="hide-sm">Exceptions</th><th className="hide-sm">Avg days</th><th>Health</th></tr></thead>
                <tbody>{d.carriersReport.scorecard.map((c) => (<tr key={c.carrier}><td><b>{c.carrier}</b></td><td>{fmtInt(c.active)}</td><td>{fmtInt(c.critical)}</td><td className="hide-sm">{c.criticalPct}%</td><td>{fmtInt(c.stuck)}</td><td className="hide-sm">{fmtInt(c.exceptions)}</td><td className="hide-sm">{c.avgDays === null ? '—' : `${c.avgDays} d`}</td>
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
              series={[{ key: 'ontime', label: 'On time %', points: dp.trend.map((w) => ({ x: w.week, y: w.onTimePct })) }]}/></div>
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
      {!rs.rows.length ? <Empty icon="checkCircle" title="No reshipped parcels found">No old parcel is waiting to be closed.</Empty> : (<div className="table-wrap"><table className="t compact">
          <thead><tr><th>Order</th><th>Old parcel</th><th>How we know</th><th>Sent again as</th><th className="hide-sm">Next step</th></tr></thead>
          <tbody>{rs.rows.map((r) => (<tr key={r.key}>
              <td className="nowrap"><Button size="xs" variant="ghost" onClick={() => onOpen(r.order)} title="Open this order">{r.order}</Button><ShopifyOrderLink url={r.shopifyUrl}/></td>
              <td className="small">{r.carrier}{r.tracking ? <span className="mono faint"> {r.tracking}</span> : null}<div className="faint xs">{r.oldStatus.replace(/_/g, ' ') || '—'}{r.days !== null ? ` · ${dayText(r.days)} in stage` : ''}</div></td>
              <td className="small"><Pill tone="info">{r.howLabel}</Pill><div className="faint xs">{r.detail}</div></td>
              <td className="small">{r.newOrder && r.newOrder !== r.order ? <Button size="xs" variant="ghost" onClick={() => onOpen(r.newOrder)}>{r.newOrder}</Button> : null}{r.newCarrier ? <div className="faint xs">{r.newCarrier}{r.newTracking ? ` ${r.newTracking}` : ''}{r.newStatus ? ` · ${CAT[r.newStatus]?.label ?? r.newStatus}` : ''}</div> : <div className="faint xs">not dispatched yet</div>}</td>
              <td className="small hide-sm">{r.action}</td>
            </tr>))}</tbody>
        </table></div>)}
    </Card>);
}

/* ------------------------------------------------------------------ Unfulfilled */
const BAND_TONE = { '9+': 'crit', '6-8': 'warn', '4-5': 'warn', '0-3': 'neutral' };
function UnfulfilledTab({ brand, onOpen }) {
    const q = useApi(`/shipping/unfulfilled${qs({ brand })}`);
    const [band, setBand] = useState('');
    return (<SourceGate query={q}>
      {(d) => {
            const shown = d.rows.filter((r) => !band || r.band === band);
            return (<Card title="Unfulfilled orders" sub={`${d.rule} ${fmtInt(d.total)} orders${d.withAmazon ? `, ${fmtInt(d.withAmazon)} of them with Amazon` : ''}.`}
              actions={<select className="select sm" style={{ width: 'auto' }} value={band} onChange={(e) => setBand(e.target.value)} aria-label="Waiting time">
                <option value="">All ({d.total})</option>{d.bands.map((b) => <option key={b.key} value={b.key}>Waiting {b.label} ({d.counts[b.key]})</option>)}</select>} flush>
              {!shown.length ? <Empty icon="checkCircle" title="No unfulfilled orders">Every order has been sent.</Empty> : (<div className="table-wrap"><table className="t compact">
                  <thead><tr><th>Order</th><th>Ordered</th><th>Waiting</th><th className="hide-sm">Amazon</th><th>Next step</th></tr></thead>
                  <tbody>{shown.slice(0, 200).map((r) => (<tr key={`${r.brand}|${r.order}`}>
                      <td className="nowrap"><Button size="xs" variant="ghost" onClick={() => onOpen(r.order)} title="Open this order">{r.order}</Button><ShopifyOrderLink url={r.shopifyUrl}/>{r.flagged ? <Pill tone="warn">Flagged</Pill> : null}</td>
                      <td className="small nowrap">{r.placedAt ? fmtDateTime(r.placedAt) : '—'}</td>
                      <td><Pill tone={BAND_TONE[r.band]}>{dayText(r.days ?? 0)}</Pill></td>
                      <td className="small hide-sm">{r.amazon || <span className="faint">—</span>}</td>
                      <td className="small">{r.action}</td></tr>))}</tbody>
                </table></div>)}
              {shown.length > 200 ? <div className="card-body muted xs">Showing the first 200 of {shown.length}.</div> : null}
            </Card>);
        }}
    </SourceGate>);
}

/* ------------------------------------------------------------------ Checks */
function ChecksTab({ brand, onOpen }) {
    const q = useApi(`/shipping/checks${qs({ brand })}`);
    const toast = useToast();
    const [kind, setKind] = useState('');
    return (<SourceGate query={q}>
      {(d) => {
            const ex = d.exceptions;
            const shown = ex.rows.filter((r) => !kind || (r.types || [r.type]).includes(kind));
            return (<>
          <Card title="Exceptions and data problems" sub={`${fmtInt(ex.total)} open. Click an order to see its tracking and decide the next step.`}
            actions={<select className="select sm" style={{ width: 'auto' }} value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Type of exception">
              <option value="">All types ({ex.total})</option>{ex.types.map((t) => <option key={t.key} value={t.key}>{t.label} ({ex.counts[t.key]})</option>)}</select>} flush>
            {!shown.length ? <Empty icon="checkCircle" title="Nothing to review">No exceptions of this type.</Empty> : (<div className="table-wrap"><table className="t compact">
                <thead><tr><th>Order</th><th>Type</th><th className="hide-sm">Carrier</th><th>What is wrong</th></tr></thead>
                <tbody>{shown.slice(0, 60).map((r) => {
                    const issues = r.issues || [r];
                    return (<tr key={`${r.brand}|${r.order}`}>
                    <td className="nowrap"><Button size="xs" variant="ghost" onClick={() => onOpen(r.order)} title="Open this order">{r.order}</Button><ShopifyOrderLink url={r.shopifyUrl}/></td>
                    <td><div className="row" style={{ gap: 4, flexWrap: 'wrap' }}>{[...new Map(issues.map((i) => [i.type, i])).values()].map((i) => (
                        <Pill key={i.type} tone={i.severity === 'high' ? 'crit' : 'warn'}>{i.label}</Pill>))}</div></td>
                    <td className="hide-sm small">{r.carrier}</td>
                    <td className="small">{issues.length === 1 ? issues[0].detail : issues.map((i) => <div key={`${i.type}|${i.key}`}>{i.detail}</div>)}</td></tr>);
                })}</tbody>
              </table></div>)}
            {shown.length > 60 ? <div className="card-body muted xs">Showing the first 60 of {shown.length}.</div> : null}
          </Card>
<Card title="Marked DONE by the team, but Shopify shows not fulfilled" sub={d.mcf.available ? `${d.mcf.rule}${d.mcf.amazonKnown === false ? ' (Amazon status needs supabase/108_flow_board_amazon.sql.)' : ` ${d.mcf.withAmazonRecord} of ${d.mcf.rows.length} have an Amazon record.`}` : undefined} flush>
            {!d.mcf.available ? <div className="card-body"><div className="callout warn"><Icon name="alert"/><div>Unavailable: {d.mcf.reason} The list is not shown rather than shown empty.</div></div></div>
                : !d.mcf.rows.length ? <Empty icon="checkCircle" title="No mismatches">Every order marked DONE in its note is fulfilled, or is under 5 days old.</Empty>
                    : (<div className="table-wrap"><table className="t compact">
                        <thead><tr><th>Order</th><th>Age</th><th>Fulfilment status</th><th>Amazon says</th><th>Level</th></tr></thead>
                        <tbody>{d.mcf.rows.map((r) => (<tr key={r.order}><td className="nowrap"><Button size="xs" variant="ghost" onClick={() => onOpen(r.order)} title="Open this order">{r.order}</Button><ShopifyOrderLink url={r.shopifyUrl}/></td><td>{dayText(r.age)}</td><td className="small">{r.status.replace(/_/g, ' ')}</td>
                            <td className="small">{r.amazon ? <>{r.amazon}{r.amazonTracking ? <div className="faint xs mono">{r.amazonTracking}</div> : null}</> : <span className="faint">No Amazon record</span>}</td>
                            <td><Pill tone={r.level === 'critical' ? 'crit' : r.level === 'watch' ? 'warn' : 'info'}>{r.level}</Pill></td></tr>))}</tbody>
                      </table></div>)}
          </Card>
          <ReshippedCard rs={d.reshipped} onOpen={onOpen}/>
          <Card title="Marketplace / unknown carriers to verify" sub="No carrier delivery data exists for these parcels, so a person checks them."
            actions={<Button size="sm" icon="download" onClick={() => download(`/shipping/export/verify${qs({ brand })}`).catch(toast.error)}>Verify list (CSV)</Button>}>
            <div className="kpis">
              <Tile label="To verify" value={d.verify.total} tone="info"/>
              <Tile label="Tracking missing" value={d.verify.missingTracking} tone="crit"/>
              {d.verify.team ? (<>
                  <Tile label="Marked delivered" value={d.verify.team.delivered} tone="ok"/>
                  <Tile label="Marked lost" value={d.verify.team.lost} tone="crit"/>
                  <Tile label="Couldn't deliver" value={d.verify.team.failed} tone="warn"/>
                  <Tile label="Still in transit" value={d.verify.team.inTransit}/>
                  <Tile label="Not checked yet" value={d.verify.team.notChecked}/>
                </>) : <Tile label="Team marks" value="" na foot={d.verify.teamReason}/>}
            </div>
            <div className="muted xs mt-8">Team marks are recorded in the order drawer (open an order, then Team mark).</div>
          </Card>
          <ImportPreview brand={brand}/>
        </>);
        }}
    </SourceGate>);
}
