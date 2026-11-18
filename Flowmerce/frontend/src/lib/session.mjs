/**
 * Hosted-mode sign-in session (used by src/middleware.js only).
 *
 * The cookie holds `v1.<expiry seconds>.<HMAC-SHA256 signature>`. The signing key is derived from the configured
 * username and password, so changing FLOWMERCE_LOGIN_PASSWORD signs everyone out. Web Crypto only: runs in
 * Next.js middleware and in Node.
 */

export const SESSION_COOKIE = 'fm_session';
/** Readable by the page (not a secret): tells the app shell to show "Signed in" and Sign out. */
export const HOSTED_COOKIE = 'fm_hosted';
export const LONG_SESSION_SECONDS = 30 * 24 * 3600;
export const SHORT_SESSION_SECONDS = 12 * 3600;

const enc = new TextEncoder();

function b64url(bytes) {
  let s = '';
  for (const b of new Uint8Array(bytes)) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

async function key(user, password) {
  return crypto.subtle.importKey('raw', enc.encode(`flowmerce-session-v1\u0000${user}\u0000${password}`),
    { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
}

async function sign(user, password, exp) {
  return b64url(await crypto.subtle.sign('HMAC', await key(user, password), enc.encode(`${user}.${exp}`)));
}

/** Compare without stopping at the first difference, so timing does not reveal how much of a guess was right. */
export function same(a, b) {
  let diff = a.length ^ b.length;
  for (let i = 0; i < Math.max(a.length, b.length); i++) diff |= (a.charCodeAt(i) || 0) ^ (b.charCodeAt(i) || 0);
  return diff === 0;
}

export async function createToken(user, password, seconds) {
  const exp = Math.floor(Date.now() / 1000) + seconds;
  return `v1.${exp}.${await sign(user, password, exp)}`;
}

export async function verifyToken(token, user, password) {
  if (!token) return false;
  const [v, expText, sig] = token.split('.');
  const exp = Number(expText);
  if (v !== 'v1' || !Number.isInteger(exp) || exp < Date.now() / 1000 || !sig) return false;
  return same(sig, await sign(user, password, exp));
}
