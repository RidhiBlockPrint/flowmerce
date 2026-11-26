'use client';
/**
 * AI image prompts for featured images (server: services/image_prompts.py). Owner request 2026-11-23.
 *
 * ImagePromptPanel sits in the article editor's Featured image card: it shows the one prompt Flowmerce wrote for this
 * article (paste it into Gemini, ChatGPT or any AI image tool), the product photos to attach as references, the exact
 * size for the store's Shopify theme and the suggested alt text. The finished picture is uploaded with ImageSource.
 *
 * ImagePromptBackfill sits on SEO & Blog: it queues prompts for past drafts and live blogs, shows the queue and the
 * store's visual style that Claude read from its own photos.
 */
import { useEffect, useState } from 'react';
import { api, qs, useApi } from '../lib/api';
import { Button, Card, Pill } from './ui';
import { ConfirmDialog, useToast } from './overlays';
import { Icon } from './Icon';

const STATUS = {
    none: { tone: 'neutral', label: 'Not written yet' },
    queued: { tone: 'info', label: 'Waiting in line' },
    working: { tone: 'info', label: 'Being written' },
    ready: { tone: 'ok', label: 'Ready' },
    failed: { tone: 'crit', label: 'Failed' },
};
const BRAND_NAME = { ridhi: 'Ridhi', cpc: 'CPC' };

async function copy(text, toast, what = 'Prompt') {
    try { await navigator.clipboard.writeText(text); toast.ok(`${what} copied. Paste it into your AI image tool.`); }
    catch { toast.error(new Error('The browser did not allow copying. Select the text and copy it yourself.')); }
}

export function ImagePromptPanel({ articleId, canWrite, onUseAlt, onUsePicture, currentImage }) {
    const q = useApi(`/articles/${articleId}/image-prompt`, { remember: false });
    const toast = useToast();
    const [busy, setBusy] = useState(false);
    const [kind, setKind] = useState('banner');
    const d = q.data;
    const picturing = d && ['queued', 'working'].includes(d.image?.status);
    const moving = d && (d.status === 'queued' || d.status === 'working' || picturing);
    const shown = d ? (kind === 'pin' && d.pinPrompt ? d.pinPrompt : d.prompt) : '';
    useEffect(() => {
        if (!moving) return undefined;
        const t = setInterval(() => q.reload(), 5000);
        return () => clearInterval(t);
    }, [moving]);   // eslint-disable-line react-hooks/exhaustive-deps
    const ask = async () => {
        setBusy(true);
        try { await api.post(`/articles/${articleId}/image-prompt`); q.reload(); toast.ok('Claude will write the image prompt in a moment.'); }
        catch (e) { toast.error(e); } finally { setBusy(false); }
    };
    if (q.error) return <div className="callout warn small"><Icon name="alert"/><div>The image prompt could not be loaded: {q.error.message}</div></div>;
    if (!d) return null;
    const st = STATUS[d.status] ?? STATUS.none;
    const f = d.format;
    return (<div className="imgprompt">
      <div className="row-wrap">
        <span className="row strong small"><Icon name="sparkle" size="sm"/>AI image prompt</span><span className="spacer"/>
        <Pill tone={st.tone} dot>{d.status === 'queued' && d.position ? `${st.label} (${d.position})` : st.label}</Pill>
      </div>
      <div className="muted xs">Size for {BRAND_NAME[d.brand] ?? 'this store'}&rsquo;s blog: {f.shape} {f.ratio}, {f.width} × {f.height} px. {f.theme}</div>
      {d.status === 'none' ? (<div className="col">
          <div className="small">Flowmerce writes a banner prompt you can paste into any AI image tool, sized for this store&rsquo;s blog and different from every other article, plus a tall Pinterest version.</div>
          {canWrite ? <Button size="sm" icon="sparkle" loading={busy} disabled={!d.configured} onClick={ask}
            title={d.configured ? '' : 'Claude is not connected on this server'}>Write an image prompt (about ${d.estimateUsd.toFixed(2)})</Button> : null}
        </div>) : null}
      {moving && d.brandPaused ? <div className="callout info small"><Icon name="pause"/><div>Automation is paused for {BRAND_NAME[d.brand] ?? 'this store'}, so this prompt waits until it is resumed (Automation page).</div></div> : null}
      {moving ? <div className="small muted row"><Icon name="loader" size="sm" className="spin"/>
        {d.status === 'working' ? 'Claude is looking at the article and the store’s photos…' : d.reason === 'backfill' ? 'Queued with the past articles. New articles go first.' : 'Starting soon.'}
        {d.error ? ` Last try: ${d.error}` : ''}</div> : null}
      {d.status === 'failed' ? (<div className="callout warn small"><Icon name="alert"/><div>{d.error || 'Claude could not write the prompt.'}
        {canWrite ? <div className="mt-8"><Button size="sm" loading={busy} onClick={ask} icon="refresh">Try again</Button></div> : null}</div></div>) : null}
      {d.prompt ? (<>
        {d.payoff ? <div className="xs"><span className="strong">The picture shows:</span> {d.payoff}</div> : null}
        <Picture d={d} canWrite={canWrite} currentImage={currentImage} onUsePicture={onUsePicture} onChanged={q.reload}/>
        {d.pinPrompt ? (<div className="seg sm" role="tablist" aria-label="Which picture">
            <button type="button" role="tab" aria-pressed={kind === 'banner'} onClick={() => setKind('banner')}>Blog banner {f.ratio}</button>
            <button type="button" role="tab" aria-pressed={kind === 'pin'} onClick={() => setKind('pin')}>Pinterest pin {d.pin.ratio}</button>
          </div>) : null}
        <textarea className="textarea mono imgprompt-text" readOnly rows={9} value={shown} aria-label={kind === 'pin' ? 'Pinterest pin prompt' : 'Blog banner prompt'} onFocus={(e) => e.target.select()}/>
        <div className="row-wrap">
          <Button size="sm" variant="primary" icon="sheet" onClick={() => copy(shown, toast, kind === 'pin' ? 'Pinterest prompt' : 'Banner prompt')}>
            {kind === 'pin' ? 'Copy Pinterest prompt' : 'Copy banner prompt'}</Button>
          {canWrite && !moving ? <Button size="sm" variant="ghost" icon="refresh" loading={busy} onClick={ask}>Write new ones</Button> : null}
        </div>
        {kind === 'pin' ? <div className="xs muted">For Pinterest only: {d.pin.width} × {d.pin.height} px, with calm space at the top for a title. Do not upload it as the article&rsquo;s featured image.</div> : null}
        {d.references?.length ? (<div className="col">
            <span className="xs strong">Attach {d.references.length === 1 ? 'this photo' : 'these photos'} in the AI tool</span>
            <div className="row-wrap">{d.references.map((r) => (<a key={r.url} className="imgprompt-ref" href={r.url} target="_blank" rel="noreferrer" title={`Open ${r.title} to save it`}>
              <img src={r.url + (r.url.includes('?') ? '&' : '?') + 'width=160'} alt="" width={56} height={56}/>
              <span className="xs">{r.title}<br/><span className="muted">Open to save</span></span>
            </a>))}</div>
          </div>) : <div className="xs muted">No product photo needed: this is a scene picture.</div>}
        {d.altText ? (<div className="xs"><span className="strong">Suggested alt text:</span> {d.altText}{' '}
          {onUseAlt ? <button type="button" className="link-btn" onClick={() => onUseAlt(d.altText)}>Use it</button> : null}</div>) : null}
        {d.fileName ? <div className="xs muted">Save the picture as <span className="mono">{d.fileName}</span></div> : null}
      </>) : null}
      <details className="xs">
        <summary className="strong">Which AI tool, and how</summary>
        <div className="col mt-8">
          <div>Best: <b>{d.tool.name}</b>. {d.tool.why} Also works in {d.tool.also}.</div>
          <ol className="imgprompt-steps">{d.steps.map((x) => <li key={x}>{x}</li>)}</ol>
          <div className="muted">Show a real product only from its real photo. Never present an AI picture as a photograph of the actual item.</div>
        </div>
      </details>
    </div>);
}

const PICTURE = {
    queued: { tone: 'info', label: 'Waiting to be made' },
    working: { tone: 'info', label: 'Being made' },
    ready: { tone: 'ok', label: 'Made' },
    failed: { tone: 'crit', label: 'Not made' },
};

/** The picture made automatically from the prompt (server: services/ai_images.py), when an image API key is set. */
function Picture({ d, canWrite, currentImage, onUsePicture, onChanged }) {
    const toast = useToast();
    const [busy, setBusy] = useState(false);
    const im = d.image ?? { status: 'none' };
    const gen = d.generation ?? {};
    const make = async () => {
        setBusy(true);
        try { await api.post(`/articles/${d.articleId}/image-prompt/image`); onChanged(); toast.ok('The picture will be made in a minute or two.'); }
        catch (e) { toast.error(e); } finally { setBusy(false); }
    };
    if (!gen.configured)
        return <div className="xs muted">Automatic pictures are off: add an image API key (GEMINI_API_KEY or OPENAI_API_KEY) to the server to have Flowmerce make and attach the picture itself.</div>;
    const inUse = im.url && currentImage === im.url;
    const st = PICTURE[im.status];
    const chk = im.check ?? {};
    return (<div className="imgprompt-pic">
      <div className="row-wrap">
        <span className="row strong xs"><Icon name="image" size="sm"/>AI picture <span className="muted">({gen.providerName}, {gen.model})</span></span><span className="spacer"/>
        {st ? <Pill tone={inUse ? 'ok' : st.tone} dot>{inUse ? 'In use as featured image' : st.label}</Pill> : null}
      </div>
      {['queued', 'working'].includes(im.status) ? <div className="xs muted row"><Icon name="loader" size="sm" className="spin"/>{im.status === 'working' ? 'Making the picture and checking its print…' : 'In the queue.'}</div> : null}
      {im.url ? <a href={im.url} target="_blank" rel="noreferrer"><img src={im.url + (im.url.includes('?') ? '&' : '?') + 'width=800'} alt={d.altText}
        style={{ width: '100%', aspectRatio: d.format.preview, objectFit: 'cover', borderRadius: 8, background: 'var(--surface-3)' }}/></a> : null}
      {chk.faithful !== undefined ? <div className="xs">{chk.faithful && chk.looks_real ? <><Icon name="check" size="sm"/> Print check passed: the product matches its photo.</> : <><Icon name="alert" size="sm"/> Print check: {chk.problems || 'the product does not match its photo.'}</>}</div> : null}
      {chk.skipped ? <div className="xs muted">{chk.skipped}</div> : null}
      {im.error && im.status !== 'queued' ? <div className="callout warn small"><Icon name="alert"/><div>{im.error}</div></div> : null}
      <div className="row-wrap">
        {im.url && !inUse && canWrite && onUsePicture ? <Button size="sm" variant="primary" icon="check" onClick={() => { onUsePicture(im.url, d.altText); toast.ok('Picture set as the featured image. Save the article to keep it.'); }}>Use this picture</Button> : null}
        {canWrite && !['queued', 'working'].includes(im.status) ? <Button size="sm" variant="ghost" icon="refresh" loading={busy} onClick={make}>{im.url ? 'Make a new picture' : 'Make the picture'}</Button> : null}
        {im.pinUrl ? <a className="small" href={im.pinUrl} target="_blank" rel="noreferrer">Pinterest picture</a> : null}
      </div>
    </div>);
}

export function ImagePromptBackfill({ brand, canRun }) {
    const q = useApi(`/image-prompts${qs({ brand })}`);
    const toast = useToast();
    const [confirm, setConfirm] = useState(null);
    const [busy, setBusy] = useState('');
    const d = q.data;
    const active = d && (d.counts.queued + d.counts.working > 0);
    useEffect(() => {
        if (!active) return undefined;
        const t = setInterval(() => q.reload(), 8000);
        return () => clearInterval(t);
    }, [active]);   // eslint-disable-line react-hooks/exhaustive-deps
    if (q.error || !d) return null;
    const run = async (scope) => {
        setBusy(scope);
        try {
            const r = await api.post('/image-prompts/backfill', { brand: brand || 'all', scope });
            toast.ok(r.queued ? `${r.queued} articles queued. About $${r.estimateUsd.toFixed(2)} of Claude, spread over the coming days.` : 'Every article in that group already has a prompt.');
            q.reload();
        } catch (e) { toast.error(e); } finally { setBusy(''); setConfirm(null); }
    };
    const cancel = async () => {
        setBusy('cancel');
        try { await api.post('/image-prompts/backfill/cancel', { brand: brand || 'all' }); toast.ok('Past articles taken out of the queue.'); q.reload(); }
        catch (e) { toast.error(e); } finally { setBusy(''); }
    };
    const restyle = async (b) => {
        setBusy(`style-${b}`);
        try { await api.post('/image-prompts/style', { brand: b }); toast.ok('Claude read the store’s photos again.'); q.reload(); }
        catch (e) { toast.error(e); } finally { setBusy(''); }
    };
    const w = d.withoutPrompt;
    const groups = [['drafts', 'past drafts', w.drafts], ['published', 'live blogs', w.published], ['all', 'both', w.drafts + w.published]];
    const pick = groups.find((g) => g[0] === confirm);
    return (<Card title="AI image prompts" sub="Every new draft gets a prompt for its featured image by itself. Paste it into Gemini, ChatGPT or any AI image tool.">
      <div className="col gap-12">
        <div className="row-wrap">
          <Pill tone="ok">{d.counts.ready} ready</Pill>
          {d.counts.queued + d.counts.working ? <Pill tone="info" dot>{d.counts.queued + d.counts.working} in the queue</Pill> : null}
          {d.counts.failed ? <Pill tone="crit">{d.counts.failed} failed</Pill> : null}
          <Pill>{w.drafts} drafts and {w.published} live blogs without one</Pill>
        </div>
        {d.resting && active ? <div className="callout info small"><Icon name="clock"/><div>Waiting for room in today&rsquo;s Claude limit. Past articles only use what is left after one automatic blog, so they never hold up new work.</div></div> : null}
        {d.pausedBrands?.length ? <div className="callout info small"><Icon name="pause"/><div>Automation is paused for {d.pausedBrands.map((b) => BRAND_NAME[b] ?? b).join(' and ')}: its prompts wait in the queue until it is resumed on the Automation page.</div></div> : null}
        {!d.configured ? <div className="callout warn small"><Icon name="alert"/><div>Claude is not connected on this server, so prompts cannot be written here.</div></div> : null}
        {canRun ? (<div className="row-wrap">
            {groups.map(([scope, label, n]) => <Button key={scope} size="sm" icon="sparkle" disabled={!n || !d.configured} loading={busy === scope}
              onClick={() => setConfirm(scope)}>Create prompts for {label} ({n})</Button>)}
            {d.backfillWaiting ? <Button size="sm" variant="ghost" icon="x" loading={busy === 'cancel'} onClick={cancel}>Stop the {d.backfillWaiting} waiting</Button> : null}
          </div>) : null}
        {d.generation ? <Generation g={d.generation} canRun={canRun} brand={brand} onChanged={q.reload}/> : null}
        <div className="muted xs">Best tool: <b>{d.tool.name}</b>. {d.tool.why} Sizes:{Object.entries(d.formats).map(([b, f]) => `${BRAND_NAME[b] ?? b} ${f.ratio} (${f.width} × ${f.height})`).join(' · ')}.</div>
        <details className="xs">
          <summary className="strong">The store&rsquo;s look, as Claude read it from its photos</summary>
          <div className="col gap-12 mt-8">{Object.entries(d.styles).map(([b, v]) => (<div key={b} className="col">
            <div className="row"><b>{BRAND_NAME[b] ?? b}</b><span className="spacer"/>
              {canRun ? <Button size="sm" variant="ghost" icon="refresh" loading={busy === `style-${b}`} disabled={!d.configured} onClick={() => restyle(b)}>Read the photos again</Button> : null}</div>
            {v ? <div className="imgprompt-style">{v.style}</div> : <div className="muted">Not read yet. It is read from the store&rsquo;s photos before the first prompt.</div>}
          </div>))}</div>
        </details>
      </div>
      {pick ? <ConfirmDialog title={`Create prompts for ${pick[1]}?`} confirmLabel={`Queue ${pick[2]} articles`} busy={busy === pick[0]}
        onConfirm={() => run(pick[0])} onClose={() => setConfirm(null)}>
        <div className="small">About ${(pick[2] * d.estimateUsd).toFixed(2)} of Claude in total. They are written one at a time from what is left of each day&rsquo;s Claude limit
          after one automatic blog, so a long list may take a few days. New drafts always go first. Nothing on Shopify changes.
          {d.generation?.active ? ` Pictures are made too (about $${Number(d.generation.costPerImageUsd ?? 0).toFixed(2)} each, at most ${d.generation.settings.dailyLimit} a day); live blogs keep their image until a person chooses the new one.` : ''}</div>
      </ConfirmDialog> : null}
    </Card>);
}

/** Automatic pictures from an image API: switches, limits and what was spent (server: services/ai_images.py). */
function Generation({ g, canRun, brand, onChanged }) {
    const toast = useToast();
    const [busy, setBusy] = useState(false);
    const [limits, setLimits] = useState({ dailyLimit: g.settings.dailyLimit, monthlyUsd: g.settings.monthlyUsd });
    useEffect(() => { setLimits({ dailyLimit: g.settings.dailyLimit, monthlyUsd: g.settings.monthlyUsd }); }, [g.settings.dailyLimit, g.settings.monthlyUsd]);
    const save = async (patch) => {
        setBusy(true);
        try { await api.patch(`/image-prompts/settings${qs({ brand })}`, patch); onChanged(); toast.ok('Saved.'); }
        catch (e) { toast.error(e); } finally { setBusy(false); }
    };
    if (!g.configured)
        return (<div className="callout info small"><Icon name="image"/><div><b>Automatic pictures need an image API key.</b> {g.setup}
          {' '}Once it is set, every new draft gets its picture made, checked against the real product photo and attached by itself.</div></div>);
    const sp = g.spending;
    const toggle = (k, label, hint) => (<label className="row xs" title={hint}>
      <input type="checkbox" checked={!!g.settings[k]} disabled={!canRun || busy} onChange={(e) => save({ [k]: e.target.checked })}/>{label}</label>);
    return (<div className="imgprompt-gen col">
      <div className="row-wrap">
        <span className="row strong small"><Icon name="image" size="sm"/>Automatic pictures</span>
        <Pill tone={g.active ? 'ok' : 'neutral'} dot>{g.active ? `On: ${g.providerName}, ${g.model}` : 'Off'}</Pill>
        <span className="spacer"/>
        <span className="xs muted">Today {sp.today} of {g.settings.dailyLimit} · this month ${sp.monthUsd.toFixed(2)} of ${Number(g.settings.monthlyUsd).toFixed(2)}{g.costPerImageUsd ? ` · about $${g.costPerImageUsd.toFixed(2)} a picture` : ''}</span>
      </div>
      <div className="row-wrap">
        {toggle('enabled', 'Make and attach pictures by itself', 'Every new draft gets its picture; live blogs keep theirs until a person chooses')}
        {toggle('check', 'Check the print against the real product photo', 'Claude compares them (about $0.04); a failed picture is made once more, then left to a person')}
        {toggle('pins', 'Also make a Pinterest picture', 'A second, tall picture per article (doubles the image cost)')}
      </div>
      {canRun ? (<div className="row-wrap xs">
          <label className="row">Pictures a day <input className="input" style={{ width: 70 }} type="number" min={0} max={100} value={limits.dailyLimit} onChange={(e) => setLimits({ ...limits, dailyLimit: e.target.value })}/></label>
          <label className="row">Monthly limit $ <input className="input" style={{ width: 80 }} type="number" min={0} max={200} step="1" value={limits.monthlyUsd} onChange={(e) => setLimits({ ...limits, monthlyUsd: e.target.value })}/></label>
          <Button size="sm" variant="ghost" loading={busy} onClick={() => save({ dailyLimit: Number(limits.dailyLimit), monthlyUsd: Number(limits.monthlyUsd) })}>Save limits</Button>
        </div>) : null}
    </div>);
}
