'use client';
import Link from 'next/link';
import { useApp } from '../lib/app';
import { useHomeData } from '../lib/home';
import { fmtCompact, fmtDate, fmtInt, timeAgo } from '../lib/format';
import { BrandTag, Card, Empty, ErrorState, LoadingBlock, PageHead, Pill } from '../components/ui';
import { Icon } from '../components/Icon';
import { Kpi, BRAND_COLOR } from '../components/metrics';
import { LineChart } from '../components/charts';
import { ListCard, ListRow, brandLabel } from '../components/home';

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

/**
 * Home: the management view. One row of headline numbers across the modules, the trend, what needs a decision,
 * and a per-brand report. Ridhi and CPC are never added together. Every figure comes from GET /api/home (real records).
 */
export default function Home() {
    const { brand, me, setBrand } = useApp();
    const { data, loading, error, reload } = useHomeData(brand);
    const brands = me.brands;
    const showBrand = brand === 'all';
    const common = { brands, showBrand };
    const clicks = (b) => data.metrics.find((m) => m.brand === b && m.key === 'gsc_clicks');
    const sessions = (b) => data.metrics.find((m) => m.brand === b && m.key === 'ga4_sessions');
    const failedJobs = data.jobs.filter((j) => j.status === 'failed' && !j.failedOnlyBecausePaused && !(j.lastSuccessAt && j.lastSuccessAt > (j.finishedAt ?? j.startedAt ?? '')));
    const ship = data.shipping?.all;
    const live = sum(data.articles, 'live');
    const waiting = sum(data.articles, 'pendingApproval');
    const drafts = sum(data.articles, 'drafts');
    const total = sum(data.articles, 'total');
    const oneBrand = brand !== 'all';
    return (<>
      <PageHead title="Home" sub={<>Business overview for {brandLabel(brand, brands)}. Figures cover the last {data.window?.days ?? 28} days unless stated.</>}/>

      <ErrorState error={error} onRetry={reload}/>

      {loading ? <LoadingBlock rows={6}/> : error ? null : (<>
          <div className="kpis">
            <Kpi icon="blogs" label="Articles live" value={fmtInt(live)} foot={<span>{fmtInt(total)} in total · {fmtInt(drafts)} drafts</span>}/>
            <Kpi icon="checkCircle" label="Waiting for a decision" value={fmtInt(data.approvalsTotal)} foot={<Link href="/publishing">Open Publishing <Icon name="arrowRight" size="sm"/></Link>} na={false}/>
            <Kpi icon="analytics" label="Blog search clicks" value={oneBrand ? fmtCompact(clicks(brand)?.value) : `${fmtCompact(clicks('ridhi')?.value)} / ${fmtCompact(clicks('cpc')?.value)}`} foot={<span>{oneBrand ? 'Search Console, blog pages' : 'Ridhi / CPC, kept separate'}</span>} spark={oneBrand ? data.trend?.[0]?.points.map((p) => p.y) : undefined}/>
            <Kpi icon="truck" label="Delivery problems" value={ship ? fmtInt(ship.problems) : '—'} foot={<Link href="/shipping">{ship ? `${fmtInt(ship.inTransit)} in transit · ` : ''}open Shipping <Icon name="arrowRight" size="sm"/></Link>}/>
          </div>
          
          <div className="grid main-side mt-16">
            <Card title="Blog search clicks" sub="Daily clicks from Google search to blog pages, by brand" actions={<Link className="btn ghost sm" href="/analytics">Open SEO & traffic</Link>}>
              {data.trend?.length ? <LineChart ariaLabel="Daily blog search clicks by brand" height={230} series={data.trend.map((t) => ({ key: t.brand, label: brands.find((b) => b.id === t.brand)?.name ?? t.brand, color: BRAND_COLOR[t.brand], points: t.points }))}/>
                : <Empty icon="analytics" title="No trend yet">Daily figures appear once Search Console data is available.</Empty>}
            </Card>
            <Card title="Shipping snapshot" sub={ship?.asOf ? `As of ${fmtDate(ship.asOf)}` : undefined} actions={<Link className="btn ghost sm" href="/shipping">Open Shipping</Link>}>
              {ship ? (<div className="col gap-12">
                  <div className="stat-row">
                    <div className="stat"><div className="v">{fmtInt(ship.active)}</div><div className="l">Parcels on the way</div></div>
                    <div className="stat"><div className="v">{fmtInt(ship.delivered30d)}</div><div className="l">Delivered (30 days)</div></div>
                    <div className={`stat ${ship.problems ? 'warn' : ''}`}><div className="v">{fmtInt(ship.problems)}</div><div className="l">Delivery problems</div></div>
                    <div className="stat"><div className="v">{fmtInt(ship.unverified)}</div><div className="l">No carrier updates</div></div>
                  </div>
                  {ship.top?.length ? (<div className="alert-list">
                      {ship.top.map((s) => (<ListRow key={s.trackingId} icon="truck" tone="warn" title={`${s.order} · ${s.carrier}`} meta={`${s.days ?? '?'} day${s.days === 1 ? '' : 's'} since dispatch${s.place ? ` · last seen ${s.place}` : ''}`} to={`/shipping?tab=shipments&q=${encodeURIComponent(s.order ?? '')}`} brand={s.brand} {...common}/>))}
                    </div>) : <div className="muted small">No open delivery problems.</div>}
                </div>) : <Empty icon="truck" title="Shipping data unavailable">Supabase is not set up or could not be reached. Open Shipping for details.</Empty>}
            </Card>
          </div>

          <div className="grid cols-2 mt-16">
            <ListCard title="Pending approvals" sub={data.approvalsTotal > data.approvals.length ? `Decisions for your role · showing ${data.approvals.length} of ${data.approvalsTotal}` : `Decisions waiting for your role${me.user?.roleLabel ? ` (${me.user.roleLabel})` : ''}`} to="/publishing" linkLabel="Open Publishing" icon="checkCircle" emptyTitle="Nothing waiting for you" emptyText="No review, publishing or topic decisions are waiting for your role.">
              {data.approvals.length ? data.approvals.map((a) => (<ListRow key={a.id} icon="checkCircle" title={a.title} to={a.to} brand={a.brand} {...common} meta={`${a.label} · ${isIso(a.since) ? `waiting ${timeAgo(a.since).replace(' ago', '')}` : a.since}`}/>)) : null}
            </ListCard>
            <ListCard title="Alerts" sub="Unresolved issues, most serious first. Each row opens the page where it can be fixed." icon="alert" emptyTitle="No alerts" emptyText="Nothing needs attention right now.">
              {data.alerts.length ? data.alerts.map((a) => (<ListRow key={a.id} icon="alert" tone={SEVERITY[a.severity]?.tone} title={a.title} to={a.to ?? undefined} {...common} meta={a.detail || 'Open for details'} trailing={<Pill tone={SEVERITY[a.severity]?.tone ?? 'neutral'}>{SEVERITY[a.severity]?.label ?? a.severity}</Pill>}/>)) : null}
            </ListCard>
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
            <ListCard title="Automation and recent runs" sub={failedJobs.length ? `${failedJobs.length} run${failedJobs.length === 1 ? '' : 's'} failed and not fixed since.` : 'Latest pipeline runs.'} to="/automation" linkLabel="Open Automation" icon="clock" emptyTitle="No runs recorded" emptyText="Pipeline runs appear here once they exist.">
              {data.jobs.length ? data.jobs.map((j) => (<ListRow key={`job-${j.id}`} icon={runInfo(j.status).icon} tone={runInfo(j.status).tone} title={j.name} brand={j.brand} {...common} meta={`started ${ago(j.startedAt, 'at an unknown time')} · last success: ${ago(j.lastSuccessAt, 'none recorded')}`} trailing={<Pill tone={runInfo(j.status).tone ?? 'neutral'}>{runInfo(j.status).label}</Pill>}/>)) : null}
            </ListCard>
          </div>
        </>)}
    </>);
}
