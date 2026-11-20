'use client';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { useParams, useSearchParams } from '../lib/nav';
import { api, useApi, qs } from '../lib/api';
import { useApp } from '../lib/app';
import { fmtCompact, fmtDate, fmtDateTime, fmtInt, fmtPct, fmtPos, fmtUtc, fmtZoned, originLabel, syncLabel, timeAgo } from '../lib/format';
import { seoChecks } from '../lib/seo';
import { compareWithLatest, exportEdits, preview, rebase } from '../lib/conflict.mjs';
import { previewDoc } from '../lib/preview';
import { Button, Card, ErrorState, Field, Kv, LivePill, LoadingBlock, Pill, RoleTag, ShopifyStatePill, SourceBadge, StatusPill, Tabs, Empty } from '../components/ui';
import { ConfirmDialog, Dialog, useToast } from '../components/overlays';
import { Icon } from '../components/Icon';
import { ScoreRing } from '../components/charts';
import { AuthorizeDialog, MODE_LABEL, RejectDialog } from '../components/publish';
import { AskClaude, ClaudeInstructions, ClaudeNotes } from '../components/claude';
import { ImageSource } from '../components/ImageSource';
const EDITABLE = ['title', 'handle', 'primary_keyword', 'meta_title', 'meta_description', 'summary_html', 'body_html', 'tags', 'author', 'image_url', 'image_alt'];
const pick = (a) => Object.fromEntries(EDITABLE.map((k) => [k, a[k] ?? '']));
export default function ArticleEditor() {
    const { id } = useParams();
    const [sp, setSp] = useSearchParams();
    const tab = sp.get('tab') || 'edit';
    const setTab = (t) => { const n = new URLSearchParams(sp); if (t === 'edit')
        n.delete('tab');
    else
        n.set('tab', t); setSp(n, { replace: true }); };
    const { data, error, loading, reload, setData } = useApi(`/articles/${id}`, { remember: false });
    const { can, brandOf } = useApp();
    const toast = useToast();
    const [draft, setDraft] = useState(null);
    const [saving, setSaving] = useState(false);
    const [conflict, setConflict] = useState('');
    const [rteKey, setRteKey] = useState(0);
    // A newer saved version (a sync from Shopify, or another person) arrived while this tab has unsaved edits.
    const [newer, setNewer] = useState(null);
    // Edits the user chose to discard, kept in memory so they can be put back on top of the latest version.
    const [discarded, setDiscarded] = useState(null);
    const base = useMemo(() => (data ? pick(data.article) : null), [data]);
    const applied = useRef({ key: null, base: null, baseVersion: null, draft: null, own: false });
    applied.current.draft = draft;
    useEffect(() => { if (data) {
        const key = `${data.article.id}:${data.article.version}`;
        const cur = applied.current;
        if (cur.key === key)
            return;
        const sameArticle = cur.key !== null && cur.key.split(':')[0] === String(data.article.id);
        const hasEdits = !!(cur.draft && cur.base && EDITABLE.some((k) => cur.draft[k] !== cur.base[k]));
        cur.key = key;
        if (sameArticle && hasEdits && !cur.own) {
            // Never replace text someone is typing. Keep the draft, block saving over the newer version, and say so.
            setNewer(data.article.version);
            return;
        }
        cur.own = false;
        cur.base = pick(data.article);
        cur.baseVersion = data.article.version;
        setNewer(null);
        setDraft(pick(data.article));
        setRteKey((k) => k + 1);
    } }, [data?.article.id, data?.article.version]); // eslint-disable-line react-hooks/exhaustive-deps
    const latestFields = data ? pick(data.article) : null;
    const copyEdits = async () => {
        if (!data || !draft)
            return;
        const text = exportEdits({ draft, base: applied.current.base, fields: EDITABLE, title: data.article.title, version: applied.current.baseVersion });
        try {
            await navigator.clipboard.writeText(text);
            toast.ok('Your edits were copied to the clipboard.');
        }
        catch {
            toast.error(new Error('The browser did not allow copying. Use "Apply my edits on top of the latest version" instead.'));
        }
    };
    // Keep the user's text, take the server's change in every field the user did not touch.
    const applyOnLatest = () => {
        if (!data || !draft)
            return;
        const r = rebase({ draft, base: applied.current.base, latest: latestFields, fields: EDITABLE });
        applied.current.base = latestFields;
        applied.current.baseVersion = data.article.version;
        setNewer(null);
        setConflict('');
        setDraft(r.merged);
        setRteKey((k) => k + 1);
        const names = (l) => l.map((k) => k.replace(/_/g, ' ')).join(', ');
        toast.ok(`Your edits are on top of version ${data.article.version}.${r.taken.length ? ` Updated from the latest: ${names(r.taken)}.` : ''}${r.clashes.length ? ` Both changed: ${names(r.clashes)} — yours is shown; the other text is in History.` : ''} Not saved yet.`);
    };
    const discardMine = () => {
        if (!data || !draft)
            return;
        setDiscarded({ draft, base: applied.current.base });
        applied.current.base = latestFields;
        applied.current.baseVersion = data.article.version;
        setNewer(null);
        setConflict('');
        setDraft(latestFields);
        setRteKey((k) => k + 1);
    };
    const restoreDiscarded = () => {
        if (!discarded || !latestFields)
            return;
        const r = rebase({ draft: discarded.draft, base: discarded.base, latest: latestFields, fields: EDITABLE });
        setDraft(r.merged);
        setRteKey((k) => k + 1);
        setDiscarded(null);
        toast.ok('Your discarded edits are back on top of the current version. Not saved yet.');
    };
    const dirtyFields = draft && base ? EDITABLE.filter((k) => draft[k] !== base[k]) : [];
    const dirty = dirtyFields.length > 0;
    const editable = can('article:write') && data?.article.status !== 'scheduled';
    const blocked = newer !== null;
    useEffect(() => {
        if (!dirty)
            return;
        const h = (e) => { e.preventDefault(); };
        window.addEventListener('beforeunload', h);
        return () => window.removeEventListener('beforeunload', h);
    }, [dirty]);
    const save = useCallback(async (note) => {
        if (!data || !draft || !dirty)
            return true;
        if (newer !== null) {
            setConflict(`This article changed to version ${newer} while you were editing. Your edits are kept here, but saving is blocked so they cannot overwrite it. Load the latest version, then re-apply your changes.`);
            return false;
        }
        setSaving(true);
        setConflict('');
        try {
            const patch = { expected_version: data.article.version, note };
            for (const k of dirtyFields)
                patch[k] = draft[k];
            const a = await api.patch(`/articles/${data.article.id}`, patch);
            applied.current.own = true;
            setData({ ...data, article: a });
            reload();
            const lostApproval = data.article.status !== a.status && ['approved', 'publish_requested', 'in_review', 'published'].includes(data.article.status);
            toast.ok(lostApproval ? `Saved as version ${a.version}. The content changed, so it needs review again.` : `Saved · version ${a.version}`);
            return true;
        }
        catch (e) {
            if (e.code === 'version_conflict') {
                applied.current.own = false;
                setConflict(e.message);
            }
            else
                toast.error(e);
            return false;
        }
        finally {
            setSaving(false);
        }
    }, [data, draft, dirty, dirtyFields, newer, setData, reload, toast]);
    useEffect(() => {
        const onKey = (e) => { if ((e.ctrlKey || e.metaKey) && e.key === 's') {
            e.preventDefault();
            if (editable)
                void save();
        } };
        document.addEventListener('keydown', onKey);
        return () => document.removeEventListener('keydown', onKey);
    }, [save, editable]);
    if (error)
        return <ErrorState error={error} onRetry={reload}/>;
    if (loading && !data)
        return <LoadingBlock rows={8}/>;
    if (!data || !draft)
        return null;
    const a = data.article;
    const brand = brandOf(a.brand_id);
    const set = (k, v) => setDraft((d) => (d ? { ...d, [k]: v } : d));
    const act = async (fn, okMsg) => {
        if (dirty && !(await save()))
            return;
        try {
            await fn();
            toast.ok(okMsg);
            reload();
        }
        catch (e) {
            toast.error(e);
        }
    };
    return (<div data-brand={a.brand_id}>
      <div className="crumbs"><Link href="/articles">Articles</Link><Icon name="chevronRight" size="sm"/><span className={`brand-dot ${a.brand_id}`}/>{brand.name}</div>
      <div className="page-head" style={{ marginBottom: 12 }}>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div className="row-wrap gap-4 mb-8">
            <StatusPill status={a.status}/>
            <LivePill live={a.shopify_published} differs={a.live_differs}/>
            <ShopifyStatePill state={a.shopify_state} at={a.published_at} hideLive/>
            {a.status === 'scheduled' ? <Pill tone="info" title="Scheduled by a Flowmerce publish request">Scheduled by Flowmerce</Pill> : null}
            {loading ? <span className="row small muted"><Icon name="loader" className="spin" size="sm"/>Refreshing…</span> : null}
            <span className="pill outline">v{a.version}</span>
            {a.approval_current ? <Pill tone="ok" title={`Approved ${fmtDateTime(a.approved_at)}`}><Icon name="check" size="sm"/>Approved content</Pill> : null}
            {dirty ? <span className="row small" style={{ color: 'var(--warn)' }}><span className="dirty-dot"/>Unsaved changes</span> : null}
          </div>
          <h1 className="page-title ellipsis" title={a.title}>{draft.title || 'Untitled'}</h1>
          <div className="page-sub row-wrap">
            <span>Next: <b>{a.next_action.label}</b></span> <RoleTag role={a.next_action.role}/>
            {a.live_url && a.shopify_published ? <a href={a.live_url} target="_blank" rel="noopener" className="small">View live <Icon name="external" size="sm"/></a> : null}
          </div>
        </div>
        <div className="page-actions">
          {editable ? <Button variant={dirty ? 'primary' : 'secondary'} icon="check" loading={saving} disabled={!dirty || blocked} onClick={() => save()}>Save</Button> : null}
          {can('article:submit') && ['draft', 'idea', 'changes_requested', 'failed'].includes(a.status) ? (<Button icon="send" onClick={() => act(() => api.post(`/articles/${a.id}/submit`), 'Sent for review.')}>Send for review</Button>) : null}
          {can('article:review') && a.status === 'in_review' ? <Button variant="primary" icon="eye" onClick={() => setTab('review')}>Review</Button> : null}
          {a.status === 'approved' && can('publish:request') ? <Button variant="primary" icon="publish" onClick={() => setTab('publish')}>Publishing</Button> : null}
        </div>
      </div>

      {newer !== null ? <ConflictPanel rows={compareWithLatest({ draft, base: applied.current.base, latest: latestFields, fields: EDITABLE })} version={newer} onCopy={copyEdits} onApply={applyOnLatest} onDiscard={discardMine}/> : null}
      {conflict && newer === null ? <div className="callout warn mb-12"><Icon name="alert"/><div style={{ flex: 1 }}>{conflict}<div className="small mt-4">Your edits are still here and nothing was saved over them.</div></div><Button size="sm" onClick={reload}>Show the latest version</Button></div> : null}
      {discarded ? <div className="callout info mb-12"><Icon name="info"/><div style={{ flex: 1 }}>You discarded your edits and loaded the latest version. They are still held in this tab.</div><Button size="sm" onClick={restoreDiscarded}>Put my edits back</Button><Button size="sm" variant="ghost" onClick={() => setDiscarded(null)}>Forget them</Button></div> : null}
      {a.status === 'scheduled' ? <div className="callout info mb-12"><Icon name="clock"/>This article is scheduled by Flowmerce (an authorized publish request) for <b>{fmtZoned(a.publish_at)}</b> ({fmtUtc(a.publish_at)}). Editing is locked until it goes live or the schedule is withdrawn in Publishing.</div> : null}
      {a.shopify_state === 'scheduled_in_shopify' ? <div className="callout info mb-12"><Icon name="clock"/><div>Shopify admin has this article hidden with a future publication date of <b>{fmtZoned(a.published_at)}</b> ({fmtUtc(a.published_at)}), so Shopify will show it then. Flowmerce did not schedule this and will not change it.</div></div> : null}
      {a.unpublished_in_shopify ? <div className="callout warn mb-12"><Icon name="alert"/><div>Published from Flowmerce but now unpublished in Shopify. Flowmerce keeps its status until a person decides what to do.</div></div> : null}
      {a.last_error ? <div className="callout crit mb-12"><Icon name="alert"/><div style={{ overflowWrap: 'anywhere' }}><b>Last Shopify error:</b> {a.last_error}{a.shopify_synced_at ? <span className="muted"> (last successful sync {timeAgo(a.shopify_synced_at)})</span> : <span className="muted"> (never synced)</span>}</div></div> : null}
      {a.review_note && a.status === 'changes_requested' ? <div className="callout warn mb-12"><Icon name="edit"/><div><b>Reviewer asked for changes:</b> {a.review_note}</div></div> : null}
      {a.shopify_sync === 'public_feed' ? <div className="callout info mb-12"><Icon name="info"/><div>{brand.configured?.shopifyAdmin ? 'This article is still matched through the public storefront feed, which carries no SEO fields or drafts. The next Shopify sync will link it through the Admin API.' : 'This article is matched through the public storefront feed, which carries no SEO fields or drafts. Connect the Shopify Admin API on Integrations for full sync.'}</div></div> : null}

      <Tabs value={tab} onChange={setTab} tabs={[
            { key: 'edit', label: <><Icon name="edit" size="sm"/>Edit</> },
            { key: 'preview', label: <><Icon name="eye" size="sm"/>Preview</> },
            { key: 'review', label: <>Review{data.notes.length ? <span className="faint">{data.notes.length}</span> : null}</> },
            { key: 'publish', label: <>Publishing{data.requests.some((r) => r.status === 'pending' || r.status === 'failed') ? <span className="brand-dot" style={{ background: 'var(--saffron)' }}/> : null}</> },
            { key: 'revisions', label: <>History<span className="faint">{data.revisions.length}</span></> },
            { key: 'performance', label: 'Performance' },
        ]}/>

      {tab === 'edit' ? <EditTab draft={draft} set={set} article={a} detail={data} editable={editable} dirty={dirty} onRevised={reload} rteKey={rteKey} storefront={brand.storefrontUrl} onAssign={async (v) => { try {
        await api.patch(`/articles/${a.id}`, { assignee_id: v || null });
        reload();
        toast.ok('Assignee updated.');
    }
    catch (e) {
        toast.error(e);
    } }}/> : null}
      {tab === 'preview' ? <PreviewTab draft={draft} article={a} storefront={brand.storefrontUrl}/> : null}
      {tab === 'review' ? <ReviewTab detail={data} dirty={dirty} onChanged={reload}/> : null}
      {tab === 'publish' ? <PublishTab detail={data} dirty={dirty} onChanged={reload}/> : null}
      {tab === 'revisions' ? <RevisionsTab detail={data} current={draft} onRestored={() => { reload(); setTab('edit'); }}/> : null}
      {tab === 'performance' ? <PerformanceTab detail={data}/> : null}
    </div>);
}
/* ---------------- Edit ---------------- */
function EditTab({ draft, set, article, detail, editable, dirty, onRevised, rteKey, storefront, onAssign }) {
    const { checks, score, words } = useMemo(() => seoChecks(draft, new URL(storefront).host), [draft, storefront]);
    const [mode, setMode] = useState('visual');
    const [linkOpen, setLinkOpen] = useState(false);
    const rte = useRef(null);
    const savedRange = useRef(null);
    const products = useApi(`/brands/${article.brand_id}/products`);
    useEffect(() => { if (rte.current && mode === 'visual')
        rte.current.innerHTML = draft.body_html; }, [rteKey, mode]); // eslint-disable-line react-hooks/exhaustive-deps
    const exec = (cmd, value) => {
        rte.current?.focus();
        document.execCommand(cmd, false, value);
        if (rte.current)
            set('body_html', rte.current.innerHTML);
    };
    const openLink = () => {
        const sel = window.getSelection();
        savedRange.current = sel && sel.rangeCount ? sel.getRangeAt(0).cloneRange() : null;
        setLinkOpen(true);
    };
    const insertLink = (url, text) => {
        setLinkOpen(false);
        rte.current?.focus();
        const sel = window.getSelection();
        if (savedRange.current && sel) {
            sel.removeAllRanges();
            sel.addRange(savedRange.current);
        }
        if (sel && sel.toString())
            document.execCommand('createLink', false, url);
        else
            document.execCommand('insertHTML', false, `<a href="${url.replace(/"/g, '&quot;')}">${(text || url).replace(/</g, '&lt;')}</a>`);
        if (rte.current)
            set('body_html', rte.current.innerHTML);
    };
    const [seoSuggestion, setSeoSuggestion] = useState(null);
    const seoContext = () => ({ title: draft.title, primary_keyword: draft.primary_keyword, meta_title: draft.meta_title, meta_description: draft.meta_description,
        handle: draft.handle, tags: draft.tags, featured_image: draft.image_url ? (products.data ?? []).find((p) => p.image_url === draft.image_url)?.title ?? draft.image_url : '',
        article_text: draft.body_html.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').slice(0, 12000) });
    const applySeo = (withTitle) => {
        const s = seoSuggestion;
        set('meta_title', s.meta_title);
        set('meta_description', s.meta_description);
        if (!article.shopify_published && s.handle)
            set('handle', s.handle.toLowerCase().replace(/[^a-z0-9-]/g, '-'));
        set('tags', s.tags.join(', '));
        if (s.summary)
            set('summary_html', `<p>${s.summary.replace(/</g, '&lt;')}</p>`);
        if (draft.image_url && s.image_alt)
            set('image_alt', s.image_alt);
        if (withTitle && s.title)
            set('title', s.title);
        setSeoSuggestion(null);
    };
    const metaTitleShown = draft.meta_title || draft.title;
    const host = new URL(storefront).host;
    return (<div className="editor-layout">
      <div className="col" style={{ gap: 16, minWidth: 0 }}>
        <div className="card" style={{ padding: '14px 22px 4px' }}>
          <textarea className="editor-title" rows={1} value={draft.title} onChange={(e) => set('title', e.target.value)} placeholder="Article title" readOnly={!editable} aria-label="Title" onInput={(e) => { const t = e.currentTarget; t.style.height = 'auto'; t.style.height = t.scrollHeight + 'px'; }}/>
        </div>
        <div className="card">
          <div className="rte-toolbar" role="toolbar" aria-label="Formatting">
            {mode === 'visual' && editable ? (<>
                <button className="btn" title="Heading 2" onClick={() => exec('formatBlock', 'h2')}>H2</button>
                <button className="btn" title="Heading 3" onClick={() => exec('formatBlock', 'h3')}>H3</button>
                <button className="btn" title="Paragraph" onClick={() => exec('formatBlock', 'p')}>¶</button>
                <span className="sep"/>
                <button className="btn" title="Bold (Ctrl+B)" onClick={() => exec('bold')}><Icon name="bold" size="sm"/></button>
                <button className="btn" title="Italic (Ctrl+I)" onClick={() => exec('italic')}><Icon name="italic" size="sm"/></button>
                <button className="btn" title="Link" onClick={openLink}><Icon name="link" size="sm"/></button>
                <span className="sep"/>
                <button className="btn" title="Bulleted list" onClick={() => exec('insertUnorderedList')}><Icon name="list" size="sm"/></button>
                <button className="btn" title="Numbered list" onClick={() => exec('insertOrderedList')}><Icon name="listOl" size="sm"/></button>
                <button className="btn" title="Quote" onClick={() => exec('formatBlock', 'blockquote')}><Icon name="quote" size="sm"/></button>
                <button className="btn" title="Undo" onClick={() => exec('undo')}><Icon name="undo" size="sm"/></button>
              </>) : <span className="small muted" style={{ padding: '5px 6px' }}>{editable ? 'HTML source — sanitized on save (scripts, iframes and inline handlers are removed)' : 'Read only'}</span>}
            <span className="spacer"/>
            <div className="seg sm" role="group" aria-label="Editor mode">
              <button aria-pressed={mode === 'visual'} onClick={() => setMode('visual')}>Visual</button>
              <button aria-pressed={mode === 'html'} onClick={() => setMode('html')}><Icon name="code" size="sm"/>HTML</button>
            </div>
          </div>
          {mode === 'visual' ? (<div key={rteKey} ref={rte} className="rte" contentEditable={editable} suppressContentEditableWarning role="textbox" aria-multiline="true" aria-label="Article body" onInput={(e) => set('body_html', e.currentTarget.innerHTML)} onPaste={(e) => {
                const html = e.clipboardData.getData('text/html');
                if (html) {
                    e.preventDefault();
                    const clean = html.replace(/<(script|style|meta|link)[\s\S]*?(<\/\1>|>)/gi, '').replace(/\s(style|class|on\w+)="[^"]*"/gi, '');
                    document.execCommand('insertHTML', false, clean);
                }
            }}/>) : (<textarea className="html-src" value={draft.body_html} onChange={(e) => set('body_html', e.target.value)} readOnly={!editable} spellCheck={false} aria-label="Article HTML"/>)}
          <div className="card-foot"><span className="num">{words.toLocaleString()} words</span><span>·</span><span>{Math.max(1, Math.round(words / 230))} min read</span></div>
        </div>
        <Card title="Listing summary" sub="Shown on the blog index page">
          <textarea className="textarea" rows={3} value={draft.summary_html.replace(/<\/?p>/g, '')} onChange={(e) => set('summary_html', e.target.value ? `<p>${e.target.value}</p>` : '')} readOnly={!editable} aria-label="Summary"/>
        </Card>
        <ClaudeNotes notes={detail.aiNotes}/>
      </div>

      <div className="col" style={{ gap: 16, minWidth: 0 }}>
        {/* Claude's box comes first in the side panel, so it is reachable without scrolling past the article (owner request 2026-11-20). */}
        <ClaudeInstructions article={article} dirty={dirty} onRevised={onRevised}/>
        <Card title="SEO check" actions={<ScoreRing value={score}/>}>
          <div className="checklist">
            {checks.map((c) => (<div key={c.id} className={`check-row ${c.state}`}>
                <Icon name={c.state === 'pass' ? 'checkCircle' : c.state === 'warn' ? 'alert' : 'xCircle'} size="sm"/>
                <span><span className="strong">{c.label}</span>{c.detail ? <span className="muted"> — {c.detail}</span> : null}</span>
              </div>))}
          </div>
        </Card>
        <Card title="Search result preview">
          <div className="serp" aria-label="Google result preview">
            <div className="u">{host} › blogs › {draft.handle || 'handle'}</div>
            <div className="ti">{metaTitleShown || 'Title'}</div>
            <div className="d">{draft.meta_description || <span style={{ color: '#9aa0a6' }}>Google will pick text from the page when there is no meta description.</span>}</div>
          </div>
        </Card>
        <Card title="SEO fields" actions={editable ? <AskClaude brand={article.brand_id} kind="seo_fields" context={seoContext} onResult={setSeoSuggestion} label="Ask Claude"/> : null}>
          <div className="col gap-12">
            {seoSuggestion ? (<div className="callout info" style={{ display: 'block' }}>
                <div className="small strong mb-8">Claude suggests (nothing is changed until you apply it):</div>
                <div className="small col" style={{ gap: 4 }}>
                  {seoSuggestion.title && seoSuggestion.title !== draft.title ? <div><b>Title:</b> {seoSuggestion.title}</div> : null}
                  <div><b>SEO title:</b> {seoSuggestion.meta_title} <span className="faint">({seoSuggestion.meta_title.length})</span></div>
                  <div><b>Meta description:</b> {seoSuggestion.meta_description} <span className="faint">({seoSuggestion.meta_description.length})</span></div>
                  {!article.shopify_published ? <div><b>URL handle:</b> <span className="mono">{seoSuggestion.handle}</span></div> : null}
                  <div><b>Tags:</b> {seoSuggestion.tags.join(', ')}</div>
                  {seoSuggestion.summary ? <div><b>Listing summary:</b> {seoSuggestion.summary}</div> : null}
                  {draft.image_url && seoSuggestion.image_alt ? <div><b>Image alt text:</b> {seoSuggestion.image_alt}</div> : null}
                </div>
                <div className="row-wrap mt-8" style={{ gap: 6 }}>
                  <Button size="sm" variant="primary" onClick={() => applySeo(false)}>Apply</Button>
                  {seoSuggestion.title && seoSuggestion.title !== draft.title ? <Button size="sm" onClick={() => applySeo(true)}>Apply with the title</Button> : null}
                  <Button size="sm" variant="ghost" onClick={() => setSeoSuggestion(null)}>Dismiss</Button>
                </div>
              </div>) : null}
            {article.shopify_sync === 'public_feed' ? <div className="callout info"><Icon name="info"/><div className="small">SEO title and meta description are not available from the public feed, so blank fields here do not mean Shopify has none.</div></div> : null}
            <Field label="Primary keyword"><input className="input" value={draft.primary_keyword} onChange={(e) => set('primary_keyword', e.target.value)} readOnly={!editable}/></Field>
            <Field label="SEO title" counter={{ n: draft.meta_title.length, max: 60 }} hint="Leave empty to use the article title."><input className="input" value={draft.meta_title} onChange={(e) => set('meta_title', e.target.value)} readOnly={!editable}/></Field>
            <Field label="Meta description" counter={{ n: draft.meta_description.length, min: 120, max: 160 }}><textarea className="textarea" rows={3} value={draft.meta_description} onChange={(e) => set('meta_description', e.target.value)} readOnly={!editable}/></Field>
            <Field label="URL handle" hint={article.shopify_published ? 'Locked: the article is live and its URL is public.' : `${host}/blogs/…/${draft.handle}`}>
              <input className="input mono" value={draft.handle} onChange={(e) => set('handle', e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, '-'))} readOnly={!editable || article.shopify_published}/>
            </Field>
            <Field label="Tags" hint="Comma-separated"><input className="input" value={draft.tags} onChange={(e) => set('tags', e.target.value)} readOnly={!editable}/></Field>
            <Field label="Author"><input className="input" value={draft.author} onChange={(e) => set('author', e.target.value)} readOnly={!editable}/></Field>
          </div>
        </Card>
        <Card title="Featured image">
          <div className="col gap-12">
            {draft.image_url ? <img src={draft.image_url} alt={draft.image_alt} style={{ borderRadius: 10, aspectRatio: '16/9', objectFit: 'cover', width: '100%', background: 'var(--surface-3)' }}/> : null}
            {editable ? <ImageSource brand={article.brand_id} url={draft.image_url} alt={draft.image_alt}
              onPick={(url, alt) => { set('image_url', url); if (!draft.image_alt && alt) set('image_alt', alt); }}/>
              : <Field label="Image URL"><input className="input" value={draft.image_url} readOnly/></Field>}
            <Field label="Alt text" hint="What the picture shows, for search engines and screen readers"><input className="input" value={draft.image_alt} onChange={(e) => set('image_alt', e.target.value)} readOnly={!editable}/></Field>
            {editable && draft.image_url ? <Button size="sm" variant="ghost" icon="x" onClick={() => set('image_url', '')}>Remove image</Button> : null}
          </div>
        </Card>
      </div>
      {linkOpen ? <LinkDialog products={products.data ?? []} storefront={storefront} onClose={() => setLinkOpen(false)} onInsert={insertLink}/> : null}
    </div>);
}
const FIELD_NAME = { title: 'Title', handle: 'URL handle', primary_keyword: 'Primary keyword', meta_title: 'SEO title', meta_description: 'Meta description', summary_html: 'Listing summary', body_html: 'Article body', tags: 'Tags', author: 'Author', image_url: 'Image URL', image_alt: 'Image alt text' };
/** Shown when a newer saved version arrives while the tab holds unsaved edits. Nothing is replaced until a person chooses. */
function ConflictPanel({ rows, version, onCopy, onApply, onDiscard }) {
    return (<div className="callout warn mb-12" role="alert">
      <Icon name="alert"/>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div><b>This article changed while you were editing.</b> Version {version} was saved by a Shopify sync or another person. Your unsaved edits are untouched and Save is blocked, so neither version can silently overwrite the other.</div>
        {rows.length ? (<div className="table-wrap mt-8" style={{ background: 'var(--surface)', borderRadius: 8 }}>
            <table className="t compact">
              <thead><tr><th>Field you edited</th><th>Your text</th><th>Latest saved (v{version})</th></tr></thead>
              <tbody>{rows.map((r) => (<tr key={r.field}>
                  <td className="small strong nowrap">{FIELD_NAME[r.field] ?? r.field}{r.clash ? <div><span className="pill warn">changed in both</span></div> : null}</td>
                  <td className="small" style={{ overflowWrap: 'anywhere' }}>{preview(r.mine)}</td>
                  <td className="small" style={{ overflowWrap: 'anywhere' }}>{r.same ? <span className="muted">same as yours</span> : r.clash ? preview(r.latest) : <span className="muted">unchanged by the sync</span>}</td>
                </tr>))}</tbody>
            </table>
          </div>) : <div className="small mt-4">The edits you made now match the latest version.</div>}
        <div className="row-wrap mt-8">
          <Button size="sm" variant="primary" onClick={onApply}>Keep my edits on top of v{version}</Button>
          <Button size="sm" icon="sheet" onClick={onCopy}>Copy my edits</Button>
          <Button size="sm" variant="ghost" onClick={onDiscard}>Discard mine, use v{version}</Button>
        </div>
        <div className="muted xs mt-4">Keeping your edits applies the sync's changes to every field you did not touch. Where both of you changed a field, your text is shown and the other text stays in History. Nothing is saved until you press Save.</div>
      </div>
    </div>);
}
function LinkDialog({ products, storefront, onClose, onInsert }) {
    const [url, setUrl] = useState('');
    const [q, setQ] = useState('');
    const matches = products.filter((p) => !q || p.title.toLowerCase().includes(q.toLowerCase())).slice(0, 8);
    const valid = /^(https:\/\/|\/)/.test(url);
    return (<Dialog title="Insert link" sub="Internal links to products help both readers and search engines." onClose={onClose} footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button variant="primary" disabled={!valid} onClick={() => onInsert(url)}>Insert link</Button></>}>
      <div className="col gap-12">
        <Field label="URL" hint={`An https:// address or a path on ${storefront.replace('https://', '')} such as /collections/tablecloths`}>
          <input className="input" data-autofocus value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://…"/>
        </Field>
        {products.length ? (<>
            <div className="input-icon"><Icon name="search"/><input className="input sm" placeholder="Find a product" value={q} onChange={(e) => setQ(e.target.value)}/></div>
            <div className="col gap-4">
              {matches.map((p) => (<button key={p.handle} className="search-hit" style={{ border: 0, background: 'none', textAlign: 'left' }} onClick={() => onInsert(new URL(p.url).pathname, p.title)}>
                  {p.image_url ? <img src={p.image_url + (p.image_url.includes('?') ? '&' : '?') + 'width=64'} alt="" width={28} height={28} style={{ borderRadius: 6, objectFit: 'cover' }}/> : <Icon name="store"/>}
                  <span className="ellipsis small">{p.title}</span>
                </button>))}
            </div>
          </>) : <div className="muted small">Products appear here after a Shopify sync.</div>}
      </div>
    </Dialog>);
}
/* ---------------- Preview ---------------- */
function PreviewTab({ draft, article, storefront }) {
    const [device, setDevice] = useState('desktop');
    const doc = useMemo(() => previewDoc(article.brand_id, { ...draft, published_at: article.published_at }, storefront), [draft, article.brand_id, article.published_at, storefront]);
    return (<>
      <div className="toolbar">
        <div className="seg sm" role="group" aria-label="Device">
          <button aria-pressed={device === 'desktop'} onClick={() => setDevice('desktop')}><Icon name="monitor" size="sm"/>Desktop</button>
          <button aria-pressed={device === 'mobile'} onClick={() => setDevice('mobile')}><Icon name="phone" size="sm"/>Mobile</button>
        </div>
        <span className="muted small">Includes unsaved edits. Styled to match the {article.brand_id === 'ridhi' ? 'Ridhi' : 'Cotton Print Club'} storefront; not the live page.</span>
      </div>
      <div className="preview-frame-wrap">
        <iframe title="Article preview" className={`preview-frame ${device}`} sandbox="" srcDoc={doc}/>
      </div>
    </>);
}
/* ---------------- Review ---------------- */
function ReviewTab({ detail, dirty, onChanged }) {
    const a = detail.article;
    const { can } = useApp();
    const toast = useToast();
    const [note, setNote] = useState('');
    const [busy, setBusy] = useState(null);
    const decide = async (decision) => {
        setBusy(decision);
        try {
            await api.post(`/articles/${a.id}/review`, { decision, version: a.version, note });
            toast.ok(decision === 'approve' ? `Version ${a.version} approved.` : 'Sent back with your notes.');
            setNote('');
            onChanged();
        }
        catch (e) {
            toast.error(e);
        }
        finally {
            setBusy(null);
        }
    };
    return (<div className="grid main-side">
      <Card title="Review history" flush>
        {detail.notes.length ? (<div className="timeline" style={{ padding: '6px 16px' }}>
            {detail.notes.map((n) => (<div key={n.id} className="tl-item">
                <span className="tl-dot"><Icon name={n.kind.includes('approve') ? 'check' : n.kind.includes('changes') ? 'edit' : n.kind === 'submitted' ? 'send' : 'info'}/></span>
                <div>
                  <div className="small"><b>{n.reviewer_name || 'Someone'}</b> {n.kind === 'submitted' ? 'sent for review' : n.kind === 'approved' ? 'approved' : n.kind === 'changes_requested' ? 'requested changes' : n.kind.replace('offline_', 'offline: ').replace('_', ' ')} · v{n.version}{n.source === 'excel' ? <span className="pill warn" style={{ marginLeft: 6 }}>Excel import · note only</span> : null}</div>
                  {n.note ? <div className="small mt-4" style={{ whiteSpace: 'pre-wrap' }}>{n.note}</div> : null}
                  <div className="faint xs">{fmtDateTime(n.created_at)}</div>
                </div>
              </div>))}
          </div>) : <Empty icon="eye" title="No reviews yet">Send the article for review when it is ready.</Empty>}
      </Card>
      <Card title="Decision">
        {a.status === 'in_review' && can('article:review') ? (<div className="col gap-12">
            <p className="small" style={{ margin: 0 }}>You are reviewing <b>version {a.version}</b>. If someone saves a newer version while you read, your decision will be refused so you can review the latest text.</p>
            {dirty ? <div className="callout warn"><Icon name="alert"/>You have unsaved edits in this tab. Reviews apply to the saved version.</div> : null}
            <Field label="Notes for the writer"><textarea className="textarea" value={note} onChange={(e) => setNote(e.target.value)} placeholder="Required when requesting changes"/></Field>
            <div className="row-wrap">
              <Button variant="primary" icon="check" loading={busy === 'approve'} onClick={() => decide('approve')}>Approve v{a.version}</Button>
              <Button icon="edit" loading={busy === 'request_changes'} disabled={!note.trim()} onClick={() => decide('request_changes')}>Request changes</Button>
            </div>
          </div>) : (<div className="col gap-12 small">
            <div className="row"><span className="muted">Status</span><span className="spacer"/><StatusPill status={a.status}/></div>
            {a.approval_current ? <div className="callout ok"><Icon name="checkCircle"/>The current text (v{a.version}) is approved.</div> : a.approved_hash ? <div className="callout warn"><Icon name="alert"/>An earlier version was approved; the text has changed since.</div> : null}
            {a.status === 'in_review' && !can('article:review') ? <div className="muted">Waiting for a reviewer.</div> : null}
            {['draft', 'idea', 'changes_requested'].includes(a.status) ? <div className="muted">Send the article for review from the top bar when it is ready.</div> : null}
          </div>)}
      </Card>
    </div>);
}
/* ---------------- Publishing ---------------- */
function PublishTab({ detail, dirty, onChanged }) {
    const a = detail.article;
    const { can, me, brandOf } = useApp();
    const toast = useToast();
    const brand = brandOf(a.brand_id);
    const [mode, setMode] = useState(a.shopify_published ? 'update_live' : 'publish_now');
    const [when, setWhen] = useState('');
    const [note, setNote] = useState('');
    const [busy, setBusy] = useState(null);
    const [authorize, setAuthorize] = useState(null);
    const [reject, setReject] = useState(null);
    const [confirmDraft, setConfirmDraft] = useState(false);
    const pending = detail.requests.find((r) => r.status === 'pending' || r.status === 'failed');
    const canRequest = a.status === 'approved' && a.approval_current && can('publish:request');
    const saveDraft = async () => {
        setBusy('draft');
        try {
            const res = await api.post(`/articles/${a.id}/shopify-draft`);
            toast.ok(res?.message ?? 'Saved to Shopify as a hidden draft.');
            setConfirmDraft(false);
            onChanged();
        }
        catch (e) {
            toast.error(e);
        }
        finally {
            setBusy(null);
        }
    };
    const request = async () => {
        setBusy('request');
        try {
            await api.post(`/articles/${a.id}/publish-request`, { mode, publish_at: mode === 'schedule' ? new Date(when).toISOString() : null, note });
            toast.ok('Publish request sent to reviewers.');
            onChanged();
        }
        catch (e) {
            toast.error(e);
        }
        finally {
            setBusy(null);
        }
    };
    const withdraw = async (r) => {
        try {
            await api.post(`/publish-requests/${r.id}/cancel`);
            toast.ok('Request withdrawn.');
            onChanged();
        }
        catch (e) {
            toast.error(e);
        }
    };
    const req = (r) => ({ ...r, title: a.title, brand_id: a.brand_id, stale: r.content_hash !== a.content_hash });
    return (<div className="grid main-side">
      <div className="col" style={{ gap: 16, minWidth: 0 }}>
        {!me.livePublishing ? <div className="callout warn"><Icon name="lock"/><div><b>Live publishing is off on this server.</b> Requests and approvals work, but the server refuses to make anything visible until an admin sets ALLOW_LIVE_PUBLISH=true. Hidden drafts still work.</div></div> : null}
        {dirty ? <div className="callout warn"><Icon name="alert"/>Save your edits first. Saving changed text sends the article back for review.</div> : null}
        {pending ? (<Card title={pending.status === 'failed' ? 'Publishing failed' : 'Waiting for authorization'} sub={`${MODE_LABEL[pending.mode]}${pending.publish_at ? ' · ' + fmtZoned(pending.publish_at) : ''} · requested by ${pending.requested_by_name ?? '—'} ${timeAgo(pending.requested_at)}`}>
            <div className="col gap-12">
              {pending.status === 'failed' ? <div className="callout crit"><Icon name="alert"/><div><b>Shopify error:</b> {pending.error}</div></div> : null}
              {pending.note ? <div className="small"><span className="muted">Note:</span> {pending.note}</div> : null}
              <div className="row-wrap">
                {can('publish:authorize') && (pending.requested_by !== me.user.id || me.user.role === 'admin') ? (<Button variant="primary" icon="shield" onClick={() => setAuthorize({ req: req(pending), retry: pending.status === 'failed' })}>{pending.status === 'failed' ? 'Retry publish…' : 'Authorize…'}</Button>) : null}
                {can('publish:authorize') ? <Button onClick={() => setReject(pending)}>Reject</Button> : null}
                {(pending.requested_by === me.user.id || me.user.role === 'admin') ? <Button variant="ghost" onClick={() => withdraw(pending)}>Withdraw</Button> : null}
                {pending.requested_by === me.user.id && me.user.role !== 'admin' ? <span className="muted small">Another person must authorize your request.</span> : null}
              </div>
            </div>
          </Card>) : null}

        {canRequest && !pending ? (<Card title="Request publishing" sub="A reviewer or admin authorizes it; nothing goes live from this form.">
            <div className="col gap-12">
              <div className="seg" role="radiogroup" aria-label="Mode">
                {(a.shopify_published ? ['update_live'] : ['publish_now', 'schedule']).map((m) => (<button key={m} role="radio" aria-checked={mode === m} aria-pressed={mode === m} onClick={() => setMode(m)}>{MODE_LABEL[m]}</button>))}
              </div>
              {mode === 'schedule' ? (<Field label={`Go live at (your local time, ${fmtZoned(new Date().toISOString()).split(' ').pop()})`}><input type="datetime-local" className="input" value={when} min={new Date(Date.now() + 15 * 60_000).toISOString().slice(0, 16)} onChange={(e) => setWhen(e.target.value)}/></Field>) : null}
              <Field label="Note for the approver"><input className="input" value={note} onChange={(e) => setNote(e.target.value)} placeholder="Optional"/></Field>
              <div><Button variant="primary" icon="send" loading={busy === 'request'} disabled={dirty || (mode === 'schedule' && !when)} onClick={request}>Send request</Button></div>
            </div>
          </Card>) : null}

        {!canRequest && !pending ? (<div className="callout info"><Icon name="info"/>
            {a.status === 'scheduled' ? `Scheduled by Flowmerce for ${fmtZoned(a.publish_at)}.` : a.status === 'published' ? 'This article is live and unchanged. Edit it to start an update.' : 'Publishing requests open once a reviewer approves the current version.'}
          </div>) : null}

        <Card title="Request history" flush>
          {detail.requests.length ? (<div className="table-wrap">
              <table className="t compact">
                <thead><tr><th>When</th><th>Mode</th><th>Status</th><th className="hide-sm">By</th><th className="hide-sm">Decision</th></tr></thead>
                <tbody>
                  {detail.requests.map((r) => (<tr key={r.id}>
                      <td className="nowrap small">{fmtDateTime(r.requested_at)}</td>
                      <td className="small">{MODE_LABEL[r.mode]} · v{r.version}</td>
                      <td><Pill tone={r.status === 'executed' ? 'ok' : r.status === 'failed' ? 'crit' : r.status === 'pending' ? 'accent' : 'neutral'}>{r.status}</Pill></td>
                      <td className="hide-sm small">{r.requested_by_name ?? '—'}</td>
                      <td className="hide-sm small">{r.decided_by_name ? `${r.decided_by_name}${r.decision_note ? ': ' + r.decision_note : ''}` : r.decision_note || '—'}</td>
                    </tr>))}
                </tbody>
              </table>
            </div>) : <div className="card-body muted small">No publish requests yet.</div>}
        </Card>
      </div>

      <div className="col" style={{ gap: 16 }}>
        <Card title="Shopify">
          <Kv items={[
            ['Store', brand.shopDomain],
            ['Shopify status', <span className="row"><ShopifyStatePill state={a.shopify_state} at={a.published_at} compact/>{a.live_url && a.shopify_published ? <a href={a.live_url} target="_blank" rel="noopener" className="small">Open <Icon name="external" size="sm"/></a> : null}</span>],
            [a.shopify_published ? 'Published' : 'Publication date', a.published_at ? <span title={fmtUtc(a.published_at)}>{fmtZoned(a.published_at)}</span> : '—'],
            ['First imported', originLabel(a.origin)],
            ['Kept in step via', syncLabel(a.shopify_sync)],
            ['Last synced', a.shopify_synced_at ? timeAgo(a.shopify_synced_at) : 'never'],
            ['Last sync error', a.last_error ? <span style={{ color: 'var(--crit)', overflowWrap: 'anywhere' }}>{a.last_error}</span> : 'None'],
            ['Live matches working copy', a.shopify_published ? (a.live_differs ? <span style={{ color: 'var(--warn)' }}>No — edits not live</span> : 'Yes') : '—'],
        ]}/>
          {can('shopify:draft') && !a.shopify_published ? (<div className="mt-16">
              <Button icon="upload" disabled={dirty || !brand.configured.shopifyAdmin || !a.approval_current} onClick={() => setConfirmDraft(true)}>{a.has_shopify_draft ? 'Update hidden draft' : 'Save as hidden Shopify draft'}</Button>
              {!brand.configured.shopifyAdmin ? <p className="muted xs mt-8">Needs the Shopify Admin API token for {brand.name}. See Integrations.</p>
                : !a.approval_current ? <p className="muted xs mt-8">Available once a reviewer approves this version. Any edit needs a new approval.</p>
                : <p className="muted xs mt-8">Creates or updates the article with visibility off. Customers cannot see it.</p>}
            </div>) : null}
        </Card>
      </div>

      {authorize ? <AuthorizeDialog req={authorize.req} retry={authorize.retry} onClose={() => setAuthorize(null)} onDone={() => { setAuthorize(null); onChanged(); }}/> : null}
      {reject ? <RejectDialog req={reject} onClose={() => setReject(null)} onDone={() => { setReject(null); onChanged(); }}/> : null}
      {confirmDraft ? (<ConfirmDialog title="Save hidden draft to Shopify" confirmLabel="Save hidden draft" busy={busy === 'draft'} onClose={() => setConfirmDraft(false)} onConfirm={saveDraft}>
          <p style={{ margin: 0 }}>Version {a.version} of “{a.title}” will be written to {brand.shopDomain} with <b>visibility: hidden</b>. It will not appear on the storefront.</p>
        </ConfirmDialog>) : null}
    </div>);
}
/* ---------------- Revisions ---------------- */
function blocks(html) {
    return html.split(/(?=<(?:h[1-6]|p|ul|ol|blockquote|table|figure)\b)/i).map((b) => b.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim()).filter(Boolean);
}
function RevisionsTab({ detail, current, onRestored }) {
    const [sel, setSel] = useState(detail.revisions[1]?.id ?? detail.revisions[0]?.id ?? null);
    const rev = useApi(sel ? `/articles/${detail.article.id}/revisions/${sel}` : null);
    const { can } = useApp();
    const toast = useToast();
    const [confirm, setConfirm] = useState(false);
    const [busy, setBusy] = useState(false);
    const restore = async () => {
        setBusy(true);
        try {
            await api.post(`/articles/${detail.article.id}/restore/${sel}`);
            toast.ok('Restored as a new version.');
            setConfirm(false);
            onRestored();
        }
        catch (e) {
            toast.error(e);
        }
        finally {
            setBusy(false);
        }
    };
    const d = rev.data?.data;
    const changed = d ? EDITABLE.filter((k) => k !== 'body_html' && (d[k] ?? '') !== (current[k] ?? '')) : [];
    const oldB = d ? blocks(d.body_html) : [];
    const newB = blocks(current.body_html);
    const removed = oldB.filter((b) => !newB.includes(b));
    const added = newB.filter((b) => !oldB.includes(b));
    return (<div className="grid side-main">
      <Card title="Versions" flush>
        <div className="alert-list">
          {detail.revisions.map((r) => (<button key={r.id} className="alert-item" style={{ border: 0, background: sel === r.id ? 'var(--accent-soft)' : 'none', textAlign: 'left', width: '100%', cursor: 'pointer', borderTop: '1px solid var(--line-2)' }} onClick={() => setSel(r.id)}>
              <span className="pill outline">v{r.version}</span>
              <span style={{ minWidth: 0, flex: 1 }}>
                <span className="small strong ellipsis" style={{ display: 'block' }}>{r.note || 'Edited'}</span>
                <span className="muted xs">{r.user_name ?? 'System'} · {fmtDateTime(r.created_at)}</span>
              </span>
              {r.content_hash === detail.article.approved_hash ? <Pill tone="ok">approved</Pill> : null}
              {r.content_hash === detail.article.live_hash ? <Pill tone="live">live</Pill> : null}
            </button>))}
        </div>
      </Card>
      <Card title={rev.data ? `Version ${rev.data.version} compared with the editor` : 'Select a version'} actions={can('article:write') && rev.data && rev.data.version !== detail.article.version ? <Button size="sm" icon="history" onClick={() => setConfirm(true)}>Restore this version</Button> : null}>
        {rev.loading ? <LoadingBlock /> : null}
        {d ? (<div className="col gap-12">
            {!changed.length && !removed.length && !added.length ? <div className="callout ok"><Icon name="check"/>Identical to the text in the editor.</div> : null}
            {changed.map((k) => (<div key={k}>
                <div className="label mb-8">{k.replace('_', ' ')}</div>
                <div className="small"><span className="diff-del">{(d[k] || '∅').replace(/<[^>]+>/g, '')}</span></div>
                <div className="small mt-4"><span className="diff-ins">{(current[k] || '∅').replace(/<[^>]+>/g, '')}</span></div>
              </div>))}
            {removed.length || added.length ? (<div>
                <div className="label mb-8">Body · {removed.length} paragraph{removed.length === 1 ? '' : 's'} removed, {added.length} added</div>
                <div className="col gap-4 small" style={{ maxHeight: 420, overflowY: 'auto' }}>
                  {removed.map((b, i) => <div key={'r' + i} className="diff-del" style={{ padding: '4px 8px', borderRadius: 6 }}>{b}</div>)}
                  {added.map((b, i) => <div key={'a' + i} className="diff-ins" style={{ padding: '4px 8px', borderRadius: 6 }}>{b}</div>)}
                </div>
              </div>) : null}
          </div>) : null}
      </Card>
      {confirm && rev.data ? (<ConfirmDialog title={`Restore version ${rev.data.version}?`} confirmLabel="Restore" busy={busy} onClose={() => setConfirm(false)} onConfirm={restore}>
          <p style={{ margin: 0 }}>The text of version {rev.data.version} becomes a new version. Nothing is deleted. If the article was approved, it will need review again.</p>
        </ConfirmDialog>) : null}
    </div>);
}
/* ---------------- Performance ---------------- */
function PerformanceTab({ detail }) {
    const a = detail.article;
    const { range } = useApp();
    const perf = useApi(a.live_url ? `/analytics/articles${qs({ brand: a.brand_id, from: range.from, to: range.to })}` : null);
    if (!a.live_url)
        return <Empty icon="analytics" title="Not live yet">Search and traffic numbers appear once the article is published and data is synced.</Empty>;
    const b = perf.data?.brands?.[0];
    const row = b?.rows.find((r) => r.id === a.id);
    return (<div className="col" style={{ gap: 16 }}>
      <div className="grid cols-2">
        <Card title="Search Console" sub={`${fmtDate(range.from)} – ${fmtDate(range.to)}`} actions={b ? <SourceBadge source={b.sources.gsc}/> : null}>
          {b?.sources.gsc.kind ? (<div className="kpis">
              <div className="kpi"><div className="kpi-label">Clicks</div><div className="kpi-value">{fmtInt(row?.clicks)}</div></div>
              <div className="kpi"><div className="kpi-label">Impressions</div><div className="kpi-value">{fmtCompact(row?.impressions)}</div></div>
              <div className="kpi"><div className="kpi-label">CTR</div><div className="kpi-value">{fmtPct(row?.ctr)}</div></div>
              <div className="kpi"><div className="kpi-label">Position</div><div className="kpi-value">{fmtPos(row?.position)}</div></div>
            </div>) : <div className="muted small">No Search Console data connected or imported.</div>}
        </Card>
        <Card title="GA4" sub="Sessions that landed on this article" actions={b ? <SourceBadge source={b.sources.ga4}/> : null}>
          {b?.sources.ga4.kind ? (<div className="kpis">
              <div className="kpi"><div className="kpi-label">Sessions</div><div className="kpi-value">{fmtInt(row?.sessions)}</div></div>
              <div className="kpi"><div className="kpi-label">Engagement rate</div><div className="kpi-value">{fmtPct(row?.engagementRate)}</div></div>
              <div className="kpi"><div className="kpi-label">Key events</div><div className="kpi-value">{fmtInt(row?.keyEvents)}</div></div>
            </div>) : <div className="muted small">No GA4 data connected or imported.</div>}
        </Card>
      </div>
      <Card title="Search queries for this article" sub={detail.queries ? `${fmtDate(detail.queries.period.from)} – ${fmtDate(detail.queries.period.to)}` : undefined} actions={detail.queries ? <SourceBadge kind={detail.queries.source} label={detail.queries.source === 'api' ? 'Live API' : detail.queries.source === 'excel' ? 'Excel import' : 'Demo data — not real'}/> : null} flush>
        {detail.queries?.rows.length ? (<div className="table-wrap">
            <table className="t compact">
              <thead><tr><th>Query</th><th className="r">Clicks</th><th className="r">Impr.</th><th className="r">Position</th></tr></thead>
              <tbody>{detail.queries.rows.map((r) => <tr key={r.query}><td>{r.query}</td><td className="r">{fmtInt(r.clicks)}</td><td className="r">{fmtInt(r.impressions)}</td><td className="r">{fmtPos(r.position)}</td></tr>)}</tbody>
            </table>
          </div>) : <div className="card-body muted small">No query data for this URL.</div>}
      </Card>
    </div>);
}
