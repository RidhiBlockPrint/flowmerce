'use client';
import { useState } from 'react';
import Link from 'next/link';
import { More } from '../components/More';
import { useApp } from '../lib/app';
import { useNavigate } from '../lib/nav';
import { useApi, qs } from '../lib/api';
import { HOME_PERIODS, useHomeAds, useHomeData, useHomePeriod } from '../lib/home';
import { conversionScale } from '../lib/cro';
import { fmtCompact, fmtInt, timeAgo } from '../lib/format';
import { BrandTag, Card, Empty, ErrorState, LoadingBlock, PageHead, Paged, Pill } from '../components/ui';
import { BRAND_COLOR } from '../components/metrics';
import { LineChart } from '../components/charts';
import { AdsTile, GoalTile, ListCard, ListRow, MixTile, OpsRow, SalesHero, StoreTiles, brandLabel } from '../components/home';
import { ExplainedError, Seg } from '../components/cro';
import { Journey, MiniGrid, MiniStat, RingCard, SectionHead, TodoRow } from '../components/dash';

const SEVERITY = {
    critical: { tone: 'crit', label: 'Critical' },
    warning: { tone: 'warn', label: 'Warning' },
    info: { tone: 'info', label: 'Info' },
};
const RUN = {
    succeeded: { tone: 'ok', icon: 'checkCircle', label: 'Succeeded' },
    failed: { tone: 'crit', icon: 'xCircle', label: 'Failed' },
    running: { tone: 'info', icon: 'refresh', label: 'Running' },
    waiting: { tone: 'warn', icon: 'clock', label: 'Waiting' },
    skipped: { tone: undefined, icon: 'pause', label: 'Skipped' },
};
const runInfo = (status) => RUN[status] ?? { tone: undefined, icon: 'info', label: status };
const isIso = (v) => !!v && /^\d{4}-\d{2}-\d{2}T/.test(v);
const ago = (v, none) => (v ? (isIso(v) ? timeAgo(v) : v) : none);
const sum = (rows, f) => rows.reduce((n, r) => n + (r[f] ?? 0), 0);

/* Article lifecycle, left to right. `statuses` matches the Articles page filter. */
const CONTENT_STAGES = [
    { key: 'drafts', label: 'Ideas and drafts', statuses: ['idea', 'draft', 'changes_requested'], color: 'var(--theme-neutral)' },
    { key: 'review', label: 'In review', statuses: ['in_review'], color: 'var(--theme-primary-soft)' },
    { key: 'approved', label: 'Approved', statuses: ['approved', 'publish_requested'], color: 'var(--theme-usual-strong)' },
    { key: 'scheduled', label: 'Scheduled', statuses: ['scheduled'], color: 'var(--theme-usual)' },
    { key: 'published', label: 'Published', statuses: ['published'], color: 'var(--theme-good)' },
];

/**
 * Home: the CEO view, layout "A · Bento" (owner, 2026-11-27; design-mockups/home-ceo/a-bento.html). One dashboard for
 * All, Ridhi and CPC, for a period (Today, Yesterday, 7 days, 30 days, Month to date) against the one before: a large
 * Sales tile, orders, average order, conversion and visits, a wide Ads tile, the brands' (or channels') shares, the
 * month's goal, and a small row of operations figures. Figures only: no headline sentence and no advice. On All both
 * brands are added together on the server (GET /api/cro/home-period, GET /api/ads/company). The to-do list, content
 * pipeline, blog clicks, brand report and automation runs are folded under "Show more" (GET /api/home,
 * GET /api/articles/counts).
 */
export default function Home() {
    const { brand, me, setBrand } = useApp();
    const nav = useNavigate();
    const brands = me.brands;
    const oneBrand = brand !== 'all';
    const showBrand = !oneBrand;
    const [period, setPeriod] = useState('yesterday');
    const q = useHomePeriod(brand, period);
    const h = q.data;
    const ads = useHomeAds(brand, h?.from, h?.to);
    const { data, loading, error, reload } = useHomeData(brand);
    const counts = useApi(`/articles/counts${qs({ brand: oneBrand ? brand : undefined })}`);
    // Same address as the Shipping page's overview, so either page shows the other's answer at once.
    const shipSummary = useApi(`/shipping/summary${qs({ brand: oneBrand ? brand : undefined })}`);

    const scope = oneBrand ? brands.find((b) => b.id === brand)?.short ?? brand : 'both brands';
    const days = (h?.days ?? []).filter((d) => d.date <= (h?.to ?? ''));
    const scale = h ? conversionScale(days.slice(-28).map((d) => d.conversion_rate), h.metrics?.conversion_rate?.value ?? null) : null;
    const sub = h ? `${brandLabel(brand, brands)} · ${h.period_label}${h.baseline_label ? `, ${h.baseline_label}` : ''}` : brandLabel(brand, brands);

    return (<>
      <PageHead title="Home" sub={sub} actions={<Seg label="Period" options={HOME_PERIODS} value={period} onChange={setPeriod}/>}/>

      {q.error && !h ? <ExplainedError error={q.error} onRetry={q.reload}/> : !h ? <LoadingBlock rows={8}/> : (<>
        <div className="hb-grid">
          <SalesHero h={h} scope={scope}/>
          <StoreTiles h={h} scale={scale}/>
          <AdsTile ads={ads.data} error={ads.error} scope={scope} today={h.period === 'today'}/>
          <MixTile h={h} ads={ads.data} brands={brands} oneBrand={oneBrand} today={h.period === 'today'}/>
          <GoalTile goal={h.goal} oneBrand={oneBrand}/>
        </div>
        {h.cvr_error ? <div className="hb-note"><ExplainedError error={{ code: h.cvr_error.state, message: h.cvr_error.message }}/></div> : null}
      </>)}

      <OpsRow shipProblems={data.shipping?.all?.problems} shipSummary={shipSummary.data} waiting={loading ? null : data.approvalsTotal}
        ordersSyncedAt={h?.orders_synced_at} adsBrands={ads.data?.brands}/>

      {loading || error ? (<More id="home" label="Show the to-do list, content pipeline and brand report">
          {error ? <ErrorState error={error} onRetry={reload}/> : <LoadingBlock rows={6}/>}
        </More>)
        : <HomeDetails data={data} counts={counts} brand={brand} brands={brands} showBrand={showBrand} setBrand={setBrand} nav={nav}/>}
    </>);
}

/**
 * Everything that is not a headline figure, folded under "Show more": the to-do list (decisions, alerts, failed runs,
 * delivery problems, most serious first), the content pipeline, blog search clicks, the brand report and automation
 * runs. Ridhi and CPC are never added together here (search clicks, the brand report).
 */
function HomeDetails({ data, counts, brand, brands, showBrand, setBrand, nav }) {
    const oneBrand = brand !== 'all';
    const common = { brands, showBrand };
    const clicks = (b) => data.metrics.find((m) => m.brand === b && m.key === 'gsc_clicks');
    const sessions = (b) => data.metrics.find((m) => m.brand === b && m.key === 'ga4_sessions');
    const failedJobs = data.jobs.filter((j) => j.status === 'failed' && !j.failedOnlyBecausePaused && !(j.lastSuccessAt && j.lastSuccessAt > (j.finishedAt ?? j.startedAt ?? '')));
    const ship = data.shipping?.all;
    const live = sum(data.articles, 'live');
    const total = sum(data.articles, 'total');
    const n = (statuses) => (counts.data ?? []).filter((c) => statuses.includes(c.status)).reduce((a, c) => a + c.n, 0);
    const failedPublish = n(['failed']);
    const sentBack = n(['changes_requested']);
    const toArticles = (statuses) => nav(`/articles?status=${statuses.join(',')}`);

    const todo = [
        ...data.approvals.map((a) => ({ id: `ap-${a.id}`, tone: 'info', icon: 'checkCircle', title: a.title, to: a.to, brand: a.brand,
            meta: a.label, detail: isIso(a.since) ? `Waiting ${timeAgo(a.since).replace(' ago', '')} for your decision.` : a.since, action: 'Decide', tag: 'Decision' })),
        ...data.alerts.map((a) => ({ id: `al-${a.id}`, tone: SEVERITY[a.severity]?.tone ?? 'warn', icon: 'alert', title: a.title, to: a.to, brand: null,
            meta: SEVERITY[a.severity]?.label ?? a.severity, detail: a.detail || 'Open for details.', action: 'Open', tag: 'Alert' })),
        ...failedJobs.map((j) => ({ id: `job-${j.id}`, tone: 'crit', icon: 'xCircle', title: j.name, to: '/automation', brand: j.brand,
            meta: 'Automation run failed', detail: `Started ${ago(j.startedAt, 'at an unknown time')}. Last success: ${ago(j.lastSuccessAt, 'none recorded')}.`, action: 'Check run', tag: 'Automation' })),
        ...(ship?.top ?? []).map((s) => ({ id: `sh-${s.trackingId}`, tone: 'warn', icon: 'truck', title: `${s.order} · ${s.carrier}`,
            to: `/shipping?tab=shipments&q=${encodeURIComponent(s.order ?? '')}`, brand: s.brand, meta: 'Delivery problem',
            detail: `${s.days ?? '?'} day${s.days === 1 ? '' : 's'} since the last carrier update${s.label ? ` (${s.label})` : ''}${s.place ? `, last seen ${s.place}` : ''}.`, action: 'Open order', tag: 'Shipping' })),
    ];
    const severity = { crit: 0, warn: 1, info: 2 };
    todo.sort((a, b) => (severity[a.tone] ?? 3) - (severity[b.tone] ?? 3));
    const critical = data.alerts.filter((a) => a.severity === 'critical').length;
    const needs = data.approvalsTotal + critical + failedJobs.length + (ship?.problems ?? 0);

    return (<More id="home" label={`Show the to-do list${needs ? ` (${fmtInt(needs)})` : ''}, content pipeline and brand report`}>
      <SectionHead title="Today&rsquo;s to-do" note="Decisions, alerts, failed runs and delivery problems, most serious first."
        action={<Link className="btn sm" href="/publishing">All decisions</Link>}/>
      <Card flush className="triage">
        {!todo.length ? <Empty icon="checkCircle" title="Nothing to do">No decisions, alerts or problems are waiting.</Empty> : (
            <Paged rows={todo} size={8}>{(page) => page.map((t) => (<TodoRow key={t.id} tone={t.tone} icon={t.icon} title={t.title}
                onTitle={t.to ? () => nav(t.to) : undefined}
                meta={<>{t.meta}{showBrand && t.brand ? <> · {brands.find((b) => b.id === t.brand)?.short ?? t.brand}</> : null}</>}
                detail={t.detail} tags={<Pill tone={t.tone === 'crit' ? 'crit' : t.tone === 'info' ? 'info' : 'warn'}>{t.tag}</Pill>}
                action={t.to ? <Link className="btn sm dark" href={t.to}>{t.action}</Link> : null}/>))}</Paged>)}
      </Card>

      <SectionHead title="SEO &amp; Blog" note="Content pipeline and blog search clicks."
        action={<Link className="btn sm" href="/articles">Open Articles</Link>}/>
      <div className="ov-hero">
        <RingCard label="Articles live on the storefront" total={live} onTotal={() => nav('/articles?live=1')}
          pill={total ? { tone: 'neutral', label: `${Math.round((live / total) * 100)}% of ${fmtInt(total)} articles live` } : null}
          centerLabel="live"
          segments={CONTENT_STAGES.map((s) => ({ key: s.key, name: s.label, value: n(s.statuses), color: s.color, onClick: () => toArticles(s.statuses) }))}/>
        <MiniGrid>
          <MiniStat label="Waiting for a decision" value={fmtInt(data.approvalsTotal)} tone={data.approvalsTotal ? 'warn' : undefined}
            foot={data.approvalsTotal ? 'Reviews, publish requests, topics' : 'Nothing waiting'} onClick={() => nav('/publishing')}/>
          <MiniStat label="Blog search clicks" value={oneBrand ? fmtCompact(clicks(brand)?.value) : `${fmtCompact(clicks('ridhi')?.value)} / ${fmtCompact(clicks('cpc')?.value)}`}
            foot={oneBrand ? `Search Console, last ${data.window?.days ?? 28} days` : 'Ridhi / CPC, kept separate'} onClick={() => nav('/analytics')}/>
        </MiniGrid>
      </div>

      <Journey label="Article journey" steps={CONTENT_STAGES.map((s) => ({
          key: s.key, label: s.label, value: counts.data ? n(s.statuses) : '…', done: s.key === 'published', onClick: () => toArticles(s.statuses),
          calm: s.key === 'published' ? 'Live on the blog' : 'Nothing stuck',
          flags: s.key === 'drafts' && sentBack ? [{ label: 'sent back', value: sentBack, tone: 'warn', onClick: () => toArticles(['changes_requested']) }]
              : s.key === 'review' && data.approvalsTotal ? [{ label: 'waiting for you', value: data.approvalsTotal, tone: 'info', onClick: () => nav('/publishing') }]
                  : s.key === 'published' && failedPublish ? [{ label: 'failed to publish', value: failedPublish, tone: 'crit', onClick: () => toArticles(['failed']) }] : [],
      }))}/>

      <Card title="Blog search clicks" sub="Daily clicks from Google search to blog pages, by brand" actions={<Link className="btn ghost sm" href="/analytics">Open SEO & traffic</Link>}>
        {data.trend?.length ? <LineChart ariaLabel="Daily blog search clicks by brand" height={230} series={data.trend.map((t) => ({ key: t.brand, label: brands.find((b) => b.id === t.brand)?.name ?? t.brand, color: BRAND_COLOR[t.brand], points: t.points }))}/>
          : <Empty icon="analytics" title="No trend yet">Daily figures appear once Search Console data is available.</Empty>}
      </Card>
      <h2 className="section-title">Report by brand</h2>
      <div className="card flush">
        <div className="table-wrap">
          <table className="t">
            <thead><tr><th>Brand</th><th className="r">Articles</th><th className="r">Live</th><th className="r">Drafts</th><th className="r">Waiting</th><th className="r">Search clicks</th><th className="r">Sessions</th><th className="r">Delivery problems</th><th><span className="sr-only">Open</span></th></tr></thead>
            <tbody>
              {data.articles.map((b) => {
                  const s = data.shipping?.byBrand?.[b.brand];
                  return (<tr key={b.brand}>
                    <td><BrandTag id={b.brand} brands={brands}/> <span className="strong">{brands.find((x) => x.id === b.brand)?.name}</span></td>
                    <td className="r">{fmtInt(b.total)}</td>
                    <td className="r">{fmtInt(b.live)}</td>
                    <td className="r">{fmtInt(b.drafts)}</td>
                    <td className="r">{b.pendingApproval ? <Pill tone="warn">{b.pendingApproval}</Pill> : 0}</td>
                    <td className="r">{fmtInt(clicks(b.brand)?.value)}</td>
                    <td className="r">{fmtInt(sessions(b.brand)?.value)}</td>
                    <td className="r">{s ? (s.problems ? <Pill tone="crit">{s.problems}</Pill> : 0) : '—'}</td>
                    <td className="r"><Link className="btn ghost sm" href="/articles" onClick={() => setBrand(b.brand)}>Open</Link></td>
                  </tr>);
              })}
            </tbody>
          </table>
        </div>
        <div className="card-foot muted xs">Ridhi and CPC are separate businesses and are never added together in this table.</div>
      </div>
      <div className="mt-16">
        <ListCard title="Automation and recent runs" sub="Latest pipeline runs." to="/automation" linkLabel="Open Automation" icon="clock" emptyTitle="No runs recorded" emptyText="Pipeline runs appear here once they exist.">
          {data.jobs.length ? data.jobs.map((j) => (<ListRow key={`job-${j.id}`} icon={runInfo(j.status).icon} tone={runInfo(j.status).tone} title={j.name} brand={j.brand} {...common} meta={`started ${ago(j.startedAt, 'at an unknown time')} · last success: ${ago(j.lastSuccessAt, 'none recorded')}`} trailing={<Pill tone={runInfo(j.status).tone ?? 'neutral'}>{runInfo(j.status).label}</Pill>}/>)) : null}
        </ListCard>
      </div>
    </More>);
}
