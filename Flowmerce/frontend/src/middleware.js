/**
 * Hosted-mode sign-in gate.
 *
 * Off unless FLOWMERCE_LOGIN_PASSWORD is set, so the local app on your own computer is unchanged (and /login
 * just goes to Home there). When it is set (the hosted copy, see docs/operations/hosting-render.md):
 *   - every page needs a signed session cookie; without one you are sent to the /login page,
 *   - /api calls without one get 401,
 *   - POST /auth/login passes the email and password to the Python API, which checks them against that
 *     person's own account (or the owner key: FLOWMERCE_LOGIN_USER, default "admin", with
 *     FLOWMERCE_LOGIN_PASSWORD), starts their session and pauses sign-in after repeated wrong passwords.
 *     The cookie lasts 12 hours, or 30 days with "Keep me signed in",
 *   - /auth/logout ends the session and clears the cookie.
 * The cookie's signature is checked here on every request; the API then looks the session up on every call,
 * so it decides who the person is and what their role allows (src/lib/session.mjs).
 * Exceptions: /healthz (the host's uptime probe; returns "ok" only) and POST /api/hooks/workflow, which
 * carries its own secret (X-Workflow-Secret) checked by the API. The Python API listens only inside the
 * container, so this gate is the one way in. Ignored by the static GitHub Pages demo build.
 */
import { NextResponse } from 'next/server';
import { LEGACY_NAME_COOKIE, SESSION_COOKIE, createToken, verifyToken } from './lib/session.mjs';

export const config = {
  matcher: ['/((?!_next/static|_next/image|favicon.svg|brand/).*)'],
};

/** Marks a call as made by this server itself. The API accepts sign-in only with it; a browser may never send it. */
const INTERNAL_HEADER = 'x-flowmerce-internal';
const FAILURE_DELAY_MS = 400;

/** Only same-site paths, never "//evil.example" or a full URL. */
function safeNext(value) {
  return typeof value === 'string' && value.startsWith('/') && !value.startsWith('//') && !value.startsWith('/\\')
    && !value.startsWith('/login') && !value.startsWith('/auth/') ? value : '/';
}

function isHttps(request) {
  return request.nextUrl.protocol === 'https:' || request.headers.get('x-forwarded-proto') === 'https';
}

/** The browser's address as the host's proxy reports it. Used by the API to pause repeated wrong passwords. */
function clientAddress(request) {
  return (request.headers.get('x-forwarded-for') || '').split(',')[0].trim().slice(0, 60) || 'unknown';
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

/** A direct call from this server to the Python API (inside the container; never through the public address). */
function callApi(path, { body, cookie, internal = false } = {}) {
  const origin = process.env.FLOWMERCE_API_ORIGIN || 'http://127.0.0.1:8787';
  const headers = { 'Content-Type': 'application/json', Accept: 'application/json', 'X-Requested-With': 'blog-ops' };
  if (internal) headers[INTERNAL_HEADER] = process.env.FLOWMERCE_INTERNAL_SECRET || '';
  if (cookie) headers.Cookie = `${SESSION_COOKIE}=${cookie}`;
  return fetch(`${origin}/api${path}`, {
    method: 'POST', headers, body: JSON.stringify(body ?? {}), cache: 'no-store', signal: AbortSignal.timeout(20_000),
  });
}

function clearCookies(response) {
  response.cookies.delete(SESSION_COOKIE);
  response.cookies.delete(LEGACY_NAME_COOKIE);
  return response;
}

async function handleLogin(request, user, password) {
  let form;
  try { form = await request.formData(); } catch { form = new FormData(); }
  const next = safeNext(String(form.get('next') || '/'));
  const back = (code) => noStore(redirectTo(request, `/login?error=${code}${next !== '/' ? `&next=${encodeURIComponent(next)}` : ''}`));
  const remember = form.get('remember') === 'on';

  let answer;
  let data = null;
  try {
    answer = await callApi('/auth/login', {
      internal: true,
      body: {
        username: String(form.get('username') || '').trim().slice(0, 200),
        password: String(form.get('password') || '').slice(0, 300),
        remember,
        address: clientAddress(request),
      },
    });
    data = await answer.json();
  } catch {
    return back('unavailable');
  }
  if (answer.status === 429) return back('locked');
  if (answer.status === 403 && data?.code === 'no_access') return back('no_access');   // right password, not on the people list
  if (answer.status === 401) {
    await new Promise((r) => setTimeout(r, FAILURE_DELAY_MS));
    return back('invalid');
  }
  if (!answer.ok || !data?.token || !Number.isInteger(data.seconds)) return back('unavailable');

  let cookie;
  try { cookie = await createToken(user, password, data.token, data.seconds); } catch { return back('unavailable'); }
  const response = redirectTo(request, next);
  const common = { path: '/', sameSite: 'lax', secure: isHttps(request), ...(remember ? { maxAge: data.seconds } : {}) };
  response.cookies.set(SESSION_COOKIE, cookie, { ...common, httpOnly: true });
  response.cookies.delete(LEGACY_NAME_COOKIE);
  return noStore(response);
}

/** Sign out, or (with ?expired=1, sent by the app when the API no longer knows the session) just clear the cookie. */
async function handleLogout(request) {
  const cookie = request.cookies.get(SESSION_COOKIE)?.value;
  if (cookie) {
    try { await callApi('/auth/logout', { cookie }); } catch { /* the cookie is cleared either way */ }
  }
  const params = request.nextUrl.searchParams;
  const next = safeNext(params.get('next') || '/');
  const where = params.get('expired')
    ? `/login?error=expired${next !== '/' ? `&next=${encodeURIComponent(next)}` : ''}`
    : '/login?signed_out=1';
  return noStore(clearCookies(redirectTo(request, where)));
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
  // Only this server may mark a call as its own; a browser that tries is refused before anything is forwarded.
  if (request.headers.has(INTERNAL_HEADER)) return noStore(new NextResponse('Not allowed.', { status: 403 }));
  if (pathname === '/api/hooks/workflow' && request.method === 'POST') return NextResponse.next();

  const user = process.env.FLOWMERCE_LOGIN_USER || 'admin';
  if (pathname === '/auth/login' && request.method === 'POST') return handleLogin(request, user, password);
  if (pathname === '/auth/logout') return handleLogout(request);

  const signedIn = await verifyToken(request.cookies.get(SESSION_COOKIE)?.value, user, password);
  if (pathname === '/login') return signedIn ? redirectTo(request, '/', 307) : noStore(NextResponse.next());
  if (signedIn) return NextResponse.next();

  if (pathname.startsWith('/api/')) {
    return noStore(NextResponse.json({ error: 'Sign in to continue.', code: 'signed_out' }, { status: 401 }));
  }
  const next = pathname === '/' ? '' : `?next=${encodeURIComponent(pathname + search)}`;
  return noStore(redirectTo(request, `/login${next}`, 307));
}
