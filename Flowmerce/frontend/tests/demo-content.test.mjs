import test from 'node:test';
import assert from 'node:assert/strict';
import { demoRequest, resetDemo } from '../src/demo/index.js';
import * as content from '../src/demo/modules/content.js';

const get = (p) => demoRequest('GET', p);
const post = (p, b) => demoRequest('POST', p, b);
const day = (n) => new Date(Date.now() - n * 86400000).toISOString().slice(0, 10);
const range = `from=${day(27)}&to=${day(0)}`;

test('seed: articles, counts, statuses', async () => {
  resetDemo();
  const all = await get('/articles?limit=100');
  assert.ok(all.total >= 24);
  const statuses = new Set(all.rows.map((r) => r.status));
  for (const s of ['idea', 'draft', 'changes_requested', 'in_review', 'approved', 'publish_requested', 'scheduled', 'published', 'failed']) assert.ok(statuses.has(s), s);
  const ridhi = await get('/articles?brand=ridhi&limit=100');
  assert.ok(ridhi.rows.every((r) => r.brand_id === 'ridhi' && r.next_action && !('body_html' in r)));
  assert.ok((await get('/articles?status=in_review,approved')).rows.length >= 3);
  assert.ok((await get('/articles?live=1')).rows.every((r) => r.shopify_published));
  assert.ok((await get('/articles?q=tablecloth&limit=6')).rows.length > 0);
  const counts = await get('/articles/counts?brand=cpc');
  assert.ok(counts.every((c) => c.status && c.n > 0));
});

test('article detail shape and long bodies', async () => {
  const d = await get('/articles/1');
  for (const k of ['article', 'revisions', 'notes', 'requests', 'topic', 'queries', 'assignees']) assert.ok(k in d, k);
  assert.ok(d.article.body_html.replace(/<[^>]+>/g, ' ').split(/\s+/).length > 600);
  assert.equal(d.article.shopify_state, 'live');
  assert.ok(d.queries.rows.length > 0 && d.queries.source === 'demo');
  const rev = await get(`/articles/1/revisions/${d.revisions[1].id}`);
  assert.ok(rev.version && rev.data.title);
  assert.ok((await get('/brands/ridhi/products')).length > 5);
});

test('workflow: create, submit, approve, request, authorize', async () => {
  resetDemo();
  const a = await post('/articles', { brand_id: 'ridhi', title: 'Demo flow article about table linen', primary_keyword: 'table linen' });
  assert.equal(a.status, 'idea');
  assert.ok((await get('/articles?q=Demo flow')).rows.some((r) => r.id === a.id));
  await assert.rejects(post(`/articles/${a.id}/submit`), /text/);
  const body = '<p>Table linen first paragraph.</p><h2>Table linen care</h2><p>More.</p>';
  const saved = await demoRequest('PATCH', `/articles/${a.id}`, { expected_version: 1, body_html: `${body}<script>x()</script>` });
  assert.equal(saved.version, 2);
  assert.equal(saved.status, 'draft');
  assert.ok(!saved.body_html.includes('script'));
  await assert.rejects(demoRequest('PATCH', `/articles/${a.id}`, { expected_version: 1, title: 'x' }), (e) => e.code === 'version_conflict');
  await post(`/articles/${a.id}/submit`);
  assert.equal((await get(`/articles/${a.id}`)).article.status, 'in_review');
  await assert.rejects(post(`/articles/${a.id}/review`, { decision: 'approve', version: 1 }), (e) => e.status === 409);
  await post(`/articles/${a.id}/review`, { decision: 'request_changes', version: 2, note: 'Add links' });
  assert.equal((await get(`/articles/${a.id}`)).article.status, 'changes_requested');
  await post(`/articles/${a.id}/submit`);
  await post(`/articles/${a.id}/review`, { decision: 'approve', version: 2, note: '' });
  let d = await get(`/articles/${a.id}`);
  assert.equal(d.article.status, 'approved');
  assert.ok(d.article.approval_current);
  assert.equal(d.notes.length, 4);
  const dr = await post(`/articles/${a.id}/shopify-draft`);
  assert.match(dr.message, /Nothing was sent/);
  assert.equal((await get(`/articles/${a.id}`)).article.shopify_state, 'not_in_shopify');
  const req = await post(`/articles/${a.id}/publish-request`, { mode: 'publish_now', note: 'go' });
  assert.equal(req.status, 'pending');
  const pub = await get('/publishing?brand=ridhi');
  assert.ok(pub.requests.some((r) => r.id === req.id && r.title && r.requested_by_name));
  await assert.rejects(post(`/publish-requests/${req.id}/authorize`, { confirm: 'nope' }), (e) => e.code === 'confirmation_required');
  const res = await post(`/publish-requests/${req.id}/authorize`, { confirm: 'PUBLISH' });
  assert.match(res.message, /Demo only/);
  d = await get(`/articles/${a.id}`);
  assert.equal(d.article.status, 'published');
  assert.equal(d.article.shopify_state, 'live');
  const audit = await get('/audit?action=publish');
  assert.ok(audit[0].action === 'publish.authorize' && audit[0].summary.includes('Simulated'));
  const v1 = d.revisions.find((r) => r.version === 1);
  const rest = await post(`/articles/${a.id}/restore/${v1.id}`);
  assert.equal(rest.version, 3);
});

test('publishing: retry, reject, cancel, schedule', async () => {
  resetDemo();
  const pub = await get('/publishing');
  const failed = pub.requests.find((r) => r.status === 'failed');
  assert.ok(failed && failed.error);
  assert.ok(pub.requests.filter((r) => r.status === 'pending').length >= 2);
  assert.ok(pub.requests.some((r) => r.status === 'pending' && r.mode === 'schedule'));
  assert.ok(pub.scheduled.length >= 1 && pub.readyForRequest.length >= 1 && pub.drafts.length >= 1 && pub.shopifyScheduled.length >= 1);
  await post(`/publish-requests/${failed.id}/retry`, { confirm: 'PUBLISH' });
  assert.equal((await get(`/articles/${failed.article_id}`)).article.status, 'published');
  const pending = pub.requests.filter((r) => r.status === 'pending');
  await post(`/publish-requests/${pending[0].id}/reject`, { note: 'Not yet' });
  assert.equal((await get(`/articles/${pending[0].article_id}`)).article.status, 'approved');
  await post(`/publish-requests/${pending[1].id}/cancel`);
  await post(`/publish-requests/${pending[2].id}/cancel`);
  const after = await get('/publishing');
  assert.equal(after.requests.filter((r) => r.status === 'pending' || r.status === 'failed').length, 0);
});

test('topics and keywords', async () => {
  resetDemo();
  const topics = await get('/topics?brand=ridhi');
  assert.ok(new Set(topics.map((t) => t.status)).size >= 5);
  const validated = topics.find((t) => t.status === 'validated');
  await post(`/topics/${validated.id}/decision`, { decision: 'reject' });
  assert.equal((await get('/topics?brand=ridhi&status=validated')).some((t) => t.id === validated.id), false);
  assert.ok((await get('/topics?brand=ridhi&status=rejected')).some((t) => t.id === validated.id));
  const approved = topics.find((t) => t.status === 'approved' && !t.article_id);
  const r = await post(`/topics/${approved.id}/article`, { mode: 'claude' });
  assert.ok(r.articleId);
  assert.equal((await get(`/articles/${r.articleId}`)).topic.id, approved.id);
  const t = await post('/topics', { brand_id: 'cpc', title: 'New idea', primary_keyword: 'new idea kw' });
  assert.equal(t.status, 'proposed');
  await assert.rejects(post('/topics', { brand_id: 'cpc', title: 'Dup', primary_keyword: 'new idea kw' }), (e) => e.status === 409);
  await demoRequest('PATCH', `/topics/${t.id}`, { title: 'Renamed', primary_keyword: 'new idea kw' });
  assert.ok((await get('/keywords')).length >= 40);
  await post('/keywords', { brand_id: 'cpc', keyword: 'brand new keyword', search_volume: '300', source_tool: 'Tool' });
  assert.ok((await get('/keywords?brand=cpc')).some((k) => k.keyword === 'brand new keyword'));
  const kf = await get('/keyword-file');
  assert.ok(kf.found && kf.rows.length > 10 && kf.clusters.length);
});

test('analytics: shapes, determinism', async () => {
  for (const kind of ['gsc', 'ga4', 'articles']) {
    const r = await get(`/analytics/${kind}?${range}`);
    assert.equal(r.brands.length, 2);
    for (const b of r.brands) assert.equal((b.source ?? b.sources.gsc).kind, 'demo');
  }
  const b = (await get(`/analytics/gsc?brand=ridhi&${range}`)).brands[0];
  assert.ok(b.totals.clicks > 0 && b.series.length >= 26 && b.pages.length && b.queries.rows.length && b.pages[0].article.id);
  assert.equal(b.series.reduce((s, d) => s + d.clicks, 0), b.totals.clicks);
  assert.ok(b.declining.length >= 1, 'a declining page exists');
  assert.ok(b.opportunities.length >= 1);
  assert.deepEqual((await get(`/analytics/gsc?brand=ridhi&${range}`)).brands[0].totals, b.totals);
  const ga = (await get(`/analytics/ga4?brand=cpc&${range}`)).brands[0];
  assert.ok(ga.totals.sessions > 0 && ga.pages[0].page_path);
  const ar = (await get(`/analytics/articles?brand=ridhi&from=${day(89)}&to=${day(0)}`)).brands[0];
  assert.ok(ar.rows.length >= 4 && ar.rows[0].clicks !== undefined);
  assert.match((await post('/analytics/sync', { brand: 'ridhi', source: 'gsc' })).message, /No request was made/);
});

test('helpers for Home match the pages', async () => {
  const db = { me: { userId: 1 } };
  content.seed(db);
  const g = (await get(`/analytics/gsc?brand=ridhi&from=${day(30)}&to=${day(3)}`)).brands[0].totals;
  const t = content.trafficSummary(db, 'ridhi', day(30), day(3));
  assert.equal(t.clicks, g.clicks);
  assert.equal(t.impressions, g.impressions);
  assert.ok(t.sessions > 0 && t.series.length === 28);
  const c = content.articleCounts(db, 'cpc');
  assert.deepEqual(Object.keys(c).sort(), ['drafts', 'live', 'pendingApproval', 'total']);
  const rv = content.tasksFor(db, 'reviewer', 3);
  assert.ok(rv.some((x) => x.kind === 'review') && rv.some((x) => x.kind === 'authorize'));
  assert.ok(content.tasksFor(db, 'seo_manager', 2).every((x) => x.kind && x.brand && x.title && x.action && x.link && x.since));
  const row = content.addAudit(db, { action: 'x.test', brand: 'cpc', entity: 'article:5', detail: 'hi', userId: 2 });
  assert.equal(row.user_email, 'asha@demo.flowmerce.invalid');
});

test('audit paging and exports', async () => {
  resetDemo();
  const all = await get('/audit');
  assert.ok(all.length >= 25 && all[0].id > all[1].id);
  assert.ok((await get(`/audit?before=${all[5].id}`)).every((r) => r.id < all[5].id));
  assert.ok((await get('/audit?brand=cpc')).every((r) => r.brand_id === 'cpc'));
  for (const k of ['articles', 'topics', 'keywords', 'gsc_pages', 'ga4_pages', 'audit']) {
    const e = await get(`/data/export/${k}?${range}`);
    assert.ok(e.__download.columns.length && e.__download.rows.length, k);
  }
});
