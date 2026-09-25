# Phase 2B Data Contract

Decision record for persisting daily market data in Phase 2B.

| | |
| --- | --- |
| **Date** | 2026-09-24 |
| **Basis** | Phase 2A.5 sanity check (verdict: READY WITH CONDITIONS) and the project owner's Phase 2B direction |
| **Applies to** | Daily stock prices from the Pholenk/IDX-Dataset development source (`data/ingestion/pholenk.py`), and any later daily-price source unless it documents stronger semantics |
| **Related** | [market_data_requirements.md](market_data_requirements.md) §21–§23, §26, §32, §36 |

## Status

**APPROVED FOR IMPLEMENTATION.** All three blocking decisions are resolved
below. Implementation has **not** started; this record changes no code, schema,
or tests. The code changes it requires are listed under
[Required implementation changes](#required-implementation-changes).

## Scope

**Development mode only.** This contract governs how the Pholenk development
source is persisted. It does not declare that source production-grade or
production-licensed, and it does **not** weaken any production requirement in
the requirements document. Where this contract is stricter than the
requirements document (temporal semantics, §22), this contract applies.

---

## Decision 1 — Market Scope

### Findings (Pholenk snapshot `9bb3b26`)

* `Volume`, `Value`, and `Frequency` describe the **regular market**.
  `NonRegularVolume > Volume` in 47,181 rows, so `Volume` is not a total.
* 6,102 rows have `Volume = 0` but `NonRegularVolume > 0`: negotiated or other
  non-regular activity happened although no regular-market trade was recorded.
* The source's non-regular columns are `NonRegularVolume`, `NonRegularValue`,
  and `NonRegularFrequency`.

### Decision

1. **Canonical `volume`, `value`, and `frequency` mean regular-market activity
   only.** They are the default basis for prices, returns, liquidity, and
   ordinary backtesting. Non-regular activity is never added to them.
2. **Non-regular data is retained in the raw layer (option B).** The raw files
   are immutable and keep all non-regular columns; every canonical row points
   to its raw row (file + line). Phase 2B adds **no** separate non-regular
   canonical fields and **no** second market ledger.
3. **The scope is made explicit in the canonical layer by one row-level
   quality flag:** `non_regular_activity_present` — set when the source's
   `NonRegularVolume > 0`. It lets analyses find affected rows without
   re-reading raw files. Non-regular figures are promoted to canonical fields
   only in a later market-microstructure phase, if needed.

### Trading status

| Status | Valid when | Meaning |
| --- | --- | --- |
| `TRADED` | Regular-market volume > 0, with high and low present | At least one regular-market trade was recorded. |
| `NO_REGULAR_MARKET_TRADE` | Regular-market volume = 0 and the source's high and low are 0 (the source's zero-volume pattern) | No regular-market trade was recorded by the source for this security/date. The source does not establish whether this was a suspension, no trading activity, or activity occurring only outside the regular market. |
| `UNKNOWN` | Any other pattern (e.g. zero volume with a non-zero range, or a source that omits volume) | The status cannot be determined from the source. |

* `NO_REGULAR_MARKET_TRADE` replaces the Phase 2A value
  `NO_TRADE_OR_SUSPENDED`, whose wording implied that no trade of any kind
  occurred — false for the 6,102 rows above.
* **`SUSPENDED` is not used** until an authoritative suspension source exists.
  **`NO_TRADES` is not used either**: the source cannot distinguish "no
  trading activity" from the other causes.
* A `TRADED` row with a missing high or low remains hard-invalid (existing
  validation rule).

---

## Decision 2 — Snapshot vs Ingestion Run

| Concept | Answers | Identity | Cardinality |
| --- | --- | --- | --- |
| **Snapshot** | **What** dataset version | Deterministic from content | One per distinct dataset version |
| **Ingestion run** | **When / how** we loaded it | Unique per execution | Many per snapshot |

### Snapshot identity

* A snapshot is an immutable version of an external dataset.
* Identity is derived from **source + source revision + content hash**:
  * `source_id` — e.g. `pholenk-idx-dataset`;
  * `source_revision` — e.g. git commit `9bb3b26bd28ab46bc2f3e74a7c03805ce053301b`;
  * `content_sha256` — SHA-256 over the sorted file inventory
    (relative path + file SHA-256 of every data file loaded).
* **`retrieved_at` is never part of snapshot identity.** Retrieving the same
  content twice yields the same snapshot.
* `archive_sha256` (e.g. `5165948e…566c91`) is recorded as an integrity
  attribute, not as the identity: a re-generated archive of identical content
  can have different bytes, while the file inventory hash depends only on the
  data actually loaded.
* If the same `source_id` + `source_revision` ever arrives with a different
  `content_sha256`, that is a **different snapshot** and must be recorded as a
  data-quality incident — never merged silently.
* Uniqueness: (`source_id`, `source_revision`, `content_sha256`). The
  `snapshot_id` string is derived deterministically from these values.

### Ingestion run identity

* One run = one execution of the loader. Every execution gets a new, unique
  `ingestion_run_id` (e.g. a UUID); run IDs are **not** deterministic.
* Run metadata: `ingestion_run_id`, `snapshot_id`, `started_at`,
  `completed_at`, `status` (`running` / `succeeded` / `failed`), `rows_seen`,
  `rows_accepted` (inserted + already present and identical), `rows_rejected`,
  and a validation summary.
* Canonical rows reference their **snapshot** (what they came from). The run
  is an audit record of the load.
* Phase 2A's deterministic `ingestion_run_id`
  (`pholenk-idx-dataset@<revision>@<retrieved_at>`) is in effect a snapshot
  label; it is replaced by the split above.

### Idempotency consequence

Loading the same snapshot again creates a new run record and **no new or
changed canonical rows**: identical observations are recognised and left as
they are.

---

## Decision 3 — Temporal Semantics

| Concept | Definition | Pholenk value |
| --- | --- | --- |
| `trading_date` | The exchange-local date (WIB) to which the market observation belongs; the temporal identity of the observation | The source `Date` column |
| `retrieved_at` | UTC timestamp when **our system** obtained the dataset; describes our knowledge, not the market | Snapshot-level: `2026-09-24T11:28:14Z` for revision `9bb3b26` |
| historical `available_at` | When the observation actually became available to a market participant | **UNKNOWN** — the source gives no reliable publication timestamp |

Rules:

1. `retrieved_at` is stored at **snapshot level**, not repeated per row.
2. `retrieved_at` is **never** stored or used as historical `available_at`,
   and no observation is claimed to have become available at retrieval time.
3. For this source, historical `available_at` is recorded as **unknown** (not
   a fabricated value). No precise end-of-day availability time is invented.
4. A future authoritative publication timestamp, if obtained, is stored as a
   separate, source-attributed field.

This supersedes, for backfilled daily prices, the fallback in requirements
doc §22 ("use `retrieved_at` and flag `available_at_is_fallback`"). The
fallback made every historical price appear to become available in 2026,
which is unusable for backtests and misleading.

---

## Backtesting Time Integrity

Project-level rule:

> **A backtest must never use information based solely on the fact that our
> system retrieved the dataset later.**

The system distinguishes three times:

1. **Event time** — when the market event occurred (`trading_date`).
2. **Availability time** — when the data was actually available to a market
   participant.
3. **Knowledge time** — when our system retrieved it (`retrieved_at`).

If (2) is unknown, the model must not silently treat (3) as (2).

Consequences for any future backtest or feature computation:

* When availability time is unknown, the backtest configuration must state an
  **explicit, documented availability assumption**, and that assumption must
  be recorded with the results. Phase 2B defines **no default** assumption.
* A decision dated D may use only observations whose availability — under the
  stated assumption or an authoritative timestamp — precedes the decision.
* Every backtest pins the snapshot(s) it read, so results are reproducible and
  later corrections do not change past results silently.
* Rows flagged as quality issues (e.g. `unverified_trading_date`) are handled
  by an explicit, recorded rule — never ignored implicitly.

---

## Supporting Data Semantics

### `reference_price` (source `Previous`)

* Canonical name: **`reference_price`** (Phase 2A: `previous_close`).
* It is the exchange's reference price for the day. It is **not necessarily
  the prior trading day's close**: it differs around corporate actions (BBCA
  2021-10-13: reference 7,325 vs prior close 36,600 across the 5:1 split) and
  on 64 zero-volume rows in the snapshot.
* It must **not** be used as an ordinary return denominator without
  corporate-action context. It may later serve as evidence for detecting
  corporate actions.

### `is_adjusted`

* Pholenk prices are raw: `is_adjusted = false` (`price_basis = raw`),
  confirmed by the unadjusted BBCA split in the data.
* Raw observations are never modified. Future pipeline:
  **RAW PRICE → CORPORATE ACTIONS → ADJUSTMENT FACTORS → ADJUSTED PRICE /
  TOTAL RETURN**. Factors and adjusted series are stored separately and
  **never overwrite** raw observations.

### Missing Open

* Raw `Open = 0` → canonical `open = NULL`. Zero is never a valid traded open.
* `open` is **never** filled from close, the reference price, a previous
  day's open, or by forward fill.
* This is an intentional record of a **data-source limitation** (open missing
  in 81.10% of rows, mostly before 2025). Analyses needing opens must handle
  `NULL` explicitly.

### Close on a zero-volume row

* The source Close is preserved, and the row is kept.
* On a `NO_REGULAR_MARKET_TRADE` row, **Close is a source reference/carried
  price and is not evidence of an executed regular-market trade.** In the
  snapshot it equals the source's `Previous` on every such row.
* High and low are `NULL` on these rows; `volume` is 0.

### Quality flags

Quality flags record source conditions without changing or deleting data.
Initial vocabulary:

| Flag | Level | Set when |
| --- | --- | --- |
| `non_regular_activity_present` | Row | Source `NonRegularVolume > 0` |
| `unverified_trading_date` | Row | `trading_date` falls on a Saturday or Sunday (the only calendar check possible without an authoritative calendar) |
| `source_ticker_column_mismatch` | Security (source key) | The source's ticker column differs from the file key; the raw value is recorded |

Conditions already expressed by a field are **not** duplicated as flags
(e.g. `open IS NULL`, `trading_status = NO_REGULAR_MARKET_TRADE`). New flags
are added only for observed conditions and must be documented here.

### TRUE ticker anomaly

* `TRUE.csv` contains ticker text `True` in all 1,188 rows (upstream boolean
  coercion).
* The **file key `TRUE` is the deterministic source key**.
* The mismatch is preserved as `source_ticker_column_mismatch` with raw value
  `True`. The security is not renamed, deleted, or merged.
* The database must support source-level quality flags for this.

### Unusual trading dates

* `2021-05-22` (a Saturday) appears for 732 securities and in the source's
  composite index. The same rows appear in a separately published IDX-format
  copy (requirements doc §36).
* The date is **not declared invalid**. Trading-calendar validation is
  currently unavailable. Rows on weekend dates carry
  `unverified_trading_date`. An authoritative IDX trading calendar will
  resolve them later; no calendar is invented.

### Per-file provenance

| Level | Contents |
| --- | --- |
| Snapshot | `source_id`, `source_revision`, `content_sha256`, `archive_sha256`, `retrieved_at`, licence reference, parser version, source URL, raw storage path |
| File | relative path, file SHA-256, row count, source key |
| Row | file reference, source line, quality flags |

* Raw files remain **outside PostgreSQL**; no raw CSV blobs are stored.
* A canonical row is reproduced as: row → file (path + SHA-256) → snapshot
  (revision + content hash) → source line.
* The file SHA-256 must be computed from **the same bytes that are parsed**,
  and the file inventory is verified against the snapshot before loading.

---

## Phase 2B Database Principles

Principles only; no schema is defined here.

1. **Raw is immutable.** Source files are never modified; raw values are never
   overwritten.
2. **Canonical is normalized.** Canonical rows follow the semantics in this
   contract.
3. **Provenance is traceable.** Every canonical row resolves to snapshot, file,
   and line.
4. **Snapshot identity is deterministic** (Decision 2).
5. **Ingestion runs are unique** per execution (Decision 2).
6. **Loading is idempotent.** Re-loading a snapshot changes no canonical rows.
   The natural key of a daily observation is
   (`source_id`, `security_id`, `trading_date`, `price_basis`).
7. **No silent overwrite.** Exact duplicates are deduplicated. Conflicting
   observations — within a snapshot or across snapshots — are never silently
   overwritten: the existing value stays, the conflict is recorded as a
   data-quality incident with references to both raw rows, and resolution
   follows the source-precedence rule (requirements doc §21) once adopted.
8. **Ticker is not a permanent security identity.** `security_id` is an
   internal key; source keys (today the development identity
   `dev:pholenk-idx-dataset:<KEY>`) are mapped to it, so a future stable
   vendor/exchange ID can be added without rewriting price rows.
9. **No fabricated availability timestamps** (Decision 3).

## Required implementation changes

To be made **as part of Phase 2B implementation**, not by this record:

* `TradingStatus`: replace `NO_TRADE_OR_SUSPENDED` with
  `NO_REGULAR_MARKET_TRADE`; stop producing `NO_TRADES` / `SUSPENDED` from
  this source.
* `DailyPrice.previous_close` → `reference_price`.
* Provenance: stop presenting `retrieved_at` as `available_at`; represent
  unknown availability explicitly. Move `retrieved_at`, licence, parser
  version, and revision to snapshot level.
* Replace the deterministic Phase 2A `ingestion_run_id` with `snapshot_id`
  (deterministic) plus a per-execution `ingestion_run_id`.
* Compute file hashes from the parsed bytes; build and verify the file
  inventory and `content_sha256`.
* Produce the quality flags defined above.
* Update tests accordingly.

## Known Development Limitations

* The Pholenk/IDX-Dataset **development** source only.
* Coverage **2020-01-02 onward** (production requires 2015-01-01).
* **Missing Open** in 81.10% of rows.
* **No authoritative suspension status.**
* **No authoritative trading calendar** yet.
* **No stable production security ID**; development identity only.
* **No corporate-action adjustment layer.**
* **Production licensing remains unresolved** (requirements doc §32).

## Explicit Non-Goals

Phase 2B does **not** solve:

* production licensing;
* corporate actions;
* adjusted prices;
* total return;
* stable production security IDs;
* historical ticker/name mapping;
* authoritative suspension status;
* an authoritative trading calendar;
* backtesting.
