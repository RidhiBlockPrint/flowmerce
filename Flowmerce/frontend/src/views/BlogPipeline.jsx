'use client';
/**
 * Blog pipeline (SEO & Blog): every blog in the order it is built, on one page, with the button for its next step right
 * beside it. Owner request 2026-11-24: "I generate a title, then have to go to another section to see it, another to draft
 * it, and after Claude drafts it I cannot see where to schedule it." So the steps are lined up here:
 *
 *   1 Topics            Claude's ideas and your own: approve or reject; an approved topic gets "Draft with Claude"
 *   2 Claude is writing  runs and Claude jobs in progress, each with Stop
 *   3 Drafts & review    send for review, approve (reviewers), or open the editor
 *   4 Ready to schedule  approved blogs: "Schedule…" picks the go-live date and time (admins can authorize at once)
 *   5 Scheduled          waiting for a reviewer, or authorized: hidden on Shopify until its time
 *   6 Live               on the storefront
 *
 * Drafts stay in Flowmerce: nothing reaches Shopify before step 5's authorization. Built only from existing endpoints
 * (/topics, /articles, /ai/jobs, /autopilot, /publishing), so the demo serves it too.
 */
import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { api, qs, useApi } from '../lib/api';
import { useApp, useBrandParam } from '../lib/app';
import { fmtDate, fmtZoned, timeAgo } from '../lib/format';
import { BrandTag, Button, ErrorState, Field, LoadingBlock, PageHead, Paged, Pill, StatusPill } from '../components/ui';
import { Dialog, useToast } from '../components/overlays';
import { Icon } from '../components/Icon';
import { Journey } from '../components/dash';
import { WriteBlog } from '../components/claude';
import { AuthorizeDialog, ScheduleBlogDialog } from '../components/publish';

const ACTIVE = ['pending', 'queued', 'running'];
const DRAFTING = ['idea', 'draft', 'in_review', 'changes_requested'];
const STAGES = [
    { key: 'topics', label: 'Topics', sub: 'Ideas from Claude or you. Approve the ones worth writing, then let Claude draft them.' },
    { key: 'writing', label: 'Claude is writing', sub: 'In progress now. Stop one to cancel its unfinished Claude work.' },
    { key: 'drafts', label: 'Drafts & review', sub: 'Written, not approved yet. Send for review, or approve if you are a reviewer.' },
    { key: 'ready', label: 'Ready to schedule', sub: 'Approved and kept in Flowmerce. Pick the date and time each one goes live.' },
    { key: 'scheduled', label: 'Scheduled', sub: 'Waiting for a reviewer to authorize, or authorized: hidden on Shopify until its time.' },
    { key: 'live', label: 'Live', sub: 'On the storefront, newest first.' },
];

export default function BlogPipeline() {
    const brand = useBrandParam();
    const { can, me } = useApp();
    const toast = useToast();
    const topics = useApi(`/topics${qs({ brand })}`);
    const arts = useApi(`/articles${qs({ brand, limit: 200, sort: 'updated', dir: 'desc' })}`);
    const jobs = useApi(`/ai/jobs${qs({ brand })}`);
    const runs = useApi(`/autopilot${qs({ brand })}`);
    const pub = useApi(`/publishing${qs({ brand })}`);
    const ov = useApi(`/blog/overview${qs({ brand })}`);
    const [busy, setBusy] = useState('');
    const [scheduling, setScheduling] = useState(null);
    const [authorizing, setAuthorizing] = useState(null);
    const [asking, setAsking] = useState(false);
    const [dating, setDating] = useState(null);
    const reloadAll = () => { topics.reload(); arts.reload(); jobs.reload(); runs.reload(); pub.reload(); ov.reload(); };

    const d = useMemo(() => build(topics.data, arts.data, jobs.data, runs.data, pub.data, ov.data), [topics.data, arts.data, jobs.data, runs.data, pub.data, ov.data]);
    // While Claude is writing, look again every 8 seconds so finished blogs move on by themselves.
    const writing = d.writing.length;
    useEffect(() => {
        if (!writing)
            return undefined;
        const t = setInterval(() => { jobs.reload(); runs.reload(); topics.reload(); arts.reload(); }, 8000);
        return () => clearInterval(t);
    }, [writing]); // eslint-disable-line react-hooks/exhaustive-deps

    const act = async (key, fn, ok) => {
        setBusy(key);
        try {
            await fn();
            if (ok)
                toast.ok(ok);
            reloadAll();
        }
        catch (e) {
            toast.error(e);
        }
        finally {
            setBusy('');
        }
    };
    const error = topics.error || arts.error || jobs.error || pub.error;
    const loading = !topics.data || !arts.data || !pub.data;
    const go = (key) => document.getElementById(`stage-${key}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    const mayAuthorize = (r) => can('publish:authorize') && (r.requested_by !== me.user.id || me.user.role === 'admin');

    return (<>
      <PageHead title="Blog pipeline" sub="Every blog in building order: topic → draft → schedule → live. Each step's button is right here."
        actions={<>
          {can('workflow:run') ? <Button icon="search" disabled={!brand} onClick={() => setAsking(true)} title={brand ? 'Claude suggests topics (about $0.40)' : 'Pick one brand first'}>Ask Claude for topics</Button> : null}
          {can('workflow:run') && brand ? <WriteBlog brand={brand} onDone={reloadAll} onStart={reloadAll}/> : null}
        </>}/>
      <ErrorState error={error} onRetry={reloadAll}/>
      {loading && !error ? <LoadingBlock rows={8}/> : null}
      {!loading ? (<>
          <Journey compact label="Blog stages" steps={STAGES.map((s, i) => ({ key: s.key, label: `${i + 1} · ${s.label}`, value: d[s.key].length, done: s.key === 'live', onClick: () => go(s.key) }))}/>
          <div className="pipe">
            <Stage n={1} s={STAGES[0]} rows={d.topics} brand={brand} render={(t) => (<>
                <Cell title={t.title} sub={[t.primary_keyword, t.search_volume != null ? `${t.search_volume} searches/mo` : ''].filter(Boolean).join(' · ')} brandId={!brand && t.brand_id} brands={me.brands}/>
                <td>{t.slot ? <Pill tone="info" dot title="Flowmerce writes it 5 days before, then you authorize it">Blog on {fmtDate(t.slot.publish_on, { day: 'numeric', month: 'short' })}</Pill>
                    : <Pill tone={t.status === 'approved' ? 'ok' : t.status === 'validated' ? 'info' : 'neutral'} dot>{t.status}</Pill>}
                  {t.source === 'claude' ? <span className="pill outline" title="Suggested by Claude"><Icon name="sparkle" size="sm"/></span> : null}</td>
                <td className="r"><div className="row-wrap pipe-acts">
                  {t.slot && can('workflow:run') ? <Button size="xs" variant="ghost" icon="x" loading={busy === `sc${t.slot.id}`} title="Take it off the calendar: Claude will not write it for that day"
                      onClick={() => act(`sc${t.slot.id}`, () => api.post(`/blog/slots/${t.slot.id}/cancel`), 'Taken off the calendar.')}>Cancel</Button> : null}
                  {!t.slot && can('workflow:run') ? <Button size="xs" variant="primary" icon="calendar" title="Pick the day it goes live: Flowmerce writes, checks and schedules it"
                      onClick={() => setDating(t)}>Put on a day…</Button> : null}
                  {!t.slot && t.status !== 'approved' && can('topic:decide') ? (<>
                      <Button size="xs" icon="check" loading={busy === `ta${t.id}`} onClick={() => act(`ta${t.id}`, () => api.post(`/topics/${t.id}/decision`, { decision: 'approve' }), 'Topic approved. Draft it with Claude when you are ready.')}>Approve</Button>
                      <Button size="xs" variant="ghost" icon="x" aria-label="Reject" loading={busy === `tr${t.id}`} onClick={() => act(`tr${t.id}`, () => api.post(`/topics/${t.id}/decision`, { decision: 'reject' }), 'Topic rejected.')}/>
                    </>) : null}
                  {!t.slot && t.status === 'approved' && can('workflow:run') ? <Button size="xs" icon="sparkle" loading={busy === `td${t.id}`} title="Claude writes the full draft (about $0.80). It appears under Drafts in a few minutes."
                      onClick={() => act(`td${t.id}`, () => api.post(`/topics/${t.id}/article`, { mode: 'claude' }), 'Claude is writing it. It moves to “Drafts & review” when done.')}>Draft with Claude</Button> : null}
                  {!t.slot && t.status === 'approved' && can('article:write') ? <Button size="xs" variant="ghost" loading={busy === `tb${t.id}`}
                      onClick={() => act(`tb${t.id}`, () => api.post(`/topics/${t.id}/article`, { mode: 'blank' }), 'Blank article started. It is under “Drafts & review”.')}>Write myself</Button> : null}
                </div></td>
              </>)} empty={<>No open topics. Use <b>Ask Claude for topics</b>, or add one under Topics &amp; keywords.</>} foot={<Link className="small" href="/topics">All topics &amp; keywords</Link>}/>

            <Stage n={2} s={STAGES[1]} rows={d.writing} brand={brand} render={(w) => (<>
                <Cell title={w.title} sub={`${w.what} · started ${timeAgo(w.at)}`} brandId={!brand && w.brand_id} brands={me.brands}/>
                <td><Pill tone="info" dot>{w.message || 'Working'}</Pill></td>
                <td className="r">{can('workflow:run') ? <Button size="xs" variant="secondary" icon="pause" loading={busy === w.key} title="Stop it. Unfinished Claude work is cancelled; nothing is approved."
                    onClick={() => act(w.key, () => (w.run ? api.post(`/autopilot/${w.id}/stop`) : api.post(`/ai/jobs/${w.id}/cancel`)), 'Stopped. Claude will not spend any more on it.')}>Stop</Button> : null}</td>
              </>)} empty="Claude is not writing anything right now."/>

            <Stage n={3} s={STAGES[2]} rows={d.drafts} brand={brand} render={(a) => (<>
                <Cell title={<Link href={`/articles/${a.id}`}>{a.title}</Link>} sub={`v${a.version} · ${a.next_action?.label ?? ''} · updated ${timeAgo(a.updated_at)}`} brandId={!brand && a.brand_id} brands={me.brands}/>
                <td><StatusPill status={a.status}/></td>
                <td className="r"><div className="row-wrap pipe-acts">
                  {['draft', 'changes_requested'].includes(a.status) && can('article:submit') ? <Button size="xs" icon="send" loading={busy === `as${a.id}`}
                      onClick={() => act(`as${a.id}`, () => api.post(`/articles/${a.id}/submit`), 'Sent for review.')}>Send for review</Button> : null}
                  {a.status === 'in_review' && can('article:review') ? <Button size="xs" variant="primary" icon="check" loading={busy === `ar${a.id}`} title={`Approve version ${a.version} as it is. Open it to read it first or to request changes.`}
                      onClick={() => act(`ar${a.id}`, () => api.post(`/articles/${a.id}/review`, { decision: 'approve', version: a.version, note: '' }), 'Approved. It is now under “Ready to schedule”.')}>Approve</Button> : null}
                  <Link className="btn ghost xs" href={`/articles/${a.id}${a.status === 'in_review' ? '?tab=review' : ''}`}>Open</Link>
                </div></td>
              </>)} empty="No drafts waiting."/>

            <Stage n={4} s={STAGES[3]} rows={d.ready} brand={brand} render={(a) => (<>
                <Cell title={<Link href={`/articles/${a.id}`}>{a.title}</Link>} sub={`v${a.version} · approved · in Flowmerce only`} brandId={!brand && a.brand_id} brands={me.brands}/>
                <td><Pill tone="ok">Approved</Pill></td>
                <td className="r"><div className="row-wrap pipe-acts">
                  {can('publish:request') ? <Button size="xs" variant="primary" icon="calendar" onClick={() => setScheduling(a)}>Schedule…</Button> : null}
                  <Link className="btn ghost xs" href={`/articles/${a.id}`}>Open</Link>
                </div></td>
              </>)} empty="Nothing approved and waiting for a date."/>

            <Stage n={5} s={STAGES[4]} rows={d.scheduled} brand={brand} render={(a) => (<>
                <Cell title={<Link href={`/articles/${a.id}?tab=publish`}>{a.title}</Link>}
                  sub={a.publish_at ? `Goes live ${fmtZoned(a.publish_at)}` : a.req?.mode === 'publish_now' ? 'Goes live as soon as it is authorized' : ''} brandId={!brand && a.brand_id} brands={me.brands}/>
                <td>{a.status === 'scheduled' ? <Pill tone="ok" title="Authorized: on Shopify hidden, Shopify shows it at its time">Hidden on Shopify until then</Pill>
                    : a.req?.status === 'failed' ? <Pill tone="crit">Failed: retry in Publishing</Pill> : <Pill tone="warn">Waiting for a reviewer</Pill>}</td>
                <td className="r"><div className="row-wrap pipe-acts">
                  {a.req?.status === 'pending' && mayAuthorize(a.req) ? <Button size="xs" variant="primary" icon="shield" onClick={() => setAuthorizing({ ...a.req, title: a.title, brand_id: a.brand_id, version: a.version })}>Authorize…</Button> : null}
                  {a.req?.status === 'pending' && (a.req.requested_by === me.user.id || me.user.role === 'admin') ? <Button size="xs" variant="ghost" loading={busy === `w${a.id}`}
                      onClick={() => act(`w${a.id}`, () => api.post(`/publish-requests/${a.req.id}/cancel`), 'Schedule withdrawn. The blog is back under “Ready to schedule”.')}>Withdraw</Button> : null}
                  {a.status === 'scheduled' || a.req?.status === 'failed' ? <Link className="btn ghost xs" href="/publishing">Publishing</Link> : null}
                </div></td>
              </>)} empty="Nothing scheduled." foot={<Link className="small" href="/calendar">See them on the content calendar</Link>}/>

            <Stage n={6} s={STAGES[5]} rows={d.live} brand={brand} size={5} render={(a) => (<>
                <Cell title={<Link href={`/articles/${a.id}`}>{a.title}</Link>} sub={a.published_at ? `Live since ${fmtZoned(a.published_at)}` : 'Live'} brandId={!brand && a.brand_id} brands={me.brands}/>
                <td><Pill tone="ok">Live</Pill></td>
                <td className="r">{a.live_url ? <a className="btn ghost xs" href={a.live_url} target="_blank" rel="noopener">View <Icon name="external" size="sm"/></a> : null}</td>
              </>)} empty="Nothing live yet."/>
          </div>
        </>) : null}
      {scheduling ? <ScheduleBlogDialog article={scheduling} onClose={() => setScheduling(null)} onDone={(o) => { if (!o?.keepOpen) setScheduling(null); reloadAll(); }}/> : null}
      {authorizing ? <AuthorizeDialog req={authorizing} onClose={() => setAuthorizing(null)} onDone={() => { setAuthorizing(null); reloadAll(); }}/> : null}
      {dating ? <TopicDayDialog topic={dating} onClose={() => setDating(null)} onDone={() => { setDating(null); reloadAll(); }}/> : null}
      {asking ? <AskTopics brand={brand} onClose={() => setAsking(false)} onDone={() => { setAsking(false); reloadAll(); }}/> : null}
    </>);
}

/** Sort the loaded records into the six stages. */
function build(topics, arts, jobs, runs, pub, ov) {
    const slotOf = new Map((ov?.slots ?? []).filter((x) => x.topic_id && ['planned', 'writing', 'ready'].includes(x.status)).map((x) => [x.topic_id, x]));
    const rows = arts?.rows ?? [];
    const activeJobs = (jobs?.jobs ?? []).filter((j) => ACTIVE.includes(j.status));
    const activeRuns = (runs?.runs ?? []).filter((r) => r.status === 'running');
    const runJobIds = new Set(activeRuns.flatMap((r) => [r.research_job_id, r.draft_job_id, r.revise_job_id]).filter(Boolean));
    const topicTitle = new Map((topics ?? []).map((t) => [t.id, t.title]));
    const draftingTopics = new Set([...activeJobs.filter((j) => j.taskType === 'content_generation').map((j) => j.input?.topic_id), ...activeRuns.map((r) => r.topic_id)].filter(Boolean));
    const writing = [
        ...activeRuns.map((r) => ({ key: `r${r.id}`, id: r.id, run: true, brand_id: r.brand_id, at: r.created_at, message: r.message,
            title: r.topic_title || r.article_title || 'Choosing a topic', what: r.source === 'auto' ? 'Automatic blog' : 'Write a blog' })),
        ...activeJobs.filter((j) => !runJobIds.has(j.id) && ['topic_research', 'content_generation', 'content_revision'].includes(j.taskType)).map((j) => ({
            key: `j${j.id}`, id: j.id, run: false, brand_id: j.brand, at: j.createdAt, message: j.message,
            title: j.taskType === 'topic_research' ? `Topic ideas${j.input?.focus ? `: ${j.input.focus}` : ''}` : topicTitle.get(j.input?.topic_id) ?? 'A draft',
            what: j.taskType === 'topic_research' ? 'Researching topics' : j.taskType === 'content_revision' ? 'Revising a draft' : 'Writing a draft' })),
    ];
    const pending = new Map((pub?.requests ?? []).filter((r) => ['pending', 'failed'].includes(r.status)).map((r) => [r.article_id, r]));
    const byStatus = (st) => rows.filter((a) => st.includes(a.status));
    return {
        topics: (topics ?? []).filter((t) => (['proposed', 'validated'].includes(t.status) || (t.status === 'approved' && !t.article_id)) && !draftingTopics.has(t.id))
            .map((t) => ({ ...t, slot: slotOf.get(t.id)?.status === 'planned' ? slotOf.get(t.id) : null }))
            .sort((a, b) => (a.status === 'approved' ? 0 : 1) - (b.status === 'approved' ? 0 : 1)),
        writing,
        drafts: byStatus(DRAFTING),
        ready: rows.filter((a) => a.status === 'approved' && a.approval_current && !a.shopify_published),
        scheduled: [...byStatus(['publish_requested', 'failed']).filter((a) => pending.has(a.id)), ...byStatus(['scheduled'])]
            .map((a) => ({ ...a, req: pending.get(a.id) })).sort((a, b) => String(a.publish_at ?? '').localeCompare(String(b.publish_at ?? ''))),
        live: rows.filter((a) => a.shopify_published && a.status === 'published')
            .sort((a, b) => String(b.published_at ?? '').localeCompare(String(a.published_at ?? ''))),
    };
}

/** One stage: a numbered section with its rows, paged so a long stage does not push the next ones away. */
function Stage({ n, s, rows, render, empty, foot, size = 6, brand }) {
    return (<section id={`stage-${s.key}`} className={`card flush pipe-stage${rows.length ? '' : ' is-empty'}`}>
      <div className="card-head">
        <div style={{ minWidth: 0 }}>
          <h2 className="card-title"><span className="pipe-n">{n}</span>{s.label} <span className="muted">· {rows.length}</span></h2>
          <div className="card-sub">{s.sub}</div>
        </div>
        {foot ? <div className="row" style={{ marginLeft: 'auto' }}>{foot}</div> : null}
      </div>
      {rows.length ? (<Paged rows={rows} size={size} resetKey={`${brand}|${s.key}`}>{(page) => (<div className="table-wrap">
          <table className="t compact pipe-table"><tbody>{page.map((r) => <tr key={r.key ?? r.id}>{render(r)}</tr>)}</tbody></table>
        </div>)}</Paged>) : <div className="pipe-empty muted small">{empty}</div>}
    </section>);
}

function Cell({ title, sub, brandId, brands }) {
    return (<td className="title-cell">
      <span className="ttl">{title}</span>
      <span className="sub">{brandId ? <><BrandTag id={brandId} brands={brands}/> </> : null}{sub}</span>
    </td>);
}

/** Ask Claude for topic ideas with an optional focus; they land in stage 1 for approval. */
function AskTopics({ brand, onClose, onDone }) {
    const toast = useToast();
    const [focus, setFocus] = useState('');
    const [busy, setBusy] = useState(false);
    const go = async () => {
        setBusy(true);
        try {
            await api.post('/ai/jobs', { brand, task_type: 'topic_research', input: focus.trim() ? { focus: focus.trim() } : {} });
            toast.ok('Claude is researching topics. They appear under “Topics” in a few minutes.');
            onDone();
        }
        catch (e) {
            toast.error(e);
        }
        finally {
            setBusy(false);
        }
    };
    return (<Dialog title="Ask Claude for topics" sub="Claude suggests 3 topics with keywords. About $0.40 of the daily Claude limit." onClose={onClose}
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button variant="primary" icon="sparkle" loading={busy} onClick={go}>Ask Claude</Button></>}>
      <Field label="Focus (optional)" hint="What to look for, e.g. “round tablecloths for small apartments”. Empty: the next event or the brand's usual focus.">
        <input className="input" data-autofocus value={focus} onChange={(e) => setFocus(e.target.value)}/>
      </Field>
    </Dialog>);
}

/** Put a topic on a day: Flowmerce writes it 5 days before (at once if sooner), checks and approves it, and makes a publish
 * request for 10:00 that day, which you authorize with one click (POST /blog/slots). */
function TopicDayDialog({ topic, onClose, onDone }) {
    const toast = useToast();
    const todayIso = new Date().toISOString().slice(0, 10);
    const later = (n) => { const x = new Date(); x.setDate(x.getDate() + n); return `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, '0')}-${String(x.getDate()).padStart(2, '0')}`; };
    const [day, setDay] = useState(later(7));
    const [busy, setBusy] = useState(false);
    const go = async () => {
        setBusy(true);
        try {
            const slot = await api.post('/blog/slots', { brand: topic.brand_id, publish_on: day, topic_id: topic.id });
            toast.ok(`On the calendar for ${fmtDate(day, { weekday: 'short', day: 'numeric', month: 'short' })}. ${slot.status === 'writing' ? 'Claude has started writing it.' : 'Claude writes it 5 days before.'}`);
            onDone();
        }
        catch (e) {
            toast.error(e);
        }
        finally {
            setBusy(false);
        }
    };
    return (<Dialog title={`Put “${topic.title}” on a day`} sub="Flowmerce writes it 5 days before (straight away if the day is sooner), adds images, checks and approves it, and makes a publish request for 10:00 that day. You authorize it with one click."
      onClose={onClose} footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button variant="primary" icon="calendar" loading={busy} disabled={!day || day <= todayIso} onClick={go}>Put on the calendar</Button></>}>
      <Field label="Goes live on" hint="At 10:00 that day. Tomorrow or later."><input className="input" type="date" min={later(1)} value={day} onChange={(e) => setDay(e.target.value)}/></Field>
    </Dialog>);
}
