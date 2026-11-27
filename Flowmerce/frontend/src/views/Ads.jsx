'use client';
/* Ads: Meta Ads and Google Ads next to the store's own sales, for one brand at a time (docs/plans/ads-module.md).
 * Every figure comes from /api/ads/...; this page only lays it out. Phase 1: the screens exist and run on sample
 * numbers in the preview copy; on live data the page says Ads is not connected yet.
 * The brand, platform (All / Meta / Google), tab, date range and comparison are kept in the address, so a link opens
 * the same view. Read-only: nothing here changes an ad account. */
import { Fragment, useEffect, useState } from 'react';
import { api, qs, useApi } from '../lib/api';
import { useBrandParam } from '../lib/app';
import { useSearchParams } from '../lib/nav';
import { tabLabel } from '../lib/routes.mjs';
import { fmtDate, fmtDateTime, fmtDay, fmtInt, timeAgo } from '../lib/format';
import {
    ACTION_GROUPS, ACTION_STATUS, AD_STATUS, BRANDS, CAMPAIGN_TYPES, DEFAULT_RANGE, PLATFORMS, PLATFORM_LABEL, RULE_GROUPS, TABS, VERDICTS, VERDICT_ORDER,
    changeOf, filterAds, filterCampaigns, pct1, platformFor, ratioTone, usd, x2,
} from '../lib/ads';
import { effectiveCompare, isRangeKey, presetRange, todayIn } from '../lib/cro';
import { LineChart } from '../components/charts';
import { Seg } from '../components/cro';
import {
    AdStatus, AdsError, AdsGate, AdsKpi, AdsRangeBar, DropOff, FunnelSteps, GapPill, Pick, PlatformTag, Ratio, SearchBox, Tag,
    VerdictPill, useSort,
} from '../components/ads';
import { AdsDayStrip, BrandCard, ChangeChip, GoalCard, KpiTile, MiniStats, TodayPlan } from '../components/adsOverview';
import { BRAND_COLOR } from '../components/metrics';
import { Icon } from '../components/Icon';
import { useToast } from '../components/overlays';
import { Button, Card, PageHead, Paged, Pill } from '../components/ui';

const isDay = (v) => /^\d{4}-\d{2}-\d{2}$/.test(v ?? '');
const BOTH_BRANDS = [{ key: 'all', label: 'Both' }, ...BRANDS];
const SERIES = { sales: 'var(--accent)', spend: 'var(--ink-2)', mer: 'var(--info)' };
const STATUS_OPTIONS = [{ key: 'active', label: 'Active' }, { key: 'off', label: 'Paused' }];
const GROUP_KIND = { ad_set: 'ad set', ad_group: 'ad group', asset_group: 'asset group' };
const Note = ({ children }) => <div className="muted small" style={{ padding: '10px 16px' }}>{children}</div>;
/** A name column no wider than `max` px: real ad and campaign names are long, so they end in "…" and show in
 *  full on hover instead of pushing the table wider than its card. */
const nameCell = (max) => ({ maxWidth: max, minWidth: Math.min(180, max) });
/** "Video, 24 s, watched 6 s on average", leaving out what Meta did not give (length needs more than ads_read). */
function videoLine(v) {
    const parts = ['Video'];
    if (v.length_s !== null && v.length_s !== undefined) parts.push(`${Math.round(v.length_s)} s`);
    if (v.avg_watch_s !== null && v.avg_watch_s !== undefined) parts.push(`watched ${v.avg_watch_s} s on average`);
    return parts.join(', ');
}

export default function Ads() {
    const [sp, setSp] = useSearchParams();
    const globalBrand = useBrandParam();
    const tab = TABS.some((t) => t.key === sp.get('tab')) ? sp.get('tab') : 'overview';
    const store = BRANDS.some((b) => b.key === sp.get('store')) ? sp.get('store') : null;
    const brand = globalBrand ?? store ?? 'ridhi';
    // Top bar on All: the Overview shows both brands together (the company view) until a brand is picked here; the
    // other tabs are one brand at a time (Ridhi unless CPC is picked).
    const company = !globalBrand && !store && tab === 'overview';
    const tabDef = TABS.find((t) => t.key === tab);
    const platform = platformFor(tab, sp.get('platform'));
    const settings = useApi(`/ads/settings${qs({ brand })}`);
    // The ad account's own "today" decides what "Yesterday" means. The account's known zone is used until settings answers.
    const today = settings.data?.today ?? todayIn(BRANDS.find((b) => b.key === brand)?.tz);
    const update = (patch) => {
        const next = new URLSearchParams(sp);
        for (const [k, v] of Object.entries({ platform: platform === 'all' ? null : platform, ...patch })) {
            if (v === null || v === '' || v === undefined) next.delete(k);
            else next.set(k, v);
        }
        setSp(next, { replace: true });
    };
    const rKey = sp.get('r') === 'custom' ? (isDay(sp.get('from')) && isDay(sp.get('to')) ? 'custom' : DEFAULT_RANGE) : isRangeKey(sp.get('r')) ? sp.get('r') : DEFAULT_RANGE;
    const fixed = rKey === 'custom' ? { from: sp.get('from'), to: sp.get('to') } : presetRange(rKey, today);
    const cfrom = isDay(sp.get('cfrom')) ? sp.get('cfrom') : null;
    const range = { r: rKey, ...fixed, cmp: effectiveCompare(sp.get('cmp') || 'previous', fixed.from, fixed.to, cfrom), cfrom };
    // From the date picker ({ r, from, to }; a moving pick keeps only its key) or the comparison menu ({ cmp, cfrom }).
    // The chosen comparison stays when the dates change, as in Shopify.
    const setRange = (patch) => {
        if ('cmp' in patch) update({ cmp: patch.cmp === 'previous' ? null : patch.cmp, cfrom: patch.cmp === 'custom' ? patch.cfrom : null });
        else if (patch.r && patch.r !== 'custom') update({ r: patch.r === DEFAULT_RANGE ? null : patch.r, from: null, to: null });
        else update({ r: 'custom', from: patch.from, to: patch.to });
    };
    const rq = { brand, platform: tabDef.only ?? platform, from: range.from, to: range.to, compare: range.cmp, cfrom: range.cmp === 'custom' ? range.cfrom : undefined };
    const lines = settings.data?.product_lines ?? [];
    const goTab = (t, extra = {}) => update({ tab: t === 'overview' ? null : t, campaign: null, ...extra });
    // Choosing the other platform on a one-platform tab goes back to the Overview, where both exist.
    const setPlatform = (p) => update({ platform: p === 'all' ? null : p, ...(tabDef.only && p !== 'all' && p !== tabDef.only ? { tab: null, campaign: null } : {}) });
    return (<>
      <PageHead title={tab === 'overview' ? 'Ads' : tabLabel('/ads', tab)} crumbs={tab === 'overview' ? null : 'Ads'}
        sub={company ? 'Both brands together: their Meta and Google ad spend next to both stores’ own sales. Nothing here changes an ad account.'
            : 'Meta and Google Ads next to the store’s own sales. One brand at a time; nothing here changes an ad account.'}
        actions={<>
          {globalBrand ? null : <Seg label="Brand" size="" options={tab === 'overview' ? BOTH_BRANDS : BRANDS} value={company ? 'all' : brand}
            onChange={(b) => update({ store: b === 'all' ? null : b, campaign: null })}/>}
          {company ? null : <Seg label="Platform" size="" options={PLATFORMS} value={platform} onChange={setPlatform}/>}
        </>}/>
      {settings.error ? <AdsError error={settings.error} onRetry={settings.reload}/> : (<>
        <div className="mt-16 col" style={{ gap: 16 }} key={company ? 'company' : brand}>
          {company ? null : <AccountsLine settings={settings.data} platform={rq.platform}/>}
          {tabDef.range ? <AdsRangeBar key={`${range.from}-${range.to}`} value={range} today={today} onChange={setRange} compare={tab !== 'search'}/> : null}
          {tab === 'campaigns' ? <CampaignsTab rq={rq} lines={lines} onAds={(id) => goTab('creatives', { campaign: id })}/>
              : tab === 'creatives' ? <CreativesTab rq={rq} lines={lines} campaign={sp.get('campaign')} onCampaign={(id) => update({ campaign: id })}/>
              : tab === 'funnel' ? <FunnelTab rq={rq}/>
              : tab === 'search' ? <SearchTab rq={rq}/>
              : tab === 'gap' ? <GapTab brand={brand}/>
              : tab === 'actions' ? <ActionsTab brand={brand} platform={platform}/>
              : tab === 'rules' ? <RulesTab brand={brand} onSaved={settings.reload}/>
              : company ? <CompanyOverview rq={rq} onOpen={(b) => update({ store: b })}/>
              : <OverviewTab rq={rq} onTab={goTab} onPickDay={(day) => setRange({ r: 'custom', from: day, to: day })}/>}
        </div>
      </>)}
    </>);
}

/* ------------------------------------------------------------------ Both brands (top bar on All) */
/**
 * The company view for directors: both brands' ad spend (Meta and Google) against both stores' sales, company MER and
 * cost per order with their change and 14-day trend; one card per brand with its own spend call (open it to act); and
 * the days, with each brand's MER. Platform-claimed sales are never added across brands or platforms.
 */
function CompanyOverview({ rq, onOpen }) {
    const q = useApi(`/ads/company${qs({ from: rq.from, to: rq.to, compare: rq.compare, cfrom: rq.cfrom })}`);
    return (<AdsGate query={q} rows={8}>
      {(d) => {
          const m = d.metrics;
          const last14 = d.trend.slice(-14);
          const spark = (field) => last14.map((r) => r[field]);
          const ready = d.brands.filter((b) => b.ready);
          return (<>
            <div className="ads-kpi-row">
              <KpiTile label="Company ad spend" block={m.spend} format={usd} good="none" spark={spark('spend')} sparkColor="var(--ink-2)"
                help="Meta and Google ad spend of both brands in these days, in dollars."/>
              <KpiTile label="Store sales" block={m.sales_ex_bulk} format={usd} spark={spark('sales_ex_bulk')}
                help="Both stores' orders as placed, bulk orders left out (as in MER)."/>
              <KpiTile label="Company MER" block={m.mer_ex_bulk} format={x2} spark={spark('mer_ex_bulk')} sparkColor="var(--info)"
                help="Both stores' sales for every $1 of both brands' ad spend, bulk orders left out."/>
              <KpiTile label="Ad cost per order" block={m.cost_per_order} format={(v) => usd(v, 2)} good="down"
                help="All ad spend divided by all store orders of both brands."/>
            </div>
            <div className="grid cols-2">
              {d.brands.map((b) => <BrandCard key={b.brand} b={b} onOpen={() => onOpen(b.brand)}/>)}
            </div>
            <section className="card ov-card" aria-label="Both brands by day">
              <div className="grid cols-2">
                <div><div className="muted small mb-8">Store sales and ad spend a day, both brands</div>
                  <LineChart ariaLabel="Both brands' store sales and ad spend by day" height={200} yFormat={usd} area
                    series={[{ key: 'sales', label: 'Store sales', color: SERIES.sales, points: d.trend.map((r) => ({ x: r.date, y: r.sales_ex_bulk })) },
                        { key: 'spend', label: 'Ad spend', color: SERIES.spend, dashed: true, points: d.trend.map((r) => ({ x: r.date, y: r.spend })) }]}/></div>
                <div><div className="muted small mb-8">MER a day, by brand</div>
                  <LineChart ariaLabel="Each brand's MER by day" height={200} yFormat={x2}
                    series={ready.map((b) => ({ key: b.brand, label: b.label, color: BRAND_COLOR[b.brand] ?? 'var(--accent)',
                        points: d.trend.map((r) => ({ x: r.date, y: r[`${b.brand}_mer_ex_bulk`] ?? null })) }))}/></div>
              </div>
              <div className="muted xs mt-8">{d.notes.join(' ')}</div>
            </section>
          </>);
      }}
    </AdsGate>);
}

/** Which ad accounts the figures come from, their currency, and when each was last read. */
function AccountsLine({ settings, platform }) {
    if (!settings) return null;
    const shown = settings.accounts.filter((a) => platform === 'all' || a.platform === platform);
    return (<div className="row-wrap">
      {shown.map((a) => (<span key={a.platform} className="cro-ctx">
        <b>{PLATFORM_LABEL[a.platform]}</b> <span className="muted">· {a.name} · {a.currency}{a.converted_at ? ` shown in $ at Rs ${a.converted_at}` : ''} · read {timeAgo(a.last_read_at)}</span>
        {a.token_days_left !== null && a.token_days_left <= 14 ? <span style={{ color: 'var(--crit)', fontWeight: 650 }}> · sign-in expires in {a.token_days_left} days</span> : null}
      </span>))}
    </div>);
}

/* ------------------------------------------------------------------ Overview */
/**
 * The Overview for directors and heads of department (owner request 2026-11-24): today's plan first (the spend call in
 * plain words and the top suggestions), then the four headline figures with their change and 14-day trend, four
 * smaller ones, the daily sales goal (editable), the platforms, and the last 14 days. Definitions are in tooltips.
 */
function OverviewTab({ rq, onPickDay, onTab }) {
    const q = useApi(`/ads/overview${qs(rq)}`);
    const acts = useApi(`/ads/actions${qs({ brand: rq.brand, platform: rq.platform })}`);
    const toast = useToast();
    const saveGoal = async (n) => {
        try {
            await api.patch(`/ads/rules${qs({ brand: rq.brand })}`, { goal_daily_sales: n });
            toast.ok(`Daily sales goal set to ${usd(n)}.`);
            q.reload();
        } catch (e) {
            toast.error(e);
            throw e;
        }
    };
    return (<AdsGate query={q} rows={8}>
      {(d) => {
          const m = d.metrics;
          const one = d.platform !== 'all';
          const meta = d.platforms.find((p) => p.platform === 'meta');
          const last14 = d.trend.slice(-14);
          const spark = (field) => last14.map((r) => r[field]);
          const incomplete = d.meta_saved_to && d.meta_saved_to < d.to
              ? `Meta figures are saved up to ${fmtDate(d.meta_saved_to)} only: the days after show store sales without their ad spend, so MER and this plan are not reliable until the next read.`
              : null;
          const roas = one ? m.roas : { value: meta?.roas ?? null, baseline_value: meta?.prev_roas ?? null, change_pct: changeOf(meta?.roas, meta?.prev_roas) };
          const vs = d.compare ? `vs ${d.compare.label}` : null;
          return (<>
            <TodayPlan gate={d.gate} lines={d.gate_lines} targets={d.targets} actions={acts.data} onAllActions={() => onTab('actions')} warning={incomplete}/>
            <div className="ads-kpi-row">
              <KpiTile label={one ? `${PLATFORM_LABEL[d.platform]} ad spend` : 'Ad spend'} block={m.spend} format={usd} good="none" spark={spark('spend')} sparkColor="var(--ink-2)"
                help={`Total ad spend in these days${one ? '' : ' (Meta + Google)'}, ${vs ?? ''}.`}/>
              <KpiTile label="Store sales" block={m.sales} format={usd} spark={spark('sales_ex_bulk')}
                help={`Orders as placed in the store, all channels${d.bulk.orders ? `; includes ${d.bulk.orders} bulk order${d.bulk.orders === 1 ? '' : 's'} (${usd(d.bulk.amount)})` : ''}.`}/>
              <KpiTile label="MER" block={m.mer_ex_bulk} format={x2} spark={spark('mer_ex_bulk')} sparkColor="var(--info)" tone={ratioTone(m.mer_ex_bulk.value, d.targets.mer_floor)}
                help={`Store sales for every $1 of all ad spend, bulk orders left out. Target ${x2(d.targets.mer)}.`}/>
              <KpiTile label={one ? `${PLATFORM_LABEL[d.platform]} ROAS` : 'Meta ROAS'} block={roas} format={x2} spark={spark(d.platform === 'google' ? 'google_roas' : 'meta_roas')}
                sparkColor="var(--info)" tone={d.platform === 'google' ? undefined : ratioTone(roas.value, d.targets.roas)}
                help={`Sales the platform claims for every $1 spent on it. Target ${x2(d.targets.roas)}. Platforms can claim the same order, so this is higher than MER.`}/>
            </div>
            <MiniStats items={[
                { label: 'Store orders', block: m.orders, format: fmtInt, help: 'All store orders in these days.' },
                { label: 'Average order', block: m.aov, format: (v) => usd(v, 2), help: 'Store sales per order, bulk orders left out.' },
                { label: 'Ad cost per order', block: m.cost_per_order, format: (v) => usd(v, 2), good: 'down', help: 'All ad spend divided by all store orders: each order counted once.' },
                one ? { label: `${PLATFORM_LABEL[d.platform]} purchases`, block: m.purchases, format: fmtInt, help: 'Purchases the platform claims.' }
                    : { label: 'Meta purchases', block: { value: meta?.purchases ?? null }, format: fmtInt, help: 'Purchases Meta claims.' },
            ]}/>
            <div className="grid ads-pair">
              <GoalCard goal={d.goal} days={d.trend.filter((r) => r.date <= d.to).slice(-7)} onSave={saveGoal}/>
              <section className="card ov-card" aria-labelledby="ads-platforms">
                <div className="ov-card-head"><h2 id="ads-platforms" className="serif ov-serif">Meta and Google</h2><span className="muted xs">{vs}</span></div>
                <div className="col" style={{ gap: 12 }}>
                  {d.platforms.map((p) => (<div key={p.platform} className="ads-plat">
                    <div className="row" style={{ justifyContent: 'space-between' }}>
                      <span className="row" style={{ gap: 8 }}><PlatformTag platform={p.platform}/><span className="muted small ellipsis">{p.account}</span></span>
                      <span className="ads-plat-share">{p.share_of_spend === null ? '' : `${Math.round(p.share_of_spend)}% of spend`}</span>
                    </div>
                    {p.spend === null ? <div className="muted small">Google Ads is the next build step.</div> : (<>
                      <div className="ads-goal-bar" aria-hidden="true"><span style={{ width: `${p.share_of_spend ?? 0}%`, background: p.platform === 'meta' ? 'var(--info)' : 'var(--saffron)' }}/></div>
                      <div className="ads-plat-figs">
                        <div><span>Spend</span><b>{usd(p.spend)}</b></div>
                        <div><span>Purchases</span><b>{fmtInt(p.purchases)}</b></div>
                        <div><span>ROAS</span><b><Ratio value={p.roas} target={p.platform === 'meta' ? d.targets.roas : null}/></b> <ChangeChip value={changeOf(p.roas, p.prev_roas)}/></div>
                        <div><span>Cost per purchase</span><b>{usd(p.cpa, 2)}</b></div>
                      </div>
                    </>)}
                  </div>))}
                  <div className="muted xs" title={d.notes.join(' ')}><Icon name="info" size="sm"/> Each platform counts the sales it claims; the store&rsquo;s own sales are the total.</div>
                </div>
              </section>
            </div>
            <section className="card ov-card" aria-label="The last 14 days">
              <AdsDayStrip days={last14} onPick={onPickDay}/>
              <div className="grid cols-2 mt-16">
                <div><div className="muted small mb-8">Store sales and ad spend a day</div>
                  <LineChart ariaLabel="Store sales and ad spend by day" height={200} yFormat={usd} area
                    series={[{ key: 'sales', label: 'Store sales', color: SERIES.sales, points: d.trend.map((r) => ({ x: r.date, y: r.sales_ex_bulk })) },
                        { key: 'spend', label: 'Ad spend', color: SERIES.spend, dashed: true, points: d.trend.map((r) => ({ x: r.date, y: r.spend })) }]}/></div>
                <div><div className="muted small mb-8">MER a day, against the target</div>
                  <LineChart ariaLabel="MER by day" height={200} yFormat={x2} refLine={{ y: d.targets.mer, label: `Target ${x2(d.targets.mer)}` }} extremes="high"
                    series={[{ key: 'mer', label: 'MER', color: SERIES.mer, points: d.trend.map((r) => ({ x: r.date, y: r.mer_ex_bulk })) }]}/></div>
              </div>
            </section>
          </>);
      }}
    </AdsGate>);
}

/* ------------------------------------------------------------------ Campaigns */
function CampaignsTab({ rq, lines, onAds }) {
    const q = useApi(`/ads/campaigns${qs(rq)}`);
    const [f, setF] = useState({ q: '', type: null, line: null, status: null });
    const set = (patch) => setF((old) => ({ ...old, ...patch }));
    return (<AdsGate query={q}>
      {(d) => {
          const cbos = d.campaigns.filter((c) => c.health);
          const types = CAMPAIGN_TYPES.filter((t) => d.campaigns.some((c) => c.type === t.key));
          const shown = filterCampaigns(d.campaigns, f);
          return (<>
            {cbos.length ? (<Card title="CBO health" sub="Each scaling campaign: how many ads are delivering, how much of the spend one ad takes, and what the budget rule says." flush>
              <div className="table-wrap"><table className="t">
                <thead><tr><th>Campaign</th><th className="r">Budget a day</th><th className="r">Delivering ads</th><th className="r">Top ad&rsquo;s share</th><th className="r">7-day ROAS</th><th className="r">3-day ROAS</th><th>Budget call</th></tr></thead>
                <tbody>{cbos.map((c) => {
                    const h = c.health;
                    const few = h.delivering_ads < h.min_ads, many = h.delivering_ads > h.max_ads;
                    return (<tr key={c.id}>
                      <td className="title-cell" style={nameCell(380)}><span className="ttl" title={c.name}>{c.name}</span></td>
                      <td className="r">{usd(c.daily_budget)}</td>
                      <td className="r" title={`The rule keeps ${h.min_ads} to ${h.max_ads} delivering ads in a CBO`}><b style={{ color: few || many ? 'var(--warn)' : undefined }}>{h.delivering_ads}</b>
                        <span className="muted xs"> {few ? 'add ads' : many ? 'too many' : `of ${h.min_ads}–${h.max_ads}`}</span></td>
                      <td className="r" title="Share of the last 7 days' spend"><b style={{ color: h.top_ad_share >= 60 ? 'var(--warn)' : undefined }}>{h.top_ad_share === null ? '—' : `${h.top_ad_share}%`}</b> <span className="muted xs">{h.top_ad}</span></td>
                      <td className="r"><Ratio value={c.roas_7d} target={d.targets.roas} strong/></td>
                      <td className="r"><Ratio value={c.roas_3d} target={d.targets.roas}/></td>
                      <td><Pill tone={h.call.key === 'increase' ? 'ok' : h.call.key === 'decrease' ? 'crit' : 'neutral'}>{h.call.label}{h.call.new_budget ? ` → ${usd(h.call.new_budget)}` : ''}</Pill>
                        <div className="muted xs mt-4">{h.call.why}</div></td>
                    </tr>);
                })}</tbody>
              </table></div>
            </Card>) : null}
            <Card title="All campaigns" sub={`${fmtDate(d.from)} – ${fmtDate(d.to)}. Click a campaign to see its ${d.platform === 'google' ? 'ad groups and asset groups' : d.platform === 'meta' ? 'ad sets' : 'ad sets or groups'}.`} flush>
              <div className="toolbar" style={{ padding: '12px 16px 0' }}>
                <SearchBox value={f.q} onChange={(v) => set({ q: v })} placeholder="Search campaigns"/>
                <Pick label="Type" value={f.type} onChange={(v) => set({ type: v })} options={types}/>
                <Pick label="Product" value={f.line} onChange={(v) => set({ line: v })} options={lines}/>
                <Pick label="Status" value={f.status} onChange={(v) => set({ status: v })} options={STATUS_OPTIONS}/>
                <span className="spacer"/><span className="muted small num">{shown.length} of {d.campaigns.length}</span>
              </div>
              {shown.length ? <CampaignTable campaigns={shown} target={d.targets.roas} lines={lines} onAds={onAds} resetKey={JSON.stringify(f)}/> : <Note>No campaign matches these filters.</Note>}
            </Card>
          </>);
      }}
    </AdsGate>);
}

function CampaignTable({ campaigns, target, lines, onAds, resetKey }) {
    const { rows, th } = useSort(campaigns, 'spend');
    const [open, setOpen] = useState(null);
    const line = (key) => lines.find((l) => l.key === key)?.label ?? key;
    return (<Paged rows={rows} size={12} resetKey={resetKey}>
      {(page) => (<div className="table-wrap"><table className="t">
        <thead><tr>{th('name', 'Campaign', { right: false })}<th>Status</th>{th('daily_budget', 'Budget a day')}{th('spend', 'Spend')}{th('purchases', 'Purchases')}{th('roas', 'ROAS')}
          {th('roas_3d', '3-day ROAS', { className: 'hide-sm' })}{th('prev_roas', 'Before', { className: 'hide-sm', title: 'ROAS in the period before' })}{th('cpa', 'CPA')}{th('ctr', 'CTR', { className: 'hide-sm' })}</tr></thead>
        <tbody>{page.map((c) => (<Fragment key={c.id}>
          <tr className="clickable" onClick={() => setOpen(open === c.id ? null : c.id)} aria-expanded={open === c.id}>
            <td className="title-cell" style={nameCell(380)}><span className="ttl" title={c.name}><Icon name={open === c.id ? 'chevronDown' : 'chevronRight'} size="sm"/> {c.name}</span>
              <span className="row-wrap mt-4" style={{ gap: 4 }}><PlatformTag platform={c.platform}/><Tag>{c.type_label}</Tag><Tag>{line(c.product_line)}</Tag>
                {c.is_brand ? <Tag title="People searching for the brand by name. Its ROAS is not comparable with other campaigns.">Brand search</Tag> : null}</span></td>
            <td><AdStatus status={c.status}/></td>
            <td className="r">{c.daily_budget === null ? <span className="muted xs">per ad set</span> : usd(c.daily_budget)}</td>
            <td className="r">{usd(c.spend)}</td><td className="r">{fmtInt(c.purchases)}</td>
            <td className="r"><Ratio value={c.roas} target={c.is_brand ? null : target} strong/></td>
            <td className="r hide-sm"><Ratio value={c.roas_3d} target={c.is_brand ? null : target}/></td>
            <td className="r hide-sm muted">{x2(c.prev_roas)}</td><td className="r">{usd(c.cpa, 2)}</td><td className="r hide-sm">{pct1(c.ctr)}</td>
          </tr>
          {open === c.id ? (c.groups.length ? (<>
            {c.groups.map((g) => (<tr key={g.name} style={{ background: 'var(--surface-2)' }}>
              <td style={{ paddingLeft: 36 }}><span className="small">{g.name}</span> <span className="muted xs">· {GROUP_KIND[g.kind] ?? 'group'}{g.ads === null ? '' : ` · ${g.active_ads} of ${g.ads} ads active`}</span></td>
              <td/><td/><td className="r">{usd(g.spend)}</td><td className="r">{fmtInt(g.purchases)}</td><td className="r"><Ratio value={g.roas} target={target}/></td><td className="hide-sm"/><td className="hide-sm"/><td/><td className="hide-sm"/>
            </tr>))}
            {c.platform === 'meta' ? (<tr style={{ background: 'var(--surface-2)' }}><td colSpan={10} style={{ paddingLeft: 36 }}>
              <Button size="sm" variant="ghost" onClick={(e) => { e.stopPropagation(); onAds(c.id); }}>See this campaign&rsquo;s {c.ads} ads <Icon name="arrowRight" size="sm"/></Button></td></tr>) : null}
          </>) : (<tr style={{ background: 'var(--surface-2)' }}><td colSpan={10} style={{ paddingLeft: 36 }} className="muted small">
            {c.platform === 'google' ? 'No ad groups or asset groups with spend in these days.' : 'No ad sets with spend in these days.'}</td></tr>)) : null}
        </Fragment>))}</tbody>
      </table></div>)}
    </Paged>);
}

/* ------------------------------------------------------------------ Creatives (Meta) */
const VIEWS = [{ key: 'all', label: 'All ads' }, { key: 'new', label: 'New, under 7 days' }, { key: 'tests', label: 'In test' }, { key: 'winners', label: 'Winners bench' }];
const FORMATS = [{ key: 'video', label: 'Video' }, { key: 'image', label: 'Image' }];

function CreativesTab({ rq, lines, campaign, onCampaign }) {
    const q = useApi(`/ads/creatives${qs({ brand: rq.brand, from: rq.from, to: rq.to, compare: rq.compare, cfrom: rq.cfrom })}`);
    const [f, setF] = useState({ q: '', view: 'all', verdict: null, line: null, format: null, status: null, minSpend: '' });
    const set = (patch) => setF((old) => ({ ...old, ...patch }));
    return (<AdsGate query={q}>
      {(d) => {
          const filters = { ...f, campaign };
          const campaigns = [...new Map(d.ads.map((a) => [a.campaign_id, { key: a.campaign_id, label: a.campaign }])).values()];
          const shown = filterAds(d.ads, filters, d.winners);
          // The chips count the ads every other filter leaves, so a number always matches what clicking it shows.
          const base = filterAds(d.ads, { ...filters, verdict: null }, d.winners);
          return (<>
            <Card title="Verdicts" sub={`What the rule set says about each ad. Test spend ${usd(d.targets.test_spend)}, proven from ${usd(d.targets.proven_spend)} lifetime, ROAS target ${x2(d.targets.roas)}.`}>
              <div className="row-wrap">
                <button type="button" className="chip" aria-pressed={!f.verdict} onClick={() => set({ verdict: null })}>All <span className="n">{base.length}</span></button>
                {VERDICT_ORDER.map((v) => (<button key={v} type="button" className="chip" aria-pressed={f.verdict === v} title={VERDICTS[v].help} onClick={() => set({ verdict: f.verdict === v ? null : v })}>
                  {VERDICTS[v].label} <span className="n">{base.filter((a) => a.verdict === v).length}</span></button>))}
              </div>
              <div className="muted small mt-12">Account average in these days: ROAS {x2(d.account.roas)} · CTR {pct1(d.account.ctr)} · add-to-cart {pct1(d.account.atc_rate)} of page views · hook {pct1(d.account.hook_rate)} · CPA {usd(d.account.cpa, 2)}</div>
            </Card>
            <Card title="Ads" sub={`${fmtDate(d.from)} – ${fmtDate(d.to)}. Click an ad for the reason behind its verdict and how it compares with the account.`} flush>
              <div className="toolbar" style={{ padding: '12px 16px 0' }}>
                <Seg label="Which ads" options={VIEWS} value={f.view} onChange={(v) => set({ view: v })}/>
                <SearchBox value={f.q} onChange={(v) => set({ q: v })} placeholder="Search by name, code or ad ID"/>
              </div>
              <div className="toolbar" style={{ padding: '0 16px' }}>
                <Pick label="Campaign" value={campaign} onChange={onCampaign} options={campaigns}/>
                <Pick label="Product" value={f.line} onChange={(v) => set({ line: v })} options={lines}/>
                <Pick label="Format" value={f.format} onChange={(v) => set({ format: v })} options={FORMATS}/>
                <Pick label="Status" value={f.status} onChange={(v) => set({ status: v })} options={STATUS_OPTIONS}/>
                <label className="row small" style={{ gap: 6 }}><span className="muted nowrap">Spend at least $</span>
                  <input className="input sm" type="number" min="0" step="10" value={f.minSpend} onChange={(e) => set({ minSpend: e.target.value })} style={{ width: 84 }} aria-label="Minimum spend"/></label>
                <span className="spacer"/><span className="muted small num">{shown.length} of {d.ads.length} ads</span>
              </div>
              {shown.length ? <AdsTable ads={shown} d={d} resetKey={JSON.stringify(filters)}/> : <Note>No ad matches these filters.</Note>}
            </Card>
          </>);
      }}
    </AdsGate>);
}

function AdsTable({ ads, d, resetKey }) {
    const { rows, th } = useSort(ads, 'spend');
    const [open, setOpen] = useState(null);
    const target = d.targets.roas;
    return (<Paged rows={rows} size={12} resetKey={resetKey}>
      {(page) => (<div className="table-wrap"><table className="t compact">
        <thead><tr>{th('name', 'Ad', { right: false })}<th>Verdict</th>{th('spend', 'Spend')}{th('purchases', 'Purch.')}{th('roas', 'ROAS')}{th('roas_3d', '3-day')}
          {th('lifetime.roas', 'Lifetime', { title: 'ROAS since the ad started. Well above the recent figure means the ad is tiring.' })}{th('ctr', 'CTR')}{th('atc_rate', 'Cart rate', { title: 'Add to cart as a share of landing page views' })}
          <th title="Hook rate (watched 3 seconds), then the share of viewers who stay from 25% to 50%, 50% to 75% and 75% to 95% of the video">Hook and drop-off</th>
          {th('weakest.label', 'Weakest step', { right: false })}</tr></thead>
        <tbody>{page.map((a) => (<Fragment key={a.id}>
          <tr className={`clickable${a.status === 'ACTIVE' ? '' : ' fade'}`} onClick={() => setOpen(open === a.id ? null : a.id)} aria-expanded={open === a.id}>
            <td className="title-cell" style={nameCell(250)}><span className="ttl" title={a.name}>{a.name}</span>
              <span className="sub">{a.campaign} · {a.status === 'ACTIVE' ? `${a.days_live} days live` : a.status === 'PAUSED' ? 'paused' : 'ad set paused'}{a.is_new ? ' · new' : ''}</span></td>
            <td><VerdictPill verdict={a.verdict} reason={a.reason}/></td>
            <td className="r">{usd(a.spend)}</td><td className="r">{fmtInt(a.purchases)}</td>
            <td className="r"><Ratio value={a.roas} target={target} strong/></td><td className="r"><Ratio value={a.roas_3d} target={target}/></td>
            <td className="r" title={`${usd(a.lifetime.spend)} lifetime spend, ${a.lifetime.purchases} purchases`}><Ratio value={a.lifetime.roas} target={target}/></td>
            <td className="r">{pct1(a.ctr)}</td><td className="r">{pct1(a.atc_rate)}</td>
            <td><DropOff video={a.video}/></td>
            <td>{a.weakest.key === 'none' ? <span className="muted small">None</span> : a.weakest.key === 'early' ? <span className="faint small">Too early</span> : <Pill tone="warn">{a.weakest.label}</Pill>}</td>
          </tr>
          {open === a.id ? (<tr style={{ background: 'var(--surface-2)' }}><td colSpan={11}>
            <div className="grid cols-3 small" style={{ padding: '6px 4px', gap: 12 }}>
              <div><b>Why {VERDICTS[a.verdict]?.label.toLowerCase()}</b><div className="mt-4">{a.reason}</div>
                <div className="muted mt-4">Lifetime: {usd(a.lifetime.spend)} spend, {fmtInt(a.lifetime.purchases)} purchases, ROAS {x2(a.lifetime.roas)}. Last 7 days: {usd(a.spend_7d)}, {fmtInt(a.purchases_7d)} purchases.</div></div>
              <div><b>Against the account average</b>
                <div className="mt-4">ROAS {x2(a.roas)} <span className="muted">vs {x2(d.account.roas)}</span> · 14-day {x2(a.roas_14d)} · CPA {usd(a.cpa, 2)} <span className="muted">vs {usd(d.account.cpa, 2)}</span></div>
                <div>CTR {pct1(a.ctr)} <span className="muted">vs {pct1(d.account.ctr)}</span></div>
                <div>Cart rate {pct1(a.atc_rate)} <span className="muted">vs {pct1(d.account.atc_rate)}</span>{a.video ? <> · Hook {pct1(a.video.hook_rate)} <span className="muted">vs {pct1(d.account.hook_rate)}</span></> : null}</div>
                <div className="muted mt-4">{fmtInt(a.impressions)} impressions · {fmtInt(a.lpv)} page views · {fmtInt(a.atc)} carts · CPM {usd(a.cpm, 2)}</div></div>
              <div><b>Where it runs</b><div className="mt-4">{a.campaign} › {a.ad_set}</div>
                <div className="muted mt-4">{a.format === 'video' ? videoLine(a.video) : 'Image'} · started {fmtDate(a.launched)}</div>
                <div className="mono muted mt-4">Ad ID {a.id}</div></div>
            </div>
          </td></tr>) : null}
        </Fragment>))}</tbody>
      </table></div>)}
    </Paged>);
}

/* ------------------------------------------------------------------ Funnel */
function FunnelTab({ rq }) {
    const q = useApi(`/ads/funnel${qs(rq)}`);
    return (<AdsGate query={q}>
      {(d) => {
          const s = d.store;
          const cmp = d.compare ? `against the ${d.compare.label}` : 'no comparison';
          return (<>
            <div className={`grid ${d.meta && d.google ? 'cols-2' : ''}`}>
              {d.meta ? <Card title="Meta: from seeing the ad to buying" sub={`Each step and the share that came through from the step before, ${cmp}. A step in red lost more people than before.`}><FunnelSteps steps={d.meta.steps}/></Card> : null}
              {d.google ? <Card title="Google: from seeing the ad to buying" sub={d.google.note} foot={d.meta ? null : `Shown ${cmp}.`}><FunnelSteps steps={d.google.steps}/></Card> : null}
            </div>
            <Card title="On the store" sub="All visitors, not only the ones from ads. If clicks hold but these fall, the page or the offer is the problem, not the ad.">
              <div className="kpis">
                <AdsKpi label="Store sessions" block={s.sessions} format={fmtInt}/>
                <AdsKpi label="Store orders" block={s.orders} format={fmtInt}/>
                <AdsKpi label="Store conversion rate" block={s.conversion_rate} format={(v) => `${Number(v).toFixed(2)}%`}/>
                <AdsKpi label="AOV" block={s.aov} format={(v) => usd(v, 2)}/>
              </div>
            </Card>
          </>);
      }}
    </AdsGate>);
}

/* ------------------------------------------------------------------ Search terms (Google) */
function SearchTab({ rq }) {
    const q = useApi(`/ads/search-terms${qs({ brand: rq.brand, from: rq.from, to: rq.to })}`);
    return (<AdsGate query={q}>
      {(d) => {
          const b = d.brand_share;
          const share = b.total_value ? Math.round(b.value / b.total_value * 100) : 0;
          return (<>
            <div className="callout info"><Icon name="info"/><div><b>{share}% of the sales Google claims came from people searching for the brand by name</b>, on {usd(b.spend)} of the {usd(b.total_spend)} spent.
              Most of them would have found the store anyway, so judge Google on the other rows.</div></div>
            <div className="grid cols-2">
              <Card title="Keywords" sub="What the Search campaigns bid on." flush><TermTable rows={d.keywords} name="text" head="Keyword" extra={(r) => <span className="muted xs">{r.match_type.toLowerCase()}</span>}/></Card>
              <Card title="Search terms" sub="What people actually typed." flush><TermTable rows={d.terms} name="term" head="Search term"/></Card>
            </div>
            <Card title="Products" sub="Shopping and Performance Max, by product." flush><TermTable rows={d.products} name="title" head="Product" size={10}/></Card>
          </>);
      }}
    </AdsGate>);
}

function TermTable({ rows: all, name, head, extra, size = 8 }) {
    const { rows, th } = useSort(all, 'spend');
    if (!all.length) return <Note>Nothing with spend in these days.</Note>;
    return (<Paged rows={rows} size={size}>
      {(page) => (<div className="table-wrap"><table className="t compact">
        <thead><tr>{th(name, head, { right: false })}{th('spend', 'Spend')}{th('clicks', 'Clicks')}{th('purchases', 'Purch.')}{th('value', 'Sales', { className: 'hide-sm' })}{th('roas', 'ROAS')}</tr></thead>
        <tbody>{page.map((r) => (<tr key={r.id ?? `${r[name]}|${r.match_type ?? ''}`}>
          <td>{r[name]} {extra ? extra(r) : null} {r.is_brand ? <Tag>Brand</Tag> : null}</td>
          <td className="r">{usd(r.spend, 2)}</td><td className="r">{fmtInt(r.clicks)}</td><td className="r">{fmtInt(r.purchases)}</td><td className="r hide-sm">{usd(r.value)}</td><td className="r"><Ratio value={r.roas}/></td>
        </tr>))}</tbody>
      </table></div>)}
    </Paged>);
}

/* ------------------------------------------------------------------ ABO to CBO gap (Meta) */
function GapTab({ brand }) {
    const q = useApi(`/ads/gap${qs({ brand })}`);
    return (<AdsGate query={q}>
      {(d) => (<>
        <div className={`callout ${d.missing ? 'warn' : 'ok'}`}><Icon name={d.missing ? 'alert' : 'checkCircle'}/><div>
          <b>{d.missing ? `${d.missing} proven ad${d.missing === 1 ? ' is' : 's are'} still only in testing.` : 'Every proven test ad is already in its scaling campaign.'}</b>{' '}
          Proven means lifetime spend of {usd(d.rule.spend)} or more, ROAS {x2(d.rule.roas)} or better and at least {d.rule.purchases} purchases, up to {fmtDate(d.as_of)}. {d.note}</div></div>
        {d.pairs.map((p) => (<Card key={p.test_campaign} flush title={p.scale_campaign ? `${p.test_campaign}  →  ${p.scale_campaign}` : p.test_campaign}
          sub={p.note ?? (p.missing ? `${p.missing} to add to the scaling campaign.` : 'Nothing to add.')}>
          <GapTable rows={p.rows} target={d.rule.roas}/>
        </Card>))}
      </>)}
    </AdsGate>);
}

function GapTable({ rows, target }) {
    return (<Paged rows={rows} size={8}>
      {(page) => (<div className="table-wrap"><table className="t compact">
        <thead><tr><th>Verdict</th><th>Ad</th><th className="r">Lifetime spend</th><th className="r">Purchases</th><th className="r">ROAS</th><th className="r">7-day ROAS</th><th>Why</th></tr></thead>
        <tbody>{page.map((r) => (<tr key={r.id} className={r.verdict === 'early' ? 'fade' : ''}>
          <td><GapPill verdict={r.verdict}/></td>
          <td className="title-cell" style={nameCell(340)}><span className="ttl" title={r.name}>{r.name}</span><span className="sub">{AD_STATUS[r.status]?.label ?? r.status} · <span className="mono">{r.id}</span></span></td>
          <td className="r">{usd(r.spend)}</td><td className="r">{fmtInt(r.purchases)}</td><td className="r"><Ratio value={r.roas} target={target} strong/></td>
          <td className="r"><Ratio value={r.roas_7d} target={target}/></td><td className="small muted" style={{ minWidth: 240 }}>{r.why}</td>
        </tr>))}</tbody>
      </table></div>)}
    </Paged>);
}

/* ------------------------------------------------------------------ Actions */
function ActionsTab({ brand, platform }) {
    const q = useApi(`/ads/actions${qs({ brand, platform })}`);
    const [show, setShow] = useState('open');
    const [busy, setBusy] = useState(null);
    const toast = useToast();
    const mark = async (a, status) => {
        setBusy(a.id);
        try {
            await api.patch(`/ads/actions/${encodeURIComponent(a.id)}${qs({ brand })}`, { status });
            q.reload();
        } catch (e) {
            toast.error(e);
        } finally {
            setBusy(null);
        }
    };
    return (<AdsGate query={q}>
      {(d) => {
          const shown = d.actions.filter((a) => show === 'all' || a.status === show);
          const count = (s) => d.actions.filter((a) => a.status === s).length;
          return (<>
            <div className="callout info"><Icon name="lock"/><div><b>Suggestions only.</b> {d.read_only}{platform === 'meta' ? '' : ` ${d.google_note}`}</div></div>
            <Card flush title="What the rules suggest" sub={`From the last 7 days up to ${fmtDate(d.as_of)}. Open suggestions would change the daily budget by ${d.daily_impact > 0 ? '+' : ''}${usd(d.daily_impact)}.`}
              actions={<Seg label="Show" options={[...ACTION_STATUS.map((s) => ({ key: s.key, label: `${s.label} ${count(s.key)}` })), { key: 'all', label: `All ${d.actions.length}` }]} value={show} onChange={setShow}/>}>
              {shown.length ? (<div className="table-wrap"><table className="t">
                <thead><tr><th className="r">#</th><th>Do</th><th>What and where</th><th>Now → proposed</th><th>Evidence</th><th className="r">Daily budget</th><th>Status</th></tr></thead>
                <tbody>{shown.map((a) => (<tr key={a.id} className={a.status === 'open' ? '' : 'fade'}>
                  <td className="r muted">{a.n}</td>
                  <td><Pill tone={ACTION_GROUPS[a.group]?.tone ?? 'neutral'}>{ACTION_GROUPS[a.group]?.label ?? a.group}</Pill></td>
                  <td className="title-cell" style={nameCell(300)}><span className="ttl" title={a.title}>{a.title}</span><span className="sub" title={a.where}>{a.where}</span></td>
                  <td className="small">{a.current} <span className="muted">→</span> <b>{a.proposed}</b></td>
                  <td className="small" style={{ minWidth: 200 }}>{a.evidence} <span className="muted">Confidence: {a.confidence.toLowerCase()}.</span></td>
                  <td className="r">{a.daily_impact ? <span style={{ color: a.daily_impact < 0 ? 'var(--crit)' : 'var(--ok)', fontWeight: 650 }}>{a.daily_impact > 0 ? '+' : ''}{usd(a.daily_impact)}</span> : <span className="faint">—</span>}</td>
                  <td className="nowrap">{a.status === 'open' ? (<span className="row" style={{ gap: 4 }}>
                    <Button size="sm" icon="check" loading={busy === a.id} onClick={() => mark(a, 'done')}>Done</Button>
                    <Button size="sm" variant="ghost" disabled={busy === a.id} onClick={() => mark(a, 'skipped')}>Skip</Button></span>)
                    : (<span className="row" style={{ gap: 6 }}><Pill tone={a.status === 'done' ? 'ok' : 'neutral'}>{a.status === 'done' ? 'Done' : 'Skipped'}</Pill>
                      <Button size="sm" variant="ghost" disabled={busy === a.id} onClick={() => mark(a, 'open')}>Reopen</Button></span>)}</td>
                </tr>))}</tbody>
              </table></div>) : <Note>{d.actions.length ? 'Nothing with this status.' : platform === 'google' ? d.google_note : 'The rules suggest nothing right now.'}</Note>}
            </Card>
            <Card flush title="History" sub="Who marked what, newest first.">
              {d.history.length ? (<div className="table-wrap"><table className="t compact">
                <thead><tr><th>When</th><th>Who</th><th>Marked</th><th>Suggestion</th></tr></thead>
                <tbody>{d.history.map((h) => (<tr key={h.id}><td className="nowrap">{fmtDateTime(h.at)}</td><td>{h.by}</td>
                  <td><Pill tone={h.status === 'done' ? 'ok' : 'neutral'}>{ACTION_STATUS.find((s) => s.key === h.status)?.label ?? h.status}</Pill></td>
                  <td><span className="muted">{ACTION_GROUPS[h.group]?.label}:</span> {h.title}</td></tr>))}</tbody>
              </table></div>) : <Note>Nothing has been marked done or skipped yet.</Note>}
            </Card>
          </>);
      }}
    </AdsGate>);
}

/* ------------------------------------------------------------------ Rules */
function RulesTab({ brand, onSaved }) {
    const q = useApi(`/ads/rules${qs({ brand })}`, { remember: false });
    const [draft, setDraft] = useState(null);
    const [saving, setSaving] = useState(false);
    const toast = useToast();
    useEffect(() => { setDraft(null); }, [brand]);
    return (<AdsGate query={q}>
      {(d) => {
          const values = draft ?? d.rules;
          const changed = Object.fromEntries(Object.entries(values).filter(([k, v]) => k in d.defaults && Number(v) !== d.rules[k]).map(([k, v]) => [k, Number(v)]));
          const bad = Object.values(changed).some((v) => !Number.isFinite(v) || v <= 0);
          const save = async () => {
              setSaving(true);
              try {
                  await api.patch(`/ads/rules${qs({ brand })}`, changed);
                  toast.ok('Rules saved. Every tab now uses them.');
                  setDraft(null);
                  q.reload();
                  onSaved?.();   // the account line shows the rupee rate
              } catch (e) {
                  toast.error(e);
              } finally {
                  setSaving(false);
              }
          };
          return (<div className="grid main-side">
            <div className="col" style={{ gap: 16 }}>
              <Card title="Rules" sub="Every threshold the page uses for this brand. Changing one changes the verdicts, the scaling gate and the suggestions."
                actions={<><Button size="sm" variant="ghost" disabled={!draft || saving} onClick={() => setDraft(null)}>Undo changes</Button>
                  <Button size="sm" variant="primary" icon="check" loading={saving} disabled={!Object.keys(changed).length || bad} onClick={save}>Save {Object.keys(changed).length || ''}</Button></>}>
                <div className="col" style={{ gap: 18 }}>
                  {RULE_GROUPS.map((g) => {
                      const fields = g.fields.filter((fl) => !fl.only || fl.only === d.meta_currency);
                      return (<div key={g.title}><div style={{ fontWeight: 650 }} className="mb-8">{g.title}</div>
                        <div className="grid cols-3" style={{ gap: 12 }}>
                          {fields.map((fl) => (<div key={fl.key} className="field"><label htmlFor={`rule-${fl.key}`}>{fl.label}{fl.unit ? <span className="muted"> ({fl.unit})</span> : null}</label>
                            <input id={`rule-${fl.key}`} className="input" type="number" step="any" min="0" value={values[fl.key] ?? ''} onChange={(e) => setDraft({ ...values, [fl.key]: e.target.value })}
                              style={Number(values[fl.key]) !== d.rules[fl.key] ? { borderColor: 'var(--accent)' } : undefined}/>
                            <div className="hint">{fl.hint ?? ''}{Number(d.rules[fl.key]) !== d.defaults[fl.key] ? `${fl.hint ? ' ' : ''}Started as ${d.defaults[fl.key]}.` : ''}</div></div>))}
                        </div></div>);
                  })}
                  {d.meta_currency === 'INR' && d.rules.fx_from ? <div className="muted small">The current rupee rate has applied since {fmtDay(d.rules.fx_from)}.</div> : null}
                </div>
              </Card>
            </div>
            <div className="col" style={{ gap: 16 }}>
              <Card title="Words used on this page">
                <dl className="col" style={{ gap: 10, margin: 0 }}>{d.glossary.map((gl) => (<div key={gl.term}><dt style={{ fontWeight: 650 }}>{gl.term}</dt><dd className="muted small" style={{ margin: 0 }}>{gl.meaning}</dd></div>))}</dl>
              </Card>
            </div>
          </div>);
      }}
    </AdsGate>);
}

