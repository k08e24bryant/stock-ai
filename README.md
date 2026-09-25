# stock-ai

Quantitative stock intelligence and decision-support system for Indonesian equities.

The system combines fundamental, valuation, technical, news, event, and risk
analysis into an **explainable** research assistant. It is explicitly *not* a
black-box price predictor — see [CLAUDE.md](CLAUDE.md) for the full philosophy
and [PROJECT_PLAN.md](PROJECT_PLAN.md) for the roadmap.

> **Status: Phase 2D (market indices, observed trading calendar) implemented,
> pending review.** 195 tests pass. Phase 2C (corporate actions, dividends,
> adjusted prices) is committed. The development database holds the Pholenk snapshot
> `9bb3b26`: 1,289,820 raw daily prices for 983 securities, 2020-01-02 →
> 2026-05-29, loaded and verified on 2026-09-25.
> PostgreSQL 17 and Redis 7 run in Docker and are reachable from the app.
> **Phase 2 (market data) in progress.** $0 development mode: production data
> is BLOCKED (no production provider selected), and development data is
> UNBLOCKED. Requirements, provider research, validation, and the development
> source map are in [docs/data_sources/market_data_requirements.md](docs/data_sources/market_data_requirements.md).
> Raw prices stay raw. Split-, rights-, and bonus-adjusted and total-return
> series are derived from IDX reference prices plus development
> corporate-action and dividend sources (Phase 2C). There is no valuation,
> technical, ML, backtesting, or trading logic yet. Git state is
> recorded in [CONTEXT.md](CONTEXT.md).

---

## Requirements

| Tool | Version used here | Required |
| --- | --- | --- |
| Python | 3.13.15 | 3.13.x |
| Git | 2.55.0 | any recent |
| Docker + Compose v2 | 29.8.0 / v5.5.1 | needed for PostgreSQL/Redis |
| Node.js / npm | 24.21.0 / 11.19.0 | only from Phase 12 (dashboard) |

Python 3.14 is also present on this machine but is **not** used: parts of the
planned ML stack (XGBoost, LightGBM, PyTorch) do not yet ship reliable 3.14
wheels. Pin to 3.13 until that changes.

---

## Setup

```bash
git clone <repo-url> stock-ai
cd stock-ai

# 1. Create the virtual environment (Python 3.13)
py -3.13 -m venv .venv

# 2. Activate it
.venv\Scripts\Activate.ps1      # PowerShell
# source .venv/Scripts/activate # Git Bash
# .venv\Scripts\activate.bat    # cmd.exe

# 3. Install the project in editable mode with dev tooling
python -m pip install -e ".[dev]"

# 4. Create your local environment file
cp .env.example .env            # then edit POSTGRES_PASSWORD
```

`.env` is git-ignored and must never be committed.

### Optional dependency groups

Declared in `pyproject.toml` but **not installed yet**. Install each when its
phase begins:

```bash
python -m pip install -e ".[data]"     # pandas, numpy, scipy      (Phase 2+)
python -m pip install -e ".[api]"      # fastapi, uvicorn          (backend service)
python -m pip install -e ".[workers]"  # celery, redis             (background jobs)
python -m pip install -e ".[ml]"       # scikit-learn, xgboost, lightgbm (Phase 9)
```

---

## Starting PostgreSQL and Redis

Only stateful infrastructure runs in Docker. Application code, tests, and
research run on the host (CLAUDE.md §24).

```bash
docker compose up -d      # start PostgreSQL 17 + Redis 7
docker compose ps         # both should report "healthy"
docker compose logs -f    # follow logs
docker compose down       # stop, keeping data in named volumes
docker compose down -v    # stop and DELETE all local data
```

Connection check:

```bash
docker compose exec postgres psql -U stockai -d stockai -c "select version();"
docker compose exec redis redis-cli ping     # -> PONG
```

`POSTGRES_PASSWORD` has no default in `docker-compose.yml`; Compose refuses to
start until it is set in `.env`.

---

## Running tests

```bash
pytest                 # full suite
pytest -q              # quiet
pytest -x -vv          # stop at first failure, verbose
```

Tests marked `integration` talk to the local PostgreSQL and Redis and are
**skipped** (reason shown in the summary) when those services are down.
Integration tests that write data never use the development database, which
holds the loaded snapshot. They run in a throwaway database that the
`migrated_database` fixture (`tests/conftest.py`) creates, migrates with
Alembic, and drops. This needs a PostgreSQL role allowed to create databases;
the local `stockai` role is.

```bash
pytest -m integration        # only the live-service tests
pytest -m "not integration"  # no database or network needed
```

---

## Development commands

```bash
ruff check .           # lint
ruff check . --fix     # lint + autofix
ruff format .          # format
mypy .                 # type check (strict)
pytest                 # tests
```

### Database migrations

Alembic reads its URL from `backend.config.Settings`, not from `alembic.ini`,
so credentials stay in `.env`.

```bash
alembic current                              # applied revision
alembic revision --autogenerate -m "message" # draft a migration -- ALWAYS review it
alembic upgrade head                         # apply
alembic downgrade -1                         # roll back one revision
```

Three migrations exist:

* `1c1d7048b74f`: the Phase 2B market-data schema (see
  [docs/data_sources/phase_2b_schema_design.md](docs/data_sources/phase_2b_schema_design.md));
* `6117977fb001`: Phase 2D index values and the `observed_trading_days` view
  (see [docs/data_sources/phase_2d_indices_design.md](docs/data_sources/phase_2d_indices_design.md));
* `55a78b2c9066`: Phase 2C corporate actions, dividends, and adjustment
  factors (see [docs/data_sources/phase_2c_corporate_actions_design.md](docs/data_sources/phase_2c_corporate_actions_design.md)).

Tests never migrate the development database; apply migrations
deliberately with `alembic upgrade head`.
`alembic check` should report no new upgrade operations.

---

## Project layout

```text
backend/        FastAPI app: api/ models/ schemas/ services/
data/           ingestion/ cleaning/ validation/ features/
ml/             sentiment/ classification/ prediction/ training/
valuation/      historical multiples, peers, earnings-based, DCF
event_engine/   event taxonomy, exposure mapping, knowledge graph, event studies
backtesting/    engine/ strategies/ metrics/
database/       migrations/ (Alembic)  schemas/ (reference docs)
workers/        background/scheduled jobs
dashboard/      Next.js frontend (Phase 12 — empty)
docs/           project documentation (data_sources/: market-data requirements and provider research)
tests/          pytest suite
```

Implementation code so far:

* `backend/config.py`: environment-driven settings.
* `backend/database.py`: engine, session factory, connectivity check.
* `backend/models/`: the Phase 2B market-data tables.
* `data/ingestion/provider.py`: the provider-neutral market-data interface.
* `data/ingestion/pholenk.py`: the development provider for the
  Pholenk/IDX-Dataset snapshot.
* Snapshot loading: `data/ingestion/snapshot.py`, `loader.py`,
  `pholenk_snapshot.py`, and the `load_snapshot.py` CLI.
* `data/validation/daily_prices.py`: validation and the quality report.
* `data/validation/verify_load.py`: read-only post-load verification.
* Phase 2C: `backend/models/corporate_actions.py`,
  `data/ingestion/records.py` (record-snapshot loader),
  `data/ingestion/idx_bei_actions.py` and `data/ingestion/idx_dividends.py`
  (source adapters), `data/features/adjustment_factors.py`, and
  `data/features/adjusted_prices.py`.
* Phase 2D: `backend/models/indices.py`, `data/ingestion/pholenk_indices.py`,
  and `data/features/index_series.py` (IHSG and other benchmarks).

Every other package contains only a docstring stating its responsibility.

### Development market data (Pholenk snapshot)

The development provider reads a local snapshot that is **not** committed
(`data/raw/` is git-ignored). Expected layout:

```text
data/raw/pholenk/IDX-Dataset-<short-revision>/
├── manifest.json            # source_id, revision, archive_sha256, retrieved_at
└── dataset/stocks/csv/*.csv # from https://github.com/Pholenk/IDX-Dataset
```

Quality report for a snapshot:

```bash
python -m data.ingestion.pholenk data/raw/pholenk/IDX-Dataset-9bb3b26
```

Load it into PostgreSQL. The default is a dry run with no database access;
`--execute` needs the **full** 40-hex `revision` from `manifest.json`:

```bash
python -m data.ingestion.load_snapshot pholenk data/raw/pholenk/IDX-Dataset-9bb3b26 --expect-stock-files 983
python -m data.ingestion.load_snapshot pholenk data/raw/pholenk/IDX-Dataset-9bb3b26 --expect-stock-files 983     --execute --confirm-revision 9bb3b26bd28ab46bc2f3e74a7c03805ce053301b
```

Verify what is stored. This is read-only; `--deep` compares every row:

```bash
python -m data.validation.verify_load pholenk data/raw/pholenk/IDX-Dataset-9bb3b26 --expect-stock-files 983 --deep
```

See [docs/data_sources/phase_2b_ingestion_design.md](docs/data_sources/phase_2b_ingestion_design.md)
for the design and the recorded load and verification results.

Corporate actions, dividends, and adjustment factors (Phase 2C; the
snapshots live under `data/raw/`, each with a `manifest.json`):

```bash
python -m data.ingestion.load_snapshot idx-bei-actions data/raw/nichsedge-idx-bei/idx-bei-34903ce            # dry run
python -m data.ingestion.load_snapshot idx-dividends data/raw/dimasirginsyh-idx-dividends/indonesia-stock-dividends-92115bf
python -m data.features.adjustment_factors            # dry run; --execute writes, --verify compares
python -m data.ingestion.load_snapshot pholenk-indices data/raw/pholenk/IDX-Dataset-9bb3b26   # 56 index files
```

See [docs/data_sources/phase_2c_corporate_actions_design.md](docs/data_sources/phase_2c_corporate_actions_design.md) for the method, the series to use
for returns, simulation, and display, and the recorded results.

Development data only; see `docs/data_sources/market_data_requirements.md` §36.

---

## Known environment gaps

These block later phases and need a decision — see PROJECT_PLAN.md
*Open decisions*.

1. **Node.js is not on `PATH`.** It exists at `C:\Program Files\nodejs`
   (v24.21.0) but is not resolvable from the shell. Only matters from Phase 12.
2. **No data source has been selected.** No market-data, fundamental, or news
   provider is configured, and none may be added before its licence terms,
   redistribution rules, and rate limits are reviewed (CLAUDE.md Rules 7–8).

---

## License

MIT.
