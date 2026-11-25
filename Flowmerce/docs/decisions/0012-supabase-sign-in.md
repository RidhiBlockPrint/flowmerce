# ADR 0012: People sign in through Supabase Auth; access comes from the `flowmerce` schema

- Status: accepted (owner, 2026-11-25: "start sign-in")
- Date: 2026-11-25
- Replaces, when configured: the local accounts and owner-key sign-in of ADR 0011. ADR 0011's gate, session cookie,
  account menu and guard stay.
- Source: the handover of 2026-11-25 (`FLOWMERCE_ACCESS.md`, `README.md`, `sql/01…17`) for the ERP's Supabase project.

## Context

The Flowmerce data is moving into the ERP's Supabase project, schema `flowmerce`. That database enforces access per
person with row-level security, and its people list is `flowmerce.member`. Flowmerce is given the project address and a
publishable key only: no service role key, no database password, no dashboard login. The handover asks that Flowmerce
keeps no second people list, keeps each person's tokens on the server, and makes every request as the person.

ADR 0011 (the day before) put accounts in Flowmerce's own SQLite file. That is a second people list.

## Decision

When `FLOWMERCE_SUPABASE_URL` and `FLOWMERCE_SUPABASE_KEY` are both set on the hosted copy:

1. **Supabase Auth checks the password.** `POST /api/auth/login` (still called only by the frontend gate) passes the
   email and password to Supabase. Flowmerce stores no password and compares none.
2. **The database says what the person may open.** Right after sign-in, and again at most once a minute, Flowmerce
   reads `flowmerce.my_access` with the person's own token: role, stores, sections, whether they see costs. No row
   means no access (not a member, or switched off), and the person is refused or signed out.
3. **Tokens stay on the server, encrypted.** Table `identity_sessions` holds one row per Flowmerce session with the
   Supabase tokens sealed with a key derived from `FLOWMERCE_LOGIN_PASSWORD`. They never appear in a response or a
   cookie. The token is renewed shortly before it runs out.
4. **Roles.** Supabase's role decides the Flowmerce permissions: owner and admin act as Admin; manager and editor as
   SEO Manager; viewer gets a new role that can only look. On top of the per-route permission checks, a viewer's
   changing request is refused everywhere, because Shipping and CRO routes only ask for "view".
5. **Sections.** The menu shows only the modules a person was given. The Shipping and CRO APIs refuse a person
   without that section.
6. **Stores.** The brand switch offers only the person's stores.
7. **People are managed in Supabase.** Settings → Team shows the list as the database shows it to the signed-in
   administrator, read-only. `POST` and `PATCH /api/users` answer 409.
8. **The owner key signs nobody in.** `FLOWMERCE_LOGIN_PASSWORD` remains required: it signs the session cookies and
   seals the stored tokens, so changing it still signs everyone out.
9. **A local record per person stays**, in `users`, because articles, tasks and the audit log point at it. It is
   written at sign-in from Supabase, holds no password, and its role column is not used for permissions.

Without the two settings the hosted copy behaves as in ADR 0011, and the owner's computer as in ADR 0005.

## Not done here (known limits)

- **Screens still read the old sources.** Shipping and CRO still use the earlier Supabase project with its service
  role key, and SEO & Blog its SQLite file. So the per-person rules of the new database (only their stores, costs
  hidden) are not yet applied to that data; only the menu, the two section checks and the viewer rule are. Moving
  each screen to the new schema, read as the person, is the next piece of work.
- **SEO & Blog routes are not matched to the `seo` section on the server**; the menu and the page hide them.
- **No "Reviewer / Approver".** Nobody maps to it, so approving content and publishing is done by owners and admins.
- **A viewer's local record** carries the role "reviewer" in `users.role`, because that column only allows the three
  local roles. Nothing reads it for permissions in this mode, but lists that pick people by that column would
  include viewers.
- **`identity_sessions` is created at start-up**, not by a numbered migration, so that it cannot collide with
  migration numbers on branches that are not merged yet. Fold it into the migrations once those have landed.
- **More than one workspace**: the first one is used.

## Alternatives considered

- **Keep ADR 0011's local accounts.** A second people list, against the handover, and nothing would link a person to
  the rows the database lets them see.
- **A direct database login for the server** (file 17 of the handover). Switched off by its author: such a login can
  read two Supabase-owned system tables.
- **Tokens in an encrypted cookie.** The handover asks that tokens do not go to the browser, and a renewed token
  could not be written back from a proxied API call.
- **Tokens in memory only.** The free Render plan restarts the app after 15 idle minutes; everyone would be signed
  out each time.

## Consequences and dependencies

- Files: `modules/seo/identity.py` (new), `auth.py`, `app.py`, `api.py`, `config.py`, `permissions.py`;
  `frontend/src/views/Team.jsx`, `components/Shell.jsx`, `lib/routes.mjs`, `middleware.js`, `app/login/page.jsx`.
- New dependency: `cryptography` (Fernet), declared in the `seo` extra.
- Tests: `tests/integration/seo/test_supabase_identity.py` (a stand-in for Supabase; no network).
- Checked against the real project on 2026-11-25 with the login the owner supplied: sign-in, `my_access`, `member`,
  token renewal and sign-out behave as the stand-in does. That login has the role admin, not viewer.
- Supabase being unreachable: signing in answers "not answering right now"; people already signed in keep their last
  known access for 15 minutes.

## Review date

When the Shipping screens move to the `flowmerce` schema.
