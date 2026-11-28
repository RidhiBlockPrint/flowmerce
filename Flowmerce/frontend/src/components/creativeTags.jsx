'use client';
/* Creative Strategist, what it monitors: winners and losers by tag (on Insights), the Ad tags tab, the
 * Product context tab and the rules / season calendar. Every figure comes from /api/creative; Claude only
 * suggests tags and a person confirms or corrects them (a manual edit is never changed by Claude again). */
import { useEffect, useMemo, useState } from 'react';
import { api, qs, useApi } from '../lib/api';
import { fmtInt } from '../lib/format';
import { fmtMoney } from '../lib/shipping';
import { Button, Card, Empty, ErrorState, Field, LoadingBlock, Pill, Tabs } from './ui';
import { Dialog, useToast } from './overlays';

export const DIMENSIONS = [
    { key: 'hook_type', label: 'Hook' },
    { key: 'visual_style', label: 'Visual' },
    { key: 'format', label: 'Format' },
    { key: 'print', label: 'Print' },
    { key: 'color', label: 'Color' },
    { key: 'category', label: 'Category' },
    { key: 'season', label: 'Season' },
    { key: 'product', label: 'Product' },
];

const SPECIAL = {
    ugc_person: 'UGC / person', stripe_check: 'Stripe / check', yellow_mustard: 'Yellow / mustard', white_cream: 'White / cream',
    beige_natural: 'Beige / natural', indigo_blue: 'Indigo / blue', animal_bird: 'Animal / bird', botanical_leaf: 'Botanical / leaf',
    offer_discount: 'Offer / discount', problem_solution: 'Problem → solution', before_after: 'Before / after', all_season: 'All season',
    untagged: 'Not tagged yet', rsa: 'Search ad (RSA)', ugc: 'UGC',
};
/** "craft_story" -> "Craft story". */
export function tagLabel(v) {
    if (v === null || v === undefined || v === '') return '—';
    if (SPECIAL[v]) return SPECIAL[v];
    const s = String(v).replace(/[_-]+/g, ' ');
    return s.charAt(0).toUpperCase() + s.slice(1);
}

const VERDICT = {
    winner: { label: 'Winner', tone: 'ok' },
    average: { label: 'Average', tone: 'info' },
    loser: { label: 'Loser', tone: 'crit' },
    insufficient_data: { label: 'Not enough data', tone: 'neutral' },
};
export function VerdictPill({ verdict }) {
    const v = VERDICT[verdict] ?? { label: verdict, tone: 'neutral' };
    return <Pill tone={v.tone} dot>{v.label}</Pill>;
}
function SourcePill({ source, confirmed }) {
    if (!source) return <Pill tone="warn">Not tagged</Pill>;
    if (source === 'manual') return <Pill tone="info">Manual</Pill>;
    return confirmed ? <Pill tone="ok">AI · confirmed</Pill> : <Pill tone="warn" title="Suggested by Claude, not reviewed yet">AI · review</Pill>;
}

const money = (currency) => (v) => (v === null || v === undefined ? '—' : fmtMoney(v, currency || 'USD'));
const pct = (v) => (v === null || v === undefined ? '—' : `${v}%`);
const roas = (v) => (v === null || v === undefined ? '—' : `${v}x`);

function Thumb({ src, alt }) {
    const box = { width: 40, height: 40, borderRadius: 8, flexShrink: 0, background: 'var(--surface-3)', border: '1px solid var(--line-2)', display: 'block' };
    // eslint-disable-next-line @next/next/no-img-element
    return src ? <img src={src} alt={alt || ''} loading="lazy" referrerPolicy="no-referrer" style={{ ...box, objectFit: 'cover' }}/> : <span style={box} aria-hidden/>;
}

/** Run an action with a busy flag; toast the result or the error; then call onDone. */
function useAction(onDone) {
    const toast = useToast();
    const [busy, setBusy] = useState(null);
    const run = async (key, fn, message) => {
        setBusy(key);
        try {
            const res = await fn();
            const text = typeof message === 'function' ? message(res) : message;
            if (text) toast.ok(text);
            if (res?.failed?.length) toast.error(`${res.failed.length} could not be tagged: ${res.failed[0].error}`);
            onDone?.(res);
            return res;
        }
        catch (e) {
            toast.error(e);
            return null;
        }
        finally {
            setBusy(null);
        }
    };
    return { busy, run };
}

/** Edit dialog for tags. `fields`: [{ key, label, options }]; a field without options is free text. */
function TagDialog({ title, sub, fields, initial, onSave, onClose }) {
    const [values, setValues] = useState(() => Object.fromEntries(fields.map((f) => [f.key, initial?.[f.key] ?? ''])));
    const [saving, setSaving] = useState(false);
    const toast = useToast();
    const save = async () => {
        const changed = Object.fromEntries(fields.filter((f) => values[f.key] !== '' && values[f.key] !== (initial?.[f.key] ?? '')).map((f) => [f.key, values[f.key]]));
        setSaving(true);
        try {
            await onSave(Object.keys(changed).length ? changed : { confirmed: true });
            toast.ok(Object.keys(changed).length ? 'Saved. Claude will not change these tags again.' : 'Confirmed.');
            onClose();
        }
        catch (e) {
            toast.error(e);
        }
        finally {
            setSaving(false);
        }
    };
    return (<Dialog title={title} sub={sub} onClose={onClose} footer={<>
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button variant="primary" icon="check" loading={saving} onClick={save}>Save</Button>
      </>}>
      <div className="form-grid">
        {fields.map((f) => (<Field key={f.key} label={f.label} full={!f.options}>
            {f.options ? (<select className="select" value={values[f.key]} onChange={(e) => setValues({ ...values, [f.key]: e.target.value })}>
                <option value="">—</option>
                {f.options.map((o) => <option key={o} value={o}>{tagLabel(o)}</option>)}
              </select>) : (<input className="input" value={values[f.key]} maxLength={300} onChange={(e) => setValues({ ...values, [f.key]: e.target.value })}/>)}
          </Field>))}
      </div>
      <p className="small muted mt-12">Saving without changes confirms the current tags.</p>
    </Dialog>);
}

/* ------------------------------------------------------------------ Insights: what wins and loses */
export function WhatWinsSection({ brand, range }) {
    const q = useApi(`/creative/patterns${qs({ brand, from: range.from, to: range.to })}`);
    const [dim, setDim] = useState('hook_type');
    if (q.error) return <ErrorState error={q.error} onRetry={q.reload}/>;
    if (!q.data) return <LoadingBlock rows={4}/>;
    const d = q.data;
    const m = money(d.currency);
    const groups = d.dimensions[dim] ?? [];
    return (<>
      <div className="stat-row mb-16">
        {['winner', 'average', 'loser', 'insufficient_data'].map((v) => (<a key={v} href={`/creative${qs({ tab: 'tags', store: brand, verdict: v })}`} className="stat">
            <div className="v">{fmtInt(d.verdicts[v])}</div><div className="l"><VerdictPill verdict={v}/></div>
          </a>))}
        <a href={`/creative${qs({ tab: 'tags', store: brand, review: 1 })}`} className="stat"><div className="v">{fmtInt(d.untagged)}</div><div className="l">Ads without tags</div></a>
      </div>
      <div className="grid cols-2 mb-16">
        <AdList title="Top winners" sub={`ROAS at or above ${roas(d.rule.target_roas)} with enough spend`} ads={d.topWinners} m={m} empty="No ad has reached the target ROAS with enough spend yet."/>
        <AdList title="Biggest losers" sub={`ROAS below ${roas(d.rule.breakeven_roas)}, most spend first`} ads={d.topLosers} m={m} empty="No ad is below break-even with enough spend."/>
      </div>
      <Card flush title="What wins and loses" sub={`Ads grouped by each tag. A group's verdict uses the same rules as a single ad: at least ${m(d.rule.min_spend)} spend and ${fmtInt(d.rule.min_impressions)} impressions.`}>
        <div style={{ padding: '0 16px' }}><Tabs tabs={DIMENSIONS} value={dim} onChange={setDim}/></div>
        {!groups.length ? <Empty icon="analytics" title="No data yet">No ads delivered in this period.</Empty> : (<div className="table-wrap"><table className="t compact">
            <thead><tr><th>{DIMENSIONS.find((x) => x.key === dim)?.label}</th><th className="r">Ads</th><th>Win / avg / lose / too little</th><th className="r">Spend</th><th className="r">ROAS</th><th className="r">CPA</th><th className="r">CTR</th><th className="r">Hook</th><th className="r">Hold</th><th>Verdict</th></tr></thead>
            <tbody>{groups.map((g) => (<tr key={g.value}>
                <td><b>{dim === 'product' && g.value !== 'untagged' ? g.value : tagLabel(g.value)}</b></td>
                <td className="r">{fmtInt(g.ads)}</td>
                <td className="small nowrap"><span style={{ color: 'var(--ok)' }}>{g.winners}</span> / {g.average} / <span style={{ color: 'var(--crit)' }}>{g.losers}</span> / <span className="faint">{g.insufficient}</span></td>
                <td className="r">{m(g.sums.spend)}</td>
                <td className="r"><b>{roas(g.rates.roas)}</b></td>
                <td className="r">{m(g.rates.cpa)}</td>
                <td className="r">{pct(g.rates.ctr)}</td>
                <td className="r">{pct(g.rates.hookRate)}</td>
                <td className="r">{pct(g.rates.holdRate)}</td>
                <td><VerdictPill verdict={g.verdict}/></td>
              </tr>))}</tbody>
          </table></div>)}
      </Card>
      <div className="mt-16"><RulesCards brand={brand} onSaved={q.reload}/></div>
    </>);
}

function AdList({ title, sub, ads, m, empty }) {
    return (<Card flush title={title} sub={sub}>
      {!ads.length ? <Empty icon="inbox" title="None yet">{empty}</Empty> : (<div className="table-wrap"><table className="t compact"><tbody>
          {ads.map((a) => (<tr key={a.adId}>
              <td style={{ width: 52 }}><Thumb src={a.thumbnailUrl} alt={a.name}/></td>
              <td><b>{a.name}</b><div className="faint xs">{tagLabel(a.tags.hook_type)} · {tagLabel(a.tags.visual_style)} · {tagLabel(a.tags.format)}</div></td>
              <td className="r nowrap"><b>{roas(a.rates.roas)}</b><div className="faint xs">{m(a.sums.spend)}</div></td>
            </tr>))}
        </tbody></table></div>)}
    </Card>);
}

const RULE_FIELDS = [
    ['min_spend', 'Minimum spend to judge an ad', 'In the ad account currency. Below it, the ad is “not enough data”.'],
    ['min_impressions', 'Minimum impressions to judge an ad', ''],
    ['target_roas', 'Winner at ROAS of at least', ''],
    ['breakeven_roas', 'Loser below ROAS of', 'Usually your break-even ROAS.'],
];

function RulesCards({ brand, onSaved }) {
    const q = useApi(`/creative/rules${qs({ brand })}`);
    const [rule, setRule] = useState(null);
    const [cal, setCal] = useState([]);
    useEffect(() => { if (q.data) { setRule(q.data.rule); setCal(q.data.seasons); } }, [q.data]);
    const { busy, run } = useAction(() => { q.reload(); onSaved?.(); });
    if (q.error) return <ErrorState error={q.error} onRetry={q.reload}/>;
    if (!q.data || !rule) return null;
    const demo = q.data.source === 'demo';
    return (<div className="grid cols-2">
      <Card title="Winner and loser rules" sub={demo ? 'Defaults; editable once an ad account is connected.' : undefined}
        foot={<Button size="sm" variant="primary" icon="check" disabled={demo} loading={busy === 'rule'} onClick={() => run('rule', () => api.put(`/creative/rules${qs({ brand })}`, Object.fromEntries(Object.entries(rule).map(([k, v]) => [k, Number(v)]))), 'Rules saved.')}>Save rules</Button>}>
        <div className="form-grid">
          {RULE_FIELDS.map(([k, label, hint]) => (<Field key={k} label={label} hint={hint}>
              <input className="input" type="number" min="0" step="any" value={rule[k] ?? ''} disabled={demo} onChange={(e) => setRule({ ...rule, [k]: e.target.value })}/>
            </Field>))}
        </div>
      </Card>
      <Card title="Season calendar" sub="An ad's season is the season of its first day with impressions. Dates are MM-DD; a range may wrap past New Year."
        foot={<Button size="sm" variant="primary" icon="check" disabled={demo} loading={busy === 'seasons'} onClick={() => run('seasons', () => api.put(`/creative/seasons${qs({ brand })}`, { seasons: cal }), 'Season calendar saved.')}>Save seasons</Button>}>
        <table className="t compact"><thead><tr><th>Season</th><th>From</th><th>To</th></tr></thead><tbody>
          {cal.map((s, i) => (<tr key={s.season}>
              <td><Pill>{tagLabel(s.season)}</Pill></td>
              {['start', 'end'].map((k) => (<td key={k}><input className="input sm" style={{ width: 72 }} value={s[k]} disabled={demo} aria-label={`${s.season} ${k}`}
                  onChange={(e) => setCal(cal.map((r, j) => (j === i ? { ...r, [k]: e.target.value } : r)))}/></td>))}
            </tr>))}
        </tbody></table>
      </Card>
    </div>);
}

/* ------------------------------------------------------------------ Ad tags tab */
export function AdTagsTab({ brand, range, verdict, review, setFilter }) {
    const q = useApi(`/creative/patterns${qs({ brand, from: range.from, to: range.to })}`);
    const tax = useApi('/creative/taxonomy');
    const [search, setSearch] = useState('');
    const [editing, setEditing] = useState(null);
    const [varying, setVarying] = useState(null);
    const { busy, run } = useAction(() => q.reload());
    const rows = useMemo(() => (q.data?.ads ?? []).filter((a) => (!verdict || a.verdict === verdict)
        && (!review || !a.tags.source || (a.tags.source === 'ai' && !a.tags.confirmed))
        && (!search || `${a.name} ${a.headline ?? ''} ${a.primaryText ?? ''}`.toLowerCase().includes(search.toLowerCase()))), [q.data, verdict, review, search]);
    if (q.error) return <ErrorState error={q.error} onRetry={q.reload}/>;
    if (!q.data) return <LoadingBlock rows={8}/>;
    const d = q.data;
    const m = money(d.currency);
    const demo = d.source === 'demo';
    return (<>
      <div className="toolbar">
        <select className="select sm" style={{ width: 'auto' }} value={verdict} onChange={(e) => setFilter({ verdict: e.target.value })} aria-label="Verdict">
          <option value="">All verdicts</option>
          {Object.entries(VERDICT).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
        </select>
        <label className="row small"><input type="checkbox" checked={review} onChange={(e) => setFilter({ review: e.target.checked ? '1' : '' })}/> Needs review only</label>
        <input className="input sm" style={{ width: 240 }} placeholder="Search name or copy" value={search} onChange={(e) => setSearch(e.target.value)}/>
        <span className="small muted" style={{ marginLeft: 'auto' }}>{rows.length} ads</span>
        <Button size="sm" icon="sparkle" variant="primary" disabled={demo || !d.untagged} loading={busy === 'tag'}
          onClick={() => run('tag', () => api.post(`/creative/tags/run${qs({ brand })}`, { limit: 20 }), (r) => `Claude tagged ${r.tagged} ads; ${r.untaggedLeft} left.`)}>Tag 20 with Claude</Button>
      </div>
      {demo ? <div className="callout info mb-12"><div>Sample ads: tags can be set once an ad account is connected.</div></div> : null}
      <div className="card flush"><div className="table-wrap"><table className="t compact">
        <thead><tr><th/><th>Ad</th><th>Hook</th><th>Visual</th><th>Format</th><th>Print / color</th><th>Product · season</th><th className="r">Spend</th><th className="r">ROAS</th><th className="r">CTR</th><th>Verdict</th><th>Tags</th><th/></tr></thead>
        <tbody>{rows.map((a) => (<tr key={a.adId} className={demo ? undefined : 'clickable'} onClick={demo ? undefined : () => setEditing(a)}>
            <td style={{ width: 52 }}><Thumb src={a.thumbnailUrl} alt={a.name}/></td>
            <td style={{ maxWidth: 320 }}><b>{a.name}</b><div className="faint xs ellipsis" title={a.primaryText ?? ''}>{a.tags.hook_text ? `“${a.tags.hook_text}”` : (a.headline || a.primaryText || '')}</div></td>
            <td className="small nowrap">{tagLabel(a.tags.hook_type)}</td>
            <td className="small nowrap">{tagLabel(a.tags.visual_style)}</td>
            <td className="small nowrap">{tagLabel(a.tags.format)}</td>
            <td className="small nowrap">{tagLabel(a.tags.print)} · {tagLabel(a.tags.color)}</td>
            <td className="small">{a.productTitle ?? <span className="faint">No product link</span>}<div className="faint xs">{tagLabel(a.tags.season)}</div></td>
            <td className="r">{m(a.sums.spend)}</td>
            <td className="r"><b>{roas(a.rates.roas)}</b></td>
            <td className="r">{pct(a.rates.ctr)}</td>
            <td><VerdictPill verdict={a.verdict}/></td>
            <td><SourcePill source={a.tags.source} confirmed={a.tags.confirmed}/></td>
            <td onClick={(e) => e.stopPropagation()}>{a.verdict === 'winner' && !demo
                ? <Button size="sm" variant="ghost" icon="sparkle" onClick={() => setVarying(a)}>Variations</Button> : null}</td>
          </tr>))}</tbody>
      </table></div>
      {!rows.length ? <Empty icon="image" title="No ads match">{d.ads.length ? 'Change the filters or the period.' : 'No ads delivered in this period.'}</Empty> : null}
      </div>
      {editing && tax.data ? (<TagDialog title="Ad tags" sub={editing.name} initial={editing.tags} onClose={() => setEditing(null)}
          onSave={async (body) => { await api.patch(`/creative/tags/${encodeURIComponent(editing.adId)}${qs({ brand })}`, body); q.reload(); }}
          fields={[
            { key: 'hook_type', label: 'Hook type', options: tax.data.hook_type },
            { key: 'visual_style', label: 'Visual style', options: tax.data.visual_style },
            { key: 'print', label: 'Print', options: tax.data.print },
            { key: 'color', label: 'Color', options: tax.data.color },
            { key: 'hook_text', label: 'Hook (opening line)' },
          ]}/>) : null}
      {varying ? <AdVariationsDialog brand={brand} ad={varying} onClose={() => setVarying(null)}/> : null}
    </>);
}

/** Claude's variations of one winning ad: one variable changes, the rest is kept. Each can be saved
 * as a concept (and from there get a designer brief). */
function AdVariationsDialog({ brand, ad, onClose }) {
    const toast = useToast();
    const [state, setState] = useState({ loading: true, data: null, error: null });
    const [saved, setSaved] = useState({});
    useEffect(() => {
        let gone = false;
        api.post(`/creative/ads/${encodeURIComponent(ad.adId)}/variations${qs({ brand })}`)
            .then((data) => { if (!gone) setState({ loading: false, data, error: null }); })
            .catch((error) => { if (!gone) setState({ loading: false, data: null, error }); });
        return () => { gone = true; };
    }, [brand, ad.adId]);
    const save = async (v, i) => {
        setSaved((s) => ({ ...s, [i]: 'saving' }));
        try {
            await api.post(`/creative/concepts${qs({ brand })}`, {
                title: v.label, hook: v.hook, angle: v.what_changed, message: v.why, origin: 'ai',
                evidence: [`Variation of the winning ad "${ad.name}" (ROAS ${ad.rates.roas ?? '—'}x); changes the ${state.data.variable} only.`],
            });
            setSaved((s) => ({ ...s, [i]: 'saved' }));
        }
        catch (e) {
            toast.error(e);
            setSaved((s) => ({ ...s, [i]: null }));
        }
    };
    const d = state.data;
    return (<Dialog title="Variations from a winning ad" sub={ad.name} onClose={onClose} wide footer={<Button variant="ghost" onClick={onClose}>Close</Button>}>
      {state.loading ? <LoadingBlock rows={4}/> : state.error ? <ErrorState error={state.error}/> : (<div className="col" style={{ gap: 12 }}>
          <div className="small"><b>Keep the same:</b> {d.kept} <span className="faint">(changing only: {tagLabel(d.variable)})</span></div>
          {d.variations.map((v, i) => (<Card key={i} flush className="pad-sm" title={v.label}
              actions={saved[i] === 'saved' ? <Pill tone="ok">Saved to Concepts</Pill>
                  : <Button size="sm" variant="ghost" icon="star" loading={saved[i] === 'saving'} onClick={() => save(v, i)}>Save to Concepts</Button>}>
              <div className="small"><b>Hook:</b> &ldquo;{v.hook}&rdquo;</div>
              <div className="small mt-4"><b>What changes:</b> {v.what_changed}</div>
              <div className="small faint mt-4">{v.why}</div>
            </Card>))}
          {d.cost_usd ? <div className="faint xs">Claude cost: ${Number(d.cost_usd).toFixed(2)}</div> : null}
        </div>)}
    </Dialog>);
}

/* ------------------------------------------------------------------ Product context tab */
export function ProductsTab({ brand }) {
    const q = useApi(`/creative/products${qs({ brand })}`);
    const rules = useApi(`/creative/rules${qs({ brand })}`);
    const tax = useApi('/creative/taxonomy');
    const [review, setReview] = useState(false);
    const [search, setSearch] = useState('');
    const [editing, setEditing] = useState(null);
    const { busy, run } = useAction(() => q.reload());
    const rows = useMemo(() => (q.data?.products ?? []).filter((p) => (!review || !p.source || (p.source === 'ai' && !p.confirmed))
        && (!search || `${p.title} ${p.product_type}`.toLowerCase().includes(search.toLowerCase()))), [q.data, review, search]);
    if (q.error) return <ErrorState error={q.error} onRetry={q.reload}/>;
    if (!q.data) return <LoadingBlock rows={8}/>;
    const demo = rules.data?.source === 'demo';
    const untagged = (q.data.products ?? []).filter((p) => !p.source).length;
    return (<>
      <div className="toolbar">
        <label className="row small"><input type="checkbox" checked={review} onChange={(e) => setReview(e.target.checked)}/> Needs review only</label>
        <input className="input sm" style={{ width: 240 }} placeholder="Search title or type" value={search} onChange={(e) => setSearch(e.target.value)}/>
        <span className="small muted" style={{ marginLeft: 'auto' }}>{rows.length} products</span>
        <Button size="sm" icon="refresh" disabled={demo} loading={busy === 'sync'} onClick={() => run('sync', () => api.post(`/creative/products/sync${qs({ brand })}`), (r) => `Read ${r.products} products from Shopify.`)}>Sync from Shopify</Button>
        <Button size="sm" icon="sparkle" variant="primary" disabled={demo || !untagged} loading={busy === 'tag'} onClick={() => run('tag', () => api.post(`/creative/products/tag${qs({ brand })}`, { limit: 20 }), (r) => `Claude tagged ${r.tagged} products; ${r.untaggedLeft} left.`)}>Tag 20 with Claude</Button>
      </div>
      {demo ? <div className="callout info mb-12"><div>Product context is read from Shopify once an ad account is connected; the page is showing sample data.</div></div> : null}
      <div className="card flush"><div className="table-wrap"><table className="t compact">
        <thead><tr><th/><th>Product</th><th>Print</th><th>Color</th><th>Category</th><th>Season fit</th><th>Tags</th><th/></tr></thead>
        <tbody>{rows.map((p) => (<tr key={p.handle} className="clickable" onClick={() => setEditing(p)}>
            <td style={{ width: 52 }}><Thumb src={p.image_url} alt={p.title}/></td>
            <td><b>{p.title}</b><div className="faint xs">{p.product_type || p.handle}</div></td>
            <td className="small nowrap">{tagLabel(p.print)}</td>
            <td className="small nowrap">{tagLabel(p.color)}</td>
            <td className="small nowrap">{tagLabel(p.category)}</td>
            <td className="small nowrap">{tagLabel(p.season_fit)}</td>
            <td><SourcePill source={p.source} confirmed={p.confirmed}/></td>
            <td onClick={(e) => e.stopPropagation()}>{p.source === 'ai' && !p.confirmed ? <Button size="sm" variant="ghost" icon="check" loading={busy === p.handle}
                onClick={() => run(p.handle, () => api.patch(`/creative/products/${encodeURIComponent(p.handle)}${qs({ brand })}`, { confirmed: true }), 'Confirmed.')}>Confirm</Button> : null}</td>
          </tr>))}</tbody>
      </table></div>
      {!rows.length ? <Empty icon="sheet" title="No products here">{q.data.products?.length ? 'Change the filter.' : demo ? 'Shown once an ad account is connected.' : 'Sync products from Shopify to see them here.'}</Empty> : null}
      </div>
      {editing && tax.data ? (<TagDialog title="Product attributes" sub={editing.title} initial={editing} onClose={() => setEditing(null)}
          onSave={async (body) => { await api.patch(`/creative/products/${encodeURIComponent(editing.handle)}${qs({ brand })}`, body); q.reload(); }}
          fields={[
            { key: 'print', label: 'Print', options: tax.data.print },
            { key: 'color', label: 'Color', options: tax.data.color },
            { key: 'category', label: 'Category', options: tax.data.category },
            { key: 'season_fit', label: 'Season fit', options: tax.data.season_fit },
          ]}/>) : null}
    </>);
}
