// Every GET endpoint the pages call must answer in the demo, and the shared payloads must be consistent.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { demoRequest, resetDemo } from '../src/demo/index.js';

const GET = [
  '/auth/me', '/tasks', '/home', '/home?brand=ridhi', '/brands', '/publishing', '/articles', '/articles/counts', '/topics', '/keywords',
  '/analytics/gsc', '/automation', '/ai/jobs', '/integrations', '/data/kinds', '/data/health', '/audit',
  '/shipping/summary', '/shipping/shipments', '/shipping/analytics', '/shipping/checks',
  '/cro/overview?brand=ridhi', '/cro/sales-trend?brand=cpc', '/cro/sales-breakdown?brand=ridhi', '/cro/order-health?brand=ridhi',
  '/cro/products?brand=cpc', '/cro/conversion?brand=ridhi', '/cro/segments?brand=ridhi&dimension=channel', '/cro/recommendations?brand=ridhi', '/cro/ai-advice?brand=ridhi', '/cro/goal?brand=ridhi', '/blog/overview', '/blog/overview?brand=cpc',
  '/cro/benchmarks', '/cro/home', '/cro/home?brand=cpc', '/cro/overview?brand=ridhi&from=2026-11-01&to=2026-11-07&compare=last_week', '/cro/alarms?brand=ridhi', '/cro/alerts?brand=ridhi', '/cro/change-log?brand=ridhi', '/cro/settings?brand=cpc',
];

test('every page endpoint answers', async () => {
  resetDemo();
  for (const p of GET) {
    try { assert.ok(await demoRequest('GET', p), p); } catch (e) { assert.fail(`${p}: ${e.message}`); }
  }
});

test('home is consistent with the module data', async () => {
  const home = await demoRequest('GET', '/home');
  assert.equal(home.articles.length, 2);
  assert.ok(home.shipping.all.active > 0);
  assert.ok(home.metrics.every((m) => m.source.kind === 'demo'));
  const me = await demoRequest('GET', '/auth/me');
  assert.equal(me.livePublishing, true);
});

test('role switch changes permissions and tasks', async () => {
  await demoRequest('POST', '/demo/role', { role: 'reviewer' });
  const me = await demoRequest('GET', '/auth/me');
  assert.ok(me.permissions.includes('publish:authorize') && !me.permissions.includes('article:write'));
  await demoRequest('POST', '/demo/role', { role: 'admin' });
});
