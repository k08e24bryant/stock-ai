# Phase 2C Design — Corporate Actions, Dividends, and Adjusted Prices

## Status

**IMPLEMENTED (Phase 2C-2), pending owner review.** Design in Phase 2C-1; the
owner approved all five decisions in §4 on 2026-09-25. Implementation,
migration `55a78b2c9066`, the development loads, and verification are
recorded in [§6](#6-implementation-and-results-phase-2c-2). §1–§2 are the
Phase 2C-1 measurements. They were taken read-only from the development
database (Pholenk snapshot `9bb3b26`, loaded in Phase 2B.3D) and from the two
external snapshots, now stored git-ignored under `data/raw/`.

Governing documents: [market_data_requirements.md](market_data_requirements.md)
§14, §21–§25, §36; [Phase 2B Data Contract](phase_2b_data_contract.md)
(`daily_prices` stays raw, never adjusted in place); CLAUDE.md §17 (document
which price series is used for returns, simulation, and display).

## Why this phase

`daily_prices` holds **raw** prices. BBCA closes at 36,600 on 2021-10-12 and at
7,525 on 2021-10-13 because of a 1:5 split. Any return, indicator, event
study, model feature, or backtest computed from raw closes reads that split as
a −79% crash. Of the 200 raw daily moves above 35% outside the anomaly dates
(§2.2), 94 disappear once the corporate-action adjustment in this design is
applied. The remaining 106 are all tick-size moves of stocks priced at Rp10 or
less (for example Rp2 → Rp3).

---

## 1. Sources audited

| # | Source | Pinned revision | Archive SHA-256 | Licence (as published) | Content used |
| --- | --- | --- | --- | --- | --- |
| DS-4 | Pholenk/IDX-Dataset (already loaded) | `9bb3b26bd28ab46bc2f3e74a7c03805ce053301b` | `5165948e…566c91` | ODbL 1.0; upstream IDX | `Previous` = IDX **reference price** (`daily_prices.reference_price`) |
| DS-9 | nichsedge/idx-bei `data/corporateActions.json` | `34903cee8880d27c73fd2af67dfe028e8f937f98` (2026-09-24) | `610c87d035913f9671de4702b2319d59e71bae9dc81aa7b885543cfea17fcdcf` | MIT (repository); data scraped from IDX, upstream rights unclear | 1,652 events in 15 categories: code, `TanggalPencatatan` (registration date), `JumlahSaham`, `JumlahSahamSetelahTindakan` |
| DS-7 | dimasirginsyh/indonesia-stock-dividends `all_dividends.json` | `92115bfb6b68d8c3afe6d417dd2201e93ee561ed` (2026-09-10) | `3739eead4bc63b6915dd9955ce72ec3d0522f4ace6771443d5ef149ec2870947` | **none** (LICENSE UNCLEAR); upstream DS-8 → IDX | Cash dividends for 602 tickers: `ex_date`, `dividend`, `dividend_type`, `fiscal_year`, `payment_date` |

All three are **development sources** (requirements §36). None satisfies the
production licensing requirements. The licences are recorded here, not
treated as a gate, per the $0 development-mode decision.

---

## 2. Findings (measured 2026-09-25)

### 2.1 The IDX reference price already encodes price adjustments

On an ex-date IDX publishes an **adjusted reference price** (`Previous`).
Wherever `reference_price(t) ≠ close(t−1)`, the ratio
`f = reference_price(t) / close(t−1)` is IDX's own price-adjustment factor.

* 1,288,837 consecutive (security, day) pairs: 1,278,716 with
  `reference_price = previous close` and **10,121 without**.
* Examples (`close(t−1) / reference_price(t)`):
  * splits: FAST 2.000, SIDO 2.007, BELL 5.000, DIGI 5.000, EMTK 10.000,
    BBCA 36,600 / 7,325;
  * reverse splits: BEKS 0.100, NETV 0.500;
  * rights and bonus issues: ARTO 6.653, BEKS 4.289, ASRM 1.298.

### 2.2 18 market-wide anomaly dates are data errors, not corporate actions

9,911 of the 10,121 mismatches fall on **18 dates** on which 75–618
securities mismatch at once:

* 2021-05-24;
* 2023-02-07;
* 2024-02-01, 02-02, 02-13, 02-15, 02-28, 02-29, 03-26, 06-26, 07-01, 07-04,
  07-05, 07-16, 07-31, 08-01, 08-15, 08-16.

On these dates, in 4,379 cases the reference price equals the close from *two*
rows back: a stored row is shifted by one trading day. This extends the §36.5
finding (DS-4 and DS-1 disagree on 9 dates in 2024, including exact one-day
shifts). 2021-05-24 follows the Saturday row 2021-05-22, which is already
flagged `unverified_trading_date`. Which stored row is wrong on each date
cannot be decided from DS-4 alone.

### 2.3 Per-security discontinuities (210 events, 166 securities)

Outside the 18 dates, 210 discontinuities remain:

| Ratio `close(t−1) / ref(t)` | Events |
| --- | --- |
| > 1.25 (split, rights, bonus-like) | 118 |
| 1.02–1.25 | 71 |
| within 2% | 16 |
| < 0.8 (reverse-split-like) | 5 |

### 2.4 DS-9 corporate actions: right dates for splits, incomplete overall

Checked against the 210 discontinuities:

| DS-9 type (2020-01-03 → 2026-05-29, Pholenk universe) | Events | Matching discontinuity |
| --- | --- | --- |
| `stockSplit` | 56 | 54 on **exactly** the DS-9 date |
| `hmetd` (rights issue) | 57 | 39 at 1–3 weeks **before** the DS-9 date |
| `sahamBonus` (bonus shares) | 13 | 13 at 1–3 weeks before |
| `dividenSaham` (stock dividend) | 5 | 5 at 2–3 weeks before |
| `reverseStock` | 0 | — (yet the prices show 5 reverse-split-like events) |

* For splits, `TanggalPencatatan` is the ex-date. For rights, bonus shares, and
  stock dividends it is the **listing date of the new shares**, after the
  ex-date.
* The 18 rights issues with no discontinuity are consistent with rights that
  were out of the money. IDX sets no lower reference price then (§25), but
  DS-9 carries no exercise price to confirm this.
* **DS-9's share counts are unreliable for ratios.** Reading `JumlahSaham` as
  "shares added" reproduces the price ratio (within 2%) for only 38 of 51
  matched splits.
* **DS-9 is incomplete.** 104 discontinuities have no DS-9 event, including
  clear splits: EMTK 10:1 (2021-01-11), DSSA 10:1 (2024-07-18), HEAL 5:1,
  SCMA 5:1, MIDI ≈10:1.

### 2.5 Cash dividends are not in the reference price

* 2,216 DS-7 ex-dates fall in the DS-4 range and universe.
* 2,153 have `reference_price = previous close`: IDX does **not** adjust the
  reference price for cash dividends.
* 12 differ, each on a day with another corporate action (for example MEGA
  bonus shares). 48 fall on anomaly dates, and 3 ex-dates have no row.
* Total return therefore **needs DS-7**; price return does not.
* Carried over from §36.4: gross vs net is not stated, and `payment_date` is
  missing in 45% of records.

---

## 3. Design

### 3.1 Principles

1. `daily_prices` is **never modified**: no adjusted columns and no updates.
2. **Price-adjustment factors come from the exchange's reference price**
   (§2.1). It is the most complete and precise development signal, and it is
   IDX's own number. DS-9 only *classifies* events; it is never the source of
   a ratio.
3. **Every factor is traceable** to the two raw rows it came from (file, line,
   run) and to the method version that derived it.
4. Nothing is inferred silently. The anomaly dates, unclassified events, and
   out-of-the-money rights are recorded and reported, never "fixed".
5. **Point-in-time.** A factor becomes known on its ex-date. Back-adjusted
   price *levels* before an ex-date contain later information. Returns
   computed from them do not, because each factor cancels within a day.

### 3.2 Series and their uses (CLAUDE.md §17)

| Series | Definition | Use |
| --- | --- | --- |
| **Raw** (`daily_prices`) | As published | Display, trading simulation (fills, lots, tick sizes, auto-rejection limits), anything price-level-based that must be point-in-time |
| **Price-adjusted** (derived) | `adj_close(t) = close(t) × Π f(e)` over ex-dates `e > t`. The daily price return is `close(t) / reference_price(t) − 1` | Price returns, technical indicators, event studies, ML features |
| **Total-return** (derived) | Price-adjusted, plus DS-7 cash dividends reinvested at the ex-date close (§24 convention; gross assumed, §4 decision 3) | Performance and backtest P&L and benchmarks |

On days that are not ex-dates, `reference_price(t) = close(t−1)`. The
price-adjusted daily return is then exactly the raw return, so **price returns
never need cumulative factors**. Factors matter only for adjusted *levels*.

### 3.3 Proposed tables (Phase 2C-2; one new migration)

* **`corporate_action_events`**: raw DS-9 records. Columns: source, snapshot,
  file and line provenance, `security_id`, `event_type` (source category
  kept), `registration_date`, and both share counts as published. No derived
  ratio.
* **`cash_dividends`**: raw DS-7 records. Columns: provenance, `security_id`,
  `ex_date`, `amount` (exact numeric, IDR per share), `dividend_type`,
  `fiscal_year`, and a nullable `payment_date`. Gross vs net is recorded as
  `unknown`.
* **`price_adjustment_factors`**: derived from `daily_prices`, and re-derivable
  at any time. Columns:
  * `security_id`, `ex_date`, `factor = reference_price(t) / close(t−1)`
    (exact numeric), and the two raw values;
  * both rows' `file_id` and `source_line`;
  * `method_version`;
  * `classification`: `split`, `reverse_split`, `rights`, `bonus`,
    `stock_dividend`, or `unclassified`, via DS-9 matching rules (§2.4:
    same day for splits, 0–4 weeks before the DS-9 date for rights, bonus,
    and stock dividends);
  * `matched_event_id` (nullable);
  * `status`: `applied`, or `excluded_market_wide_anomaly` (§2.2).
* **Adjusted series**: a view, or a table rebuilt from the factors, is decided
  in 2C-2 by measured cost. It is never stored inside `daily_prices`.
* **Data-quality incidents** for the 18 anomaly dates (one per date, with
  counts), and for unclassified factors.

### 3.4 Loaders

DS-9 and DS-7 follow the Phase 2B pattern: git-ignored raw snapshot with a
`manifest.json` (source URL, commit SHA, archive SHA-256, retrieval time,
licence); deterministic snapshot identity; database-free dry run by default;
`--execute` with the exact confirmation; idempotent and conflict-detecting;
read-only verification. The Phase 2B loader core (`SnapshotSource` protocol,
runs, incidents, advisory lock) is reused.

### 3.5 Validation plan (2C-2)

* Recompute every factor from `daily_prices` and match the table
  (verification, deep mode).
* Known cases:
  * BBCA 2021-10-13 factor 7,325 / 36,600;
  * EMTK 2021-01-11 factor 0.1;
  * BEKS reverse split factor 10;
  * adjusted BBCA series continuous across the split.
* After adjustment, no |daily return| > 35% outside the anomaly dates, except
  prices ≤ Rp10 (today: 106 such, all tick-size).
* The cash-dividend count on ex-dates reconciles with DS-7. Total-return ≥
  price-return for every security with dividends.
* Leakage test: a return on date *t* uses only rows ≤ *t*.

---

## 4. Decisions (approved by the owner, 2026-09-25)

1. **Primary adjustment signal = IDX reference price** (§3.1-2), with DS-9
   for classification only. *Recommended.* The alternative, DS-9 ratios, is
   incomplete (§2.4) and inconsistent.
2. **Use DS-7 (no licence) for development total return.** It is the only
   public cash-dividend source found. Development only, and the licence gap is
   recorded. *Recommended* in $0 mode; the alternative is to postpone total
   return.
3. **Treat DS-7 amounts as gross per share.** IDX announcements state gross
   amounts; tax is withheld at payment. This is a documented assumption
   (§24), not a verified fact.
4. **The 18 anomaly dates:** flag them as incidents, and exclude their
   discontinuities from adjustment factors. Mark returns touching them as
   unreliable, and do **not** repair them in 2C. *Recommended.* The
   alternative is cross-source repair with DS-1, a later separate step, since
   DS-1 is CC BY-NC and is itself one side of the disagreement.
5. **Unclassified discontinuities** (104 with no DS-9 match): *apply* the
   exchange factor and flag it `unclassified` for review (*recommended*,
   because the reference price is IDX-computed); or apply only classified
   factors.

## 5. Non-goals of Phase 2C

* Ticker changes, mergers into another ticker, and delistings: the security
  universe and survivorship (CLAUDE.md §16) is a separate phase.
* Rights exercise economics beyond the reference-price factor (§25): no
  exercise-price source exists.
* Pre-2020 history (DS-5, Yahoo split-adjusted), and cross-source repair of
  the anomaly dates.
* Any production-grade claim.

## 6. Implementation and results (Phase 2C-2)

### 6.1 What was built

| Part | Where |
| --- | --- |
| Tables: `corporate_action_events`, `cash_dividends`, `adjustment_builds`, `price_adjustment_factors`, `reference_price_anomaly_dates` | `backend/models/corporate_actions.py`; migration `55a78b2c9066` |
| Record-snapshot loader (JSON sources). It reuses the Phase 2B registration, incidents, run lifecycle, and advisory lock, now module functions in `data/ingestion/loader.py` | `data/ingestion/records.py` |
| DS-9 and DS-7 adapters | `data/ingestion/idx_bei_actions.py`, `data/ingestion/idx_dividends.py` |
| CLI for the new sources | `python -m data.ingestion.load_snapshot {idx-bei-actions,idx-dividends} <root> [--execute --confirm-revision <full rev>]` |
| Factor derivation, method `ref-v1` (dry run by default, `--execute`, `--verify`) | `python -m data.features.adjustment_factors` |
| Price-adjusted and total-return series (§3.2) | `data/features/adjusted_prices.py` (`load_adjusted_series`) |
| Read-only verification of record sources (`--deep` compares every row) | `python -m data.validation.verify_load {idx-bei-actions,idx-dividends} <root> --deep` |

### 6.2 Refinements made during implementation

* **`adjustment_builds`.** Each derivation records its method parameters,
  its input snapshots, and a summary with the factor hash. Factors and
  anomaly dates reference their build. A rebuild replaces them for the
  (price source, method version) scope.
* **`effective_date`, not only an ex-date.** A cash dividend is reinvested
  on the ex-date, or on the next traded day if the security did not trade on
  the ex-date (§24). `source_ex_date` keeps the source's date.
* **The dividend factor is `close / (close + D)`.** It makes the adjusted
  daily return exactly `(close + D) / reference_price − 1`, the §24 formula.
* **A same-day split rescues an anomaly-date factor.** A discontinuity on
  an anomaly date is applied when the event source has a split or reverse
  split on that very date (2 cases). All others are excluded (decision 4).
* **The security link is a column, not an identity.** The link is recorded
  in `security_match` (`ticker_text_match` / `unmatched`). Unmatched records
  are stored with `security_id` NULL, never dropped.
* **New incident type `malformed_optional_field`.** It was added in the
  migration's CHECK. Six DS-7 records have a malformed `payment_date` (for
  example `'2025-06-9'`, `'2026-0626'`). The dividend is kept, the field is
  stored as NULL (not repaired), and the raw value is recorded in a warning
  incident.
* **Test isolation, completed.** `tests/test_database.py` used to run
  `alembic upgrade head` against the development database. With the new
  migration present, the first test run applied it there. The schema
  applied is identical to the reviewed migration: `alembic check` is clean,
  and no data or sequence changed. The test now only asserts, read-only,
  that the configured database is at head. Migrations are exercised on
  throwaway databases, including a downgrade/upgrade round trip.

### 6.3 Development loads (2026-09-25)

| Source | Snapshot | Run | Result |
| --- | --- | --- | --- |
| DS-9 `nichsedge-idx-bei` | `…:34903cee…:198092461433733e` | `5dd7e637-55dd-4fce-8de6-a495bf197f2c` | 1,652 events inserted; 924 of 957 tickers linked; 99 records unmatched (tickers absent from Pholenk) |
| DS-7 `dimasirginsyh-idx-dividends` | `…:92115bfb…:7d42f78a5ac90c24` | `0abb038d-9e8c-4e13-a2de-bcd8ed11b85d` | 5,934 dividends inserted; all 602 tickers linked; 6 `malformed_optional_field` warnings |

Both pass `verify_load --deep`, 16/16 each (0 missing, differing, or extra
rows).

### 6.4 Factor build `d1daa2d6-4c74-47eb-aacd-a7e0a6a0e371` (method `ref-v1`)

| Measure | Value |
| --- | --- |
| Anomaly dates | 18 (identical to §2.2) |
| Price factors applied | 212: split 53 (51 + 2 rescued on anomaly dates), rights 39, bonus 13, stock dividend 4, unclassified 103 |
| Price factors excluded (anomaly dates) | 9,909 |
| Cash-dividend factors | 2,202 effective dates from 2,205 dividends; 29 postponed to the next traded day; 1 date merges 4 dividends (GEMS, not traded from 2020-08 until 2021-04-26) |
| Dividends not applied | 3,482 dated before the security's first row; 247 with no traded row afterwards (mostly after 2026-05-29) |
| Securities with factors | 887 |
| Determinism | Factor hash `9cf5e32b…d5b6b1` identical in the dry run, the execute run, and the verify run; `--verify` reports 0 differences |

Validation on the real data (read-only, §3.5):

* BBCA 2021-10-13: the factor is exactly 7,325 / 36,600 (`split`). The
  adjusted series is continuous across the split, and 2020-01-02 adjusts to
  6,694.57.
* EMTK 2021-01-11: factor 0.1 (`unclassified`; DS-9 lacks this split).
  BEKS 2020-12-10: reverse-split factor 10.
* Outside the anomaly dates, 121 daily price returns exceed 35%:
  * 106 are at a reference price of Rp10 or less (tick size);
  * the other 15 are each security's **first** row, an IPO between
    2020-01-09 and 2020-03-09 measured against the offering price (+50% to
    +70%).

  No split, rights, or bonus issue survives as a jump.
* Cumulative total return ≥ price return for all 460 securities with
  applied dividends.
* `daily_prices` is unchanged: `verify_load pholenk` passes 47/47.

### 6.5 Open items for review

1. **22 classified factors on anomaly dates are excluded** (18 rights, 4
   stock dividends; for example FITT 2024-07-01, 0.8957). Some may be genuine
   ex-dates that coincide with a data-shift date. A later method version
   could use a stricter test than the same-day split rule.
2. **92 of the 103 unclassified factors deviate from 1 by more than 2%.**
   They look like real corporate actions missing from DS-9. The other 11 are
   small, and their cause is unknown. All are applied (decision 5).
3. **The anomaly dates are not repaired** (decision 4). Returns on them are
   marked unreliable.
4. **Development heuristics:** the security link is by ticker text, and
   DS-7 amounts are assumed gross.
