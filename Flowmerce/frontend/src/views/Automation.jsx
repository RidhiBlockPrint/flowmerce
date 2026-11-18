'use client';
import { useEffect, useState } from 'react';
import Link from 'next/link';
import { api, useApi, qs } from '../lib/api';
import { useApp, useBrandParam } from '../lib/app';
import { fmtDateTime, timeAgo } from '../lib/format';
import { Button, Card, ErrorState, LoadingBlock, PageHead, Pill, BrandTag, Paged } from '../components/ui';
import { Dialog, useToast } from '../components/overlays';
import { Icon } from '../components/Icon';
const STATE = {
    ok: { label: 'OK', tone: 'ok' }, needs_action: { label: 'Needs action', tone: 'warn' }, failed: { label: 'Failed', tone: 'crit' },
    running: { label: 'Running', tone: 'info' }, paused: { label: 'Paused', tone: 'neutral' }, pending_setup: { label: 'Pending setup', tone: 'outline' }, idle: { label: 'Not run yet', tone: 'neutral' },
};
const RUN_TONE = { succeeded: 'ok', failed: 'crit', running: 'info', waiting: 'warn', skipped: 'neutral' };
const STAGE_LINK = {
    keyword_validation: '/topics?status=proposed', topic_approval: '/topics?status=validated', content_generation: '/topics?status=approved',
    content_approval: '/articles?status=in_review', image_selection: '/articles?status=draft,in_review,approved', shopify_draft: '/articles?status=approved', publication_approval: '/publishing',
};
export default function Automation() {
    const brand = useBrandParam();
    const { can, brandOf, me } = useApp();
    const q = useApi(`/automation${qs({ brand })}`);
    const toast = useToast();
    const [busy, setBusy] = useState(null);
    const [pause, setPause] = useState(null);
    const [focusJob, setFocusJob] = useState(null);
    const [jobsTick, setJobsTick] = useState(0);
    const runStage = async (b, stage, label) => {
        setBusy(`${b}:${stage}`);
        try {
            const r = await api.post(`/automation/${b}/stages/${stage}/run`);
            if (r.status === 'failed')
                toast.error(`${label} failed: ${r.error}`);
            else if (r.job) {
                toast.ok(`${label}: ${r.message}. Follow it under AI jobs.`);
                setFocusJob(r.job.id);
                setJobsTick((n) => n + 1);
            }
            else
                toast.ok(`${label}: ${r.message}`);
        }
        catch (e) {
            toast.error(e);
        }
        finally {
            setBusy(null);
            q.reload();
        }
    };
    const retry = async (id) => {
        setBusy(`run:${id}`);
        try {
            const r = await api.post(`/automation/runs/${id}/retry`);
            if (r.status === 'failed')
                toast.error(r.error);
            else
                toast.ok(r.message);
        }
        catch (e) {
            toast.error(e);
        }
        finally {
            setBusy(null);
            q.reload();
        }
    };
    const resume = async (b) => { try {
        await api.post(`/automation/${b}/resume`);
        toast.ok('Automation resumed.');
        q.reload();
    }
    catch (e) {
        toast.error(e);
    } };
    return (<>
      <PageHead title="Automation" sub="Topic research → keyword validation → topic approval → content generation → content approval → image selection → Shopify draft → publication approval → performance tracking. Automated stages run only when someone starts them; the background job only refreshes data."/>
      <ErrorState error={q.error} onRetry={q.reload}/>
      {q.loading && !q.data ? <LoadingBlock rows={8}/> : null}
      {q.data ? (<div className="col" style={{ gap: 20 }}>
          {['pending_setup', 'disabled'].includes(q.data.configured.ai?.state) ? <div className="callout warn"><Icon name="plug"/><div><b>AI execution is {q.data.configured.ai.state === 'disabled' ? 'switched off' : 'pending setup'}.</b> {q.data.configured.ai.reason} Topic research and content generation run as background AI jobs and wait for this. Everything else works. <Link href="/settings/integrations">Integrations</Link></div></div> : null}
          {q.data.brands.map((b) => (<section key={b.brand}>
              <div className="row-wrap mb-12">
                <span className={`brand-dot ${b.brand}`}/>
                <h2 className="serif" style={{ fontSize: 20 }}>{brandOf(b.brand).name}</h2>
                {b.paused ? <Pill tone="neutral" dot>Paused {b.pause?.paused_by_name ? `by ${b.pause.paused_by_name}` : ''} {timeAgo(b.pause?.paused_at)}{b.pause?.reason ? ` — ${b.pause.reason}` : ''}</Pill> : <Pill tone="ok" dot>Active</Pill>}
                <span className="spacer"/>
                {can('workflow:run') ? (b.paused
                    ? <Button size="sm" icon="play" onClick={() => resume(b.brand)}>Resume automation</Button>
                    : <Button size="sm" icon="pause" onClick={() => setPause(b.brand)}>Pause automation</Button>) : null}
              </div>
              <div className="stages">
                {b.stages.map((s, i) => (<div key={s.key} className={`stage ${s.state}`}>
                    <div className="row">
                      <span className="stage-num">{i + 1}</span>
                      <span className="strong" style={{ flex: 1 }}>{s.label}</span>
                      <Pill tone={STATE[s.state]?.tone ?? 'neutral'} dot>{STATE[s.state]?.label ?? s.state}</Pill>
                    </div>
                    <div className="muted small">{s.description}</div>
                    <div className="row-wrap xs muted">
                      <span className="row gap-4"><Icon name={s.kind === 'human' ? 'users' : 'automation'} size="sm"/>{s.kind === 'human' ? 'Person' : 'Automated'} · {s.owner}</span>
                      {s.lastRun ? <span title={fmtDateTime(s.lastRun.started_at)}>· last run {timeAgo(s.lastRun.started_at)} ({s.lastRun.trigger})</span> : null}
                    </div>
                    {s.lastRun?.message && s.lastRun.status !== 'failed' ? <div className="small">{s.lastRun.message}</div> : null}
                    {s.state === 'failed' ? <div className="err"><b>Error:</b> {s.lastRun?.error}</div> : null}
                    {s.setupGap ? <div className="small" style={{ color: 'var(--warn)' }}><Icon name="plug" size="sm"/> {s.setupGap}</div> : null}
                    {s.humanAction ? (<Link href={STAGE_LINK[s.key] ?? '#'} className="callout warn" style={{ padding: '7px 10px', textDecoration: 'none' }}>
                        <Icon name="arrowRight" size="sm"/><span className="small"><b>{s.pending} waiting:</b> {s.humanAction}</span>
                      </Link>) : null}
                    {s.kind === 'automated' && can('workflow:run') ? (<div className="row-wrap mt-4">
                        {s.state === 'failed' && s.lastRun && s.lastRun.trigger !== 'ai_job' ? <Button size="sm" variant="primary" icon="refresh" loading={busy === `run:${s.lastRun.id}`} disabled={b.paused} onClick={() => retry(s.lastRun.id)}>Retry</Button> : null}
                        <Button size="sm" icon="play" loading={busy === `${b.brand}:${s.key}`} disabled={b.paused || !!s.setupGap || s.state === 'running'} title={['topic_research', 'content_generation'].includes(s.key) ? 'Queues a background AI job' : undefined} onClick={() => runStage(b.brand, s.key, s.label)}>{['topic_research', 'content_generation'].includes(s.key) ? 'Queue AI job' : 'Run now'}</Button>
                      </div>) : null}
                  </div>))}
              </div>
            </section>))}


          <AiJobs brand={brand} focusJobId={focusJob} onFocusHandled={() => setFocusJob(null)} refreshKey={jobsTick} />

          <Card title="Run history" sub="Runs started here, by the background refresh, or reported by external agents through the webhook" flush>
            <Paged rows={q.data.runs} resetKey={brand}>{(pageRows) => (<>
<div className="table-wrap">
              <table className="t compact">
                <thead><tr><th>Started</th><th>Stage</th>{!brand ? <th className="hide-sm">Brand</th> : null}<th>Result</th><th className="hide-md">Message</th><th className="hide-sm">By</th><th /></tr></thead>
                <tbody>
                  {pageRows.map((r) => (<tr key={r.id}>
                      <td className="nowrap small" title={r.finished_at ? `finished ${fmtDateTime(r.finished_at)}` : ''}>{fmtDateTime(r.started_at)}</td>
                      <td className="small">{r.stage.replace(/_/g, ' ')}</td>
                      {!brand ? <td className="hide-sm"><BrandTag id={r.brand_id} brands={me.brands}/></td> : null}
                      <td><Pill tone={RUN_TONE[r.status] ?? 'neutral'}>{r.status}</Pill>{r.retry_of ? <span className="faint xs"> retry</span> : null}</td>
                      <td className="hide-md small" style={{ maxWidth: 420, overflowWrap: 'anywhere' }}>{r.error ? <span style={{ color: 'var(--crit)' }}>{r.error}</span> : r.message}</td>
                      <td className="hide-sm small">{r.user_name ?? (r.trigger_kind === 'scheduler' ? 'Scheduler' : r.trigger_kind === 'webhook' ? 'Webhook' : 'System')}</td>
                      <td className="r">{r.status === 'failed' && r.trigger_kind !== 'ai_job' && can('workflow:run') ? <Button size="xs" icon="refresh" loading={busy === `run:${r.id}`} onClick={() => retry(r.id)}>Retry</Button> : null}</td>
                    </tr>))}
                  {!q.data.runs.length ? <tr><td colSpan={7} className="muted small" style={{ padding: 16 }}>No runs yet. Start with “Performance tracking” to pull articles and products from both storefronts.</td></tr> : null}
                </tbody>
              </table>
            </div>
</>)}</Paged>
          </Card>
        </div>) : null}
      {pause ? <PauseDialog brand={pause} onClose={() => setPause(null)} onDone={() => { setPause(null); q.reload(); }}/> : null}
    </>);
}

const JOB_TONE = { pending: 'neutral', queued: 'info', running: 'info', succeeded: 'ok', failed: 'crit', cancelled: 'neutral' };
const JOB_LABEL = { pending: 'Pending', queued: 'Queued (worker accepted)', running: 'Running', succeeded: 'Succeeded', failed: 'Failed', cancelled: 'Cancelled' };
const TASKS = { topic_research: 'Topic research', content_generation: 'Draft for an approved topic' };
/** Why AI jobs can or cannot run right now, in the words the owner needs: which part is missing. */
function providerBanner(p) {
    if (!p) return null;
    if (p.mode === 'demo_simulated') return { tone: 'info', icon: 'sparkle', text: 'Demo build: jobs are run by a "Demo worker (simulated)" in your browser. No AI model or service is called; results are sample output for a person to review.' };
    if (p.state === 'ready') return { tone: 'ok', icon: 'checkCircle', text: (p.mode === 'anthropic_api' ? `Ready. Jobs run on this server with Claude (${p.model}).` : 'Ready. Jobs are sent to the AI worker, which reports back to the webhook.') + (p.notes?.length ? ` ${p.notes.join(' ')}` : '') };
    if (p.state === 'unavailable') return { tone: 'crit', icon: 'alert', text: `Worker unavailable. ${p.reason} Jobs wait and retry automatically.` };
    if (p.state === 'disabled') return { tone: 'info', icon: 'plug', text: 'AI job execution is switched off (AI_EXECUTION_MODE=disabled). The rest of Flowmerce is unaffected.' };
    const what = { worker_config: 'Worker not configured.', webhook_secret: 'Callback authentication not configured.', callback_url: 'Callback URL invalid.' }[p.missing] ?? 'API not configured.';
    return { tone: 'warn', icon: 'plug', text: `${what} ${p.reason} No job can be created until this is set up.` };
}
function AiJobs({ brand, focusJobId, onFocusHandled, refreshKey }) {
    const { can, me, brandOf } = useApp();
    const toast = useToast();
    const q = useApi(`/ai/jobs${qs({ brand })}`);
    const [busy, setBusy] = useState(null);
    const [open, setOpen] = useState(false);
    const [detail, setDetail] = useState(null);
    const active = (q.data?.jobs ?? []).some((j) => ['pending', 'queued', 'running'].includes(j.status));
    const reload = q.reload;
    useEffect(() => {
        if (refreshKey) reload();
    }, [refreshKey, reload]);
    useEffect(() => {
        if (!focusJobId) return;
        setDetail(focusJobId);   // show the job a stage run just created, with its status
        onFocusHandled?.();
    }, [focusJobId, onFocusHandled]);
    useEffect(() => {
        if (!active) return undefined;
        const t = setInterval(reload, 5000);
        return () => clearInterval(t);
    }, [active, reload]);
    const act = async (job, verb) => {
        setBusy(`${verb}:${job.id}`);
        try {
            await api.post(`/ai/jobs/${job.id}/${verb}`);
            toast.ok(verb === 'retry' ? 'Job queued again.' : 'Job cancelled.');
        }
        catch (e) {
            toast.error(e);
        }
        finally {
            setBusy(null);
            reload();
        }
    };
    const banner = providerBanner(q.data?.provider);
    return (<Card title="AI jobs" sub="Work handed to Claude, directly or through an AI worker. Results become proposed topics or draft articles; a person still reviews and approves them, and nothing here publishes." flush
      actions={can('workflow:run') ? <Button size="sm" variant="primary" icon="plus" disabled={q.data?.provider.state === 'pending_setup' || q.data?.provider.state === 'disabled'} onClick={() => setOpen(true)}>New AI job</Button> : null}>
      {banner ? <div className={`callout ${banner.tone}`} style={{ margin: 12 }}><Icon name={banner.icon}/><div className="small">{banner.text}</div></div> : null}
      <ErrorState error={q.error} onRetry={q.reload}/>
      <div className="table-wrap">
        <table className="t compact">
          <thead><tr><th>Job</th>{!brand ? <th className="hide-sm">Brand</th> : null}<th>Task</th><th>Status</th><th className="hide-md">Progress</th><th className="hide-md">Last update</th><th className="hide-md">Started</th><th className="hide-md">Finished</th><th>Result / reason</th><th /></tr></thead>
          <tbody>
            {(q.data?.jobs ?? []).map((j) => (<tr key={j.id}>
                <td className="mono small"><Button size="xs" variant="ghost" title={j.id} onClick={() => setDetail(j.id)}>{j.id.slice(0, 8)}</Button></td>
                {!brand ? <td className="hide-sm"><BrandTag id={j.brand} brands={me.brands}/></td> : null}
                <td className="small">{TASKS[j.taskType] ?? j.taskType}<div className="faint xs">{j.provider === 'demo_worker' ? 'Demo worker (simulated)' : j.provider === 'external_worker' ? 'AI worker' : 'Claude API'}{j.runNumber > 1 ? ` · attempt ${j.runNumber}` : ''}</div></td>
                <td><Pill tone={JOB_TONE[j.status] ?? 'neutral'} dot>{JOB_LABEL[j.status] ?? j.status}</Pill>{j.waitingForResume ? <div className="xs" style={{ color: 'var(--warn)' }}>waiting: automation is paused</div> : j.waitingOnProvider ? <div className="xs" style={{ color: 'var(--warn)' }}>waiting to retry ({j.retryCount}/{j.maxRetries})</div> : null}</td>
                <td className="hide-md small">{['running', 'queued'].includes(j.status) || j.progress ? `${j.progress}%` : '—'}</td>
                <td className="hide-md small nowrap" title={fmtDateTime(j.updatedAt)}>{timeAgo(j.lastProgressAt ?? j.updatedAt)}</td>
                <td className="hide-md small nowrap">{j.startedAt ? fmtDateTime(j.startedAt) : '—'}</td>
                <td className="hide-md small nowrap">{j.finishedAt ? fmtDateTime(j.finishedAt) : '—'}</td>
                <td className="small" style={{ maxWidth: 360, overflowWrap: 'anywhere' }}>
                  {j.status === 'failed' ? <span style={{ color: 'var(--crit)' }}>{j.error}</span> : j.resultAvailable ? <>{j.result.summary}{' '}{j.result.kind === 'topics' ? <Link href="/topics?status=proposed">Review topics</Link> : <Link href={`/articles/${j.result.articleId}`}>Open draft</Link>}</> : <span className="muted">{j.message}</span>}
                </td>
                <td className="r nowrap">
                  {can('workflow:run') && j.retryAvailable ? <Button size="xs" icon="refresh" loading={busy === `retry:${j.id}`} disabled={j.brandPaused} title={j.brandPaused ? 'Resume automation for this brand to retry' : undefined} onClick={() => act(j, 'retry')}>Retry</Button> : null}
                  {can('workflow:run') && j.cancellable ? <Button size="xs" variant="ghost" loading={busy === `cancel:${j.id}`} onClick={() => act(j, 'cancel')}>Cancel</Button> : null}
                </td>
              </tr>))}
            {!q.data && q.loading ? <tr><td colSpan={10} className="muted small" style={{ padding: 16 }}>Loading AI jobs…</td></tr> : null}
            {!q.data && q.error ? <tr><td colSpan={10} className="muted small" style={{ padding: 16 }}>AI jobs could not be loaded, so none are shown. This does not mean there are none.</td></tr> : null}
            {q.data && !q.data.jobs.length ? <tr><td colSpan={10} className="muted small" style={{ padding: 16 }}>No AI jobs yet.</td></tr> : null}
          </tbody>
        </table>
      </div>
      {open ? <NewJobDialog defaultBrand={brand} onClose={() => setOpen(false)} onDone={() => { setOpen(false); reload(); }}/> : null}
      {detail ? <JobDetail id={detail} brandOf={brandOf} onClose={() => setDetail(null)}/> : null}
    </Card>);
}
function NewJobDialog({ defaultBrand, onClose, onDone }) {
    const { me } = useApp();
    const toast = useToast();
    const [b, setB] = useState(defaultBrand || me.brands[0]?.id);
    const [task, setTask] = useState('topic_research');
    const [topic, setTopic] = useState('');
    const [busy, setBusy] = useState(false);
    const topics = useApi(task === 'content_generation' ? `/topics${qs({ brand: b, status: 'approved' })}` : null);
    const waiting = (topics.data ?? []).filter((t) => !t.article_id);
    const go = async () => {
        setBusy(true);
        try {
            const r = await api.post('/ai/jobs', { brand: b, task_type: task, input: task === 'content_generation' ? { topic_id: Number(topic) } : {} });
            toast.ok(r.deduplicated ? 'That job already exists, showing it.' : 'Job created. It runs in the background.');
            onDone();
        }
        catch (e) {
            toast.error(e);
        }
        finally {
            setBusy(false);
        }
    };
    return (<Dialog title="New AI job" sub="The job is saved first, then run in the background. You can leave this page." onClose={onClose} footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button variant="primary" loading={busy} disabled={task === 'content_generation' && !topic} onClick={go}>Create job</Button></>}>
      <div className="field"><label htmlFor="aj-b">Brand</label><select id="aj-b" className="select" value={b} onChange={(e) => { setB(e.target.value); setTopic(''); }}>{me.brands.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</select></div>
      <div className="field"><label htmlFor="aj-t">Task</label><select id="aj-t" className="select" value={task} onChange={(e) => setTask(e.target.value)}>{Object.entries(TASKS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></div>
      {task === 'content_generation' ? (<div className="field"><label htmlFor="aj-p">Approved topic</label>
        <select id="aj-p" className="select" value={topic} onChange={(e) => setTopic(e.target.value)}><option value="">Choose a topic…</option>{waiting.map((t) => <option key={t.id} value={t.id}>{t.title}</option>)}</select>
        {topics.data && !waiting.length ? <div className="muted small mt-4">No approved topics are waiting for a draft.</div> : null}</div>) : null}
    </Dialog>);
}
function JobDetail({ id, brandOf, onClose }) {
    const q = useApi(`/ai/jobs/${id}`);
    const j = q.data;
    const live = !!j && ['pending', 'queued', 'running'].includes(j.status);
    const reloadJob = q.reload;
    useEffect(() => {
        if (!live) return undefined;
        const t = setInterval(reloadJob, 3000);   // follow the job while it runs
        return () => clearInterval(t);
    }, [live, reloadJob]);
    return (<Dialog title={`AI job ${id.slice(0, 8)}`} sub={j ? `${brandOf(j.brand).name} · ${TASKS[j.taskType] ?? j.taskType}` : ''} onClose={onClose} footer={<Button variant="primary" onClick={onClose}>Close</Button>}>
      <ErrorState error={q.error} onRetry={q.reload}/>
      {j ? (<div className="col gap-8 small">
          <div className="mono xs" style={{ overflowWrap: 'anywhere' }}>{j.id}{j.externalId ? ` · external ${j.externalId}` : ''}{j.workerId ? ` · worker ${j.workerId}` : ''}</div>
          <div>Status <b>{JOB_LABEL[j.status] ?? j.status}</b> · attempt {j.runNumber} · retries {j.retryCount}/{j.maxRetries}</div>
          {j.error ? <div className="err"><b>Error{j.errorKind ? ` (${j.errorKind})` : ''}:</b> {j.error}</div> : null}
          <h4>History</h4>
          <ul className="col gap-4" style={{ listStyle: 'none', padding: 0 }}>{j.events.map((e, i) => (<li key={i} className="xs"><span className="muted">{fmtDateTime(e.created_at)}</span> · {e.event_type}{e.progress != null ? ` ${e.progress}%` : ''}{e.message ? ` — ${e.message}` : ''}{e.source === 'worker' ? ' (worker)' : ''}</li>))}</ul>
        </div>) : <LoadingBlock rows={4}/>}
    </Dialog>);
}
function PauseDialog({ brand, onClose, onDone }) {
    const [reason, setReason] = useState('');
    const [busy, setBusy] = useState(false);
    const toast = useToast();
    const go = async () => { setBusy(true); try {
        await api.post(`/automation/${brand}/pause`, { reason });
        toast.ok('Automation paused.');
        onDone();
    }
    catch (e) {
        toast.error(e);
    }
    finally {
        setBusy(false);
    } };
    return (<Dialog title="Pause automation" sub="Stops the background refresh and blocks automated stages for this brand until resumed. Manual editing, reviews and publishing are unaffected." onClose={onClose} footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button variant="primary" loading={busy} onClick={go}>Pause</Button></>}>
      <div className="field"><label htmlFor="pr">Reason (shown to the team)</label><input id="pr" data-autofocus className="input" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Holiday content freeze"/></div>
    </Dialog>);
}
