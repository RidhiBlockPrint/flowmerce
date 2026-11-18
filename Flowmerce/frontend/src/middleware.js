/**
 * Hosted-mode sign-in gate.
 *
 * Off unless FLOWMERCE_LOGIN_PASSWORD is set, so the local app on your own computer is unchanged (and /login
 * just goes to Home there). When it is set (the hosted copy, see docs/operations/hosting-render.md):
 *   - every page needs a signed session cookie; without one you are sent to the /login page,
 *   - /api calls without one get 401,
 *   - POST /auth/login checks the username (FLOWMERCE_LOGIN_USER, default "admin") and password and sets the
 *     cookie (12 hours, or 30 days with "Keep me signed in"); 5 wrong tries lock sign-in for 15 minutes,
 *   - /auth/logout clears it.
 * Exceptions: /healthz (the host's uptime probe; returns "ok" only) and POST /api/hooks/workflow, which
 * carries its own secret (X-Workflow-Secret) checked by the API. The Python API listens only inside the
 * container, so this gate is the one way in. Ignored by the static GitHub Pages demo build.
 */
import { NextResponse } from 'next/server';
import {
  HOSTED_COOKIE, LONG_SESSION_SECONDS, SESSION_COOKIE, SHORT_SESSION_SECONDS, createToken, same, verifyToken,
} from './lib/session.mjs';

export const config = {
  matcher: ['/((?!_next/static|_next/image|favicon.svg|brand/).*)'],
};

const MAX_FAILURES = 5;
const LOCK_MS = 15 * 60 * 1000;
/** Failed sign-ins per client address, kept in this server process only. */
const failures = new Map();

function clientKey(request) {
  return (request.headers.get('x-forwarded-for') || '').split(',')[0].trim() || 'unknown';
}

function locked(ip) {
  const f = failures.get(ip);
  if (!f) return false;
  if (Date.now() - f.first > LOCK_MS) { failures.delete(ip); return false; }
  return f.count >= MAX_FAILURES;
}

function recordFailure(ip) {
  const f = failures.get(ip);
  if (!f || Date.now() - f.first > LOCK_MS) failures.set(ip, { count: 1, first: Date.now() });
  else f.count += 1;
  if (failures.size > 5000) failures.clear();
}

/** Only same-site paths, never "//evil.example" or a full URL. */
function safeNext(value) {
  return typeof value === 'string' && value.startsWith('/') && !value.startsWith('//') && !value.startsWith('/\\')
    && !value.startsWith('/login') && !value.startsWith('/auth/') ? value : '/';
}

function isHttps(request) {
  return request.nextUrl.protocol === 'https:' || request.headers.get('x-forwarded-proto') === 'https';
}

/** Next.js needs an absolute address. The Host header is the address the browser used (also behind Render's
 *  proxy, with X-Forwarded-Proto https); request.url is not (it shows the bind address, e.g. 0.0.0.0). */
function redirectTo(request, path, status = 303) {
  const proto = request.headers.get('x-forwarded-proto') || request.nextUrl.protocol.replace(':', '');
  const host = request.headers.get('host') || request.nextUrl.host;
  return NextResponse.redirect(new URL(path, `${proto}://${host}`), status);
}

function noStore(response) {
  response.headers.set('Cache-Control', 'no-store');
  return response;
}

async function handleLogin(request, user, password) {
  const ip = clientKey(request);
  let form;
  try { form = await request.formData(); } catch { form = new FormData(); }
  const next = safeNext(String(form.get('next') || '/'));
  const back = (code) => redirectTo(request, `/login?error=${code}${next !== '/' ? `&next=${encodeURIComponent(next)}` : ''}`);

  if (locked(ip)) return noStore(back('locked'));
  const givenUser = String(form.get('username') || '').trim();
  const givenPassword = String(form.get('password') || '');
  if (!(same(givenUser, user) & same(givenPassword, password))) {
    recordFailure(ip);
    await new Promise((r) => setTimeout(r, 400));
    return noStore(back(locked(ip) ? 'locked' : 'invalid'));
  }
  failures.delete(ip);
  const remember = form.get('remember') === 'on';
  const seconds = remember ? LONG_SESSION_SECONDS : SHORT_SESSION_SECONDS;
  const response = redirectTo(request, next);
  const common = { path: '/', sameSite: 'lax', secure: isHttps(request), ...(remember ? { maxAge: seconds } : {}) };
  response.cookies.set(SESSION_COOKIE, await createToken(user, password, seconds), { ...common, httpOnly: true });
  response.cookies.set(HOSTED_COOKIE, user, { ...common, httpOnly: false });
  return noStore(response);
}

export async function middleware(request) {
  const password = process.env.FLOWMERCE_LOGIN_PASSWORD || '';
  const hosted = process.env.FLOWMERCE_HOSTED === '1';
  const { pathname, search } = request.nextUrl;

  if (pathname === '/healthz') return noStore(new NextResponse('ok', { status: 200 }));
  if (!password) {
    // Fail closed: a hosted copy without a password must never serve the app.
    if (hosted) return new NextResponse('Sign-in is not configured (FLOWMERCE_LOGIN_PASSWORD).', { status: 503 });
    // Local operator mode has no sign-in: next.config.mjs sends /login straight to Home (non-hosted builds).
    return NextResponse.next();
  }
  if (pathname === '/api/hooks/workflow' && request.method === 'POST') return NextResponse.next();

  const user = process.env.FLOWMERCE_LOGIN_USER || 'admin';
  if (pathname === '/auth/login' && request.method === 'POST') return handleLogin(request, user, password);
  if (pathname === '/auth/logout') {
    const response = redirectTo(request, '/login?signed_out=1');
    response.cookies.delete(SESSION_COOKIE);
    response.cookies.delete(HOSTED_COOKIE);
    return noStore(response);
  }

  const signedIn = await verifyToken(request.cookies.get(SESSION_COOKIE)?.value, user, password);
  if (pathname === '/login') return signedIn ? redirectTo(request, '/', 307) : noStore(NextResponse.next());
  if (signedIn) return NextResponse.next();

  if (pathname.startsWith('/api/')) {
    return noStore(NextResponse.json({ error: 'Sign in to continue.', code: 'signed_out' }, { status: 401 }));
  }
  const next = pathname === '/' ? '' : `?next=${encodeURIComponent(pathname + search)}`;
  return noStore(redirectTo(request, `/login${next}`, 307));
}
