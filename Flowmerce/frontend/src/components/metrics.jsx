'use client';
import Link from 'next/link';
import { Delta, SourceBadge } from './ui';
import { Icon } from './Icon';
import { Sparkline } from './charts';
import { CountUp } from './motion';
import { fmtCompact, fmtDate, fmtInt, fmtPct, fmtPos, fmtSeconds, pctChange, timeAgo } from '../lib/format';
export const BRAND_COLOR = { ridhi: 'var(--series-ridhi)', cpc: 'var(--series-cpc)' };
export function Kpi({ label, value, delta, invert, foot, spark, na, icon }) {
    return (<div className="kpi">
      <div className="kpi-label">{icon ? <Icon name={icon} size="sm"/> : null}{label}</div>
      <div className="row" style={{ alignItems: 'flex-end', gap: 10 }}>
        <div className={`kpi-value ${na ? 'na' : ''}`}>{na ? value : <CountUp value={value}/>}</div>
        {spark && spark.length > 2 ? <div className="hide-sm" style={{ flex: 1, minWidth: 0, overflow: 'hidden', display: 'flex', justifyContent: 'flex-end', paddingBottom: 4 }}><Sparkline values={spark} width={72}/></div> : null}
      </div>
      <div className="kpi-foot">{delta !== undefined ? <Delta value={delta} invert={invert}/> : null}{foot}</div>
    </div>);
}
const REASON = {
    paused: 'Paused — outside current integration scope',
    not_set_up: 'Not configured',
    not_synced: 'Connected but never synced',
    syncing: 'First sync still running',
    sync_failed: 'The last sync failed',
    no_rows: 'Synced, but Google returned no rows for this range',
    demo_not_loaded: 'Demo mode is on and no demo data is loaded',
};
/** Why a source has no figures, in plain words. Never implies a zero. */
export function missingReason(source) {
    const base = REASON[source?.state] ?? 'No data for this range';
    return source?.state === 'sync_failed' && source.lastError ? `${base}: ${source.lastError}` : base;
}
/** How fresh a source is: when it last synced, how far its rows reach, and whether they stop short of the range. */
export function Freshness({ source }) {
    if (!source?.kind)
        return null;
    const to = source.coverage?.to;
    return (<span className="muted xs">
      {source.syncedAt ? `Synced ${timeAgo(source.syncedAt)}` : 'Sync time unknown'}
      {to ? ` · data through ${fmtDate(to)}` : ''}
      {source.state === 'partial' ? <b style={{ color: 'var(--warn)' }}> · stops before the end of this range (Google reports with a delay, or the last sync is old)</b> : null}
    </span>);
}
export function MissingBlock({ what, brand, short, source }) {
    const cpc = brand === 'cpc' && source?.state === 'not_set_up';
    return (<div className="callout info">
      <Icon name="info"/>
      <div style={{ minWidth: 0, overflowWrap: 'anywhere' }}>
        <b>{short ? `${short(brand)} · ` : ''}{what}: unavailable{cpc ? ', CPC is not configured' : ''}.</b> {cpc ? 'CPC is outside the current integration scope, so this is not zero performance.' : missingReason(source).replace(/[.\s]+$/, '')}.{' '}
        {source?.state === 'not_set_up' || source?.state === 'not_synced' ? <>Set it up under <Link href="/settings/integrations">Integrations</Link>, or import an export in <Link href="/settings/data">Data import/export</Link>. </> : null}
        Nothing is estimated or filled in.
      </div>
    </div>);
}
const SCOPE_NOTE = 'Blog pages only (URLs containing /blogs/). Site-wide traffic is not collected.';
function BrandBlock({ part, short, many, children }) {
    return (<div className="col gap-8">
      {many ? <div className="row"><span className={`brand-dot ${part.brand}`}/><b className="small">{short(part.brand)}</b><SourceBadge source={part.source}/></div> : null}
      {children}
      <Freshness source={part.source}/>
    </div>);
}
/** One block per brand. Brands are never added together: Ridhi and CPC are separate businesses. */
export function GscKpis({ parts, short }) {
    const many = parts.length > 1;
    return (<div className="col gap-16">
      {parts.map((p) => !p.totals ? <MissingBlock key={p.brand} what="Search Console" brand={p.brand} short={many ? short : undefined} source={p.source}/> : (<BrandBlock key={p.brand} part={p} short={short} many={many}>
          <div className="kpis">
            <Kpi label="Blog organic clicks" value={fmtCompact(p.totals.clicks)} delta={pctChange(p.totals.clicks, p.previous?.clicks)} spark={p.series.map((r) => r.clicks)} foot={<SourceBadge source={p.source} compact/>}/>
            <Kpi label="Blog impressions" value={fmtCompact(p.totals.impressions)} delta={pctChange(p.totals.impressions, p.previous?.impressions)} spark={p.series.map((r) => r.impressions)} foot={<SourceBadge source={p.source} compact/>}/>
            <Kpi label="CTR" value={fmtPct(p.totals.ctr)} na={p.totals.ctr === null} delta={pctChange(p.totals.ctr, p.previous?.ctr)} foot={p.totals.ctr === null ? <span className="faint">no impressions</span> : <SourceBadge source={p.source} compact/>}/>
            <Kpi label="Avg. position" value={fmtPos(p.totals.position)} na={p.totals.position === null} delta={pctChange(p.totals.position, p.previous?.position)} invert foot={<span className="faint">lower is better</span>}/>
          </div>
          <div className="muted xs">{SCOPE_NOTE}</div>
        </BrandBlock>))}
    </div>);
}
export function Ga4Kpis({ parts, short }) {
    const many = parts.length > 1;
    return (<div className="col gap-16">
      {parts.map((p) => !p.totals ? <MissingBlock key={p.brand} what="GA4" brand={p.brand} short={many ? short : undefined} source={p.source}/> : (<BrandBlock key={p.brand} part={p} short={short} many={many}>
          <div className="kpis">
            <Kpi label="Sessions (blog landing)" value={fmtCompact(p.totals.sessions)} delta={pctChange(p.totals.sessions, p.previous?.sessions)} spark={p.series.map((r) => r.sessions)} foot={<SourceBadge source={p.source} compact/>}/>
            <Kpi label="Engagement rate" value={fmtPct(p.totals.engagementRate)} na={p.totals.engagementRate === null} delta={pctChange(p.totals.engagementRate, p.previous?.engagementRate)} foot={p.totals.engagementRate === null ? <span className="faint">no sessions</span> : <SourceBadge source={p.source} compact/>}/>
            <Kpi label="Avg. engagement time" value={fmtSeconds(p.totals.avgEngagementSeconds)} na={p.totals.avgEngagementSeconds === null} delta={pctChange(p.totals.avgEngagementSeconds, p.previous?.avgEngagementSeconds)} foot={<SourceBadge source={p.source} compact/>}/>
            <Kpi label="Key events" value={fmtInt(p.totals.keyEvents)} delta={pctChange(p.totals.keyEvents, p.previous?.keyEvents)} foot={<SourceBadge source={p.source} compact/>}/>
          </div>
          <div className="muted xs">Sessions that landed on blog pages, from any channel. Site-wide sessions are not collected.</div>
        </BrandBlock>))}
    </div>);
}
export function seriesFrom(parts, key, label) {
    return parts.filter((p) => p.series.length).map((p) => ({
        key: p.brand,
        label: label(p.brand) + (p.source.kind === 'demo' ? ' (demo)' : ''),
        color: BRAND_COLOR[p.brand],
        dashed: p.source.kind === 'demo',
        points: p.series.map((r) => ({ x: r.date, y: r[key] ?? null })),
    }));
}
