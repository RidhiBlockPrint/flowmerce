/**
 * Demo module: the automatic blog pipeline and the SEO & Blog overview (GET /api/blog/overview, services/auto_blog.py).
 * Synthetic: fictional titles, no Claude calls. Two slots a week per brand (Tuesday and Friday) for the next 4 weeks;
 * the nearest are ready (approved, kept in Flowmerce), the next one is being written, the rest are planned.
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
    topic_id: s.topic_id ?? null, scheduled_topic: !!s.topic_id,
    article_title: s.status === 'ready' ? s.title : null, topic_title: s.title, article_status: s.status === 'ready' ? 'publish_requested' : null,
    primary_keyword: s.title ? s.title.toLowerCase().split(' ').slice(0, 4).join(' ') : '',
    message: s.status === 'ready' ? 'Approved and kept in Flowmerce. Publish request waits for a reviewer.' : s.status === 'writing' ? 'Claude is writing the draft' : '',
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


// ---------------------------------------------------------------- AI image prompts (server: services/image_prompts.py)
// Synthetic: the demo writes a sample prompt at once instead of asking Claude.
const IMG_FORMATS = {
  ridhi: { shape: 'square', ratio: '1:1', width: 2048, height: 2048, preview: '1 / 1', theme: 'Yuva theme: blog cards and the article banner show the image at its own shape, and most posts are square, so a square image keeps the blog grid even.' },
  cpc: { shape: 'landscape', ratio: '4:3', width: 2400, height: 1800, preview: '4 / 3', theme: 'Nimbus theme: blog cards crop to 4:3 and the article banner and featured post crop to 10:7, from the centre.' },
};
const IMG_TOOL = { name: 'Google Gemini (Nano Banana Pro)', also: 'ChatGPT Images or any other tool that accepts a reference photo', why: "It keeps an attached product photo's print and colours most faithfully." };
const imgSteps = (f) => [`Open ${IMG_TOOL.name} (or ${IMG_TOOL.also}).`, `Set the image shape (aspect ratio) to ${f.ratio} in the tool's settings: image tools often copy the shape of the attached photo instead of following the prompt.`, 'Attach the reference photos shown here, if there are any (download them first).',
  'Paste the prompt and generate. Make a few and keep the best.', `Check the picture is ${f.ratio} and at least ${f.width * 3 / 4} pixels wide, then upload it with “From your computer” below.`];
const SCENES = ['a sunlit breakfast table on a wooden veranda, shot from a low three-quarter angle', 'a quiet bedroom corner at dusk with a folded quilt on a cane chair, seen from above',
  'hands pressing a carved teak block onto cream cotton in a bright workshop, close up', 'a long festive dinner table under string lights, seen from the far end'];

function samplePrompt(a, n) {
  const f = IMG_FORMATS[a.brand_id] ?? IMG_FORMATS.ridhi;
  return {
    prompt: `A realistic editorial photograph for an article titled “${a.title}”: ${SCENES[n % SCENES.length]}. Soft natural daylight, warm cream and indigo tones, `
      + 'hand block-printed cotton with visible weave and slightly irregular hand-stamped motifs, a few simple props in brass and terracotta, shallow depth of field, calm and inviting.\n\n'
      + `Format: a ${f.shape} image, aspect ratio ${f.ratio}, ${f.width} × ${f.height} pixels. If the tool offers only preset shapes, choose ${f.ratio}.\n`
      + 'It must look like a real photograph taken with a good camera: natural textures, true-to-life colour, no illustration, cartoon, 3D render or plastic AI sheen.\n'
      + 'Do not include any words, letters, numbers, logos, watermarks, borders, frames or collage panels.',
    pinPrompt: `A tall, top-down editorial photograph for “${a.title}”: hands smoothing hand block-printed cotton across a wooden surface, `
      + 'a few brass and terracotta props, soft daylight, calm uncluttered space at the top.\n\n'
      + 'Format: a portrait image, aspect ratio 2:3, 1000 × 1500 pixels. If the tool offers only preset shapes, choose 2:3. Leave calm, uncluttered space in the top quarter, where a title can be added later in Canva or Pinterest.\n'
      + 'Do not include any words, letters, numbers, logos, watermarks, borders, frames or collage panels.',
    payoff: 'How the piece looks and feels in everyday use.',
    concept: SCENES[n % SCENES.length], altText: `${a.title}: a styled scene with hand block-printed cotton`, fileName: `${String(a.handle || a.title).toLowerCase().replace(/[^a-z0-9]+/g, '-').slice(0, 60)}.jpg`,
  };
}

function imgDb(db) {
  if (!db.imagePrompts) {
    db.imagePrompts = {};
    for (const a of db.articles ?? []) if (a.id % 3 !== 0) db.imagePrompts[a.id] = { status: 'ready', reason: 'new_article', ...samplePrompt(a, a.id) };
  }
  return db.imagePrompts;
}

function imgState(db, id) {
  const a = (db.articles ?? []).find((x) => x.id === Number(id));
  if (!a) throw new DemoError(404, 'Article not found.');
  const f = IMG_FORMATS[a.brand_id] ?? IMG_FORMATS.ridhi;
  const p = imgDb(db)[a.id];
  const base = { articleId: a.id, brand: a.brand_id, brandPaused: false, configured: true, estimateUsd: 0.1, tool: IMG_TOOL, format: f,
    pin: { shape: 'portrait', ratio: '2:3', width: 1000, height: 1500 }, steps: imgSteps(f) };
  // The demo shows how an automatically made picture looks, using the article's own image as a stand-in.
  const generation = { configured: true, active: true, providerName: 'Google Gemini (demo)', model: 'gemini-3-pro-image' };
  const image = p && a.image_url ? { status: 'ready', url: a.image_url, pinUrl: '', attached: true, check: { faithful: true, looks_real: true, problems: '' }, error: null, attempts: 1 }
    : { status: 'none' };
  return p ? { ...base, references: [], error: null, costUsd: 0.08, position: null, updatedAt: dayAgo(1), generation, image, ...p } : { ...base, status: 'none', generation, image };
}

const IMG_GEN = { enabled: true, pins: false, check: true, dailyLimit: 10, monthlyUsd: 25 };

function imgSummary(db, brand) {
  const p = imgDb(db);
  const arts = (db.articles ?? []).filter((a) => !brand || a.brand_id === brand);
  const counts = { queued: 0, working: 0, ready: 0, failed: 0 };
  for (const a of arts) if (p[a.id]) counts[p[a.id].status] += 1;
  const without = (live) => arts.filter((a) => !p[a.id] && (a.status === 'published') === live).length;
  const brands = brand ? [brand] : BRAND_IDS;
  return { counts, pausedBrands: [], backfillWaiting: 0, withoutPrompt: { drafts: without(false), published: without(true) }, estimateUsd: 0.1, configured: true, resting: false, tool: IMG_TOOL,
    formats: Object.fromEntries(brands.map((b) => [b, IMG_FORMATS[b]])),
    generation: { configured: true, active: !!(db.imageGen ?? IMG_GEN).enabled, provider: 'gemini', providerName: 'Google Gemini (demo)', model: 'gemini-3-pro-image',
      costPerImageUsd: 0.134, setup: null, settings: db.imageGen ?? IMG_GEN, spending: { today: 2, todayUsd: 0.27, monthUsd: 3.62 } },
    styles: Object.fromEntries(brands.map((b) => [b, { builtAt: dayAgo(3), photos: 12, style: 'Light: soft, natural window light from one side.\nColour palette: cream, indigo, sage and warm terracotta.\nBackgrounds and surfaces: plain lime-washed walls, old teak and cane.\nProps and styling: a few brass and clay pieces, fresh flowers, nothing crowded.\nComposition and camera: eye level or a gentle top-down view, the textile filling most of the frame.\nMood: calm, handmade, lived-in.\nAvoid: harsh flash, glossy studio sets, clutter.' }])) };
}


// ---------------------------------------------------------------- the calendar (server: GET /api/calendar)
// Any month or year: built-in events computed for the years shown, the demo's blog slots in the range, and tasks
// scheduled in this browser. Synthetic; nothing runs.
const isoD = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
const nthWeekday = (y, m, wd, n) => { const d = new Date(y, m - 1, 1, 12); while (d.getDay() !== wd) d.setDate(d.getDate() + 1); d.setDate(d.getDate() + 7 * (n - 1)); return d; };
function builtinEvents(y) {
  const tg = nthWeekday(y, 11, 4, 4);
  const bf = new Date(tg); bf.setDate(bf.getDate() + 1);
  const rows = [["New Year's Day", new Date(y, 0, 1, 12), 30, 'Fresh-start tables, New Year hosting'], ["Valentine's Day", new Date(y, 1, 14, 12), 35, 'Dinner for two, red and pink linens'],
    ['Spring begins', new Date(y, 2, 20, 12), 30, 'Spring table refresh, florals, brunch'], ["Mother's Day", nthWeekday(y, 5, 0, 2), 35, 'Gifts for mom, brunch tables'],
    ["Father's Day", nthWeekday(y, 6, 0, 3), 28, 'Gifts, grilling and outdoor tables'], ['Independence Day', new Date(y, 6, 4, 12), 28, 'Fourth of July picnics and patio tables'],
    ['Halloween', new Date(y, 9, 31, 12), 35, 'Halloween parties and autumn decor'], ['Thanksgiving', tg, 45, 'Thanksgiving table sizes, sets, hosting and care'],
    ['Black Friday', bf, 30, 'Gift guides and holiday shopping'], ['Winter begins', new Date(y, 11, 21, 12), 30, 'Cozy winter tables and bedding'],
    ['Christmas', new Date(y, 11, 25, 12), 50, 'Christmas tables, red and green linens, gifting'], ["New Year's Eve", new Date(y, 11, 31, 12), 30, 'Party tables and hosting']];
  return rows.map(([name, d, lead, note]) => { const by = new Date(d); by.setDate(by.getDate() - lead);
    return { key: `${name.toLowerCase().replace(/[^a-z0-9]+/g, '-')}-${y}`, name, date: isoD(d), lead_days: lead, publish_by: isoD(by), note, builtin: true, brand_id: '' }; });
}
function eventsBetween(from, to) {
  const out = [];
  for (let y = Number(from.slice(0, 4)); y <= Number(to.slice(0, 4)) + 1; y++) out.push(...builtinEvents(y));
  return out.filter((e) => (e.date >= from && e.date <= to) || (e.publish_by >= from && e.publish_by <= to)).sort((a, b) => a.date.localeCompare(b.date));
}
function calendarView(db, query) {
  const brand = BRAND_IDS.includes(query.brand) ? query.brand : undefined;
  const isDay = (v) => /^\d{4}-\d{2}-\d{2}$/.test(String(v ?? ''));
  const from = isDay(query.from) ? query.from : `${dayAgo(0).slice(0, 8)}01`;
  const to = isDay(query.to) ? query.to : dayAgo(-41);
  const today = dayAgo(0);
  const upcoming = eventsBetween(today, dayAgo(-90)).filter((e) => e.date >= today);
  return {
    from, to, today, events: eventsBetween(from, to),
    schedule: (db.calendarSchedule ?? []).filter((x) => (!brand || x.brand_id === brand) && x.run_on >= from && x.run_on <= to),
    slots: overview(db, brand).slots.filter((x) => x.publish_on >= from && x.publish_on <= to),
    upcoming,
    budget: { today, todayUsd: 0.6, dailyLimitUsd: 3, remainingTodayUsd: 2.4, monthlyBudgetUsd: 90, monthUsd: 21.4, daysInMonth: 30, maxMonthlyUsd: 500, warning: null,
      estimates: { topic_research: 0.4, content_generation: 0.8, content_revision: 0.4, assist: 0.15 } },
    scheduledPublishes: (db.articles ?? []).filter((a) => a.publish_at && (!brand || a.brand_id === brand) && a.publish_at.slice(0, 10) >= from && a.publish_at.slice(0, 10) <= to)
      .map((a) => ({ id: a.id, brand_id: a.brand_id, title: a.title, publish_at: a.publish_at, status: a.status })),
  };
}

export const routes = [
  // Uploads need a real Shopify store: the demo explains that instead of pretending.
  ['POST', '/images/upload', () => { throw new DemoError(412, 'The demo has no Shopify store to keep uploaded images. Paste an image link instead.', 'pending_setup'); }],
  ['GET', '/articles/:id/image-prompt', ({ params, db }) => imgState(db, params.id)],
  ['POST', '/articles/:id/image-prompt', ({ params, db }) => {
    const a = (db.articles ?? []).find((x) => x.id === Number(params.id));
    if (!a) throw new DemoError(404, 'Article not found.');
    imgDb(db)[a.id] = { status: 'ready', reason: 'editor', ...samplePrompt(a, Date.now() % 4) };
    return imgState(db, a.id);
  }],
  ['GET', '/image-prompts', ({ query, db }) => imgSummary(db, BRAND_IDS.includes(query.brand) ? query.brand : undefined)],
  ['POST', '/image-prompts/backfill', ({ body, db }) => {
    const brand = BRAND_IDS.includes(body.brand) ? body.brand : undefined;
    const scopes = { drafts: (a) => a.status !== 'published', published: (a) => a.status === 'published', all: () => true };
    if (!scopes[body.scope]) throw new DemoError(400, 'scope must be one of drafts, published, all.');
    const p = imgDb(db);
    const todo = (db.articles ?? []).filter((a) => (!brand || a.brand_id === brand) && !p[a.id] && scopes[body.scope](a));
    todo.forEach((a, i) => { p[a.id] = { status: 'ready', reason: 'backfill', ...samplePrompt(a, i) }; });
    return { queued: todo.length, estimateUsd: Math.round(todo.length * 10) / 100, ...imgSummary(db, brand) };
  }],
  ['POST', '/image-prompts/backfill/cancel', ({ body, db }) => imgSummary(db, BRAND_IDS.includes(body.brand) ? body.brand : undefined)],
  ['POST', '/articles/:id/image-prompt/image', () => { throw new DemoError(412, 'The demo has no image API key or Shopify store, so it cannot make a picture.', 'pending_setup'); }],
  ['POST', '/articles/:id/image-prompt/use', ({ params, db }) => imgState(db, params.id)],
  ['PATCH', '/image-prompts/settings', ({ body, query, db }) => {
    const cur = { ...(db.imageGen ?? IMG_GEN) };
    for (const k of ['enabled', 'pins', 'check']) if (k in body) cur[k] = !!body[k];
    if ('dailyLimit' in body) cur.dailyLimit = Math.max(0, Math.min(100, Math.round(Number(body.dailyLimit) || 0)));
    if ('monthlyUsd' in body) cur.monthlyUsd = Math.max(0, Math.min(200, Number(body.monthlyUsd) || 0));
    db.imageGen = cur;
    return imgSummary(db, BRAND_IDS.includes(query.brand) ? query.brand : undefined);
  }],
  ['POST', '/image-prompts/style', ({ body, db }) => imgSummary(db, BRAND_IDS.includes(body.brand) ? body.brand : undefined)],
  ['GET', '/calendar', ({ query, db }) => calendarView(db, query)],
  ['POST', '/calendar/schedule', ({ body, db }) => {
    if (!BRAND_IDS.includes(body.brand)) throw new DemoError(400, 'Pick a brand.');
    if (!/^\d{4}-\d{2}-\d{2}$/.test(String(body.run_on ?? '')) || body.run_on < dayAgo(0)) throw new DemoError(400, 'Pick today or a later day.');
    db.calendarSchedule ??= [];
    const e = { id: db.calendarSchedule.length + 1, brand_id: body.brand, action: body.action, run_on: body.run_on, event_key: body.event_key || '', event_name: '', focus: body.focus || '',
      topic_id: body.topic_id ?? null, article_id: body.article_id ?? null, status: 'planned', message: 'Demo only: nothing runs.' };
    db.calendarSchedule.push(e);
    return e;
  }],
  ['GET', '/blog/overview', ({ query, db }) => overview(db, BRAND_IDS.includes(query.brand) ? query.brand : undefined)],
  ['PATCH', '/blog/autopilot', ({ body, db }) => {
    if ('enabled' in body) db.blog.settings.enabled = !!body.enabled;
    return db.blog.settings;
  }],
  ['POST', '/blog/slots/:id/skip', ({ params, db }) => cancelSlot(db, params.id)],
  // A topic put on a day (server: auto_blog.schedule_topic). The demo has no Claude: the slot stays planned.
  ['POST', '/blog/slots', ({ body, db }) => {
    if (!BRAND_IDS.includes(body.brand)) throw new DemoError(400, 'Pick a brand.');
    const day = String(body.publish_on ?? '').slice(0, 10);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(day) || day <= dayAgo(0)) throw new DemoError(400, 'Pick tomorrow or a later day: Flowmerce needs time to write and check the blog.');
    let t = body.topic_id ? (db.topics ?? []).find((x) => x.id === Number(body.topic_id) && x.brand_id === body.brand) : null;
    if (body.topic_id && !t) throw new DemoError(404, 'That topic does not exist for this brand.');
    if (!t) {
      const title = String(body.title ?? '').trim();
      if (title.length < 5) throw new DemoError(400, 'Write the blog topic (its working title).');
      db.topics ??= [];
      t = { id: Math.max(0, ...db.topics.map((x) => x.id)) + 1, brand_id: body.brand, title, primary_keyword: String(body.keyword || title).toLowerCase(), secondary_keywords: '',
        intent: 'informational', search_volume: null, keyword_difficulty: null, volume_source: '', notes: 'Put on the content calendar.', status: 'approved', source: 'manual',
        rationale: '', validation_note: '', article_id: null, created_at: new Date().toISOString(), updated_at: new Date().toISOString() };
      db.topics.push(t);
    }
    t.status = 'approved';
    if (db.blog.slots.some((x) => x.topic_id === t.id && ['planned', 'writing', 'ready'].includes(x.status))) throw new DemoError(409, 'This topic is already on the calendar.', 'already_scheduled');
    let slot = db.blog.slots.find((x) => x.brand_id === body.brand && x.publish_on === day);
    if (slot && (['writing', 'ready'].includes(slot.status) || (slot.topic_id && slot.status === 'planned'))) throw new DemoError(409, `${day} already has a blog for this brand. Pick another day, or cancel that one first.`, 'day_taken');
    if (!slot) {
      slot = { id: Math.max(0, ...db.blog.slots.map((x) => x.id)) + 1, brand_id: body.brand, publish_on: day, groups: {} };
      db.blog.slots.push(slot);
    }
    Object.assign(slot, { status: 'planned', topic_id: t.id, title: t.title, score: null });
    return { ...overview(db, body.brand).slots.find((x) => x.id === slot.id), topic_title: t.title };
  }],
  ['POST', '/blog/slots/:id/cancel', ({ params, db }) => cancelSlot(db, params.id)],
  // "Write a blog" (server: services/autopilot.py). The demo never calls Claude: a run "writes" for a few seconds, then
  // ends without an article, and can be stopped while it runs.
  ['GET', '/autopilot', ({ query, db }) => ({ runs: runsOf(db).filter((r) => !BRAND_IDS.includes(query.brand) || r.brand_id === query.brand).map((r) => tickRun(r)).reverse().slice(0, 10),
    budget: { todayUsd: 0.6, dailyLimitUsd: 3, remainingTodayUsd: 2.4, monthlyBudgetUsd: 90, monthUsd: 21.4, warning: null } })],
  ['GET', '/autopilot/:id', ({ params, db }) => tickRun(runOf(db, params.id))],
  ['POST', '/autopilot', ({ body, db }) => {
    if (!BRAND_IDS.includes(body.brand)) throw new DemoError(400, 'Unknown brand.');
    if (runsOf(db).some((r) => r.brand_id === body.brand && tickRun(r).status === 'running')) throw new DemoError(409, 'A blog is already being written for this brand. Wait for it to finish.', 'already_running');
    const r = { id: runsOf(db).length + 1, brand_id: body.brand, status: 'running', step: 'research', message: 'Claude is choosing topics (demo)', started: Date.now(), article_id: null, article_title: null };
    runsOf(db).push(r);
    return r;
  }],
  ['POST', '/autopilot/:id/stop', ({ params, db }) => {
    const r = tickRun(runOf(db, params.id));
    if (r.status !== 'running') throw new DemoError(409, 'This blog is not being written any more.', 'not_running');
    Object.assign(r, { status: 'failed', message: 'Stopped by you (demo).' });
    return r;
  }],
];

function cancelSlot(db, id) {
  const s = db.blog.slots.find((x) => x.id === Number(id));
  if (!s) throw new DemoError(404, 'That slot does not exist.');
  if (!['planned', 'writing'].includes(s.status)) throw new DemoError(409, 'Only a blog that is planned or being written can be cancelled.');
  s.status = 'skipped';
  return s;
}
const runsOf = (db) => (db.autopilotRuns ??= []);
function runOf(db, id) {
  const r = runsOf(db).find((x) => x.id === Number(id));
  if (!r) throw new DemoError(404, 'Run not found.');
  return r;
}
/** A demo run "writes" for 12 seconds, then ends without an article (the demo has no Claude). */
function tickRun(r) {
  if (r.status === 'running' && Date.now() - r.started > 12_000)
    Object.assign(r, { status: 'done', step: 'done', message: 'Demo only: no blog was written. In the real app the approved blog stays in Flowmerce, ready to schedule.' });
  else if (r.status === 'running' && Date.now() - r.started > 6_000)
    Object.assign(r, { step: 'draft', message: 'Claude is writing the draft (demo)' });
  return r;
}
