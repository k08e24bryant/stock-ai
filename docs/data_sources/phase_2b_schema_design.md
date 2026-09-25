# Phase 2B Database Schema Design

## Status

**IMPLEMENTED** in Phase 2B.2 (commit `94dc6eb`, migration `1c1d7048b74f`).
The Pholenk development snapshot was loaded in Phase 2B.3D (2026-09-25). Design
date: 2026-09-24. Target stack (verified): PostgreSQL 17.11, SQLAlchemy 2.0.54,
Alembic 1.20.0, psycopg 3.3.6.

Governing documents: [Phase 2B Data Contract](phase_2b_data_contract.md)
(approved) and [market_data_requirements.md](market_data_requirements.md).
Where this design refines the contract, the refinement is listed in
[Contract alignment](#contract-alignment) and takes effect only when this
design is approved.

## Design Goals

1. Raw source data is immutable; raw files stay outside PostgreSQL.
2. Canonical data is normalized and follows the contract's semantics.
3. Every canonical observation traces to snapshot → file → line.
4. Snapshot identity (what) is separate from ingestion-run identity (when/how).
5. Ticker is never a permanent security identity.
6. Missing Open stays `NULL`; zero-volume rows are preserved.
7. Volume/value/frequency are explicitly regular-market.
8. `reference_price` is not treated as previous close.
9. Raw prices are unadjusted; adjustments live elsewhere and never overwrite.
10. No historical `available_at` is fabricated.
11. Re-loading a snapshot is idempotent.
12. Conflicting observations are never silently overwritten.
13. Efficient for millions of daily rows, with the simplest structure that
    satisfies 1–12.

## Entity Overview

```text
data_sources ──< source_snapshots ──< source_files
                        │                   │
                        └──< ingestion_runs │
                                  │         │
securities ──< security_source_keys >── data_sources
    │
    └──< daily_prices >── source_files      (provenance: file + line)
             │     └───── ingestion_runs    (run that inserted the row)
             └─────────── data_sources      (which source observed it)

data_quality_incidents >── ingestion_runs (required)
                       >── securities, source_files (optional)
```

`A ──< B` means one A has many B. Eight tables in total; no partitioning, no
enum types, no triggers.

## Table-by-Table Design

Conventions: constraint names follow the project naming convention in
`backend/models/__init__.py`; all CHECK constraints get explicit names;
timestamps are `TIMESTAMPTZ` stored in UTC; identifiers of external things
(`source_id`, hashes, paths) are `TEXT`.

### `data_sources`

**Purpose:** the logical external source (e.g. `pholenk-idx-dataset`). Kept —
tiny, and it gives a foreign-key target for every `source_id`, preventing
typo-level provenance errors. Licence text is **not** stored here: licences are
read per snapshot and can change.

| Column | Type | Null | Notes |
| --- | --- | --- | --- |
| `source_id` | TEXT | NOT NULL | **PK**. CHECK `source_id ~ '^[a-z0-9][a-z0-9-]*$'` |
| `source_name` | TEXT | NOT NULL | Human-readable name |
| `homepage_url` | TEXT | NULL | e.g. repository URL |
| `created_at` | TIMESTAMPTZ | NOT NULL | default `now()` |

Dropped from the proposal: `provider_type`, `active` (no current use),
`license_reference` (snapshot level).

### `source_snapshots`

**Purpose:** one immutable version of an external dataset.

| Column | Type | Null | Notes |
| --- | --- | --- | --- |
| `snapshot_id` | TEXT | NOT NULL | **PK**. Deterministic: `<source_id>:<source_revision>:<first 16 hex of content_sha256>` |
| `source_id` | TEXT | NOT NULL | FK → `data_sources` (RESTRICT) |
| `source_revision` | TEXT | NOT NULL | e.g. git commit SHA |
| `content_sha256` | TEXT | NOT NULL | SHA-256 over the sorted file inventory (`relative_path` + file SHA-256 of every loaded file). CHECK `~ '^[0-9a-f]{64}$'` |
| `archive_sha256` | TEXT | NULL | Integrity attribute of the downloaded archive, **not** identity. Same CHECK when not NULL |
| `source_url` | TEXT | NOT NULL | Where the snapshot was obtained |
| `retrieved_at` | TIMESTAMPTZ | NOT NULL | Retrieval time of the copy that registered the snapshot. Not identity |
| `licence_reference` | TEXT | NOT NULL | Licence and date read |
| `raw_storage_path` | TEXT | NOT NULL | Path **relative to the project data root** (e.g. `data/raw/pholenk/IDX-Dataset-9bb3b26`), never machine-specific |
| `file_count` | INTEGER | NOT NULL | CHECK `>= 0`; cross-check with `source_files` |
| `created_at` | TIMESTAMPTZ | NOT NULL | default `now()` |

- **UNIQUE** (`source_id`, `source_revision`, `content_sha256`) — the
  deterministic identity. `retrieved_at` and `archive_sha256` are excluded:
  identical content retrieved twice, or re-archived with different bytes, is
  the same snapshot.
- Same `source_id` + `source_revision` with a different `content_sha256` is a
  different snapshot and triggers a `snapshot_content_mismatch` incident.
- Indexes: PK and the UNIQUE constraint only.

### `source_files`

**Purpose:** metadata of each raw file in a snapshot. Raw bytes stay on disk.

| Column | Type | Null | Notes |
| --- | --- | --- | --- |
| `file_id` | BIGINT | NOT NULL | **PK**, `GENERATED ALWAYS AS IDENTITY` |
| `snapshot_id` | TEXT | NOT NULL | FK → `source_snapshots` (RESTRICT) |
| `relative_path` | TEXT | NOT NULL | e.g. `dataset/stocks/csv/BBCA.csv` |
| `sha256` | TEXT | NOT NULL | Hash of **the exact bytes parsed**. CHECK `~ '^[0-9a-f]{64}$'` |
| `row_count` | INTEGER | NOT NULL | Data rows (excluding header). CHECK `>= 0` |
| `source_key` | TEXT | NULL | Security key the file represents, when the layout is one-file-per-security (Pholenk: file stem). NULL for multi-security files |

- **UNIQUE** (`snapshot_id`, `relative_path`); this also serves lookups by
  snapshot.
- `source_key` belongs here because, for Pholenk, the file *is* the
  source-side identity evidence (e.g. `TRUE.csv` with ticker column `True`).
  The canonical mapping to a security lives in `security_source_keys`.

### `ingestion_runs`

**Purpose:** one execution of the loader.

| Column | Type | Null | Notes |
| --- | --- | --- | --- |
| `ingestion_run_id` | UUID | NOT NULL | **PK**; generated per execution (UUIDv4) — deliberately not deterministic |
| `snapshot_id` | TEXT | NOT NULL | FK → `source_snapshots` (RESTRICT) |
| `parser_version` | TEXT | NOT NULL | Version of **our** parsing/normalization code used by this run |
| `started_at` | TIMESTAMPTZ | NOT NULL | |
| `completed_at` | TIMESTAMPTZ | NULL | |
| `status` | TEXT | NOT NULL | CHECK IN (`running`, `succeeded`, `failed`) |
| `rows_seen` | BIGINT | NOT NULL | default 0, CHECK `>= 0` |
| `rows_inserted` | BIGINT | NOT NULL | default 0, CHECK `>= 0` |
| `rows_unchanged` | BIGINT | NOT NULL | default 0, CHECK `>= 0` — already present and identical |
| `rows_rejected` | BIGINT | NOT NULL | default 0, CHECK `>= 0` — hard-invalid, quarantined as incidents |
| `rows_conflicted` | BIGINT | NOT NULL | default 0, CHECK `>= 0` — differ from stored observation |
| `validation_summary` | JSONB | NULL | Quality-report output for the run |

- CHECK: (`status = 'running'`) = (`completed_at IS NULL`).
- CHECK: `completed_at IS NULL OR completed_at >= started_at`.
- "Rows accepted" in the contract = `rows_inserted + rows_unchanged`.
- Index: (`snapshot_id`).
- **Referenced by `daily_prices`?** Yes, as `ingestion_run_id` = the run that
  **inserted** the row (immutable). It is the only link from a row to the
  parser version that produced it; see [Contract alignment](#contract-alignment).

### `securities`

**Purpose:** internal security identity plus **current display metadata**.

| Column | Type | Null | Notes |
| --- | --- | --- | --- |
| `security_id` | BIGINT | NOT NULL | **PK**, `GENERATED ALWAYS AS IDENTITY`. Internal surrogate; never exposed as a market identifier |
| `ticker` | TEXT | NOT NULL | **Current display ticker only.** Not unique, not identity |
| `name` | TEXT | NULL | **Latest known name only** (as of the most recent snapshot) |
| `currency` | TEXT | NOT NULL | Listing currency; default `'IDR'`; CHECK `~ '^[A-Z]{3}$'` |
| `identity_kind` | TEXT | NOT NULL | CHECK IN (`development`). Makes the limitation explicit in data; extended by migration when a stable identifier scheme exists |
| `created_at` | TIMESTAMPTZ | NOT NULL | default `now()` |

- Index: (`ticker`) non-unique, for lookup.
- `ticker` and `name` are display metadata. History tables
  (`security_tickers`, `security_names`) are **deferred**: the development
  source has no ticker history, and name history is recoverable from the raw
  files when needed.
- `security_id` values are assigned in sorted source-key order at load, so a
  rebuild from the same snapshot reproduces them. Analyses must still refer to
  source keys, not raw surrogate numbers.

### `security_source_keys`

**Purpose:** maps each source's key to an internal security. Future stable
identifiers (ISIN, vendor, exchange) are added as new mappings, without
touching price rows.

| Column | Type | Null | Notes |
| --- | --- | --- | --- |
| `source_id` | TEXT | NOT NULL | FK → `data_sources` (RESTRICT) |
| `source_key` | TEXT | NOT NULL | Source's natural key (Pholenk: file key, e.g. `BBCA`, `TRUE`) |
| `security_id` | BIGINT | NOT NULL | FK → `securities` (RESTRICT) |
| `first_seen_snapshot_id` | TEXT | NOT NULL | FK → `source_snapshots` (RESTRICT) |
| `quality_flags` | TEXT[] | NOT NULL | default `'{}'`; CHECK `quality_flags <@ ARRAY['source_ticker_column_mismatch']::text[]` |
| `created_at` | TIMESTAMPTZ | NOT NULL | default `now()` |

- **PK** (`source_id`, `source_key`).
- Index: (`security_id`).
- The development identity string `dev:pholenk-idx-dataset:<KEY>` is
  `source_id` + `source_key`; it is **not** stored separately.

### `daily_prices`

**Purpose:** raw, unadjusted daily observations per source. Adjusted prices
are **not** stored here.

| Column | Type | Null | CHECK / notes |
| --- | --- | --- | --- |
| `security_id` | BIGINT | NOT NULL | FK → `securities` (RESTRICT) |
| `trading_date` | DATE | NOT NULL | Exchange-local (WIB) date of the observation |
| `source_id` | TEXT | NOT NULL | FK → `data_sources` (RESTRICT) |
| `open` | NUMERIC(20,4) | NULL | `open > 0`. NULL = source did not supply an open |
| `high` | NUMERIC(20,4) | NULL | `high > 0` |
| `low` | NUMERIC(20,4) | NULL | `low > 0` |
| `close` | NUMERIC(20,4) | NOT NULL | `close > 0` |
| `reference_price` | NUMERIC(20,4) | NULL | `reference_price > 0` |
| `volume` | BIGINT | NULL | `volume >= 0`; regular market, shares |
| `value` | NUMERIC(24,4) | NULL | `value >= 0`; regular market, IDR |
| `frequency` | BIGINT | NULL | `frequency >= 0`; regular market, number of trades |
| `trading_status` | TEXT | NOT NULL | IN (`traded`, `no_regular_market_trade`, `unknown`) |
| `quality_flags` | TEXT[] | NOT NULL | default `'{}'`; `quality_flags <@ ARRAY['non_regular_activity_present','unverified_trading_date']::text[]` |
| `file_id` | BIGINT | NOT NULL | FK → `source_files` (RESTRICT) |
| `source_line` | INTEGER | NOT NULL | `source_line >= 1` |
| `ingestion_run_id` | UUID | NOT NULL | FK → `ingestion_runs` (RESTRICT); run that inserted the row |

- **PK** (`security_id`, `trading_date`, `source_id`).
- Row-consistency CHECKs, which encode the contract's hard-invalid rules at the
  database level:
  - `ck_…_traded_shape`: `trading_status <> 'traded' OR (volume > 0 AND high
    IS NOT NULL AND low IS NOT NULL AND high >= low AND high >= close AND low
    <= close AND (open IS NULL OR (open >= low AND open <= high)))`.
  - `ck_…_no_regular_trade_shape`: `trading_status <> 'no_regular_market_trade'
    OR (volume = 0 AND high IS NULL AND low IS NULL AND open IS NULL)`.
- Indexes: the PK, plus (`trading_date`). See [Indexing](#indexing).

Proposed fields that were **removed**, with reasons:

| Field | Decision |
| --- | --- |
| `price_basis` | Removed. The table holds raw observations only, so the value would be constant. Adjusted series get their own table later. The loader asserts `PriceBasis.RAW` before insert. |
| `is_adjusted` | Removed. Redundant with `price_basis`, and with the table's definition. |
| `snapshot_id` | Removed. Derivable: `file_id → source_files.snapshot_id`. |
| `content_hash` | Removed. Idempotency and conflict detection compare columns directly in SQL (`IS DISTINCT FROM`), which is exact and needs no hash definition to stay stable. |
| `created_at` | Removed. The insert time is `ingestion_runs.started_at` via `ingestion_run_id`. |
| `currency` | Moved to `securities`. |

### `data_quality_incidents`

**Purpose:** events that need attention or evidence: conflicts, rejected rows,
source anomalies. Flags record **states**; incidents record **events and
details**.

| Column | Type | Null | Notes |
| --- | --- | --- | --- |
| `incident_id` | BIGINT | NOT NULL | **PK**, identity |
| `ingestion_run_id` | UUID | NOT NULL | FK → `ingestion_runs` (RESTRICT); run that detected it |
| `incident_type` | TEXT | NOT NULL | CHECK IN (`conflicting_observation`, `conflicting_duplicate_in_snapshot`, `hard_invalid_record`, `source_ticker_column_mismatch`, `snapshot_content_mismatch`) |
| `status` | TEXT | NOT NULL | default `open`; CHECK IN (`open`, `resolved`, `accepted`) |
| `source_id` | TEXT | NULL | FK → `data_sources` (RESTRICT) |
| `security_id` | BIGINT | NULL | FK → `securities` (RESTRICT) |
| `trading_date` | DATE | NULL | |
| `file_id` | BIGINT | NULL | FK → `source_files` (RESTRICT) |
| `source_line` | INTEGER | NULL | CHECK `>= 1` |
| `details` | JSONB | NOT NULL | e.g. stored values, incoming values, raw references, raw ticker text `True` |
| `created_at` | TIMESTAMPTZ | NOT NULL | default `now()` |

- Indexes: (`ingestion_run_id`); (`security_id`, `trading_date`).
- Detection is idempotent: re-running a snapshot does not add a second
  identical incident. The loader checks for an existing incident with the same
  type, key, and incoming values before inserting.

## Daily Price Semantics

| Field | Meaning | NULL means | 0 in raw source means |
| --- | --- | --- | --- |
| `open` | First regular-market price | Source did not supply an open (81.10% of rows) | Missing; stored as NULL, **never filled** from close, reference price, a previous open, or forward fill |
| `high` / `low` | Regular-market range | No range: always NULL on `no_regular_market_trade` rows | Placeholder on zero-volume rows; stored as NULL |
| `close` | Source closing/reference price; always present | — | Not observed (a raw 0 would be rejected as hard-invalid) |
| `reference_price` | Exchange reference price (source `Previous`). **Not necessarily the prior close**: it differs around corporate actions | Source did not supply one | Not observed |
| `volume` | Regular-market shares traded | Source did not supply it | Genuinely zero regular-market volume |
| `value` | Regular-market traded value, IDR | Not supplied | Zero |
| `frequency` | Regular-market number of trades | Not supplied | Zero |
| `trading_status` | `traded`: regular volume > 0 with a range. `no_regular_market_trade`: the source's zero-volume pattern; says nothing about suspension. `unknown`: any other pattern | — | — |
| price basis | Raw, unadjusted: the table's definition | — | — |
| `quality_flags` | `non_regular_activity_present` (source `NonRegularVolume > 0`); `unverified_trading_date` (Saturday or Sunday) | — | — |

- On a `no_regular_market_trade` row, `close` equals the source's reference
  price and is **not evidence of an executed regular-market trade**.
- Non-regular figures stay in the raw files (contract Decision 1, option B).

## Identity Model

- `security_id` is an internal surrogate. It is never the ticker, and it
  never *is* a market identifier.
- A source-side identity is `(source_id, source_key)` in
  `security_source_keys`. Today every mapping is a development identity
  (`securities.identity_kind = 'development'`).
- A future stable identifier (ISIN, exchange or vendor ID) is added as another
  mapping, or as a later `security_identifiers` table with validity periods.
  Price rows keep pointing at `security_id` and are **never rewritten**.
- Ticker and name on `securities` are current display metadata. Their history
  is deferred (see [Future Extensions](#future-extensions)).
- Pholenk mapping: one security per file key. The file key is the
  deterministic source key (`TRUE`, not `True`).

## Provenance Model

The chain from a price row back to the raw bytes:

```text
daily_prices (file_id, source_line)
  → source_files (relative_path, sha256, snapshot_id)
    → source_snapshots (source_id, source_revision, content_sha256,
                        archive_sha256, source_url, retrieved_at,
                        licence_reference, raw_storage_path)
daily_prices (ingestion_run_id) → ingestion_runs (parser_version, started_at)
```

- **Sufficient to reproduce a row exactly:** open
  `raw_storage_path/relative_path`, verify `sha256`, read `source_line`, and
  re-run the recorded `parser_version`.
- **Not duplicated per row:** `snapshot_id`, file path, file hash, revision,
  licence, URL, retrieval time, parser version. Per-row provenance cost is
  `file_id` (8 B) + `source_line` (4 B) + `ingestion_run_id` (16 B).
- **Provenance is first-seen.** If a later snapshot contains an identical
  observation, the row keeps its original `file_id`, and the later run counts
  it as `rows_unchanged`.
- **Hashing:** file hashes are computed from the same bytes that are parsed,
  and the snapshot's `content_sha256` is recomputed from the file inventory
  and verified before any insert.

## Idempotency & Conflict Model

Natural key of an observation: (`security_id`, `trading_date`, `source_id`),
which is the primary key. Price basis is implicitly raw.

**Mechanism.** One database transaction per ingestion run, with the run
record itself written and finalized in its own short transactions so that a
failure is still recorded.

1. Get-or-create `data_sources` and `source_snapshots` by natural key.
   `source_files` is inserted with `ON CONFLICT (snapshot_id, relative_path) DO
   NOTHING`, then every stored `sha256` is verified to equal the recomputed one.
2. Get-or-create `securities` / `security_source_keys` by
   (`source_id`, `source_key`).
3. COPY canonical rows into a temporary staging table.
4. Within-snapshot conflicting duplicates are rejected before staging (the
   provider already raises). The security's batch is rejected and recorded as a
   `conflicting_duplicate_in_snapshot` incident.
5. `INSERT INTO daily_prices SELECT … FROM staging ON CONFLICT (pk) DO NOTHING`
   gives `rows_inserted`.
6. Staging rows whose key exists but whose values differ (any canonical column
   `IS DISTINCT FROM` the stored value, including `quality_flags`) become
   `conflicting_observation` incidents. The details hold the stored values, the
   incoming values, and both raw references. The stored row is **not**
   modified.
7. The remaining matched rows are `rows_unchanged`.

**Scenarios.**

| Scenario | Result |
| --- | --- |
| Run A on snapshot S | Inserts all valid observations |
| Run B on the same S | `rows_inserted = 0`, `rows_unchanged = rows_seen − rejected`, no new incidents |
| Same key, different content (a new snapshot, or a new parser version) | Canonical row unchanged; `conflicting_observation` incident with both versions |
| Hard-invalid row | Not inserted; `hard_invalid_record` incident with its raw reference |

## Correction handling (future; not implemented)

The schema keeps every piece of a correction:

- the original observation (the canonical row);
- the corrected candidate (the incident's `details`, with its file and line);
- both snapshots (via the file IDs);
- the reason (incident type and status).

A future correction workflow can add a `daily_price_versions` history table:
copy the current row with `superseded_by_incident_id` and a timestamp, then
update the canonical row, following the source-precedence rule (requirements
doc §21). Nothing in Phase 2B blocks this, and no data is lost in the meantime.

## Indexing

| Query | Index used |
| --- | --- |
| One stock over a date range | PK (`security_id`, `trading_date`, `source_id`), range scan |
| All stocks on a date | **(`trading_date`)** — the only extra index on `daily_prices` |
| Latest price per security | PK, backward scan per security (`DISTINCT ON` / `LATERAL … LIMIT 1`) |
| Liquidity screening on a date | (`trading_date`), then filter `volume`/`value` |
| Feature calculation (full series per security) | PK |

- **Not indexed yet:** `file_id` and `ingestion_run_id` on `daily_prices`.
  They're used for audits, not hot paths, and deletes are restricted. Add them
  if audit queries prove slow.
- Other tables: only their PK/UNIQUE constraints plus the few FK-lookup
  indexes listed per table. Estimated `daily_prices` size for 1.29M rows is
  ~150–250 MB including indexes.

## Partitioning Decision

**Not partitioned in Phase 2B.**
- 1.29M rows, or even tens of millions, fit comfortably in one PostgreSQL
  table with the PK and date index.
- Partitioning would solve data-retention management and very large scans,
  and neither exists yet.
- It adds real costs: every partition needs its constraints and indexes, and
  Alembic handling gets more complex.
- The PK already contains `trading_date`, so range-partitioning by date remains
  possible later without changing the key.
- **Revisit** when the table exceeds ~100M rows or measured queries require it.

## Numeric Precision

Measured on snapshot `9bb3b26`:
- max price 398,000; min close 1; all prices whole rupiah;
- max volume 45,941,761,600 (above the 32-bit limit of 2,147,483,647);
- max value 9,804,286,370,000;
- max frequency 530,819.

| Field | Type | Reason |
| --- | --- | --- |
| Prices | NUMERIC(20,4) | Exact. 16 integer digits (vs 6 needed), and scale 4 for future non-IDR or sub-unit prices at no correctness cost |
| `volume` | BIGINT | Exceeds 32-bit; BIGINT max is 9.2 × 10¹⁸ |
| `frequency` | BIGINT | Fits 32-bit today; BIGINT per requirement and future sources |
| `value` | NUMERIC(24,4) | Exact; 20 integer digits vs 13 needed; allows fractional values from other sources |
| Counters in `ingestion_runs` | BIGINT | Row counts |

No FLOAT or REAL anywhere in financial data.

## Delete / FK Behavior

- **All foreign keys are `ON DELETE RESTRICT`.** Nothing uses `CASCADE` or
  `SET NULL`.
- Snapshots, files, runs, securities, source keys, prices and incidents are
  historical evidence. Deleting a referenced parent fails.
- Deliberate removal, for example of a local test load, must delete children
  explicitly, in order, in a reviewed script.
- Updates to key columns are not expected. PK values are immutable by
  convention (no `ON UPDATE CASCADE`).

## Bulk Loading Recommendation

**psycopg 3 `COPY` into a temporary staging table, then set-based SQL**
(`INSERT … SELECT … ON CONFLICT DO NOTHING`, plus a conflict-detection
`SELECT`), in one transaction per run.

- COPY is the fastest standard way to load 1.29M rows, typically seconds. ORM
  or `executemany` bulk inserts are much slower at this size.
- The staging table makes idempotency and conflict detection pure SQL,
  avoiding row-by-row Python round trips.
- It's reachable from SQLAlchemy via the underlying psycopg 3 connection
  (`Connection.connection.driver_connection`, then `cursor().copy(...)`), with
  no new dependency.
- Staging is `CREATE TEMP TABLE … (LIKE daily_prices)` plus provenance
  columns, dropped at commit. It isn't part of the schema or migrations.

## Migration Safety

Every construct is supported by SQLAlchemy 2.0 and Alembic 1.20 on
PostgreSQL 17:

| Construct | SQLAlchemy / Alembic support | Note |
| --- | --- | --- |
| BIGINT, INTEGER, NUMERIC(p,s), DATE, TEXT, TIMESTAMPTZ | `BigInteger`, `Integer`, `Numeric(p, s)`, `Date`, `Text`, `DateTime(timezone=True)` | Portable |
| Identity columns | `Identity()` | |
| UUID | `sqlalchemy.Uuid` (native `uuid` on PostgreSQL) | |
| JSONB | `postgresql.JSONB` | PostgreSQL-specific. Justified: variable incident details and validation summaries, used only in 2 audit tables |
| TEXT[] + `<@` CHECK | `postgresql.ARRAY(Text)` | PostgreSQL-specific. Justified as the simplest extensible flag representation |
| CHECK constraints | `CheckConstraint(..., name=...)` | Alembic autogenerate does **not** detect CHECK changes, so migrations must write them explicitly |
| Status vocabularies | TEXT + CHECK, **not** PostgreSQL ENUM | Adding a value is an ordinary constraint change, whereas `ALTER TYPE` has transaction caveats and poor autogenerate support |

**Implementation note:** `tests/test_project_setup.py::test_orm_metadata_is_empty_in_phase_0`
is a deliberate tripwire. Phase 2B.2 must update it when the models are added.

## Quality flags — representation decision

**Chosen: `TEXT[]` with a CHECK against the documented vocabulary**, on
`daily_prices` (row flags) and `security_source_keys` (source-key flags).
Details that a flag cannot carry, such as the raw ticker `True`, go to
`data_quality_incidents`.

| Option | Verdict |
| --- | --- |
| JSONB | Rejected. Unstructured; a vocabulary is harder to enforce |
| **TEXT[] + CHECK** | **Chosen.** One column, enforced vocabulary, `'flag' = ANY(quality_flags)` queries, GIN-indexable later, and a new flag is a one-line constraint change |
| Normalized flag table | Rejected for now. Extra joins for 2 sparse flags; revisit if flags gain attributes |
| Enum columns | Rejected. ENUM migration friction |
| Separate booleans | Rejected. One migration **and** one column per flag, and a wider table |

## Contract alignment

This design refines the approved contract in three points. They take effect
**with approval of this design**. The contract text was updated accordingly in
Phase 2B.4.

1. **`parser_version` moves from snapshot level to `ingestion_runs`.** It
   describes our code, not the dataset. The same snapshot parsed by two
   parser versions is the same dataset version.
2. **Rows also reference their inserting `ingestion_run_id`.** The contract's
   "rows reference their snapshot" holds via `file_id`. The run link adds the
   only path to the parser version that produced a row.
3. **`price_basis` is implicit (raw) rather than a column.** The contract's
   natural key (`source_id`, `security_id`, `trading_date`, `price_basis`)
   reduces to the PK here, because this table holds raw observations only.

## Future Extensions

| Extension | How it fits |
| --- | --- |
| Stable IDs | New `security_source_keys` rows, or a `security_identifiers` (scheme, value, valid_from, valid_to) table. Prices untouched |
| Ticker history | `security_tickers` (security_id, ticker, valid_from, valid_to, source) |
| Name history | `security_names` (same shape); backfillable from raw files |
| Corporate actions | `corporate_actions` table keyed to `security_id`, with provenance links |
| Adjusted prices | `adjustment_factors` + an adjusted series table/view; never written into `daily_prices` |
| Total return | Derived from raw prices + dividends + factors (contract §24 assumption) |
| Authoritative trading calendar | `trading_calendar` table; replaces the weekend-only `unverified_trading_date` rule |
| Authoritative suspension data | New status values (`suspended`, `no_trades`) via a CHECK change, from a source that establishes them |
| Multiple licensed sources | Additional `source_id` values; the PK already separates per-source observations; a resolved per-(security, date) view follows the precedence rule |
| Non-regular market data | Promote the raw non-regular fields to canonical columns in a microstructure phase |
| Partitioning | Range by `trading_date` when size requires |

## Open Questions

None block Phase 2B implementation.

- **FUTURE / NON-BLOCKING:** revision string convention for sources without a
  version identifier (define with the first such source).
- **FUTURE / NON-BLOCKING:** whether `quality_flags` changes from a new parser
  version should be a correction workflow or a separate annotation update.
  Until decided, they are treated as conflicts (step 6) — safe, since nothing
  is overwritten.
- **FUTURE / NON-BLOCKING:** audit indexes on `daily_prices.file_id` /
  `ingestion_run_id`, if audit queries need them.
