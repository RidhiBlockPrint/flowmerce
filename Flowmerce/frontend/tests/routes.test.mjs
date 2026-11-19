// Run with: node --test tests/   (from the frontend folder; no packages needed)
import assert from 'node:assert/strict';
import { existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { REDIRECTS } from '../redirects.mjs';
import { NAV, NAV_ITEMS, SETTINGS, moduleOf, parentOf, pathMatches, showsSearch, usesRange } from '../src/lib/routes.mjs';

const APP = join(dirname(fileURLToPath(import.meta.url)), '..', 'src', 'app');
const pageExists = (path) => existsSync(join(APP, path.replace(/^\//, '').replace(/:id/g, '[id]').replace(/:brand/g, '[brand]'), 'page.jsx'));
const bare = (dest) => dest.split('?')[0];

test('the menu has exactly the agreed modules and pages, in order', () => {
    assert.deepEqual(NAV.map((e) => [e.label, e.kind === 'module' ? e.items.map((i) => i.label) : null]), [
        ['Home', null],
        ['SEO & Blog', ['Articles', 'Topics & keywords', 'Content calendar', 'Publishing', 'SEO & traffic', 'Automation']],
        ['Shipping', null],
    ]);
    assert.deepEqual(SETTINGS.items.map((i) => i.label), ['Integrations', 'Brands', 'Data management', 'Audit log']);
});

test('Automation lives inside SEO & Blog, and Shipping is one top-level entry', () => {
    assert.ok(!NAV.some((e) => e.label === 'Automation'));
    assert.equal(NAV.find((e) => e.id === 'seo').items.find((i) => i.label === 'Automation').to, '/automation');
    assert.equal(NAV.find((e) => e.id === 'shipping').to, '/shipping');
});

test('each page belongs to one module, so the sidebar can expand and highlight the right parent', () => {
    for (const p of ['/articles', '/articles/42', '/topics', '/calendar', '/publishing', '/analytics', '/automation'])
        assert.equal(moduleOf(p), 'seo', p);
    assert.equal(moduleOf('/'), 'home');
    assert.equal(moduleOf('/shipping'), 'shipping');
    for (const p of ['/settings/integrations', '/settings/brands', '/settings/data', '/settings/audit'])
        assert.equal(moduleOf(p), 'settings', p);
    assert.equal(moduleOf('/nope'), null);
});

test('every menu item opens a real page, and no page appears twice', () => {
    for (const i of NAV_ITEMS)
        assert.ok(pageExists(i.to === '/' ? '' : i.to), `${i.label} -> ${i.to}`);
    const tos = NAV_ITEMS.map((i) => i.to);
    assert.equal(new Set(tos).size, tos.length);
});

test('retired destinations are not in the menu', () => {
    const tos = NAV_ITEMS.map((i) => i.to);
    for (const gone of ['/seo', '/workspace', '/blogs', '/data', '/integrations', '/audit'])
        assert.ok(!tos.some((t) => t === gone || t.startsWith(`${gone}/`)), gone);
});

test('every old address redirects to a page that exists, and is no longer a page itself', () => {
    for (const r of REDIRECTS) {
        const dest = bare(r.destination);
        assert.ok(dest === '/' || pageExists(dest), `${r.source} -> ${r.destination}`);
        assert.ok(!pageExists(r.source.replace(/:\w+/g, (m) => (m === ':id' ? ':id' : ':brand'))) || r.source === '/', `${r.source} still has its own page`);
    }
});

test('redirects cannot loop', () => {
    const sources = new Set(REDIRECTS.map((r) => r.source));
    for (const r of REDIRECTS)
        assert.ok(!sources.has(bare(r.destination)) || bare(r.destination) === '/', `${r.source} -> ${r.destination}`);
});

test('the merged pages keep working through their old addresses', () => {
    const to = Object.fromEntries(REDIRECTS.map((r) => [r.source, r.destination]));
    assert.equal(to['/blogs'], '/articles');
    assert.equal(to['/blogs/:id'], '/articles/:id');
    assert.equal(to['/workspace/:brand'], '/articles?brand=:brand');   // the brand is selected on arrival
    assert.equal(to['/seo'], '/');
    assert.equal(to['/data'], '/settings/data');
    assert.equal(to['/integrations'], '/settings/integrations');
    assert.equal(to['/audit'], '/settings/audit');
});

test('the audit log is offered only to roles that may view it', () => {
    assert.equal(NAV_ITEMS.find((i) => i.label === 'Audit log').perm, 'audit:view');
});

test('active-link matching treats a section and its children as one place, but Home only matches itself', () => {
    assert.ok(pathMatches('/articles/42', '/articles'));
    assert.ok(!pathMatches('/articles', '/articles/42'));
    assert.ok(pathMatches('/', '/', true) && !pathMatches('/articles', '/', true));
});

test('the date range shows only where figures depend on it; search is hidden in Settings', () => {
    assert.ok(usesRange('/analytics') && usesRange('/articles/7'));
    assert.ok(!usesRange('/articles') && !usesRange('/settings/data') && !usesRange('/'));
    assert.ok(showsSearch('/articles') && showsSearch('/'));
    assert.ok(!showsSearch('/settings/brands'));
});

test('Back goes to the parent list when a page was opened directly', () => {
    assert.equal(parentOf('/articles/9'), '/articles');
    assert.equal(parentOf('/settings/data'), '/');
});

test('Shipping has no date range or article search', () => {
    assert.ok(pathMatches('/shipping', '/shipping'));
    assert.equal(usesRange('/shipping'), false);
    assert.equal(showsSearch('/shipping'), false);
});
