# ADR 0011: Each person signs in with their own account on the hosted copy

- Status: accepted (owner, 2026-11-24)
- Date: 2026-11-24
- Amends: ADR 0005 (local operator mode stays as it is on the owner's computer; the hosted copy no longer acts as one
  shared administrator) and ADR 0006 (the unmounted `views/Users.jsx` is replaced by Settings → Team).
- Supersedes, for now: decision D3 in `docs/FLOWMERCE_DATABASE_AND_BUILD_PLAN.md` (Google sign-in through Supabase
  Auth in Phase 5). That can still replace this later; nothing here blocks it.

## Context

The hosted copy on Render had one shared sign-in (`admin` and one password) checked by the Next.js middleware. The
Python API saw every call as coming from this computer and acted as the first administrator. So everyone who had the
password was the same administrator: the audit log could not say who did what, removing one person meant changing the
password for everyone, and the rule that you cannot approve your own publish request never applied.

The pieces for separate accounts already existed and were switched off: the `users` and `sessions` tables, scrypt
password hashing, `/api/users`, and a role-to-permission map that every API route already checks.

## Decision

On the hosted copy only (`FLOWMERCE_HOSTED=1`, set by `scripts/run_hosted.py`):

1. **The Python API decides who is signed in.** Every `/api` call must carry a live session. The guard in
   `modules/seo/app.py` loads the person from the session and the existing permission checks apply their role.
   No session: `401 signed_out`.
2. **Sign-in.** The sign-in form posts to the middleware (`/auth/login`), which passes the email and password to
   `POST /api/auth/login` inside the container. The API checks them against that person's record, starts a row in
   `sessions` (12 hours, or 30 days with "Keep me signed in") and returns the token. Only the frontend can call it: the
   call must carry `FLOWMERCE_INTERNAL_SECRET`, generated at every start and known only to the two processes.
3. **Cookie.** `fm_session` holds `v2.<expiry>.<session token>.<signature>`. The middleware checks the signature on
   every page and API request, so a made-up cookie never reaches the app; the API looks the token up on every call, so
   deactivating a person or resetting their password takes effect at once.
4. **Owner key.** The username `FLOWMERCE_LOGIN_USER` (default `admin`) with `FLOWMERCE_LOGIN_PASSWORD` signs in as the
   first active administrator. It is how the owner gets in the first time and a way back in if every admin password is
   lost. The same value signs the cookies, so changing it in Render signs everyone out.
5. **Roles.** The three existing roles (Admin, SEO Manager, Reviewer). Everyone can open every section; roles limit SEO
   writing, approval, publishing and settings. Per-section access was considered and left for later (owner, 2026-11-24).
6. **Passwords.** An administrator adds a person on Settings → Team; the browser generates a password, shows it once
   and the administrator passes it on. No email is sent. People change their own password from the account menu.
7. **No schema change.** `users` and `sessions` are used as they are.

Local operator mode (the owner's computer) and the demo build are unchanged: no sign-in, `/api/auth/login` answers 410.

## Throttling

Kept in the API process: 8 wrong passwords for one email from one address, 20 for one email from any address, or 40
from one address pause that key for 15 minutes. The owner key is not paused per name, so nobody can lock the owner out
by guessing; it is a 16+ character generated secret. Failed sign-ins are written to the audit log only for real
accounts, so what someone types for an unknown name is never stored.

## Alternatives considered

- **Keep the shared password and add a "who are you" field.** No real identity; anyone can pick any name.
- **The middleware checks accounts itself.** It runs in the Edge runtime and cannot read the SQLite database.
- **A trusted header from the middleware naming the user.** Works, but one forwarding mistake would let a browser name
  itself. Looking up a random session token in the database has no such failure mode.
- **Google sign-in through Supabase Auth (plan decision D3).** More setup (OAuth client, redirect addresses, mapping
  Google accounts to roles) and a new dependency for a handful of people. Still possible later.
- **Email invitation links.** Needs an email-sending service; declined by the owner for now.

## Advantages

- The audit log, shipping notes and CRO change log record the real person.
- One person can be removed or have their password reset without touching anyone else.
- The publish approval rule (not your own request) applies again for non-administrators.

## Disadvantages

- The administrator has to hand over each first password personally.
- Sessions and the throttle counters live in one process and one SQLite file; fine for one small instance, not for
  several instances.
- The address used for throttling comes from the host's `X-Forwarded-For` header, which a caller can influence. The
  per-email limit does not depend on it.
- Shipping and CRO actions still need only the `view` permission, so every signed-in role can do them. That matches
  "everyone can open every section"; tightening it belongs with per-section access.

## Consequences and dependencies

- Files: `modules/seo/{auth,app,api,config}.py`, `frontend/src/middleware.js`, `frontend/src/lib/{session,passwords}.mjs`,
  `frontend/src/views/Team.jsx`, `frontend/src/components/Shell.jsx`, `frontend/src/app/login/page.jsx`,
  `scripts/run_hosted.py`, `scripts/hosted_probe.py`.
- Tests: `tests/integration/seo/test_hosted_auth.py`, `frontend/tests/session.test.mjs`, the CI job "Hosted container".
- User records live in the SEO SQLite database, which Litestream copies to Supabase Storage. Without
  `LITESTREAM_BUCKET` they are lost on restart.
- Separate logins do not raise capacity: the free Render plan is still sized for one person at a time
  (`docs/operations/hosting-render.md`).

## Review date

When per-section access, more than about ten people, or a second instance is needed.
