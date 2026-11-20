'use client';
/**
 * SEO & Blog overview: the blogs Flowmerce plans, writes and schedules by itself (services/auto_blog.py), on a calendar,
 * with how far each one is and projected figures beside it. Built to be read in 5-10 minutes: what goes out next, what
 * waits for a reviewer, whether quality holds, and what it is expected to bring. Every figure comes from
 * GET /api/blog/overview; projections say what they are based on, and show "—" when there is not enough history.
 */
import Link from 'next/link';
import { useState } from 'react';
import { api, qs, useApi } from '../lib/api';
import { useApp, useBrandParam } from '../lib/app';
import { useNavigate } from '../lib/nav';
import { fmtDate, fmtInt } from '../lib/format';
import { Button, Card, ErrorState, LoadingBlock, PageHead, Pill } from '../components/ui';
import { Icon } from '../components/Icon';
import { MiniGrid, MiniStat, RingCard, SectionHead } from '../components/dash';
import { ProgressRing } from '../components/motion';
import { useToast } from '../components/overlays';

/** How each slot state reads and is coloured. */
export const SLOT = {
    ready: { label: 'Ready', long: 'Hidden Shopify draft, waiting for a reviewer', tone: 'ok', color: 'var(--ok)' },
    writing: { label: 'Writing', long: 'Claude is writing it', tone: 'info', color: 'var(--info)' },
    planned: { label: 'Planned', long: 'Topic chosen 5 days before', tone: 'neutral', color: '#c9c0b5' },
    failed: { label: 'Stopped', long: 'The automatic run stopped', tone: 'crit', color: 'var(--crit)' },
    missed: { label: 'Missed', long: 'Not written in time', tone: 'warn', color: 'var(--warn)' },
    skipped: { label: 'Skipped', long: 'Skipped by a person', tone: 'neutral', color: 'var(--line-2)' },
};
const GROUPS = [['seo', 'SEO'], ['aeo', 'AEO'], ['geo', 'GEO'], ['llmo', 'LLMO']];
const DAY_MS = 864e5;
const isoOf = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
/** A slot's title: the article or topic once chosen, else "<Brand> blog". */
const slotTitle = (s, brands) => s.article_title || s.topic_title || `${brands?.find((b) => b.id === s.brand_id)?.short ?? s.brand_id} blog`;
/** When Claude picks the topic for a planned slot (lead days before its day). */
const pickDay = (s, lead) => fmtDate(isoOf(new Date(new Date(`${s.publish_on}T00:00:00`).getTime() - lead * DAY_MS)), { day: 'numeric', month: 'short' });
const scoreTone = (s) => (s === null || s === undefined ? 'neutral' : s >= 85 ? 'ok' : s >= 65 ? 'warn' : 'crit');

export default function BlogHome() {
    const brand = useBrandParam();
    const { can, me } = useApp();
    const q = useApi(`/blog/overview${qs({ brand })}`);
    const toast = useToast();
    const [busy, setBusy] = useState(false);
    const toggle = async (enabled) => {
        setBusy(true);
        try { await api.patch('/blog/autopilot', { enabled }); toast.ok(enabled ? 'Automatic blogs are on. The next one starts 5 days before its day.' : 'Automatic blogs are paused. Nothing new will start.'); q.reload(); }
        catch (e) { toast.error(e); } finally { setBusy(false); }
    };
    const d = q.data;
    return (<>
      <PageHead title="SEO & Blog" sub="Blogs Flowmerce plans, writes and schedules by itself."
        actions={<>
          {d && can('workflow:run') ? <Button icon={d.settings.enabled ? 'pause' : 'play'} loading={busy} onClick={() => toggle(!d.settings.enabled)}
            title={d.settings.enabled ? 'Stop new automatic blogs from starting (anything already written stays)' : 'Let Flowmerce write the planned blogs (about $2 of Claude each; saved as hidden Shopify drafts)'}>
            {d.settings.enabled ? 'Pause automatic blogs' : 'Start automatic blogs'}</Button> : null}
          <Link className="btn secondary" href="/write"><Icon name="edit"/>Write it yourself</Link>
        </>}/>
      {q.error ? <ErrorState error={q.error} onRetry={q.reload}/> : !d ? <LoadingBlock rows={6}/> : <Overview d={d} onChanged={q.reload} canRun={can('workflow:run')} brands={me.brands}/>}
    </>);
}

function Overview({ d, onChanged, canRun, brands }) {
    const nav = useNavigate();
    const c = d.counts;
    const p = d.projection;
    const segments = ['ready', 'writing', 'planned', 'missed', 'failed'].map((k) => ({ key: k, name: SLOT[k].label, range: SLOT[k].long, value: c[k] ?? 0, color: SLOT[k].color }));
    const budgetShare = d.budget?.monthlyBudgetUsd ? Math.round((p.claudeUsdNext4Weeks / d.budget.monthlyBudgetUsd) * 100) : null;
    return (<>
      {!d.settings.enabled ? <div className="callout warn mb-12"><Icon name="pause"/><div><b>Automatic blogs are off.</b> The calendar shows what Flowmerce would write; nothing is written until an admin starts them.
        Start them in one copy of Flowmerce only (this computer or the online workspace): each copy has its own records, so running both would write every blog twice.</div></div> : null}
      <div className="ov-hero">
        <RingCard label="Blogs in the next 4 weeks" total={c.upcoming} centerLabel="planned" segments={segments}
          pill={{ tone: 'info', label: `${d.settings.weekdayNames.join(' & ')} · 10:00` }}/>
        <MiniGrid>
          <MiniStat label="Waiting for a reviewer" value={fmtInt(c.waitingForReviewer)} tone={c.waitingForReviewer ? 'warn' : undefined}
            foot="Hidden drafts to authorize" onClick={() => nav('/publishing')} title="Open Publishing to authorize them"/>
          <MiniStat label="Live in the last 30 days" value={fmtInt(c.liveLast30)} foot="Articles published on Shopify"/>
          <MiniStat label="Average quality" value={p.averageQuality === null ? '—' : `${p.averageQuality}/100`} tone={p.averageQuality === null ? undefined : scoreTone(p.averageQuality)}
            foot="Fields, SEO, AEO, GEO, LLMO">
            {p.averageQuality !== null ? <span className="viz-meter"><span className="fill" style={{ width: `${p.averageQuality}%`, background: `var(--${scoreTone(p.averageQuality)})` }}/></span> : null}
          </MiniStat>
          <MiniStat label="Projected clicks a month" value={p.monthlyClicksFromNext4Weeks === null ? '—' : `+${fmtInt(p.monthlyClicksFromNext4Weeks)}`}
            foot={p.clicksPerArticleMonth === null ? 'Needs 28 days of Search Console data and 3 live articles' : `From the next ${c.next4Weeks} blogs, at today's ${p.clicksPerArticleMonth} a month per live article (${p.basedOnArticles} articles)`}/>
          <MiniStat label="Claude cost, next 4 weeks" value={`$${p.claudeUsdNext4Weeks.toFixed(2)}`}
            foot={`About $${p.blogEstimateUsd.toFixed(2)} a blog${budgetShare !== null ? ` · ${budgetShare}% of a month's budget` : ''}`}>
            {budgetShare !== null ? <span className="viz-meter"><span className="fill" style={{ width: `${Math.min(100, budgetShare)}%`, background: 'var(--accent)' }}/></span> : null}
          </MiniStat>
          <MiniStat label="Claude today" value={`$${Number(d.budget?.todayUsd ?? 0).toFixed(2)}`} foot={`of $${Number(d.budget?.dailyLimitUsd ?? 0).toFixed(2)} daily limit`}>
            <span className="viz-meter"><span className="fill" style={{ width: `${Math.min(100, (100 * (d.budget?.todayUsd ?? 0)) / (d.budget?.dailyLimitUsd || 1))}%`, background: 'var(--info)' }}/></span>
          </MiniStat>
        </MiniGrid>
      </div>
      <SectionHead title="Blog calendar" note="Each blog goes live only after a reviewer authorizes it." action={<Link className="small" href="/calendar">Content calendar</Link>}/>
      <BlogCalendar d={d} brands={brands}/>
      <SectionHead title="Coming up" note="What each blog is, and how its quality check came out."/>
      <ComingUp d={d} onChanged={onChanged} canRun={canRun} brands={brands}/>
    </>);
}

/** Five weeks from this Monday, a cell per day, the brand's slots and calendar events in each. */
function BlogCalendar({ d, brands }) {
    const today = new Date(`${d.today}T00:00:00`);
    const monday = new Date(today.getTime() - ((today.getDay() + 6) % 7) * DAY_MS);
    const days = Array.from({ length: 35 }, (_, i) => isoOf(new Date(monday.getTime() + i * DAY_MS)));
    const bySlot = new Map();
    for (const s of d.slots) bySlot.set(s.publish_on, [...(bySlot.get(s.publish_on) ?? []), s]);
    const byEvent = new Map(d.events.map((e) => [e.date, e]));
    return (<div className="blogcal" role="grid" aria-label="Blog calendar, five weeks">
      {['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].map((w) => <div key={w} className="blogcal-head" role="columnheader">{w}</div>)}
      {days.map((day, i) => {
          const slots = bySlot.get(day) ?? [];
          const ev = byEvent.get(day);
          const past = day < d.today;
          return (<div key={day} role="gridcell" className={`blogcal-day${day === d.today ? ' today' : ''}${past ? ' past' : ''}`} style={{ animationDelay: `${Math.min(i, 20) * 12}ms` }}>
            <span className="blogcal-date">{day.slice(8) === '01' || i === 0 ? fmtDate(day, { day: 'numeric', month: 'short' }) : Number(day.slice(8))}</span>
            {ev ? <span className="blogcal-event" title={ev.name}><Icon name="star" size="sm"/>{ev.name}</span> : null}
            {slots.map((s) => {
                const info = SLOT[s.status] ?? SLOT.planned;
                const title = slotTitle(s, brands);
                const body = (<>
                  <span className={`brand-dot ${s.brand_id}`}/>
                  <span className="blogcal-title">{title}</span>
                  {s.checks?.score !== null && s.checks?.score !== undefined ? <span className={`blogcal-score tone-${scoreTone(s.checks.score)}`}>{s.checks.score}</span> : null}
                </>);
                return s.article_id
                    ? <Link key={s.id} href={`/articles/${s.article_id}`} className={`blogcal-slot st-${s.status}`} title={`${info.label}: ${title}`}>{body}</Link>
                    : <span key={s.id} className={`blogcal-slot st-${s.status}`} title={`${info.label}: ${info.long}`}>{body}</span>;
            })}
          </div>);
      })}
    </div>);
}

/** The next blogs, nearest first: status, quality by group, and Skip for one that has not started. */
function ComingUp({ d, onChanged, canRun, brands }) {
    const toast = useToast();
    const rows = d.slots.filter((s) => s.publish_on >= d.today && s.status !== 'skipped').slice(0, 8);
    const skip = async (s) => {
        try { await api.post(`/blog/slots/${s.id}/skip`); toast.ok(`The ${fmtDate(s.publish_on, { day: 'numeric', month: 'short' })} blog is skipped.`); onChanged(); }
        catch (e) { toast.error(e); }
    };
    if (!rows.length)
        return <Card><div className="muted small">No automatic blogs are planned. They are planned within 15 minutes of starting Flowmerce.</div></Card>;
    return (<div className="col gap-12 stagger">
      {rows.map((s) => {
          const info = SLOT[s.status] ?? SLOT.planned;
          const ck = s.checks ?? {};
          return (<div key={s.id} className="card blog-row">
            <div className="blog-row-when">
              <span className="blog-row-day">{fmtDate(s.publish_on, { weekday: 'short' })}</span>
              <span className="blog-row-date">{fmtDate(s.publish_on, { day: 'numeric', month: 'short' })}</span>
            </div>
            <div className="blog-row-main">
              <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
                <span className={`brand-dot ${s.brand_id}`}/>
                {s.article_id ? <Link href={`/articles/${s.article_id}`} className="strong">{s.article_title || s.topic_title}</Link>
                    : <span className="strong">{slotTitle(s, brands)}</span>}
                <Pill tone={info.tone} dot={s.status === 'writing'}>{info.label}</Pill>
              </div>
              <div className="muted small">{s.message || (s.status === 'planned' ? `Claude picks the topic on ${pickDay(s, d.settings.leadDays ?? 5)}` : info.long)}{s.primary_keyword ? ` · keyword “${s.primary_keyword}”` : ''}{ck.words ? ` · ${fmtInt(ck.words)} words, ${ck.images} images` : ''}</div>
              {ck.open?.length ? <div className="xs muted">Still open: {ck.open.join(', ')}</div> : null}
            </div>
            <div className="blog-row-checks">
              {ck.score !== null && ck.score !== undefined ? (<>
                <ProgressRing value={ck.score} max={100} label={String(ck.score)} color={`var(--${scoreTone(ck.score)})`} size={52} title={`Quality ${ck.score} of 100`}/>
                <div className="blog-groups">{GROUPS.map(([k, l]) => (<span key={k} className="blog-group" title={`${l}: ${ck.groups?.[k] ?? '—'}/100`}>
                  <span className="blog-group-label">{l}</span>
                  <span className="blog-group-bar"><span className="grow-x" style={{ width: `${ck.groups?.[k] ?? 0}%`, background: `var(--${scoreTone(ck.groups?.[k])})` }}/></span>
                </span>))}</div>
              </>) : <span className="muted xs">Checked after writing</span>}
            </div>
            <div className="blog-row-act">
              {s.status === 'planned' && canRun ? <Button size="sm" variant="ghost" onClick={() => skip(s)} title="Do not write a blog for this day">Skip</Button> : null}
            </div>
          </div>);
      })}
    </div>);
}
