'use client';
/**
 * SEO & Blog overview: the blogs Flowmerce plans, writes and schedules by itself (services/auto_blog.py), on a calendar,
 * with how far each one is and projected figures beside it. Built to be read in 5-10 minutes: what goes out next, what
 * waits for a reviewer, whether quality holds, and what it is expected to bring. Every figure comes from
 * GET /api/blog/overview; projections say what they are based on, and show "—" when there is not enough history.
 */
import Link from 'next/link';
import { useRef, useState } from 'react';
import { api, qs, useApi } from '../lib/api';
import { useApp, useBrandParam } from '../lib/app';
import { useNavigate } from '../lib/nav';
import { fmtDate, fmtInt } from '../lib/format';
import { Button, Card, ErrorState, LoadingBlock, PageHead, Pill } from '../components/ui';
import { Icon } from '../components/Icon';
import { MiniGrid, MiniStat, RingCard, SectionHead } from '../components/dash';
import { ProgressRing } from '../components/motion';
import { useToast } from '../components/overlays';
import { ImagePromptBackfill } from '../components/ImagePrompt';
import { AutoBlogSwitch } from '../components/claude';
import { MonthNav, ScheduleDialog, WEEKDAYS, addDays, addMonths, monthDays, monthTitle, useWheelMonths } from '../components/calendar';

/** How each slot state reads and is coloured. */
export const SLOT = {
    ready: { label: 'Ready', long: 'Written and approved, in Flowmerce; waiting for a reviewer to authorize it', tone: 'ok', color: 'var(--theme-good)' },
    writing: { label: 'Writing', long: 'Claude is writing it', tone: 'info', color: 'var(--theme-primary)' },
    planned: { label: 'Planned', long: 'Topic chosen 5 days before', tone: 'neutral', color: 'var(--theme-neutral)' },
    failed: { label: 'Stopped', long: 'The automatic run stopped', tone: 'crit', color: 'var(--theme-low-strong)' },
    missed: { label: 'Missed', long: 'Not written in time', tone: 'warn', color: 'var(--theme-usual-strong)' },
    skipped: { label: 'Skipped', long: 'Skipped by a person', tone: 'neutral', color: 'var(--line-2)' },
};
/** A meter's fill in the dashboard theme for a score's tone (the figure itself keeps the tone's ink). */
const METER = { ok: 'var(--theme-good-strong)', warn: 'var(--theme-usual-strong)', crit: 'var(--theme-low-strong)' };
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
    const d = q.data;
    return (<>
      <PageHead title="SEO & Blog" sub="Blogs Flowmerce plans, writes and schedules by itself."
        actions={<>
          <AutoBlogSwitch enabled={d?.settings.enabled} onChanged={q.reload}/>
          <Link className="btn secondary" href="/pipeline"><Icon name="edit"/>Blog pipeline</Link>
        </>}/>
      {q.error ? <ErrorState error={q.error} onRetry={q.reload}/> : !d ? <LoadingBlock rows={6}/> : <Overview d={d} onChanged={q.reload} canRun={can('workflow:run')} brands={me.brands} brand={brand}/>}
    </>);
}

function Overview({ d, onChanged, canRun, brands, brand }) {
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
            foot="Blogs to authorize" onClick={() => nav('/publishing')} title="Open Publishing to authorize them"/>
          <MiniStat label="Live in the last 30 days" value={fmtInt(c.liveLast30)} foot="Articles published on Shopify"/>
          <MiniStat label="Average quality" value={p.averageQuality === null ? '—' : `${p.averageQuality}/100`} tone={p.averageQuality === null ? undefined : scoreTone(p.averageQuality)}
            foot="Fields, SEO, AEO, GEO, LLMO">
            {p.averageQuality !== null ? <span className="viz-meter"><span className="fill" style={{ width: `${p.averageQuality}%`, background: METER[scoreTone(p.averageQuality)] ?? 'var(--theme-primary)' }}/></span> : null}
          </MiniStat>
          <MiniStat label="Projected clicks a month" value={p.monthlyClicksFromNext4Weeks === null ? '—' : `+${fmtInt(p.monthlyClicksFromNext4Weeks)}`}
            foot={p.clicksPerArticleMonth === null ? 'Needs 28 days of Search Console data and 3 live articles' : `From the next ${c.next4Weeks} blogs, at today's ${p.clicksPerArticleMonth} a month per live article (${p.basedOnArticles} articles)`}/>
          <MiniStat label="Claude cost, next 4 weeks" value={`$${p.claudeUsdNext4Weeks.toFixed(2)}`}
            foot={`About $${p.blogEstimateUsd.toFixed(2)} a blog${budgetShare !== null ? ` · ${budgetShare}% of a month's budget` : ''}`}>
            {budgetShare !== null ? <span className="viz-meter"><span className="fill" style={{ width: `${Math.min(100, budgetShare)}%`, background: 'var(--theme-primary)' }}/></span> : null}
          </MiniStat>
          <MiniStat label="Claude today" value={`$${Number(d.budget?.todayUsd ?? 0).toFixed(2)}`} foot={`of $${Number(d.budget?.dailyLimitUsd ?? 0).toFixed(2)} daily limit`}>
            <span className="viz-meter"><span className="fill" style={{ width: `${Math.min(100, (100 * (d.budget?.todayUsd ?? 0)) / (d.budget?.dailyLimitUsd || 1))}%`, background: 'var(--theme-primary)' }}/></span>
          </MiniStat>
        </MiniGrid>
      </div>
      <SectionHead title="Blog calendar" note="Scroll or pick any month; click a day to see its blogs, cancel one or put a blog on it."/>
      <OverviewCalendar brand={brand} brands={brands} canRun={canRun} today={d.today} onChanged={onChanged}/>
      <SectionHead title="Coming up" note="What each blog is, and how its quality check came out."/>
      <ComingUp d={d} onChanged={onChanged} canRun={canRun} brands={brands}/>
      <SectionHead title="Featured images" note="One AI image prompt per article, sized for the store's blog."/>
      <ImagePromptBackfill brand={brand} canRun={canRun}/>
    </>);
}

/**
 * The overview's blog calendar, interactive (owner request 2026-11-24: "a full-fledged calendar, not a static one"):
 * move to any month and year (arrows, the month picker, Today, or scrolling over the month), click a day to see its
 * blogs and events beside the month, cancel or stop a blog, open its article, or put a blog on that day.
 * Reads GET /calendar for the six weeks shown, so any month shows its blogs and events.
 */
function OverviewCalendar({ brand, brands, canRun, today, onChanged }) {
    const toast = useToast();
    const [month, setMonthState] = useState(today.slice(0, 7));
    const [sel, setSel] = useState(today);
    const [adding, setAdding] = useState(null);
    const gridRef = useRef(null);
    const days = monthDays(month);
    const cal = useApi(`/calendar${qs({ brand, from: days[0], to: days[41] })}`);
    const setMonth = (m) => { setMonthState(m); setSel(m === today.slice(0, 7) ? today : `${m}-01`); };
    useWheelMonths(gridRef, (n) => setMonth(addMonths(month, n)), !!cal.data);
    const bySlot = new Map();
    for (const s of cal.data?.slots ?? [])
        if (s.status !== 'skipped')
            bySlot.set(s.publish_on, [...(bySlot.get(s.publish_on) ?? []), s]);
    const byEvent = new Map();
    for (const e of cal.data?.events ?? [])
        byEvent.set(e.date, [...(byEvent.get(e.date) ?? []), e]);
    const reload = () => { cal.reload(); onChanged(); };
    const cancel = async (s) => {
        try {
            await api.post(`/blog/slots/${s.id}/cancel`);
            toast.ok(s.status === 'writing' ? 'Stopped. Claude will not write a blog for this day.' : 'Cancelled. Claude will not write a blog for this day.');
            reload();
        }
        catch (e) {
            toast.error(e);
        }
    };
    const selSlots = bySlot.get(sel) ?? [];
    const selEvents = byEvent.get(sel) ?? [];
    return (<>
      <div className="ovcal-head">
        <MonthNav month={month} today={today} onChange={setMonth} onToday={() => { setMonthState(today.slice(0, 7)); setSel(today); }}/>
        <span className="spacer"/>
        {canRun ? <Button size="sm" variant="primary" icon="plus" onClick={() => setAdding({ action: 'blog', run_on: sel > today ? sel : addDays(today, 7) })}>Blog on a day</Button> : null}
        <Link className="btn ghost sm" href="/calendar">Content calendar</Link>
      </div>
      <div className="ovcal">
        <div className="blogcal" role="grid" aria-label={`Blog calendar, ${monthTitle(month)}`} ref={gridRef} title="Scroll over the calendar to move to the next or previous month">
          {WEEKDAYS.map((w) => <div key={w} className="blogcal-head" role="columnheader">{w}</div>)}
          {days.map((day, i) => {
              const slots = bySlot.get(day) ?? [];
              const evs = byEvent.get(day) ?? [];
              return (<button type="button" key={day} role="gridcell" onClick={() => setSel(day)} aria-pressed={day === sel}
                className={`blogcal-day${day === today ? ' today' : ''}${day < today ? ' past' : ''}${day.slice(0, 7) !== month ? ' other' : ''}${day === sel ? ' sel' : ''}`}
                style={{ animationDelay: `${Math.min(i, 20) * 12}ms` }}>
                <span className="blogcal-date">{day.slice(8) === '01' ? fmtDate(day, { day: 'numeric', month: 'short' }) : Number(day.slice(8))}</span>
                {evs.slice(0, 1).map((e) => <span key={e.key} className="blogcal-event" title={e.name}><Icon name="star" size="sm"/>{e.name}</span>)}
                {slots.map((s) => (<span key={s.id} className={`blogcal-slot st-${s.status}`} title={`${(SLOT[s.status] ?? SLOT.planned).label}: ${slotTitle(s, brands)}`}>
                  <span className={`brand-dot ${s.brand_id}`}/>
                  <span className="blogcal-title">{slotTitle(s, brands)}</span>
                  {s.checks?.score !== null && s.checks?.score !== undefined ? <span className={`blogcal-score tone-${scoreTone(s.checks.score)}`}>{s.checks.score}</span> : null}
                </span>))}
              </button>);
          })}
        </div>
        <aside className="ovcal-side" aria-label="The selected day"><div className="ovcal-side-in">
          <h3 className="dayside-title">{new Date(`${sel}T12:00:00`).toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })}</h3>
          {canRun && sel > today ? <Button size="sm" variant="primary" icon="plus" className="mt-8" onClick={() => setAdding({ action: 'blog', run_on: sel })}>Blog on this day</Button> : null}
          {!selSlots.length && !selEvents.length ? <div className="daypanel-empty mt-8">{sel > today ? 'Nothing planned. Put a blog on this day.' : 'Nothing on this day.'}</div> : null}
          <div className="mt-8">
            {selEvents.map((e) => (<div key={e.key} className="ovcal-item">
              <div className="row-wrap" style={{ gap: 6 }}><Icon name="star" size="sm"/><span className="strong">{e.name}</span>{e.builtin ? null : <Pill tone="info">Your event</Pill>}</div>
              <div className="small muted">Publish an article for it by {fmtDate(e.publish_by)}.{e.note ? ` ${e.note}` : ''}</div>
            </div>))}
            {selSlots.map((s) => {
                const info = SLOT[s.status] ?? SLOT.planned;
                return (<div key={s.id} className="ovcal-item">
                  <div className="row-wrap" style={{ gap: 6 }}><span className={`brand-dot ${s.brand_id}`}/><Pill tone={info.tone} dot={s.status === 'writing'}>{info.label}</Pill>
                    {s.scheduled_topic ? <Pill tone="outline">Your topic</Pill> : null}</div>
                  <div className="strong mt-4">{slotTitle(s, brands)}</div>
                  <div className="small muted">{s.message || (s.status === 'planned' ? `Claude writes it on ${pickDay(s, 5)}; it goes live at 10:00 once you authorize it.` : info.long)}</div>
                  {s.checks?.score !== null && s.checks?.score !== undefined ? <div className="small">Quality check: {s.checks.score}/100</div> : null}
                  <div className="row-wrap mt-4" style={{ gap: 6 }}>
                    {s.article_id ? <Link className="btn ghost xs" href={`/articles/${s.article_id}`}>Open article</Link> : null}
                    {canRun && ['planned', 'writing'].includes(s.status) ? <Button size="xs" variant="secondary" icon="x" onClick={() => cancel(s)}>{s.status === 'writing' ? 'Stop writing' : 'Cancel this blog'}</Button> : null}
                  </div>
                </div>);
            })}
          </div>
        </div></aside>
      </div>
      {adding ? <ScheduleDialog initial={adding} upcoming={cal.data?.upcoming ?? []} onClose={() => setAdding(null)} onSaved={() => { setAdding(null); reload(); }}/> : null}
    </>);
}

/** The next blogs, nearest first: status, quality by group, and Cancel for one that is planned or being written. */
function ComingUp({ d, onChanged, canRun, brands }) {
    const toast = useToast();
    const rows = d.slots.filter((s) => s.publish_on >= d.today && s.status !== 'skipped').slice(0, 8);
    const skip = async (s) => {
        try {
            await api.post(`/blog/slots/${s.id}/cancel`);
            toast.ok(`The ${fmtDate(s.publish_on, { day: 'numeric', month: 'short' })} blog is cancelled.${s.status === 'writing' ? ' Claude has stopped writing it.' : ''}`);
            onChanged();
        }
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
              {['planned', 'writing'].includes(s.status) && canRun ? <Button size="sm" variant="ghost" icon="x" onClick={() => skip(s)}
                title={s.status === 'writing' ? 'Stop Claude writing this blog; no blog for this day' : 'Do not write a blog for this day'}>{s.status === 'writing' ? 'Stop' : 'Cancel'}</Button> : null}
            </div>
          </div>);
      })}
    </div>);
}
