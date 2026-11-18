'use client';
/* Shipping building blocks, made from Flowmerce's own components. The server decides every category and number; this
   file only shows them, and shows "unavailable" (never zero) when the server says the data is not there. */
import { useState } from 'react';
import { api, useApi } from '../lib/api';
import { useApp } from '../lib/app';
import { fmtDateTime, fmtInt, timeAgo } from '../lib/format';
import { CAT, OUTCOME, SOURCE_TITLE, STAGE_LABEL, TEAM_LABEL, dayText, fmtMoney, missingParts, OUTCOMES } from '../lib/shipping';
import { Button, Card, Empty, ErrorState, Kv, LoadingBlock, Pill } from './ui';
import { Drawer, useToast } from './overlays';
import { Icon } from './Icon';

export function CatPill({ cat, resolved }) {
    const c = CAT[cat] ?? { label: cat, tone: 'neutral' };
    return <Pill tone={c.tone}>{resolved ? `Resolved: ${resolved.label}` : c.label}</Pill>;
}

function SetupNeeded({ source }) {
    return (<Empty icon="plug" title="Supabase not configured">
      Shipping reads Supabase, and no connection is set up, so no figures are shown. {source.reason} Set <span className="mono">SUPABASE_URL</span> and <span className="mono">SUPABASE_SERVICE_ROLE_KEY</span> in the <span className="mono">.env</span> file, then restart Flowmerce (see docs/operations/shipping-supabase-setup.md).
    </Empty>);
}

/** Banner for the freshness of the saved data: a failed or stale sync is said out loud, with its reason. */
export function FreshnessBanner({ freshness }) {
    if (!freshness || freshness.state === 'fresh')
        return null;
    const tone = freshness.state === 'failed' ? 'crit' : freshness.state === 'no_runs' ? 'info' : 'warn';
    const text = freshness.message || 'Freshness could not be confirmed.';
    return (<div className={`callout ${tone}`} role={tone === 'crit' ? 'alert' : 'status'}><Icon name={tone === 'crit' ? 'alert' : 'info'}/><div>{text}{freshness.lastChecked ? <> Last shipment check: {fmtDateTime(freshness.lastChecked)}.</> : null}</div></div>);
}

/**
 * Wraps a Shipping API query. Renders the right message for every state of the source (not set up, brand not
 * configured, paused, unavailable, partial) and calls `children(data)` only when there is real data to show.
 */
export function SourceGate({ query, children }) {
    const { data, error, reload } = query;
    const { brandOf } = useApp();
    if (error)
        return <ErrorState error={error} onRetry={reload}/>;
    if (!data)
        return <LoadingBlock rows={6}/>;
    const s = data.source;
    if (s.state === 'not_configured')
        return <SetupNeeded source={s}/>;
    if (s.state === 'brand_not_configured' || s.state === 'paused')
        return <Empty icon="truck" title={s.state === 'paused' ? 'Shipping is paused' : 'Shipping is not set up for this brand'}>{s.reason}</Empty>;
    if (SOURCE_TITLE[s.state]) {
        return (<div className="callout crit" role="alert"><Icon name="alert"/>
        <div style={{ flex: 1 }}><b>{SOURCE_TITLE[s.state]}: Shipping data is unavailable.</b> {String(s.reason).replace(/[.s]+$/, "")}. No figures are shown instead of zeros. Test the connection under Settings &gt; Integrations.</div>
        <Button size="sm" icon="refresh" onClick={reload}>Retry</Button></div>);
    }
    const missing = missingParts(s);
    return (<div className="col" style={{ gap: 16 }}>
      {data.notConfigured?.length ? <div className="callout info"><Icon name="info"/><div>Showing {brandOf(data.brand)?.short ?? data.brand} only. Shipping is not set up for {data.notConfigured.map((b) => brandOf(b)?.short ?? b).join(', ')}, so nothing is added together.</div></div> : null}
      {s.state === 'partial' ? (<div className="callout warn"><Icon name="alert"/><div><b>Some details are unavailable:</b> {missing.map((m) => m.label).join(', ')}. Figures that depend on them are marked unavailable, not zero.
          <ul className="small" style={{ margin: '6px 0 0', paddingLeft: 18 }}>{missing.map((m) => <li key={m.key}>{m.label}: {m.reason || 'not readable'}</li>)}</ul></div></div>) : null}
      <FreshnessBanner freshness={s.freshness}/>
      {children(data)}
    </div>);
}

export function Tile({ label, value, tone, foot, onClick, na }) {
    const style = tone ? { color: `var(--${tone})` } : undefined;
    const props = onClick ? { role: 'button', tabIndex: 0, onClick, onKeyDown: (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onClick(); } }, style: { cursor: 'pointer' } } : {};
    return (<div className="kpi" {...props}>
      <div className="kpi-label">{label}</div>
      <div className={`kpi-value ${na ? 'na' : ''}`} style={style}>{na ? 'Unavailable' : typeof value === 'number' ? fmtInt(value) : value}</div>
      <div className="kpi-foot">{foot}</div>
    </div>);
}

export const TONE_VAR = { neutral: 'ink', good: 'ok', muted: 'muted', warn: 'warn', orange: 'warn', bad: 'crit', info: 'info' };

/** Opens the order's page in Shopify admin in a new tab. Shows nothing when the server has no Shopify link for it. */
export function ShopifyOrderLink({ url, label }) {
    if (!url)
        return null;
    return (<a className={`btn ghost xs${label ? '' : ' icon-only'}`} href={url} target="_blank" rel="noreferrer" title="Open this order in Shopify admin"
      aria-label={label ? undefined : 'Open this order in Shopify admin'}><Icon name="external" size="sm"/>{label ?? null}</a>);
}

export function ShipmentsTable({ rows, onOpen, empty }) {
    if (!rows.length)
        return <Empty icon="truck" title="No shipments match">{empty ?? 'Nothing matches these filters.'}</Empty>;
    return (<div className="table-wrap">
      <table className="t compact">
        <thead><tr><th>Order</th><th>Status</th><th className="hide-sm">Carrier</th><th className="hide-sm">Tracking</th><th>In stage</th><th className="hide-md">Last scan</th><th className="hide-md">Dispatched</th></tr></thead>
        <tbody>
          {rows.map((r) => (<tr key={r.key}>
              <td className="nowrap"><Button size="xs" variant="ghost" onClick={() => onOpen(r.order)} title="Open this order">{r.order}</Button><ShopifyOrderLink url={r.shopifyUrl}/>{r.packages > 1 ? <span className="faint xs"> · {r.packages} parcels</span> : null}</td>
              <td><div className="row-wrap" style={{ gap: 4 }}>
                  <CatPill cat={r.cat} resolved={r.resolved}/>
                  {r.exception ? <Pill tone="crit">{r.exception.replace(/_/g, ' ')}</Pill> : null}
                  {r.flagged ? <Pill tone="info">Flagged</Pill> : null}
                  {r.noMove ? <Pill tone="warn" title={`No carrier scan for ${r.scanAge} days`}>No movement</Pill> : null}
                </div></td>
              <td className="hide-sm small">{r.carrier || <span className="faint">Unknown</span>}</td>
              <td className="hide-sm small mono">{r.missingTracking ? <span className="faint">Missing</span> : r.trackUrl ? <a href={r.trackUrl} target="_blank" rel="noreferrer">{r.tracking}</a> : r.tracking}</td>
              <td className="small nowrap">{r.unconfirmed && r.cat !== 'lost' && r.cat !== 'failed' ? <span className="faint">No delivery data</span> : dayText(r.days)}<div className="faint xs">{STAGE_LABEL[r.stage] ?? r.stage}</div></td>
              <td className="hide-md small" title={r.lastScanAt ? fmtDateTime(r.lastScanAt) : ''}>{r.lastScanAt ? <>{timeAgo(r.lastScanAt)}<div className="faint xs ellipsis" style={{ maxWidth: 200 }}>{r.lastScan}</div></> : <span className="faint">No scan data</span>}</td>
              <td className="hide-md small nowrap">{r.dispatchedAt ? fmtDateTime(r.dispatchedAt) : <span className="faint">Not yet</span>}</td>
            </tr>))}
        </tbody>
      </table>
    </div>);
}

/** The team's own marks on an order (checked, flagged for escalation) and notes. Saved in Flowmerce, recorded in the audit log. */
function OrderActions({ order, detail, setData, brand }) {
    const a = detail.annotation;
    const [text, setText] = useState('');
    const [busy, setBusy] = useState('');
    const [pending, setPending] = useState('');
    const toast = useToast();
    const run = async (action, body = {}, ok) => {
        setBusy(action);
        try {
            setData(await api.post(`/shipping/shipments/${encodeURIComponent(order)}/note${brand ? `?brand=${brand}` : ''}`, { action, ...body }));
            if (action === 'note')
                setText('');
            if (ok)
                toast.ok(ok);
        }
        catch (e) {
            toast.error(e);
        }
        finally {
            setBusy('');
        }
    };
    return (<Card title="Team actions" sub="Saved in Flowmerce for the whole team. Nothing is sent to Shopify or the carrier.">
      <div className="row-wrap">
        {a.reviewedAt ? <Button size="sm" icon="checkCircle" loading={busy === 'uncheck'} onClick={() => run('uncheck')}>Checked {timeAgo(a.reviewedAt)} (undo)</Button>
            : <Button size="sm" icon="checkCircle" loading={busy === 'check'} onClick={() => run('check', {}, 'Marked as checked')}>Mark as checked</Button>}
        {a.flagged ? <Button size="sm" icon="alert" loading={busy === 'unflag'} onClick={() => run('unflag')}>Remove escalation flag</Button>
            : <Button size="sm" icon="alert" variant="primary" loading={busy === 'flag'} onClick={() => run('flag', {}, 'Flagged for escalation. It is now on the escalation list.')}>Flag for escalation</Button>}
      </div>
      {a.reviewedBy ? <div className="muted xs mt-8">Checked by {a.reviewedBy}.</div> : null}
      <div className="mt-12">
        {a.outcome ? (<div className="row-wrap">
            <Pill tone="neutral">Resolved: {a.outcomeLabel}</Pill>
            <span className="muted xs">by {a.outcomeBy || 'the team'} · {timeAgo(a.outcomeAt)}. Out of Critical and the delay figures.</span>
            <Button size="sm" loading={busy === 'clear_outcome'} onClick={() => run('clear_outcome', {}, 'Outcome removed. The order is back in the active figures.')}>Undo</Button>
          </div>) : (<>
            <div className="small">Outcome Shopify does not show (removes the order from Critical and the delay figures):</div>
            <div className="row-wrap mt-4">{OUTCOMES.map(([k, l]) => (<Button key={k} size="sm" loading={busy === 'outcome' && pending === k}
                onClick={() => { setPending(k); run('outcome', { text: k }, `Marked ${l.toLowerCase()}. It is now under Resolved.`); }}>{l}</Button>))}</div>
          </>)}
      </div>
      <div className="row mt-8"><input className="input sm" style={{ flex: 1 }} value={text} onChange={(e) => setText(e.target.value)} placeholder="Add a note" aria-label="Add a note" maxLength={500}
          onKeyDown={(e) => { if (e.key === 'Enter' && text.trim())
              run('note', { text }); }}/>
        <Button size="sm" loading={busy === 'note'} disabled={!text.trim()} onClick={() => run('note', { text })}>Add note</Button></div>
      {a.notes.length ? (<div className="alert-list mt-8">{a.notes.map((n) => (<div key={n.at + n.text} className="alert-item"><span className="sev info"/><span className="small">{n.text}<span className="muted xs" style={{ display: 'block' }}>{n.by} · {timeAgo(n.at)}</span></span></div>))}</div>) : <div className="muted xs mt-8">No notes yet.</div>}
    </Card>);
}

const TEAM_MARKS = [['', 'Not checked'], ['in_transit', 'Still in transit'], ['delivered', 'Delivered'], ['lost', 'Lost'], ['failed', "Couldn't deliver"]];

/** For a parcel with no carrier data (Amazon, unknown carrier, or tracking Shopify never received): a person checks it and records the outcome. */
function TeamMark({ parcel, onSaved }) {
    const [mark, setMark] = useState(parcel.manual?.status ?? '');
    const [busy, setBusy] = useState(false);
    const toast = useToast();
    const save = async () => {
        setBusy(true);
        try {
            await api.post(`/shipping/shipments/${parcel.trackingId}/mark`, { mark: mark || null });
            toast.ok(mark ? 'Team mark saved.' : 'Team mark cleared.');
            onSaved();
        }
        catch (e) {
            toast.error(e);
        }
        finally {
            setBusy(false);
        }
    };
    return (<div className="row mt-8" style={{ gap: 8 }}>
      <label className="small" htmlFor={`tm-${parcel.key}`}>Team mark</label>
      <select id={`tm-${parcel.key}`} className="select sm" style={{ width: 'auto' }} value={mark} onChange={(e) => setMark(e.target.value)}>
        {TEAM_MARKS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
      </select>
      <Button size="sm" loading={busy} disabled={mark === (parcel.manual?.status ?? '')} onClick={save}>Save</Button>
    </div>);
}

export function OrderDrawer({ order, brand, onClose }) {
    const q = useApi(`/shipping/shipments/${encodeURIComponent(order)}${brand ? `?brand=${brand}` : ''}`);
    const d = q.data;
    return (<Drawer title={`Order ${order}`} onClose={onClose}>
      {q.error ? <ErrorState error={q.error} onRetry={q.reload}/> : !d ? <LoadingBlock rows={6}/> : (<div className="col" style={{ gap: 16 }}>
          {d.shopifyUrl ? <div><ShopifyOrderLink url={d.shopifyUrl} label="Open in Shopify"/></div> : null}
          {d.excluded ? <div className="callout warn"><Icon name="info"/><div>This order is {d.excluded}, so it is left out of the active figures.</div></div> : null}
          {d.packages.map((p) => (<Card key={p.key} title={<span className="row">{p.carrier || 'Unknown carrier'} <CatPill cat={p.cat} resolved={p.resolved}/></span>} sub={p.tracking ? undefined : 'No tracking number yet'}>
              <Kv items={[
                  ['Tracking', p.missingTracking ? 'Missing' : p.trackUrl ? <a href={p.trackUrl} target="_blank" rel="noreferrer">{p.tracking}</a> : p.tracking],
                  ['Stage', STAGE_LABEL[p.stage] ?? p.stage],
                  ['In stage', p.unconfirmed ? 'No delivery data for this carrier' : dayText(p.days)],
                  ['Order placed', p.orderCreatedAt ? fmtDateTime(p.orderCreatedAt) : '—'],
                  ['Dispatched', p.dispatchedAt ? fmtDateTime(p.dispatchedAt) : 'Not yet'],
                                    ['Last scan', p.lastScanAt ? `${fmtDateTime(p.lastScanAt)} — ${p.scanDescription || 'no description'}${p.location ? `, ${p.location}` : ''}` : 'No scan data'],
                  ['Carrier status', p.status.replace(/_/g, ' ') || '—'],
                  ...(p.resolved ? [['Resolved', `${p.resolved.label} (${p.resolved.by === 'team' ? `team${p.resolved.who ? `: ${p.resolved.who}` : ''}` : `carrier: ${p.resolved.detail || 'last update'}`})${p.resolved.at ? ` · ${timeAgo(p.resolved.at)}` : ''}`]] : []),
                  ...(p.reshipped ? [['Reshipped', `${p.reshipped.detail}${p.reshipped.newOrder && p.reshipped.newOrder !== order ? ` New order ${p.reshipped.newOrder}.` : ''}${p.reshipped.newTracking ? ` New tracking ${p.reshipped.newTracking}.` : ''} Close this old parcel in Shopify / Amazon.`]] : []),
                  ...(p.amazonStatus ? [['Amazon (MCF)', `${p.amazonStatus}${p.amazonAt ? ` · ${timeAgo(p.amazonAt)}` : ''}${p.amazonTracking && p.amazonTracking !== p.tracking ? ` · tracking ${p.amazonTracking}` : ''}`]] : []),
                  ['Team mark', p.manual ? `${TEAM_LABEL[p.manual.status] ?? p.manual.status}${p.manual.at ? ` · ${timeAgo(p.manual.at)}` : ''}` : 'None'],
                  ['Promised delivery', p.promisedAt ? fmtDateTime(p.promisedAt) : '—'],
                  ...(p.delayReason ? [['Delay reason', p.delayReason]] : []),
              ]}/>
              <p className="small" style={{ margin: '10px 0 0' }}><b>Next step:</b> {p.action}</p>
              {p.unconfirmed && p.trackingId ? <TeamMark parcel={p} onSaved={q.reload}/> : null}
              </Card>))}
          {d.packages.map((p) => (<Card key={`ev-${p.key}`} title="Tracking timeline" sub={d.packages.length > 1 ? `${p.carrier || 'Unknown carrier'} ${p.tracking || ''}` : undefined}>
              {p.events?.length ? (<ol className="alert-list" style={{ listStyle: 'none', margin: 0, padding: 0 }}>{[...p.events].reverse().map((e) => (<li key={e.at + e.description} className="alert-item"><span className={`sev ${e.status === 'delivered' ? 'info' : e.status === 'returned' || e.status === 'failed_delivery' ? 'critical' : 'warning'}`}/>
                    <span className="small"><b>{e.description}</b><span className="muted xs" style={{ display: 'block' }}>{fmtDateTime(e.at)}{e.location ? ` · ${e.location}` : ''}</span></span></li>))}</ol>) : <div className="muted small">{p.missingTracking ? 'No tracking number, so there are no scans.' : 'No carrier scan has been recorded yet.'}</div>}
            </Card>))}
          <Card title="Destination">
            <Kv items={[['Destination', d.destination ? `${d.destination.city}, ${d.destination.state} (city and state only)` : '—'], ...(d.items ?? []).map((i) => [`${i.qty} x`, i.name])]}/>
          </Card>
          <OrderActions order={order} detail={d} setData={q.setData} brand={brand}/>
          <Card title="Order check">
            {d.check ? (<Kv items={[
                  ['Fulfilment', d.check.fulfillment || '—'],
                  ['Payment', d.check.financial || '—'],
                  ['Cancelled', d.check.cancelled ? 'Yes' : 'No'],
                  ['Note says DONE', d.check.notesSayDone ? 'Yes' : 'No'],
                  ['Order value', fmtMoney(d.check.total, d.check.currency)],
                  ['Amazon (MCF)', d.check.amazon ? `${d.check.amazon}${d.check.amazonAt ? ` · ${timeAgo(d.check.amazonAt)}` : ''}` : (d.check.amazonKnown === false ? 'Not read yet' : 'No Amazon record')],
              ]}/>) : <div className="muted small">{d.checkAvailable ? 'No order check is stored for this order.' : 'Order checks are unavailable right now.'}</div>}
            <div className="muted xs mt-8">The order note itself is never shown here, only whether it says DONE.</div>
          </Card>
        </div>)}
    </Drawer>);
}

/** Tracking-number sheet check. PREVIEW ONLY: the server reports what would change and changes nothing. */
export function ImportPreview({ brand }) {
    const [text, setText] = useState('');
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState(null);
    const [result, setResult] = useState(null);
    const [carriers, setCarriers] = useState([]);
    const readFile = (file) => {
        if (!file)
            return;
        const reader = new FileReader();
        reader.onload = () => setText(String(reader.result ?? ''));
        reader.readAsText(file);
    };
    const fillSample = async () => {
        try {
            const r = await api.get(`/shipping/import/sample${brand ? `?brand=${brand}` : ''}`);
            setText(r.text);
            setCarriers(r.carriers ?? []);
            setResult(null);
        }
        catch (e) {
            setError(e);
        }
    };
    const check = async () => {
        setBusy(true);
        setError(null);
        try {
            const r = await api.post(`/shipping/import/preview${brand ? `?brand=${brand}` : ''}`, { text });
            setResult(r);
            if (r.carriers)
                setCarriers(r.carriers);
        }
        catch (e) {
            setResult(null);
            setError(e);
        }
        finally {
            setBusy(false);
        }
    };
    return (<Card title="Tracking number sheet (preview only)" sub="Paste or upload a CSV with the columns order_number, tracking_number, carrier. Nothing is saved anywhere: this only shows what would change.">
      <div className="col" style={{ gap: 10 }}>
        <textarea className="textarea" rows={5} value={text} onChange={(e) => setText(e.target.value)} placeholder={'order_number,tracking_number,carrier\n#1234,9400111202555842761234,USPS'} aria-label="Sheet contents"/>
        <div className="row-wrap">
          <input type="file" accept=".csv,text/csv,text/plain" onChange={(e) => readFile(e.target.files?.[0])} aria-label="Upload a CSV"/>
          <Button variant="primary" loading={busy} disabled={!text.trim()} onClick={check} icon="search">Check sheet</Button>
          <Button onClick={fillSample}>Use a sample sheet</Button>
          {carriers.length ? <span className="muted small">Carriers: {carriers.join(', ')}.</span> : null}
        </div>
        <ErrorState error={error}/>
        {result ? (<>
            <div className="small"><b>{result.rows.length}</b> rows · <b>{result.counts.will_update}</b> would update · <b>{result.counts.skip_has_tracking}</b> already have tracking · <b>{result.counts.ambiguous}</b> need a choice · <b>{result.counts.error}</b> errors <span className="muted">· {result.note}</span></div>
            <div className="table-wrap"><table className="t compact">
                <thead><tr><th>Line</th><th>Order</th><th>Tracking</th><th>Carrier</th><th>Result</th><th>Why</th></tr></thead>
                <tbody>{result.rows.map((r) => (<tr key={r.line}>
                    <td>{r.line}</td><td>{r.order || '—'}</td><td className="mono small">{r.tracking || '—'}</td><td>{r.carrier || '—'}</td>
                    <td><Pill tone={OUTCOME[r.outcome]?.tone ?? 'neutral'}>{OUTCOME[r.outcome]?.label ?? r.outcome}</Pill></td><td className="small">{r.message}</td></tr>))}</tbody>
              </table></div>
          </>) : null}
      </div>
    </Card>);
}
