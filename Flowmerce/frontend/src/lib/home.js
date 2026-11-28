/**
 * Data behind the Home page (the CEO view, layout "A · Bento", owner 2026-11-27): one dashboard for All, Ridhi and CPC,
 * with both brands added together on All, for a period (today, yesterday, 7 or 30 days, month to date) against the one
 * before. Every figure is a real record from the API; nothing is added up or worked out here beyond reshaping one
 * answer into the shape of another:
 *   - GET /api/cro/home-period: sales, orders, average order, conversion and visits, the sales breakdown, the sales
 *     chart, the daily figures, each brand's share and the month's goal (cro/company.py);
 *   - GET /api/ads/company (All) or GET /api/ads/overview (one brand), for the same days: ad spend, sales per $1 of ads,
 *     cost per order, the Meta / Google split, targets, the days;
 *   - GET /api/home: approvals, alerts, automation runs, articles, blog search clicks, the shipping problems.
 */
import { useMemo } from 'react';
import { qs, useApi } from './api';
const EMPTY = { kind: 'none', brief: [], metrics: [], articles: [], approvals: [], approvalsTotal: 0, alerts: [], reports: [], jobs: [], syncs: [], trend: [], shipping: null };
/** Home data for the selected brand: the real GET /api/home response. */
export function useHomeData(brand) {
    const live = useApi(`/home${qs({ brand: brand === 'all' ? undefined : brand })}`);
    const real = useMemo(() => (live.data ? { ...EMPTY, ...live.data, kind: 'api' } : EMPTY), [live.data]);
    return { data: real, loading: live.loading || (!live.data && !live.error), error: live.error, reload: live.reload };
}

/** The periods Home offers, in the order the switch shows them. */
export const HOME_PERIODS = [
    { key: 'today', label: 'Today' },
    { key: 'yesterday', label: 'Yesterday' },
    { key: '7d', label: '7 days' },
    { key: '30d', label: '30 days' },
    { key: 'mtd', label: 'Month to date' },
];

/** Sales and the store figures for a period, one brand or both added together. */
export function useHomePeriod(brand, period) {
    return useApi(`/cro/home-period${qs({ brand: brand === 'all' ? undefined : brand, period })}`);
}

/**
 * One brand's GET /api/ads/overview answer in the shape of GET /api/ads/company, so Home draws one brand and both brands
 * the same way. Only names change: nothing is added up or worked out.
 */
export function companyFromOverview(brand, o) {
    const m = o.metrics ?? {};
    return {
        from: o.from, to: o.to, days: o.days, compare: o.compare,
        metrics: { spend: m.total_spend, sales: m.sales, sales_ex_bulk: m.sales_ex_bulk, orders: m.orders, mer_ex_bulk: m.mer_ex_bulk, cost_per_order: m.cost_per_order },
        brands: [{ brand, ready: true, gate: o.gate, targets: o.targets, gate_lines: o.gate_lines,
            metrics: { total_spend: m.total_spend, sales_ex_bulk: m.sales_ex_bulk, mer_ex_bulk: m.mer_ex_bulk, orders: m.orders },
            share_of_spend: 100, platforms: o.platforms ?? [], goal: o.goal, meta_saved_to: o.meta_saved_to, google_saved_to: o.google_saved_to }],
        platforms: (o.platforms ?? []).filter((p) => p.spend !== null && p.spend !== undefined)
            .map((p) => ({ platform: p.platform, spend: p.spend, share_of_spend: p.share_of_spend, roas: p.roas })),
        trend: (o.trend ?? []).map((r) => ({ date: r.date, spend: r.spend, sales_ex_bulk: r.sales_ex_bulk, mer_ex_bulk: r.mer_ex_bulk,
            [`${brand}_spend`]: r.spend, [`${brand}_mer_ex_bulk`]: r.mer_ex_bulk })),
    };
}

/** Ad spend and its return for the same days as the sales (`from`..`to`, YYYY-MM-DD) against the days before: both
 *  brands on All, else the one brand. Nothing is asked until the days are known. */
export function useHomeAds(brand, from, to) {
    const one = brand !== 'all';
    const range = { from: from ?? undefined, to: to ?? undefined };
    const q = useApi(!from ? null : one ? `/ads/overview${qs({ brand, platform: 'all', ...range })}` : `/ads/company${qs(range)}`);
    // While a switch between All and one brand loads, the hook still holds the other address's answer: use an answer
    // only when its shape matches the address (the company answer lists brands, a brand's overview has a gate).
    const data = useMemo(() => {
        if (!q.data) return null;
        if (one) return q.data.gate && !Array.isArray(q.data.brands) ? companyFromOverview(brand, q.data) : null;
        return Array.isArray(q.data.brands) ? q.data : null;
    }, [q.data, one, brand]);
    return { data, error: q.error, reload: q.reload };
}
