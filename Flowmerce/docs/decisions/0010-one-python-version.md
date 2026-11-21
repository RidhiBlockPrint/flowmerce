# ADR 0010: One Python version everywhere (3.14)

- Status: accepted (owner, 2026-11-21)
- Date: 2026-11-21

## Decision

The backend runs on **Python 3.14** and only 3.14, in every place it runs:

| Where | Set in |
|---|---|
| The owner's computer (`.venv`, `scripts/run_flowmerce.py`) | `.python-version`; the launcher stops with a clear message on any other version |
| CI (lint, type check, tests, smoke test) | `.github/workflows/ci.yml` |
| The hosted app on Render | `Dockerfile` (`python:3.14-slim-trixie`) |
| Packaging and type checking | `pyproject.toml` (`requires-python = ">=3.14,<3.15"`, mypy `python_version = "3.14"`; ruff takes its target from `requires-python`) |

## Rationale

Before this, the hosted app ran 3.12, the owner's computer 3.14.7 (the only version installed), CI both, and the
docs said 3.10+, 3.12+ or "tested on 3.13". A difference between the version things are built and tested on and the
version that runs live can break the live app without showing up anywhere else. 3.14 was chosen because it is what
the owner's computer already has, and CI was already running the full test suite on it.

## Alternatives considered

- **3.12 everywhere:** the live app would not change, but the owner would have to install 3.12 and rebuild `.venv`,
  and development would move to an older version.
- **Keep a range (3.12+) and test the ends:** what ADR 0004 set up. It still lets the computer and the live app differ.

## Advantages

- What is built and tested is what runs live. One CI Python job instead of two.

## Disadvantages

- Anyone setting up the project needs exactly 3.14; the launcher says so.
- The hosted image changes base version, so the first deploy after this is the first time the live app runs on 3.14.

## Consequences and dependencies

- Evidence at the time of the decision: on 3.14, `mypy` gave the same 52 existing errors as on 3.12, `ruff` the same
  985 existing findings with a 3.14 target, and pytest the same results (710 passed, the one known failure).
- Moving to 3.15 later is one change in the five places above plus this record.
- Supersedes the "3.12 and 3.14" test matrix in ADR 0004 (the rest of ADR 0004 stands).
