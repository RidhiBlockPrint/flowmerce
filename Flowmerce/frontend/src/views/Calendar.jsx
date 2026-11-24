'use client';
/*
 * Content calendar: upcoming events and seasons with their "publish by" dates, the blogs Flowmerce writes for a day
 * (automatic ones, and topics a person put on a day), and the research, drafting and publish tasks.
 *
 * One screen (owner request 2026-11-24): the calendar takes exactly the height left in the window and its day cells share
 * it, so the whole month is visible without scrolling; the side panel beside it has three tabs (the selected day, events
 * coming up, the daily Claude limit) and scrolls inside itself. "List" shows the schedule as a table in the same space.
 *
 * "Blog on this day": pick a topic (or type a new one) and the go-live day. Flowmerce writes it 5 days before (at once if
 * sooner), checks and approves it, and makes a publish request for 10:00 that day; a reviewer authorizes it with one
 * click (owner decision 2026-11-24). Scheduled Claude work runs within the daily limit.
 */
import { useLayoutEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { api, qs, useApi } from '../lib/api';
import { useApp, useBrandParam } from '../lib/app';
import { fmtDate } from '../lib/format';
import { BrandTag, Button, ErrorState, Field, LoadingBlock, PageHead, Paged, Pill } from '../components/ui';
import { ConfirmDialog, Dialog, useToast } from '../components/overlays';
import { Icon } from '../components/Icon';
import { AutoBlogSwitch, BudgetLine, WriteBlog, usd } from '../components/claude';
import { ACTION, MonthNav, MonthPicker, ScheduleDialog, WEEKDAYS, addDays, addMonths, iso, mondayOf, useWheelMonths } from '../components/calendar';

const TONE = { planned: 'info', done: 'ok', skipped: 'neutral', failed: 'crit' };
/** Colour lane, label and icon of each kind of calendar item (CSS classes .lane-*). */
const LANE = {
    event: { cls: 'lane-event', label: 'Event', icon: 'star' },
    deadline: { cls: 'lane-due', label: 'Publish by', icon: 'flag' },
    auto: { cls: 'lane-auto', label: 'Blog', icon: 'sparkle' },
    research: { cls: 'lane-research', label: 'Research', icon: 'search' },
    draft: { cls: 'lane-draft', label: 'Draft', icon: 'edit' },
    publish: { cls: 'lane-publish', label: 'Publish request', icon: 'publish' },
    live: { cls: 'lane-live', label: 'Goes live', icon: 'clock' },
};
const laneOf = (it) => (it.kind === 'entry' ? it.s.action : it.kind);
const AUTO_STATUS = { planned: 'Planned', writing: 'Writing', ready: 'Ready, waiting for a reviewer', failed: 'Stopped', missed: 'Missed', skipped: 'Cancelled' };
const ITEM_H = 24;   // one chip in a day cell, with its gap
const CELL_TOP = 34;   // the day number and the cell padding
const MORE_H = 16;   // the "+2 more" line

/** What sits below an element down to the end of the page: its ancestors' bottom padding, borders and margins, and any
 * blocks after it. Measured from the layout itself, so a page's minimum height (empty space) never counts. */
function spaceBelow(el) {
    let below = 0;
    for (let n = el; n && n !== document.body; n = n.parentElement) {
        const cs = getComputedStyle(n);
        below += parseFloat(cs.marginBottom) || 0;
        if (n !== el)
            below += (parseFloat(cs.paddingBottom) || 0) + (parseFloat(cs.borderBottomWidth) || 0);
        for (let s = n.nextElementSibling; s; s = s.nextElementSibling) {
            const ss = getComputedStyle(s);
            if (!['absolute', 'fixed'].includes(ss.position) && ss.display !== 'none')
                below += s.offsetHeight + (parseFloat(ss.marginTop) || 0) + (parseFloat(ss.marginBottom) || 0);
        }
    }
    return below;
}

/** The height that makes the page end exactly at the bottom of the window: the window's height minus what sits above the
 * element and what sits below it. At least `min`; measured again when the window is resized and once fonts have loaded. */
function useFitHeight(min = 440) {
    const ref = useRef(null);
    const [h, setH] = useState(0);
    useLayoutEffect(() => {
        const fit = () => {
            const el = ref.current;
            if (el)
                setH(Math.max(min, Math.floor(window.innerHeight - (el.getBoundingClientRect().top + window.scrollY) - spaceBelow(el))));
        };
        fit();
        document.fonts?.ready.then(fit);
        window.addEventListener('resize', fit);
        return () => window.removeEventListener('resize', fit);
    });
    return [ref, h];
}

export default function Calendar() {
    const brand = useBrandParam();
    const { can, me } = useApp();
    const toast = useToast();
    const [view, setView] = useState('month');
    const [anchor, setAnchor] = useState(() => iso(new Date()));
    const month = anchor.slice(0, 7);
    const first = `${month}-01`;
    const gridStart = view === 'month' ? mondayOf(first) : view === 'twoweeks' ? mondayOf(anchor) : anchor;
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
    const [wrapRef, height] = useFitHeight();
    const mainRef = useRef(null);
    const todayIso = cal.data?.today ?? cal.data?.budget?.today ?? iso(new Date());
    /** Show a month (`YYYY-MM`), of any year: its first day is selected, or today in the current month. */
    const setMonth = (m) => {
        setAnchor(`${m}-01`);
        setSelDay(m === todayIso.slice(0, 7) ? todayIso : `${m}-01`);
    };
    const shift = (n) => {
        if (view === 'month')
            setMonth(addMonths(month, n));
        else
            setAnchor(addDays(anchor, n * (view === 'twoweeks' ? 14 : 30)));
    };
    // Scrolling over the month (or two weeks) moves to the next or previous one; PageUp / PageDown too.
    useWheelMonths(mainRef, shift, (view === 'month' || view === 'twoweeks') && !!cal.data);
    const toggleFilter = (k) => setHidden((h) => { const n = new Set(h); if (n.has(k)) n.delete(k); else n.add(k); return n; });
    const reload = () => { cal.reload(); auto.reload(); };
    const byDay = useMemo(() => {
        const m = {};
        const push = (day, item) => { (m[day] ||= []).push(item); };
        for (const e of cal.data?.events ?? []) {
            push(e.date, { kind: 'event', e });
            if (e.lead_days > 0)
                push(e.publish_by, { kind: 'deadline', e });
        }
        // A blog slot stands for its own publish request and go-live, so those are not listed a second time. The slots come
        // with the calendar's own range (GET /calendar), so any month or year shows its blogs.
        const autoArticles = new Set((cal.data?.slots ?? []).filter((s) => s.article_id && s.status !== 'skipped').map((s) => s.article_id));
        for (const s of cal.data?.slots ?? [])
            if (s.status !== 'skipped')
                push(s.publish_on, { kind: 'auto', slot: s });
        for (const s of cal.data?.schedule ?? [])
            if (!(s.action === 'publish' && autoArticles.has(s.article_id)))
                push(s.run_on, { kind: 'entry', s });
        for (const a of cal.data?.scheduledPublishes ?? [])
            if (!autoArticles.has(a.id))
                push(a.publish_at.slice(0, 10), { kind: 'live', a });
        return m;
    }, [cal.data]);
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
    /** Cancel a blog slot: one not started is skipped; one Claude is writing is stopped (its Claude work cancelled). */
    const cancelSlot = async (slot) => {
        try {
            await api.post(`/blog/slots/${slot.id}/cancel`);
            toast.ok(slot.status === 'writing' ? 'Stopped. Claude will not write a blog for this day.' : 'Cancelled. Claude will not write a blog for this day.');
            reload();
        }
        catch (e) {
            toast.error(e);
        }
    };
    if (cal.error)
        return <ErrorState error={cal.error} onRetry={cal.reload}/>;
    const today = todayIso;
    const days = Array.from({ length: gridLen }, (_, i) => addDays(gridStart, i));
    const day = selDay ?? today;
    const isHidden = (it) => hidden.has(laneOf(it)) || (brandOf(it) && hidden.has(`b:${brandOf(it)}`));
    const title = view === 'month' ? new Date(`${first}T12:00:00`).toLocaleDateString('en-GB', { month: 'long', year: 'numeric' })
        : `${fmtDate(gridStart, { day: 'numeric', month: 'short' })} – ${fmtDate(gridEnd, { day: 'numeric', month: 'short', year: 'numeric' })}`;
    // How many chips fit in a day cell: the rows share the calendar's height (6 rows a month, 2 for two weeks).
    const rows = view === 'month' ? 6 : 2;
    const cellH = height ? (height - (view === 'month' ? 24 : 0) - 6 * rows) / rows : 110;
    const perCell = Math.max(1, Math.min(8, Math.floor((cellH - CELL_TOP) / ITEM_H)));
    const perCellWithMore = Math.max(1, Math.min(8, Math.floor((cellH - CELL_TOP - MORE_H) / ITEM_H)));
    const cell = (d, i) => {
        const items = byDay[d] ?? [];
        const shown = items.length > perCell ? perCellWithMore : perCell;
        return (<button type="button" key={d} role="gridcell" onClick={() => setSelDay(d)}
          className={`lanecal-day${d === today ? ' today' : ''}${d === day ? ' sel' : ''}${d < today ? ' past' : ''}${view === 'month' && d.slice(0, 7) !== month ? ' other' : ''}`}
          aria-pressed={d === day} aria-label={`${fmtDate(d)}: ${items.length ? `${items.length} item${items.length === 1 ? '' : 's'}` : 'nothing planned'}`}>
          <span className="lanecal-num">{view === 'twoweeks' ? `${WEEKDAYS[i % 7]} ${Number(d.slice(8))}` : Number(d.slice(8))}{d === today ? <span className="pill info" style={{ height: 18, padding: '0 6px' }}>Today</span> : null}</span>
          {items.slice(0, shown).map((it, k) => <DayItem key={k} it={it} delay={(i % 7) * 25 + k * 40} dim={isHidden(it)} short
            hl={hover && chainOf(it) === hover} onHover={setHover}/>)}
          {items.length > shown ? <span className="lanecal-more">+{items.length - shown} more</span> : null}
        </button>);
    };
    return (<div>
      <PageHead title="Content calendar" sub="Put a topic on a day: Flowmerce writes, checks and schedules the blog for it."
        actions={<>
          {can('workflow:run') ? <Button variant="primary" icon="plus" onClick={() => setAdding({ action: 'blog', run_on: addDays(today, 7) })}>Blog on a day</Button> : null}
          {can('workflow:run') ? <Button icon="calendar" onClick={() => setAdding({ action: 'research', run_on: today })}>Schedule a task</Button> : null}
          {can('topic:write') ? <Button icon="star" onClick={() => setAddingEvent(true)}>Add event</Button> : null}
          {can('workflow:run') ? <Button icon="calendar" disabled={!brand} onClick={() => setPlanning(true)} title={brand ? 'Research and drafting tasks for upcoming events' : 'Pick one brand at the top first'}>Plan events</Button> : null}
          <AutoBlogSwitch enabled={auto.data?.settings.enabled} onChanged={auto.reload}/>
          {can('workflow:run') && brand ? <WriteBlog brand={brand} variant="secondary" onDone={reload}/> : null}
        </>}/>

      <section className="card calcard">
        <div className="card-head">
          {view === 'month' ? <MonthNav month={month} today={today} onChange={setMonth} onToday={() => { setAnchor(today); setSelDay(today); }}/>
              : (<div className="monthnav row" style={{ gap: 4 }}>
                <Button size="sm" variant="ghost" icon="chevronLeft" iconOnly aria-label="Earlier" onClick={() => shift(-1)}/>
                <MonthPicker month={month} today={today} onPick={setMonth} label={title}/>
                <Button size="sm" variant="ghost" icon="chevronRight" iconOnly aria-label="Later" onClick={() => shift(1)}/>
                <Button size="sm" variant="ghost" onClick={() => { setAnchor(today); setSelDay(today); }}>Today</Button>
              </div>)}
          <div className="row" style={{ gap: 6, flexWrap: 'wrap', marginLeft: 'auto' }}>
          <div className="calfilters" role="group" aria-label="Show">
            {Object.entries(LANE).map(([k, l]) => <button type="button" key={k} className={`lane-chip ${l.cls} calfilter${hidden.has(k) ? ' off' : ''}`} aria-pressed={!hidden.has(k)} onClick={() => toggleFilter(k)} title={`Show or hide: ${l.label}`}><Icon name={l.icon} size="sm"/>{l.label}</button>)}
            {me.brands.map((b) => <button type="button" key={b.id} className={`calfilter brandfilter${hidden.has(`b:${b.id}`) ? ' off' : ''}`} aria-pressed={!hidden.has(`b:${b.id}`)} onClick={() => toggleFilter(`b:${b.id}`)}><span className={`brand-dot ${b.id}`}/>{b.short}</button>)}
          </div>
          <div className="seg sm" role="group" aria-label="View">
            {[['month', 'Month'], ['twoweeks', '2 weeks'], ['agenda', 'Agenda'], ['list', 'List']].map(([k, l]) => <button key={k} aria-pressed={view === k} onClick={() => { setView(k); setAnchor(view === 'month' && k !== 'month' ? today : anchor); }}>{l}</button>)}
          </div>
          </div>
        </div>
        <div className="card-body">
        {cal.loading && !cal.data ? <LoadingBlock rows={6}/> : (<div className="calwrap fit" ref={wrapRef} style={height ? { height } : undefined}>
          <div className="calmain" ref={mainRef} title={view === 'month' || view === 'twoweeks' ? 'Scroll over the calendar to move to the next or previous month' : undefined}>
            {view === 'agenda' ? <Agenda days={days} byDay={byDay} today={today} day={day} onPick={setSelDay} isHidden={isHidden} hover={hover} onHover={setHover}/>
                : view === 'list' ? <ScheduleTable rows={cal.data?.schedule ?? []} brands={me.brands} canRun={can('workflow:run')} resetKey={`${brand}|${gridStart}`} onStatus={setStatus} onRemove={removeEntry}/>
                    : (<div className={`lanecal${view === 'month' ? ' has-head' : ''}`} style={{ gridTemplateRows: `${view === 'month' ? 'auto ' : ''}repeat(${rows}, minmax(0, 1fr))` }} role="grid" aria-label={view === 'month' ? 'Month' : 'Two weeks'}>
                      {view === 'month' ? WEEKDAYS.map((d) => <div key={d} className="lanecal-head" role="columnheader">{d}</div>) : null}
                      {days.map(cell)}
                    </div>)}
          </div>
          <DaySide day={day} today={today} items={byDay[day] ?? []} all={cal.data?.schedule ?? []} upcoming={cal.data?.upcoming ?? []} canRun={can('workflow:run')} brands={me.brands}
            budget={cal.data?.budget} brand={brand} onAdd={(initial) => setAdding(initial)} onBudgetSaved={cal.reload} canEditBudget={can('integrations:manage')}
            onSkip={(s) => setStatus(s, s.replan ? 'planned' : 'skipped')} onRemove={removeEntry} onCancelSlot={cancelSlot}/>
        </div>)}
        </div>
      </section>

      {adding ? <ScheduleDialog initial={adding} upcoming={cal.data?.upcoming ?? []} onClose={() => setAdding(null)} onSaved={() => { setAdding(null); reload(); }}/> : null}
      {addingEvent ? <EventDialog onClose={() => setAddingEvent(false)} onSaved={() => { setAddingEvent(false); cal.reload(); }}/> : null}
      {planning ? (<ConfirmDialog title="Plan upcoming events" confirmLabel="Add to the schedule" onClose={() => setPlanning(false)} onConfirm={plan}>
          For every event in the next 90 days that has no plan yet, Flowmerce adds two tasks: topic research about three weeks before its publish-by date, then a draft three days later.
          It puts at most one Claude task on any day, so the work stays inside the daily limit ({usd(cal.data?.budget?.dailyLimitUsd)} a day). Topics still need your approval before they are drafted, and nothing is published without a reviewer.
        </ConfirmDialog>) : null}
    </div>);
}

/** The schedule of the view as a table ("List"): every research, draft and publish task, with Cancel, Plan again and Delete. */
function ScheduleTable({ rows, brands, canRun, resetKey, onStatus, onRemove }) {
    if (!rows.length)
        return <div className="daypanel-empty">Nothing is scheduled in these days. Use “Blog on a day” or “Schedule a task”.</div>;
    return (<div className="callist"><Paged rows={rows} resetKey={resetKey} size={12}>{(pageRows) => (<table className="table">
        <thead><tr><th>Day</th><th>Brand</th><th>Task</th><th>For</th><th>Status</th><th/></tr></thead>
        <tbody>{pageRows.map((s) => (<tr key={s.id}>
            <td className="nowrap">{fmtDate(s.run_on)}</td>
            <td><BrandTag id={s.brand_id} brands={brands}/></td>
            <td className="nowrap"><Icon name={ACTION[s.action][1]} size="sm"/> {ACTION[s.action][0]}</td>
            <td className="small">{s.event_name || s.focus || ''}{s.topic_title ? <div className="muted">Topic: {s.topic_title}</div> : null}
              {s.article_id ? <div><Link href={`/articles/${s.article_id}`}>{s.article_title}</Link></div> : null}</td>
            <td><Pill tone={TONE[s.status]}>{s.status === 'skipped' ? 'cancelled' : s.status}</Pill>{s.message ? <div className="small muted">{s.message}</div> : null}</td>
            <td className="r nowrap">{canRun && s.status === 'planned' ? <Button size="xs" variant="ghost" icon="x" onClick={() => onStatus(s, 'skipped')} title="Flowmerce will not run it (you can plan it again)">Cancel</Button> : null}
              {canRun && s.status === 'skipped' ? <Button size="xs" variant="ghost" onClick={() => onStatus(s, 'planned')}>Plan again</Button> : null}
              {canRun && s.status !== 'done' ? <Button size="xs" variant="ghost" icon="x" iconOnly aria-label="Delete" onClick={() => onRemove(s)}/> : null}</td>
          </tr>))}</tbody>
      </table>)}</Paged></div>);
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
        return it.slot.article_id ? `a:${it.slot.article_id}` : it.slot.topic_id ? `t:${it.slot.topic_id}` : null;
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
 * The panel beside the calendar, as tall as the calendar and scrolling inside itself. Three tabs: the selected day (what
 * Flowmerce does then, with Cancel / Stop on each blog and task, and "Add a blog or task" for that day), the events
 * coming up (with Ask Claude and "Blog for this"), and the daily Claude limit.
 */
function DaySide({ day, today, items, all, upcoming, canRun, brands, budget, brand, onAdd, onBudgetSaved, canEditBudget, onSkip, onRemove, onCancelSlot }) {
    const [tab, setTab] = useState('day');
    const order = ['event', 'deadline', 'auto', 'research', 'draft', 'publish', 'live'];
    const sorted = [...items].sort((a, b) => order.indexOf(laneOf(a)) - order.indexOf(laneOf(b)));
    const title = new Date(`${day}T12:00:00`).toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long' });
    return (<aside className="dayside" aria-label="Day, events and Claude limit">
      <div className="seg sm dayside-tabs" role="tablist">
        {[['day', 'This day'], ['events', `Coming up${upcoming.length ? ` · ${upcoming.length}` : ''}`], ['limit', 'Claude limit']].map(([k, l]) =>
            <button key={k} role="tab" aria-selected={tab === k} aria-pressed={tab === k} onClick={() => setTab(k)}>{l}</button>)}
      </div>
      {tab === 'day' ? (<>
          <h3 className="dayside-title">{title}</h3>
          {canRun && day > today ? <Button size="sm" variant="primary" icon="plus" className="mt-8" onClick={() => onAdd({ action: 'blog', run_on: day })}>Add a blog or task</Button>
              : canRun && day === today ? <Button size="sm" icon="plus" className="mt-8" onClick={() => onAdd({ action: 'research', run_on: day })}>Add a task for today</Button> : null}
          {sorted.length ? (<div className="dtimeline mt-12">
              {sorted.map((it, i) => (<div key={`${day}-${i}`} className={`dtl-item ${LANE[laneOf(it)].cls}`} style={{ animationDelay: `${i * 60}ms` }}>
                <span className="dtl-time">{timeOf(it)}</span>
                <DayDetail it={it} brands={brands} canRun={canRun} onSkip={onSkip} onRemove={onRemove} onCancelSlot={onCancelSlot} all={all}/>
              </div>))}
            </div>) : <div className="daypanel-empty mt-8">{day > today ? 'Nothing planned. Add a blog for this day.' : day === today ? 'Nothing planned today.' : 'Nothing happened on this day.'}</div>}
        </>) : null}
      {tab === 'events' ? <ComingUp upcoming={upcoming} today={today} brand={brand} canRun={canRun} onAdd={onAdd}/> : null}
      {tab === 'limit' ? <div className="mt-12"><BudgetForm budget={budget} onSaved={onBudgetSaved} canEdit={canEditBudget}/></div> : null}
    </aside>);
}

/** Events coming up, soonest first: Ask Claude for topics now, or put a blog for the event on its publish-by day. */
function ComingUp({ upcoming, today, brand, canRun, onAdd }) {
    const toast = useToast();
    const [busy, setBusy] = useState('');
    const research = async (ev) => {
        if (!brand)
            return toast.error(new Error('Pick one brand at the top of the page first.'));
        setBusy(ev.key);
        try {
            await api.post('/ai/jobs', { brand, task_type: 'topic_research', input: { focus: `Upcoming: ${ev.name} (${ev.date}); publish by ${ev.publish_by}. ${ev.note || ''}`.trim() } });
            toast.ok(`Claude is researching topics for ${ev.name}. They appear in the Blog pipeline under Topics.`);
        }
        catch (e) {
            toast.error(e);
        }
        finally {
            setBusy('');
        }
    };
    if (!upcoming.length)
        return <div className="daypanel-empty mt-12">Nothing coming up. Add your own events, such as a sale or a collection launch.</div>;
    return (<div className="col mt-8" style={{ gap: 0 }}>
      {upcoming.map((e) => {
          const late = e.publish_by < today;
          const blogDay = e.publish_by > today ? e.publish_by : addDays(today, 1);
          return (<div key={e.key} className="dayside-event">
            <div className="row-wrap" style={{ gap: 6 }}><span className="strong">{e.name}</span><span className="small muted">{fmtDate(e.date)}</span>{e.builtin ? null : <Pill tone="info">Your event</Pill>}</div>
            <div className="small" style={{ color: late ? 'var(--warn)' : undefined }}>Publish by {fmtDate(e.publish_by)}{late ? ' (passed: a late article can still help)' : ''}</div>
            {e.note ? <div className="small muted">{e.note}</div> : null}
            {canRun ? (<div className="row-wrap mt-4" style={{ gap: 6 }}>
                <Button size="xs" variant="primary" icon="plus" onClick={() => onAdd({ action: 'blog', run_on: blogDay, event_key: e.key })} title="Put a blog for this event on its publish-by day">Blog for this</Button>
                <Button size="xs" icon="sparkle" loading={busy === e.key} disabled={!brand} onClick={() => research(e)} title={brand ? 'Claude suggests topics now (uses the daily Claude limit)' : 'Pick one brand first'}>Ask Claude for topics</Button>
              </div>) : null}
          </div>);
      })}
    </div>);
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

function DayDetail({ it, brands, canRun, onSkip, onRemove, onCancelSlot, all = [] }) {
    const lane = LANE[laneOf(it)];
    const b = brandOf(it);
    let state = null;
    let more = null;
    let actions = null;
    if (it.kind === 'entry') {
        const s = it.s;
        state = <Pill tone={TONE[s.status]}>{s.status === 'skipped' ? 'cancelled' : s.status}</Pill>;
        more = (<>{s.topic_title ? <div>Topic: {s.topic_title}</div> : null}{s.message ? <div>{s.message}</div> : null}</>);
        actions = canRun && s.status === 'planned' ? (<><Button size="xs" variant="secondary" icon="x" onClick={() => onSkip(s)}
            title={s.action === 'publish' ? 'Do not make this publish request' : 'Claude will not do this task (you can plan it again)'}>Cancel</Button>
          <Button size="xs" variant="ghost" onClick={() => onRemove(s)}>Delete</Button></>) : null;
        if (canRun && s.status === 'skipped')
            actions = <Button size="xs" variant="ghost" onClick={() => onSkip({ ...s, replan: true })}>Plan again</Button>;
        if (s.article_id)
            actions = <>{actions}<Link className="btn ghost xs" href={`/articles/${s.article_id}`}>Open article</Link></>;
    }
    else if (it.kind === 'auto') {
        const s = it.slot;
        state = <Pill tone={s.status === 'ready' ? 'ok' : s.status === 'writing' ? 'info' : ['failed', 'missed'].includes(s.status) ? 'warn' : 'neutral'}>{AUTO_STATUS[s.status] ?? s.status}</Pill>;
        const writeOn = addDays(s.publish_on, -5);
        more = (<>{s.message ? <div>{s.message}</div> : null}
          {s.status === 'planned' ? <div>{s.scheduled_topic ? 'Your topic. ' : 'Claude picks the topic. '}Claude writes it {writeOn > iso(new Date()) ? `on ${fmtDate(writeOn, { day: 'numeric', month: 'short' })}` : 'soon'}; it goes live at 10:00 once you authorize it.</div> : null}
          {s.checks?.score !== null && s.checks?.score !== undefined ? <div>Quality check: {s.checks.score}/100</div> : null}</>);
        const cancel = canRun && ['planned', 'writing'].includes(s.status)
            ? <Button size="xs" variant="secondary" icon="x" onClick={() => onCancelSlot(s)} title={s.status === 'writing' ? 'Stop Claude writing this blog; no blog for this day' : 'Claude will not write a blog for this day'}>
                {s.status === 'writing' ? 'Stop writing' : 'Cancel this blog'}</Button> : null;
        actions = <>{cancel}{s.article_id ? <Link className="btn ghost xs" href={`/articles/${s.article_id}`}>Open article</Link> : null}</>;
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
