import test from 'node:test';
import assert from 'node:assert/strict';
import { demoRequest } from '../src/demo/index.js';
import * as automation from '../src/demo/modules/automation.js';

const get = (p) => demoRequest('GET', p);
const post = (p, b) => demoRequest('POST', p, b);
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

test('GET /automation shape', async () => {
  const a = await get('/automation');
  assert.equal(a.brands.length, 2);
  const b = a.brands[0];
  assert.equal(b.stages.length, 9);
  for (const k of ['key', 'label', 'kind', 'owner', 'description', 'state', 'pending', 'lastRun']) assert.ok(k in b.stages[0]);
  assert.equal(a.configured.ai.state, 'ready');
  assert.ok(a.runs.length > 5);
  assert.equal((await get('/automation?brand=cpc')).brands.length, 1);
});

test('stage run animates running -> succeeded, retry works, pause/resume', async () => {
  const r = await post('/automation/ridhi/stages/keyword_validation/run');
  assert.equal(r.status, 'running');
  await assert.rejects(post('/automation/ridhi/stages/topic_approval/run'), /done by a person/);
  let a = await get('/automation?brand=ridhi');
  assert.equal(a.runs.find((x) => x.id === r.id).status, 'running');
  await wait(3700);
  a = await get('/automation?brand=ridhi');
  assert.equal(a.runs.find((x) => x.id === r.id).status, 'succeeded');
  const failed = (await get('/automation?brand=cpc')).runs.find((x) => x.status === 'failed' && x.trigger_kind !== 'ai_job');
  assert.ok(failed.error);
  const rt = await post('/automation/runs/' + failed.id + '/retry');
  assert.ok(rt.message);
  await post('/automation/cpc/pause', { reason: 'Freeze' });
  const p = (await get('/automation?brand=cpc')).brands[0];
  assert.equal(p.paused, true);
  assert.equal(p.pause.reason, 'Freeze');
  await assert.rejects(post('/automation/cpc/stages/keyword_validation/run'), /paused/);
  await post('/automation/cpc/resume');
  assert.equal((await get('/automation?brand=cpc')).brands[0].paused, false);
});

test('AI jobs history, create, animate, cancel, retry', async () => {
  const l = await get('/ai/jobs');
  assert.equal(l.provider.mode, 'demo_simulated');
  assert.ok(l.jobs.some((j) => j.status === 'failed' && j.error && j.retryAvailable));
  assert.ok(l.jobs.some((j) => j.status === 'succeeded' && j.resultAvailable));
  assert.ok(l.jobs.some((j) => j.status === 'cancelled'));
  const d = await get('/ai/jobs/' + l.jobs[0].id);
  assert.ok(Array.isArray(d.events) && d.events.length >= 2);
  const c = await post('/ai/jobs', { brand: 'ridhi', task_type: 'topic_research', input: {} });
  assert.equal(c.deduplicated, false);
  assert.equal((await post('/ai/jobs', { brand: 'ridhi', task_type: 'topic_research' })).deduplicated, true);
  assert.ok(['pending', 'queued', 'running'].includes((await get('/ai/jobs/' + c.job.id)).status));
  await post('/ai/jobs/' + c.job.id + '/cancel');
  assert.equal((await get('/ai/jobs/' + c.job.id)).status, 'cancelled');
  const g = await post('/automation/cpc/stages/content_generation/run');
  assert.ok(g.job.id);
  await wait(9000);
  const done = await get('/ai/jobs/' + g.job.id);
  assert.equal(done.status, 'succeeded');
  assert.equal(done.result.kind, 'article');
  const failed = l.jobs.find((j) => j.status === 'failed');
  const rt = await post('/ai/jobs/' + failed.id + '/retry');
  assert.equal(rt.job.runNumber, failed.runNumber + 1);
  await assert.rejects(post('/ai/jobs/' + failed.id + '/bogus'), /Unknown action/);
});

test('home exports', () => {
  const db = {};
  automation.seed(db);
  const runs = automation.homeRuns(db, ['ridhi', 'cpc']);
  assert.ok(runs.length > 0 && runs.length <= 8);
  for (const k of ['id', 'brand', 'name', 'status', 'trigger', 'startedAt', 'finishedAt', 'lastSuccessAt']) assert.ok(k in runs[0]);
  const alerts = automation.automationAlerts(db, ['ridhi', 'cpc']);
  assert.ok(alerts.some((a) => a.level === 'critical' && a.link.startsWith('/automation')));
});

test('integrations never read as connected', async () => {
  const i = await get('/integrations');
  assert.ok(i.items.length >= 10);
  assert.ok(!i.items.some((x) => x.state === 'connected'));
  assert.ok(i.planned.length >= 3);
  const t = await post('/integrations/test', { key: 'shopify', brand: 'ridhi' });
  assert.match(t.message, /Simulated check — no request was sent to Shopify/);
  const s = await post('/integrations/test', { key: 'shipping_supabase', brand: 'ridhi' });
  assert.equal(s.result.label, 'Demo — simulated');
  await assert.rejects(post('/integrations/test', { key: 'nope' }), /Unknown/);
});

test('brands', async () => {
  assert.equal((await get('/brands')).length, 2);
  const r = await demoRequest('PATCH', '/brands/ridhi', { voice: 'New voice', topicsPerRun: 99 });
  assert.equal(r.settings.voice, 'New voice');
  assert.equal(r.settings.topicsPerRun, 15);
});

test('data kinds, health, templates, exports, admin/demo', async () => {
  const k = await get('/data/kinds');
  assert.ok(k.find((x) => x.key === 'topics').fields.some((f) => f.required));
  assert.equal(k.find((x) => x.key === 'articles').importable, false);
  const h = await get('/data/health');
  assert.ok(h.flags.length && h.imports.length);
  const t = await get('/data/templates/keywords');
  assert.equal(t.__download.columns[0], 'brand');
  await assert.rejects(get('/data/templates/articles'), /No template/);
  for (const e of ['approvals', 'gsc_queries', 'ga4_pages']) {
    const x = await get('/data/export/' + e);
    assert.ok(x.__download.rows.length > 0);
    assert.equal(x.__download.rows[0].length, x.__download.columns.length);
  }
  const d = await post('/admin/demo', { action: 'load' });
  assert.ok(d.message);
});

test('import preview/commit with CSV and simulated xlsx', async () => {
  const csv = [
    'brand,keyword,search_volume,keyword_difficulty,source_tool,source_date',
    'ridhi,linen napkins,500,30,Semrush,2026-03-01',
    'ridhi,linen napkins,500,30,Semrush,2026-03-01',
    'cpc,bad row,abc,30,Semrush,2026-03-01',
    'ridhi,block print napkins,200,20,Semrush,2026-03-01',
  ].join('\n');
  const p = await post('/data/import/keywords?mode=preview', csv);
  assert.equal(p.summary.total, 4);
  assert.equal(p.summary.invalid, 1);
  assert.equal(p.summary.duplicatesInFile, 1);
  assert.equal(p.summary.duplicatesExisting, 1);
  await assert.rejects(post('/data/import/keywords?mode=preview', 'brand,keyword\nridhi,x'), /Missing required columns/);
  const before = (await get('/data/health')).imports.length;
  const c = await post('/data/import/keywords?mode=commit&duplicates=skip&filename=k.csv', csv);
  assert.equal(c.inserted, 1);
  assert.equal(c.duplicates, 2);
  assert.equal(c.rejected, 1);
  const h = await get('/data/health');
  assert.equal(h.imports.length, before + 1);
  assert.equal(h.imports[0].filename, 'k.csv');
  const again = await post('/data/import/keywords?mode=preview', csv);
  assert.equal(again.summary.duplicatesExisting, 2);
  const buf = new Uint8Array(5000).fill(80);
  buf[0] = 0x50; buf[1] = 0x4b;
  const x = await post('/data/import/topics?mode=preview', buf.buffer);
  assert.ok(x.summary.total > 10);
  assert.equal(x.summary.invalid, 2);
  await assert.rejects(post('/data/import/articles?mode=preview', csv), /cannot be imported/);
});
