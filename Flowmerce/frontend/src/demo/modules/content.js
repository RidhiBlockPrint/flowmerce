/**
 * Demo module: content (articles, publishing, topics, keywords, analytics, audit).
 * Everything is synthetic and runs in the browser. "Publishing" and "Shopify draft" are SIMULATED: they change this
 * demo's own records and write audit rows, but nothing is sent to Shopify, Google or any other service.
 *
 * Shared collections (other demo modules may read them; do not rename fields):
 *
 * db.articles[]  {
 *   id, brand_id ('ridhi'|'cpc'), topic_id|null, title, handle, primary_keyword, meta_title, meta_description,
 *   summary_html, body_html, tags (comma string), author, image_url, image_alt,
 *   status: idea|draft|in_review|changes_requested|approved|publish_requested|scheduled|published|failed,
 *   version, content_hash, approved_hash|null, approved_at|null, live_hash|null, review_note,
 *   assignee_id|null, created_by, origin ('app'|'claude'|'shopify_admin'), created_at, updated_at,
 *   shopify_article_id|null (only for entries that exist in the demo store listing), shopify_published (bool),
 *   published_at|null, shopify_synced_at|null, live_url|null, publish_at|null (schedule), last_error|null,
 *   demo_draft_at|null (a simulated hidden draft was prepared), demo: {traffic, trend} (drives synthetic analytics)
 * }
 * db.articleVersions[]  { id, article_id, version, note, user_id, user_name, created_at, content_hash, data: {title, handle, ...body_html} }
 * db.reviewNotes[]      { id, article_id, version, reviewer_id, reviewer_name, kind: submitted|approved|changes_requested, note, created_at, source }
 * db.publishRequests[]  {
 *   id, article_id, brand_id, version, mode: publish_now|schedule|update_live, publish_at|null,
 *   status: pending|executed|failed|rejected|cancelled, note, requested_by (user id), requested_at,
 *   decided_by|null, decided_at|null, decision_note, content_hash (article hash when requested), attempts, error|null
 * }
 * db.topics[]   { id, brand_id, title, primary_keyword, secondary_keywords, intent, search_volume|null, keyword_difficulty|null, volume_source,
 *                 status: proposed|validated|approved|rejected|in_production|published, source ('claude'|'manual'), notes, rationale,
 *                 validation_note, article_id|null, created_at, updated_at }
 * db.keywords[] { id, brand_id, keyword, search_volume, keyword_difficulty, intent, source_tool, source, source_date (YYYY-MM-DD) }
 * db.audit[]    { id, ts, user_id, user_email, action, entity_type, entity_id, brand_id, summary, details, ip }   (ids ascend; newest = highest)
 * db.analyticsSync { [brand]: { gsc: ISO, ga4: ISO } }   last simulated sync time
 *
 * Exports for other modules: addAudit, trafficSummary, articleCounts, tasksFor.
 */
import { DemoError, csvDownload, daysAgo, hoursAgo, list, matches } from '../util.js';
import { BRAND_IDS, USERS } from '../brands.js';
import { ARTICLE_SPECS, KEYWORD_SPECS, QUERY_MODIFIERS, TOPIC_SPECS, productsFor } from './contentSeed.js';

const CONTENT_FIELDS = ['title', 'handle', 'primary_keyword', 'meta_title', 'meta_description', 'summary_html', 'body_html', 'tags', 'author', 'image_url', 'image_alt'];
const APPROVAL_BOUND = ['approved', 'publish_requested', 'scheduled', 'published', 'failed'];
const STATUS_ORDER = ['idea', 'draft', 'changes_requested', 'in_review', 'approved', 'publish_requested', 'scheduled', 'published', 'failed'];
const BLOG = { ridhi: 'news', cpc: 'journal' };
const BRAND_NAME = { ridhi: 'Ridhi Block Print', cpc: 'Cotton Print Club' };
const DEMO_NOTE = 'Demo only: nothing was sent to Shopify or any storefront.';

const userOf = (id) => USERS.find((u) => u.id === id) ?? null;
const actorOf = (db) => userOf(db.me?.userId) ?? USERS[0];
const nextIdOf = (arr) => arr.reduce((m, r) => Math.max(m, r.id), 0) + 1;
const nowIso = () => new Date().toISOString();
const num = (v) => (v === '' || v === null || v === undefined || Number.isNaN(Number(v)) ? null : Number(v));
const slugify = (s) => String(s ?? '').toLowerCase().replace(/&/g, ' and ').replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 90);
const sanitize = (html) => String(html ?? '')
  .replace(/<\s*(script|iframe|object|embed)[\s\S]*?(<\/\s*\1\s*>|$)/gi, '')
  .replace(/\son\w+\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)/gi, '')
  .replace(/javascript:/gi, '');
const hashOf = (c) => {
  const s = JSON.stringify(CONTENT_FIELDS.map((f) => c[f] ?? ''));
  let h1 = 5381; let h2 = 52711;
  for (let i = 0; i < s.length; i++) { h1 = ((h1 * 33) ^ s.charCodeAt(i)) >>> 0; h2 = ((h2 * 31) ^ s.charCodeAt(i)) >>> 0; }
  return h1.toString(16).padStart(8, '0') + h2.toString(16).padStart(8, '0');
};
const contentOf = (a) => Object.fromEntries(CONTENT_FIELDS.map((f) => [f, String(a[f] ?? '')]));
const liveUrl = (brand, handle) => `https://${brand}.demo.invalid/blogs/${BLOG[brand]}/${handle}`;
const pathOf = (a) => `/blogs/${BLOG[a.brand_id]}/${a.handle}`;
const need = (cond, status, msg, code) => { if (!cond) throw new DemoError(status, msg, code); };

/* ---------------- audit ---------------- */

/** Append one audit row. `entity` may be 'article:12', 'article 12' or {type, id}; `detail` a string (summary) or an object ({summary, ...details}). */
export function addAudit(db, { action, brand = '', entity = '', detail = '', userId, ts } = {}) {
  db.audit ??= [];
  const u = userId === null ? null : (userOf(userId ?? db.me?.userId) ?? USERS[0]);
  let type = ''; let id = '';
  if (entity && typeof entity === 'object') { type = entity.type ?? ''; id = entity.id ?? ''; }
  else if (entity) { const m = String(entity).split(/[:\s]+/); type = m[0]; id = m.slice(1).join(' '); }
  const summary = typeof detail === 'string' ? detail : detail?.summary ?? '';
  const details = typeof detail === 'object' && detail ? Object.fromEntries(Object.entries(detail).filter(([k]) => k !== 'summary')) : {};
  const row = { id: db.audit.reduce((m, r) => Math.max(m, r.id), 0) + 1, ts: ts ?? nowIso(), user_id: u?.id ?? null, user_email: u?.email ?? null,
    action, entity_type: type, entity_id: String(id), brand_id: brand || '', summary, details, ip: 'demo' };
  db.audit.push(row);
  return row;
}

/* ---------------- article helpers ---------------- */

function nextAction(a) {
  const live = !!a.shopify_published;
  switch (a.status) {
    case 'idea': return { role: 'seo_manager', label: 'Write the first draft' };
    case 'draft': return { role: 'seo_manager', label: live ? 'Finish edits, then send for review' : 'Finish and send for review' };
    case 'changes_requested': return { role: 'seo_manager', label: 'Address reviewer feedback' };
    case 'in_review': return { role: 'reviewer', label: 'Review content' };
    case 'approved': return { role: 'seo_manager', label: live ? 'Request update of the live article' : 'Save a draft or request publishing' };
    case 'publish_requested': return { role: 'reviewer', label: 'Authorize publishing' };
    case 'scheduled': return { role: '', label: a.publish_at ? `Goes live ${new Date(a.publish_at).toUTCString().slice(5, 22)} UTC` : 'Goes live at the scheduled time' };
    case 'failed': return { role: 'seo_manager', label: 'Check the error and retry' };
    case 'published': return { role: 'seo_manager', label: 'Track performance' };
    default: return { role: '', label: '' };
  }
}

function shopifyState(a) {
  if (!a.shopify_article_id) return 'not_in_shopify';
  if (a.shopify_published) return 'live';
  if (a.published_at && Date.parse(a.published_at) > Date.now()) return 'scheduled_in_shopify';
  return 'hidden';
}

function decorate(db, a, withBody = true) {
  const linked = !!a.shopify_article_id;
  const out = {
    ...a,
    shopify_state: shopifyState(a),
    shopify_published: !!a.shopify_published,
    shopify_sync: linked ? 'admin_api' : null,
    unpublished_in_shopify: linked && !a.shopify_published && a.status === 'published',
    has_shopify_draft: !!a.demo_draft_at || (linked && !a.shopify_published),
    live_differs: !!a.shopify_published && !!a.live_hash && a.live_hash !== a.content_hash,
    approval_current: !!a.approved_hash && a.approved_hash === a.content_hash,
    next_action: nextAction(a),
    assignee_name: userOf(a.assignee_id)?.name ?? null,
  };
  if (!withBody) delete out.body_html;
  return out;
}

const getArticle = (db, id) => {
  const a = db.articles.find((x) => x.id === Number(id));
  need(a, 404, 'Article not found.', 'not_found');
  return a;
};

/** Promote Flowmerce-scheduled articles whose time has passed (simulated go-live). */
function tick(db) {
  for (const a of db.articles) {
    if (a.status === 'scheduled' && a.publish_at && Date.parse(a.publish_at) <= Date.now()) {
      goLive(a, a.publish_at);
    }
  }
}

function goLive(a, at) {
  a.status = 'published';
  a.shopify_published = true;
  a.shopify_article_id ??= `demo-article-${a.id}`;
  a.published_at = at;
  a.live_url = liveUrl(a.brand_id, a.handle);
  a.live_hash = a.content_hash;
  a.shopify_synced_at = nowIso();
  a.last_error = null;
  a.publish_at = null;
  a.demo ??= { traffic: 0.6, trend: 0 };
}

function snapshot(db, a, userId, note) {
  db.articleVersions.push({ id: nextIdOf(db.articleVersions), article_id: a.id, version: a.version, note, user_id: userId, user_name: userOf(userId)?.name ?? null,
    created_at: nowIso(), content_hash: a.content_hash, data: contentOf(a) });
}

function cancelOpenRequests(db, a, note) {
  for (const r of db.publishRequests) if (r.article_id === a.id && (r.status === 'pending' || r.status === 'failed')) { r.status = 'cancelled'; r.decided_at = nowIso(); r.decision_note = note; }
}

/** Apply new content: new version, new hash, approval no longer covers it. */
function applyContent(db, a, next, user, note) {
  Object.assign(a, next);
  a.version += 1;
  a.content_hash = hashOf(a);
  a.updated_at = nowIso();
  if (['approved', 'publish_requested', 'in_review', 'published', 'failed', 'idea'].includes(a.status)) {
    if (a.status !== 'idea') cancelOpenRequests(db, a, 'Content changed after the request');
    a.status = 'draft';
    a.publish_at = null;
  }
  snapshot(db, a, user.id, note || 'Edited');
}

function uniqueHandle(db, brand, wanted, exceptId) {
  const base = slugify(wanted) || 'article';
  let h = base;
  for (let i = 2; db.articles.some((x) => x.brand_id === brand && x.handle === h && x.id !== exceptId); i++) h = `${base}-${i}`;
  return h;
}

function addNote(db, a, user, kind, note) {
  db.reviewNotes.push({ id: nextIdOf(db.reviewNotes), article_id: a.id, version: a.version, reviewer_id: user.id, reviewer_name: user.name, kind, note: note || '', created_at: nowIso(), source: 'app' });
}

/* ---------------- publish request helpers ---------------- */

function decorateRequest(db, r) {
  const a = db.articles.find((x) => x.id === r.article_id);
  return { ...r, title: a?.title ?? '(deleted)', handle: a?.handle, article_version: a?.version, article_hash: a?.content_hash, shopify_published: !!a?.shopify_published,
    requested_by_name: userOf(r.requested_by)?.name ?? null, decided_by_name: userOf(r.decided_by)?.name ?? null, stale: !!a && r.content_hash !== a.content_hash };
}

function execute(db, r, user, note, auditAction) {
  const a = getArticle(db, r.article_id);
  need(r.content_hash === a.content_hash, 409, 'The article changed after this request, so it was refused. It needs a fresh review.', 'stale_request');
  r.status = 'executed'; r.decided_by = user.id; r.decided_at = nowIso(); r.error = null;
  if (note) r.decision_note = note;
  if (r.mode === 'schedule') { a.status = 'scheduled'; a.publish_at = r.publish_at; a.last_error = null; }
  else goLive(a, nowIso());
  a.updated_at = nowIso();
  const summary = r.mode === 'schedule'
    ? `Simulated: "${a.title}" marked as scheduled in the demo. ${DEMO_NOTE}`
    : `Simulated: "${a.title}" marked as published in the demo. ${DEMO_NOTE}`;
  addAudit(db, { action: auditAction, brand: a.brand_id, entity: { type: 'publish_request', id: r.id }, detail: { summary, simulated: true, mode: r.mode, article_id: a.id, version: r.version }, userId: user.id });
  return { ok: true, status: a.status, simulated: true, message: r.mode === 'schedule' ? 'Demo only: marked as scheduled. Nothing was sent to Shopify.' : 'Demo only: marked as published. Nothing was sent to a storefront.' };
}

function resetArticleAfterRequest(a, user, note) {
  if (['publish_requested', 'failed'].includes(a.status)) { a.status = 'approved'; a.publish_at = null; a.last_error = null; a.updated_at = nowIso(); }
  void user; void note;
}

/* ---------------- seed ---------------- */

export function seed(db) {
  db.articles = []; db.articleVersions = []; db.reviewNotes = []; db.publishRequests = []; db.topics = []; db.keywords = []; db.audit = [];
  const events = [];
  const ev = (hoursBefore, e) => events.push({ ...e, hoursBefore });
  let reqSeq = 1;

  ARTICLE_SPECS.forEach((s, i) => {
    const id = i + 1;
    const author = userOf(s.author);
    const content = {
      title: s.title, handle: s.handle, primary_keyword: s.kw, meta_title: s.metaTitle ?? '', meta_description: s.meta ?? '', summary_html: s.summary ? `<p>${s.summary}</p>` : '',
      body_html: s.body ?? '', tags: s.tags ?? '', author: BRAND_NAME[s.brand], image_url: s.body || s.status !== 'idea' ? `${process.env.NEXT_PUBLIC_BASE_PATH ?? ''}/demo/tile-${s.img ?? 1}.svg` : '',
      image_alt: s.body || s.status !== 'idea' ? `Demo image for ${s.title}` : '',
    };
    const created = daysAgo(s.createdD);
    const hash = hashOf(content);
    const bound = APPROVAL_BOUND.includes(s.status);
    const events0 = [s.createdD * 24, ...(s.notes ?? []).map((n) => n[2]), s.req?.hoursAgo ?? 9999, s.publishedD ? s.publishedD * 24 : 9999];
    const lastH = s.publishedD ? Math.max(2, s.publishedD * 24 - 3) : Math.min(...events0.slice(1)) < 9999 ? Math.min(...events0.slice(1)) : Math.max(2, s.createdD * 6);
    const published = s.status === 'published';
    const a = {
      id, brand_id: s.brand, topic_id: null, ...content, status: s.status, version: s.version, content_hash: hash,
      approved_hash: bound ? hash : null, approved_at: bound ? hoursAgo(Math.max(1, lastH - 1)) : null, live_hash: published ? hash : null,
      review_note: s.reviewNote ?? '', assignee_id: s.author, created_by: s.author, origin: s.origin ?? 'app', created_at: created, updated_at: hoursAgo(lastH),
      shopify_article_id: published || s.shopifyHidden || s.shopifyScheduledH ? `demo-article-${id}` : null, shopify_published: published,
      published_at: published ? daysAgo(s.publishedD) : s.shopifyScheduledH ? hoursAgo(s.shopifyScheduledH) : null,
      shopify_synced_at: published || s.shopifyHidden || s.shopifyScheduledH ? hoursAgo(5) : null,
      live_url: published ? liveUrl(s.brand, s.handle) : null, publish_at: s.status === 'scheduled' ? hoursAgo(s.publishAtH) : s.req?.mode === 'schedule' && s.req.status === 'pending' ? hoursAgo(s.req.publishAtH) : null,
      last_error: s.lastError ?? null, demo_draft_at: null, demo: { traffic: s.traffic ?? 0, trend: s.trend ?? 0 },
    };
    db.articles.push(a);

    // versions: older ones are shorter / lack the meta description
    for (let v = 1; v <= s.version; v++) {
      const old = v < s.version;
      const body = old && content.body_html.includes('<h2') ? content.body_html.slice(0, content.body_html.lastIndexOf('<h2')) : content.body_html;
      const data = { ...content, body_html: body, meta_description: v === 1 ? '' : content.meta_description };
      const hrs = (s.createdD * 24) - ((s.createdD * 24 - lastH) * (v - 1)) / Math.max(1, s.version - 1);
      db.articleVersions.push({ id: db.articleVersions.length + 1, article_id: id, version: v, note: v === 1 ? (s.origin === 'shopify_admin' ? 'Imported (shopify_admin)' : s.origin === 'claude' ? 'Created by the demo AI step' : 'Created') : v === s.version ? (s.status === 'changes_requested' ? 'Addressed first round of notes' : 'Edited') : 'Edited',
        user_id: s.author, user_name: author?.name, created_at: hoursAgo(v === s.version ? lastH + 1 : Math.max(lastH + 2, hrs)), content_hash: old ? hashOf(data) : hash, data: old ? data : content });
    }

    ev(s.createdD * 24, { action: 'article.create', brand: s.brand, entity: { type: 'article', id }, detail: { summary: content.title, origin: a.origin }, userId: s.author });
    // review notes
    let notes = s.notes;
    if (!notes && bound) notes = [['submitted', s.author, lastH + 30, '', s.version], ['approved', 3, lastH + 24, 'Approved.', s.version]];
    for (const [kind, uid, h, text, ver] of notes ?? []) {
      db.reviewNotes.push({ id: db.reviewNotes.length + 1, article_id: id, version: ver, reviewer_id: uid, reviewer_name: userOf(uid)?.name, kind, note: text, created_at: hoursAgo(h), source: 'app' });
      ev(h, { action: kind === 'submitted' ? 'article.submit' : kind === 'approved' ? 'article.approve' : 'article.request_changes', brand: s.brand, entity: { type: 'article', id }, detail: { summary: `${content.title} (v${ver})${text ? `: ${text}` : ''}` }, userId: uid });
    }
    // publish requests
    const rs = s.req ?? (published ? { mode: 'publish_now', requestedBy: s.author, hoursAgo: s.publishedD * 24 + 2, status: 'executed', decidedBy: 3, decidedHoursAgo: s.publishedD * 24, note: '', decisionNote: 'Authorized.' } : null);
    if (rs) {
      const r = { id: reqSeq++, article_id: id, brand_id: s.brand, version: s.version, mode: rs.mode, publish_at: rs.publishAtH !== undefined ? hoursAgo(rs.publishAtH) : null, status: rs.status, note: rs.note ?? '',
        requested_by: rs.requestedBy, requested_at: hoursAgo(rs.hoursAgo), decided_by: rs.decidedBy ?? null, decided_at: rs.decidedHoursAgo !== undefined ? hoursAgo(rs.decidedHoursAgo) : null,
        decision_note: rs.decisionNote ?? '', content_hash: hash, attempts: rs.attempts ?? (rs.status === 'executed' ? 1 : 0), error: rs.error ?? null };
      db.publishRequests.push(r);
      ev(rs.hoursAgo, { action: 'publish.request', brand: s.brand, entity: { type: 'publish_request', id: r.id }, detail: { summary: `${MODE[rs.mode]} requested for "${content.title}"` }, userId: rs.requestedBy });
      if (rs.status === 'executed') ev(rs.decidedHoursAgo, { action: 'publish.authorize', brand: s.brand, entity: { type: 'publish_request', id: r.id }, detail: { summary: `Simulated: marked as ${rs.mode === 'schedule' ? 'scheduled' : 'published'} in the demo. ${DEMO_NOTE}`, simulated: true }, userId: rs.decidedBy });
      if (rs.status === 'failed') ev(rs.decidedHoursAgo, { action: 'publish.failed', brand: s.brand, entity: { type: 'publish_request', id: r.id }, detail: { summary: rs.error, simulated: true }, userId: null });
    }
  });

  // topics
  TOPIC_SPECS.forEach((t, i) => {
    const [brand, title, kw, sec, intent, vol, kd, status, source, articleKey, notes, rationale, validation] = t;
    const art = articleKey ? db.articles[ARTICLE_SPECS.findIndex((s) => s.key === articleKey)] : null;
    const rec = { id: i + 1, brand_id: brand, title, primary_keyword: kw, secondary_keywords: sec, intent, search_volume: vol, keyword_difficulty: kd, volume_source: vol ? 'Sample keyword data (demo)' : '',
      status, source, notes, rationale, validation_note: validation, article_id: art?.id ?? null, created_at: daysAgo(40 - i), updated_at: daysAgo(Math.max(0.3, 14 - i)) };
    db.topics.push(rec);
    if (art) art.topic_id = rec.id;
  });
  ev(2 * 24, { action: 'topic.decision', brand: 'ridhi', entity: { type: 'topic', id: 7 }, detail: { summary: 'Approved: autumn hosting with cotton linen' }, userId: 3 });
  ev(5 * 24, { action: 'topic.decision', brand: 'ridhi', entity: { type: 'topic', id: 11 }, detail: { summary: 'Rejected: wholesale buyers guide (not a consumer topic)' }, userId: 3 });

  // keywords
  KEYWORD_SPECS.forEach(([brand, keyword, vol, kd, intent, old], i) => {
    db.keywords.push({ id: i + 1, brand_id: brand, keyword, search_volume: vol, keyword_difficulty: kd, intent, source_tool: 'Sample tool export', source: 'demo', source_date: daysAgo(old).slice(0, 10) });
  });
  ev(20 * 24, { action: 'data.import', brand: 'ridhi', entity: { type: 'keywords', id: '' }, detail: { summary: 'Imported 24 sample keywords (demo)' }, userId: 2 });
  ev(15 * 24, { action: 'data.import', brand: 'cpc', entity: { type: 'keywords', id: '' }, detail: { summary: 'Imported 19 sample keywords (demo)' }, userId: 2 });
  ev(3, { action: 'analytics.sync', brand: 'ridhi', entity: { type: 'integration', id: 'gsc' }, detail: { summary: 'Simulated Search Console sync (demo): no request was made to Google', simulated: true }, userId: 2 });

  events.sort((x, y) => y.hoursBefore - x.hoursBefore);
  for (const e of events) addAudit(db, { action: e.action, brand: e.brand, entity: e.entity, detail: e.detail, userId: e.userId, ts: hoursAgo(e.hoursBefore) });
  db.analyticsSync = { ridhi: { gsc: hoursAgo(3), ga4: hoursAgo(3) }, cpc: { gsc: hoursAgo(3), ga4: hoursAgo(3) } };
}

const MODE = { publish_now: 'Publish now', schedule: 'Schedule', update_live: 'Update live article' };

/* ---------------- synthetic analytics (one generator for every consumer) ---------------- */

const DAY = 86400000;
const dayIdx = (iso) => Math.floor(Date.parse(iso.length === 10 ? `${iso}T00:00:00Z` : iso) / DAY);
const idxToDay = (i) => new Date(i * DAY).toISOString().slice(0, 10);
const todayIdx = () => Math.floor(Date.now() / DAY);
const DOW = [0.8, 1.05, 1.1, 1.1, 1.05, 1, 0.85];
const mix = (a, b) => {
  let h = Math.imul(a ^ 0x9e3779b9, 0x85ebca6b) ^ Math.imul(b + 0x7f4a7c15, 0xc2b2ae35);
  h ^= h >>> 13; h = Math.imul(h, 0xc2b2ae3d); h ^= h >>> 16;
  return (h >>> 0) / 4294967296;
};
const liveArticles = (db, brand) => db.articles.filter((a) => a.brand_id === brand && a.shopify_published && a.live_url && a.published_at);

function dayMetrics(a, idx) {
  const pub = dayIdx(a.published_at);
  if (idx < pub) return null;
  const d = a.demo ?? { traffic: 0.6, trend: 0 };
  const base = 22 * d.traffic;
  if (base <= 0) return { clicks: 0, impressions: 0, position: 12, sessions: 0, engaged: 0, keyEvents: 0, secs: 0 };
  const ramp = Math.min(1, 0.35 + (idx - pub) * 0.08);
  const f = Math.max(0.15, 1 + d.trend * (idx - todayIdx()));
  const clicks = Math.max(0, Math.round(base * DOW[(idx + 4) % 7] * f * ramp * (0.7 + 0.6 * mix(a.id * 7 + 1, idx))));
  const ctr = 0.028 + (a.id % 5) * 0.006;
  const impressions = Math.round((clicks / ctr) * (0.9 + 0.2 * mix(a.id * 7 + 2, idx)));
  const sessions = Math.round(clicks * 1.9 * (0.85 + 0.3 * mix(a.id * 7 + 3, idx)));
  return {
    clicks, impressions, position: 6 + (a.id % 7) * 1.3 + (mix(a.id * 7 + 5, idx) - 0.5) * 1.2, sessions,
    engaged: Math.round(sessions * (0.55 + (a.id % 4) * 0.04)), keyEvents: Math.round(sessions * 0.03 * (0.5 + mix(a.id * 7 + 4, idx))), secs: 60 + (a.id % 6) * 14,
  };
}

/** Last day that has data: yesterday (Google reports with a delay). */
const lastDataIdx = () => todayIdx() - 1;

function aggregate(arts, fromI, toI) {
  const per = new Map(arts.map((a) => [a.id, { clicks: 0, impressions: 0, pw: 0, sessions: 0, engaged: 0, keyEvents: 0, secW: 0 }]));
  const series = [];
  for (let i = fromI; i <= Math.min(toI, lastDataIdx()); i++) {
    const day = { date: idxToDay(i), clicks: 0, impressions: 0, pw: 0, sessions: 0, engaged: 0, key_events: 0 };
    for (const a of arts) {
      const m = dayMetrics(a, i);
      if (!m) continue;
      const p = per.get(a.id);
      p.clicks += m.clicks; p.impressions += m.impressions; p.pw += m.position * m.impressions; p.sessions += m.sessions; p.engaged += m.engaged; p.keyEvents += m.keyEvents; p.secW += m.secs * m.sessions;
      day.clicks += m.clicks; day.impressions += m.impressions; day.pw += m.position * m.impressions; day.sessions += m.sessions; day.engaged += m.engaged; day.key_events += m.keyEvents;
    }
    series.push(day);
  }
  const tot = { clicks: 0, impressions: 0, pw: 0, sessions: 0, engaged: 0, keyEvents: 0, secW: 0 };
  for (const p of per.values()) for (const k of Object.keys(tot)) tot[k] += p[k];
  return { per, series, tot };
}

function resolveRange(query) {
  const to = (query.to ?? '').slice(0, 10) || idxToDay(todayIdx());
  const from = (query.from ?? '').slice(0, 10) || idxToDay(todayIdx() - 27);
  const fromI = dayIdx(from); const toI = Math.max(fromI, dayIdx(to));
  const n = toI - fromI + 1;
  return { from, to, fromI, toI, n, prev: { from: idxToDay(fromI - n), to: idxToDay(fromI - 1) }, prevFromI: fromI - n, prevToI: fromI - 1 };
}

const demoSource = (db, brand, key, r) => {
  const covTo = idxToDay(Math.min(r.toI, lastDataIdx()));
  return { kind: 'demo', label: 'Demo data', state: r.toI > lastDataIdx() ? 'partial' : 'ok', syncedAt: db.analyticsSync?.[brand]?.[key] ?? null, lastError: null, coverage: { from: r.from, to: covTo } };
};

const gscTotals = (t) => ({ clicks: t.clicks, impressions: t.impressions, ctr: t.impressions ? t.clicks / t.impressions : null, position: t.impressions ? t.pw / t.impressions : null });
const ga4Totals = (t) => ({ sessions: t.sessions, engagedSessions: t.engaged, engagementRate: t.sessions ? t.engaged / t.sessions : null, avgEngagementSeconds: t.sessions ? t.secW / t.sessions : null, keyEvents: t.keyEvents });

/** Search query rows for a brand's live articles over the fixed period (last 28 days up to yesterday). */
function queryPeriod(db, brand) {
  const toI = lastDataIdx(); const fromI = toI - 27;
  const arts = liveArticles(db, brand);
  const { per } = aggregate(arts, fromI, toI);
  const rows = [];
  const weights = [0.34, 0.24, 0.17, 0.13, 0.12];
  for (const a of arts) {
    const p = per.get(a.id);
    const apos = p.impressions ? p.pw / p.impressions : 9;
    weights.forEach((w, k) => {
      const n = 0.9 + 0.2 * mix(a.id * 13 + k, 7);
      const impressions = Math.round(p.impressions * w * n);
      const clicks = Math.round(p.clicks * w * n * (k === 0 ? 1.15 : 0.9));
      if (!impressions) return;
      rows.push({ query: `${a.primary_keyword}${QUERY_MODIFIERS[(k + a.id) % QUERY_MODIFIERS.length]}`.trim(), clicks, impressions, position: Math.round((apos + k * 2.4 + mix(a.id * 17 + k, 3)) * 10) / 10, ctr: impressions ? clicks / impressions : null, page: pathOf(a), article_id: a.id });
    });
  }
  return { period: { from: idxToDay(fromI), to: idxToDay(toI) }, rows };
}

function gscReport(db, brand, r) {
  const arts = liveArticles(db, brand);
  const cur = aggregate(arts, r.fromI, r.toI);
  const prv = aggregate(arts, r.prevFromI, r.prevToI);
  const source = demoSource(db, brand, 'gsc', r);
  const pages = arts.filter((a) => cur.per.get(a.id).impressions || prv.per.get(a.id).clicks).map((a) => {
    const p = cur.per.get(a.id);
    return { page: pathOf(a), clicks: p.clicks, impressions: p.impressions, position: p.impressions ? p.pw / p.impressions : null, ctr: p.impressions ? p.clicks / p.impressions : null,
      prevClicks: prv.per.get(a.id).clicks, article: { id: a.id, title: a.title } };
  }).sort((x, y) => y.clicks - x.clicks);
  const declining = pages.filter((p) => p.prevClicks >= 5 && p.clicks < p.prevClicks * 0.75).map((p) => ({ ...p, change: p.clicks - p.prevClicks })).sort((x, y) => x.change - y.change).slice(0, 10);
  const qp = queryPeriod(db, brand);
  const idx = new Map(arts.map((a) => [pathOf(a), { id: a.id, title: a.title }]));
  const queries = { period: qp.period, rows: [...qp.rows].sort((x, y) => y.clicks - x.clicks || y.impressions - x.impressions).slice(0, 50).map(({ article_id, ...q }) => q) };
  const opportunities = qp.rows.filter((q) => q.position >= 4 && q.position <= 20 && q.impressions >= 20).sort((x, y) => y.impressions - x.impressions).slice(0, 12).map(({ article_id, ...q }) => ({ ...q, article: idx.get(q.page) ?? null }));
  return { brand, source, totals: gscTotals(cur.tot), previous: gscTotals(prv.tot), previousRange: r.prev,
    series: cur.series.map((d) => ({ date: d.date, clicks: d.clicks, impressions: d.impressions, position: d.impressions ? d.pw / d.impressions : null })),
    pages, queries, declining, opportunities };
}

function ga4Report(db, brand, r) {
  const arts = liveArticles(db, brand);
  const cur = aggregate(arts, r.fromI, r.toI);
  const prv = aggregate(arts, r.prevFromI, r.prevToI);
  const pages = arts.filter((a) => cur.per.get(a.id).sessions).map((a) => {
    const p = cur.per.get(a.id);
    return { page_path: pathOf(a), sessions: p.sessions, engaged: p.engaged, avg_seconds: p.sessions ? p.secW / p.sessions : null, key_events: p.keyEvents, engagementRate: p.sessions ? p.engaged / p.sessions : null, article: { id: a.id, title: a.title } };
  }).sort((x, y) => y.sessions - x.sessions);
  return { brand, source: demoSource(db, brand, 'ga4', r), totals: ga4Totals(cur.tot), previous: ga4Totals(prv.tot), previousRange: r.prev,
    series: cur.series.map((d) => ({ date: d.date, sessions: d.sessions, engaged: d.engaged, key_events: d.key_events })), pages };
}

function articlePerformance(db, brand, r) {
  const arts = liveArticles(db, brand);
  const cur = aggregate(arts, r.fromI, r.toI);
  const rows = arts.filter((a) => dayIdx(a.published_at) <= r.toI).sort((x, y) => Date.parse(y.published_at) - Date.parse(x.published_at)).map((a) => {
    const p = cur.per.get(a.id);
    return { id: a.id, title: a.title, status: a.status, url: a.live_url, published_at: a.published_at, live: true,
      clicks: p.clicks, impressions: p.impressions, ctr: p.impressions ? p.clicks / p.impressions : null, position: p.impressions ? p.pw / p.impressions : null,
      sessions: p.sessions, engagementRate: p.sessions ? p.engaged / p.sessions : null, keyEvents: p.keyEvents };
  });
  const s = (key) => demoSource(db, brand, key, r);
  return { brand, sources: { gsc: s('gsc'), ga4: s('ga4') }, rows };
}

/** Totals and daily clicks for Home, from the same generator the SEO & traffic page uses. */
export function trafficSummary(db, brandId, from, to) {
  const arts = liveArticles(db, brandId);
  const { tot, series } = aggregate(arts, dayIdx(from), dayIdx(to));
  return { clicks: tot.clicks, impressions: tot.impressions, sessions: tot.sessions, series: series.map((d) => ({ date: d.date, clicks: d.clicks })) };
}

/** Same definitions as services/home.py _articles. */
export function articleCounts(db, brandId) {
  const arts = db.articles.filter((a) => a.brand_id === brandId);
  const n = (s) => arts.filter((a) => a.status === s).length;
  const pend = db.publishRequests.filter((r) => r.brand_id === brandId && r.status === 'pending').length;
  return { total: arts.length, live: arts.filter((a) => a.shopify_published).length, drafts: n('idea') + n('draft') + n('changes_requested'), pendingApproval: n('in_review') + pend };
}

const ROLE_CAN = {
  admin: ['article:review', 'publish:authorize', 'article:write', 'topic:decide'],
  seo_manager: ['article:write', 'topic:decide'],
  reviewer: ['article:review', 'publish:authorize'],
};

/** The /tasks list for a role, as services/api.py _tasks_for builds it. */
export function tasksFor(db, role, userId) {
  const can = ROLE_CAN[role] ?? [];
  const out = [];
  const add = (rows, kind, action, link, since = 'updated_at') => out.push(...rows.map((r) => ({ kind, brand: r.brand_id, title: r.title, action, link: link(r), since: r[since] })));
  const byOld = (arr, k = 'updated_at') => [...arr].sort((x, y) => x[k].localeCompare(y[k]));
  const A = db.articles;
  if (can.includes('article:review')) add(byOld(A.filter((a) => a.status === 'in_review')), 'review', 'Review content', (r) => `/articles/${r.id}?tab=review`);
  if (can.includes('publish:authorize')) {
    const rows = byOld(db.publishRequests.filter((r) => r.status === 'pending' && (r.requested_by !== userId || role === 'admin')), 'requested_at')
      .map((r) => ({ brand_id: r.brand_id, title: A.find((a) => a.id === r.article_id)?.title ?? '', requested_at: r.requested_at }));
    add(rows, 'authorize', 'Authorize publishing', () => '/publishing', 'requested_at');
  }
  if (can.includes('article:write')) {
    add(byOld(A.filter((a) => a.status === 'changes_requested')), 'changes', 'Address review notes', (r) => `/articles/${r.id}`);
    add(byOld(A.filter((a) => a.status === 'failed')), 'failed', 'Fix failed publish', () => '/publishing');
    add(byOld(A.filter((a) => a.status === 'approved' && a.approved_hash === a.content_hash)), 'request', 'Request publishing', (r) => `/articles/${r.id}?tab=publish`);
    add(byOld(A.filter((a) => ['draft', 'idea'].includes(a.status) && a.assignee_id === userId)), 'draft', 'Finish your draft', (r) => `/articles/${r.id}`);
  }
  if (can.includes('topic:decide')) add(byOld(db.topics.filter((t) => t.status === 'validated')), 'topic', 'Approve or reject topic', () => '/topics?status=validated');
  return out;
}

/* ---------------- routes ---------------- */

const brandQ = (q) => (q.brand && q.brand !== 'all' ? q.brand : null);
const brandsFor = (q) => (brandQ(q) ? [brandQ(q)] : BRAND_IDS);
const checkBrand = (b) => { need(BRAND_IDS.includes(b), 400, 'Choose a brand.', 'bad_brand'); return b; };
const inRange = (iso, from, to) => (!from || iso.slice(0, 10) >= from) && (!to || iso.slice(0, 10) <= to);

function filterArticles(db, q) {
  tick(db);
  const statuses = list(q.status);
  const brand = brandQ(q);
  return db.articles.filter((a) => (!brand || a.brand_id === brand) && (!statuses.length || statuses.includes(a.status))
    && (q.live === '1' ? a.shopify_published : q.live === '0' ? !a.shopify_published : true)
    && (!q.assignee || String(a.assignee_id) === String(q.assignee))
    && matches(q.q, a.title, a.primary_keyword, a.handle, a.tags));
}

function filterTopics(db, q) {
  const brand = brandQ(q);
  return db.topics.filter((t) => (!brand || t.brand_id === brand) && (!q.status || list(q.status).includes(t.status)) && (q.missing !== 'volume' || t.search_volume == null) && matches(q.q, t.title, t.primary_keyword, t.secondary_keywords))
    .sort((x, y) => y.updated_at.localeCompare(x.updated_at));
}

const filterKeywords = (db, q) => db.keywords.filter((k) => (!brandQ(q) || k.brand_id === brandQ(q)) && matches(q.q, k.keyword)).sort((x, y) => (y.search_volume ?? -1) - (x.search_volume ?? -1));

function topicFields(body, base = {}) {
  const f = { ...base };
  for (const k of ['title', 'primary_keyword', 'secondary_keywords', 'volume_source', 'notes']) if (k in body) f[k] = String(body[k] ?? '').trim();
  if ('intent' in body) f.intent = body.intent || 'informational';
  if ('search_volume' in body) f.search_volume = num(body.search_volume);
  if ('keyword_difficulty' in body) f.keyword_difficulty = num(body.keyword_difficulty);
  return f;
}

function draftBodyFor(topic) {
  const k = topic.primary_keyword;
  return `<p>This is a placeholder first draft created in the demo for "${topic.title}". In the real product an AI worker would write it; here it is fixed sample text to show the workflow.</p>\n<h2>What to know about ${k}</h2>\n<p>Explain the main idea in plain, warm language and mention how ${k} fits into everyday home life.</p>\n<h2>Practical tips</h2>\n<ul><li>Start with the simplest option.</li><li>Keep care instructions short and clear.</li></ul>\n<p>Edit this draft, add internal links to the store, then send it for review.</p>`;
}

function newArticle(db, user, brand, c, extra = {}) {
  const content = { title: c.title, handle: uniqueHandle(db, brand, c.handle || c.title), primary_keyword: c.primary_keyword ?? '', meta_title: '', meta_description: '', summary_html: '', body_html: sanitize(c.body_html ?? ''),
    tags: '', author: c.author || BRAND_NAME[brand], image_url: '', image_alt: '' };
  const t = nowIso();
  const a = { id: nextIdOf(db.articles), brand_id: brand, topic_id: extra.topic_id ?? null, ...content, status: extra.status ?? (content.body_html ? 'draft' : 'idea'), version: 1, content_hash: hashOf(content),
    approved_hash: null, approved_at: null, live_hash: null, review_note: '', assignee_id: user.id, created_by: user.id, origin: extra.origin ?? 'app', created_at: t, updated_at: t,
    shopify_article_id: null, shopify_published: false, published_at: null, shopify_synced_at: null, live_url: null, publish_at: null, last_error: null, demo_draft_at: null, demo: { traffic: 0.6, trend: 0 } };
  db.articles.push(a);
  snapshot(db, a, user.id, extra.origin === 'claude' ? 'Created by the demo AI step' : 'Created');
  addAudit(db, { action: 'article.create', brand, entity: { type: 'article', id: a.id }, detail: { summary: a.title, origin: a.origin }, userId: user.id });
  return a;
}

export const routes = [
  /* ----- articles ----- */
  ['GET', '/articles', ({ query, db }) => {
    const rows = filterArticles(db, query);
    const key = query.sort === 'title' ? 'title' : query.sort === 'status' ? 'status' : 'updated_at';
    const dir = query.dir === 'asc' ? 1 : -1;
    rows.sort((x, y) => dir * (key === 'status' ? STATUS_ORDER.indexOf(x.status) - STATUS_ORDER.indexOf(y.status) : String(x[key]).localeCompare(String(y[key]))));
    const limit = Number(query.limit) || 50; const offset = Number(query.offset) || 0;
    return { total: rows.length, rows: rows.slice(offset, offset + limit).map((a) => decorate(db, a, false)) };
  }],
  ['GET', '/articles/counts', ({ query, db }) => {
    tick(db);
    const rows = db.articles.filter((a) => !brandQ(query) || a.brand_id === brandQ(query));
    return STATUS_ORDER.map((status) => ({ status, n: rows.filter((a) => a.status === status).length })).filter((c) => c.n);
  }],
  ['POST', '/articles', ({ body, db }) => {
    const user = actorOf(db);
    const brand = checkBrand(body.brand_id);
    need(String(body.title ?? '').trim(), 400, 'A title is required.', 'bad_request');
    return decorate(db, newArticle(db, user, brand, { ...body, title: String(body.title).trim() }));
  }],
  ['GET', '/articles/:id/revisions/:rev', ({ params, db }) => {
    const v = db.articleVersions.find((x) => x.id === Number(params.rev) && x.article_id === Number(params.id));
    need(v, 404, 'Version not found.', 'not_found');
    return v;
  }],
  ['GET', '/articles/:id', ({ params, db }) => {
    tick(db);
    const a = getArticle(db, params.id);
    const cur = db.articleVersions.filter((v) => v.article_id === a.id).sort((x, y) => y.version - x.version).map(({ data, ...v }) => v);
    const qp = a.live_url ? queryPeriod(db, a.brand_id) : null;
    return {
      article: decorate(db, a),
      revisions: cur,
      notes: db.reviewNotes.filter((n) => n.article_id === a.id).sort((x, y) => y.created_at.localeCompare(x.created_at)),
      requests: db.publishRequests.filter((r) => r.article_id === a.id).sort((x, y) => y.id - x.id).map((r) => decorateRequest(db, r)),
      topic: a.topic_id ? db.topics.find((t) => t.id === a.topic_id) ?? null : null,
      queries: qp ? { source: 'demo', period: qp.period, rows: qp.rows.filter((q) => q.article_id === a.id).sort((x, y) => y.clicks - x.clicks).map(({ article_id, page, ...q }) => q) } : null,
      assignees: USERS.filter((u) => ['seo_manager', 'admin'].includes(u.role)).map((u) => ({ id: u.id, name: u.name, role: u.role })),
    };
  }],
  ['PATCH', '/articles/:id', ({ params, body, db }) => {
    const user = actorOf(db);
    const a = getArticle(db, params.id);
    if (body.expected_version !== undefined && body.expected_version !== null) {
      need(Number(body.expected_version) === a.version, 409, `Someone saved version ${a.version} while you were editing. Reload to see their changes before saving.`, 'version_conflict');
    }
    need(a.status !== 'scheduled' || !CONTENT_FIELDS.some((f) => f in body), 409, 'This article is scheduled. Withdraw the schedule from Publishing before editing.', 'scheduled');
    const before = contentOf(a);
    const next = { ...before };
    const raw = (f) => (f in body ? String(body[f] ?? '') : null);
    for (const f of ['title', 'primary_keyword', 'meta_title', 'meta_description', 'author', 'image_url', 'image_alt']) if (raw(f) !== null) next[f] = raw(f).trim();
    if (raw('summary_html') !== null) next.summary_html = sanitize(raw('summary_html'));
    if (raw('body_html') !== null) next.body_html = sanitize(raw('body_html'));
    if (raw('tags') !== null) next.tags = [...new Set(String(body.tags).split(',').map((t) => t.trim()).filter(Boolean))].slice(0, 30).join(', ');
    need(next.title, 400, 'A title is required.', 'bad_request');
    if (raw('handle') !== null && slugify(body.handle) !== before.handle) {
      need(!a.shopify_published, 409, 'The URL handle of a live article cannot change here; it would break the published link.', 'handle_locked');
      next.handle = uniqueHandle(db, a.brand_id, body.handle || next.title, a.id);
    }
    if ('assignee_id' in body) { a.assignee_id = body.assignee_id ? Number(body.assignee_id) : null; if (!CONTENT_FIELDS.some((f) => next[f] !== before[f])) addAudit(db, { action: 'article.assign', brand: a.brand_id, entity: { type: 'article', id: a.id }, detail: `Assignee set to ${userOf(a.assignee_id)?.name ?? 'nobody'}`, userId: user.id }); }
    if ('topic_id' in body) a.topic_id = body.topic_id ? Number(body.topic_id) : null;
    const changed = CONTENT_FIELDS.filter((f) => next[f] !== before[f]);
    if (changed.length) {
      const was = a.status;
      applyContent(db, a, next, user, String(body.note ?? '').slice(0, 300));
      addAudit(db, { action: 'article.save', brand: a.brand_id, entity: { type: 'article', id: a.id }, detail: { summary: `Saved v${a.version} of "${a.title}" (${changed.join(', ')})${was !== a.status ? `; status ${was} to ${a.status}` : ''}`, fields: changed }, userId: user.id });
    }
    return decorate(db, a);
  }],
  ['POST', '/articles/:id/submit', ({ params, db }) => {
    const user = actorOf(db);
    const a = getArticle(db, params.id);
    need(['draft', 'idea', 'changes_requested', 'failed'].includes(a.status), 409, `An article in status "${a.status}" cannot be sent for review.`, 'bad_state');
    need(a.title && (a.body_html || '').replace(/<[^>]+>/g, '').trim(), 400, 'Write some text before sending for review.', 'empty_body');
    cancelOpenRequests(db, a, 'Sent back for review');
    a.status = 'in_review'; a.review_note = ''; a.updated_at = nowIso();
    addNote(db, a, user, 'submitted', '');
    addAudit(db, { action: 'article.submit', brand: a.brand_id, entity: { type: 'article', id: a.id }, detail: `Sent "${a.title}" (v${a.version}) for review`, userId: user.id });
    return decorate(db, a);
  }],
  ['POST', '/articles/:id/review', ({ params, body, db }) => {
    const user = actorOf(db);
    const a = getArticle(db, params.id);
    need(a.status === 'in_review', 409, 'This article is not waiting for review.', 'bad_state');
    need(Number(body.version) === a.version, 409, `Version ${a.version} was saved while you read. Review the latest text.`, 'version_changed');
    if (body.decision === 'approve') {
      a.status = 'approved'; a.approved_hash = a.content_hash; a.approved_at = nowIso(); a.review_note = '';
      addNote(db, a, user, 'approved', body.note);
      addAudit(db, { action: 'article.approve', brand: a.brand_id, entity: { type: 'article', id: a.id }, detail: `Approved "${a.title}" v${a.version}${body.note ? `: ${body.note}` : ''}`, userId: user.id });
    } else if (body.decision === 'request_changes') {
      need(String(body.note ?? '').trim(), 400, 'Add a note so the writer knows what to change.', 'note_required');
      a.status = 'changes_requested'; a.review_note = String(body.note).trim();
      addNote(db, a, user, 'changes_requested', a.review_note);
      addAudit(db, { action: 'article.request_changes', brand: a.brand_id, entity: { type: 'article', id: a.id }, detail: `Requested changes on "${a.title}" v${a.version}: ${a.review_note}`, userId: user.id });
    } else throw new DemoError(400, 'Choose approve or request changes.', 'bad_request');
    a.updated_at = nowIso();
    return decorate(db, a);
  }],
  ['POST', '/articles/:id/shopify-draft', ({ params, db }) => {
    const user = actorOf(db);
    const a = getArticle(db, params.id);
    need(!!a.approved_hash && a.approved_hash === a.content_hash, 409, 'Only reviewer-approved content can be saved to Shopify. Send it for review first.', 'not_approved');
    need(!a.shopify_published, 409, 'This article is already live; use an update request instead.', 'bad_state');
    a.demo_draft_at = nowIso();
    addAudit(db, { action: 'shopify.draft', brand: a.brand_id, entity: { type: 'article', id: a.id }, detail: { summary: `Simulated hidden draft prepared for "${a.title}" v${a.version}. ${DEMO_NOTE}`, simulated: true }, userId: user.id });
    return { ok: true, simulated: true, message: 'Demo only: draft prepared in the demo. Nothing was sent to Shopify.' };
  }],
  ['POST', '/articles/:id/publish-request', ({ params, body, db }) => {
    const user = actorOf(db);
    const a = getArticle(db, params.id);
    need(a.status === 'approved' && a.approved_hash === a.content_hash, 409, 'Publishing requests open once a reviewer approves the current version.', 'not_approved');
    need(!db.publishRequests.some((r) => r.article_id === a.id && r.status === 'pending'), 409, 'A request is already waiting for this article.', 'duplicate');
    const mode = a.shopify_published ? 'update_live' : body.mode === 'schedule' ? 'schedule' : 'publish_now';
    let at = null;
    if (mode === 'schedule') {
      at = body.publish_at ? new Date(body.publish_at) : null;
      need(at && !Number.isNaN(at.getTime()), 400, 'Choose a date and time.', 'bad_request');
      need(at.getTime() > Date.now() + 10 * 60000, 400, 'Choose a time at least 15 minutes from now.', 'bad_time');
      at = at.toISOString();
    }
    const r = { id: nextIdOf(db.publishRequests), article_id: a.id, brand_id: a.brand_id, version: a.version, mode, publish_at: at, status: 'pending', note: String(body.note ?? '').slice(0, 300),
      requested_by: user.id, requested_at: nowIso(), decided_by: null, decided_at: null, decision_note: '', content_hash: a.content_hash, attempts: 0, error: null };
    db.publishRequests.push(r);
    a.status = 'publish_requested'; a.publish_at = at; a.updated_at = nowIso();
    addAudit(db, { action: 'publish.request', brand: a.brand_id, entity: { type: 'publish_request', id: r.id }, detail: { summary: `${MODE[mode]} requested for "${a.title}" v${a.version}`, mode }, userId: user.id });
    return decorateRequest(db, r);
  }],
  ['POST', '/articles/:id/restore/:rev', ({ params, db }) => {
    const user = actorOf(db);
    const a = getArticle(db, params.id);
    need(a.status !== 'scheduled', 409, 'Withdraw the schedule from Publishing before restoring a version.', 'scheduled');
    const v = db.articleVersions.find((x) => x.id === Number(params.rev) && x.article_id === a.id);
    need(v, 404, 'Version not found.', 'not_found');
    const next = { ...v.data };
    if (next.handle !== a.handle && a.shopify_published) next.handle = a.handle;
    applyContent(db, a, next, user, `Restored from v${v.version}`);
    addAudit(db, { action: 'article.restore', brand: a.brand_id, entity: { type: 'article', id: a.id }, detail: `Restored v${v.version} of "${a.title}" as v${a.version}`, userId: user.id });
    return decorate(db, a);
  }],
  ['GET', '/brands/:id/products', ({ params }) => {
    const p = productsFor(params.id);
    need(p, 404, 'Unknown brand.', 'not_found');
    return p;
  }],

  /* ----- publishing ----- */
  ['GET', '/publishing', ({ query, db }) => {
    tick(db);
    const ids = brandsFor(query);
    const order = { pending: 0, failed: 1 };
    const requests = db.publishRequests.filter((r) => ids.includes(r.brand_id)).map((r) => decorateRequest(db, r))
      .sort((x, y) => (order[x.status] ?? 2) - (order[y.status] ?? 2) || y.requested_at.localeCompare(x.requested_at)).slice(0, 200);
    const arts = db.articles.filter((a) => ids.includes(a.brand_id));
    const unseen = arts.filter((a) => a.shopify_article_id && !a.shopify_published).map((a) => ({ id: a.id, brand_id: a.brand_id, title: a.title, status: a.status, version: a.version, origin: a.origin, shopify_article_id: a.shopify_article_id,
      shopify_published: false, published_at: a.published_at, shopify_synced_at: a.shopify_synced_at, updated_at: a.updated_at, shopify_state: shopifyState(a) }));
    return {
      requests,
      scheduled: arts.filter((a) => a.status === 'scheduled').sort((x, y) => String(x.publish_at).localeCompare(String(y.publish_at))).map((a) => ({ id: a.id, brand_id: a.brand_id, title: a.title, publish_at: a.publish_at, live_url: a.live_url })),
      drafts: unseen.filter((r) => r.shopify_state === 'hidden'),
      shopifyScheduled: unseen.filter((r) => r.shopify_state === 'scheduled_in_shopify'),
      readyForRequest: arts.filter((a) => a.status === 'approved' && a.approved_hash === a.content_hash).sort((x, y) => String(y.approved_at).localeCompare(String(x.approved_at)))
        .map((a) => ({ id: a.id, brand_id: a.brand_id, title: a.title, version: a.version, approved_at: a.approved_at, shopify_published: !!a.shopify_published })),
      livePublishingEnabled: true,
      confirmPhrase: 'PUBLISH',
      demo: true,
    };
  }],
  ['POST', '/publish-requests/:id/authorize', ({ params, body, db }) => {
    const user = actorOf(db);
    const r = db.publishRequests.find((x) => x.id === Number(params.id));
    need(r, 404, 'Request not found.', 'not_found');
    need(String(body.confirm ?? '').trim() === 'PUBLISH', 400, 'Type PUBLISH to confirm.', 'confirmation_required');
    need(r.status === 'pending', 409, `This request is already ${r.status}.`, 'bad_state');
    need(r.requested_by !== user.id || user.role === 'admin', 403, 'Another person must authorize your own request.', 'forbidden');
    r.attempts = (r.attempts ?? 0) + 1;
    return execute(db, r, user, String(body.note ?? '').slice(0, 300), 'publish.authorize');
  }],
  ['POST', '/publish-requests/:id/retry', ({ params, body, db }) => {
    const user = actorOf(db);
    const r = db.publishRequests.find((x) => x.id === Number(params.id));
    need(r, 404, 'Request not found.', 'not_found');
    need(String(body.confirm ?? '').trim() === 'PUBLISH', 400, 'Type PUBLISH to confirm.', 'confirmation_required');
    need(r.status === 'failed', 409, 'Only a failed request can be retried.', 'bad_state');
    r.attempts = (r.attempts ?? 0) + 1;
    return execute(db, r, user, '', 'publish.retry');
  }],
  ['POST', '/publish-requests/:id/reject', ({ params, body, db }) => {
    const user = actorOf(db);
    const r = db.publishRequests.find((x) => x.id === Number(params.id));
    need(r, 404, 'Request not found.', 'not_found');
    need(['pending', 'failed'].includes(r.status), 409, `This request is already ${r.status}.`, 'bad_state');
    need(String(body.note ?? '').trim(), 400, 'A reason is required.', 'note_required');
    r.status = 'rejected'; r.decided_by = user.id; r.decided_at = nowIso(); r.decision_note = String(body.note).trim();
    const a = getArticle(db, r.article_id);
    resetArticleAfterRequest(a, user, r.decision_note);
    addAudit(db, { action: 'publish.reject', brand: r.brand_id, entity: { type: 'publish_request', id: r.id }, detail: `Rejected publish request for "${a.title}": ${r.decision_note}`, userId: user.id });
    return { ok: true };
  }],
  ['POST', '/publish-requests/:id/cancel', ({ params, db }) => {
    const user = actorOf(db);
    const r = db.publishRequests.find((x) => x.id === Number(params.id));
    need(r, 404, 'Request not found.', 'not_found');
    need(['pending', 'failed'].includes(r.status), 409, `This request is already ${r.status}.`, 'bad_state');
    need(r.requested_by === user.id || user.role === 'admin', 403, 'Only the requester or an admin can withdraw a request.', 'forbidden');
    r.status = 'cancelled'; r.decided_by = user.id; r.decided_at = nowIso(); r.decision_note = 'Withdrawn';
    const a = getArticle(db, r.article_id);
    resetArticleAfterRequest(a, user, 'Withdrawn');
    addAudit(db, { action: 'publish.cancel', brand: r.brand_id, entity: { type: 'publish_request', id: r.id }, detail: `Withdrew publish request for "${a.title}"`, userId: user.id });
    return { ok: true };
  }],

  /* ----- topics & keywords ----- */
  ['GET', '/topics', ({ query, db }) => filterTopics(db, query)],
  ['POST', '/topics', ({ body, db }) => {
    const user = actorOf(db);
    const brand = checkBrand(body.brand_id);
    const f = topicFields(body, { title: '', primary_keyword: '', secondary_keywords: '', intent: 'informational', search_volume: null, keyword_difficulty: null, volume_source: '', notes: '' });
    need(f.title && f.primary_keyword, 400, 'A title and a primary keyword are required.', 'bad_request');
    need(!db.topics.some((t) => t.brand_id === brand && t.primary_keyword.toLowerCase() === f.primary_keyword.toLowerCase()), 409, 'A topic with this primary keyword already exists for this brand.', 'duplicate');
    const t = { id: nextIdOf(db.topics), brand_id: brand, ...f, status: f.search_volume != null ? 'validated' : 'proposed', source: 'manual', rationale: '',
      validation_note: f.search_volume != null ? 'Volume entered by hand; ready for a decision.' : 'No volume data yet. Add it from your keyword tool to validate.', article_id: null, created_at: nowIso(), updated_at: nowIso() };
    db.topics.push(t);
    addAudit(db, { action: 'topic.create', brand, entity: { type: 'topic', id: t.id }, detail: `Added topic "${t.title}"`, userId: user.id });
    return t;
  }],
  ['PATCH', '/topics/:id', ({ params, body, db }) => {
    const user = actorOf(db);
    const t = db.topics.find((x) => x.id === Number(params.id));
    need(t, 404, 'Topic not found.', 'not_found');
    const f = topicFields(body, t);
    need(f.title && f.primary_keyword, 400, 'A title and a primary keyword are required.', 'bad_request');
    need(!db.topics.some((x) => x.id !== t.id && x.brand_id === t.brand_id && x.primary_keyword.toLowerCase() === f.primary_keyword.toLowerCase()), 409, 'A topic with this primary keyword already exists for this brand.', 'duplicate');
    if (f.primary_keyword !== t.primary_keyword && ['validated', 'approved'].includes(t.status)) { f.status = 'proposed'; f.validation_note = 'Keyword changed: needs validation again.'; }
    Object.assign(t, f, { updated_at: nowIso() });
    addAudit(db, { action: 'topic.update', brand: t.brand_id, entity: { type: 'topic', id: t.id }, detail: `Updated topic "${t.title}"`, userId: user.id });
    return t;
  }],
  ['POST', '/topics/:id/decision', ({ params, body, db }) => {
    const user = actorOf(db);
    const t = db.topics.find((x) => x.id === Number(params.id));
    need(t, 404, 'Topic not found.', 'not_found');
    if (body.decision === 'approve') { need(['proposed', 'validated', 'rejected'].includes(t.status), 409, 'This topic cannot be approved now.', 'bad_state'); t.status = 'approved'; }
    else if (body.decision === 'reject') { need(['proposed', 'validated', 'approved'].includes(t.status), 409, 'This topic cannot be rejected now.', 'bad_state'); t.status = 'rejected'; t.validation_note = `Rejected by ${user.name}.`; }
    else if (body.decision === 'reopen') { need(t.status === 'rejected', 409, 'Only a rejected topic can be reopened.', 'bad_state'); t.status = t.search_volume != null ? 'validated' : 'proposed'; }
    else throw new DemoError(400, 'Unknown decision.', 'bad_request');
    t.updated_at = nowIso();
    addAudit(db, { action: 'topic.decision', brand: t.brand_id, entity: { type: 'topic', id: t.id }, detail: `${body.decision === 'approve' ? 'Approved' : body.decision === 'reject' ? 'Rejected' : 'Reopened'} topic "${t.title}"`, userId: user.id });
    return t;
  }],
  ['POST', '/topics/:id/article', ({ params, body, db }) => {
    const user = actorOf(db);
    const t = db.topics.find((x) => x.id === Number(params.id));
    need(t, 404, 'Topic not found.', 'not_found');
    need(t.status === 'approved' && !t.article_id, 409, 'Only an approved topic without an article can be started.', 'bad_state');
    const ai = body.mode === 'claude';
    const a = newArticle(db, user, t.brand_id, { title: t.title, primary_keyword: t.primary_keyword, body_html: ai ? draftBodyFor(t) : '' }, { topic_id: t.id, origin: ai ? 'claude' : 'app' });
    t.status = 'in_production'; t.article_id = a.id; t.updated_at = nowIso();
    if (ai) addAudit(db, { action: 'workflow.draft', brand: t.brand_id, entity: { type: 'article', id: a.id }, detail: { summary: `Simulated AI draft created for "${t.title}" (demo placeholder text)`, simulated: true }, userId: user.id });
    return { articleId: a.id, simulated: ai };
  }],
  ['GET', '/keywords', ({ query, db }) => filterKeywords(db, query)],
  ['POST', '/keywords', ({ body, db }) => {
    const user = actorOf(db);
    const brand = checkBrand(body.brand_id);
    const keyword = String(body.keyword ?? '').trim();
    need(keyword && String(body.source_tool ?? '').trim(), 400, 'A keyword and its source tool are required.', 'bad_request');
    need(!db.keywords.some((k) => k.brand_id === brand && k.keyword.toLowerCase() === keyword.toLowerCase()), 409, 'This keyword already exists for this brand.', 'duplicate');
    const k = { id: nextIdOf(db.keywords), brand_id: brand, keyword, search_volume: num(body.search_volume), keyword_difficulty: num(body.keyword_difficulty), intent: body.intent || null,
      source_tool: String(body.source_tool).trim(), source: 'manual', source_date: String(body.source_date || nowIso()).slice(0, 10) };
    db.keywords.push(k);
    addAudit(db, { action: 'keyword.create', brand, entity: { type: 'keyword', id: k.id }, detail: `Added keyword "${keyword}"`, userId: user.id });
    return k;
  }],
  ['GET', '/keyword-file', ({ db }) => {
    const ks = db.keywords.filter((k) => k.brand_id === 'ridhi');
    const clusters = ['Table linen', 'Care and washing', 'Bedding and cushions', 'Craft and process', 'Seasonal'];
    const clusterOf = (k) => (/care|iron|wash/.test(k) ? clusters[1] : /bedding|cushion/.test(k) ? clusters[2] : /print|dye|indigo/.test(k) && !/tablecloth|napkin|runner|placemat/.test(k) ? clusters[3] : /autumn|winter|seasonal/.test(k) ? clusters[4] : clusters[0]);
    const rows = ks.map((k, i) => {
      const art = db.articles.find((a) => a.brand_id === 'ridhi' && a.primary_keyword.toLowerCase() === k.keyword.toLowerCase());
      const opp = k.search_volume >= 1000 && k.keyword_difficulty <= 35 && !art;
      const live = art && art.shopify_published;
      const clicks = live ? Math.round(30 + mix(i, 1) * 200) : null;
      return { id: i + 1, keyword: k.keyword, topic: art?.title ?? null, cluster: clusterOf(k.keyword), intent: k.intent, search_volume: k.search_volume, keyword_difficulty: k.keyword_difficulty,
        gsc_clicks: clicks, gsc_impressions: clicks ? clicks * Math.round(18 + mix(i, 2) * 12) : null, gsc_avg_position: clicks ? Math.round((5 + mix(i, 3) * 9) * 10) / 10 : null,
        recommended_action: art ? (live ? 'Refresh the article and add two internal links.' : 'Finish the article.') : opp ? 'Write a new article for this keyword.' : 'Monitor; no article planned yet.',
        confidence: opp ? 'medium' : art ? 'high' : 'low', notes: 'Demo sample row.', opportunity: opp, new: i % 7 === 0 };
    });
    return { found: true, file: 'demo-keyword-research (sample data).xlsx', modifiedAt: daysAgo(12), title: 'Demo keyword research (synthetic sample data)', rows, clusters, pattern: 'ridhi-keyword-db-*.xlsx', folder: 'data', error: null, demo: true };
  }],

  /* ----- analytics ----- */
  ['GET', '/analytics/:kind', ({ params, query, db }) => {
    const r = resolveRange(query);
    const fn = { gsc: gscReport, ga4: ga4Report, articles: articlePerformance }[params.kind];
    need(fn, 404, 'Unknown report.', 'not_found');
    return { range: { from: r.from, to: r.to }, brands: brandsFor(query).map((b) => fn(db, b, r)) };
  }],
  ['POST', '/analytics/sync', ({ body, db }) => {
    const user = actorOf(db);
    const brand = body.brand ? checkBrand(body.brand) : null;
    const source = String(body.source ?? 'gsc');
    for (const b of brand ? [brand] : BRAND_IDS) {
      db.analyticsSync[b] ??= {};
      if (source === 'gsc' || source === 'all') db.analyticsSync[b].gsc = nowIso();
      if (source === 'ga4' || source === 'all') db.analyticsSync[b].ga4 = nowIso();
      addAudit(db, { action: 'analytics.sync', brand: b, entity: { type: 'integration', id: source }, detail: { summary: `Simulated ${source} sync (demo): no request was made to Google or Shopify`, simulated: true }, userId: user.id });
    }
    return { ok: true, simulated: true, source, rows: 0, message: 'Demo only: refreshed the sample figures. No request was made to Google or Shopify.' };
  }],

  /* ----- audit & exports ----- */
  ['GET', '/audit', ({ query, db }) => {
    const brand = brandQ(query);
    const limit = Math.min(Number(query.limit) || 100, 200);
    return db.audit.filter((r) => (!brand || r.brand_id === brand) && (!query.action || r.action.startsWith(`${query.action}.`) || r.action === query.action)
      && (!query.user || String(r.user_email ?? 'system').toLowerCase().includes(String(query.user).toLowerCase())) && (!query.before || r.id < Number(query.before)))
      .sort((x, y) => y.id - x.id).slice(0, limit);
  }],
  ['GET', '/data/export/articles', ({ query, db }) => csvDownload('flowmerce-articles-demo.xlsx',
    ['id', 'brand', 'title', 'handle', 'status', 'version', 'primary_keyword', 'author', 'shopify_published', 'published_at', 'updated_at', 'live_url'],
    filterArticles(db, query).map((a) => [a.id, a.brand_id, a.title, a.handle, a.status, a.version, a.primary_keyword, a.author, a.shopify_published ? 'yes' : 'no', a.published_at ?? '', a.updated_at, a.live_url ?? '']))],
  ['GET', '/data/export/topics', ({ query, db }) => csvDownload('flowmerce-topics-demo.xlsx',
    ['id', 'brand', 'title', 'primary_keyword', 'intent', 'search_volume', 'keyword_difficulty', 'status', 'source'],
    filterTopics(db, query).map((t) => [t.id, t.brand_id, t.title, t.primary_keyword, t.intent, t.search_volume ?? '', t.keyword_difficulty ?? '', t.status, t.source]))],
  ['GET', '/data/export/keywords', ({ query, db }) => csvDownload('flowmerce-keywords-demo.xlsx',
    ['brand', 'keyword', 'search_volume', 'keyword_difficulty', 'intent', 'source_tool', 'source_date'],
    filterKeywords(db, query).map((k) => [k.brand_id, k.keyword, k.search_volume ?? '', k.keyword_difficulty ?? '', k.intent ?? '', k.source_tool, k.source_date]))],
  ['GET', '/data/export/gsc_pages', ({ query, db }) => {
    const r = resolveRange(query);
    const rows = brandsFor(query).flatMap((b) => gscReport(db, b, r).pages.map((p) => [b, p.page, p.clicks, p.impressions, p.ctr === null ? '' : p.ctr.toFixed(4), p.position === null ? '' : p.position.toFixed(1), r.from, r.to, 'demo']));
    return csvDownload('flowmerce-gsc-pages-demo.xlsx', ['brand', 'page', 'clicks', 'impressions', 'ctr', 'position', 'from', 'to', 'source'], rows);
  }],
  ['GET', '/data/export/ga4_pages', ({ query, db }) => {
    const r = resolveRange(query);
    const rows = brandsFor(query).flatMap((b) => ga4Report(db, b, r).pages.map((p) => [b, p.page_path, p.sessions, p.engaged, p.avg_seconds === null ? '' : Math.round(p.avg_seconds), p.key_events, r.from, r.to, 'demo']));
    return csvDownload('flowmerce-ga4-pages-demo.xlsx', ['brand', 'page_path', 'sessions', 'engaged_sessions', 'avg_engagement_seconds', 'key_events', 'from', 'to', 'source'], rows);
  }],
  ['GET', '/data/export/audit', ({ query, db }) => csvDownload('flowmerce-audit-demo.xlsx', ['time', 'user', 'action', 'brand', 'entity', 'summary'],
    db.audit.filter((r) => (!brandQ(query) || r.brand_id === brandQ(query)) && inRange(r.ts, query.from, query.to)).sort((x, y) => y.id - x.id)
      .map((r) => [r.ts, r.user_email ?? 'system', r.action, r.brand_id, `${r.entity_type} ${r.entity_id}`.trim(), r.summary]))],
];
