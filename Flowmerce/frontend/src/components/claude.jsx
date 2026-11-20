'use client';
/*
 * Claude helpers shared by the SEO & Blog pages: the "Ask Claude" button for form fields, the daily-limit meter,
 * Claude's notes beside a draft, and the instructions panel (standing instructions + "Revise this draft").
 * Every Claude call goes through the server, which checks the daily limit before anything is sent.
 */
import { useEffect, useState } from 'react';
import { api } from '../lib/api';
import { useApp } from '../lib/app';
import { Button, Card, Field } from './ui';
import { Icon } from './Icon';
import { useToast } from './overlays';

export const usd = (n) => `$${Number(n ?? 0).toFixed(2)}`;

/** One line: today's Claude spend against the daily limit, and the month against the budget. */
export function BudgetLine({ budget }) {
    if (!budget)
        return null;
    const pct = budget.dailyLimitUsd > 0 ? Math.min(100, Math.round((budget.todayUsd / budget.dailyLimitUsd) * 100)) : 100;
    return (<div className="small muted" title={`The daily limit is the monthly budget divided by ${budget.daysInMonth} days. It resets at midnight.`}>
      <div className="row-wrap" style={{ gap: 6 }}>
        <Icon name="sparkle" size="sm"/>
        <span>Claude today <b>{usd(budget.todayUsd)}</b> of {usd(budget.dailyLimitUsd)}</span>
        <span>·</span><span>this month {usd(budget.monthUsd)} of {usd(budget.monthlyBudgetUsd)}</span>
      </div>
      <div style={{ height: 4, borderRadius: 4, background: 'var(--surface-3)', marginTop: 4, overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', background: pct >= 90 ? 'var(--crit)' : pct >= 70 ? 'var(--warn)' : 'var(--ok)' }}/>
      </div>
      <BudgetWarning budget={budget}/>
    </div>);
}

/** The warning shown when today's limit or the month's budget is nearly (or fully) used. */
export function BudgetWarning({ budget }) {
    const w = budget?.warning;
    if (!w)
        return null;
    return <div className={`callout ${w.level === 'crit' ? 'crit' : 'warn'} mt-8`} role="status"><Icon name="alert"/><div className="small">{w.message}</div></div>;
}

/** A button that asks Claude for one suggestion and hands it to onResult. Nothing is saved until the person applies it. */
export function AskClaude({ brand, kind, context, onResult, label = 'Ask Claude', size = 'sm', disabled, variant = 'secondary' }) {
    const toast = useToast();
    const [busy, setBusy] = useState(false);
    const run = async () => {
        setBusy(true);
        try {
            const r = await api.post('/ai/assist', { brand, kind, context: typeof context === 'function' ? context() : context });
            onResult(r.suggestion, r);
            toast.ok(`Claude answered (about ${usd(r.costUsd)}; today ${usd(r.budget.todayUsd)} of ${usd(r.budget.dailyLimitUsd)}).`);
            if (r.budget.warning)
                r.budget.warning.level === 'crit' ? toast.error(new Error(r.budget.warning.message)) : toast.info(r.budget.warning.message);
        }
        catch (e) {
            toast.error(e);
        }
        finally {
            setBusy(false);
        }
    };
    return <Button size={size} variant={variant} icon="sparkle" loading={busy} disabled={disabled || !brand} onClick={run}>{label}</Button>;
}

const NOTE_SECTIONS = [
    ['needs_confirmation', 'Confirm before publishing', 'alert'],
    ['recommendations', 'Recommendations', 'sparkle'],
    ['technical_checks', 'Checks for an admin', 'settings'],
    ['sources', 'Sources Claude used', 'library'],
];

/** Claude's notes for the latest draft or revision. Never published. */
export function ClaudeNotes({ notes }) {
    const has = notes && NOTE_SECTIONS.some(([k]) => notes[k]?.length) || notes?.next_article || notes?.image_brief;
    if (!has)
        return null;
    return (<Card title="Claude's notes" sub={notes.revision ? `After the change request: “${notes.revision.slice(0, 120)}”` : 'From the draft Claude wrote. Not published.'}>
      <div className="col gap-12">
        {NOTE_SECTIONS.map(([k, label, icon]) => (notes[k]?.length ? (<div key={k}>
            <div className="small strong row" style={{ gap: 6, marginBottom: 4 }}><Icon name={icon} size="sm"/>{label}</div>
            <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>{notes[k].map((x, i) => <li key={i} style={{ marginBottom: 2 }}>{x}</li>)}</ul>
          </div>) : null))}
        {notes.secondary_keywords?.length ? <div className="small"><span className="strong">Related keywords: </span>{notes.secondary_keywords.join(', ')}</div> : null}
        {notes.image_brief ? <div className="small"><span className="strong">Photo to take: </span>{notes.image_brief}</div> : null}
        {notes.next_article ? <div className="small"><span className="strong">Next article: </span>{notes.next_article}</div> : null}
      </div>
    </Card>);
}

/** Wait for an AI job to finish. Resolves with the final job (succeeded, failed or cancelled). */
async function waitForJob(id, onTick) {
    for (;;) {
        await new Promise((r) => setTimeout(r, 3000));
        const j = await api.get(`/ai/jobs/${id}`);
        onTick?.(j);
        if (['succeeded', 'failed', 'cancelled'].includes(j.status))
            return j;
    }
}

/**
 * "Ask Claude to revise" for this article: one text box and one button, nothing else (owner request 2026-11-20).
 * The brand's saved standing instructions still go with every request; they are no longer edited here.
 */
export function ClaudeInstructions({ article, dirty, onRevised }) {
    const { can } = useApp();
    const toast = useToast();
    const [ask, setAsk] = useState('');
    const [job, setJob] = useState(null);
    const revise = async () => {
        try {
            const r = await api.post('/ai/jobs', { brand: article.brand_id, task_type: 'content_revision',
                input: { article_id: article.id, base_version: article.version, instructions: ask } });
            setJob(r.job);
            const done = await waitForJob(r.job.id, setJob);
            if (done.status === 'succeeded') {
                toast.ok('Claude revised the draft. The new version is loaded; the old one is under History.');
                setAsk('');
                onRevised();
            }
            else
                toast.error(new Error(done.error || `The revision ${done.status}.`));
        }
        catch (e) {
            toast.error(e);
            setJob(null);
        }
    };
    const running = job && !['succeeded', 'failed', 'cancelled'].includes(job.status);
    if (!can('workflow:run') || article.status === 'scheduled')
        return null;
    return (<Card className="claude-ask">
      <div className="col gap-12">
        <textarea className="textarea" rows={4} value={ask} onChange={(e) => setAsk(e.target.value)} disabled={running} aria-label="Ask Claude to change this draft"
          placeholder="Ask Claude to change this draft…"/>
        <Button variant="primary" icon="sparkle" loading={running} disabled={!ask.trim() || dirty || running} onClick={revise}
          title={dirty ? 'Save your edits first: Claude works on the saved version' : 'Claude saves the result as a new version'}>{running ? (job.message || 'Working…') : 'Ask Claude to revise'}</Button>
      </div>
    </Card>);
}

const RUN_STEPS = [['research', 'Choosing a topic'], ['draft', 'Writing the draft'], ['revise', 'Fixing what the quality check found'], ['done', 'Approved and saved']];

/** "Write a blog": one click to a finished hidden Shopify draft (research, pick, draft, approve, save). Shows live progress. */
export function WriteBlog({ brand, size = 'sm', variant = 'primary', onDone }) {
    const toast = useToast();
    const [run, setRun] = useState(null);
    const [starting, setStarting] = useState(false);
    const busy = starting || run?.status === 'running';
    useEffect(() => {
        if (!brand)
            return undefined;
        let stop = false;
        api.get(`/autopilot?brand=${brand}`).then((r) => { if (!stop) setRun(r.runs.find((x) => x.status === 'running') ?? null); }).catch(() => {});
        return () => { stop = true; };
    }, [brand]);
    useEffect(() => {
        if (run?.status !== 'running')
            return undefined;
        const t = setInterval(async () => {
            try {
                const r = await api.get(`/autopilot/${run.id}`);
                setRun(r);
                if (r.status === 'done') {
                    toast.ok(`Blog ready: ${r.article_title ?? 'draft'}. ${r.message}`);
                    onDone?.(r);
                }
                else if (r.status === 'failed')
                    toast.error(new Error(`Write a blog stopped: ${r.message}`));
            }
            catch { /* try again on the next tick */ }
        }, 4000);
        return () => clearInterval(t);
    }, [run?.id, run?.status]); // eslint-disable-line react-hooks/exhaustive-deps
    const start = async () => {
        setStarting(true);
        try {
            setRun(await api.post('/autopilot', { brand }));
            toast.ok('Writing a blog: Claude picks a topic, writes it, and Flowmerce saves it as a hidden Shopify draft. About 5–10 minutes.');
        }
        catch (e) {
            toast.error(e);
        }
        finally {
            setStarting(false);
        }
    };
    const step = RUN_STEPS.findIndex(([k]) => k === run?.step);
    return (<span className="row-wrap" style={{ gap: 8 }}>
      <Button size={size} variant={variant} icon="sparkle" loading={busy} disabled={!brand || busy} onClick={start} title={brand ? 'Uses about $1.20 of the daily Claude limit' : 'Pick one brand first'}>
        {busy ? 'Writing…' : 'Write a blog'}
      </Button>
      {run?.status === 'running' ? <span className="small muted">{run.message || RUN_STEPS[step]?.[1]}</span> : null}
      {run?.status === 'done' && run.article_id ? <a className="small" href={`/articles/${run.article_id}`}>Open “{run.article_title}”</a> : null}
    </span>);
}
