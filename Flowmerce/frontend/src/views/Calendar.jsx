'use client';
/*
 * Content calendar: upcoming events and seasons with their "publish by" dates, and the schedule of what Flowmerce
 * researches, drafts and puts forward for publishing on which day, plus the automatic blogs (services/auto_blog.py).
 * Every kind of item has its own colour lane; a two-week strip sits on top. Clicking a day opens a panel: first what
 * Flowmerce does that day, then a form to schedule another task for it. Scheduled Claude work runs within the daily
 * limit; a scheduled publish only creates a publish request, which a reviewer still authorizes.
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
/** Colour lane, label and icon of each kind of calendar item (CSS classes .lane-*). */
const LANE = {
    event: { cls: 'lane-event', label: 'Event', icon: 'star' },
    deadline: { cls: 'lane-due', label: 'Publish by', icon: 'flag' },
    research: { cls: 'lane-research', label: 'Research', icon: 'search' },
    draft: { cls: 'lane-draft', label: 'Draft', icon: 'edit' },
    publish: { cls: 'lane-publish', label: 'Publish request', icon: 'publish' },
    live: { cls: 'lane-live', label: 'Goes live', icon: 'clock' },
    auto: { cls: 'lane-auto', label: 'Automatic blog', icon: 'sparkle' },
};
const laneOf = (it) => (it.kind === 'entry' ? it.s.action : it.kind);
const AUTO_STATUS = { planned: 'Planned', writing: 'Writing', ready: 'Ready, waiting for a reviewer', failed: 'Stopped', missed: 'Missed', skipped: 'Skipped' };
const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
const addDays = (s, n) => { const d = new Date(`${s}T12:00:00`); d.setDate(d.getDate() + n); return iso(d); };

export default function Calendar() {
    const brand = useBrandParam();
    const { can, me } = useApp();
    const toast = useToast();
    const [view, setView] = useState('month');
    const [anchor, setAnchor] = useState(() => iso(new Date()));
    const month = anchor.slice(0, 7);
    const first = `${month}-01`;
    const monday = (s) => addDays(s, -((new Date(`${s}T12:00:00`).getDay() + 6) % 7));
    const gridStart = view === 'month' ? monday(first) : view === 'twoweeks' ? monday(anchor) : anchor;
    const gridLen = view === 'month' ? 42 : view === 'twoweeks' ? 14 : 30;
    const gridEnd = addDays(gridStart, gridLen - 1);
    const cal = useApi(`/calendar${qs({ brand, from: gridStart, to: gridEnd })}`);
    const auto = useApi(`/blog/overview${qs({ brand })}`);
    const [adding, setAdding] = useState(null);
    const [selDay, setSelDay] = useState(null);
    const [hidden, setHidden] = useState(() => new Set());
    const [hover, setHover] = useState(null);
    const [addingEvent, setAddingEvent] = useState(false);
    const [planning, setPlanning] = useState(false);
    const [busy, setBusy] = useState('');
    const shift = (n) => {
        if (view === 'month') {
            const d = new Date(`${first}T12:00:00`);
            d.setMonth(d.getMonth() + n);
            setAnchor(iso(d));
        }
        else
            setAnchor(addDays(anchor, n * (view === 'twoweeks' ? 14 : 30)));
    };
    const toggleFilter = (k) => setHidden((h) => { const n = new Set(h); if (n.has(k)) n.delete(k); else n.add(k); return n; });
    const byDay = useMemo(() => {
        const m = {};
        const push = (day, item) => { (m[day] ||= []).push(item); };
        for (const e of cal.data?.events ?? []) {
            push(e.date, { kind: 'event', e });
            if (e.lead_days > 0)
                push(e.publish_by, { kind: 'deadline', e });
        }
        // An automatic blog stands for its own publish request and go-live, so those are not listed a second time.
        const autoArticles = new Set((auto.data?.slots ?? []).filter((s) => s.article_id && s.status !== 'skipped').map((s) => s.article_id));
        for (const s of cal.data?.schedule ?? [])
            if (!(s.action === 'publish' && autoArticles.has(s.article_id)))
                push(s.run_on, { kind: 'entry', s });
        for (const a of cal.data?.scheduledPublishes ?? [])
            if (!autoArticles.has(a.id))
                push(a.publish_at.slice(0, 10), { kind: 'live', a });
        for (const s of auto.data?.slots ?? [])
            if (s.status !== 'skipped')
                push(s.publish_on, { kind: 'auto', slot: s });
        return m;
    }, [cal.data, auto.data]);
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
    const removeEntry = async (s) => {
        try { await api.del(`/calendar/schedule/${s.id}`); cal.reload(); } catch (e) { toast.error(e); }
    };
    if (cal.error)
        return <ErrorState error={cal.error} onRetry={cal.reload}/>;
    const today = cal.data?.budget?.today ?? iso(new Date());
    const days = Array.from({ length: gridLen }, (_, i) => addDays(gridStart, i));
    const day = selDay ?? today;
    const isHidden = (it) => hidden.has(laneOf(it)) || (brandOf(it) && hidden.has(`b:${brandOf(it)}`));
    const title = view === 'month' ? new Date(`${first}T12:00:00`).toLocaleDateString('en-GB', { month: 'long', year: 'numeric' })
        : `${fmtDate(gridStart, { day: 'numeric', month: 'short' })} – ${fmtDate(gridEnd, { day: 'numeric', month: 'short', year: 'numeric' })}`;
    const cell = (d, i) => {
        const items = byDay[d] ?? [];
        return (<button type="button" key={d} role="gridcell" onClick={() => setSelDay(d)}
          className={`lanecal-day${d === today ? ' today' : ''}${d === day ? ' sel' : ''}${d < today ? ' past' : ''}${view === 'month' && d.slice(0, 7) !== month ? ' other' : ''}${view === 'twoweeks' ? ' tall' : ''}`}
          aria-pressed={d === day} aria-label={`${fmtDate(d)}: ${items.length ? `${items.length} item${items.length === 1 ? '' : 's'}` : 'nothing planned'}`}>
          <span className="lanecal-num">{view === 'twoweeks' ? `${WEEKDAYS[i % 7]} ${Number(d.slice(8))}` : Number(d.slice(8))}{d === today ? <span className="pill info" style={{ height: 18, padding: '0 6px' }}>Today</span> : null}</span>
          {items.slice(0, view === 'twoweeks' ? 6 : 3).map((it, k) => <DayItem key={k} it={it} delay={(i % 7) * 25 + k * 40} dim={isHidden(it)} short
            hl={hover && chainOf(it) === hover} onHover={setHover}/>)}
          {items.length > (view === 'twoweeks' ? 6 : 3) ? <span className="lanecal-more">+{items.length - (view === 'twoweeks' ? 6 : 3)} more</span> : null}
          <span className="lanecal-load" aria-hidden="true"><span style={{ width: `${Math.min(100, items.length * 25)}%` }}/></span>
        </button>);
    };
    return (<div>
      <PageHead title="Content calendar" sub="What to write, for which event, and when."
        actions={<>
          {can('topic:write') ? <Button icon="plus" onClick={() => setAddingEvent(true)}>Add event</Button> : null}
          {can('workflow:run') ? <Button icon="calendar" onClick={() => setAdding({ run_on: today })}>Schedule a task</Button> : null}
          {can('workflow:run') ? <Button icon="calendar" disabled={!brand} onClick={() => setPlanning(true)} title={brand ? '' : 'Pick one brand at the top first'}>Plan upcoming events</Button> : null}
          {can('workflow:run') && brand ? <WriteBlog brand={brand} onDone={cal.reload}/> : null}
        </>}/>

      <div className="col" style={{ gap: 16 }}>
        <Card title={title}
          actions={<div className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
            <div className="seg sm" role="group" aria-label="View">
              {[['month', 'Month'], ['twoweeks', '2 weeks'], ['agenda', 'Agenda']].map(([k, l]) => <button key={k} aria-pressed={view === k} onClick={() => { setView(k); setAnchor(view === 'month' && k !== 'month' ? today : anchor); }}>{l}</button>)}
            </div>
            <Button size="sm" variant="ghost" icon="chevronLeft" iconOnly aria-label="Earlier" onClick={() => shift(-1)}/>
            <Button size="sm" variant="ghost" onClick={() => { setAnchor(today); setSelDay(today); }}>Today</Button>
            <Button size="sm" variant="ghost" icon="chevronRight" iconOnly aria-label="Later" onClick={() => shift(1)}/>
          </div>}>
          <div className="calfilters" role="group" aria-label="Show">
            {Object.entries(LANE).map(([k, l]) => <button type="button" key={k} className={`lane-chip ${l.cls} calfilter${hidden.has(k) ? ' off' : ''}`} aria-pressed={!hidden.has(k)} onClick={() => toggleFilter(k)}><Icon name={l.icon} size="sm"/>{l.label}</button>)}
            {me.brands.map((b) => <button type="button" key={b.id} className={`calfilter brandfilter${hidden.has(`b:${b.id}`) ? ' off' : ''}`} aria-pressed={!hidden.has(`b:${b.id}`)} onClick={() => toggleFilter(`b:${b.id}`)}><span className={`brand-dot ${b.id}`}/>{b.short}</button>)}
          </div>
          {cal.loading && !cal.data ? <LoadingBlock rows={6}/> : (<div className="calwrap">
            <div style={{ minWidth: 0 }}>
              {view === 'month' ? <TwoWeeks today={today} byDay={byDay} onPick={setSelDay}/> : null}
              {view === 'agenda' ? <Agenda days={days} byDay={byDay} today={today} day={day} onPick={setSelDay} isHidden={isHidden} hover={hover} onHover={setHover}/>
                  : (<div className="lanecal" role="grid" aria-label={view === 'month' ? 'Month' : 'Two weeks'}>
                    {view === 'month' ? WEEKDAYS.map((d) => <div key={d} className="lanecal-head" role="columnheader">{d}</div>) : null}
                    {days.map(cell)}
                  </div>)}
              <div className="small muted mt-8">Click a day to see what Flowmerce does then and to schedule a task. Hover an item to light up the other steps of the same blog.</div>
            </div>
            <DaySide day={day} today={today} items={byDay[day] ?? []} all={cal.data?.schedule ?? []} upcoming={cal.data?.upcoming ?? []} canRun={can('workflow:run')} brands={me.brands}
              budget={cal.data?.budget} onChanged={() => { cal.reload(); auto.reload(); }} onSkip={(s) => setStatus(s, 'skipped')} onRemove={removeEntry}/>
          </div>)}
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

      <Card title="Schedule in this view" className="mt-16" flush>
        {(cal.data?.schedule ?? []).length ? (<Paged rows={cal.data.schedule} resetKey={`${brand}|${gridStart}`}>{(pageRows) => (<table className="table">
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
                  {can('workflow:run') && s.status !== 'done' ? <Button size="xs" variant="ghost" icon="x" iconOnly aria-label="Delete" onClick={() => removeEntry(s)}/> : null}</td>
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

/** What an item is called on the calendar and in the day panel. */
function itemText(it) {
    if (it.kind === 'event')
        return it.e.name;
    if (it.kind === 'deadline')
        return it.e.name;
    if (it.kind === 'live')
        return it.a.title;
    if (it.kind === 'auto')
        return it.slot.article_title || it.slot.topic_title || 'Topic chosen 5 days before';
    const s = it.s;
    return s.action === 'publish' ? s.article_title : s.event_name || s.focus || s.topic_title || ACTION[s.action][0];
}
const brandOf = (it) => (it.kind === 'entry' ? it.s.brand_id : it.kind === 'live' ? it.a.brand_id : it.kind === 'auto' ? it.slot.brand_id : it.e.brand_id || '');

/** Items that belong to one blog share a key: the event they are for, else the article or topic. */
function chainOf(it) {
    if (it.kind === 'event' || it.kind === 'deadline')
        return `e:${it.e.key}`;
    if (it.kind === 'entry')
        return it.s.event_key ? `e:${it.s.event_key}` : it.s.article_id ? `a:${it.s.article_id}` : it.s.topic_id ? `t:${it.s.topic_id}` : null;
    if (it.kind === 'auto')
        return it.slot.article_id ? `a:${it.slot.article_id}` : null;
    return it.kind === 'live' ? `a:${it.a.id}` : null;
}
/** When in the day an item happens: research and drafting run during the day, publishing at 10:00 (business time). */
const timeOf = (it) => (it.kind === 'event' ? 'All day' : it.kind === 'deadline' ? 'By today' : it.kind === 'live' || it.kind === 'auto' || (it.kind === 'entry' && it.s.action === 'publish') ? '10:00' : 'During the day');

/** One chip on the grid: its colour lane, brand dot and short text. Dimmed by the filters; lit up with its chain. */
function DayItem({ it, delay, dim, hl, onHover, short }) {
    const lane = LANE[laneOf(it)];
    const b = brandOf(it);
    const off = (it.kind === 'entry' && it.s.status === 'skipped') || (it.kind === 'auto' && ['missed', 'failed'].includes(it.slot.status));
    const key = chainOf(it);
    return (<span className={`lane-chip ${lane.cls}${off ? ' off' : ''}${dim ? ' dim' : ''}${hl ? ' hl' : ''}`} style={{ animationDelay: `${delay}ms` }} title={`${lane.label}: ${itemText(it)}`}
      onMouseEnter={key && onHover ? () => onHover(key) : undefined} onMouseLeave={key && onHover ? () => onHover(null) : undefined}>
      {b ? <span className={`brand-dot ${b}`}/> : <Icon name={lane.icon} size="sm"/>}
      {short && b ? <Icon name={lane.icon} size="sm"/> : null}
      <span className="lane-text">{it.kind === 'event' || short ? itemText(it) : `${lane.label} · ${itemText(it)}`}</span>
    </span>);
}

/** The next 14 days as a strip: today in ink, one coloured bar per kind of item on each day. Click a day to open it. */
function TwoWeeks({ today, byDay, onPick }) {
    const days = Array.from({ length: 14 }, (_, i) => addDays(today, i));
    const count = days.reduce((n, d) => n + (byDay[d]?.length ?? 0), 0);
    return (<div className="twoweeks">
      <div className="twoweeks-head"><b>Next 14 days</b><span className="small muted">{count} item{count === 1 ? '' : 's'}</span></div>
      <div className="twoweeks-row">
        {days.map((d) => {
            const lanes = [...new Set((byDay[d] ?? []).map(laneOf))];
            return (<button type="button" key={d} className={`twoweeks-day${d === today ? ' today' : ''}`} onClick={() => onPick(d)} title={fmtDate(d)}>
              <span className="twoweeks-wd">{WEEKDAYS[(new Date(`${d}T12:00:00`).getDay() + 6) % 7]}</span>
              <span className="twoweeks-n">{Number(d.slice(8))}</span>
              <span className="twoweeks-bars">{lanes.map((l) => <i key={l} className={LANE[l].cls}/>)}</span>
            </button>);
        })}
      </div>
    </div>);
}

/** Agenda: the days of the view that have something on them, as rows. */
function Agenda({ days, byDay, today, day, onPick, isHidden, hover, onHover }) {
    const busy = days.filter((d) => (byDay[d] ?? []).length);
    if (!busy.length)
        return <div className="daypanel-empty">Nothing is planned in these 30 days.</div>;
    return (<div className="agenda stagger">
      {busy.map((d) => (<button type="button" key={d} className={`agenda-row${d === day ? ' sel' : ''}${d === today ? ' today' : ''}`} onClick={() => onPick(d)}>
        <span className="agenda-date"><span className="agenda-wd">{fmtDate(d, { weekday: 'short' })}</span><span className="agenda-n">{fmtDate(d, { day: 'numeric', month: 'short' })}</span></span>
        <span className="agenda-items">{byDay[d].map((it, k) => <DayItem key={k} it={it} delay={k * 40} dim={isHidden(it)} hl={hover && chainOf(it) === hover} onHover={onHover}/>)}</span>
      </button>))}
    </div>);
}

/**
 * The selected day, beside the calendar (under it on narrow screens). First what Flowmerce does that day, as a
 * timeline with times; then a form to schedule another task for it (today or later only).
 */
function DaySide({ day, today, items, all, upcoming, canRun, brands, budget, onChanged, onSkip, onRemove }) {
    const toast = useToast();
    const order = ['event', 'deadline', 'research', 'draft', 'publish', 'live', 'auto'];
    const sorted = [...items].sort((a, b) => order.indexOf(laneOf(a)) - order.indexOf(laneOf(b)));
    const title = new Date(`${day}T12:00:00`).toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long' });
    return (<aside className="dayside" aria-label={`What happens on ${title}`}>
      <h3 className="dayside-title">{title}</h3>
      <div className="small muted">{sorted.length ? `${sorted.length} thing${sorted.length === 1 ? '' : 's'} Flowmerce does this day` : 'Nothing planned yet'}</div>
      <div className="daypanel-label mt-12"><Icon name="sparkle" size="sm"/>What Flowmerce does</div>
      {sorted.length ? (<div className="dtimeline">
          {sorted.map((it, i) => (<div key={`${day}-${i}`} className={`dtl-item ${LANE[laneOf(it)].cls}`} style={{ animationDelay: `${i * 60}ms` }}>
            <span className="dtl-time">{timeOf(it)}</span>
            <DayDetail it={it} brands={brands} canRun={canRun} onSkip={onSkip} onRemove={onRemove} all={all}/>
          </div>))}
        </div>) : <div className="daypanel-empty">{day >= today ? 'A free day: a good one for topic research.' : 'Nothing happened on this day.'}</div>}
      <div className="daypanel-label mt-16"><Icon name="plus" size="sm"/>Schedule another task</div>
      {!canRun ? <div className="small muted">Your role cannot schedule tasks.</div>
          : day < today ? <div className="small muted">This day has passed. Pick today or a later day to schedule a task.</div>
              : (<>
                <ScheduleForm key={day} initial={{ run_on: day }} upcoming={upcoming} compact submitLabel={`Add to ${fmtDate(day, { weekday: 'short', day: 'numeric', month: 'short' })}`}
                  onSaved={() => { toast.ok('Added to the calendar.'); onChanged(); }}/>
                {budget?.estimates ? <div className="muted xs mt-8">Research costs about {usd(budget.estimates.topic_research)} and a draft about {usd(budget.estimates.content_generation)} of the daily Claude limit; a publish request costs nothing.</div> : null}
              </>)}
    </aside>);
}

/** How far one blog has got: research, draft, then live. From the calendar entries of the same event, or an automatic blog's state. */
function chainSteps(it, all) {
    if (it.kind === 'auto') {
        const s = it.slot.status;
        return [['Topic', ['writing', 'ready'].includes(s)], ['Written', s === 'ready'], ['Live', it.slot.article_status === 'published']];
    }
    const key = it.kind === 'entry' ? it.s.event_key : it.kind === 'event' || it.kind === 'deadline' ? it.e.key : '';
    if (!key)
        return null;
    const of = (a) => all.filter((s) => s.event_key === key && s.action === a);
    if (!all.some((s) => s.event_key === key))
        return null;
    const done = (a) => of(a).some((s) => s.status === 'done');
    return [['Research', done('research')], ['Draft', done('draft')], ['Live', done('publish')]];
}

function DayDetail({ it, brands, canRun, onSkip, onRemove, all = [] }) {
    const lane = LANE[laneOf(it)];
    const b = brandOf(it);
    let state = null;
    let more = null;
    let actions = null;
    if (it.kind === 'entry') {
        const s = it.s;
        state = <Pill tone={TONE[s.status]}>{s.status}</Pill>;
        more = (<>{s.topic_title ? <div>Topic: {s.topic_title}</div> : null}{s.message ? <div>{s.message}</div> : null}</>);
        actions = canRun && s.status === 'planned' ? (<><Button size="xs" variant="ghost" onClick={() => onSkip(s)}>Skip</Button>
          <Button size="xs" variant="ghost" icon="x" onClick={() => onRemove(s)}>Remove</Button></>) : null;
        if (s.article_id)
            actions = <>{actions}<Link className="btn ghost xs" href={`/articles/${s.article_id}`}>Open article</Link></>;
    }
    else if (it.kind === 'auto') {
        const s = it.slot;
        state = <Pill tone={s.status === 'ready' ? 'ok' : s.status === 'writing' ? 'info' : ['failed', 'missed'].includes(s.status) ? 'warn' : 'neutral'}>{AUTO_STATUS[s.status] ?? s.status}</Pill>;
        more = (<>{s.message ? <div>{s.message}</div> : <div>Goes live at 10:00 once a reviewer authorizes it.</div>}
          {s.checks?.score !== null && s.checks?.score !== undefined ? <div>Quality check: {s.checks.score}/100</div> : null}</>);
        actions = s.article_id ? <Link className="btn ghost xs" href={`/articles/${s.article_id}`}>Open article</Link> : <Link className="btn ghost xs" href="/blog">SEO &amp; Blog overview</Link>;
    }
    else if (it.kind === 'live') {
        const at = new Date(it.a.publish_at).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
        state = it.a.status === 'scheduled' ? <Pill tone="ok">Scheduled</Pill> : it.a.status === 'published' ? <Pill tone="ok">Live</Pill> : <Pill tone="warn">Waiting for a reviewer</Pill>;
        more = <div>{it.a.status === 'scheduled' ? `Scheduled on Shopify for ${at}.` : it.a.status === 'published' ? `Went live at ${at}.` : `Goes live at ${at} once a reviewer authorizes the publish request.`}</div>;
        actions = <Link className="btn ghost xs" href={`/articles/${it.a.id}`}>Open article</Link>;
    }
    else if (it.kind === 'deadline') {
        more = <div>An article for {it.e.name} ({fmtDate(it.e.date)}) should be live by today.</div>;
    }
    else if (it.e.note) {
        more = <div>{it.e.note}</div>;
    }
    return (<div className={`daydetail ${lane.cls}`}>
      <div className="daydetail-head">
        <span className="daydetail-kind"><Icon name={lane.icon} size="sm"/>{lane.label}</span>
        {b ? <BrandTag id={b} brands={brands}/> : null}
        <span className="spacer"/>{state}
      </div>
      <div className="daydetail-title">{itemText(it)}</div>
      {(() => {
          const steps = chainSteps(it, all);
          return steps ? (<div className="chainbar" title={steps.map(([l, ok]) => `${l}: ${ok ? 'done' : 'not yet'}`).join(' · ')}>
            {steps.map(([l, ok]) => <span key={l} className={ok ? 'on' : ''}><i/>{l}</span>)}
          </div>) : null;
      })()}
      {more ? <div className="daydetail-more">{more}</div> : null}
      {actions ? <div className="row-wrap" style={{ gap: 6, marginTop: 6 }}>{actions}</div> : null}
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
    return (<Dialog wide title="Schedule a task" sub="Flowmerce does it on that day. Claude tasks wait if the daily limit is used up; a publish request is made once the article is approved, and a reviewer still authorizes it." onClose={onClose}>
      <ScheduleForm initial={initial} upcoming={upcoming} onSaved={onSaved} onCancel={onClose}/>
    </Dialog>);
}

/** The task form, used in the "Schedule a task" dialog and in a day's panel. */
function ScheduleForm({ initial, upcoming, onSaved, onCancel, submitLabel = 'Add to schedule', compact }) {
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
            setF((x) => ({ ...x, focus: '', topic_id: '', article_id: '' }));
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
    return (<div className={compact ? 'schedform compact' : 'schedform'}>
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
      <div className="row mt-12" style={{ gap: 8, justifyContent: 'flex-end' }}>
        {onCancel ? <Button variant="ghost" onClick={onCancel}>Cancel</Button> : null}
        <Button variant="primary" loading={busy} disabled={!ok} onClick={save}>{submitLabel}</Button>
      </div>
    </div>);
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
