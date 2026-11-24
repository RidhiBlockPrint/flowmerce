// Run with: node --test tests/   (from the frontend folder; no packages needed)
// The hosted sign-in cookie (src/lib/session.mjs) and the passwords handed to team members (src/lib/passwords.mjs).
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { LONG_SESSION_SECONDS, SESSION_COOKIE, SHORT_SESSION_SECONDS, createToken, same, verifyToken } from '../src/lib/session.mjs';
import { generatePassword, passwordProblem } from '../src/lib/passwords.mjs';

const USER = 'admin';
const KEY = 'owner-key-for-tests-0123456789';
const TOKEN = 'Zk3vX9q_L-2bT7mN0pQwErTyUiOpAsDfGhJkLzXcVbN';   // the shape the API returns (43 URL-safe characters)

test('a cookie made for a session is accepted, and carries the session token for the API', async () => {
    const cookie = await createToken(USER, KEY, TOKEN, SHORT_SESSION_SECONDS);
    const [version, exp, token, sig] = cookie.split('.');
    assert.equal(version, 'v2');
    assert.equal(token, TOKEN);
    assert.ok(sig.length >= 40);
    assert.ok(Math.abs(Number(exp) - (Date.now() / 1000 + SHORT_SESSION_SECONDS)) < 5);
    assert.equal(await verifyToken(cookie, USER, KEY), true);
    assert.equal(SESSION_COOKIE, 'fm_session');
    assert.equal(LONG_SESSION_SECONDS, 30 * 24 * 3600);
});

test('a changed, made-up or expired cookie is refused', async () => {
    const cookie = await createToken(USER, KEY, TOKEN, 60);
    const [v, exp, token, sig] = cookie.split('.');
    const other = TOKEN.replace('Zk3', 'Zk4');
    const refused = [
        '', undefined, 'made-up', 'v2...', `v2.${exp}.${token}`,
        `v2.${exp}.${other}.${sig}`,                       // someone else's session token with this signature
        `v2.${Number(exp) + 86400}.${token}.${sig}`,       // a later expiry with this signature
        `v2.${exp}.${token}.${sig.slice(0, -1)}x`,
        `v2.${exp}.${token}.${sig}.extra`,
        `v1.${exp}.${sig}`,                                // the earlier shared-password cookie
        `${v}.${exp}.${token}.`,
    ];
    for (const value of refused) assert.equal(await verifyToken(value, USER, KEY), false, String(value));
    const old = await createToken(USER, KEY, TOKEN, -10);
    assert.equal(await verifyToken(old, USER, KEY), false);
});

test('changing the owner key signs everyone out', async () => {
    const cookie = await createToken(USER, KEY, TOKEN, 60);
    assert.equal(await verifyToken(cookie, USER, `${KEY}-changed`), false);
    assert.equal(await verifyToken(cookie, 'someone-else', KEY), false);
    assert.equal(await verifyToken(cookie, USER, KEY), true);
});

test('only a token shaped like the API\'s is ever signed', async () => {
    for (const bad of ['', 'short', 'has.a.dot.in.it.and.is.long.enough', 'has spaces in it and is long enough', `${TOKEN};path=/`]) {
        await assert.rejects(() => createToken(USER, KEY, bad, 60), /Unexpected session token/);
    }
});

test('same() compares whole strings', () => {
    assert.ok(same('abc', 'abc') && same('', ''));
    assert.ok(!same('abc', 'abd') && !same('abc', 'abcd') && !same('abc', ''));
});

test('a generated password is 16 look-alike-free characters in four groups and passes the rule', () => {
    const seen = new Set();
    for (let i = 0; i < 200; i += 1) {
        const p = generatePassword();
        assert.match(p, /^[a-km-np-z2-9]{4}(-[a-km-np-z2-9]{4}){3}$/);
        assert.equal(passwordProblem(p), '');
        seen.add(p);
    }
    assert.equal(seen.size, 200);
    // Every byte value maps to a symbol, evenly: 256 values over 32 symbols is 8 each.
    const counts = {};
    for (let b = 0; b < 256; b += 1) {
        const ch = generatePassword((bytes) => bytes.fill(b))[0];
        counts[ch] = (counts[ch] ?? 0) + 1;
    }
    assert.equal(Object.keys(counts).length, 32);
    assert.ok(Object.values(counts).every((n) => n === 8));
});

test('a typed password needs 12 to 200 characters', () => {
    assert.match(passwordProblem('short'), /at least 12/);
    assert.match(passwordProblem(undefined), /at least 12/);
    assert.equal(passwordProblem('twelve chars'), '');
    assert.match(passwordProblem('x'.repeat(201)), /200 characters or fewer/);
});
