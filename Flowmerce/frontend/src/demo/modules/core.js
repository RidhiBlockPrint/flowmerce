/**
 * Demo module: who is using the app (/auth/me), the task list (/tasks) and the Home overview (/home).
 * It owns no business records: Home is assembled read-only from what the other demo modules expose, with the same
 * payload the Python /api/home endpoint returns (plus `trend` and `shipping`, which the backend will add).
 *
 * db.me = { userId }   which demo user is acting (the role switcher in the sidebar changes it)
 */
import { ALL_PERMISSIONS, USERS, brandsPublic } from '../brands.js';
import { DemoError, hoursAgo } from '../util.js';
import { articleCounts, tasksFor, trafficSummary } from './content.js';
import { automationAlerts, homeRuns } from './automation.js';
import { shippingHomeSummary } from './shipping.js';
import { brandSettingsFor } from './settings.js';

const ROLE_PERMS = {
  admin: ALL_PERMISSIONS,
  seo_manager: ['view', 'topic:write', 'topic:decide', 'article:write', 'article:submit', 'shopify:draft', 'publish:request', 'workflow:run', 'analytics:sync', 'data:import', 'audit:view'],
  reviewer: ['view', 'article:review', 'publish:authorize', 'analytics:sync', 'audit:view'],
};
const WINDOW_DAYS = 28;
const LATENCY_DAYS = 3;
const APPROVAL_LABEL = { review: 'Content approval', authorize: 'Publish approval', topic: 'Topic approval' };

const currentUser = (db) => USERS.find((u) => u.id === db.me.userId) ?? USERS[0];
const day = (offset) => new Date(Date.now() - offset * 86400000).toISOString().slice(0, 10);

export function seed(db) {
  db.me = { userId: 1 };
}

function brandIds(query) {
  return query.brand && query.brand !== 'all' ? [query.brand] : ['ridhi', 'cpc'];
}

function alertsFor(db, ids, ship) {
  const out = [];
  const reqs = (db.publishRequests ?? []).filter((r) => ids.includes(r.brand_id));
  const failed = reqs.filter((r) => r.status === 'failed');
  if (failed.length) out.push({ level: 'critical', title: `${failed.length} publish request${failed.length === 1 ? '' : 's'} failed`, detail: 'The simulated publish step reported an error. Open Publishing to retry.', link: '/publishing' });
  out.push(...automationAlerts(db, ids));
  if (ship?.red) out.push({ level: 'warning', title: `${ship.red} shipments need escalation`, detail: 'Delayed past the promised date or without a scan. Open Shipping, Checks and exceptions.', link: '/shipping?tab=checks' });
  out.push({ level: 'info', title: 'All integrations are simulated in this preview', detail: 'Shopify, Search Console, GA4 and the AI worker are not connected. See Settings, Integrations.', link: '/settings/integrations' });
  const order = { critical: 0, warning: 1, info: 2 };
  return out.sort((a, b) => order[a.level] - order[b.level]);
}

export const routes = [
  ['GET', '/auth/me', ({ db }) => {
    const user = currentUser(db);
    return {
      user, permissions: ROLE_PERMS[user.role], brands: brandsPublic().map((b) => ({ ...b, settings: brandSettingsFor(db, b.id) })), livePublishing: true,
      demoLoaded: false, demoMode: false, localOperator: false, preview: true,
    };
  }],
  ['POST', '/demo/role', ({ body, db }) => {
    const u = USERS.find((x) => x.role === body.role);
    if (!u) throw new DemoError(400, 'Unknown demo role.', 'bad_role');
    db.me.userId = u.id;
    return { ok: true, user: u };
  }],
  ['GET', '/tasks', ({ db }) => {
    const u = currentUser(db);
    return tasksFor(db, u.role, u.id);
  }],
  ['GET', '/home', ({ query, db }) => {
    const u = currentUser(db);
    const ids = brandIds(query);
    const to = day(LATENCY_DAYS);
    const from = day(LATENCY_DAYS + WINDOW_DAYS - 1);
    const tasks = tasksFor(db, u.role, u.id).filter((t) => ids.includes(t.brand));
    const approvals = tasks.filter((t) => APPROVAL_LABEL[t.kind]).sort((a, b) => (a.since ?? '').localeCompare(b.since ?? ''))
      .map((t, i) => ({ id: `${t.kind}-${i}`, brand: t.brand, module: 'seo', kind: t.kind, label: APPROVAL_LABEL[t.kind], title: t.title, action: t.action, to: t.link, since: t.since }));
    const traffic = Object.fromEntries(ids.map((b) => [b, trafficSummary(db, b, from, to)]));
    const shipping = {
      all: shippingHomeSummary(db, query.brand && query.brand !== 'all' ? query.brand : undefined),
      byBrand: Object.fromEntries(['ridhi', 'cpc'].map((b) => [b, shippingHomeSummary(db, b)])),
    };
    const alerts = alertsFor(db, ids, shipping.all).map((a, i) => ({ id: `alert-${i}`, module: 'seo', severity: a.level, title: a.title, detail: a.detail, to: a.link }));
    const syncedAt = hoursAgo(0);
    const metric = (b, key, label, value) => ({ brand: b, module: 'seo', key, label, value, source: { kind: 'demo', syncedAt, coverage: { from, to } }, state: 'ok', scope: 'blog', syncedAt, dataThrough: to, withheld: false, note: 'Demo data' });
    const brief = [];
    for (const b of new Set(approvals.map((a) => a.brand))) {
      const n = approvals.filter((a) => a.brand === b).length;
      brief.push({ module: 'seo', brand: b, text: `${n} item${n === 1 ? '' : 's'} waiting for a decision in SEO & Blog.` });
    }
    return {
      generatedAt: hoursAgo(0), window: { from, to, days: WINDOW_DAYS }, brands: ids, demoFixturesLoaded: false, demoMode: false,
      brief,
      metrics: ids.flatMap((b) => [metric(b, 'gsc_clicks', 'Search clicks', traffic[b].clicks), metric(b, 'gsc_impressions', 'Search impressions', traffic[b].impressions), metric(b, 'ga4_sessions', 'Sessions', traffic[b].sessions)]),
      trend: ids.map((b) => ({ brand: b, points: traffic[b].series.map((p) => ({ x: p.date, y: p.clicks })) })),
      articles: ids.map((b) => ({ brand: b, ...articleCounts(db, b) })),
      approvals: approvals.slice(0, 10), approvalsTotal: approvals.length, alerts,
      reports: [], reportsNote: '',
      jobs: homeRuns(db, ids), syncs: [], shipping,
    };
  }],
];
