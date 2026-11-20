'use client';
/**
 * Dashboard building blocks shared by Home, SEO & Blog and Shipping (the "Flowmerce warm" look):
 * a plain-language greeting, a ring card, small stat cards, a left-to-right journey strip and to-do rows.
 * They only lay out what they are given; every number comes from the page's own API data.
 */
import { fmtInt } from '../lib/format';
import { Card, Pill } from './ui';
import { Icon } from './Icon';
import { CountUp } from './motion';

export function greeting(d = new Date()) {
    const h = d.getHours();
    return h < 12 ? 'Good morning.' : h < 17 ? 'Good afternoon.' : 'Good evening.';
}

/** Joins ["a", "b", "c"] as "a, b and c". */
export function joinParts(parts) {
    const p = parts.filter(Boolean);
    return p.length > 1 ? `${p.slice(0, -1).join(', ')} and ${p[p.length - 1]}` : (p[0] ?? '');
}

/**
 * "Good afternoon. 12 things need you today." with the breakdown underneath.
 * `count` undefined means the figures are still loading; `noun` is singular ("order", "thing").
 */
export function Greeting({ count, noun = 'thing', parts = [], actions, calm = 'Nothing needs you today.' }) {
    const sub = joinParts(parts);
    return (<div className="today">
      <div style={{ minWidth: 0 }}>
        <h2 className="today-title serif">{greeting()} {count === undefined ? 'Reading today’s figures…' : count === 0 ? calm : `${fmtInt(count)} ${noun}${count === 1 ? '' : 's'} need${count === 1 ? 's' : ''} you today.`}</h2>
        {sub ? <div className="today-sub">{sub}.</div> : null}
      </div>
      {actions ? <div className="row-wrap">{actions}</div> : null}
    </div>);
}

/** A small clickable stat card. `children` is an optional small picture (bar, mini chart) kept at the bottom. */
export function MiniStat({ label, value, foot, tone, onClick, title, children }) {
    const inner = (<>
      <span className="mini-label">{label}</span>
      <span className="mini-value" style={tone ? { color: `var(--${tone})` } : undefined}><CountUp value={value}/></span>
      {foot ? <span className="mini-foot">{foot}</span> : null}
      {children ? <span className="mini-viz">{children}</span> : null}
    </>);
    return onClick ? <button type="button" className="mini" onClick={onClick} title={title}>{inner}</button> : <div className="mini static">{inner}</div>;
}

export function MiniGrid({ children }) {
    return <div className="ov-minis">{children}</div>;
}

const share = (v, sum) => (sum ? v / sum : 0);
const pctText = (f) => (f > 0 && f < 0.01 ? '<1%' : `${Math.round(f * 100)}%`);

/**
 * A ring of the parts with the total in its centre, and a legend whose rows carry a bar of each part's share, so
 * the card's width is used. segments: [{ key, name, range?, value, color, onClick? }]. `center` / `centerLabel`
 * override the centre (default: the total). `compact` is the smaller form used inside another card.
 */
export function RingBody({ segments, total, center, centerLabel, compact }) {
    const sum = segments.reduce((n, s) => n + (s.value || 0), 0);
    let at = 0;
    const arcs = segments.filter((s) => s.value).map((s) => {
        const len = share(s.value, sum) * 100;
        const a = { ...s, len: Math.max(len - 0.8, 0.4), off: at };
        at += len;
        return a;
    });
    const mid = center ?? (typeof total === 'number' ? fmtInt(total) : total);
    const midText = String(mid ?? '');
    return (<div className={`age-body${compact ? ' compact' : ''}`}>
      <svg className="age-ring" viewBox="0 0 36 36" role="img" aria-label={segments.map((s) => `${s.name}: ${s.value}`).join(', ')}>
        <circle cx="18" cy="18" r="15.9155" fill="none" stroke="var(--line-2)" strokeWidth="3.4"/>
        {arcs.map((a, i) => (<circle key={a.key} className="ring-arc" style={{ animationDelay: `${i * 70}ms`, ...(a.onClick ? { cursor: 'pointer' } : {}) }} cx="18" cy="18" r="15.9155" fill="none" stroke={a.color} strokeWidth="3.4"
            strokeDasharray={`${a.len} ${100 - a.len}`} strokeDashoffset={-a.off} transform="rotate(-90 18 18)"
            onClick={a.onClick}><title>{`${a.name}: ${fmtInt(a.value)}`}</title></circle>))}
        {mid !== undefined && mid !== null ? <text x="18" y={centerLabel ? 18.4 : 20} textAnchor="middle" className={`age-ring-num${midText.length > 5 ? ' long' : ''}`}><CountUp value={midText} as="tspan"/></text> : null}
        {centerLabel ? <text x="18" y="23" textAnchor="middle" className="age-ring-sub">{centerLabel}</text> : null}
      </svg>
      <div className="age-legend">
        {segments.map((s) => {
            const f = share(s.value || 0, sum);
            const body = (<>
              <span className="age-dot" style={{ background: s.color }}/>
              <span className="age-name">{s.name}{s.range && !compact ? <span className="age-range">{s.range}</span> : null}</span>
              <span className="age-count"><CountUp value={fmtInt(s.value)}/></span>
              <span className="age-pct">{pctText(f)}</span>
              <span className="age-bar" aria-hidden="true"><span style={{ width: `${Math.max(f * 100, s.value ? 1.5 : 0)}%`, background: s.color }}/></span>
            </>);
            return s.onClick ? <button type="button" key={s.key} className={`age-item${s.value ? '' : ' zero'}`} onClick={s.onClick} title={`See ${s.name}`}>{body}</button>
                : <div key={s.key} className={`age-item${s.value ? '' : ' zero'}`}>{body}</div>;
        })}
      </div>
    </div>);
}

/** A card: its label (a link to the full list when `onTotal` is given) and a pill on top, the ring and legend below. */
export function RingCard({ label, total, onTotal, pill, segments, center, centerLabel }) {
    const head = <span className="age-total-label">{label}</span>;
    return (<Card className="age-card">
      <div className="age-top">
        {onTotal ? <button type="button" className="age-total" onClick={onTotal} title={`See ${String(label).toLowerCase()}`}>{head}</button> : <div className="age-total">{head}</div>}
        {pill ? <Pill tone={pill.tone ?? 'ok'}>{pill.label}</Pill> : null}
      </div>
      <RingBody segments={segments} total={total} center={center} centerLabel={centerLabel}/>
    </Card>);
}

/**
 * Left-to-right stages with the problems sitting in each.
 * steps: [{ key, label, value, onClick?, done?, selected?, calm?, flags: [{ label, value, tone, onClick? }] }]
 */
export function Journey({ steps, label = 'Stages', compact }) {
    if (!steps.length)
        return null;
    return (<div className={`journey${compact ? ' compact' : ''}`} role="list" aria-label={label} style={{ '--steps': steps.length }}>
      {steps.map((s, i) => {
          const head = (<><span className="journey-label">{s.label}</span><span className="journey-value">{typeof s.value === 'number' ? fmtInt(s.value) : s.value}</span></>);
          const flags = s.flags ?? [];
          return (<div key={s.key} role="listitem" className={`journey-step${s.done ? ' done' : ''}${s.selected ? ' selected' : ''}${s.value === 0 ? ' zero' : ''}`}>
            {s.onClick ? <button type="button" className="journey-head" onClick={s.onClick} aria-pressed={s.selected === undefined ? undefined : !!s.selected} title={`See ${s.label.toLowerCase()}`}>{head}</button>
                  : <div className="journey-head">{head}</div>}
            {compact && !flags.length ? null : (<div className="journey-flags">
              {flags.length ? flags.map((f) => (f.onClick
                    ? <button type="button" key={f.label} className={`journey-flag tone-${f.tone}`} onClick={f.onClick}>{fmtInt(f.value)} {f.label}</button>
                    : <span key={f.label} className={`journey-flag tone-${f.tone}`}>{fmtInt(f.value)} {f.label}</span>))
                  : <span className="journey-flag calm">{s.calm ?? 'Nothing stuck'}</span>}
            </div>)}
            {i < steps.length - 1 ? <span className="journey-arrow" aria-hidden="true"><Icon name="chevronRight" size="sm"/></span> : null}
          </div>);
      })}
    </div>);
}

/** A section heading in the serif face, with a short note and an optional action on the right. */
export function SectionHead({ title, note, action }) {
    return (<div className="sec-head">
      <h2 className="serif">{title}</h2>
      {note ? <span className="muted small">{note}</span> : null}
      <span className="spacer"/>
      {action}
    </div>);
}

/**
 * One to-do row: a coloured badge, what it is, why it is here, tags, and the next step.
 * `action` is a node (a Button or a link) so each page decides where it goes.
 */
export function TodoRow({ badge, tone = 'warn', icon, title, onTitle, meta, detail, tags, action }) {
    return (<div className="triage-row">
      <span className={`triage-age tone-${tone}`}>{icon ? <Icon name={icon} size="sm"/> : badge}</span>
      <div className="triage-order">
        {onTitle ? <button type="button" className="triage-num" onClick={onTitle}>{title}</button> : <span className="triage-num static">{title}</span>}
        {meta ? <span className="triage-meta">{meta}</span> : null}
      </div>
      <div className="triage-why">{detail ? <span className="triage-detail">{detail}</span> : null}</div>
      <div className="triage-tags">{tags}</div>
      <div className="triage-acts">{action}</div>
    </div>);
}
