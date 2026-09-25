# Phase 2D — Market Indices and Observed Trading Calendar

## Status

**IMPLEMENTED (Phase 2D), pending owner review.** Date: 2026-09-25/26.
Migration `6117977fb001`. Development data only (Pholenk snapshot `9bb3b26`).

Governing documents: [Phase 2B Data Contract](phase_2b_data_contract.md),
[Phase 2B ingestion design](phase_2b_ingestion_design.md), and
[Phase 2C design](phase_2c_corporate_actions_design.md). The benchmark is
needed by CLAUDE.md §6 (relative strength), §11 (event studies), §12 (market
regime), and §20 (backtest benchmarks).

## 1. Audit of the index files (read-only, 2026-09-25)

The Pholenk snapshot already contains 56 index files,
`dataset/indices/csv/<CODE>.csv`. They were inventoried in Phase 2B.3D but not
loaded.

| Fact | Value |
| --- | --- |
| Files / rows | 56 / 63,919 |
| Header | One header in all 56 files (UTF-8 BOM): `Date, Previous, Highest, Lowest, Close, Constituent, Change, Volume, Value, Frequency, Capitalization`. **No open** |
| Row order | Newest first |
| Precision | Levels ≤ 3 decimals; volume, value, frequency, and capitalization are integers |
| Ranges | `COMPOSITE` (IHSG) 2020-01-02 → 2026-05-29, 1,540 rows. Sector indices renamed in 2021: old `AGRI`…`TRADE` end 2021-04-30; new `IDXBASIC`…`IDXTRANS` start 2021-01-25. `PEFINDO25` ends 2025-01-31 |
| Unparseable numbers, duplicates, high < low, close outside [low, high], non-positive values | 0 each |
| `Change = Close − Previous` | True on every row |
| `Previous` ≠ prior row's close | 37 rows, **all on 2021-05-24**, the Monday after the Saturday row 2021-05-22 (present in 38 files) |
| 2024 stock anomaly dates (Phase 2C §2.2) | **No** discontinuity in the index data: the problem is confined to the stock files |

### 1.1 Three trading days are missing from the stock data

IHSG has 1,540 dates and the stock data 1,537. Every stock date is an IHSG
date. The three extra IHSG dates are **2023-02-06, 2024-03-25, and
2024-07-15**. Each is the day before a Phase 2C market-wide anomaly date
(2023-02-07, 2024-03-26, 2024-07-16).

So on those three dates the IDX reference price is correct, and the stock row
of the previous trading day is missing. The other 15 anomaly dates are
consistent with shifted rows (Phase 2C §2.2).

## 2. Design

* **`index_daily_values`** (raw; never adjusted).
  * Key: `(source_id, index_code, trading_date)`. The index code is the file
    key, and no separate index entity exists until a second index source
    needs mapping.
  * Columns: `previous`, `high`, `low`, `close`, `constituents`, `volume`,
    `value`, `frequency`, `capitalization`, `quality_flags` (only
    `unverified_trading_date`), `file_id`, `source_line`, `ingestion_run_id`.
  * `Change` is validated (it must equal `close − previous`) and not stored.
  * CHECKs: positive values, `low ≤ close ≤ high`, non-negative counts, flag
    vocabulary, code format.
* **Loader.** The Phase 2C record loader is reused with a new adapter,
  `data/ingestion/pholenk_indices.py`, parser `pholenk-index-csv-1`.
  * The loader was generalized: data files are selected per snapshot
    (`select_data_files`); security linking is optional
    (`links_securities`); provenance can be a line number
    (`provenance_column = "source_line"`).
  * The indices load into the **same registered Pholenk snapshot** (same
    `snapshot_id`) as a new ingestion run.
* **View `observed_trading_days`** (not a table). For each (source, date) in
  stock or index data it gives `stock_rows`, `index_rows`, `in_stock_data`,
  `in_index_data`, and `is_weekend`. This is an *observed* calendar, not an
  authoritative IDX calendar: that remains a gap (requirements doc §26).
* **Benchmark series** (`data/features/index_series.py`,
  `load_index_series`):
  * `index_return = close / previous − 1`;
  * `reliable = False` on `unverified_trading_date` rows and wherever
    `previous` differs from the prior stored close.
* **Verification.**
  * `verify_load` checks every file's identity (path + SHA-256), and row
    counts and keys only for the files the adapter counts. This is needed
    now that one snapshot is loaded by two adapters.
  * The price check `run.latest_succeeded_rows_seen` now selects runs by
    parser version.

## 3. Results (development database)

| Measure | Value |
| --- | --- |
| Migration | `6117977fb001`, applied deliberately; `alembic check` clean |
| Index load run | `a1314200-c74e-459a-ab37-2b8c8371b9f3`: 63,919 rows inserted from 56 files, 0 rejected |
| `verify_load pholenk-indices --deep` | 16/16 (0 missing, differing, or extra rows) |
| `verify_load pholenk` (prices, after the second run on the snapshot) | 48/48 |
| `observed_trading_days` | 1,540 dates. 1,537 are in both stock and index data; 3 are index-only (§1.1); 1 is a weekend date (2021-05-22) |
| IHSG series | 1,540 bars; unreliable only on 2021-05-22 and 2021-05-24 |

## 4. Open items

1. **Phase 2C method refinement.** On the three anomaly dates that follow a
   missing stock day, the reference-price factors are genuine (the missing
   row is the cause). A later `ref-v2` could apply them instead of excluding
   them.
2. **The 2021-05-22 rows** (stocks and indices) look like a mislabeled or
   extra trading day. They are flagged, not repaired.
3. **Not an official calendar.** No authoritative IDX trading calendar or
   index methodology/constituent history is included. Development data only.
