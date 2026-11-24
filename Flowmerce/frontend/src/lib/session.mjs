/**
 * Hosted-mode sign-in cookie (used by src/middleware.js only).
 *
 * The cookie holds `v2.<expiry seconds>.<session token>.<HMAC-SHA256 signature>`.
 *   - The session token comes from the Python API when a person signs in. The API looks it up on every call,
 *     so it decides who the person is, what their role allows, and whether the session still exists.
 *   - The signature lets the middleware refuse a made-up or expired cookie on every page without asking the
 *     API. Its key is derived from the owner key (FLOWMERCE_LOGIN_USER and FLOWMERCE_LOGIN_PASSWORD), so
 *     changing FLOWMERCE_LOGIN_PASSWORD signs everyone out.
 * Web Crypto only: runs in Next.js middleware and in Node.
 */

export const SESSION_COOKIE = 'fm_session';
/** Set by the earlier shared sign-in to show a username. No longer used (the app asks the API who is signed in); only cleared. */
export const LEGACY_NAME_COOKIE = 'fm_hosted';
export const LONG_SESSION_SECONDS = 30 * 24 * 3600;
export const SHORT_SESSION_SECONDS = 12 * 3600;

const enc = new TextEncoder();
/** What the API's tokens look like (URL-safe base64). Anything else is never signed or accepted. */
const TOKEN = /^[A-Za-z0-9_-]{20,200}$/;

function b64url(bytes) {
  let s = '';
  for (const b of new Uint8Array(bytes)) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

async function key(user, password) {
  return crypto.subtle.importKey('raw', enc.encode(`flowmerce-session-v2\u0000${user}\u0000${password}`),
    { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
}

async function sign(user, password, token, exp) {
  return b64url(await crypto.subtle.sign('HMAC', await key(user, password), enc.encode(`${token}.${exp}`)));
}

/** Compare without stopping at the first difference, so timing does not reveal how much of a guess was right. */
export function same(a, b) {
  let diff = a.length ^ b.length;
  for (let i = 0; i < Math.max(a.length, b.length); i++) diff |= (a.charCodeAt(i) || 0) ^ (b.charCodeAt(i) || 0);
  return diff === 0;
}

/** The cookie value for a session the API just started. `user` and `password` are the owner key (the signing secret). */
export async function createToken(user, password, sessionToken, seconds) {
  if (!TOKEN.test(sessionToken)) throw new Error('Unexpected session token.');
  const exp = Math.floor(Date.now() / 1000) + seconds;
  return `v2.${exp}.${sessionToken}.${await sign(user, password, sessionToken, exp)}`;
}

/** True when the cookie was issued by this server with the current owner key and has not expired. */
export async function verifyToken(cookie, user, password) {
  if (!cookie) return false;
  const [v, expText, token, sig, extra] = cookie.split('.');
  const exp = Number(expText);
  if (v !== 'v2' || extra !== undefined || !Number.isInteger(exp) || exp < Date.now() / 1000) return false;
  if (!token || !TOKEN.test(token) || !sig) return false;
  return same(sig, await sign(user, password, token, exp));
}
