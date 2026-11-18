// Every GET endpoint the pages call must answer in the demo, and the shared payloads must be consistent.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { demoRequest, resetDemo } from '../src/demo/index.js';

const GET = [
  '/auth/me', '/tasks', '/home', '/home?brand=ridhi', '/brands', '/publishing', '/articles', '/articles/counts', '/topics', '/keywords',
  '/analytics/gsc', '/automation', '/ai/jobs', '/integrations', '/data/kinds', '/data/health', '/audit',
  '/shipping/summary', '/shipping/shipments', '/shipping/analytics', '/shipping/checks',
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
  assert.ok(home.shipping.all.total > 0);
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
