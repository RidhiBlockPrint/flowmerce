/**
 * Hosted-mode sign-in gate (HTTP Basic auth over HTTPS).
 *
 * Off unless FLOWMERCE_LOGIN_PASSWORD is set, so the local app on your own computer is unchanged. When it is set
 * (the hosted copy, see docs/operations/hosting-render.md), every page and /api call needs the username
 * (FLOWMERCE_LOGIN_USER, default "admin") and that password. The browser asks once and remembers it.
 *
 * Exceptions: /healthz (the host's uptime probe, returns "ok" and nothing else) and the workflow webhook
 * POST /api/hooks/workflow, which carries its own secret (X-Workflow-Secret) checked by the API.
 * The Python API itself listens only inside the container, so this gate is the one way in.
 */
import { NextResponse } from 'next/server';

export const config = {
  matcher: ['/((?!_next/static|_next/image|favicon.svg).*)'],
};

/** Compare without stopping at the first difference, so timing does not reveal how much of a guess was right. */
function same(a, b) {
  let diff = a.length ^ b.length;
  for (let i = 0; i < Math.max(a.length, b.length); i++) diff |= (a.charCodeAt(i) || 0) ^ (b.charCodeAt(i) || 0);
  return diff === 0;
}

function credentials(header) {
  if (!header || !header.startsWith('Basic ')) return null;
  try {
    const bytes = Uint8Array.from(atob(header.slice(6).trim()), (c) => c.charCodeAt(0));
    const text = new TextDecoder().decode(bytes);
    const i = text.indexOf(':');
    return i < 0 ? null : [text.slice(0, i), text.slice(i + 1)];
  } catch {
    return null;
  }
}

export function middleware(request) {
  const password = process.env.FLOWMERCE_LOGIN_PASSWORD || '';
  const hosted = process.env.FLOWMERCE_HOSTED === '1';
  const { pathname } = request.nextUrl;

  if (pathname === '/healthz') return new NextResponse('ok', { status: 200, headers: { 'Cache-Control': 'no-store' } });
  if (!password) {
    // Fail closed: a hosted copy without a password must never serve the app.
    return hosted ? new NextResponse('Sign-in is not configured (FLOWMERCE_LOGIN_PASSWORD).', { status: 503 }) : NextResponse.next();
  }
  if (pathname === '/api/hooks/workflow' && request.method === 'POST') return NextResponse.next();

  const user = process.env.FLOWMERCE_LOGIN_USER || 'admin';
  const given = credentials(request.headers.get('authorization'));
  if (given && (same(given[0], user) & same(given[1], password))) return NextResponse.next();

  return new NextResponse('Sign-in required.', {
    status: 401,
    headers: { 'WWW-Authenticate': 'Basic realm="Flowmerce", charset="UTF-8"', 'Cache-Control': 'no-store' },
  });
}
