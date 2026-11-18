/**
 * Demo module: automation (stages, runs, pause state) and AI jobs. Everything is simulated in the browser:
 * NOTHING calls Claude, Shopify, Google or any API. Jobs are "run" by a "Demo worker (simulated)".
 *
 * Collections owned here (read-only for other modules):
 *
 *  db.aiJobs: array of AI jobs, shaped like the real API's `public(job)` plus an internal `sim` field.
 *    { id (uuid string), brand ('ridhi'|'cpc'), stage, taskType ('topic_research'|'content_generation'),
 *      status ('pending'|'queued'|'running'|'succeeded'|'failed'|'cancelled'), provider ('demo_worker'),
 *      progress (0-100), message, error, errorKind, workerId, externalId, runNumber, retryCount, maxRetries, attempts,
 *      workflowRunId, createdAt, acceptedAt, startedAt, lastProgressAt, finishedAt, updatedAt, nextAttemptAt,
 *      input, result ({kind:'topics'|'article', summary, ...} or null), sim ({startAt, outcome} or null once settled) }
 *    Status is recomputed from timestamps on every read (refresh()), so polling UIs animate:
 *    queued ~1.2s, running until ~8.5s, then succeeded. A finished job that produced a draft/topics is "waiting for review".
 *
 *  db.runs: array of workflow runs (what Run history shows).
 *    { id (int), brand_id, stage, trigger_kind ('manual'|'retry'|'scheduler'|'ai_job'|'webhook'), user_id, user_name,
 *      status ('running'|'succeeded'|'failed'|'waiting'|'skipped'), message, error, started_at, finished_at, retry_of,
 *      job_id (ai_job runs), sim ({finishAt, outcome:'succeeded'|'failed', message, error} while running) }
 *
 *  db.automation: { pause: { ridhi: null | {paused:1, paused_by, paused_by_name, paused_at, reason}, cpc: ... },
 *                   pending: { ridhi: {stageKey: count}, cpc: {...} }  // "waiting for a person" counts per stage
 *                   resultSeq: number }
 */
import { BRAND_IDS, USERS } from '../brands.js';
import { DemoError, hoursAgo } from '../util.js';
import { addAudit } from './content.js';

const WORKER = 'Demo worker (simulated)';
const QUEUE_MS = 1200;
const RUN_MS = 8500;
const STAGE_RUN_MS = 3500;
const ACTIVE = ['pending', 'queued', 'running'];
const admin = USERS[0];

export const STAGES = [
  { key: 'topic_research', label: 'Topic research', kind: 'automated', owner: 'Claude', description: 'Claude proposes topics from the catalogue, existing articles and Search Console queries.' },
  { key: 'keyword_validation', label: 'Keyword validation', kind: 'automated', owner: 'Dashboard', description: 'Checks each proposed keyword against imported keyword data, Search Console and existing articles for overlap.' },
  { key: 'topic_approval', label: 'Topic approval', kind: 'human', owner: 'SEO Manager', description: 'A person approves or rejects validated topics.' },
  { key: 'content_generation', label: 'Content generation', kind: 'automated', owner: 'Claude', description: 'Claude writes a first draft for approved topics, with internal links to real products.' },
  { key: 'content_approval', label: 'Content approval', kind: 'human', owner: 'Reviewer', description: 'A reviewer approves the draft or sends it back with notes.' },
  { key: 'image_selection', label: 'Image selection', kind: 'automated', owner: 'Dashboard', description: 'Picks a featured image from the product a draft links to; editors can change it.' },
  { key: 'shopify_draft', label: 'Shopify draft', kind: 'automated', owner: 'Dashboard', description: 'Saves approved articles to Shopify as hidden drafts. Never publishes.' },
  { key: 'publication_approval', label: 'Publication approval', kind: 'human', owner: 'Reviewer / Admin', description: 'An authorized person approves the publish request and confirms it.' },
  { key: 'performance_tracking', label: 'Performance tracking', kind: 'automated', owner: 'Dashboard', description: 'Refreshes Shopify, Search Console and GA4 data.' },
];
const HUMAN_ACTION = {
  keyword_validation: 'Import keyword volumes for topics the check could not size',
  topic_approval: 'Approve or reject validated topics',
  content_generation: 'Generate drafts for approved topics',
  content_approval: 'Review drafts waiting for approval',
  image_selection: 'Choose featured images',
  shopify_draft: 'Save approved articles as Shopify drafts',
  publication_approval: 'Authorize or reject publish requests',
};
const AI_STAGES = ['topic_research', 'content_generation'];
const stageDef = (k) => STAGES.find((s) => s.key === k);

const TOPIC_POOL = {
  ridhi: [
    ['How to Care for Block Print Tablecloths', 'block print tablecloth care'], ['Styling a Summer Table with Cotton Napkins', 'cotton napkins table styling'],
    ['Hand Block Printing: How It Is Made', 'hand block printing process'], ['Choosing Bedding for a Cosy Guest Room', 'block print bedding guest room'],
    ['Five Ways to Use Block Print Cushion Covers', 'block print cushion covers'], ['Natural Dyes vs Pigments in Textile Printing', 'natural dye block print'],
    ['Laundering Handmade Cotton Linen', 'wash handmade cotton linen'],
  ],
  cpc: [
    ['Thanksgiving Tablescape Ideas with Printed Cotton', 'thanksgiving tablescape ideas'], ['How to Set a Formal Table, Step by Step', 'formal table setting guide'],
    ['Gifting Guide: Table Linen for Hosts', 'table linen hostess gift'], ['Choosing a Tablecloth Size for Your Table', 'tablecloth size guide'],
    ['Holiday Placemat and Napkin Pairings', 'holiday placemats napkins'], ['Bundle Ideas for a Festive Dinner Table', 'festive table bundle'],
    ['Christmas Table Runners That Last', 'christmas table runner cotton'],
  ],
};

const hex = (n) => Array.from({ length: n }, () => Math.floor(Math.random() * 16).toString(16)).join('');
const uuid = () => `${hex(8)}-${hex(4)}-4${hex(3)}-a${hex(3)}-${hex(12)}`;
const iso = (ms) => new Date(ms).toISOString();
const maxId = (rows) => rows.reduce((m, r) => Math.max(m, Number(r.id) || 0), 0);

function pickArticle(db, brand, topicId) {
  const arts = Array.isArray(db.articles) ? db.articles : [];
  const b = (a) => a.brand_id ?? a.brand;
  if (topicId != null) {
    const t = arts.find((a) => a.topic_id === topicId);
    if (t) return t;
  }
  const pool = arts.filter((a) => b(a) === brand);
  return pool.find((a) => a.status === 'in_review') ?? pool.find((a) => a.status === 'draft') ?? pool[0] ?? null;
}

function audit(db, action, brand, entity, detail) {
  addAudit(db, { action, brand, entity, detail, userId: admin.id });
}

// ---------------------------------------------------------------- seed

export function seed(db) {
  db.automation = {
    pause: { ridhi: null, cpc: null },
    pending: {
      ridhi: { keyword_validation: 2, topic_approval: 3, content_generation: 1, content_approval: 2, image_selection: 1, shopify_draft: 1, publication_approval: 1 },
      cpc: { keyword_validation: 0, topic_approval: 2, content_generation: 2, content_approval: 1, image_selection: 2, shopify_draft: 0, publication_approval: 0 },
    },
    resultSeq: 0,
  };
  db.aiJobs = [];
  db.runs = [];
  const run = (o) => { const r = { id: maxId(db.runs) + 1, retry_of: null, job_id: null, error: null, user_id: null, user_name: null, sim: null, ...o }; db.runs.push(r); return r; };
  const job = (o) => {
    const created = Date.parse(o.createdAt);
    const j = {
      id: uuid(), stage: o.taskType, provider: 'demo_worker', progress: 100, message: '', error: null, errorKind: null, workerId: WORKER,
      externalId: `demo-${hex(6)}`, runNumber: 1, retryCount: 0, maxRetries: 3, attempts: 1, workflowRunId: null,
      acceptedAt: iso(created + 900), startedAt: iso(created + 1800), lastProgressAt: o.finishedAt, updatedAt: o.finishedAt, nextAttemptAt: null,
      input: {}, result: null, sim: null, ...o,
    };
    db.aiJobs.push(j);
    const r = run({ brand_id: j.brand, stage: j.taskType, trigger_kind: 'ai_job', user_id: admin.id, user_name: admin.name, job_id: j.id,
      status: j.status === 'succeeded' ? 'succeeded' : j.status === 'failed' ? 'failed' : 'skipped', started_at: j.createdAt, finished_at: j.finishedAt,
      message: j.result?.summary ?? j.message, error: j.error });
    j.workflowRunId = r.id;
    return j;
  };
  const t = (h) => hoursAgo(h);
  const fin = (h, mins = 0.15) => hoursAgo(h - mins);
  const cpcArt = pickArticle(db, 'cpc');
  const ridArt = pickArticle(db, 'ridhi');
  job({ brand: 'ridhi', taskType: 'topic_research', status: 'succeeded', createdAt: t(52), finishedAt: fin(52), message: 'Proposed 5 topics',
    result: { kind: 'topics', count: 5, summary: 'Proposed 5 topics for review (simulated sample output).', topics: TOPIC_POOL.ridhi.slice(0, 5).map(([title, primary_keyword]) => ({ title, primary_keyword })) } });
  job({ brand: 'cpc', taskType: 'topic_research', status: 'succeeded', createdAt: t(30), finishedAt: fin(30), message: 'Proposed 5 topics',
    result: { kind: 'topics', count: 5, summary: 'Proposed 5 topics for review (simulated sample output).', topics: TOPIC_POOL.cpc.slice(0, 5).map(([title, primary_keyword]) => ({ title, primary_keyword })) } });
  job({ brand: 'ridhi', taskType: 'content_generation', status: 'succeeded', createdAt: t(20), finishedAt: fin(20, 0.2), message: 'Draft saved, waiting for review', input: { topic_id: 3 },
    result: { kind: 'article', articleId: ridArt?.id ?? 1, title: ridArt?.title ?? 'How to Care for Block Print Tablecloths', words: 1180, summary: 'Drafted "' + (ridArt?.title ?? 'How to Care for Block Print Tablecloths') + '" (1,180 words). Waiting for review.' } });
  job({ brand: 'cpc', taskType: 'content_generation', status: 'succeeded', createdAt: t(8), finishedAt: fin(8, 0.2), message: 'Draft saved, waiting for review', input: { topic_id: 9 },
    result: { kind: 'article', articleId: cpcArt?.id ?? 1, title: cpcArt?.title ?? 'How to Set a Formal Table, Step by Step', words: 1042, summary: 'Drafted "' + (cpcArt?.title ?? 'How to Set a Formal Table, Step by Step') + '" (1,042 words). Waiting for review.' } });
  job({ brand: 'cpc', taskType: 'content_generation', status: 'failed', createdAt: t(26), finishedAt: fin(26, 0.4), progress: 40, retryCount: 3, attempts: 3, input: { topic_id: 11 },
    message: 'Failed', errorKind: 'worker_rejected',
    error: 'The demo worker rejected the job: the topic brief is too short to draft from (simulated failure). Add notes to the topic, then retry.' });
  job({ brand: 'ridhi', taskType: 'content_generation', status: 'cancelled', createdAt: t(70), finishedAt: fin(70, 0.1), progress: 15, message: 'Cancelled by Demo Admin', input: { topic_id: 5 } });

  run({ brand_id: 'ridhi', stage: 'performance_tracking', trigger_kind: 'scheduler', status: 'succeeded', started_at: t(5), finished_at: fin(5), message: 'Refreshed demo analytics for 38 pages (simulated; no Google or Shopify request was made).' });
  run({ brand_id: 'cpc', stage: 'performance_tracking', trigger_kind: 'scheduler', status: 'succeeded', started_at: t(5), finished_at: fin(5), message: 'Refreshed demo analytics for 24 pages (simulated; no Google or Shopify request was made).' });
  run({ brand_id: 'ridhi', stage: 'keyword_validation', trigger_kind: 'manual', user_id: 2, user_name: 'Asha Verma', status: 'succeeded', started_at: t(48), finished_at: fin(48), message: 'Checked 6 proposed topics: 4 validated, 2 need keyword volumes.' });
  run({ brand_id: 'cpc', stage: 'keyword_validation', trigger_kind: 'manual', user_id: 2, user_name: 'Asha Verma', status: 'succeeded', started_at: t(29), finished_at: fin(29), message: 'Checked 5 proposed topics: 5 validated.' });
  run({ brand_id: 'ridhi', stage: 'shopify_draft', trigger_kind: 'manual', user_id: 1, user_name: admin.name, status: 'succeeded', started_at: t(15), finished_at: fin(15), message: 'Saved 1 approved article as a hidden draft (simulated; nothing was sent to Shopify).' });
  run({ brand_id: 'cpc', stage: 'image_selection', trigger_kind: 'manual', user_id: 3, user_name: 'Rohan Mehta', status: 'failed', started_at: t(11), finished_at: fin(11, 0.1), error: 'No product image matched 2 articles in the sample catalogue (simulated failure). Choose images in the editor, or retry.' });
  run({ brand_id: 'ridhi', stage: 'image_selection', trigger_kind: 'manual', user_id: 2, user_name: 'Asha Verma', status: 'succeeded', started_at: t(36), finished_at: fin(36), message: 'Picked featured images for 3 articles.' });
  run({ brand_id: 'ridhi', stage: 'performance_tracking', trigger_kind: 'scheduler', status: 'succeeded', started_at: t(29), finished_at: fin(29), message: 'Refreshed demo analytics for 38 pages (simulated).' });
  run({ brand_id: 'cpc', stage: 'performance_tracking', trigger_kind: 'scheduler', status: 'skipped', started_at: t(53), finished_at: fin(53, 0.01), message: 'Skipped: automation was paused for this brand.' });
}

// ---------------------------------------------------------------- simulation (status derived from timestamps)

const isPaused = (db, b) => !!db.automation?.pause?.[b];

function resultFor(db, job) {
  db.automation.resultSeq = (db.automation.resultSeq ?? 0) + 1;
  if (job.taskType === 'topic_research') {
    const n = Math.max(1, Math.min(15, Number(db.brandSettings?.[job.brand]?.topicsPerRun) || 5));
    const pool = TOPIC_POOL[job.brand];
    const topics = Array.from({ length: Math.min(n, pool.length) }, (_, i) => {
      const [title, primary_keyword] = pool[(db.automation.resultSeq + i) % pool.length];
      return { title, primary_keyword };
    });
    return { kind: 'topics', count: topics.length, topics, summary: `Proposed ${topics.length} topics for review (simulated sample output).` };
  }
  const a = pickArticle(db, job.brand, job.input?.topic_id);
  const title = a?.title ?? TOPIC_POOL[job.brand][db.automation.resultSeq % TOPIC_POOL[job.brand].length][0];
  const words = 900 + ((db.automation.resultSeq * 137) % 500);
  return { kind: 'article', articleId: a?.id ?? 1, title, words, summary: `Drafted "${title}" (${words.toLocaleString('en-US')} words). Waiting for review.` };
}

function advanceJob(db, j, now) {
  if (!j.sim) return;
  if (j.sim.startAt == null) {
    if (!isPaused(db, j.brand)) j.sim.startAt = now;   // resumed: work begins now
    else return;
  }
  const t = now - j.sim.startAt;
  if (t < QUEUE_MS) {
    j.status = 'queued'; j.progress = 5; j.message = `Queued (${WORKER} accepted)`; j.acceptedAt ??= iso(j.sim.startAt + 300);
  } else if (t < RUN_MS) {
    j.status = 'running'; j.progress = 10 + Math.round((80 * (t - QUEUE_MS)) / (RUN_MS - QUEUE_MS));
    j.message = j.taskType === 'topic_research' ? 'Reading existing titles and sample search queries' : 'Writing the draft from the approved topic brief';
    j.acceptedAt ??= iso(j.sim.startAt + 300); j.startedAt ??= iso(j.sim.startAt + QUEUE_MS);
  } else {
    const end = j.sim.startAt + RUN_MS;
    j.acceptedAt ??= iso(j.sim.startAt + 300); j.startedAt ??= iso(j.sim.startAt + QUEUE_MS);
    j.finishedAt = iso(end); j.nextAttemptAt = null;
    if (j.sim.outcome === 'failed') { j.status = 'failed'; j.error = j.sim.error; j.errorKind = 'worker_rejected'; j.message = 'Failed'; }
    else { j.status = 'succeeded'; j.progress = 100; j.error = null; j.errorKind = null; j.result = resultFor(db, j); j.message = 'Draft saved, waiting for review'; if (j.taskType === 'topic_research') j.message = 'Topics proposed, waiting for review'; }
    j.sim = null;
  }
  j.lastProgressAt = iso(Math.min(now, j.sim ? now : Date.parse(j.finishedAt)));
  j.updatedAt = j.lastProgressAt;
}

/** Bring every job and run up to date with the clock. Called at the start of each read. */
function refresh(db) {
  const now = Date.now();
  for (const j of db.aiJobs) advanceJob(db, j, now);
  for (const r of db.runs) {
    if (r.job_id) {
      const j = db.aiJobs.find((x) => x.id === r.job_id);
      if (!j) continue;
      r.status = ACTIVE.includes(j.status) ? 'running' : j.status === 'succeeded' ? 'succeeded' : j.status === 'failed' ? 'failed' : 'skipped';
      r.finished_at = ACTIVE.includes(j.status) ? null : j.finishedAt;
      r.message = j.result?.summary ?? (j.status === 'cancelled' ? 'Cancelled' : j.message);
      r.error = j.status === 'failed' ? j.error : null;
    } else if (r.sim && now >= r.sim.finishAt) {
      r.status = r.sim.outcome; r.finished_at = iso(r.sim.finishAt); r.message = r.sim.message ?? ''; r.error = r.sim.error ?? null; r.sim = null;
    }
  }
}

const publicJob = (db, j) => {
  const { sim, ...rest } = j;
  return {
    ...rest, resultAvailable: !!j.result, retryAvailable: j.status === 'failed', brandPaused: isPaused(db, j.brand),
    waitingForResume: j.status === 'pending' && isPaused(db, j.brand), cancellable: ACTIVE.includes(j.status), waitingOnProvider: false,
  };
};

function jobEvents(j) {
  const ev = [];
  let seq = 0;
  const add = (event_type, at, o = {}) => { if (at) ev.push({ source: o.source ?? 'flowmerce', sequence: ++seq, event_type, status: o.status ?? j.status, progress: o.progress ?? null, message: o.message ?? '', agent: o.source === 'worker' ? WORKER : null, created_at: at }); };
  add('created', j.createdAt, { status: 'pending', message: `Job saved (attempt ${j.runNumber}). Handed to ${WORKER}; no AI service is called.` });
  add('accepted', j.acceptedAt, { source: 'worker', status: 'queued', progress: 5, message: 'Accepted by the simulated worker' });
  add('started', j.startedAt, { source: 'worker', status: 'running', progress: 10, message: 'Working (simulated)' });
  if (j.startedAt) {
    const s = Date.parse(j.startedAt);
    const e = j.finishedAt ? Date.parse(j.finishedAt) : Date.parse(j.lastProgressAt ?? j.updatedAt);
    for (const p of [30, 55, 80]) if (j.progress >= p || j.finishedAt) { const at = s + ((e - s) * p) / 100; if (at <= e) add('progress', iso(at), { source: 'worker', status: 'running', progress: p, message: j.taskType === 'topic_research' ? ['Reading existing titles', 'Scoring candidate topics', 'Checking overlap'][p === 30 ? 0 : p === 55 ? 1 : 2] : ['Outlining the draft', 'Writing sections', 'Adding internal links to sample products'][p === 30 ? 0 : p === 55 ? 1 : 2] }); }
  }
  if (j.status === 'succeeded') add('succeeded', j.finishedAt, { source: 'worker', progress: 100, message: j.result?.summary ?? 'Done' });
  if (j.status === 'failed') add('failed', j.finishedAt, { source: 'worker', message: j.error });
  if (j.status === 'cancelled') add('cancelled', j.finishedAt, { message: 'Cancelled by Demo Admin' });
  return ev;
}

const PROVIDER = () => ({
  mode: 'demo_simulated', state: 'ready', missing: null, missingAll: [], model: null, callbackConfigured: false, webhookConfigured: false,
  notes: [], reason: 'Demo build: jobs are simulated in the browser by a Demo worker. No AI model or API is called.',
});

// ---------------------------------------------------------------- stage list

function lastRunFor(db, brand, stage) {
  const rows = db.runs.filter((r) => r.brand_id === brand && r.stage === stage).sort((a, b) => (a.started_at < b.started_at ? 1 : -1));
  return rows[0] ?? null;
}
const lastRunPublic = (r) => (r ? { id: r.id, status: r.status, started_at: r.started_at, finished_at: r.finished_at, message: r.message, error: r.error, trigger: r.trigger_kind, failedOnlyBecausePaused: false } : null);

function pipeline(db, brand) {
  const paused = isPaused(db, brand);
  return STAGES.map((st) => {
    const last = lastRunFor(db, brand, st.key);
    const pending = db.automation.pending?.[brand]?.[st.key] ?? 0;
    let state;
    if (last?.status === 'running') state = 'running';
    else if (last?.status === 'failed') state = 'failed';
    else if (paused && st.kind === 'automated') state = 'paused';
    else if (pending > 0) state = 'needs_action';
    else if (last) state = 'ok';
    else state = 'idle';
    return { ...st, state, pending, setupGap: null, humanAction: pending > 0 ? HUMAN_ACTION[st.key] ?? null : null, lastRun: lastRunPublic(last) };
  });
}

const runPublic = (r) => { const { sim, ...x } = r; return x; };

// ---------------------------------------------------------------- exports for the Home page

export function homeRuns(db, brandIds = BRAND_IDS) {
  refresh(db);
  const done = db.runs.filter((r) => r.status === 'succeeded');
  return db.runs.filter((r) => brandIds.includes(r.brand_id)).sort((a, b) => (a.started_at < b.started_at ? 1 : -1)).slice(0, 8).map((r) => ({
    id: r.id, brand: r.brand_id, name: stageDef(r.stage)?.label ?? r.stage, status: r.status, trigger: r.trigger_kind, startedAt: r.started_at, finishedAt: r.finished_at,
    lastSuccessAt: done.filter((d) => d.brand_id === r.brand_id && d.stage === r.stage).map((d) => d.finished_at).sort().pop() ?? null,
  }));
}

export function automationAlerts(db, brandIds = BRAND_IDS) {
  refresh(db);
  const out = [];
  const name = (b) => (b === 'ridhi' ? 'Ridhi' : 'CPC');
  for (const b of brandIds) {
    for (const s of pipeline(db, b)) if (s.state === 'failed' && s.lastRun?.trigger !== 'ai_job') out.push({ level: 'critical', title: `${s.label} failed · ${name(b)}`, detail: s.lastRun?.error ?? '', link: `/automation?brand=${b}` });
    const failedJobs = db.aiJobs.filter((j) => j.brand === b && j.status === 'failed');
    if (failedJobs.length) out.push({ level: 'critical', title: `${failedJobs.length} AI job${failedJobs.length > 1 ? 's' : ''} failed · ${name(b)}`, detail: failedJobs[0].error ?? '', link: `/automation?brand=${b}` });
    const p = db.automation.pause[b];
    if (p) out.push({ level: 'warning', title: `Automation paused · ${name(b)}`, detail: p.reason || 'No reason given', link: `/automation?brand=${b}` });
  }
  return out;
}

// ---------------------------------------------------------------- handlers

function startAiJob(db, brand, taskType, input, user = admin) {
  const now = Date.now();
  const paused = isPaused(db, brand);
  const j = {
    id: uuid(), brand, stage: taskType, taskType, status: 'pending', provider: 'demo_worker', progress: 0, message: paused ? 'Waiting: automation is paused' : 'Saved, waiting for the worker',
    error: null, errorKind: null, workerId: WORKER, externalId: null, runNumber: 1, retryCount: 0, maxRetries: 3, attempts: 0, workflowRunId: null,
    createdAt: iso(now), acceptedAt: null, startedAt: null, lastProgressAt: null, finishedAt: null, updatedAt: iso(now), nextAttemptAt: null,
    input, result: null, sim: { startAt: paused ? null : now, outcome: 'succeeded' },
  };
  db.aiJobs.unshift(j);
  const r = { id: maxId(db.runs) + 1, brand_id: brand, stage: taskType, trigger_kind: 'ai_job', user_id: user.id, user_name: user.name, status: 'running', message: '', error: null, started_at: j.createdAt, finished_at: null, retry_of: null, job_id: j.id, sim: null };
  db.runs.push(r);
  j.workflowRunId = r.id;
  return j;
}

const NON_AI_MESSAGES = {
  keyword_validation: (n) => `Checked ${3 + (n % 4)} proposed topics against sample keyword data: ${2 + (n % 3)} validated, 1 needs keyword volumes.`,
  image_selection: (n) => `Picked featured images for ${1 + (n % 3)} articles from the sample catalogue.`,
  shopify_draft: (n) => `Saved ${1 + (n % 2)} approved article${n % 2 ? 's' : ''} as hidden drafts (simulated; nothing was sent to Shopify).`,
  performance_tracking: (n) => `Refreshed demo analytics for ${24 + (n % 20)} pages (simulated; no Google or Shopify request was made).`,
};

function startRun(db, brand, stage, trigger, retryOf = null) {
  const now = Date.now();
  const id = maxId(db.runs) + 1;
  const r = { id, brand_id: brand, stage, trigger_kind: trigger, user_id: admin.id, user_name: admin.name, status: 'running', message: 'Started (simulated run)', error: null, started_at: iso(now), finished_at: null, retry_of: retryOf, job_id: null,
    sim: { finishAt: now + STAGE_RUN_MS, outcome: 'succeeded', message: NON_AI_MESSAGES[stage](id), error: null } };
  db.runs.push(r);
  return r;
}

export const routes = [
  ['GET', '/automation', ({ query, db }) => {
    refresh(db);
    const ids = query.brand && BRAND_IDS.includes(query.brand) ? [query.brand] : BRAND_IDS;
    const runs = db.runs.filter((r) => (!query.brand || r.brand_id === query.brand) && (!query.stage || r.stage === query.stage) && (!query.status || r.status === query.status))
      .sort((a, b) => (a.started_at < b.started_at ? 1 : -1)).slice(0, 60).map(runPublic);
    return {
      brands: ids.map((b) => ({ brand: b, paused: isPaused(db, b), pause: db.automation.pause[b], stages: pipeline(db, b) })),
      runs,
      configured: { claude: false, webhook: false, ai: PROVIDER(), demo: true, schedule: { stage: 'performance_tracking', label: 'Daily at 03:00 (simulated, runs only in this demo)', nextRunAt: iso(Date.now() + 9 * 3600 * 1000) } },
    };
  }],
  ['POST', '/automation/runs/:id/retry', ({ params, db }) => {
    refresh(db);
    const r = db.runs.find((x) => String(x.id) === params.id);
    if (!r) throw new DemoError(404, 'Run not found.');
    if (r.status !== 'failed') throw new DemoError(409, 'Only failed runs can be retried.');
    if (r.trigger_kind === 'ai_job') throw new DemoError(409, 'This run belongs to an AI job. Retry it from the AI jobs list.', 'ai_job_run');
    if (isPaused(db, r.brand_id)) throw new DemoError(423, 'Automation is paused for this brand. Resume it to run stages.', 'paused');
    const n = startRun(db, r.brand_id, r.stage, 'retry', r.id);
    audit(db, 'workflow.retry', r.brand_id, `stage:${r.stage}`, stageDef(r.stage)?.label);
    return { id: n.id, status: 'running', message: 'Retry started (simulated run).' };
  }],
  ['POST', '/automation/:brand/stages/:stage/run', ({ params, db }) => {
    refresh(db);
    const { brand, stage } = params;
    if (!BRAND_IDS.includes(brand)) throw new DemoError(404, 'Unknown brand.');
    const d = stageDef(stage);
    if (!d) throw new DemoError(404, 'Unknown stage.');
    if (d.kind === 'human') throw new DemoError(400, `${d.label} is done by a person, not run.`);
    if (isPaused(db, brand)) throw new DemoError(423, 'Automation is paused for this brand. Resume it to run stages.', 'paused');
    audit(db, 'workflow.run', brand, `stage:${stage}`, d.label);
    if (AI_STAGES.includes(stage)) {
      const active = db.aiJobs.find((j) => j.brand === brand && j.taskType === stage && ACTIVE.includes(j.status));
      if (active) return { status: 'queued', message: 'An AI job for this stage is already in progress', job: publicJob(db, active) };
      const j = startAiJob(db, brand, stage, {});
      return { status: 'queued', message: `Queued a simulated AI job (${WORKER})`, job: publicJob(db, j) };
    }
    if (db.runs.some((r) => r.brand_id === brand && r.stage === stage && r.status === 'running')) throw new DemoError(409, 'This stage is already running.');
    const r = startRun(db, brand, stage, 'manual');
    return { id: r.id, status: 'running', message: 'Started (simulated run, no external request is made)' };
  }],
  ['POST', '/automation/:brand/pause', ({ params, body, db }) => {
    if (!BRAND_IDS.includes(params.brand)) throw new DemoError(404, 'Unknown brand.');
    const reason = String(body?.reason ?? '').slice(0, 500);
    db.automation.pause[params.brand] = { paused: 1, paused_by: admin.id, paused_by_name: admin.name, paused_at: new Date().toISOString(), reason };
    audit(db, 'automation.pause', params.brand, `automation:${params.brand}`, reason);
    return { ok: true };
  }],
  ['POST', '/automation/:brand/resume', ({ params, db }) => {
    if (!BRAND_IDS.includes(params.brand)) throw new DemoError(404, 'Unknown brand.');
    db.automation.pause[params.brand] = null;
    audit(db, 'automation.resume', params.brand, `automation:${params.brand}`, '');
    for (const j of db.aiJobs) if (j.brand === params.brand && j.sim && j.sim.startAt == null) { j.sim.startAt = Date.now(); j.message = 'Saved, waiting for the worker'; }
    return { ok: true };
  }],
  ['GET', '/ai/jobs', ({ query, db }) => {
    refresh(db);
    const jobs = db.aiJobs.filter((j) => (!query.brand || j.brand === query.brand) && (!query.status || j.status === query.status))
      .sort((a, b) => (a.createdAt < b.createdAt ? 1 : -1)).slice(0, 100).map((j) => publicJob(db, j));
    return { provider: PROVIDER(), jobs };
  }],
  ['GET', '/ai/jobs/:id', ({ params, db }) => {
    refresh(db);
    const j = db.aiJobs.find((x) => x.id === params.id);
    if (!j) throw new DemoError(404, 'Job not found.', 'unknown_job');
    return { ...publicJob(db, j), events: jobEvents(j) };
  }],
  ['POST', '/ai/jobs', ({ body, db }) => {
    refresh(db);
    const brand = body.brand;
    if (!BRAND_IDS.includes(brand)) throw new DemoError(400, 'Choose a brand.');
    const task = body.task_type;
    if (!AI_STAGES.includes(task)) throw new DemoError(400, 'Unknown task type.');
    const input = task === 'content_generation' ? { topic_id: Number(body.input?.topic_id) } : {};
    if (task === 'content_generation' && !Number.isFinite(input.topic_id)) throw new DemoError(400, 'Choose an approved topic.');
    const dup = db.aiJobs.find((j) => j.brand === brand && j.taskType === task && ACTIVE.includes(j.status) && j.input?.topic_id === input.topic_id);
    if (dup) return { job: publicJob(db, dup), deduplicated: true };
    const j = startAiJob(db, brand, task, input);
    audit(db, 'ai_job.create', brand, `ai_job:${j.id.slice(0, 8)}`, task);
    return { job: publicJob(db, j), deduplicated: false };
  }],
  ['POST', '/ai/jobs/:id/:verb', ({ params, db }) => {
    refresh(db);
    const j = db.aiJobs.find((x) => x.id === params.id);
    if (!j) throw new DemoError(404, 'Job not found.', 'unknown_job');
    const now = Date.now();
    if (params.verb === 'cancel') {
      if (!ACTIVE.includes(j.status)) throw new DemoError(409, 'Only a job that has not finished can be cancelled.');
      j.status = 'cancelled'; j.sim = null; j.finishedAt = iso(now); j.updatedAt = j.finishedAt; j.message = 'Cancelled by Demo Admin';
    } else if (params.verb === 'retry') {
      if (j.status !== 'failed') throw new DemoError(409, 'Only a failed job can be retried.');
      if (isPaused(db, j.brand)) throw new DemoError(423, 'Automation is paused for this brand. Resume it to retry.', 'paused');
      Object.assign(j, { status: 'pending', progress: 0, error: null, errorKind: null, runNumber: j.runNumber + 1, attempts: j.attempts + 1, startedAt: null, acceptedAt: null, finishedAt: null,
        message: 'Saved again, waiting for the worker', updatedAt: iso(now), sim: { startAt: now, outcome: 'succeeded' } });
    } else throw new DemoError(404, `Unknown action "${params.verb}".`);
    audit(db, `ai_job.${params.verb}`, j.brand, `ai_job:${j.id.slice(0, 8)}`, j.taskType);
    return { job: publicJob(db, j) };
  }],
];
