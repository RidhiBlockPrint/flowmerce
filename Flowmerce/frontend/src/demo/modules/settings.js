/**
 * Demo module: integrations, brand settings, data import/export. Nothing here is connected to anything.
 * Honesty rule: no integration ever reads as "Connected". States used: demo_simulated, not_connected, standby, planned.
 *
 * Collections owned here:
 *  db.integrations: array of integration cards as GET /integrations returns them:
 *    { key, brand ('' = all brands), label, configured, testable, state ('demo_simulated'|'not_connected'|'standby'),
 *      status ({last_success_at:null, last_attempt_at, details}|null), provides, setup, paused:false, health? }
 *    plus db.integrations planned list is static (PLANNED below), returned as `planned`.
 *  db.brandSettings: { ridhi: {voice, audience, avoid, defaultAuthor, researchFocus, topicsPerRun, draftsPerRun}, cpc: {...} }
 *    Edited by PATCH /brands/:id. Other modules should read settings through `brandSettingsFor(db, id)` (also used by /brands).
 *  db.dataHealth: { flags: [{severity:'warning'|'info', area, count, message, link}],
 *                   imports: [{id, filename, kind, user_name, created_at, inserted, updated, duplicates, rejected}],
 *                   keys: ['kind|natural key', ...] // rows "imported" in this demo, so a re-import shows duplicates }
 */
import { BRAND_IDS, USERS, brandsPublic } from '../brands.js';
import { DemoError, csvDownload, hoursAgo, rng } from '../util.js';
import { addAudit } from './content.js';

const admin = USERS[0];
const SIM = (what) => `Simulated check — no request was sent to ${what}.`;

const PLANNED = [
  { key: 'carriers', label: 'Carrier tracking', description: 'Live delivery status from carrier tracking APIs for the Shipping view.' },
  { key: 'google_ads', label: 'Google Ads / Keyword Planner', description: 'Keyword volume and difficulty without manual imports.' },
  { key: 'shopify_orders', label: 'Shopify orders sync', description: 'Order and fulfilment data to feed shipping checks automatically.' },
  { key: 'alerts', label: 'Email and chat alerts', description: 'Notify the team when a stage fails or a review is waiting.' },
  { key: 'claude_direct', label: 'Direct AI execution', description: 'Run topic research and drafts against a real AI model instead of the simulated worker.' },
  { key: 'shopify_publish', label: 'Live Shopify publishing', description: 'Authorised, confirmed publishing of approved articles to the storefront.' },
];

export function brandSettingsFor(db, id) {
  return db.brandSettings?.[id] ?? brandsPublic().find((b) => b.id === id)?.settings;
}

export function seed(db) {
  const attempt = hoursAgo(0.5);
  const items = [];
  for (const b of BRAND_IDS) {
    const bp = brandsPublic().find((x) => x.id === b);
    items.push(
      { key: 'shopify', brand: b, label: 'Shopify Admin API', configured: true, testable: true, state: 'demo_simulated', status: null,
        provides: 'Demo — simulated. Articles, drafts, SEO fields and products come from sample data held in this browser.',
        setup: `Not connected. A live build would use a custom app token for ${bp.shopDomain}. Nothing is sent to Shopify from this demo.` },
      { key: 'shopify_public', brand: b, label: 'Shopify public feed', configured: false, testable: true, state: 'not_connected', status: null,
        provides: 'Not connected. Would read live articles and products from the public storefront.', setup: 'Not used in the demo: no request is made to any storefront.' },
      { key: 'gsc', brand: b, label: 'Google Search Console', configured: true, testable: true, state: 'demo_simulated', status: null,
        provides: 'Demo — simulated. Clicks, impressions and queries are synthetic sample figures.',
        setup: `Not connected. A live build would use a service account on ${bp.gscProperty}.` },
      { key: 'ga4', brand: b, label: 'Google Analytics 4', configured: true, testable: true, state: 'demo_simulated', status: null,
        provides: 'Demo — simulated. Sessions and key events are synthetic sample figures.', setup: 'Not connected. A live build would use a service account with Viewer access on the GA4 property.' },
    );
  }
  items.push(
    { key: 'shipping_supabase', brand: 'ridhi', label: 'Shipping database (Supabase)', configured: false, testable: true, state: 'not_connected', status: null,
      provides: 'Not connected. Would read shipments and delivery status from the shipping database (read-only).', setup: 'Planned: needs a restricted read key from the owner. The demo Shipping view uses sample data.' },
    { key: 'claude', brand: '', label: 'Claude (AI worker)', configured: false, testable: true, state: 'not_connected', status: null,
      provides: 'Not connected. In this demo topics and drafts come from a "Demo worker (simulated)"; no AI model is called.', setup: 'Planned: a real AI worker or API key would be set on the server.' },
    { key: 'ai_execution', brand: '', label: 'AI job execution', configured: true, testable: false, state: 'demo_simulated', status: null,
      provides: 'Demo — simulated. Jobs are saved and run by the Demo worker in your browser, then reported under Automation. A finished job never approves or publishes anything.',
      setup: 'Simulated in this build.' },
    { key: 'workflow_webhook', brand: '', label: 'Workflow webhook', configured: false, testable: false, state: 'not_connected', status: null,
      provides: 'Not connected. Would let an external AI worker report job progress to Flowmerce.', setup: 'Needs the backend, which is not part of this demo.' },
  );
  for (const i of items) { i.paused = false; }
  db.integrations = items;
  db.brandSettings = Object.fromEntries(brandsPublic().map((b) => [b.id, { ...b.settings }]));
  void attempt;
  db.dataHealth = {
    flags: [
      { severity: 'warning', area: 'Topics', count: 3, message: 'topics have no search-volume data', link: '/topics?missing=volume' },
      { severity: 'warning', area: 'Reviews', count: 1, message: 'articles waiting for review for 5+ days', link: '/articles?status=in_review' },
      { severity: 'warning', area: 'Articles', count: 2, message: 'live articles have no meta description in the dashboard', link: '/articles?live=1' },
      { severity: 'info', area: 'Articles', count: 2, message: 'articles in review or approved have no featured image', link: '/articles?status=in_review,approved' },
      { severity: 'warning', area: 'Search Console', count: 1, message: 'CPC imported Search Console data ends 21 days ago; import a newer export', link: '/analytics' },
    ],
    imports: [
      { id: 4, filename: 'semrush-keywords-nov.xlsx', kind: 'keywords', user_name: 'Asha Verma', created_at: hoursAgo(30), inserted: 42, updated: 0, duplicates: 6, rejected: 1 },
      { id: 3, filename: 'topic-ideas-q4.xlsx', kind: 'topics', user_name: 'Asha Verma', created_at: hoursAgo(120), inserted: 14, updated: 2, duplicates: 0, rejected: 0 },
      { id: 2, filename: 'gsc-pages-cpc-oct.xlsx', kind: 'gsc_pages', user_name: 'Demo Admin', created_at: hoursAgo(310), inserted: 960, updated: 0, duplicates: 0, rejected: 12 },
      { id: 1, filename: 'offline-review-notes.xlsx', kind: 'approvals', user_name: 'Rohan Mehta', created_at: hoursAgo(500), inserted: 5, updated: 0, duplicates: 0, rejected: 0 },
    ],
    keys: [],
  };
}

// ---------------------------------------------------------------- data kinds

const BRAND = { key: 'brand', header: 'brand', type: 'enum', required: true, values: ['ridhi', 'cpc'], description: 'ridhi = Ridhi Block Print, cpc = Cotton Print Club' };
const SOURCE_TS = { key: 'source_timestamp', header: 'source_timestamp', type: 'datetime', required: true, description: 'When this data was taken from its source (export time).' };
const INTENTS = ['informational', 'commercial', 'transactional', 'navigational'];
const F = (key, type, description = '', required = false, values, min, max) => ({ key, header: key, type, required, ...(values ? { values } : {}), ...(min != null ? { min } : {}), ...(max != null ? { max } : {}), description });

const KINDS = {
  topics: { title: 'Blog topics', importable: true, description: 'Topic ideas with their target keywords. Duplicate = same brand and primary keyword.', key: ['brand', 'primary_keyword'],
    fields: [BRAND, F('title', 'text', 'Working title', true), F('primary_keyword', 'text', 'The main search phrase this article targets', true), F('secondary_keywords', 'text', 'Comma-separated'),
      F('intent', 'enum', 'Search intent', false, INTENTS), F('search_volume', 'int', 'Monthly searches from your keyword tool', false, null, 0), F('keyword_difficulty', 'int', '0–100', false, null, 0, 100),
      F('volume_source', 'text', 'Tool the volume came from'), F('status', 'enum', 'Defaults to proposed', false, ['proposed', 'validated', 'approved', 'rejected']), F('notes', 'longtext', 'Brief for the writer'), SOURCE_TS] },
  keywords: { title: 'Keyword research', importable: true, description: 'Keyword volumes and difficulty from an external tool. Duplicate = same brand and keyword.', key: ['brand', 'keyword'],
    fields: [BRAND, F('keyword', 'text', 'Search phrase', true), F('search_volume', 'int', 'Monthly searches', true, null, 0), F('keyword_difficulty', 'int', '0–100', false, null, 0, 100),
      F('intent', 'enum', 'Search intent', false, INTENTS), F('source_tool', 'text', 'Semrush, Ahrefs, Google Keyword Planner…', true), F('source_date', 'date', 'Date the numbers were pulled', true), F('notes', 'longtext')] },
  articles: { title: 'Blog records', importable: false, description: 'Export only. Articles come from Shopify and the editor, so importing them is retired.',
    fields: [BRAND, F('title', 'text', 'Article title', true), F('handle', 'text', 'URL slug'), F('primary_keyword', 'text'), F('meta_title', 'text'), F('meta_description', 'longtext'), F('tags', 'text'), F('author', 'text'),
      F('status', 'enum', 'Export only', false, ['idea', 'draft', 'in_review', 'changes_requested', 'approved', 'publish_requested', 'scheduled', 'published', 'failed']),
      F('live', 'enum', 'Export only', false, ['yes', 'no']), F('url', 'url', 'Export only'), F('updated_at', 'datetime', 'Export only'), F('body_html', 'longtext')] },
  approvals: { title: 'Review notes', importable: true, key: ['brand', 'article_handle', 'reviewer_name', 'reviewed_at'],
    description: 'Review decisions made outside the dashboard. Imported rows become notes only — they never approve content or authorize publishing.',
    fields: [BRAND, F('article_handle', 'text', 'Handle of the article reviewed', true), F('reviewer_name', 'text', '', true), F('decision', 'enum', '', true, ['recommend_approve', 'changes_requested', 'comment']),
      F('note', 'longtext', '', true), F('reviewed_at', 'datetime', '', true)] },
  gsc_pages: { title: 'Search Console — pages by day', importable: true, key: ['brand', 'date', 'page'],
    description: 'Daily clicks and impressions per blog URL, exported from Search Console, for days the API did not supply. Duplicate = same brand, date and page.',
    fields: [BRAND, F('date', 'date', 'Day the metrics describe', true), F('page', 'url', 'Full URL or path of the blog article', true), F('clicks', 'int', '', true, null, 0), F('impressions', 'int', '', true, null, 0), F('position', 'number', 'Average position', true, null, 1, 200), SOURCE_TS] },
  gsc_queries: { title: 'Search Console — queries for a period', importable: true, key: ['brand', 'period_start', 'period_end', 'page', 'query'],
    description: 'Queries for a reporting period. Fallback only. Duplicate = same brand, period, page and query.',
    fields: [BRAND, F('period_start', 'date', '', true), F('period_end', 'date', '', true), F('page', 'url', 'Optional: the page the query led to'), F('query', 'text', '', true), F('clicks', 'int', '', true, null, 0), F('impressions', 'int', '', true, null, 0), F('position', 'number', '', true, null, 1, 200), SOURCE_TS] },
  ga4_pages: { title: 'GA4 — landing pages by day', importable: true, key: ['brand', 'date', 'landing_page'],
    description: 'GA4 landing-page sessions exported from Explore for days the Data API did not supply. Duplicate = same brand, date and landing page.',
    fields: [BRAND, F('date', 'date', '', true), F('landing_page', 'url', 'Path or URL', true), F('sessions', 'int', '', true, null, 0), F('engaged_sessions', 'int', '', true, null, 0),
      F('avg_engagement_seconds', 'number', 'Average engagement time per session', false, null, 0), F('key_events', 'number', 'Conversions (GA4 key events)', false, null, 0), SOURCE_TS] },
  audit: { title: 'Audit log', importable: false, description: 'Who did what and when. Export only.', fields: [F('time', 'datetime'), F('user', 'text'), F('action', 'text'), F('brand', 'text'), F('entity', 'text'), F('summary', 'longtext')] },
};

const kindsPublic = () => Object.entries(KINDS).map(([key, k]) => ({
  key, title: k.title, description: k.description, importable: k.importable,
  fields: k.fields.map((f) => ({ key: f.key, header: f.header, type: f.type, required: !!f.required, ...(f.values ? { values: f.values } : {}), description: f.description })),
}));

const SAMPLE_EXISTING = { topics: ['ridhi|block print tablecloth care', 'cpc|thanksgiving tablescape ideas'], keywords: ['ridhi|block print napkins', 'cpc|cotton tablecloth'] };

// ---------------------------------------------------------------- import parsing (CSV for real; .xlsx is simulated)

function parseCsv(text) {
  const rows = [];
  let row = [], cur = '', q = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (q) { if (c === '"') { if (text[i + 1] === '"') { cur += '"'; i++; } else q = false; } else cur += c; }
    else if (c === '"') q = true;
    else if (c === ',') { row.push(cur); cur = ''; }
    else if (c === '\n' || c === '\r') { if (c === '\r' && text[i + 1] === '\n') i++; row.push(cur); rows.push(row); row = []; cur = ''; }
    else cur += c;
  }
  if (cur !== '' || row.length) { row.push(cur); rows.push(row); }
  return rows;
}

function coerce(f, raw) {
  const v = raw == null ? '' : String(raw).trim();
  if (v === '') return f.required ? [null, `${f.header} is required`] : [null, null];
  if (f.type === 'int' || f.type === 'number') {
    const n = Number(v);
    if (!Number.isFinite(n) || (f.type === 'int' && !Number.isInteger(n))) return [null, `${f.header} must be a ${f.type === 'int' ? 'whole ' : ''}number`];
    if (f.min != null && n < f.min) return [null, `${f.header} must be at least ${f.min}`];
    if (f.max != null && n > f.max) return [null, `${f.header} must be at most ${f.max}`];
    return [n, null];
  }
  if (f.type === 'enum') { const m = f.values.find((x) => x.toLowerCase() === v.toLowerCase()); return m ? [m, null] : [null, `${f.header} must be one of: ${f.values.join(', ')}`]; }
  if (f.type === 'date') return /^\d{4}-\d{2}-\d{2}$/.test(v) && !Number.isNaN(Date.parse(v)) ? [v, null] : [null, `${f.header} must be a date like 2026-03-31`];
  if (f.type === 'datetime') return !Number.isNaN(Date.parse(v)) ? [v, null] : [null, `${f.header} must be a date and time`];
  if (f.type === 'url') return /^(https?:\/\/|\/)/.test(v) ? [v, null] : [null, `${f.header} must be a URL or a path starting with /`];
  return [v, null];
}

function bytesToText(body) {
  if (typeof body === 'string') return body;
  const u8 = body instanceof ArrayBuffer ? new Uint8Array(body) : ArrayBuffer.isView(body) ? new Uint8Array(body.buffer, body.byteOffset, body.byteLength) : null;
  if (!u8) return null;
  if (u8[0] === 0x50 && u8[1] === 0x4b) return null;   // zip = xlsx
  return new TextDecoder().decode(u8);
}
const sizeOf = (body) => (typeof body === 'string' ? body.length : body?.byteLength ?? 0);

/** Real validation for CSV text; a believable simulated validation for .xlsx (the demo has no workbook parser). */
function analyse(db, kindKey, body, dupMode) {
  const kind = KINDS[kindKey];
  if (!kind || !kind.importable) throw new DemoError(400, 'This workbook type cannot be imported.');
  const text = bytesToText(body);
  const taken = new Set([...(SAMPLE_EXISTING[kindKey] ?? []), ...db.dataHealth.keys.filter((k) => k.startsWith(`${kindKey}#`)).map((k) => k.slice(kindKey.length + 1))]);
  const warnings = [];
  let rows = [];
  if (text !== null) {
    const grid = parseCsv(text).filter((r) => r.some((c) => String(c).trim() !== ''));
    if (!grid.length) throw new DemoError(400, 'The file is empty.');
    const header = grid[0].map((h) => String(h).replace(/\*/g, '').trim().toLowerCase());
    const map = {};
    header.forEach((h, i) => { const f = kind.fields.find((x) => x.header.toLowerCase() === h); if (f) map[i] = f; });
    const missing = kind.fields.filter((f) => f.required && !Object.values(map).includes(f)).map((f) => f.header);
    if (missing.length) throw new DemoError(400, `Missing required columns: ${missing.join(', ')}`);
    warnings.push('Demo: this CSV was checked in your browser only. Nothing is uploaded anywhere.');
    const seen = new Set();
    grid.slice(1).forEach((vals, idx) => {
      const data = {}, errors = [], rw = [];
      for (const f of kind.fields) {
        const col = Object.keys(map).find((i) => map[i] === f);
        const [val, err] = col === undefined ? [null, null] : coerce(f, vals[col]);
        data[f.key] = val; if (err) errors.push(err);
      }
      const key = errors.length ? '' : kind.key.map((k) => String(data[k] ?? '').toLowerCase()).join('|');
      let duplicate = null;
      if (key && seen.has(key)) duplicate = 'file'; else if (key && taken.has(key)) duplicate = 'existing';
      if (key) seen.add(key);
      rows.push({ row: idx + 2, data, errors, warnings: rw, duplicate, key });
    });
  } else {
    if (sizeOf(body) < 600) throw new DemoError(400, 'The file could not be read as an .xlsx workbook.');
    warnings.push('Demo: .xlsx files are not read in this preview, so these results are simulated from the file size. Download a CSV template to see real row-by-row validation.');
    const r = rng(sizeOf(body));
    const total = 18 + Math.floor(r() * 30);
    const probs = {
      topics: ['primary_keyword is required', 'keyword_difficulty must be at most 100'], keywords: ['search_volume must be a whole number', 'source_date must be a date like 2026-03-31'],
    }[kindKey] ?? ['clicks must be a whole number', 'date must be a date like 2026-03-31'];
    rows = Array.from({ length: total }, (_, i) => ({ row: i + 2, data: {}, errors: [], warnings: [], duplicate: null, key: `x${i}` }));
    rows[3].errors.push(probs[0]); rows[total - 4].errors.push(probs[1]);
    rows[7].duplicate = 'file'; rows[11].duplicate = 'existing'; rows[12].duplicate = 'existing';
    rows[5].warnings.push('source_timestamp is over 30 days old');
  }
  const c = (f) => rows.filter(f).length;
  return {
    kind: kindKey, warnings,
    summary: { total: rows.length, valid: c((r) => !r.errors.length), invalid: c((r) => r.errors.length), duplicatesInFile: c((r) => r.duplicate === 'file'), duplicatesExisting: c((r) => r.duplicate === 'existing'), withWarnings: c((r) => r.warnings.length) },
    rows,
  };
}

function importPlan(parsed, dupMode) {
  const ok = parsed.rows.filter((r) => !r.errors.length);
  const dupFile = ok.filter((r) => r.duplicate === 'file').length;
  const exist = ok.filter((r) => r.duplicate === 'existing');
  const fresh = ok.filter((r) => !r.duplicate);
  return { inserted: fresh.length, updated: dupMode === 'update' ? exist.length : 0, duplicates: dupFile + (dupMode === 'update' ? 0 : exist.length), rejected: parsed.rows.length - ok.length, fresh };
}

// ---------------------------------------------------------------- sample exports (kinds not owned by the content module)

function sampleRows(kindKey, brand) {
  const r = rng(kindKey.length * 97);
  const kind = KINDS[kindKey];
  const out = [];
  const pages = ['/blogs/news/block-print-tablecloth-care', '/blogs/news/styling-cotton-napkins', '/blogs/news/hand-block-printing-process'];
  const cpcPages = ['/blogs/journal/thanksgiving-tablescape-ideas', '/blogs/journal/formal-table-setting', '/blogs/journal/tablecloth-size-guide'];
  for (const b of brand ? [brand] : BRAND_IDS) {
    const pg = b === 'ridhi' ? pages : cpcPages;
    for (let i = 0; i < 12; i++) {
      const day = new Date(Date.now() - (i + 3) * 86400000).toISOString().slice(0, 10);
      const ts = new Date().toISOString();
      const page = pg[i % pg.length];
      if (kindKey === 'approvals') out.push([b, page.split('/').pop(), ['Rohan Mehta', 'Asha Verma'][i % 2], ['recommend_approve', 'changes_requested', 'comment'][i % 3], ['Tone is on brand.', 'Please add care instructions.', 'Check the product link.'][i % 3], ts]);
      else if (kindKey === 'gsc_queries') out.push([b, day, day, page, ['block print napkins', 'cotton tablecloth care', 'table linen gift'][i % 3], Math.round(r() * 30), Math.round(200 + r() * 900), (3 + r() * 14).toFixed(1), ts]);
      else out.push([b, day, page, Math.round(40 + r() * 180), Math.round(25 + r() * 120), (40 + r() * 70).toFixed(1), (r() * 3).toFixed(1), ts]);
    }
  }
  if (kindKey === 'ga4_pages') return out.map((x) => [x[0], x[1], x[2], x[3], x[4], x[5], x[6], x[7]]);
  void kind;
  return out;
}

const exportRoute = (kindKey) => ['GET', `/data/export/${kindKey}`, ({ query }) => {
  const cols = KINDS[kindKey].fields.map((f) => f.header);
  return csvDownload(`${kindKey}-demo-export.xlsx`, cols, sampleRows(kindKey, query.brand).map((r) => r.slice(0, cols.length)));
}];

// ---------------------------------------------------------------- handlers

function addImport(db, filename, kindKey, plan) {
  const id = db.dataHealth.imports.reduce((m, i) => Math.max(m, i.id), 0) + 1;
  db.dataHealth.imports.unshift({ id, filename, kind: kindKey, user_name: admin.name, created_at: new Date().toISOString(), inserted: plan.inserted, updated: plan.updated, duplicates: plan.duplicates, rejected: plan.rejected });
  for (const r of plan.fresh) if (r.key) db.dataHealth.keys.push(`${kindKey}#${r.key}`);
  addAudit(db, { action: 'data.import', entity: `import:${kindKey}`, detail: `${filename}: ${plan.inserted} new, ${plan.updated} updated (demo only)`, userId: admin.id });
}

export const routes = [
  ['GET', '/integrations', ({ db }) => ({ items: db.integrations, planned: PLANNED, demo: true, livePublishing: false, shopifyApiVersion: 'not used in demo' })],
  ['POST', '/integrations/test', ({ body, db }) => {
    const key = String(body.key ?? '');
    const it = db.integrations.find((i) => i.key === key && (!body.brand || i.brand === body.brand));
    if (!it) throw new DemoError(404, 'Unknown integration.');
    const what = { shopify: 'Shopify', shopify_public: 'the storefront', gsc: 'Google Search Console', ga4: 'Google Analytics', shipping_supabase: 'Supabase', claude: 'Claude or any AI service' }[key] ?? 'any service';
    const now = new Date().toISOString();
    it.status = { last_success_at: null, last_attempt_at: now, last_error: null, details: { mode: 'simulated', note: 'no request sent' } };
    const message = `${SIM(what)} ${it.state === 'not_connected' ? 'A live build would report Not connected until credentials are set.' : 'A live build would check authentication and API access here.'}`;
    return { ok: true, simulated: true, message, error: null, result: { state: 'demo_simulated', label: 'Demo — simulated', error: SIM(what), simulated: true } };
  }],
  ['GET', '/brands', ({ db }) => brandsPublic().map((b) => ({ ...b, settings: brandSettingsFor(db, b.id) }))],
  ['PATCH', '/brands/:id', ({ params, body, db }) => {
    if (!BRAND_IDS.includes(params.id)) throw new DemoError(404, 'Unknown brand.');
    const cur = brandSettingsFor(db, params.id);
    const str = (k) => (body[k] === undefined ? cur[k] : String(body[k]).slice(0, 2000));
    const num = (k, lo, hi) => { const n = Number(body[k] ?? cur[k]); return Number.isFinite(n) ? Math.max(lo, Math.min(hi, Math.round(n))) : cur[k]; };
    db.brandSettings[params.id] = { ...cur, voice: str('voice'), audience: str('audience'), avoid: str('avoid'), defaultAuthor: str('defaultAuthor'), researchFocus: str('researchFocus'), topicsPerRun: num('topicsPerRun', 1, 15), draftsPerRun: num('draftsPerRun', 1, 5) };
    addAudit(db, { action: 'brand.update', brand: params.id, entity: `brand:${params.id}`, detail: 'Brand settings saved (demo only)', userId: admin.id });
    return { ok: true, settings: db.brandSettings[params.id] };
  }],
  ['GET', '/data/kinds', () => kindsPublic()],
  ['GET', '/data/health', ({ db }) => ({ flags: db.dataHealth.flags, imports: db.dataHealth.imports.slice(0, 25) })],
  ['GET', '/data/templates/:key', ({ params }) => {
    const k = KINDS[params.key];
    if (!k || !k.importable) throw new DemoError(404, 'No template for this type.');
    const cols = k.fields.map((f) => f.header);
    const sample = k.fields.map((f) => (f.key === 'brand' ? 'ridhi' : f.values ? f.values[0] : f.type === 'int' ? 100 : f.type === 'number' ? 10.5 : f.type === 'date' ? '2026-03-31' : f.type === 'datetime' ? '2026-03-31T09:00:00Z' : f.type === 'url' ? '/blogs/news/example' : `example ${f.key}`));
    return csvDownload(`${params.key}-template.xlsx`, cols, [sample]);
  }],
  ['POST', '/data/import/:kind', ({ params, query, body, db }) => {
    const dup = query.duplicates === 'update' ? 'update' : 'skip';
    const parsed = analyse(db, params.kind, body, dup);
    if (query.mode === 'commit') {
      const plan = importPlan(parsed, dup);
      const filename = query.filename ? decodeURIComponent(query.filename) : `${params.kind}-import.xlsx`;
      addImport(db, filename, params.kind, plan);
      return { inserted: plan.inserted, updated: plan.updated, duplicates: plan.duplicates, rejected: plan.rejected, demo: true };
    }
    return parsed;
  }],
  ['POST', '/admin/demo', ({ body }) => {
    if (!['load', 'clear'].includes(body.action)) throw new DemoError(400, 'action must be load or clear');
    return { ok: true, demo: true, rows: 0, removed: 0, message: 'This whole preview already runs on sample data, so there is nothing to load or clear. Use "Reset demo" in the top banner to restore the original sample data.' };
  }],
  exportRoute('approvals'), exportRoute('gsc_queries'), exportRoute('ga4_pages'),
];
