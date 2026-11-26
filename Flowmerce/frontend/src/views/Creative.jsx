'use client';
/* Creative Strategist: what the ads show (by format and hook), saved concept ideas with a ready brief, and the
 * creative pack Claude writes from those findings. One store at a time, like CRO: when the top bar says "All",
 * the page shows its own Ridhi / CPC switch. No tab bar: the sidebar's menu opens Insights / Concepts / AI pack
 * (?tab=), and the title names the open one. */
import { useEffect, useRef, useState } from 'react';
import { api, qs, useApi } from '../lib/api';
import { useBrandParam } from '../lib/app';
import { useSearchParams } from '../lib/nav';
import { Button, Card, Empty, ErrorState, LoadingBlock, PageHead, Pill } from '../components/ui';
import { Icon } from '../components/Icon';
import { useToast } from '../components/overlays';
import { fmtInt } from '../lib/format';
import { fmtMoney } from '../lib/shipping';

const STORES = [{ key: 'ridhi', label: 'Ridhi' }, { key: 'cpc', label: 'CPC' }];
const TABS = [
    { key: 'overview', label: 'Insights' },
    { key: 'concepts', label: 'Concepts' },
    { key: 'pack', label: 'AI pack' },
];
const FUNNEL_LABEL = { tof: 'Top of funnel', mof: 'Middle of funnel', bof: 'Bottom of funnel' };
const FUNNEL_TONE = { tof: 'info', mof: 'neutral', bof: 'ok' };

const pct1 = (v) => (v === null || v === undefined ? '—' : `${v}%`);
// Ridhi's Meta account reports spend in INR, CPC's in USD: never a hardcoded currency for ad figures.
const moneyIn = (currency) => (v) => (v === null || v === undefined ? '—' : fmtMoney(v, currency || 'USD'));
// Claude's own cost is always billed in USD, regardless of the store's ad spend currency.
const usd = moneyIn('USD');

function Seg({ options, value, onChange, label }) {
    return (<div className="seg sm" role="group" aria-label={label} style={{ flexWrap: 'wrap', maxWidth: '100%' }}>
      {options.map((o) => (<button key={o.key} type="button" aria-pressed={o.key === value} onClick={() => onChange(o.key)}>{o.label}</button>))}
    </div>);
}

function SourceTag({ source }) {
    return <Pill tone={source === 'demo' ? 'info' : 'ok'}>{source === 'demo' ? 'Demo data' : 'Live data'}</Pill>;
}

export default function Creative() {
    const [sp, setSp] = useSearchParams();
    const globalBrand = useBrandParam();
    const brand = globalBrand ?? (STORES.some((s) => s.key === sp.get('store')) ? sp.get('store') : 'ridhi');
    const tab = TABS.some((t) => t.key === sp.get('tab')) ? sp.get('tab') : 'overview';
    const update = (patch) => {
        const next = new URLSearchParams(sp);
        for (const [k, v] of Object.entries(patch)) {
            if (v === null || v === '' || v === undefined) next.delete(k);
            else next.set(k, v);
        }
        setSp(next, { replace: true });
    };
    const title = tab === 'overview' ? 'Creative Strategist' : `Creative Strategist · ${TABS.find((t) => t.key === tab).label}`;
    return (<>
      <PageHead title={title} sub={globalBrand ? undefined
            : <Seg options={STORES} value={brand} onChange={(store) => update({ store })} label="Store"/>}/>
      <div className="mt-16">
        {tab === 'concepts' ? <ConceptsTab brand={brand}/>
            : tab === 'pack' ? <PackTab brand={brand}/>
                : <InsightsTab brand={brand}/>}
      </div>
    </>);
}

/* ------------------------------------------------------------------ Insights */
function GroupTable({ title, note, rows, metricKey, metricLabel, metricFmt = pct1, money }) {
    return (<Card title={title} sub={note} flush>
      {!rows.length ? <Empty icon="analytics" title="No data yet">Nothing to compare for this period.</Empty> : (
          <div className="table-wrap"><table className="t compact">
            <thead><tr><th>Group</th><th className="r">Ads</th><th className="r">Spend</th><th className="r">Impressions</th><th className="r">CTR</th><th className="r">ROAS</th><th className="r">{metricLabel}</th><th>Enough data</th></tr></thead>
            <tbody>
              {rows.map((g) => (<tr key={g.key}>
                  <td><b>{g.label || g.key}</b>{g.examples?.length ? <div className="faint xs">{g.examples.join(' · ')}</div> : null}</td>
                  <td className="r">{fmtInt(g.ads)}</td>
                  <td className="r">{money(g.spend)}</td>
                  <td className="r">{fmtInt(g.impressions)}</td>
                  <td className="r">{pct1(g.ctr)}</td>
                  <td className="r">{g.roas === null || g.roas === undefined ? '—' : `${g.roas}x`}</td>
                  <td className="r">{metricFmt(g[metricKey])}</td>
                  <td>{g.sampleOk ? <Pill tone="ok">Yes</Pill> : <Pill tone="warn">Not yet</Pill>}</td>
                </tr>))}
            </tbody>
          </table></div>)}
    </Card>);
}

function ComparisonCard({ title, cmp, money }) {
    if (!cmp || !cmp.usable)
        return (<Card title={title}><Empty icon="analytics" title="Not enough data">No group has enough spend and impressions yet to compare on this.</Empty></Card>);
    const fmt = cmp.metric === 'ctr' || cmp.metric === 'hook_rate' ? pct1 : cmp.metric === 'cpa' ? money : (v) => (v === null ? '—' : `${v}x`);
    return (<Card title={title} sub={`${cmp.usable} group${cmp.usable === 1 ? '' : 's'} had enough data; median ${fmt(cmp.median)}`}>
      <div className="grid cols-2">
        <div><div className="muted xs">Best</div><div className="strong">{cmp.best.label || cmp.best.key}</div><div className="small">{fmt(cmp.best[cmp.metric === 'hook_rate' ? 'hookRate' : cmp.metric])}</div></div>
        <div><div className="muted xs">Worst</div><div className="strong">{cmp.worst.label || cmp.worst.key}</div><div className="small">{fmt(cmp.worst[cmp.metric === 'hook_rate' ? 'hookRate' : cmp.metric])}</div></div>
      </div>
    </Card>);
}

function InsightsTab({ brand }) {
    const q = useApi(`/creative/insights${qs({ brand })}`);
    if (q.error)
        return <ErrorState error={q.error} onRetry={q.reload}/>;
    if (!q.data)
        return <LoadingBlock rows={6}/>;
    const d = q.data;
    const money = moneyIn(d.currency);
    return (<>
      <div className="row-wrap mb-12" style={{ alignItems: 'center', gap: 8 }}>
        <SourceTag source={d.source}/>
        <span className="muted small">{d.from} to {d.to} · {fmtInt(d.adsSeen)} ads seen{d.currency ? ` · spend in ${d.currency}` : ''}</span>
      </div>
      <div className="grid cols-3 mb-16">
        <ComparisonCard title="Format: ROAS" cmp={d.comparisons.formatRoas} money={money}/>
        <ComparisonCard title="Hook: click-through rate" cmp={d.comparisons.hookCtr} money={money}/>
        <ComparisonCard title="Format: hook rate (3s video views)" cmp={d.comparisons.formatHookRate} money={money}/>
      </div>
      <GroupTable title="By format" note="Image, video, carousel and search, compared on spend and results." rows={d.formats} metricKey="hookRate" metricLabel="Hook rate" money={money}/>
      <div className="mt-16"><GroupTable title="By hook" note="Grouped by the first words of the ad's own copy. Not available until the ad's own copy text is synced." rows={d.hooks} metricKey="holdRate" metricLabel="Hold rate" money={money}/></div>
      <div className="mt-16"><GroupTable title="By platform" note="Meta and Google, side by side." rows={d.platforms} metricKey="cpa" metricLabel="Cost per purchase" metricFmt={money} money={money}/></div>
      <div className="muted xs mt-16">{d.note} Minimum for &ldquo;enough data&rdquo;: {fmtInt(d.thresholds.minImpressions)} impressions and {money(d.thresholds.minSpend)} spend.</div>
    </>);
}

/* ------------------------------------------------------------------ Concepts */
function Brief({ brand, conceptId }) {
    const [markdown, setMarkdown] = useState(null);
    const [loading, setLoading] = useState(false);
    const toast = useToast();
    useEffect(() => {
        let gone = false;
        setLoading(true);
        api.get(`/creative/concepts/${conceptId}/brief${qs({ brand })}`)
            .then((r) => { if (!gone) setMarkdown(r.markdown); })
            .catch((e) => { if (!gone) toast.error(e); })
            .finally(() => { if (!gone) setLoading(false); });
        return () => { gone = true; };
    }, [brand, conceptId]); // eslint-disable-line react-hooks/exhaustive-deps
    if (loading)
        return <LoadingBlock rows={3}/>;
    return <pre className="brief-markdown" style={{ whiteSpace: 'pre-wrap', fontFamily: 'inherit', margin: 0 }}>{markdown}</pre>;
}

function Variations({ brand, concept }) {
    const [state, setState] = useState({ loading: false, data: null });
    const toast = useToast();
    const ask = async () => {
        setState({ loading: true, data: null });
        try {
            const r = await api.post(`/creative/variations${qs({ brand })}`, { concept });
            setState({ loading: false, data: r });
        }
        catch (e) {
            toast.error(e);
            setState({ loading: false, data: null });
        }
    };
    if (state.loading)
        return <LoadingBlock rows={3}/>;
    if (!state.data)
        return <Button size="sm" variant="ghost" icon="sparkle" onClick={ask}>Get variations from Claude</Button>;
    return (<div className="col" style={{ gap: 8 }}>
      <div className="small"><b>Keeping:</b> {state.data.kept} <span className="faint">(changing: {state.data.variable})</span></div>
      {state.data.variations.map((v, i) => (<Card key={i} title={v.label} flush className="pad-sm">
          <div className="small"><b>Hook:</b> {v.hook}</div>
          <div className="small"><b>What changed:</b> {v.what_changed}</div>
          <div className="small faint">{v.why}</div>
        </Card>))}
    </div>);
}

function ConceptCard({ brand, concept }) {
    const [open, setOpen] = useState(null);   // null | 'brief' | 'variations'
    const evidence = Array.isArray(concept.evidence) ? concept.evidence : concept.evidence ? [concept.evidence] : [];
    return (<Card title={concept.title}
      actions={<Pill tone={FUNNEL_TONE[concept.funnel_stage] ?? 'neutral'}>{FUNNEL_LABEL[concept.funnel_stage] ?? concept.funnel_stage}</Pill>}>
      <div className="small"><b>Hook:</b> &ldquo;{concept.hook}&rdquo;</div>
      <div className="small mt-4"><b>Angle:</b> {concept.angle}</div>
      <div className="small mt-4">{concept.message}</div>
      {concept.offer ? <div className="small mt-4"><b>Offer:</b> {concept.offer}</div> : null}
      {evidence.length ? <ul className="small faint" style={{ margin: '8px 0 0', paddingLeft: 18 }}>{evidence.map((e, i) => <li key={i}>{e}</li>)}</ul> : null}
      <div className="row-wrap mt-12" style={{ gap: 8 }}>
        <Button size="sm" variant="ghost" onClick={() => setOpen(open === 'brief' ? null : 'brief')}>{open === 'brief' ? 'Hide brief' : 'View brief'}</Button>
        <Button size="sm" variant="ghost" onClick={() => setOpen(open === 'variations' ? null : 'variations')}>{open === 'variations' ? 'Hide variations' : 'Variations'}</Button>
      </div>
      {open === 'brief' ? <div className="mt-12"><Brief brand={brand} conceptId={concept.id}/></div> : null}
      {open === 'variations' ? <div className="mt-12"><Variations brand={brand} concept={concept}/></div> : null}
    </Card>);
}

function ConceptsTab({ brand }) {
    const q = useApi(`/creative/concepts${qs({ brand })}`);
    if (q.error)
        return <ErrorState error={q.error} onRetry={q.reload}/>;
    if (!q.data)
        return <LoadingBlock rows={6}/>;
    const d = q.data;
    return (<>
      <div className="row-wrap mb-12" style={{ alignItems: 'center', gap: 8 }}><SourceTag source={d.source}/><span className="muted small">{d.note}</span></div>
      {!d.concepts.length ? <Empty icon="star" title="No concepts yet">Ask Claude for an AI pack to get a first set of ideas.</Empty>
            : (<div className="col" style={{ gap: 16 }}>{d.concepts.map((c) => <ConceptCard key={c.id} brand={brand} concept={c}/>)}</div>)}
    </>);
}

/* ------------------------------------------------------------------ AI pack */
function Formats({ formats }) {
    if (!formats)
        return null;
    return (<div className="col" style={{ gap: 12 }}>
      {formats.static?.headline || formats.static?.primary_text ? (<div>
          <div className="muted xs">Static image</div>
          <div className="small"><b>{formats.static.headline}</b></div>
          <div className="small">{formats.static.primary_text}</div>
          {formats.static.visual_note ? <div className="small faint">{formats.static.visual_note}</div> : null}
        </div>) : null}
      {formats.carousel?.length ? (<div>
          <div className="muted xs">Carousel</div>
          <ol className="small" style={{ margin: 0, paddingLeft: 18 }}>{formats.carousel.map((f) => <li key={f.frame}><b>{f.visual}</b> — {f.caption}</li>)}</ol>
        </div>) : null}
      {formats.reel?.shots?.length ? (<div>
          <div className="muted xs">Reel ({formats.reel.length_seconds}s)</div>
          <ol className="small" style={{ margin: 0, paddingLeft: 18 }}>{formats.reel.shots.map((s, i) => <li key={i}>{s.at_second}s — {s.visual}{s.on_screen_text ? ` ("${s.on_screen_text}")` : ''}</li>)}</ol>
        </div>) : null}
      {formats.ugc?.creator_brief ? (<div>
          <div className="muted xs">UGC brief</div>
          <div className="small">{formats.ugc.creator_brief}</div>
          {formats.ugc.talking_points?.length ? (<div className="small mt-4"><b>Talking points:</b> {formats.ugc.talking_points.join('; ')}</div>) : null}
          {formats.ugc.do_not_say?.length ? (<div className="small faint mt-4"><b>Do not say:</b> {formats.ugc.do_not_say.join('; ')}</div>) : null}
        </div>) : null}
    </div>);
}

function SaveConceptButton({ brand, concept }) {
    const [state, setState] = useState('idle');   // idle | saving | saved
    const toast = useToast();
    const save = async () => {
        setState('saving');
        try {
            await api.post(`/creative/concepts${qs({ brand })}`, {
                title: concept.title, hook: concept.hook, angle: concept.angle, message: concept.message,
                offer: concept.offer, funnel_stage: concept.funnel_stage, persona: concept.persona,
                evidence: concept.evidence, origin: 'ai',
            });
            setState('saved');
        }
        catch (e) {
            toast.error(e);
            setState('idle');
        }
    };
    if (state === 'saved')
        return <Pill tone="ok">Saved to Concepts</Pill>;
    return <Button size="sm" variant="ghost" icon="star" loading={state === 'saving'} onClick={save}>Save to Concepts</Button>;
}

function PackConcept({ brand, concept }) {
    const [open, setOpen] = useState(false);
    return (<Card title={concept.title}
      actions={<Pill tone={FUNNEL_TONE[concept.funnel_stage] ?? 'neutral'}>{FUNNEL_LABEL[concept.funnel_stage] ?? concept.funnel_stage}</Pill>}>
      <div className="small"><b>Hook:</b> &ldquo;{concept.hook}&rdquo;</div>
      {concept.alternative_hooks?.length ? <div className="small faint mt-4">Also: {concept.alternative_hooks.join(' · ')}</div> : null}
      <div className="small mt-4"><b>Angle:</b> {concept.angle}</div>
      <div className="small mt-4">{concept.message}</div>
      {concept.offer ? <div className="small mt-4"><b>Offer:</b> {concept.offer}</div> : null}
      {concept.persona ? <div className="small faint mt-4"><b>Who it's for:</b> {concept.persona}</div> : null}
      {concept.evidence?.length ? <ul className="small faint" style={{ margin: '8px 0 0', paddingLeft: 18 }}>{concept.evidence.map((e, i) => <li key={i}>{e}</li>)}</ul> : null}
      <div className="row-wrap mt-12" style={{ gap: 8 }}>
        <SaveConceptButton brand={brand} concept={concept}/>
        <Button size="sm" variant="ghost" onClick={() => setOpen((o) => !o)}>{open ? 'Hide production notes' : 'Show production notes'}</Button>
      </div>
      {open ? (<div className="mt-12 col" style={{ gap: 12 }}>
          <Formats formats={concept.formats}/>
          {concept.test ? (<div>
              <div className="muted xs">One-variable test</div>
              <div className="small">{concept.test.hypothesis}</div>
              <div className="small faint">Changing: {concept.test.variable} · success metric: {concept.test.success_metric}</div>
              {concept.test.variants?.length ? <ul className="small" style={{ margin: '4px 0 0', paddingLeft: 18 }}>{concept.test.variants.map((v, i) => <li key={i}>{v}</li>)}</ul> : null}
            </div>) : null}
        </div>) : null}
    </Card>);
}

function PackTab({ brand }) {
    const q = useApi(`/creative/pack${qs({ brand })}`);
    const toast = useToast();
    const [asking, setAsking] = useState(false);
    const poll = useRef(null);
    useEffect(() => {
        if (q.data?.status === 'running' && !poll.current)
            poll.current = setInterval(() => q.reload(), 4000);
        else if (q.data?.status !== 'running' && poll.current) {
            clearInterval(poll.current);
            poll.current = null;
        }
        return () => { if (poll.current) { clearInterval(poll.current); poll.current = null; } };
    }, [q.data?.status]); // eslint-disable-line react-hooks/exhaustive-deps
    const ask = async () => {
        setAsking(true);
        try {
            await api.post(`/creative/pack${qs({ brand })}`);
            q.reload();
        }
        catch (e) {
            toast.error(e);
        }
        finally {
            setAsking(false);
        }
    };
    if (q.error)
        return <ErrorState error={q.error} onRetry={q.reload}/>;
    if (!q.data)
        return <LoadingBlock rows={6}/>;
    const d = q.data;
    const running = d.status === 'running';
    const budget = d.budget;
    return (<>
      <Card title="Ask Claude for a creative pack" sub="Reads the insights above and writes concepts with hooks, ad copy, carousel, Reel shots, a UGC brief and a one-variable test, for this store."
        actions={<Button icon="sparkle" loading={asking || running} disabled={!d.configured} onClick={ask}>{running ? 'Writing…' : 'Ask Claude'}</Button>}>
        {!d.configured ? <div className="small" style={{ color: 'var(--warn)' }}>ANTHROPIC_API_KEY is not set, so Claude cannot write a pack yet.</div> : null}
        <div className="row-wrap" style={{ gap: 16 }}>
          <span className="small muted">Estimated cost: {usd(d.estimate_usd)}</span>
          {budget ? <span className="small muted">Remaining today: {usd(budget.remainingTodayUsd)} of {usd(budget.dailyLimitUsd)}</span> : null}
        </div>
        {d.error ? <div className="small mt-8" style={{ color: 'var(--crit)' }}>{d.error}</div> : null}
      </Card>
      <div className="mt-16">
        {running && !d.pack ? <LoadingBlock rows={6}/>
            : !d.pack ? <Empty icon="sparkle" title="No pack yet">Ask Claude for the first creative pack for this store.</Empty>
                : (<>
            <div className="row-wrap mb-12" style={{ alignItems: 'center', gap: 8 }}>
              <SourceTag source={d.source}/>
              <span className="muted small">{d.generated_at ? `Written ${d.generated_at}` : ''}{d.by ? ` by ${d.by}` : ''}{d.model ? ` · ${d.model}` : ''}{d.cost_usd ? ` · ${usd(d.cost_usd)}` : ''}</span>
            </div>
            {d.pack.summary ? <Card flush className="pad-sm mb-16"><div className="small">{d.pack.summary}</div>{d.pack.data_caveat ? <div className="small faint mt-4">{d.pack.data_caveat}</div> : null}</Card> : null}
            <div className="col" style={{ gap: 16 }}>{d.pack.concepts.map((c, i) => <PackConcept key={i} brand={brand} concept={c}/>)}</div>
          </>)}
      </div>
    </>);
}
