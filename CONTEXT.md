# CONTEXT.md

Current state of the repository. Update this whenever a phase completes or a
significant decision is made.

**Last updated:** 2026-09-24
**Current phase:** Phase 0 — Project Initialization (complete)

---

## 1. What this project is

A quantitative stock intelligence and decision-support system for Indonesian
equities. Its output is an evidence-backed explanation — business quality,
valuation, technical condition, event impact, historical precedent, and risk,
each preserved separately — not a single BUY/SELL score.

The governing document is [CLAUDE.md](CLAUDE.md). It takes precedence over this
file wherever they disagree.

---

## 2. What exists right now

Scaffolding only. **No analytical code has been written.** There is no data
ingestion, no valuation model, no technical indicator, no NLP, no ML, no
backtester, and no dashboard.

| Area | State |
| --- | --- |
| Git repository | Initialized, branch `main`, no commits yet |
| Python environment | `.venv` on Python 3.13.15 |
| Package layout | All packages from CLAUDE.md §25 created, docstring only |
| Configuration | `backend/config.py` — env-driven `Settings` (Pydantic) |
| Database | Alembic scaffold; **zero migrations, zero tables** |
| Infrastructure | `docker-compose.yml` for PostgreSQL 17 + Redis 7 (never run) |
| Tests | 38 passing scaffold/config smoke tests |
| Frontend | `dashboard/` is an empty placeholder |

---

## 3. Development environment (verified 2026-09-24)

| Tool | Version | Notes |
| --- | --- | --- |
| Python | 3.13.15 | `py -3.13`; used for `.venv` |
| Python | 3.14.7 | present, deliberately unused |
| pip | 26.2.1 | |
| Git | 2.55.0.windows.3 | |
| Docker | **not installed** | blocks running PostgreSQL/Redis |
| Docker Compose | **not installed** | |
| Node.js | 24.21.0 | at `C:\Program Files\nodejs`, **not on `PATH`** |
| npm | 11.19.0 | same |

OS: Windows 11. Development is local-first (CLAUDE.md §24).

---

## 4. Installed Python packages

Runtime: `pydantic` 2.13.5, `pydantic-settings` 2.15.0, `SQLAlchemy` 2.0.54,
`alembic` 1.20.0, `psycopg[binary]` 3.3.6.

Dev: `pytest` 9.1.1, `ruff` 0.16.8, `mypy` 2.3.1.

Nothing else. `pandas`, `numpy`, `scipy`, `scikit-learn`, `xgboost`,
`lightgbm`, `fastapi`, and `celery` are **declared as optional extras** in
`pyproject.toml` but intentionally not installed — each is installed when its
phase begins.

---

## 5. Decisions made in Phase 0

| # | Decision | Reason |
| --- | --- | --- |
| D1 | Python **3.13**, not 3.14 | The planned ML stack lacks reliable 3.14 wheels. Reversible by recreating `.venv`. |
| D2 | Git default branch `main` | Convention; repo had no commits, so the rename was free. |
| D3 | Only PostgreSQL and Redis run in Docker | CLAUDE.md §24: application code, tests, and research run on the host. |
| D4 | Later-phase dependencies declared but not installed | Keeps the environment small and makes each phase's dependency footprint explicit. |
| D5 | Alembic URL injected from `backend.config`, not `alembic.ini` | Credentials stay in `.env` (CLAUDE.md §29). |
| D6 | `backend/models` exports an empty `MetaData` | Gives autogenerate a stable target before any schema exists. |
| D7 | `.env.example` contains **no** data-provider keys | No provider has been vetted for licence terms (CLAUDE.md Rules 7–8). |
| D8 | `dashboard/` left empty | Phase 12. Scaffolding a frontend with nothing to render is pure maintenance cost. |

---

## 6. Deliberately NOT done

* No database schema. Table design begins in Phase 2, group by group.
* No data source integration, no API client, no scraper.
* No ML, no NLP models, no feature engineering.
* No FastAPI application object or routes.
* No Celery app or worker tasks.
* No CI configuration.

---

## 7. Open decisions

Tracked in detail in [PROJECT_PLAN.md](PROJECT_PLAN.md) → *Open decisions*.
The blocking one is **data sourcing**: no market-data, fundamental, or news
provider has been chosen, and none may be added before its licence terms,
redistribution rules, and rate limits are reviewed.

---

## 8. Invariants to preserve

These are the rules most likely to be violated silently later:

1. **No look-ahead.** Every time-sensitive record carries `event_time`,
   `publication_time`, `available_at`, or `effective_date`, and features may
   only read data available at the decision timestamp (CLAUDE.md §15).
2. **No random shuffling** of time-series data — time-based splits and
   walk-forward validation only (CLAUDE.md §14).
3. **Survivorship bias.** The historical universe must include delisted,
   suspended, merged, and renamed companies (CLAUDE.md §16).
4. **No invented data.** If a source is unavailable, say so (CLAUDE.md Rule 7).
5. **No fake precision.** Probabilities require a defined, calibrated model
   (CLAUDE.md Rule 15).
6. **Raw and derived data stay separate.** Never overwrite raw records with
   calculated features.
