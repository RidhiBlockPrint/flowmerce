/**
 * Demo module: the automatic blog pipeline and the SEO & Blog overview (GET /api/blog/overview, services/auto_blog.py).
 * Synthetic: fictional titles, no Claude calls. Two slots a week per brand (Tuesday and Friday) for the next 4 weeks;
 * the nearest are ready as hidden drafts, the next one is being written, the rest are planned.
 *
 * Collection `db.blog`: { settings: { enabled, weekdays }, slots: [{ id, brand_id, publish_on, status, title, score, groups }] }
 */
import { BRAND_IDS } from '../brands.js';
import { DemoError, dayAgo } from '../util.js';

const WEEKDAY_NAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
const TITLES = {
  ridhi: ['How to care for hand block printed quilts', 'Choosing a tablecloth size for a round table', 'Indigo dyeing: what makes it last',
    'Kantha throws: a buyer\'s guide', 'Festive table setting ideas with block prints', 'Cotton or linen napkins: which to choose',
    'What thread count means for a bedspread', 'Styling floral pillow covers through the seasons'],
  cpc: ['Round tablecloths for small dining rooms', 'How to wash printed chair cushions', 'Table runner lengths explained',
    'Holiday napkin folds that impress', 'Why hand printed cotton fades less', 'Quilts for warm climates', 'Setting a table for 8', 'Caring for jade green linens'],
};
const pyWeekday = (iso) => (new Date(`${iso}T12:00:00`).getDay() + 6) % 7;   // 0 = Monday, like Python

export function seed(db) {
  const slots = [];
  let id = 1;
  for (const b of BRAND_IDS) {
    let n = 0;
    for (let i = 1; i <= 28; i++) {
      const day = dayAgo(-i);
      if (![1, 4].includes(pyWeekday(day))) continue;
      const status = n < 2 ? 'ready' : n === 2 ? 'writing' : 'planned';
      const score = status === 'ready' ? 92 - n * 4 : status === 'writing' ? 74 : null;
      slots.push({ id: id++, brand_id: b, publish_on: day, status, title: status === 'planned' ? null : TITLES[b][n % 8],
        score, groups: score ? { fields: 100, seo: score, aeo: score - 6, geo: score - 10, llmo: score + 2 > 100 ? 100 : score + 2 } : {} });
      n += 1;
    }
  }
  db.blog = { settings: { enabled: true, weekdays: [1, 4] }, slots };
}

function overview(db, brand) {
  const rows = db.blog.slots.filter((s) => !brand || s.brand_id === brand).map((s) => ({
    id: s.id, brand_id: s.brand_id, publish_on: s.publish_on, status: s.status, article_id: s.status === 'ready' ? 1 : null,
    article_title: s.status === 'ready' ? s.title : null, topic_title: s.title, article_status: s.status === 'ready' ? 'publish_requested' : null,
    primary_keyword: s.title ? s.title.toLowerCase().split(' ').slice(0, 4).join(' ') : '',
    message: s.status === 'ready' ? 'Saved as a hidden Shopify draft. Publish request waits for a reviewer.' : s.status === 'writing' ? 'Claude is writing the draft' : '',
    checks: { score: s.score, groups: s.groups, open: s.score && s.score < 90 ? ['Specific facts and figures'] : [], words: s.score ? 1400 : null, images: s.score ? 4 : null },
  }));
  const upcoming = rows.filter((r) => r.publish_on > dayAgo(0));
  const count = (k) => upcoming.filter((r) => r.status === k).length;
  const next4 = upcoming.filter((r) => !['skipped', 'missed', 'failed'].includes(r.status)).length;
  const scores = rows.map((r) => r.checks.score).filter((x) => x !== null);
  return {
    brand: brand ?? null, today: dayAgo(0), from: dayAgo(14), to: dayAgo(-35),
    settings: { ...db.blog.settings, weeksAhead: 4, leadDays: 5, inlineImages: 3, weekdayNames: db.blog.settings.weekdays.map((d) => WEEKDAY_NAMES[d]) },
    slots: rows,
    counts: { planned: count('planned'), writing: count('writing'), ready: count('ready'), failed: count('failed'), skipped: count('skipped'), missed: count('missed'),
      upcoming: upcoming.length, next4Weeks: next4, liveLast30: brand ? 3 : 6, waitingForReviewer: count('ready') },
    projection: { clicksPerArticleMonth: brand === 'cpc' ? 14 : 21, basedOnArticles: 12, monthlyClicksFromNext4Weeks: next4 * (brand === 'cpc' ? 14 : 21),
      claudeUsdNext4Weeks: Math.round(next4 * 2.0 * 100) / 100, blogEstimateUsd: 2.0, averageQuality: scores.length ? Math.round(scores.reduce((a, x) => a + x, 0) / scores.length) : null },
    budget: { todayUsd: 0.6, dailyLimitUsd: 3, remainingTodayUsd: 2.4, monthlyBudgetUsd: 90, monthUsd: 21.4, warning: null },
    events: [{ key: 'christmas', name: 'Christmas', date: `${new Date().getFullYear()}-12-25` }],
  };
}

export const routes = [
  // Uploads need a real Shopify store: the demo explains that instead of pretending.
  ['POST', '/images/upload', () => { throw new DemoError(412, 'The demo has no Shopify store to keep uploaded images. Paste an image link instead.', 'pending_setup'); }],
  ['GET', '/blog/overview', ({ query, db }) => overview(db, BRAND_IDS.includes(query.brand) ? query.brand : undefined)],
  ['PATCH', '/blog/autopilot', ({ body, db }) => {
    if ('enabled' in body) db.blog.settings.enabled = !!body.enabled;
    return db.blog.settings;
  }],
  ['POST', '/blog/slots/:id/skip', ({ params, db }) => {
    const s = db.blog.slots.find((x) => x.id === Number(params.id));
    if (!s) throw new DemoError(404, 'That slot does not exist.');
    if (s.status !== 'planned') throw new DemoError(409, 'Only a slot that has not started can be skipped.');
    s.status = 'skipped';
    return s;
  }],
];
