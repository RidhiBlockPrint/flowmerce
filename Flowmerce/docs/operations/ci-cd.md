# CI/CD

Status (2026-11-18): CI runs on GitHub from the repository root (`.github/workflows/ci.yml` in *Flowmerce Main*; the jobs work inside `Flowmerce/`). After every check passes on `main`, a **demo-only** deploy publishes the frontend to GitHub Pages: https://ridhiblockprint.github.io/flowmerce/ The real app (backend, keys, data) is never deployed; see "Demo deploy" and "Not included".

Decision record: [ADR 0004](../decisions/0004-ci-cd-github-actions.md).

## What runs and when

Workflow: `.github/workflows/ci.yml` at the root of the repository (one level above this `Flowmerce/` folder). It runs on every push to `main`, on every pull request, and on demand (Actions tab, *Run workflow*). No job uses secrets. CI jobs have read-only repository access; only the Pages deploy job gets `pages: write` and `id-token: write`.

| Job (check name) | What it does | Fails when |
|---|---|---|
| `Python 3.12` and `Python 3.14` | `pip install -e ".[dev,seo]"`, then `ruff check .`, `mypy` (strict) and `pytest -q` | any of the three fails on that Python version |
| `Frontend` | Node 24, `npm ci`, `npm run build` (Next.js build; there is no TypeScript step) | the lockfile is out of sync or the build fails |
| `Smoke test` | Builds the frontend, then `python scripts/ci_smoke.py --web` on Python 3.12: boots the API and the built Next.js frontend on a throwaway folder and probes both | the app does not start, the operator context or `/api/home` is wrong, login is not disabled, CSRF is not enforced, a working route does not render, or an unbuilt route is not a not-found page |

`.github/dependabot.yml` opens weekly update pull requests for the Python packages, the frontend packages and the GitHub Actions themselves. Nothing merges automatically.

## Run the same checks on your machine

From the repository root, in the project's virtual environment (Windows PowerShell):

```powershell
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m mypy
.venv\Scripts\python.exe -m pytest -q
cd frontend
npm run build
cd ..
.venv\Scripts\python.exe scripts\ci_smoke.py --web
```

`scripts/ci_smoke.py` is safe to run any time: it uses a fresh temporary folder (never your `.env` or `data/`), turns the scheduler and live publishing off, binds to `127.0.0.1` and deletes the folder afterwards. Without `--web` it checks only the API. With `--web` the API uses port 8787, so stop a running Flowmerce first.

## One-time GitHub settings (only the repository owner can do these)

Open the repository on GitHub, then **Settings**:
1. **Actions, General:** make sure Actions are allowed, and under *Workflow permissions* choose **Read repository contents permission**.
2. Push a commit or open a pull request so CI runs once. The check names above only appear in the settings after the first run.
3. **Branches, Add branch protection rule** for `main`: tick *Require status checks to pass before merging* and select `Python 3.12`, `Python 3.14`, `Frontend` and `Smoke test`. Decide whether to also require pull requests.
4. **Code security:** turn on *Dependabot alerts* and *Dependabot security updates*.

Without step 3, CI reports problems but does not stop a merge.

## When a check fails

- Open the **Actions** tab, click the failed run, then the failed job and step. The log shows the exact command and its output.
- **Only `Python 3.12` fails:** the code has probably used something newer than the declared minimum. It was developed on Python 3.14, so this is a likely first finding, and a real one.
- **`npm ci` fails:** `frontend/package.json` and `frontend/package-lock.json` disagree.
- **`Smoke test` fails to start the app:** the log prints the last server output. Reproduce it with the local command above.
- Re-run a job from the run page ("Re-run jobs") if you suspect a temporary GitHub problem.

## Demo deploy (CD)

Jobs `Build demo for GitHub Pages` and `Deploy demo to GitHub Pages` run only on `main`, only after `Frontend` and `Smoke test` pass. The build is a static export (`FLOWMERCE_STATIC_EXPORT=1`, base path `/flowmerce`, `NEXT_PUBLIC_FLOWMERCE_DATA_SOURCE=demo`) in `frontend/out`. The result is public at **https://ridhiblockprint.github.io/flowmerce/** and shows **synthetic data only**: no backend, no Shopify, Google or Supabase keys, nothing connected. Changes a visitor makes stay in their own browser.

- The static export leaves out what needs a server: the `/api` forwarding, the old-address redirects (`/blogs`, `/seo`, ...) and the security headers. Your normal build (`npm run build`) is unchanged.
- Article pages `/articles/1` to `/articles/500` are pre-built; a demo article with a higher number opens only by navigating inside the app.
- GitHub Pages needs a public repository on the free plan; this repository was made public on 2026-11-18. Settings → Pages must stay on *Source: GitHub Actions*.

Build the same thing locally (PowerShell, in `frontend`): `$env:FLOWMERCE_STATIC_EXPORT='1'; $env:NEXT_PUBLIC_BASE_PATH='/flowmerce'; $env:NEXT_PUBLIC_FLOWMERCE_DATA_SOURCE='demo'; npm run build`, then serve `out` under `/flowmerce/`.

## Not included (deliberately)

- **Deployment of the real app** is set up separately on Render with a sign-in gate; see [hosting-render.md](hosting-render.md). Never expose the local app (no sign-in) to the internet. Render keeps the SEO SQLite database in Supabase Storage with Litestream until the database move (roadmap B1).
- **Release artifacts and a container image** (a possible Stage B), pending your approval.
- **Dependency vulnerability scanning** (`pip-audit`, `npm audit`). Add it as advisory first so a known issue does not block every merge.
- **A format check** (`ruff format --check`): the migrated SEO code was never formatted, so it would fail today. The pipeline checks only what currently passes.
- **Frontend tests and lint:** none exist yet.

## Maintenance

- **Actions are pinned to full commit hashes**, with the version in a trailing comment. Dependabot proposes updates; review them like any other change. The hashes were checked against GitHub's API when they were added.
- To add a check, add a step to the right job in `ci.yml` and a line to the table above, and keep the local command in the section above in sync.
- Keep logic in Python scripts (`scripts/`) and keep workflow steps to one-line commands, as the project's language rule requires.

## Security notes

- CI needs no secrets and has none. The `.env` file and `data/` never reach GitHub (they are git-ignored).
- Jobs run with read-only repository permission and do not keep the checkout token (`persist-credentials: false`).
- The smoke test signs in only to its own throwaway instance, with a password the instance generated, and never prints it.
