# stock-ai

Quantitative stock intelligence and decision-support system for Indonesian equities.

The system combines fundamental, valuation, technical, news, event, and risk
analysis into an **explainable** research assistant. It is explicitly *not* a
black-box price predictor — see [CLAUDE.md](CLAUDE.md) for the full philosophy
and [PROJECT_PLAN.md](PROJECT_PLAN.md) for the roadmap.

> **Status: Phase 1 (environment & services) complete. 48 tests pass (38 at the end of Phase 0, 43 at the end of Phase 1).**
> PostgreSQL 17 and Redis 7 run in Docker and are reachable from the app.
> **Next: Phase 2 (market data). Not started.** $0 development mode:
> production data is BLOCKED (no production provider selected), development
> data is UNBLOCKED, and implementation is ready to start using public
> development sources. Requirements, provider research, validation, and the
> development source map are in [docs/data_sources/market_data_requirements.md](docs/data_sources/market_data_requirements.md).
> No data ingestion, valuation, technical, ML, backtesting, or trading logic
> exists yet. Git state is recorded in [CONTEXT.md](CONTEXT.md).

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
**skipped** (reason shown in the summary) when those services are down:

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

There are **no migrations yet**. The schema (CLAUDE.md §22) is designed
incrementally from Phase 2 onward, so `--autogenerate` currently produces an
empty migration — that is expected.

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

Implementation code so far: `backend/config.py` (environment-driven
settings), `backend/database.py` (engine, session factory, connectivity
check), and `data/ingestion/provider.py` (provider-neutral market-data
interface — no providers implemented). Every other package contains only a
docstring stating its responsibility.

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
