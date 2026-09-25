# CONTEXT.md

Current state of the repository. Update this whenever a phase completes or a
significant decision is made.

**Last updated:** 2026-09-25
**Current phase:** Phase 2 — Market data, **in progress**. Phase 2A (Pholenk
development ingestion) and Phase 2B (development persistence: data contract,
schema, snapshot loader, real load, and post-load verification) are complete.
Phase 2C (corporate actions, dividends, adjustment factors, adjusted series)
is complete. Phase 2D (market indices, observed trading calendar) is
implemented and loaded, pending review.
**Mode:** **$0 development mode** (2026-09-24). Production data is **BLOCKED**
on Q2 (no production provider selected; production licensing unresolved;
doc §32). Development data is **UNBLOCKED**: public development sources are
selected in
[docs/data_sources/market_data_requirements.md](docs/data_sources/market_data_requirements.md)
§36. Implementation proceeds on development data, through the
provider-neutral interface only.

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

Infrastructure, a file-based development market-data provider, and
PostgreSQL persistence of raw development daily prices. **No analytical code
has been written.** There are no corporate actions or adjusted prices, and no
valuation model, technical indicator, NLP, ML, backtester, or dashboard.

| Area | State |
| --- | --- |
| Git repository | Branch `main`; see *Git state* below |
| Python environment | `.venv` on Python 3.13.15 |
| Package layout | All packages from CLAUDE.md §25 created. Implementation code: `backend/config.py`, `backend/database.py`, `backend/models/` (Phase 2B tables), the provider-neutral interface `data/ingestion/provider.py`, the Pholenk development provider `data/ingestion/pholenk.py`, the snapshot loader (`data/ingestion/snapshot.py`, `loader.py`, `pholenk_snapshot.py`, CLI `load_snapshot.py`), daily-price validation/reporting `data/validation/daily_prices.py`, and read-only post-load verification `data/validation/verify_load.py`. Every other package is a docstring-only placeholder |
| Configuration | `backend/config.py` — env-driven `Settings` (Pydantic) |
| Database | One migration, `1c1d7048b74f` (8 Phase 2B tables). The development database holds Pholenk snapshot `9bb3b26`: 1,289,820 `daily_prices`, 983 securities, 1,043 source files, 1 ingestion run, 1 expected incident (loaded 2026-09-25; verified 47/47, and 51/51 with `--deep`). Phase 2C (migration `55a78b2c9066`): 1,652 corporate-action events (DS-9), 5,934 cash dividends (DS-7), and factor build `d1daa2d6` (212 applied price factors, 2,202 dividend factors, 18 reference-price anomaly dates). Phase 2D (migration `6117977fb001`): 63,919 index values (56 indices incl. IHSG `COMPOSITE`) and the `observed_trading_days` view (1,540 dates; 3 missing from the stock data) |
| Infrastructure | PostgreSQL 17.11 + Redis 7.4.11 via Docker Compose, both healthy |
| Tests | 195 passing. Integration tests that write data use a throwaway database (`migrated_database` fixture), so `pytest` leaves the development database unchanged. Phase 0 ended with 38 tests, Phase 1 with 43, and Phase 2A with 81. |
| Frontend | `dashboard/` is an empty placeholder |

### Git state (snapshot, 2026-09-25)

| Item | State |
| --- | --- |
| Branch | `main` |
| Commits on `origin/main` | … → `e6842ea` docs: finalize market data requirements → `a2beb24` docs: validate market data sources → `823920c` docs: establish zero-cost development data sources → `5014325` feat: add Pholenk development market data provider |
| Local commits after `5014325` | Not pushed (Phase 2B.2 onward); list with `git log origin/main..HEAD` |

This snapshot goes stale on every commit or push — update it when either happens.

---

## 3. Development environment (verified 2026-09-24)

| Tool | Version | Notes |
| --- | --- | --- |
| Python | 3.13.15 | `py -3.13`; used for `.venv` |
| Python | 3.14.7 | present, deliberately unused |
| pip | 26.2.1 | |
| Git | 2.55.0.windows.3 | |
| Docker | 29.8.0 | Docker Desktop |
| Docker Compose | v5.5.1 | |
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

## 5. Decisions

### Phase 0

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

### Phase 1

| # | Decision | Reason |
| --- | --- | --- |
| D9 | Integration tests skip (not fail) when services are down | Keeps the unit suite runnable without Docker; `-ra` reports every skip reason. |
| D10 | Redis checked with a raw RESP `PING` over a socket | Avoids installing the `redis` client before the `[workers]` phase. |
| D11 | 5 s database connect timeout | psycopg's 130 s default makes an unreachable database look like a hang. |

### Phase 2 preparation (Q2, owner decisions)

| # | Decision | Reason |
| --- | --- | --- |
| D12 | Budget decided only after provider comparison; cost is not pass/fail | Headline prices hide tier, coverage, and licence differences. |
| D13 | Private use now; rented cloud/VPS possibly later | Every licence must be checked for rented-server storage now. |
| D14 | Minimum history 2015-01-01 (≈ 2005 SHOULD) | Covers the §14 validation example plus indicator warm-up. |
| D15 | Store both price return and total return | Makes gross cash dividends a hard requirement. |
| D16 | Multiple data sources allowed | Requires shared IDs, per-record provenance, logged disagreements, and a precedence rule defined before ingestion. |
| D17 | $0 development mode: build on public development data now; production provider selection deferred | Production requirements stay unchanged; development sources (doc §36) are not declared to satisfy them. |
| D18 | Provider-agnostic architecture: all market data goes through `MarketDataProvider` with provenance on every record | Lets a production source replace development sources without downstream changes. |
| D19 | Core development OHLCV source: Pholenk/IDX-Dataset (ODbL; 2020-01-02 → 2026-05-29), with supplemental sources in doc §36.7 | Only full-universe raw IDX-format source found with an explicit open-data licence. Development only. |
| D20 | Source `Open = 0` → `open = None`; zero-volume rows with `High = Low = 0` → `NO_TRADE_OR_SUSPENDED` (kept, never dropped). *Status renamed by D23.* | The source supplies no open on most rows and does not distinguish suspension from no trading; nothing is fabricated. |
| D21 | Development identity `dev:pholenk-idx-dataset:<KEY>` | No stable ID in the source; explicitly not an ISIN and not stable across ticker changes. |
| D22 | Phase 2A adds no database tables | Canonical records are produced in memory; persistence is the next, separate step. *Superseded by Phase 2B (D23–D26).* |

### Phase 2B (development persistence, 2026-09-24 → 2026-09-25)

| # | Decision | Reason |
| --- | --- | --- |
| D23 | Data contract ([phase_2b_data_contract.md](docs/data_sources/phase_2b_data_contract.md)): regular-market data only; statuses `traded` / `no_regular_market_trade` / `unknown`; source `Previous` → `reference_price`; `available_at` unknown (never retrieval time); documented quality flags only | The source cannot establish suspensions, a prior close, or historical availability; nothing is inferred. |
| D24 | Snapshot identity = source + full revision + content hash; one unique run per execution; `parser_version` on the run | Reloading identical content is recognisable and idempotent; retrieval time is not identity. |
| D25 | `daily_prices` holds raw observations only; never overwritten; conflicts become incidents; every row traces to file, line, and run | Raw is immutable and auditable; adjustments come later in separate tables. |
| D27 | Price-adjustment factors come from the IDX reference price (`reference_price / previous close`); DS-9 events only classify them; DS-7 supplies cash dividends for total return (amounts assumed gross); 18 market-wide anomaly dates are flagged, not repaired; unclassified factors are applied and flagged (Phase 2C, owner decisions 1–5, 2026-09-25) | The reference price is IDX's own adjustment and is more complete than any public event source; see docs/data_sources/phase_2c_corporate_actions_design.md. |
| D26 | Real loads need `--execute` plus the exact full manifest revision; post-load state is checked by the read-only `verify_load` command; tests that write use a throwaway database | Prevents accidental writes and keeps the development database's evidence (and sequences) untouched. |

Proposed in the requirements doc but **not yet adopted**: the per-field
source-precedence rule (§21), the total-return convention — gross dividends
reinvested at the ex-date close, a modelling assumption matching MSCI's
published method (§24) — and the rights-issue methodology (§25).

---

## 6. Deliberately NOT done

* `daily_prices` stays raw. Adjusted and total-return series are derived
  (Phase 2C); the security universe, delistings, and ticker history are not
  handled yet.
* No network data client and no scraper; the only provider reads a local, git-ignored file snapshot.
* No ML, no NLP models, no feature engineering.
* No FastAPI application object or routes.
* No Celery app or worker tasks.
* No CI configuration.

---

## 7. Open decisions

Tracked in detail in [PROJECT_PLAN.md](PROJECT_PLAN.md) → *Open decisions*.
The blocking one is **data sourcing (Q2)**: no market-data, fundamental, or news
provider has been chosen, and none may be added before its licence terms,
redistribution rules, and rate limits are reviewed. For market data, the
requirements, provider evidence, and validation gathered on 2026-09-24 are in
[docs/data_sources/market_data_requirements.md](docs/data_sources/market_data_requirements.md).
Evidence shows no single candidate documents every mandatory field, so a
multi-source setup is necessary (doc §31). Written provider confirmations,
source selection, and the data contract are still open.

CI (Q6) is also open but blocks nothing; tests, lint, and type checks run
locally.

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
