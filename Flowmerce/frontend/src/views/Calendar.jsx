'use client';
/*
 * Content calendar: upcoming events and seasons with their "publish by" dates, and the schedule of what Flowmerce
 * researches, drafts and puts forward for publishing on which day. Scheduled Claude work runs within the daily limit;
 * a scheduled publish only creates a publish request, which a reviewer still authorizes.
 */
import { useMemo, useState } from 'react';
import Link from 'next/link';
import { api, qs, useApi } from '../lib/api';
import { useApp, useBrandParam } from '../lib/app';
import { fmtDate } from '../lib/format';
import { BrandTag, Button, Card, Empty, ErrorState, Field, LoadingBlock, PageHead, Paged, Pill } from '../components/ui';
import { ConfirmDialog, Dialog, useToast } from '../components/overlays';
import { Icon } from '../components/Icon';
import { BudgetLine, WriteBlog, usd } from '../components/claude';

const ACTION = { research: ['Research topics', 'search'], draft: ['Write draft', 'edit'], publish: ['Publish request', 'publish'] };
const TONE = { planned: 'info', done: 'ok', skipped: 'neutral', failed: 'crit' };
const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
const addDays = (s, n) => { const d = new Date(`${s}T12:00:00`); d.setDate(d.getDate() + n); return iso(d); };

export default function Calendar() {
    const brand = useBrandParam();
    const { can, me } = useApp();
    const toast = useToast();
    const [month, setMonth] = useState(() => iso(new Date()).slice(0, 7));
    const first = `${month}-01`;
    const gridStart = addDays(first, -((new Date(`${first}T12:00:00`).getDay() + 6) % 7));
    const gridEnd = addDays(gridStart, 41);
    const cal = useApi(`/calendar${qs({ brand, from: gridStart, to: gridEnd })}`);
    const [adding, setAdding] = useState(null);
    const [addingEvent, setAddingEvent] = useState(false);
    const [planning, setPlanning] = useState(false);
    const [busy, setBusy] = useState('');
    const shift = (n) => { const d = new Date(`${first}T12:00:00`); d.setMonth(d.getMonth() + n); setMonth(iso(d).slice(0, 7)); };
    const byDay = useMemo(() => {
        const m = {};
        const push = (day, item) => { (m[day] ||= []).push(item); };
        for (const e of cal.data?.events ?? []) {
            push(e.date, { kind: 'event', e });
            if (e.lead_days > 0)
                push(e.publish_by, { kind: 'deadline', e });
        }
        for (const s of cal.data?.schedule ?? [])
            push(s.run_on, { kind: 'entry', s });
        for (const a of cal.data?.scheduledPublishes ?? [])
            push(a.publish_at.slice(0, 10), { kind: 'live', a });
        return m;
    }, [cal.data]);
    const startResearch = async (ev) => {
        if (!brand)
            return toast.error(new Error('Pick one brand at the top of the page first.'));
        setBusy(ev.key);
        try {
            await api.post('/ai/jobs', { brand, task_type: 'topic_research', input: { focus: `Upcoming: ${ev.name} (${ev.date}); publish by ${ev.publish_by}. ${ev.note || ''}`.trim() } });
            toast.ok(`Claude is researching topics for ${ev.name}. They appear under Topics & keywords for approval.`);
            cal.reload();
        }
        catch (e) {
            toast.error(e);
        }
        finally {
            setBusy('');
        }
    };
    const plan = async () => {
        setPlanning(false);
        try {
            const r = await api.post('/calendar/plan', { brand });
            toast.ok(r.count ? `Added ${r.count} schedule entries (research, then drafting) for upcoming events.` : 'Every upcoming event already has a plan.');
            cal.reload();
        }
        catch (e) {
            toast.error(e);
        }
    };
    const setStatus = async (s, status) => {
        try {
            await api.patch(`/calendar/schedule/${s.id}`, { status });
            cal.reload();
        }
        catch (e) {
            toast.error(e);
        }
    };
    if (cal.error)
        return <ErrorState error={cal.error} onRetry={cal.reload}/>;
    const today = cal.data?.budget?.today ?? iso(new Date());
    const days = Array.from({ length: 42 }, (_, i) => addDays(gridStart, i));
    return (<div>
      <PageHead title="Content calendar" sub="What to write, for which event, and when."
        actions={<>
          {can('topic:write') ? <Button icon="plus" onClick={() => setAddingEvent(true)}>Add event</Button> : null}
          {can('workflow:run') ? <Button icon="calendar" onClick={() => setAdding({ run_on: today })}>Schedule a task</Button> : null}
          {can('workflow:run') ? <Button icon="calendar" disabled={!brand} onClick={() => setPlanning(true)} title={brand ? '' : 'Pick one brand at the top first'}>Plan upcoming events</Button> : null}
          {can('workflow:run') && brand ? <WriteBlog brand={brand} onDone={cal.reload}/> : null}
        </>}/>

      <div className="col" style={{ gap: 16 }}>
        <Card title={new Date(`${first}T12:00:00`).toLocaleDateString(undefined, { month: 'long', year: 'numeric' })}
          actions={<div className="row" style={{ gap: 4 }}>
            <Button size="sm" variant="ghost" icon="chevronLeft" iconOnly aria-label="Previous month" onClick={() => shift(-1)}/>
            <Button size="sm" variant="ghost" onClick={() => setMonth(iso(new Date()).slice(0, 7))}>Today</Button>
            <Button size="sm" variant="ghost" icon="chevronRight" iconOnly aria-label="Next month" onClick={() => shift(1)}/>
          </div>}>
          {cal.loading && !cal.data ? <LoadingBlock rows={6}/> : (<div style={{ display: 'grid', gridTemplateColumns: 'repeat(7, minmax(0, 1fr))', gap: 4 }}>
              {WEEKDAYS.map((d) => <div key={d} className="small muted strong" style={{ padding: '2px 4px' }}>{d}</div>)}
              {days.map((d) => (<div key={d} onClick={() => can('workflow:run') && d >= today ? setAdding({ run_on: d }) : null}
                  style={{ minHeight: 92, padding: 4, borderRadius: 8, border: `1px solid ${d === today ? 'var(--saffron)' : 'var(--line)'}`,
                    background: d.slice(0, 7) === month ? 'var(--surface)' : 'var(--surface-2)', opacity: d < today ? 0.7 : 1, cursor: can('workflow:run') && d >= today ? 'pointer' : 'default', minWidth: 0 }}>
                  <div className="small" style={{ fontWeight: d === today ? 700 : 500 }}>{Number(d.slice(8))}</div>
                  {(byDay[d] ?? []).map((it, i) => <DayItem key={i} it={it} brands={me.brands}/>)}
                </div>))}
            </div>)}
          <div className="row-wrap small muted mt-8" style={{ gap: 12 }}>
            <span><Icon name="star" size="sm"/> Event</span><span><Icon name="flag" size="sm"/> Publish by</span>
            <span><Icon name="search" size="sm"/> Research</span><span><Icon name="edit" size="sm"/> Draft</span><span><Icon name="publish" size="sm"/> Publish request</span><span><Icon name="clock" size="sm"/> Scheduled to go live</span>
          </div>
        </Card>

        <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 320px), 1fr))', alignItems: 'start' }}>
          <Card title="Daily Claude limit"><BudgetForm budget={cal.data?.budget} onSaved={cal.reload} canEdit={can('integrations:manage')}/></Card>
          <Card title="Coming up" sub="Soonest first. Ask Claude starts topic research for that event now." flush>
            {cal.data?.upcoming?.length ? (<Paged rows={cal.data.upcoming} size={5} resetKey={brand}>{(pageRows) => (<div className="col">
                {pageRows.map((e) => {
                    const late = e.publish_by < today;
                    return (<div key={e.key} style={{ padding: '10px 16px', borderTop: '1px solid var(--line-2)' }}>
                      <div className="row-wrap" style={{ gap: 6 }}><span className="strong">{e.name}</span><span className="small muted">{fmtDate(e.date)}</span>{e.builtin ? null : <Pill tone="info">Your event</Pill>}</div>
                      <div className="small" style={{ color: late ? 'var(--warn)' : undefined }}>Publish by {fmtDate(e.publish_by)}{late ? ' (passed: a late article can still help)' : ''}</div>
                      {e.note ? <div className="small muted">{e.note}</div> : null}
                      {can('workflow:run') ? (<div className="row-wrap mt-4" style={{ gap: 6 }}>
                          <Button size="xs" icon="sparkle" loading={busy === e.key} disabled={!brand} onClick={() => startResearch(e)} title={brand ? 'Uses the daily Claude limit' : 'Pick one brand first'}>Ask Claude for topics</Button>
                          <Button size="xs" variant="ghost" onClick={() => setAdding({ action: 'research', event_key: e.key, run_on: e.publish_by > addDays(today, 21) ? addDays(e.publish_by, -21) : today })}>Schedule</Button>
                        </div>) : null}
                    </div>);
                })}
              </div>)}</Paged>) : <Empty icon="calendar" title="Nothing coming up">Add your own events, such as a sale or a collection launch.</Empty>}
          </Card>
        </div>
      </div>

      <Card title="Schedule this month" className="mt-16" flush>
        {(cal.data?.schedule ?? []).length ? (<Paged rows={cal.data.schedule} resetKey={`${brand}|${month}`}>{(pageRows) => (<table className="table">
            <thead><tr><th>Day</th><th>Brand</th><th>Task</th><th>For</th><th>Status</th><th/></tr></thead>
            <tbody>{pageRows.map((s) => (<tr key={s.id}>
                <td>{fmtDate(s.run_on)}</td>
                <td><BrandTag id={s.brand_id} brands={me.brands}/></td>
                <td><Icon name={ACTION[s.action][1]} size="sm"/> {ACTION[s.action][0]}</td>
                <td className="small">{s.event_name || s.focus || ''}{s.topic_title ? <div className="muted">Topic: {s.topic_title}</div> : null}
                  {s.article_id ? <div><Link href={`/articles/${s.article_id}`}>{s.article_title}</Link></div> : null}</td>
                <td><Pill tone={TONE[s.status]}>{s.status}</Pill>{s.message ? <div className="small muted">{s.message}</div> : null}</td>
                <td className="r">{can('workflow:run') && s.status === 'planned' ? <Button size="xs" variant="ghost" onClick={() => setStatus(s, 'skipped')}>Skip</Button> : null}
                  {can('workflow:run') && s.status === 'skipped' ? <Button size="xs" variant="ghost" onClick={() => setStatus(s, 'planned')}>Plan again</Button> : null}
                  {can('workflow:run') && s.status !== 'done' ? <Button size="xs" variant="ghost" icon="x" iconOnly aria-label="Delete" onClick={async () => { try { await api.del(`/calendar/schedule/${s.id}`); cal.reload(); } catch (e) { toast.error(e); } }}/> : null}</td>
              </tr>))}</tbody>
          </table>)}</Paged>) : <Empty icon="calendar" title="Nothing scheduled in this view">Click a day, use “Schedule a task”, or let Flowmerce plan upcoming events.</Empty>}
      </Card>

      {adding ? <ScheduleDialog initial={adding} upcoming={cal.data?.upcoming ?? []} onClose={() => setAdding(null)} onSaved={() => { setAdding(null); cal.reload(); }}/> : null}
      {addingEvent ? <EventDialog onClose={() => setAddingEvent(false)} onSaved={() => { setAddingEvent(false); cal.reload(); }}/> : null}
      {planning ? (<ConfirmDialog title="Plan upcoming events" confirmLabel="Add to the schedule" onClose={() => setPlanning(false)} onConfirm={plan}>
          For every event in the next 90 days that has no plan yet, Flowmerce adds two tasks: topic research about three weeks before its publish-by date, then a draft three days later.
          It puts at most one Claude task on any day, so the work stays inside the daily limit ({usd(cal.data?.budget?.dailyLimitUsd)} a day). Topics still need your approval before they are drafted, and nothing is published without a reviewer.
        </ConfirmDialog>) : null}
    </div>);
}

function DayItem({ it, brands }) {
    const style = { fontSize: 11.5, lineHeight: 1.3, padding: '1px 4px', borderRadius: 4, marginTop: 2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' };
    if (it.kind === 'event')
        return <div style={{ ...style, background: 'var(--info-soft, var(--surface-3))' }} title={`${it.e.name}${it.e.note ? ` — ${it.e.note}` : ''}`}><Icon name="star" size="sm"/> {it.e.name}</div>;
    if (it.kind === 'deadline')
        return <div style={{ ...style, background: 'var(--warn-soft)' }} title={`Article for ${it.e.name} should be live by today`}><Icon name="flag" size="sm"/> {it.e.name}</div>;
    if (it.kind === 'live')
        return <div style={style} title={`Goes live: ${it.a.title}`}><Icon name="clock" size="sm"/> {it.a.title}</div>;
    const s = it.s;
    const label = s.action === 'publish' ? s.article_title : s.event_name || s.focus || s.topic_title || ACTION[s.action][0];
    return (<div style={{ ...style, border: '1px solid var(--line)', textDecoration: s.status === 'skipped' ? 'line-through' : undefined }} title={`${ACTION[s.action][0]} (${s.status})${s.message ? ` — ${s.message}` : ''}`}>
      <span className={`brand-dot ${s.brand_id}`}/> <Icon name={ACTION[s.action][1]} size="sm"/> {label}
    </div>);
}

function BudgetForm({ budget, onSaved, canEdit }) {
    const toast = useToast();
    const [v, setV] = useState('');
    const [busy, setBusy] = useState(false);
    if (!budget)
        return <LoadingBlock rows={2}/>;
    const save = async () => {
        setBusy(true);
        try {
            await api.patch('/ai/budget', { monthlyBudgetUsd: Number(v) });
            setV('');
            toast.ok('Monthly Claude budget saved.');
            onSaved();
        }
        catch (e) {
            toast.error(e);
        }
        finally {
            setBusy(false);
        }
    };
    return (<div className="col gap-12">
      <BudgetLine budget={budget}/>
      <div className="small muted">{usd(budget.monthlyBudgetUsd)} a month ÷ {budget.daysInMonth} days = <b>{usd(budget.dailyLimitUsd)} a day</b>. Unused money does not carry over, so spending stays even across the month.
        A draft costs about {usd(budget.estimates?.content_generation)}, topic research about {usd(budget.estimates?.topic_research)}, an Ask Claude suggestion about {usd(budget.estimates?.assist)}.</div>
      {canEdit ? (<div className="row" style={{ gap: 6 }}>
          <input className="input sm" inputMode="decimal" placeholder={`Monthly budget, up to ${usd(budget.maxMonthlyUsd)} (now ${usd(budget.monthlyBudgetUsd)})`} value={v} onChange={(e) => setV(e.target.value.replace(/[^0-9.]/g, ''))}/>
          <Button size="sm" loading={busy} disabled={!v} onClick={save}>Save</Button>
        </div>) : null}
    </div>);
}

function ScheduleDialog({ initial, upcoming, onClose, onSaved }) {
    const { me, brand: current } = useApp();
    const [f, setF] = useState({ brand: current === 'all' ? 'ridhi' : current, action: initial.action ?? 'research', run_on: initial.run_on, event_key: initial.event_key ?? '', focus: '', topic_id: '', article_id: '' });
    const [busy, setBusy] = useState(false);
    const [err, setErr] = useState('');
    const topics = useApi(f.action === 'draft' ? `/topics${qs({ brand: f.brand, status: 'approved' })}` : null);
    const arts = useApi(f.action === 'publish' ? `/articles${qs({ brand: f.brand, limit: 200 })}` : null);
    const set = (k, v) => setF({ ...f, [k]: v });
    const save = async () => {
        setBusy(true);
        setErr('');
        try {
            await api.post('/calendar/schedule', { ...f, topic_id: f.topic_id ? Number(f.topic_id) : null, article_id: f.article_id ? Number(f.article_id) : null });
            onSaved();
        }
        catch (e) {
            setErr(e.message);
        }
        finally {
            setBusy(false);
        }
    };
    const ok = f.run_on && (f.action === 'research' ? f.event_key || f.focus.trim() : f.action === 'draft' ? f.topic_id || f.event_key : f.article_id);
    return (<Dialog wide title="Schedule a task" sub="Flowmerce does it on that day. Claude tasks wait if the daily limit is used up; a publish request is made once the article is approved, and a reviewer still authorizes it." onClose={onClose}
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button variant="primary" loading={busy} disabled={!ok} onClick={save}>Add to schedule</Button></>}>
      <div className="form-grid">
        <div className="field full"><label>Brand</label>
          <div className="seg">{me.brands.map((b) => <button key={b.id} aria-pressed={f.brand === b.id} onClick={() => setF({ ...f, brand: b.id, topic_id: '', article_id: '' })}><span className={`brand-dot ${b.id}`}/>{b.name}</button>)}</div>
        </div>
        <div className="field full"><label>Task</label>
          <div className="seg">{Object.entries(ACTION).map(([k, [label, icon]]) => <button key={k} aria-pressed={f.action === k} onClick={() => set('action', k)}><Icon name={icon} size="sm"/>{label}</button>)}</div>
        </div>
        <Field label={f.action === 'publish' ? 'Go-live day' : 'Day'}><input className="input" type="date" value={f.run_on} onChange={(e) => set('run_on', e.target.value)}/></Field>
        {f.action !== 'publish' ? (<Field label="Event">
            <select className="select" value={f.event_key} onChange={(e) => set('event_key', e.target.value)}>
              <option value="">{f.action === 'draft' ? 'None: pick a topic' : 'None: use the focus below'}</option>
              {upcoming.map((e) => <option key={e.key} value={e.key}>{e.name} · {fmtDate(e.date)}</option>)}
            </select>
          </Field>) : null}
        {f.action === 'research' ? <Field label="Focus" full hint="What Claude should look for, e.g. “round tablecloths for small apartments”."><input className="input" value={f.focus} onChange={(e) => set('focus', e.target.value)}/></Field> : null}
        {f.action === 'draft' ? (<Field label="Approved topic" full hint={f.event_key && !f.topic_id ? 'Without a topic, Flowmerce drafts the approved topic that best matches the event.' : undefined}>
            <select className="select" value={f.topic_id} onChange={(e) => set('topic_id', e.target.value)}>
              <option value="">{f.event_key ? 'Best match for the event' : 'Pick a topic'}</option>
              {(topics.data ?? []).filter((t) => !t.article_id).map((t) => <option key={t.id} value={t.id}>{t.title}</option>)}
            </select>
          </Field>) : null}
        {f.action === 'publish' ? (<Field label="Article" full hint="It must be reviewer-approved before the publish request can be made.">
            <select className="select" value={f.article_id} onChange={(e) => set('article_id', e.target.value)}>
              <option value="">Pick an article</option>
              {(arts.data?.rows ?? []).filter((a) => !a.shopify_published).map((a) => <option key={a.id} value={a.id}>{a.title} ({a.status.replace('_', ' ')})</option>)}
            </select>
          </Field>) : null}
      </div>
      {err ? <div className="callout crit mt-12"><Icon name="alert"/>{err}</div> : null}
    </Dialog>);
}

function EventDialog({ onClose, onSaved }) {
    const { me } = useApp();
    const [f, setF] = useState({ brand: '', name: '', date: '', lead_days: '30', note: '' });
    const [busy, setBusy] = useState(false);
    const [err, setErr] = useState('');
    const set = (k, v) => setF({ ...f, [k]: v });
    const save = async () => {
        setBusy(true);
        setErr('');
        try {
            await api.post('/calendar/events', { ...f, lead_days: Number(f.lead_days || 0) });
            onSaved();
        }
        catch (e) {
            setErr(e.message);
        }
        finally {
            setBusy(false);
        }
    };
    return (<Dialog title="Add an event" sub="A sale, a collection launch, a trade show: anything an article should be ready for." onClose={onClose}
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button variant="primary" loading={busy} disabled={!f.name.trim() || !f.date} onClick={save}>Add event</Button></>}>
      <div className="form-grid">
        <div className="field full"><label>For</label>
          <div className="seg"><button aria-pressed={!f.brand} onClick={() => set('brand', '')}>Both brands</button>
            {me.brands.map((b) => <button key={b.id} aria-pressed={f.brand === b.id} onClick={() => set('brand', b.id)}><span className={`brand-dot ${b.id}`}/>{b.name}</button>)}</div>
        </div>
        <Field label="Name" full><input className="input" data-autofocus value={f.name} onChange={(e) => set('name', e.target.value)}/></Field>
        <Field label="Date"><input className="input" type="date" value={f.date} onChange={(e) => set('date', e.target.value)}/></Field>
        <Field label="Lead time (days)" hint="How long before the event the article should be live."><input className="input" inputMode="numeric" value={f.lead_days} onChange={(e) => set('lead_days', e.target.value.replace(/\D/g, '').slice(0, 3))}/></Field>
        <Field label="Note for Claude" full hint="What the event is about, e.g. “Spring collection: pastel napkins and runners”."><input className="input" value={f.note} onChange={(e) => set('note', e.target.value)}/></Field>
      </div>
      {err ? <div className="callout crit mt-12"><Icon name="alert"/>{err}</div> : null}
    </Dialog>);
}
