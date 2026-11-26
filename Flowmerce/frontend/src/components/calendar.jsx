'use client';
/*
 * Shared calendar pieces for the Content calendar (views/Calendar.jsx) and the SEO & Blog overview's calendar
 * (views/BlogHome.jsx). Owner request 2026-11-24: a full calendar you can move through to any month and year, see that
 * month's events and blogs, and schedule there; the overview's calendar works the same way.
 *
 *   MonthNav        earlier / later arrows, the month name as a button that opens a month-and-year picker, and Today
 *   useWheelMonths  scrolling the mouse wheel (or a trackpad) over the calendar moves a month at a time; PageUp and
 *                   PageDown do the same while the calendar has focus
 *   ScheduleDialog  "Add to the calendar": a blog for a day (POST /blog/slots) or a single task (POST /calendar/schedule)
 */
import { useEffect, useRef, useState } from 'react';
import { api, qs, useApi } from '../lib/api';
import { useApp } from '../lib/app';
import { fmtDate } from '../lib/format';
import { Button, Field } from './ui';
import { Dialog, useToast } from './overlays';
import { Icon } from './Icon';

export const ACTION = { blog: ['Blog on this day', 'sparkle'], research: ['Research topics', 'search'], draft: ['Write draft', 'edit'], publish: ['Publish request', 'publish'] };
export const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
export const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
export const addDays = (s, n) => { const d = new Date(`${s}T12:00:00`); d.setDate(d.getDate() + n); return iso(d); };
/** `YYYY-MM` moved by n months. */
export const addMonths = (month, n) => { const d = new Date(`${month}-01T12:00:00`); d.setMonth(d.getMonth() + n); return iso(d).slice(0, 7); };
/** The Monday on or before a day. */
export const mondayOf = (s) => addDays(s, -((new Date(`${s}T12:00:00`).getDay() + 6) % 7));
/** The 42 days (six weeks from a Monday) that show a month. */
export const monthDays = (month) => { const start = mondayOf(`${month}-01`); return Array.from({ length: 42 }, (_, i) => addDays(start, i)); };
export const monthTitle = (month) => new Date(`${month}-01T12:00:00`).toLocaleDateString('en-GB', { month: 'long', year: 'numeric' });

/** Arrows, the month as a button opening a month-and-year picker, and Today. `month` is `YYYY-MM`. */
export function MonthNav({ month, today, onChange, onToday, label, size = 'sm' }) {
    return (<div className="monthnav row" style={{ gap: 4 }}>
      <Button size={size} variant="ghost" icon="chevronLeft" iconOnly aria-label="Previous month" title="Previous month (PageUp, or scroll up over the calendar)" onClick={() => onChange(addMonths(month, -1))}/>
      <MonthPicker month={month} today={today} onPick={onChange} label={label}/>
      <Button size={size} variant="ghost" icon="chevronRight" iconOnly aria-label="Next month" title="Next month (PageDown, or scroll down over the calendar)" onClick={() => onChange(addMonths(month, 1))}/>
      <Button size={size} variant="ghost" onClick={onToday ?? (() => onChange(today.slice(0, 7)))}>Today</Button>
    </div>);
}

/** The month name as a button; it opens a year (with arrows) and its twelve months, to jump to any month of any year. */
export function MonthPicker({ month, today, onPick, label }) {
    const [open, setOpen] = useState(false);
    const [year, setYear] = useState(Number(month.slice(0, 4)));
    const box = useRef(null);
    useEffect(() => { if (open) setYear(Number(month.slice(0, 4))); }, [open, month]);
    useEffect(() => {
        if (!open)
            return undefined;
        const off = (e) => { if (box.current && !box.current.contains(e.target)) setOpen(false); };
        const esc = (e) => { if (e.key === 'Escape') setOpen(false); };
        document.addEventListener('mousedown', off);
        document.addEventListener('keydown', esc);
        return () => { document.removeEventListener('mousedown', off); document.removeEventListener('keydown', esc); };
    }, [open]);
    const pick = (m) => { onPick(`${year}-${String(m + 1).padStart(2, '0')}`); setOpen(false); };
    return (<div className="monthpicker" ref={box}>
      <button type="button" className="monthpicker-btn" aria-haspopup="dialog" aria-expanded={open} onClick={() => setOpen((o) => !o)} title="Pick a month and year">
        {label ?? monthTitle(month)}<Icon name="chevronDown" size="sm"/>
      </button>
      {open ? (<div className="monthpicker-pop" role="dialog" aria-label="Pick a month and year">
          <div className="monthpicker-year">
            <Button size="sm" variant="ghost" icon="chevronLeft" iconOnly aria-label="Previous year" onClick={() => setYear((y) => y - 1)}/>
            <b>{year}</b>
            <Button size="sm" variant="ghost" icon="chevronRight" iconOnly aria-label="Next year" onClick={() => setYear((y) => y + 1)}/>
          </div>
          <div className="monthpicker-grid">
            {MONTHS.map((m, i) => {
                const key = `${year}-${String(i + 1).padStart(2, '0')}`;
                return (<button type="button" key={m} onClick={() => pick(i)} aria-pressed={key === month}
                  className={`${key === month ? 'on' : ''}${key === today.slice(0, 7) ? ' now' : ''}`}>{m}</button>);
            })}
          </div>
          <Button size="sm" variant="ghost" className="monthpicker-today" onClick={() => { onPick(today.slice(0, 7)); setOpen(false); }}>This month</Button>
        </div>) : null}
    </div>);
}

/**
 * Scrolling over the element moves `onShift(+1 / -1)`: one step per firm scroll (a trackpad's many small events add up),
 * with a short pause so one flick does not race through a year. PageUp / PageDown do the same while focus is inside it.
 * The page itself does not scroll while the wheel is over the calendar.
 */
export function useWheelMonths(ref, onShift, enabled = true) {
    const shift = useRef(onShift);
    shift.current = onShift;
    useEffect(() => {
        const el = ref.current;
        if (!el || !enabled)
            return undefined;
        let acc = 0;
        let last = 0;
        const wheel = (e) => {
            if (e.ctrlKey || Math.abs(e.deltaX) > Math.abs(e.deltaY))
                return;   // pinch-zoom and sideways scrolling are left alone
            e.preventDefault();
            const now = Date.now();
            if (now - last < 420) {
                acc = 0;
                return;
            }
            acc += e.deltaY;
            if (Math.abs(acc) >= 60) {
                shift.current(acc > 0 ? 1 : -1);
                acc = 0;
                last = now;
            }
        };
        const key = (e) => {
            if (e.key === 'PageDown' || e.key === 'PageUp') {
                e.preventDefault();
                shift.current(e.key === 'PageDown' ? 1 : -1);
            }
        };
        el.addEventListener('wheel', wheel, { passive: false });
        el.addEventListener('keydown', key);
        return () => { el.removeEventListener('wheel', wheel); el.removeEventListener('keydown', key); };
    }, [ref, enabled]);
}

export function ScheduleDialog({ initial, upcoming, onClose, onSaved }) {
    return (<Dialog wide title="Add to the calendar" sub="A blog for a day (Flowmerce writes, checks and schedules it), or a single research, draft or publish task." onClose={onClose}>
      <ScheduleForm initial={initial} upcoming={upcoming} onSaved={onSaved} onCancel={onClose}/>
    </Dialog>);
}

/**
 * The form for the calendar: "Blog on this day" (a topic and its go-live day; POST /blog/slots) or a single task
 * (research, draft or publish request; POST /calendar/schedule).
 */
export function ScheduleForm({ initial, upcoming, onSaved, onCancel }) {
    const { me, brand: current } = useApp();
    const toast = useToast();
    const ev = upcoming.find((e) => e.key === initial.event_key);
    const [f, setF] = useState({ brand: current === 'all' ? 'ridhi' : current, action: initial.action ?? 'blog', run_on: initial.run_on, event_key: initial.event_key ?? '', focus: '', topic_id: '', article_id: '',
        source: 'new', title: '', keyword: '' });
    const [busy, setBusy] = useState(false);
    const [err, setErr] = useState('');
    const topics = useApi(f.action === 'draft' || (f.action === 'blog' && f.source === 'existing') ? `/topics${qs({ brand: f.brand })}` : null);
    const arts = useApi(f.action === 'publish' ? `/articles${qs({ brand: f.brand, limit: 200 })}` : null);
    const set = (k, v) => setF({ ...f, [k]: v });
    const todayIso = iso(new Date());
    const tomorrow = addDays(todayIso, 1);
    const writeOn = f.run_on && addDays(f.run_on, -5) > todayIso ? addDays(f.run_on, -5) : null;
    const save = async () => {
        setBusy(true);
        setErr('');
        try {
            if (f.action === 'blog') {
                const body = { brand: f.brand, publish_on: f.run_on, ...(f.source === 'existing' ? { topic_id: Number(f.topic_id) } : { title: f.title, keyword: f.keyword }) };
                const slot = await api.post('/blog/slots', body);
                toast.ok(`“${slot.topic_title}” is on the calendar for ${fmtDate(f.run_on, { weekday: 'short', day: 'numeric', month: 'short' })}. ${slot.status === 'writing' ? 'Claude has started writing it.' : 'Claude writes it 5 days before.'}`);
            }
            else
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
    const ok = f.run_on && (f.action === 'blog' ? f.run_on >= tomorrow && (f.source === 'existing' ? f.topic_id : f.title.trim().length >= 5)
        : f.action === 'research' ? f.event_key || f.focus.trim() : f.action === 'draft' ? f.topic_id || f.event_key : f.article_id);
    const openTopics = (topics.data ?? []).filter((t) => !t.article_id && ['proposed', 'validated', 'approved'].includes(t.status));
    return (<div className="schedform">
      <div className="form-grid">
        <div className="field full"><label>Brand</label>
          <div className="seg">{me.brands.map((b) => <button key={b.id} aria-pressed={f.brand === b.id} onClick={() => setF({ ...f, brand: b.id, topic_id: '', article_id: '' })}><span className={`brand-dot ${b.id}`}/>{b.name}</button>)}</div>
        </div>
        <div className="field full"><label>What</label>
          <div className="seg">{Object.entries(ACTION).map(([k, [label, icon]]) => <button key={k} aria-pressed={f.action === k} onClick={() => set('action', k)}><Icon name={icon} size="sm"/>{label}</button>)}</div>
        </div>
        {f.action === 'blog' ? (<>
            <Field label="Goes live on" hint="At 10:00 that day."><input className="input" type="date" min={tomorrow} value={f.run_on} onChange={(e) => set('run_on', e.target.value)}/></Field>
            <div className="field"><label>Topic</label>
              <div className="seg">{[['new', 'New topic'], ['existing', 'Existing topic']].map(([k, l]) => <button key={k} aria-pressed={f.source === k} onClick={() => set('source', k)}>{l}</button>)}</div>
            </div>
            {f.source === 'new' ? (<>
                <Field label="Blog topic" full hint={ev ? `For ${ev.name}. Write it like a working title.` : 'Write it like a working title, e.g. “Christmas table runners: how to pick the right length”.'}>
                  <input className="input" data-autofocus value={f.title} onChange={(e) => set('title', e.target.value)} placeholder={ev ? `${ev.name}: ` : ''}/>
                </Field>
                <Field label="Main keyword (optional)" full hint="The search phrase it should rank for. Left empty, the topic itself is used."><input className="input" value={f.keyword} onChange={(e) => set('keyword', e.target.value)}/></Field>
              </>) : (<Field label="Topic" full hint="Topics without an article yet. Choosing one approves it.">
                <select className="select" value={f.topic_id} onChange={(e) => set('topic_id', e.target.value)}>
                  <option value="">Pick a topic</option>
                  {openTopics.map((t) => <option key={t.id} value={t.id}>{t.title}{t.status !== 'approved' ? ` (${t.status})` : ''}</option>)}
                </select>
              </Field>)}
            <div className="callout info full"><Icon name="info"/><div className="small">
              Claude writes it {writeOn ? <>on <b>{fmtDate(writeOn, { weekday: 'short', day: 'numeric', month: 'short' })}</b></> : <b>straight away</b>}; Flowmerce adds images, checks its quality, approves it and makes a publish request for 10:00 that day.
              It stays in Flowmerce until you or a reviewer click <b>Authorize</b> (Blog pipeline or Publishing); then it goes to Shopify hidden and shows at 10:00 on the day.
            </div></div>
          </>) : (<>
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
                  {(topics.data ?? []).filter((t) => !t.article_id && t.status === 'approved').map((t) => <option key={t.id} value={t.id}>{t.title}</option>)}
                </select>
              </Field>) : null}
            {f.action === 'publish' ? (<Field label="Article" full hint="It must be reviewer-approved before the publish request can be made.">
                <select className="select" value={f.article_id} onChange={(e) => set('article_id', e.target.value)}>
                  <option value="">Pick an article</option>
                  {(arts.data?.rows ?? []).filter((a) => !a.shopify_published).map((a) => <option key={a.id} value={a.id}>{a.title} ({a.status.replace('_', ' ')})</option>)}
                </select>
              </Field>) : null}
          </>)}
      </div>
      {err ? <div className="callout crit mt-12"><Icon name="alert"/>{err}</div> : null}
      <div className="row mt-12" style={{ gap: 8, justifyContent: 'flex-end' }}>
        {onCancel ? <Button variant="ghost" onClick={onCancel}>Cancel</Button> : null}
        <Button variant="primary" loading={busy} disabled={!ok} onClick={save}>{f.action === 'blog' ? 'Put on the calendar' : 'Add to schedule'}</Button>
      </div>
    </div>);
}
