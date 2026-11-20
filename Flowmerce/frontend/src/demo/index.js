/**
 * Demo transport: answers the same `/api/...` calls the Python backend will answer later, entirely in the browser.
 *  - No network request is made (no Shopify, Google, Supabase, carrier or Flowmerce API).
 *  - All data is synthetic and labelled DEMO / PREVIEW in the interface.
 *  - Changes live in memory (and a localStorage snapshot of this browser) and can be reset from the banner.
 *
 * Each module in ./modules exports `seed(db)` (fills its collections) and `routes` (a list of
 * [method, pattern, handler]). A handler receives `{ params, query, body, db }` and returns the JSON the real
 * endpoint will return, or throws `DemoError`. Switching to the real backend later means setting
 * NEXT_PUBLIC_FLOWMERCE_DATA_SOURCE=live; no view changes.
 */
import { DemoError, clone, toCsv } from './util.js';
import * as core from './modules/core.js';
import * as content from './modules/content.js';
import * as automation from './modules/automation.js';
import * as settings from './modules/settings.js';
import * as shipping from './modules/shipping.js';
import * as cro from './modules/cro.js';
import * as blog from './modules/blog.js';

// Flowmerce Main runs on real data. Synthetic demo data only when NEXT_PUBLIC_FLOWMERCE_DATA_SOURCE=demo is set on purpose.
export const DATA_SOURCE = process.env.NEXT_PUBLIC_FLOWMERCE_DATA_SOURCE === 'demo' ? 'demo' : 'live';
export const IS_DEMO = DATA_SOURCE === 'demo';

const MODULES = [core, content, automation, settings, shipping, cro, blog];
const STORAGE_KEY = 'flowmerce.demo.v1';
/** Bump when seed data shapes change, so an old browser snapshot is discarded instead of breaking pages. */
const SNAPSHOT_VERSION = 3;   // 2: CRO demo data added; 3: automatic blog slots (db.blog)

let db = null;
let routes = null;

function compile(pattern) {
  const keys = [];
  const src = pattern.replace(/:([a-zA-Z_]+)/g, (_, k) => { keys.push(k); return '([^/]+)'; });
  return { re: new RegExp(`^${src}$`), keys };
}

function build() {
  routes = [];
  for (const m of MODULES) for (const [method, pattern, fn] of m.routes) routes.push({ method, ...compile(pattern), fn });
}

function seedAll() {
  db = {};
  for (const m of MODULES) m.seed(db);
  db.__version = SNAPSHOT_VERSION;
}

function load() {
  if (db) return;
  if (!routes) build();
  try {
    const raw = typeof localStorage !== 'undefined' ? localStorage.getItem(STORAGE_KEY) : null;
    const snap = raw ? JSON.parse(raw) : null;
    if (snap && snap.__version === SNAPSHOT_VERSION) { db = snap; return; }
  } catch { /* unreadable snapshot: start fresh */ }
  seedAll();
}

function persist() {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(db)); } catch { /* private mode or quota: stay in memory */ }
}

/** Throw away every change made in the demo and start again from the sample data. */
export function resetDemo() {
  try { localStorage.removeItem(STORAGE_KEY); } catch { /* ignore */ }
  if (!routes) build();
  seedAll();
  persist();
}

const wait = (ms) => new Promise((r) => setTimeout(r, ms));

/** The single entry point used by lib/api.js. `path` excludes the `/api` prefix and may carry a query string. */
export async function demoRequest(method, path, body, signal) {
  load();
  await wait(90 + Math.random() * 160);
  if (signal?.aborted) throw Object.assign(new Error('aborted'), { name: 'AbortError' });
  const [pathname, search = ''] = path.split('?');
  const query = Object.fromEntries(new URLSearchParams(search));
  const clean = pathname.replace(/\/+$/, '') || '/';
  for (const r of routes) {
    if (r.method !== method) continue;
    const m = r.re.exec(clean);
    if (!m) continue;
    const params = Object.fromEntries(r.keys.map((k, i) => [k, decodeURIComponent(m[i + 1])]));
    try {
      const out = await r.fn({ params, query, body: body ?? {}, db });
      if (method !== 'GET') persist();
      return clone(out ?? { ok: true });
    } catch (e) {
      if (e instanceof DemoError) throw e;
      throw new DemoError(500, `Demo handler error: ${e.message}`, 'demo_error');
    }
  }
  throw new DemoError(404, `No demo data for ${method} ${clean}.`, 'demo_not_found');
}

/** Builds the CSV for an export route (the handler returns `csvDownload(...)`). */
export async function demoDownload(path) {
  const out = await demoRequest('GET', path);
  if (!out?.__download) throw new DemoError(404, 'This export is not available in the demo.', 'demo_not_found');
  const { filename, columns, rows } = out.__download;
  return { filename: filename.replace(/\.xlsx$/i, '.csv'), blob: new Blob([toCsv(columns, rows)], { type: 'text/csv;charset=utf-8' }) };
}
