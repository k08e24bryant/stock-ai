# PROJECT_PLAN.md

Roadmap for the Stock Intelligence & Quantitative Decision-Support System.

**Last updated:** 2026-09-24
Phase definitions follow [CLAUDE.md](CLAUDE.md) §26. Current repository state is
recorded in [CONTEXT.md](CONTEXT.md).

Build order is a hard rule, not a preference: **no machine learning before a
deterministic baseline exists** (CLAUDE.md Rule 10), and **no phase is complete
until its leakage and bias guards are tested**.

---

## Status overview

| Phase | Name | Status |
| --- | --- | --- |
| 0 | Project initialization | ✅ Complete |
| 1 | Environment & services running | ✅ Complete |
| 2 | Market data | 🚧 In progress — Phase 2A (Pholenk development ingestion) ✅ complete; production data **BLOCKED** (Q2); development data **UNBLOCKED** |
| 3 | Fundamental data | ⬜ Not started |
| 4 | Valuation engine | ⬜ Not started |
| 5 | Technical analysis | ⬜ Not started |
| 6 | News intelligence | ⬜ Not started |
| 7 | Event intelligence | ⬜ Not started |
| 8 | Historical event study | ⬜ Not started |
| 9 | Machine learning | ⬜ Not started |
| 10 | Risk engine | ⬜ Not started |
| 11 | Backtesting | ⬜ Not started |
| 12 | Dashboard | ⬜ Not started |
| 13 | Paper trading | ⬜ Not started |

---

## Phase 0 — Project initialization ✅

Completed 2026-09-24. Everything below was actually created and verified.

### Delivered

* **Git** repository initialized; default branch renamed `master` to `main`.
  No commits existed when Phase 0 finished; the maintainer then made the
  initial commit `dff5641` and pushed it to `origin/main`.
* **Python 3.13.15 virtual environment** at `.venv`.
* **`pyproject.toml`** — project metadata, a deliberately small runtime
  dependency set, later-phase dependencies as optional extras, and
  configuration for `pytest`, `ruff` (line length 100, `E/F/I/UP/B/SIM`), and
  `mypy` (strict).
* **Package scaffold** per CLAUDE.md §25 — `backend/`, `data/`, `ml/`,
  `valuation/`, `event_engine/`, `backtesting/`, `database/`, `workers/`,
  `dashboard/`, `tests/`. Every Python package has a docstring stating its
  responsibility; none contains logic.
* **`backend/config.py`** — Pydantic `Settings` reading app, PostgreSQL, and
  Redis configuration from the environment, with `database_url` and `redis_url`
  helpers and a cached `get_settings()`.
* **`.gitignore`** — Python, Node/Next.js, Docker, VS Code, OS noise, secrets,
  caches, and generated data/model/backtest artifacts.
* **`.env.example`** — every setting `Settings` reads, and nothing else. A test
  enforces that the two stay in sync.
* **`docker-compose.yml`** — PostgreSQL 17 + Redis 7 with healthchecks, named
  volumes, and a `POSTGRES_PASSWORD` that Compose refuses to default.
* **Alembic scaffold** — `alembic.ini` with timestamped revision filenames and
  **no** hardcoded URL; `database/migrations/env.py` injects the URL from
  `backend.config`; `backend/models/__init__.py` exports a `DeclarativeBase`
  and an empty `MetaData` with a deterministic constraint naming convention.
  **Zero migrations, zero tables** — schema design is Phase 2+.
* **`database/schemas/README.md`** — states that migrations are authoritative
  and this directory holds reference documentation only.
* **Test suite** — `tests/conftest.py` and `tests/test_project_setup.py`:
  38 tests covering Python version, importability and documentation of all 22
  packages, presence of foundation files, `.env` ignore rules,
  `.env.example` vs `Settings` parity, settings defaults and env overrides, and
  an assertion that the ORM metadata is still empty (a tripwire that must be
  updated deliberately in Phase 2).
* **`README.md`**, **`CONTEXT.md`**, and this file.

### Verification run

Results as recorded when Phase 0 finished. Current results are under Phase 1.

| Command | Result at Phase 0 |
| --- | --- |
| `pytest -q` | **38 passed** |
| `ruff check .` | not recorded |
| `ruff format --check .` | not recorded |
| `mypy .` | not recorded |
| `alembic current` | **not run**: needs a running PostgreSQL |
| `docker compose config` | **not run**: Docker was not installed yet (installed in Phase 1) |

### Not done in Phase 0 (by design)

No database schema, no data ingestion, no analytical code, no ML, no FastAPI
app, no Celery app, no frontend, no CI.

---

## Phase 1 — Environment and services ✅

**Goal:** the declared infrastructure actually runs and is reachable from the
application. Verified 2026-09-24.

* [x] Install Docker Desktop — Docker 29.8.0, Compose v5.5.1.
* [x] `docker compose config` validates.
* [x] `docker compose up -d` — PostgreSQL 17.11 and Redis 7.4.11 report `healthy`.
* [x] Connectivity test from Python using `Settings.database_url` and `redis_url`
      (`tests/test_database.py`, marker `integration`; skipped with a reason
      when the services are down).
* [x] `alembic upgrade head` succeeds against an empty database; `alembic check`
      reports no pending operations.

Whether to add CI is **not** a Phase 1 exit criterion. It remains open as Q6,
does not block Phase 2, and checks run locally in the meantime.

### Delivered

* `backend/database.py` — cached engine (`pool_pre_ping`, 5 s connect timeout
  instead of psycopg's 130 s default), session factory, `ping_database()`.
  No models, no tables.
* **Fix:** `Settings.database_url` now percent-encodes credentials via
  `sqlalchemy.engine.URL.create`. Previously a password containing `@`, `/`,
  or `:` silently corrupted the host and database name.
* **Fix:** `database/migrations/env.py` escapes `%` before handing the URL to
  Alembic's configparser, which otherwise rejects any percent-encoded password.
* `integration` pytest marker registered in `pyproject.toml`.
* Committed as `41f70b5` ("phase 1 completed") and pushed to `origin/main`.

### Verification run

| Command | Result |
| --- | --- |
| `pytest -q` | **43 passed** (38 from Phase 0 + 5 new in `tests/test_database.py`) |
| `pytest` with services unreachable | 3 `integration` tests skipped with a reason; the rest pass |
| `ruff check .` | All checks passed |
| `ruff format --check .` | All files formatted |
| `mypy .` | No issues (strict) |
| `docker compose config` | Valid |
| `alembic upgrade head` / `alembic check` | Succeed; no pending operations |

---

## Phase 2 — Market data 🚧

**Goal:** a reproducible, corporate-action-correct daily OHLCV history.

Phase 2A (development ingestion from Pholenk/IDX-Dataset) and Phase 2B
(PostgreSQL persistence of raw development daily prices) are complete. No
network client, scheduled job, corporate-action layer, or adjusted price
series exists yet.

| Track | Status |
| --- | --- |
| Production data | **BLOCKED** — Q2 unresolved; readiness gate in requirements doc §32 |
| Development data | **UNBLOCKED** — $0 development mode; public sources selected (requirements doc §36) |
| Implementation | **IN PROGRESS**: Phase 2A and Phase 2B complete on development data |

Production provider selection remains a later, separate gate. Development
data does not satisfy production requirements and must not be treated as if
it did.

### Q2 — market-data source (blocking)

Requirements and provider evidence are recorded in
[docs/data_sources/market_data_requirements.md](docs/data_sources/market_data_requirements.md).

* [x] Requirements finalized (2026-09-24): MUST / SHOULD / NICE, multi-source
      rules, data-integrity and return-methodology requirements.
* [x] Owner decisions recorded: budget TBD after comparison (not pass/fail);
      private use now, rented cloud/VPS possibly later; history from
      2015-01-01 (≈ 2005 SHOULD); store price return **and** total return;
      multiple sources allowed.
* [x] Provider research completed and evidenced (2026-09-24): IDX Data
      Services, ICE, LSEG, Bloomberg, FactSet, S&P Global, EODHD, Twelve Data,
      Financial Modeling Prep, Yahoo Finance, Sectors, Invezgo, GoAPI, OHLC.dev.
      **No provider selected, ranked, or recommended.**
* [x] Provider validation, round 2 (2026-09-24) — **partially completed**:
      licensing, coverage, corporate-action fields, market data, automation,
      and cost validated per provider **from public documentation only**;
      source matrix, field-level matrix, and readiness gate recorded
      (requirements doc §28–§32). Nothing requiring a provider account or
      written confirmation could be validated.
* [x] Proposed (not yet adopted): per-field source-precedence rule (§21),
      provenance requirements (§22), disagreement handling (§23),
      total-return convention — reinvest gross dividends at the ex-date close,
      a documented modelling assumption (§24), rights-issue methodology based
      on the theoretical ex-rights price (§25).
* [x] IDX trading-rule sources identified (§26). Verified: lot size 100 from
      2014-01-06; T+2 settlement from 2018-11-26. Tick sizes from 2016 onward, price
      limits, sessions, and calendars are secondary or unverified.
* [ ] **Written provider confirmations** — the UNCLEAR licence cells, IDX
      delisted/ticker/suspension coverage, EODHD price provenance, IHSG
      history, and storage after termination (requirements doc §33).
* [ ] **Source selection** — not made. A separate, explicit decision; no
      provider has been selected, ranked, or recommended.
* [ ] **Data contract** — not started: adopt the precedence rule, set
      per-field tolerances and tie-break orders, and decide the rights
      out-of-the-money and backtest treatment.
* [ ] Sample accuracy audit of the selected source(s) against IDX primary
      disclosures (requirement M13).

**Production readiness: BLOCKED** (requirements doc §32). OHLCV,
delisted history, corporate actions, dividends, rights, security IDs, ticker
history, suspensions, IHSG, licensing, permanent storage, and cloud storage
are blocked. Automation, disagreement handling, and trading rules are
partially ready; the provenance design is ready.

### $0 development mode (decided 2026-09-24)

* [x] Public development sources searched, downloaded, and measured;
      development source map recorded (requirements doc §36).
* [x] Core development OHLCV source: Pholenk/IDX-Dataset (ODbL; raw
      IDX-format; 983 tickers; 2020-01-02 → 2026-05-29).
* [x] Supplemental development sources: Dataset-Saham-IDX and its fork
      (cross-check), faisalburhanudin/idx (2000–2019, Yahoo split-adjusted),
      IHSG (`COMPOSITE` + daily-IHSG), dividends (indonesia-stock-dividends),
      corporate-action events and company profiles (nichsedge/idx-bei),
      metadata (Dataset-Saham-IDX list, kjhq CC0).
* [x] Minimal provider-neutral interface `MarketDataProvider` with provenance
      on every record (`data/ingestion/provider.py`); no provider implemented.
* [x] Development provider for the core source — Phase 2A below.
* [x] Persistence of raw daily prices on development data (Phase 2B below).
* [ ] Next: the remaining tables and jobs below (corporate actions, adjusted
      series, universe), still on development data.

Known development-data gaps: raw IDX-format history starts 2019-07/2020-01
(not 2015); opens are mostly missing before 2025; no ticker history, ISINs,
suspension dates, or rights terms; a 9-date close disagreement in 2024 between
the two IDX-format sources (requirements doc §36.5).

### Phase 2A — Pholenk development ingestion — STATUS: COMPLETE (2026-09-24)

`Pholenk raw files → parser → normalization → validation → canonical records`

* [x] Snapshot inspected before coding (revision `9bb3b26`, 983 files, one
      header, UTF-8 BOM, newest date first, `YYYY-MM-DD` dates, integer share
      volume). Stored git-ignored at `data/raw/pholenk/IDX-Dataset-9bb3b26/`
      with `manifest.json` (URL, revision, archive SHA-256, retrieval time).
* [x] `PholenkProvider` implements `MarketDataProvider`
      (`data/ingestion/pholenk.py`): `list_securities`, `get_daily_prices`;
      dividends, corporate actions, and index history raise
      `NotProvidedError`.
* [x] Raw layer kept separate: `PholenkRawRow` holds untouched source
      strings; source files are never modified.
* [x] Normalization: `Open = 0` → `open = None` (never replaced by another
      price); zero-volume rows with `High = Low = 0` →
      `NO_TRADE_OR_SUSPENDED` (suspension is not distinguishable), kept, with
      high/low `None`; prices raw (`is_adjusted = False`); no adjustments.
* [x] Validation (`data/validation/daily_prices.py`): hard-invalid vs
      expected source condition; hard-invalid records make
      `get_daily_prices` fail loudly.
* [x] Duplicates on (security, date): exact duplicates collapse to the
      lowest source line (logged); conflicting duplicates raise.
* [x] Development-only identity `dev:pholenk-idx-dataset:<KEY>` — not an
      ISIN; does not survive ticker changes.
* [x] Provenance on every record: source, retrieval time, file path + file
      SHA-256 + line, licence, parser version, source revision, run ID.
* [x] Quality report computed from input:
      `python -m data.ingestion.pholenk data/raw/pholenk/IDX-Dataset-9bb3b26`.
      On the snapshot: 1,289,820 rows; 983 securities; 2020-01-02 →
      2026-05-29; 0 duplicates; 1,045,981 missing opens (81.10%); 156,317
      zero-volume rows; 0 invalid OHLC; 0 negative volume. The strict path
      returns all 1,289,820 rows.
* [x] No database changes: canonical records are in-memory; persistence is
      the next step. `alembic check` reports no pending operations.

Not done in Phase 2A (by design): other datasets, cross-source
reconciliation, corporate-action/dividend handling, price adjustment,
persistence, scheduling.

### Phase 2B — development persistence — STATUS: COMPLETE (2026-09-25)

`snapshot → inventory + identity → loader (dry run / confirmed load) → PostgreSQL → read-only verification`

* [x] Data contract
      ([docs/data_sources/phase_2b_data_contract.md](docs/data_sources/phase_2b_data_contract.md)):
      regular-market semantics, statuses `traded` /
      `no_regular_market_trade` / `unknown`, `reference_price`,
      unknown `available_at`, quality flags, snapshot vs run identity.
* [x] 2B.1–2B.2 Schema
      ([phase_2b_schema_design.md](docs/data_sources/phase_2b_schema_design.md)):
      8 tables, migration `1c1d7048b74f`. `daily_prices` is raw only, has
      CHECK-enforced semantics, and every foreign key is RESTRICT.
* [x] 2B.3A–B Snapshot loader
      ([phase_2b_ingestion_design.md](docs/data_sources/phase_2b_ingestion_design.md)):
      deterministic snapshot identity; streaming COPY into staging;
      idempotent, conflict-detecting, atomic load; the source advisory lock;
      a database-free dry run by default; real loads need the full revision.
* [x] 2B.3C Real-snapshot dry run: byte-identical, database-free, every
      expectation matched.
* [x] 2B.3D Real load (2026-09-25): 1,289,820 raw daily prices, 983
      securities, 1,043 source files, 0 rejected, 0 conflicts. Verified
      against the raw CSV row by row.
* [x] 2B.4 Closeout: read-only verification command
      `python -m data.validation.verify_load` (47/47 checks, 51/51 with
      `--deep`); integration tests that write moved to a throwaway database;
      contract text aligned with the schema.

Not done in Phase 2B (by design): corporate actions, adjusted prices, total
return, stable production IDs, ticker/name history, authoritative suspensions
or trading calendar, backtesting (contract, "Explicit Non-Goals").

### Implementation (tables and jobs — start on development data; production source later)

* [ ] `companies` table: identifiers, listing and delisting dates, ticker
      history, sector classification.
* [ ] `prices` table: OHLCV plus an explicit adjusted/unadjusted distinction.
* [ ] `corporate_actions` table: splits, reverse splits, rights issues,
      dividends, bonus shares.
* [ ] Ingestion job recording the retrieval timestamp of every fetch.
* [ ] Every stored record keeps its source identity and retrieval time;
      cross-source disagreements are logged, never silently merged.
* [ ] Validation: gaps, duplicates, non-positive prices, zero-volume runs,
      suspensions, implausible jumps not explained by a corporate action.
* [ ] Point-in-time universe construction that includes delisted companies
      (CLAUDE.md §16).
* [ ] Document which price series is used for returns, for simulation, and for
      display (CLAUDE.md §17).

---

## Phase 3 — Fundamental data ⬜

* [ ] Choose and document a fundamental-data source. *Blocking.*
* [ ] `financials` and `financial_publications` — every statement carries its
      **publication timestamp**, so features can never read a report before it
      was public.
* [ ] Restatement handling: keep the as-reported figures, version revisions.
* [ ] Derived metrics (profitability, growth, health, cash flow, dividend) kept
      strictly separate from raw statement data.
* [ ] Leakage test: for a sample of dates, assert no feature uses a statement
      published after that date.

---

## Phase 4 — Valuation engine ⬜

* [ ] Historical multiples (PER, PBV, EV/EBITDA, FCF yield) with percentile
      distributions.
* [ ] Peer valuation within industry groups.
* [ ] Earnings-based valuation: expected EPS times a justified multiple.
* [ ] DCF with explicit revenue, margin, tax, capex, working-capital, WACC, and
      terminal-growth assumptions.
* [ ] Bear / Base / Bull fair-value ranges, **with stored assumptions** —
      never a single point estimate (CLAUDE.md §5.5).

---

## Phase 5 — Technical analysis ⬜

* [ ] Trend, momentum, volatility, volume, and relative-strength indicators
      (CLAUDE.md §6).
* [ ] Every indicator defined with explicit timestamp semantics and tested
      against a hand-computed fixture.
* [ ] Relative strength versus sector and versus IHSG.

---

## Phase 6 — News intelligence ⬜

* [ ] **Choose legally usable news sources** — API terms, RSS, robots.txt,
      copyright, rate limits. No scraping that violates site restrictions.
      *Blocking.*
* [ ] Ingestion preserving the original publication timestamp.
* [ ] Deduplication of syndicated and rewritten articles.
* [ ] Classify availability: pre-open, intraday, post-close.
* [ ] Baseline lexicon sentiment **before** any transformer model.
* [ ] Entity extraction; event classification.

---

## Phase 7 — Event intelligence ⬜

* [ ] Event taxonomy (CLAUDE.md §8).
* [ ] Company and sector exposure stored **as data**, not hardcoded in logic.
* [ ] Economic-mechanism chain: policy, mechanism, commodity, sector, company.
* [ ] Event knowledge graph.

---

## Phase 8 — Historical event study ⬜

* [ ] Event windows; 1/3/5/10-day returns, max drawdown, max favorable
      excursion.
* [ ] Abnormal return versus IHSG and versus sector index.
* [ ] Matched non-event control periods.
* [ ] Report dispersion and sample size, not just a mean — a handful of
      observations is not evidence.

---

## Phase 9 — Machine learning ⬜

Entered only once Phases 2-8 provide a non-ML baseline to beat.

* [ ] Feature dataset with documented timestamp semantics per feature.
* [ ] Baselines in order: logistic regression, random forest, XGBoost,
      LightGBM.
* [ ] Time-based split, walk-forward and expanding-window validation.
* [ ] Probability calibration; report Brier score and reliability curves.
* [ ] Benchmark against the deterministic baseline and against buy-and-hold.

---

## Phase 10 — Risk engine ⬜

* [ ] Position sizing, ATR-based stops, risk/reward.
* [ ] Portfolio, sector, and correlation exposure limits.
* [ ] Liquidity constraints; expected loss and drawdown estimates.

---

## Phase 11 — Backtesting ⬜

* [ ] Event-driven engine with fees, tax, slippage, spread, and liquidity caps.
* [ ] Corporate actions and suspensions handled correctly.
* [ ] Metrics per CLAUDE.md §20, always against a benchmark.
* [ ] Every backtest writes its assumptions and a reproducible config.

---

## Phase 12 — Dashboard ⬜

* [ ] Next.js + TypeScript frontend answering the twelve questions in
      CLAUDE.md §32.
* [ ] Every displayed number traceable to its source and assumptions.

---

## Phase 13 — Paper trading ⬜

Only after backtesting and walk-forward validation have passed. Autonomous
real-money trading is explicitly **not** a goal of this roadmap.

---

## Open decisions

| # | Decision needed | Blocks | Notes |
| --- | --- | --- | --- |
| ~~Q1~~ | ~~Install Docker Desktop, or run PostgreSQL/Redis natively?~~ | — | **Resolved:** Docker Desktop installed; compose stack verified. |
| Q2 | Production market-data source for IDX OHLCV and corporate actions | Phase 2 production data | Requirements, research, and validation recorded (2026-09-24) in `docs/data_sources/market_data_requirements.md`; production gate BLOCKED. Development proceeds on public sources ($0 mode, doc §36). Open: written provider confirmations, selection, data contract. |
| Q3 | Fundamental-data source, including **publication timestamps** | Phase 3 | Statement dates alone are insufficient — without publication time, leakage is unavoidable. |
| Q4 | News sources and their terms of use | Phase 6 | RSS/API only unless a source explicitly permits more. |
| Q5 | Benchmark and sector index definitions (IHSG, sector indices) | Phase 8 | Needed for abnormal-return calculation. |
| Q6 | CI provider, and whether to run CI at all | Nothing | Not a Phase 1 exit criterion and not a Phase 2 blocker. Local-first is fine for now. |
| Q7 | Where `.env` secrets live once anything is deployed | later | Out of scope while local-only. |

Q2 is the real gate. Everything downstream of Phase 2 depends on it, and it is
a licensing question before it is a technical one.
