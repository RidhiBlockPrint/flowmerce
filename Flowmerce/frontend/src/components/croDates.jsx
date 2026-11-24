'use client';
/* The CRO page's date picker and comparison picker, laid out like Shopify Analytics' own (owner request 2026-11-24):
 * a button with the range's name opens a panel with the presets on the left as a tree (Today, Yesterday; Last and
 * Period to date; Black Friday Cyber Monday and Quarters, each parent opening its children; Custom range) and, on the
 * right, the start and end dates and a two-month calendar; nothing changes until Apply. "Compare to" offers Shopify's
 * choices only. Dates are store-local days (YYYY-MM-DD). */
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { Icon } from './Icon';
import { Button } from './ui';
import { RANGE_COMPARES, TO_DATE, bfcm, compareRange, fmtSpan, presetRange, rangeDays, rangeLabel, shiftDay } from '../lib/cro';

const MONTH_NAMES = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
const DOW = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const MAX_DAYS = 366;
const firstOf = (iso) => `${iso.slice(0, 7)}-01`;
const nextMonth = (first, k) => new Date(Date.UTC(Number(first.slice(0, 4)), Number(first.slice(5, 7)) - 1 + k, 1)).toISOString().slice(0, 10);
const longDate = (iso) => (iso ? `${MONTH_NAMES[Number(iso.slice(5, 7)) - 1]} ${Number(iso.slice(8))}, ${iso.slice(0, 4)}` : '');

/** "November 23, 2026", "Nov 23 2026", "2026-11-23" or "11/23/2026" as YYYY-MM-DD; null when it is not a date. */
function parseTyped(text) {
    const s = String(text || '').trim();
    if (/^\d{4}-\d{2}-\d{2}$/.test(s)) return s;
    const t = Date.parse(s.replace(/(\d)(st|nd|rd|th)\b/, '$1'));
    if (Number.isNaN(t)) return null;
    const d = new Date(t);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

/** Keeps an open panel inside the window: when it would run past the right edge, it moves left (never past 16 px). */
function useFit(panel, open) {
    useLayoutEffect(() => {
        const el = panel.current;
        if (!open || !el) return;
        el.style.left = '0px';
        const r = el.getBoundingClientRect();
        const over = r.right - (window.innerWidth - 16);
        if (over > 0) el.style.left = `${-Math.min(over, r.left - 16)}px`;
    }, [panel, open]);
}

/** Closes a popover on Escape and on a click outside it. */
function useOutside(ref, open, close) {
    useEffect(() => {
        if (!open) return undefined;
        const onDown = (e) => { if (ref.current && !ref.current.contains(e.target)) close(); };
        const onKey = (e) => { if (e.key === 'Escape') close(); };
        document.addEventListener('mousedown', onDown);
        document.addEventListener('keydown', onKey);
        return () => { document.removeEventListener('mousedown', onDown); document.removeEventListener('keydown', onKey); };
    }, [ref, open, close]);
}

/** Two months side by side; clicking picks the start, then the end (a click before the start starts again). Days after
 * `max` cannot be picked. `single` picks one day only (a custom comparison's first day). */
function TwoMonths({ from, to, max, onPick, single, mark }) {
    const [left, setLeft] = useState(firstOf(shiftDay(firstOf(to || max), -1)));
    useEffect(() => { if (to) setLeft(firstOf(shiftDay(firstOf(to), -1))); }, [to]);   // keep the chosen end in view
    const month = (first) => {
        const lead = new Date(`${first}T00:00:00Z`).getUTCDay();
        const days = new Date(Date.UTC(Number(first.slice(0, 4)), Number(first.slice(5, 7)), 0)).getUTCDate();
        const cells = [...Array(lead).fill(null), ...Array.from({ length: days }, (_, i) => shiftDay(first, i))];
        return (<div className="dp-month">
          <div className="dp-mname">{MONTH_NAMES[Number(first.slice(5, 7)) - 1]} {first.slice(0, 4)}</div>
          <div className="dp-grid">
            {DOW.map((d) => <span key={d} className="dp-dow">{d}</span>)}
            {cells.map((iso, i) => {
                if (!iso) return <span key={`e${i}`}/>;
                const off = iso > max;
                const inRange = from && to && iso >= from && iso <= to;
                const edge = iso === from || iso === to;
                const marked = mark && iso >= mark.from && iso <= mark.to;
                return (<button key={iso} type="button" disabled={off} onClick={() => onPick(iso)}
                  className={`dp-day${inRange ? ' in' : ''}${edge ? ' edge' : ''}${iso === max ? ' today' : ''}${marked ? ' mark' : ''}`}
                  aria-pressed={edge} aria-label={longDate(iso)}>{Number(iso.slice(8))}</button>);
            })}
          </div>
        </div>);
    };
    return (<div className="dp-cal">
      <button type="button" className="dp-nav prev" aria-label="Previous month" onClick={() => setLeft(nextMonth(left, -1))}><Icon name="chevronLeft" size="sm"/></button>
      {month(left)}
      <span className="dp-sep" aria-hidden="true"/>
      {month(nextMonth(left, 1))}
      <button type="button" className="dp-nav next" aria-label="Next month" disabled={nextMonth(left, 1) >= firstOf(max)} onClick={() => setLeft(nextMonth(left, 1))}><Icon name="chevronRight" size="sm"/></button>
      {single ? <span className="sr-only">Pick the first day</span> : null}
    </div>);
}

/** A date box that shows "November 23, 2026" and accepts a typed date on Enter or when left. */
function DateBox({ value, onChange, label }) {
    const [text, setText] = useState(longDate(value));
    useEffect(() => { setText(longDate(value)); }, [value]);
    const commit = () => { const d = parseTyped(text); if (d) onChange(d); else setText(longDate(value)); };
    return <input className="input dp-box" value={text} aria-label={label} onChange={(e) => setText(e.target.value)} onBlur={commit} onKeyDown={(e) => { if (e.key === 'Enter') commit(); }}/>;
}

/** The left-hand list as a tree, like Shopify's: a parent (with a chevron) opens its children underneath, one parent
 * at a time; a parent whose child is chosen shows it in bold. */
function Menu({ items, active, open, onItem }) {
    return (<div className="dp-menu" role="tree" aria-label="Ranges">
      {items.map((it) => {
          if (it.divider) return <hr key={it.key}/>;
          const expanded = !!it.children && open === it.key;
          const holds = it.children?.some((c) => c.key === active);
          return (<div key={it.key} className="dp-node">
            <button type="button" role="treeitem" aria-expanded={it.children ? expanded : undefined} aria-selected={active === it.key}
              className={`dp-item${active === it.key || holds ? ' on' : ''}${it.children ? ' parent' : ''}${expanded ? ' open' : ''}`} onClick={() => onItem(it)}>
              <span>{it.label}</span>{it.children ? <Icon name="chevronRight" size="sm" className="dp-chev"/> : null}</button>
            {expanded ? (<div className="dp-kids" role="group">{it.children.map((c) => (
              <button key={c.key} type="button" role="treeitem" aria-selected={active === c.key} disabled={c.disabled}
                className={`dp-item kid${active === c.key ? ' on' : ''}`} onClick={() => onItem(c)}>{c.label}</button>))}</div>) : null}
          </div>);
      })}
    </div>);
}

/** The children of "Last", as in Shopify. */
const LAST_CHOICES = [
    { key: 'last-7-days', label: 'Last 7 days' }, { key: 'last-30-days', label: 'Last 30 days' }, { key: 'last-90-days', label: 'Last 90 days' },
    { key: 'last-365-days', label: 'Last 365 days' }, { key: 'last-1-weeks', label: 'Last week' }, { key: 'last-1-months', label: 'Last month' },
    { key: 'last-1-quarters', label: 'Last quarter' }, { key: 'last-1-years', label: 'Last year' },
];

/**
 * The date range button and its panel. `value` is { r, from, to } (r: a range key or 'custom'); `today` the store's
 * today. Apply calls onChange({ r, from, to }).
 */
export function DateRangePicker({ value, today, onChange }) {
    const ref = useRef(null);
    const panel = useRef(null);
    const [open, setOpen] = useState(false);
    const [draft, setDraft] = useState(value);
    const [group, setGroup] = useState(null);
    const [picking, setPicking] = useState(false);   // the first click of a custom range is in, the second is awaited
    const close = () => setOpen(false);
    useOutside(ref, open, close);
    useFit(panel, open);
    const pick = (r) => setDraft({ r, ...presetRange(r, today) });
    const year = Number(today.slice(0, 4));
    const quarterNow = Math.floor((Number(today.slice(5, 7)) - 1) / 3) + 1;
    const quarters = Array.from({ length: 5 }, (_, i) => {
        const q = ((quarterNow - 1 - i) % 4 + 4) % 4 + 1;
        const y = year - Math.floor((4 - quarterNow + i) / 4);
        return { key: `q-${y}-${q}`, label: `Q${q} ${y}` };
    });
    // Parents with their children, as in Shopify's date picker; a child is a range, a parent only opens its children.
    const items = [
        { key: 'today', label: 'Today' }, { key: 'yesterday', label: 'Yesterday' }, { key: 'd1', divider: true },
        { key: 'last', label: 'Last', children: LAST_CHOICES }, { key: 'ptd', label: 'Period to date', children: TO_DATE }, { key: 'd2', divider: true },
        { key: 'bfcm', label: 'Black Friday Cyber Monday', children: [year, year - 1, year - 2].map((y) => ({ key: `bfcm-${y}`, label: String(y), disabled: bfcm(y).from > today })) },
        { key: 'quarters', label: 'Quarters', children: quarters },
        { key: 'd3', divider: true }, { key: 'custom', label: 'Custom range' },
    ];
    const parentOf = (key) => items.find((it) => it.children?.some((c) => c.key === key))?.key ?? null;
    const start = () => { setDraft(value); setGroup(parentOf(value.r)); setPicking(false); setOpen(true); };
    const onItem = (it) => {
        if (it.children) { setGroup(group === it.key ? null : it.key); return; }
        if (it.key === 'custom') { setDraft({ ...draft, r: 'custom' }); setGroup(null); return; }
        if (!parentOf(it.key)) setGroup(null);
        pick(it.key);
    };
    const onDay = (iso) => {
        if (!picking || iso < draft.from) { setDraft({ r: 'custom', from: iso, to: iso }); setPicking(true); return; }
        setDraft({ r: 'custom', from: draft.from, to: iso });
        setPicking(false);
    };
    const n = rangeDays(draft.from, draft.to);
    const bad = draft.from > draft.to ? 'The start is after the end.' : draft.from > today ? 'The range starts in the future.' : n > MAX_DAYS ? `Pick at most ${MAX_DAYS} days.` : '';
    const apply = () => { onChange({ r: draft.r, from: draft.from, to: draft.to > today ? today : draft.to }); close(); };
    return (<div className="dp" ref={ref}>
      <button type="button" className="btn sm dp-btn" aria-haspopup="dialog" aria-expanded={open} onClick={() => (open ? close() : start())}>
        <Icon name="calendar" size="sm"/>{rangeLabel(value.r, value.from, value.to)}</button>
      {open ? (<div className="dp-panel" ref={panel} role="dialog" aria-label="Pick dates">
        <Menu items={items} active={draft.r} open={group} onItem={onItem}/>
        <div className="dp-main">
          <div className="dp-boxes">
            <DateBox value={draft.from} label="Start date" onChange={(d) => setDraft({ r: 'custom', from: d, to: d > draft.to ? d : draft.to })}/>
            <Icon name="arrowRight" size="sm"/>
            <DateBox value={draft.to} label="End date" onChange={(d) => setDraft({ r: 'custom', from: d < draft.from ? d : draft.from, to: d })}/>
          </div>
          <TwoMonths from={draft.from} to={draft.to} max={today} onPick={onDay}/>
          <div className="dp-foot">
            <span className={bad ? 'dp-err' : 'muted small'}>{bad || `${n} day${n === 1 ? '' : 's'}${draft.to >= today ? ' · today is still running' : ''}`}</span>
            <div className="row" style={{ gap: 8 }}><Button size="sm" variant="ghost" onClick={close}>Cancel</Button><Button size="sm" variant="primary" disabled={!!bad} onClick={apply}>Apply</Button></div>
          </div>
        </div>
      </div>) : null}
    </div>);
}

/**
 * "Compare to" button and its panel, with Shopify's choices: previous period, previous year (same dates or same
 * weekdays), a custom period of the same length, or none. `range` is the chosen { from, to }; `value` { cmp, cfrom }.
 * Apply calls onChange({ cmp, cfrom }).
 */
export function ComparePicker({ range, value, today, onChange }) {
    const ref = useRef(null);
    const panel = useRef(null);
    const [open, setOpen] = useState(false);
    const [draft, setDraft] = useState(value);
    const close = () => setOpen(false);
    useOutside(ref, open, close);
    useFit(panel, open);
    const n = rangeDays(range.from, range.to);
    const options = RANGE_COMPARES.filter((c) => !c.hidden);
    const label = RANGE_COMPARES.find((c) => c.key === value.cmp)?.label ?? 'Previous period';
    const shown = compareRange(draft.cmp, range.from, range.to, draft.cfrom);
    const lastStart = shiftDay(range.from, -1);
    const bad = draft.cmp === 'custom' && !(draft.cfrom && draft.cfrom < range.from) ? 'Pick a first day before the chosen dates.' : '';
    const apply = () => { onChange({ cmp: draft.cmp, cfrom: draft.cmp === 'custom' ? draft.cfrom : null }); close(); };
    return (<div className="dp" ref={ref}>
      <button type="button" className="btn sm dp-btn" aria-haspopup="dialog" aria-expanded={open}
        onClick={() => { if (open) close(); else { setDraft({ cmp: value.cmp, cfrom: value.cfrom ?? shiftDay(range.from, -n) }); setOpen(true); } }}>
        <span className="muted">Compare to:</span> {label}</button>
      {open ? (<div className="dp-panel" ref={panel} role="dialog" aria-label="Compare to">
        <div className="dp-menu" role="listbox" aria-label="Comparisons">
          {options.map((c) => <button key={c.key} type="button" role="option" aria-selected={draft.cmp === c.key}
            className={`dp-item${draft.cmp === c.key ? ' on' : ''}`} onClick={() => setDraft({ ...draft, cmp: c.key })}>{c.label}</button>)}
        </div>
        <div className="dp-main">
          {draft.cmp === 'custom' ? (<>
            <div className="dp-boxes">
              <DateBox value={draft.cfrom} label="Comparison start" onChange={(d) => setDraft({ ...draft, cfrom: d })}/>
              <Icon name="arrowRight" size="sm"/>
              <input className="input dp-box" readOnly value={longDate(shiftDay(draft.cfrom, n - 1))} aria-label="Comparison end (same length)"/>
            </div>
            <TwoMonths from={draft.cfrom} to={shiftDay(draft.cfrom, n - 1)} max={lastStart} single onPick={(d) => setDraft({ ...draft, cfrom: d })} mark={range}/>
            <div className="muted xs">Pick the first day; the comparison has the same {n} day{n === 1 ? '' : 's'} as the chosen dates.</div>
          </>) : (<div className="dp-summary">
            <div><span className="muted small">Chosen dates</span><b>{fmtSpan(range.from, range.to)}</b></div>
            <div><span className="muted small">Compared with</span>
              <b>{draft.cmp === 'none' ? 'Nothing' : draft.cmp === '4week_avg' ? `The same weekday in the 4 weeks before (${fmtSpan(shiftDay(range.from, -28), shiftDay(range.from, -7))})` : fmtSpan(shown.from, shown.to)}</b></div>
          </div>)}
          <div className="dp-foot">
            <span className={bad ? 'dp-err' : 'muted small'}>{bad}</span>
            <div className="row" style={{ gap: 8 }}><Button size="sm" variant="ghost" onClick={close}>Cancel</Button><Button size="sm" variant="primary" disabled={!!bad} onClick={apply}>Apply</Button></div>
          </div>
        </div>
      </div>) : null}
    </div>);
}
