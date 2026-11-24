'use client';
/* The Ads Overview (views/Ads.jsx), redesigned on the owner's request of 2026-11-24 for the directors and heads of
 * department: "show me what helps me plan today's work". In the CRO Overview's visual language (serif card titles,
 * big figures, coloured change chips, the 14-day strip, animated rings):
 *   1. Today's plan: the spend call in plain words (what the old "scaling gate" meant), a meter that shows why, and the
 *      top suggestions from the Actions tab.
 *   2. Four headline figures, each with its change and a 14-day sparkline; four smaller ones under them.
 *   3. The daily sales goal as an animated ring, editable in place.
 *   4. The last 14 days as day tiles coloured by MER, and the sales / spend / MER charts.
 * Every figure comes from /api/ads/...; definitions live in tooltips instead of lines under each number. */
import { useState } from 'react';
import { Sparkline } from './charts';
import { Icon } from './Icon';
import { CountUp, ProgressRing } from './motion';
import { Button, Pill } from './ui';
import { ACTION_GROUPS, GATE, usd, x2 } from '../lib/ads';
import { fmtDay } from '../lib/format';

const WEEKDAY = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const weekday = (iso) => WEEKDAY[new Date(`${iso}T00:00:00Z`).getUTCDay()];

/** A change against the comparison as a coloured chip: green when it moved the good way, red otherwise, grey for a
 *  figure that is neither good nor bad (spend). */
export function ChangeChip({ value, good = 'up' }) {
    if (value === null || value === undefined) return null;
    const flat = Math.abs(value) < 0.05;
    const tone = flat || good === 'none' ? 'flat' : (value > 0) === (good === 'up') ? 'good' : 'bad';
    return (<span className={`ads-chg ${tone}`}>
      {flat ? null : <Icon name={value > 0 ? 'arrowUp' : 'arrowDown'} size="sm"/>}
      {`${Math.abs(value).toFixed(Math.abs(value) < 10 ? 1 : 0)}%`}
    </span>);
}

/**
 * A headline figure: label (definition on hover), the value large, its change chip and the comparison value at a
 * readable size, and the last 14 days as a sparkline. `tone` colours the value against a target ('ok', 'warn', 'crit').
 */
export function KpiTile({ label, help, block, format, good = 'up', spark, sparkColor = 'var(--accent)', tone, compareLabel }) {
    const b = block || {};
    const missing = b.value === null || b.value === undefined;
    return (<section className="card ads-kpi" title={help}>
      <div className="ads-kpi-label">{label}{help ? <Icon name="info" size="sm"/> : null}</div>
      <div className={`ads-kpi-value${tone ? ` t-${tone}` : ''}`}>{missing ? '—' : <CountUp value={format(b.value)}/>}</div>
      <div className="ads-kpi-cmp">
        <ChangeChip value={b.change_pct} good={good}/>
        {b.baseline_value !== null && b.baseline_value !== undefined
            ? <span>{compareLabel ?? 'was'} <b>{format(b.baseline_value)}</b></span> : null}
      </div>
      {spark && spark.filter((v) => v !== null).length > 1 ? (<div className="ads-kpi-spark" aria-hidden="true">
        <Sparkline values={spark.map((v) => v ?? 0)} color={sparkColor} width={150} height={34}/>
        <span className="muted xs">14 days</span>
      </div>) : null}
    </section>);
}

/** Four smaller figures in one card, each with its change chip. `items`: { label, help, block, format, good }. */
export function MiniStats({ items }) {
    return (<section className="card ads-minis">
      {items.map((it) => (<div key={it.label} className="ads-mini" title={it.help}>
        <span className="ads-mini-label">{it.label}</span>
        <span className="ads-mini-value">{it.block?.value === null || it.block?.value === undefined ? '—' : it.format(it.block.value)}</span>
        <ChangeChip value={it.block?.change_pct} good={it.good}/>
      </div>))}
    </section>);
}

/* ------------------------------------------------------------------ Today's plan */
/** What the spend call means, in words a director reads in one go. */
function verdict(gate) {
    const now = gate.avg_daily_spend_7d;
    const next = gate.recommended_daily_spend;
    const pct = now ? Math.round(Math.abs(next / now - 1) * 100) : 0;
    if (gate.state === 'green') return { title: pct ? `Room to spend up to ${pct}% more` : 'Room to spend more', line: 'Ads are paying back well: raise the budget of the strongest campaigns over the next 3 days.' };
    if (gate.state === 'unknown') return { title: 'No spend call yet', line: 'Part of the ad spend of the last 7 days is not saved yet, so this cannot say whether to cut, hold or grow. Keep spend as it is until it is.' };
    if (gate.state === 'red') return { title: `Cut ad spend by about ${pct || 15}%`, line: 'Ads are not paying back enough: trim the weakest campaigns and ads first, then reassess in 3 days.' };
    return { title: 'Keep total spend steady', line: 'Ads pay back, but not enough to grow: move budget from weak campaigns to strong ones.' };
}

/**
 * The store's sales per $1 of ad spend (MER, bulk orders left out) on a scale with three zones: cut back, hold, grow.
 * The 3-day and 7-day figures are marked on it, so the spend call explains itself.
 */
export function MerMeter({ mer3, mer7, red, green, target }) {
    const top = Math.max(3.5, target + 0.5, (mer3 ?? 0) + 0.3, (mer7 ?? 0) + 0.3);
    const at = (v) => `${Math.max(0, Math.min(100, (v / top) * 100))}%`;
    const dot = (v, cls) => (v === null || v === undefined ? null : <span className={`ads-meter-dot ${cls}`} style={{ left: at(v) }}/>);
    return (<div className="ads-meter" role="img" aria-label={`Store sales per $1 of ads: last 3 days ${x2(mer3)}, last 7 days ${x2(mer7)}. Cut back below ${x2(red)}, grow from ${x2(green)}.`}>
      <div className="ads-meter-legend">
        <span><i className="ads-meter-key d3"/>Last 3 days <b>{x2(mer3)}</b></span>
        <span><i className="ads-meter-key d7"/>Last 7 days <b>{x2(mer7)}</b></span>
        <span><i className="ads-meter-key tg"/>Target <b>{x2(target)}</b></span>
      </div>
      <div className="ads-meter-bar">
        <div className="ads-meter-track">
          <span className="z z-red" style={{ width: at(red) }}/>
          <span className="z z-amber" style={{ left: at(red), width: `calc(${at(green)} - ${at(red)})` }}/>
          <span className="z z-green" style={{ left: at(green), right: 0 }}/>
        </div>
        <span className="ads-meter-target" style={{ left: at(target) }}/>
        {dot(mer7, 'd7')}{dot(mer3, 'd3')}
      </div>
      <div className="ads-meter-scale">
        <span style={{ left: 0 }}>Cut back <em>under {x2(red)}</em></span>
        <span style={{ left: at((red + green) / 2), transform: 'translateX(-50%)' }}>Hold</span>
        <span style={{ right: 0 }}>Grow <em>from {x2(green)}</em></span>
      </div>
    </div>);
}

/**
 * Today's plan: the spend call (verdict, why, today's budget against the suggested one, the meter) and the top
 * suggestions from the Actions tab. `actions` is the /ads/actions answer (or null while it loads).
 */
export function TodayPlan({ gate, lines, targets, actions, onAllActions, warning }) {
    const g = GATE[gate.state] ?? GATE.amber;
    const v = verdict(gate);
    const open = (actions?.actions ?? []).filter((a) => a.status === 'open');
    return (<div className="ov-halo">
      <section className={`card ads-plan s-${gate.state}`} aria-labelledby="ads-plan-title">
        <div className="ads-plan-call">
          <div className="ov-card-head"><h2 id="ads-plan-title" className="serif ov-serif">Today&rsquo;s plan</h2>
            <span className="muted xs">from the last 3 and 7 days</span></div>
          <div className="ads-verdict">
            <span className="ads-verdict-dot" style={{ background: g.color }} aria-hidden="true"/>
            <div>
              <div className="ads-verdict-title">{v.title}</div>
              <div className="ads-verdict-line">{v.line}</div>
            </div>
          </div>
          <div className="ads-budget" title="Total ad spend a day: the average of the last 7 days, and what the rule suggests for the next 3 days">
            <div><span className="muted small">Daily ad spend now</span><b>{usd(gate.avg_daily_spend_7d)}</b></div>
            {gate.state === 'unknown' ? null : (<>
              <Icon name="arrowRight"/>
              <div><span className="muted small">Suggested</span><b style={{ color: g.color }}>{usd(gate.recommended_daily_spend)}</b></div>
            </>)}
          </div>
          <div className="ads-why">
            <span className="muted small">Store sales for every $1 of ads</span>
            <MerMeter mer3={gate.mer_3d} mer7={gate.mer_7d} red={lines.red} green={lines.green} target={targets.mer}/>
          </div>
          {warning ? <div className="ads-plan-warn"><Icon name="alert" size="sm"/>{warning}</div> : null}
        </div>
        <div className="ads-plan-todo">
          <div className="row" style={{ justifyContent: 'space-between' }}><b>Do today</b>
            {actions ? <span className="muted xs">{open.length} open</span> : null}</div>
          {!actions ? <div className="muted small">Loading the suggestions…</div>
              : open.length ? (<ol className="ads-todo">
                {open.slice(0, 4).map((a) => (<li key={a.id}>
                  <Pill tone={ACTION_GROUPS[a.group]?.tone ?? 'neutral'}>{ACTION_GROUPS[a.group]?.label ?? a.group}</Pill>
                  <div className="ads-todo-text"><span className="ellipsis" title={a.title}>{a.title}</span>
                    <span className="muted xs ellipsis" title={a.evidence}>{a.proposed}</span></div>
                </li>))}
              </ol>) : <div className="muted small">Nothing to change: the rules suggest nothing right now.</div>}
          <Button size="sm" variant="ghost" onClick={onAllActions}>All suggestions <Icon name="arrowRight" size="sm"/></Button>
        </div>
      </section>
    </div>);
}

/* ------------------------------------------------------------------ the daily sales goal */
/**
 * Progress toward the daily store-sales goal as an animated ring, the average a day, and what the gap means in ad
 * spend. The goal is edited in place (pencil, type, Save). `onSave(n)` stores it and resolves when done.
 */
export function GoalCard({ goal, days, onSave }) {
    const [editing, setEditing] = useState(false);
    const [draft, setDraft] = useState(String(goal.daily_sales_goal));
    const [saving, setSaving] = useState(false);
    const pct = goal.pct_of_goal;
    const color = pct >= 100 ? 'var(--ok)' : 'var(--saffron)';
    const n = Number(draft);
    const ok = Number.isFinite(n) && n >= 100 && n <= 1e7;
    const save = async () => {
        setSaving(true);
        try { await onSave(n); setEditing(false); } finally { setSaving(false); }
    };
    return (<section className="card ov-card ads-goal" aria-labelledby="ads-goal-title">
      <div className="ov-card-head"><h2 id="ads-goal-title" className="serif ov-serif">Daily sales goal</h2>
        {editing ? null : <Button size="sm" variant="ghost" icon="edit" onClick={() => { setDraft(String(goal.daily_sales_goal)); setEditing(true); }}>Change goal</Button>}</div>
      <div className="ads-goal-body">
        <div className="ads-goal-ring">
          <ProgressRing value={Math.min(pct, 100)} color={color} size={150} stroke={3.6} label={`${pct}%`} sub="of goal" title={`${pct}% of the daily goal`}/>
        </div>
        <div className="ads-goal-main">
          <div className="ads-goal-now"><CountUp value={usd(goal.avg_sales_7d)}/><span>/day</span></div>
          {editing ? (<div className="ads-goal-edit">
            <span className="muted">Goal $</span>
            <input className="input sm" type="number" min="100" step="500" value={draft} autoFocus aria-label="Daily store sales goal in dollars"
              onChange={(e) => setDraft(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter' && ok) save(); if (e.key === 'Escape') setEditing(false); }}/>
            <Button size="sm" variant="primary" loading={saving} disabled={!ok} onClick={save}>Save</Button>
            <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>Cancel</Button>
          </div>) : <div className="muted">average store sales of the last 7 days, against a goal of <b className="ads-goal-target">{usd(goal.daily_sales_goal)}</b> a day</div>}
          <div className="ads-goal-bar" aria-hidden="true"><span style={{ width: `${Math.min(pct, 100)}%`, background: color }}/></div>
          <div className="ads-goal-facts">
            <div title="Daily store sales still missing to reach the goal"><span>Still to find</span><b>{usd(goal.gap)}</b></div>
            <div title="Average total ad spend a day, last 7 days"><span>Ad spend now</span><b>{usd(goal.avg_spend_7d)}</b></div>
            <div title={`Ad spend a day the goal needs if every $1 of ads keeps bringing ${x2(goal.mer_7d)} of store sales (the last 7 days)`}>
              <span>Spend the goal needs</span><b>{goal.spend_needed === null ? '—' : usd(goal.spend_needed)}</b></div>
          </div>
        </div>
      </div>
      {days?.length ? <GoalDays days={days} goal={goal.daily_sales_goal}/> : null}
    </section>);
}

const short = (v) => (v >= 1000 ? `$${(v / 1000).toFixed(v >= 10000 ? 0 : 1).replace(/\.0$/, '')}k` : usd(v));

/** The last days' store sales as columns against the goal line, so a reader sees how often the goal is met. */
function GoalDays({ days, goal }) {
    const top = Math.max(goal * 1.15, ...days.map((d) => d.sales_ex_bulk ?? 0));
    const hit = days.filter((d) => (d.sales_ex_bulk ?? 0) >= goal).length;
    return (<div className="ads-goal-days">
      <div className="ads-goal-days-head"><b>Last {days.length} days against the goal</b>
        <span className={`ads-chg ${hit ? 'good' : 'flat'}`}>{hit} of {days.length} days reached it</span></div>
      <div className="ads-goal-cols" role="img" aria-label={days.map((d) => `${weekday(d.date)} ${fmtDay(d.date)} ${usd(d.sales_ex_bulk)}`).join(', ')}>
        <span className="ads-goal-line" style={{ bottom: `${(goal / top) * 100}%` }}><em>Goal {short(goal)}</em></span>
        {days.map((d, i) => {
            const v = d.sales_ex_bulk ?? 0;
            return (<div key={d.date} className="ads-goal-col" title={`${weekday(d.date)} ${fmtDay(d.date)}: store sales ${usd(v)}`}>
              <span className="v">{short(v)}</span>
              <span className={`b${v >= goal ? ' hit' : ''}`} style={{ height: `${(v / top) * 100}%`, animationDelay: `${i * 60}ms` }}/>
            </div>);
        })}
      </div>
      <div className="ads-goal-labels">{days.map((d) => <span key={d.date}>{weekday(d.date)} {Number(d.date.slice(8))}</span>)}</div>
    </div>);
}

/* ------------------------------------------------------------------ the last 14 days */
/** One tile per day, as on the CRO page: weekday, date, store sales, and a bar coloured by that day's MER. */
export function AdsDayStrip({ days, onPick }) {
    return (<div className="ov-strip-wrap">
      <div className="ov-strip-head">
        <b>Last 14 days</b>
        <div className="row" style={{ gap: 6 }}>
          <span className="lane-chip lane-live">Grow</span><span className="lane-chip lane-event">Hold</span><span className="lane-chip lane-due">Cut back</span>
        </div>
      </div>
      <div className="ov-strip" role="group" aria-label="Pick a day">
        {days.map((d) => (<button key={d.date} type="button" className={`ov-day${d.in_range ? ' in' : ''}`} onClick={() => onPick(d.date)}
          title={`${weekday(d.date)} ${fmtDay(d.date)}: store sales ${usd(d.sales_ex_bulk)}, ad spend ${usd(d.spend)}, MER ${x2(d.mer_ex_bulk)}`}>
          <span className="w">{weekday(d.date)}</span>
          <span className="n">{Number(d.date.slice(8))}</span>
          <span className="o">{usd(d.sales_ex_bulk)}</span>
          <span className="o">MER {x2(d.mer_ex_bulk)}</span>
          <span className={`ov-day-bar ${d.colour === 'green' ? 'z-high' : d.colour === 'amber' ? 'z-mid' : d.colour === 'red' ? 'z-low' : 'z-none'}`}/>
        </button>))}
      </div>
    </div>);
}

