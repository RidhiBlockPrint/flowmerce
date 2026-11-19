'use client';
import Link from 'next/link';
import { More } from '../components/More';
import { useApp } from '../lib/app';
import { useNavigate } from '../lib/nav';
import { useApi, qs } from '../lib/api';
import { useHomeData } from '../lib/home';
import { fmtCompact, fmtDate, fmtInt, timeAgo } from '../lib/format';
import { BrandTag, Card, Empty, ErrorState, LoadingBlock, PageHead, Paged, Pill } from '../components/ui';
import { Icon } from '../components/Icon';
import { BRAND_COLOR } from '../components/metrics';
import { LineChart } from '../components/charts';
import { ListCard, ListRow, brandLabel } from '../components/home';
import { Greeting, Journey, MiniGrid, MiniStat, RingCard, SectionHead, TodoRow } from '../components/dash';

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
    { key: 'drafts', label: 'Ideas and drafts', statuses: ['idea', 'draft', 'changes_requested'], color: '#a59d93' },
    { key: 'review', label: 'In review', statuses: ['in_review'], color: 'var(--info)' },
    { key: 'approved', label: 'Approved', statuses: ['approved', 'publish_requested'], color: '#d6a419' },
    { key: 'scheduled', label: 'Scheduled', statuses: ['scheduled'], color: 'var(--saffron)' },
    { key: 'published', label: 'Published', statuses: ['published'], color: 'var(--ok)' },
];

/**
 * Home: the management view across modules. A plain-language headline, the content pipeline, four headline numbers,
 * the article journey and one to-do list (decisions, alerts, failed runs, delivery problems). Ridhi and CPC are never
 * added together where it matters (search clicks, the brand report). Every figure comes from GET /api/home and
 * GET /api/articles/counts (real records).
 */
export default function Home() {
    const { brand, me, setBrand } = useApp();
    const nav = useNavigate();
    const { data, loading, error, reload } = useHomeData(brand);
    const counts = useApi(`/articles/counts${qs({ brand: brand === 'all' ? undefined : brand })}`);
    const brands = me.brands;
    const showBrand = brand === 'all';
    const common = { brands, showBrand };
    const oneBrand = brand !== 'all';
    if (loading || error) {
        return (<>
          <PageHead title="Home" sub={<>{brandLabel(brand, brands)} · last {data?.window?.days ?? 28} days</>}/>
          <ErrorState error={error} onRetry={reload}/>
          {loading ? <LoadingBlock rows={6}/> : null}
        </>);
    }
    const clicks = (b) => data.metrics.find((m) => m.brand === b && m.key === 'gsc_clicks');
    const sessions = (b) => data.metrics.find((m) => m.brand === b && m.key === 'ga4_sessions');
    const failedJobs = data.jobs.filter((j) => j.status === 'failed' && !j.failedOnlyBecausePaused && !(j.lastSuccessAt && j.lastSuccessAt > (j.finishedAt ?? j.startedAt ?? '')));
    const ship = data.shipping?.all;
    const shipNote = data.shipping?.loading ? 'Still loading, open again in a moment' : 'Shipping data unavailable';
    const live = sum(data.articles, 'live');
    const total = sum(data.articles, 'total');
    const critical = data.alerts.filter((a) => a.severity === 'critical').length;
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
            detail: `${s.days ?? '?'} day${s.days === 1 ? '' : 's'} since dispatch${s.place ? `, last seen ${s.place}` : ''}.`, action: 'Open order', tag: 'Shipping' })),
    ];
    const severity = { crit: 0, warn: 1, info: 2 };
    todo.sort((a, b) => (severity[a.tone] ?? 3) - (severity[b.tone] ?? 3));
    const needs = data.approvalsTotal + critical + failedJobs.length + (ship?.problems ?? 0);
    const parts = [
        data.approvalsTotal ? `${fmtInt(data.approvalsTotal)} waiting for your decision` : '',
        critical ? `${fmtInt(critical)} critical alert${critical === 1 ? '' : 's'}` : '',
        failedJobs.length ? `${fmtInt(failedJobs.length)} failed automation run${failedJobs.length === 1 ? '' : 's'}` : '',
        ship?.problems ? `${fmtInt(ship.problems)} delivery problem${ship.problems === 1 ? '' : 's'}` : '',
    ];

    return (<>
      <PageHead title="Home" sub={<>{brandLabel(brand, brands)} · last {data.window?.days ?? 28} days</>}/>
      <Greeting count={needs} parts={parts} calm="Nothing needs you today."
        actions={<><Link className="btn" href="/publishing"><Icon name="publish" size="sm"/>Publishing</Link><Link className="btn" href="/shipping"><Icon name="truck" size="sm"/>Shipping</Link></>}/>

      <div className="ov-hero">
        <RingCard label="Articles live on the storefront" total={live} onTotal={() => nav('/articles?live=1')}
          pill={total ? { tone: 'neutral', label: `${fmtInt(total)} articles in total` } : null}
          center={total ? `${Math.round((live / total) * 100)}%` : '—'} centerLabel="live"
          segments={CONTENT_STAGES.map((s) => ({ key: s.key, name: s.label, value: n(s.statuses), color: s.color, onClick: () => toArticles(s.statuses) }))}/>
        <MiniGrid>
          <MiniStat label="Waiting for a decision" value={fmtInt(data.approvalsTotal)} tone={data.approvalsTotal ? 'warn' : undefined}
            foot={data.approvalsTotal ? 'Reviews, publish requests, topics' : 'Nothing waiting'} onClick={() => nav('/publishing')}/>
          <MiniStat label="Blog search clicks" value={oneBrand ? fmtCompact(clicks(brand)?.value) : `${fmtCompact(clicks('ridhi')?.value)} / ${fmtCompact(clicks('cpc')?.value)}`}
            foot={oneBrand ? `Search Console, last ${data.window?.days ?? 28} days` : 'Ridhi / CPC, kept separate'} onClick={() => nav('/analytics')}/>
          <MiniStat label="Delivery problems" value={ship ? fmtInt(ship.problems) : '—'} tone={ship?.problems ? 'crit' : undefined}
            foot={ship ? `${fmtInt(ship.unverified)} with no carrier updates` : shipNote} onClick={() => nav('/shipping')}/>
          <MiniStat label="Parcels on the way" value={ship ? fmtInt(ship.active) : '—'}
            foot={ship ? `${fmtInt(ship.delivered30d)} delivered in 30 days` : shipNote} onClick={() => nav('/shipping')}/>
        </MiniGrid>
      </div>

      <Journey label="Article journey" steps={CONTENT_STAGES.map((s) => ({
          key: s.key, label: s.label, value: counts.data ? n(s.statuses) : '…', done: s.key === 'published', onClick: () => toArticles(s.statuses),
          calm: s.key === 'published' ? 'Live on the blog' : 'Nothing stuck',
          flags: s.key === 'drafts' && sentBack ? [{ label: 'sent back', value: sentBack, tone: 'warn', onClick: () => toArticles(['changes_requested']) }]
              : s.key === 'review' && data.approvalsTotal ? [{ label: 'waiting for you', value: data.approvalsTotal, tone: 'info', onClick: () => nav('/publishing') }]
                  : s.key === 'published' && failedPublish ? [{ label: 'failed to publish', value: failedPublish, tone: 'crit', onClick: () => toArticles(['failed']) }] : [],
      }))}/>

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

      <More id="home" label="Show trends, shipping and the brand report">
        <div className="grid main-side">
          <Card title="Blog search clicks" sub="Daily clicks from Google search to blog pages, by brand" actions={<Link className="btn ghost sm" href="/analytics">Open SEO & traffic</Link>}>
            {data.trend?.length ? <LineChart ariaLabel="Daily blog search clicks by brand" height={230} series={data.trend.map((t) => ({ key: t.brand, label: brands.find((b) => b.id === t.brand)?.name ?? t.brand, color: BRAND_COLOR[t.brand], points: t.points }))}/>
              : <Empty icon="analytics" title="No trend yet">Daily figures appear once Search Console data is available.</Empty>}
          </Card>
          <Card title="Shipping snapshot" sub={ship?.asOf ? `As of ${fmtDate(ship.asOf)}` : undefined} actions={<Link className="btn ghost sm" href="/shipping">Open Shipping</Link>}>
            {ship ? (<div className="stat-row">
                <div className="stat"><div className="v">{fmtInt(ship.active)}</div><div className="l">Parcels on the way</div></div>
                <div className="stat"><div className="v">{fmtInt(ship.delivered30d)}</div><div className="l">Delivered (30 days)</div></div>
                <div className={`stat ${ship.problems ? 'warn' : ''}`}><div className="v">{fmtInt(ship.problems)}</div><div className="l">Delivery problems</div></div>
                <div className="stat"><div className="v">{fmtInt(ship.unverified)}</div><div className="l">No carrier updates</div></div>
              </div>) : <Empty icon="truck" title={shipNote}>{data.shipping?.loading ? 'Shipping figures are being read and will show here shortly.' : 'Supabase is not set up or could not be reached. Open Shipping for details.'}</Empty>}
          </Card>
        </div>
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
      </More>
    </>);
}
