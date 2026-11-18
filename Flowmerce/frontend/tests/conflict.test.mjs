// Run with: node --test tests/   (from the frontend folder; no packages needed)
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { compareWithLatest, editedFields, exportEdits, preview, rebase } from '../src/lib/conflict.mjs';

const FIELDS = ['title', 'body_html', 'meta_description'];
const base = { title: 'T', body_html: '<p>one</p>', meta_description: '' };

test('editedFields lists only what the user changed', () => {
    const draft = { ...base, body_html: '<p>mine</p>' };
    assert.deepEqual(editedFields(draft, base, FIELDS), ['body_html']);
    assert.deepEqual(editedFields(null, base, FIELDS), []);
});

test('compare flags a clash only when the server changed the same field', () => {
    const draft = { ...base, body_html: '<p>mine</p>', title: 'My title' };
    const latest = { ...base, body_html: '<p>shopify</p>', meta_description: 'new seo' };
    const rows = compareWithLatest({ draft, base, latest, fields: FIELDS });
    const by = Object.fromEntries(rows.map((r) => [r.field, r]));
    assert.equal(by.body_html.clash, true);
    assert.equal(by.title.clash, false);
    assert.equal(by.body_html.mine, '<p>mine</p>');
    assert.equal(by.body_html.latest, '<p>shopify</p>');
    assert.equal(rows.length, 2);
});

test('rebase keeps the user text, takes untouched server changes, and reports clashes', () => {
    const draft = { ...base, body_html: '<p>mine</p>' };
    const latest = { ...base, body_html: '<p>shopify</p>', meta_description: 'new seo' };
    const r = rebase({ draft, base, latest, fields: FIELDS });
    assert.equal(r.merged.body_html, '<p>mine</p>');          // the user's edit is never dropped
    assert.equal(r.merged.meta_description, 'new seo');       // the server's change to an untouched field is not reverted
    assert.deepEqual(r.kept, ['body_html']);
    assert.deepEqual(r.taken, ['meta_description']);
    assert.deepEqual(r.clashes, ['body_html']);
});

test('rebase reports no clash when the server already has the same text', () => {
    const draft = { ...base, body_html: '<p>same</p>' };
    const latest = { ...base, body_html: '<p>same</p>' };
    assert.deepEqual(rebase({ draft, base, latest, fields: FIELDS }).clashes, []);
});

test('rebase never loses any user-edited field, whatever the server did', () => {
    const draft = { title: 'a', body_html: 'b', meta_description: 'c' };
    const latest = { title: 'x', body_html: 'y', meta_description: 'z' };
    const r = rebase({ draft, base, latest, fields: FIELDS });
    assert.deepEqual(r.merged, draft);
    assert.deepEqual(r.clashes.sort(), [...FIELDS].sort());
});

test('exportEdits contains every edited field and nothing else', () => {
    const draft = { ...base, body_html: '<p>mine</p>' };
    const out = JSON.parse(exportEdits({ draft, base, fields: FIELDS, title: 'T', version: 4 }));
    assert.deepEqual(out.fields, { body_html: '<p>mine</p>' });
    assert.equal(out.editedAgainstVersion, 4);
});

test('preview strips tags, handles empty and truncates', () => {
    assert.equal(preview('<p>Hello <b>world</b></p>'), 'Hello world');
    assert.equal(preview(''), '(empty)');
    assert.ok(preview('x'.repeat(500), 50).endsWith('…'));
});
