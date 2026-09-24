# Market-Data Source Requirements and Provider Research (Q2)

**Status:** Requirements finalized; provider research recorded. **No provider has
been selected.** Phase 2 implementation has **not** started.
**Research date:** all sources below were checked on **2026-09-24** unless stated.
**Governs:** PROJECT_PLAN.md → Phase 2 and open decision Q2.

This document preserves evidence. It deliberately contains **no ranking, score,
winner, or recommendation**. Provider selection is a separate, later decision
that must be made against the requirements below.

---

## 1. Purpose

Phase 2 needs a reproducible, corporate-action-correct daily price history for
Indonesian (IDX) equities. Before any ingestion code is written, this document
records:

* what the project requires from a market-data source, and why;
* the decisions already made by the project owner;
* what each candidate source's own documentation and terms actually say,
  with the URL and date checked;
* what is still unknown.

---

## 2. Project data requirements (why these requirements exist)

Derived from CLAUDE.md:

| CLAUDE.md | Consequence for market data |
| --- | --- |
| §14 Time-series validation | Enough history for time-based and walk-forward splits. |
| §15 / Rule 13 No look-ahead | Every record needs time semantics; the system must know what was knowable when. |
| §16 Survivorship bias | Delisted, suspended, merged, and renamed securities must be in the history. |
| §17 Corporate actions | Raw and adjusted prices must be distinguished; adjustments must be correct. |
| §11, §20 Benchmarks | IHSG history is needed for event studies and backtests. |
| Rules 7–8 | No invented data; no source used before its terms are checked. |

Approximate scale (estimate, not verified): roughly 900+ listed companies,
≈ 1,000–1,300 securities including delisted, ≈ 240 trading days per year —
about 3 million daily rows for ten years. Data volume is small; licensing and
completeness are the hard problems.

---

## 3. Finalized decisions (project owner, 2026-09-24)

| # | Decision |
| --- | --- |
| F1 | **Budget:** to be decided after provider comparison. Cost is **not** a pass/fail requirement. |
| F2 | **Usage:** private/personal initially; deployment to rented cloud/VPS infrastructure is possible later. |
| F3 | **Minimum history:** 2015-01-01 (MUST). ≈ 2005 or earlier is SHOULD. |
| F4 | **Returns:** store **both** price return and total return. |
| F5 | **Multiple sources:** allowed. |

---

## 4. Mandatory requirements (MUST)

| ID | Requirement |
| --- | --- |
| M1 | **Licence:** automated retrieval permitted; permanent PostgreSQL storage permitted; derived data permitted; private single-user use permitted. Record licence URL, version (if any), and date checked. |
| M2 | **Legal access path:** official API, feed, or bulk download. No scraping of consumer websites where prohibited. |
| M3 | **Raw daily OHLCV:** unadjusted; IDX equities; regular market; rupiah; clear date/time semantics (exchange trading date, WIB = UTC+7); documented volume unit (shares vs lots). |
| M4 | **Delisted securities:** history through the final trading day; listing and delisting dates where available. |
| M5 | **Corporate actions** sufficient to build adjustments: splits, reverse splits, bonus shares / stock dividends, rights issues (ratio, exercise price, dates), cash dividends (amount per share, ex-date, record date, payment date where available). |
| M6 | **Stable identifiers:** ISIN or an equivalent stable security ID that survives ticker changes; ticker history with effective dates. |
| M7 | **Trading-status integrity:** distinguish normal trading day / suspended / no trades / missing data. Suspension dates or statuses if available. Requires an IDX trading calendar. |
| M8 | **History depth:** 2015-01-01 onward (F3). |
| M9 | **Automation:** automated daily retrieval; reasonable rate limits; full historical backfill technically feasible; limits and bulk endpoints documented. |
| M10 | **IHSG:** daily IHSG history over the same period (may come from a different source). |
| M11 | **Cash dividends are a hard requirement** (F4): ex-date + gross amount per share, including for delisted securities. |
| M12 | **Per-source vetting** when more than one source is used (see §7). |
| M13 | **Sample accuracy audit** before reliance: cross-check a sample of known corporate actions and delisted tickers against IDX primary disclosures. |

## 5. Should-have requirements (SHOULD)

| ID | Requirement |
| --- | --- |
| S1 | History back to ≈ 2005 or earlier (F3). |
| S2 | Corporate-action **announcement** date (knowledge time), not only ex-date. Becomes MUST if corporate actions are studied as events (Phase 8). |
| S3 | Documented end-of-day publication time. |
| S4 | Correction/revision signals (last-modified, changelog, or as-of versions). |
| S5 | Value traded (IDR), number of trades, regular vs negotiated market separated. |
| S6 | Shares-outstanding history (overlaps Q3). |
| S7 | Wider corporate-action set: mergers, tender offers, go-private, warrants, non-pre-emptive issuance, IPO dates, suspension/delisting reasons. |
| S8 | Vendor adjustment factors for cross-validation only (never the sole source). |
| S9 | Point-in-time sector classification. |
| S10 | Sector index history (overlaps Q5). |
| S11 | Bulk endpoints; full backfill feasible within about a day. |
| S12 | Support channel, versioned schema, bulk export (limits lock-in). |
| S13 | Licence explicitly permits storage/processing on servers rented by the user (F2). **Must be checked now** for every source; required before any cloud deployment. |

## 6. Nice-to-have requirements

History before 2005 · vendor as-of (bitemporal) snapshots · foreign/domestic net
flow · point-in-time index constituents (LQ45, IDX30) · board and special-notation
flags (incl. special monitoring board / full call auction) · auto-rejection
limit-hit flags · intraday/auction prices (not needed for a daily system) ·
third-party redistribution rights · free evaluation tier · push notifications
for new corporate-action announcements.

---

## 7. Multi-source requirements

Because multiple sources are allowed (F5):

1. **Each source is vetted separately** for: licence, legal access, private use,
   storage rights, derived-data rights, cloud/server storage rights, and
   permission to combine with other sources.
2. **Shared identifier key** across sources (ISIN or equivalent), mapped
   point-in-time to tickers.
3. **Every stored record retains its source/provider identity.**
4. **Every stored record retains its retrieval time.**
5. **Source disagreements are logged**, never silently resolved.
6. **No silent merging** of values from different sources.
7. **A source-precedence rule must be established and documented before
   ingestion.** It is intentionally **not** defined here.

A factual framework for defining the rule later (a method, not a rule):

* define precedence **per field** (e.g. close price, dividend amount, ex-date),
  not per provider;
* for each field, record each source's documented provenance (exchange-origin
  vs aggregated), documented IDX coverage, and licence status;
* measure agreement on a reconciliation sample against IDX primary disclosures
  (M13) and record the results;
* choose precedence from that recorded evidence, and document the tie-break
  and the logging behaviour for disagreements.

## 8. Data-integrity requirements (system-side, regardless of provider)

* Store every fetch **raw and immutable**, with source and retrieval time;
  corrections are new versions, never overwrites (CLAUDE.md §15, invariant 6).
* Compute adjustment factors **in-house** from raw prices + corporate actions;
  store the factors; document which series is used for returns, simulation,
  and display (CLAUDE.md §17).
* Maintain a point-in-time ticker ↔ identifier mapping if a source lacks one.
* Classify each security-day as trading / suspended / no trades / missing.
* Validate: gaps against the trading calendar, duplicates, non-positive prices,
  zero-volume runs, jumps not explained by a corporate action.
* Maintain IDX market-structure reference data as a separate, sourced dataset:
  lot size, tick sizes, auto-rejection limits, session hours, settlement cycle.
  These change over time and are **not verified in this document**.

## 9. Return-methodology requirements

* Store **price return** and **total return** separately (F4).
* Price return reflects capital changes (splits, reverse splits, bonus shares /
  stock dividends, rights issues) but **excludes** cash dividends.
* Total return additionally includes cash dividends.
* Dividend amounts are stored **gross**.
* **Modelling assumption (not provider-provided fact):** dividends are
  reinvested at the ex-date. The exact reinvestment price convention is an open
  question (§20).
* The rights-issue adjustment method is an open question (§20).
* Vendor-adjusted series may be used only to cross-check in-house adjustments.

---

## 10. Candidate provider comparison

### Evidence-status legend

| Code | Meaning |
| --- | --- |
| **C** | Confirmed from the provider's own documentation, terms, or API output |
| **ND** | Not documented in the sources checked |
| **U** | Unclear, ambiguous, or contradictory |
| **X** | Unavailable or prohibited per the provider's own terms/docs |
| **S** | Requires contacting sales/provider |
| **I** | Search-engine-indexed text only; page body could not be retrieved |

Bracketed numbers refer to §22.

### Screening-order comparison

| Provider | IDX equities | 1 Licence (private / storage / derived) | 2 Delisted | 3 Raw + corporate actions | 4 Stable IDs | 5 Depth | 6 Automation | 7 Price tiers |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| IDX Data Services (official) | C (I) [1] | Product licence agreement exists (I) [1]; terms S | S | EOD + Historical products (I) [1]; "IDX Data Reference" incl. corporate actions (I) [1]; fields S | S | S | S | Price lists exist [3][4] but not retrievable; S |
| ICE (IDX data) | C [5] | S | ND | EOD + historical C [5]; CA ND | CUSIP/ISIN "may require separate licensing" C [5] | "June 2005" shown for Asia Pacific; IDX-specific U [5] | API, files C [5] | S |
| LSEG | ND for IDX (public pages) [36][37] | S | "152,000 delisted series" globally (I; not in the fetched body of [36]); IDX S | CA + EOD claimed globally (I) [37]; IDX S | S | S | Feeds/APIs/cloud C [36] | S |
| Bloomberg | ND for IDX (public page) [38] | S | S | CA + pricing claimed globally C [38][39]; IDX S | S | "20+ years" (Data License bulk) C [38] | REST, SFTP, cloud C [38] | S |
| FactSet | ND (page body not retrievable) [40] | S | S | CA from 2006 incl. rights/bonus (I) [40] | S | S | API (I) [40] | S |
| S&P Global (Capital IQ Pro / Xpressfeed) | ND for IDX [41] | S | Active + inactive securities (I) [41]; IDX S | Split-adjusted OHLCV + adjustment factor (I) [41] | S | S | Feed (I) [41] | S |
| EODHD | C — JK exchange, 924 active tickers [6] | Personal: may "store, manipulate, and analyze … for private, non-commercial purposes" C [13]; permanence U (see §11) | Delisted list endpoint C [11]; JK delisted count ND; delisting-date field ND [8] | Raw OHLC + `adjusted_close` C [7] (sourcing caveat U, §11); dividends + splits C [9]; rights issues ND | ISIN "where we have one", partial C [11]; rename history US-only [11] | "30+ years" (plan) C [12]; JK start ND | 100k calls/day, 1,000/min; bulk per exchange-day C [10][12] | C [12] |
| Twelve Data | C — XIDX, delay "EOD" [15]; min plan Pro (individual) / Venture (business) [16] | Internal-use licence C; derived data C; **delete within 30 days after termination** C [18] | 180 delisted identifiers listed (observed) C [20]; price history for them ND | `adjust=none` available (default `splits`) C [19]; dividends: `ex_date`, `amount` only C [19]; splits C [19]; rights ND | FIGI in listing C [20]; ISIN via paid add-on C [19] | `earliest_timestamp` endpoint C [19]; XIDX depth ND | Per-minute credits by tier; 5,000 points per request C [17][19] | C [17] |
| Financial Modeling Prep | Individual `.JK` pages exist C [25]; "Global Coverage" only on Ultimate C [22] | Personal licence C; **delete all data on termination** C [23]; derivative-works clause U [23] | "Delisted Companies" endpoint listed C [22]; IDX ND | Unadjusted (split) endpoint C [24]; dividends/splits endpoints listed [22]; IDX CA ND | ND | "Full Historical Access" (Ultimate) C [22]; IDX ND | Up to 3,000 calls/min; bulk (Ultimate) C [22] | C [22] |
| Yahoo Finance | Not assessed | **X** — automated collection prohibited without express prior permission C [26] | — | — | — | — | No official documented data API found; `yfinance` states it is not affiliated with Yahoo [27] | — |
| Sectors (Supertype) | C — IDX focus [28] | ND (pages rate-limited, HTTP 429) [31] | ND | Corporate-actions endpoint (dividends, splits, rights issues) C [29]; daily **OHLC ND** — documented daily data: close, volume, market cap [29][30] | ND | ND | Credits, monthly limits C [29] | ND [31] |
| Invezgo | C — "900+ listed companies" [32] | Website terms: personal, non-commercial; "Don't use bots or similar tools to collect data"; API-specific data licence ND → U [33] | ND | "Full corporate action adjusted price" C [32]; raw prices ND | ND | "since 2009" C [32] | 250–2,000 req/min by plan C [32] | C [32] |
| GoAPI | C — IDX stock API [34] | ND [34] | ND | Historical prices C; CA ND [34] | ND | ND | ND | Free limited quota mentioned; tiers ND [34] |
| OHLC.dev | C — IDX API via RapidAPI [35] | ND; disclaimer: data "may … differ from prices on official exchanges" [35] | ND | "Historical series" C; adjustment/CA ND [35] | ND | ND | ND | Via RapidAPI; ND [35] |

---

## 11. Licensing findings

**IDX Data Services (official).** Products: IDX Market Data, IDX Data Reference,
IDX Publication, IDX Index License, IDX Connection License, offered in real-time,
delayed, end-of-day, and historical formats, with a product licence agreement
(I) [1]. The site and portal returned **HTTP 403** to automated fetches on
2026-09-24 [1][2]; licence text was **not read**. Whether an individual may
license EOD/historical data, and on what storage/derived/cloud terms: **S**.

**EODHD** [13][14].
* Non-Professional (personal) users "are permitted to store, manipulate, and
  analyze the data for private, non-commercial purposes", and are prohibited
  from "Selling, reselling, retransmitting, redistributing, displaying, or
  granting access to the Information or Services, whether in its original or
  repackaged form" (C [13]).
* Plans on the pricing page are "intended for personal use only"; commercial
  use needs a separate plan (C [12][14]).
* **Contradiction / U:** search-engine-indexed text attributes to the Terms page
  a clause that data "may be stored on the subscriber's premises" during the
  subscription and must be deleted within one month of termination. That clause
  is **not present** in the Terms page text retrieved on 2026-09-24 [13]. The
  current terms page carries no version date. Whether storage may continue after
  a subscription ends is therefore **unclear** and needs written confirmation.
* **Contradiction / U (data provenance):** the EOD docs describe OHLC as "raw —
  the prices as they printed on the tape" [7], while the Terms state: "We are
  not using exchanges data feeds for the pricing data, we are using OTC, peer to
  peer trades and trading platforms over 100+ sources, we are aggregating our
  data feeds via VWAP method" and that prices "are indicative and not
  appropriate for trading purposes" [13]. Whether JK prices are exchange-origin
  is unclear.

**Twelve Data** [18] (Terms of Use, last updated 2026-01-01).
* Licence to "Access, receive, process, and store Data solely for Internal Use"
  (§2.2(a)); "Create Derived Data that cannot be reverse-engineered to recreate
  the original Data" (§2.2(c)).
* Prohibited: "Store or cache Data beyond permitted timeframes specified in the
  Documentation" (§2.3(g)); "Create derivative financial products without
  explicit written permission" (§2.3(f)).
* **Retention:** "Upon termination or expiration: (a) All Data must be deleted
  within 30 days" (§16.2). Permanent storage after termination is therefore
  **not permitted** under these terms. The "permitted timeframes specified in
  the Documentation" were **not located** (U).

**Financial Modeling Prep** [23] (Terms of Service, last updated 2023-08-01).
* Personal licence "strictly for their own personal, non-business and
  non-commercial purposes" (§2.2.1).
* §6.3: "Upon termination of this Agreement, Customer must delete all Data it
  has received from FMP … including data cached". §6.2 extends destruction to
  data "contained in or derived from The Services". Permanent storage after
  termination and retention of derived data are therefore **not permitted**.
* §2.6.1(ii) prohibits preparing "derivative works from … The Services";
  whether this covers derived analytics is **ambiguous (U)**.

**Yahoo** [26] (Terms of Service, last updated 2025-05-06).
* §2.4(i): users may not "access or collect data … from our Services using any
  automated means … for any purpose without our express, prior permission."
  Automated retrieval is **prohibited (X)** without permission. Unofficial
  wrappers (e.g. `yfinance`) are "not affiliated, endorsed, or vetted by Yahoo"
  [27] and are not treated as a licensed API.

**Invezgo** [33]. The terms found are website terms ("You can print or save it
for personal, non-commercial use only … Don't use bots or similar tools to
collect data … Each subscription is for one person"). No API-specific data
licence was found; how these clauses apply to the paid API is **unclear (U)**.
The API page names "Official IDX REST API" as a source [32]; an IDX licence for
redistribution is **not documented**.

**Sectors, GoAPI, OHLC.dev.** No data licence text was retrieved (Sectors pages
returned HTTP 429; GoAPI terms page yielded no data-licence clauses; OHLC.dev
links to terms not reviewed). **ND.**

**LSEG, Bloomberg, FactSet, S&P Global.** Enterprise agreements; public pages
contain no licence terms for individuals. **S.**

## 12. Pricing findings

Prices as displayed on 2026-09-24; not a comparison of value.

| Provider | Free tier | Paid tiers (as displayed) | Billing | Limits | Notes |
| --- | --- | --- | --- | --- | --- |
| IDX Data Services | 1-month free trial for real-time data (I) [1] | Price lists 2021, 2022, 2024 exist [3][4]; not retrievable | S | S | Security deposit "300% of the Subscription Fee" (I) [1] |
| EODHD [12] | $0: 20 calls/day, past year, EOD only | All World $19.99/mo or $199/yr (EOD, splits/dividends, adjusted, delisted); All World Extended $29.99/mo; Fundamentals $59.99/mo; All-In-One $99.99/mo | Monthly or yearly; minimum one month | 100,000 calls/day; 1,000/min (paid) | Personal use only; commercial plans separate. **U:** JK page says "All World Extended package and higher" for the trading-hours API [6]; exchanges docs say that API is in all plans [11] |
| Twelve Data [16][17] | Basic: 8 credits/min, 800/day, 3 exchanges | Grow $79/mo ($790/yr); **Pro** $229/mo ($2,290/yr) as displayed; Ultra $999/mo ($9,990/yr); business plans separate | Monthly or annual | API credits **per minute**; Pro offered at 610 / 987 / 1,597 credits/min (U: which price applies to which variant) | XIDX needs **Pro** (individual) / **Venture** (business) [16]; ISIN is a paid add-on; FIGI parameter on Ultra [19] |
| FMP [22] | Basic: 250 calls/day | Starter $19/mo (US, 5 yrs); Premium $49/mo (US/UK/Canada, 30 yrs); **Ultimate $99/mo** ("Global Coverage", "Full Historical Access", bulk) | Prices shown "billed annually" | 300 / 750 / 3,000 calls per minute | Personal vs commercial pricing pages separate |
| Invezgo [32] | 1-month trial | Advance IDR 499,900/mo; Prime IDR 999,000; Max IDR 1,999,900; Elite IDR 4,000,000 | Monthly | 250–2,000 req/min; 30,000–320,000 req/month | "99.9% Uptime SLA" claimed |
| GoAPI [34] | "Free" with limited quota | ND | ND | ND | — |
| Sectors [28][31] | ND | ND (pricing page HTTP 429) | ND | Credits + monthly limit [29] | Enterprise plans via contact |
| OHLC.dev [35] | ND | Via RapidAPI; ND | ND | ND | — |
| LSEG, Bloomberg, FactSet, S&P, ICE | — | **S** (contact sales) | S | S | Enterprise/contact-sales only |

Whether older history, delisted data, corporate actions, cloud use, or
redistribution cost extra: EODHD's All World plan lists delisted data and
splits/dividends as included [12]; Twelve Data's IDX access requires the Pro
tier and ISIN an add-on [17][19]; FMP's global coverage requires Ultimate [22];
all others **ND** or **S**.

## 13. Delisted-coverage findings

* **EODHD:** `delisted=1` returns "only tickers that are no longer traded" (C
  [11]); "Delisted symbols retain their full history" (C [7]). A delisting-date
  field is **not documented** [8]. The delisted page states "After 2018: EOD,
  Fundamentals, Dividends and Splits" and "Before 2018: EOD only" [8]; whether
  this refers to delisting year or data date is **unclear**. If it means no
  dividends for pre-2018 delistings, M11 would be affected. JK delisted count:
  **ND**.
* **Twelve Data:** `/stocks?mic_code=XIDX` returned **944** symbols; with
  `include_delisted=true` it returned **1,124** (observed 2026-09-24 via the
  documented reference endpoint with the public demo key) [20]. Whether price
  history exists for the 180 additional identifiers: **ND**.
* **FMP:** a "Delisted Companies" endpoint is listed [22]; IDX coverage **ND**.
* **All others:** ND or S.

## 14. Corporate-action findings

* **EODHD [9]:** dividends return `date` (ex-date), `value` (split-adjusted),
  `unadjustedValue`, `currency`; extended fields `declarationDate`,
  `recordDate`, `paymentDate`, `period` have "varying coverage". Coverage is
  documented as substantially complete for US/Canada and sparse for several
  Asian markets; **Indonesia is not named (ND)**. Splits are `new/old` ratios,
  including reverse splits and stock dividends as non-standard ratios. Rights
  issues as a distinct event type: **ND**.
* **Twelve Data [19]:** dividends: `ex_date`, `amount` only — **no record or
  payment date**. Splits: `date`, `description`, `ratio`, `from_factor`,
  `to_factor`. Rights issues: **ND**.
* **FMP [22][24]:** dividend and split endpoints listed; an "Unadjusted Stock
  Price" endpoint provides prices "without adjustments for stock splits".
  IDX CA coverage **ND**.
* **Sectors [29]:** endpoint `v2/company/corporate-actions/{symbol}` covering
  "Dividends, stock splits, rights issues, and other corporate actions"
  (added 2026-06-12). Fields **ND**.
* **Invezgo [32]:** prices are "Full corporate action adjusted"; raw prices and
  CA event records **ND**.
* **IDX Data Reference [1]:** includes corporate actions (I); fields **S**.
* **Institutional:** Bloomberg "more than 50 action types" (I) [39]; FactSet
  CA from 2006 incl. rights and bonus issues (I) [40]; IDX coverage **S**.

## 15. Identifier findings

* **EODHD:** symbol list includes `Isin` "where we have one. Coverage is
  partial" [11]. Symbol-rename history is documented **for US only** [11].
* **Twelve Data:** listing includes `figi_code` (e.g. AADI → `BBG01QSN4LX3`,
  observed [20]); ISIN returned as `request_access_via_add_ons` without the
  add-on [20]; ticker-change history **ND**.
* **ICE:** "CUSIP & ISIN … may require separate licensing" [5].
* **All others:** ND or S.

No candidate documented IDX ticker-change history with effective dates.

## 16. History-depth findings

| Provider | Finding |
| --- | --- |
| EODHD | Plan: "30+ years" [12]; JK start date ND |
| Twelve Data | Per-instrument `earliest_timestamp` endpoint [19]; XIDX depth ND |
| FMP | Ultimate: "Full Historical Access" [22]; IDX depth ND |
| Invezgo | "since 2009" [32] (meets F3 MUST if accurate; not S1) |
| ICE | "June 2005" shown in an Asia-Pacific context; IDX-specific U [5] |
| Bloomberg | Data License bulk: "20+ years of history" [38]; IDX ND |
| Others | ND / S |

## 17. Automation / rate-limit findings

* **EODHD:** 100,000 calls/day and 1,000 requests/minute on paid plans [12];
  every request (including 404) costs one call [7]; bulk endpoint returns a
  whole exchange for one day for a flat 100 calls, including historical dates
  [10].
* **Twelve Data:** credits per minute by tier [17]; `time_series` returns up to
  5,000 points per request [19].
* **FMP:** 300 / 750 / 3,000 calls per minute by tier; bulk delivery on
  Ultimate [22].
* **Invezgo:** 250–2,000 requests/minute and 30,000–320,000 requests/month by
  plan [32].
* **Sectors:** credit-based with a monthly limit and HTTP 429 on excess [29][30];
  the retired v1 daily endpoint was limited to 90-day windows [30].
* **IDX / institutional:** S.

## 18. Cloud / server-storage findings

"Private use" is **not** assumed to permit storage on rented servers.

| Provider | Finding |
| --- | --- |
| IDX Data Services | S |
| EODHD | Current terms do not address servers/cloud [13]; an indexed earlier clause refers to "subscriber's premises" (I). **U** |
| Twelve Data | "Authorized User" includes "computerized systems expressly authorized by Customer" [18]; cloud/rented servers not addressed. **U** |
| FMP | §2.8: "Customer will notify FMP of the IP and domain aliases of any location where data is stored or processed" [23]; implies notification duty; explicit permission for rented cloud not stated. **U** |
| Invezgo, Sectors, GoAPI, OHLC.dev | ND |
| LSEG, Bloomberg, FactSet, S&P, ICE | Cloud delivery offered commercially [36][38]; licence terms S |
| Yahoo | Not applicable (automated collection prohibited) |

## 19. Source-combination findings

| Provider | Finding |
| --- | --- |
| Twelve Data | Prohibited: "Combine Data with other sources to create competing products without permission" (§2.3(k)) [18]. Combination for non-competing internal use is not addressed by this clause. |
| EODHD | Not addressed in current terms [13]. **ND** |
| FMP | Not addressed specifically; derivative-works restriction ambiguous [23]. **U** |
| Others | ND or S |

---

## 20. Open questions

**Project-level (to decide before ingestion)**
1. Source-precedence rule per field (§7).
2. Total-return reinvestment price convention (e.g. ex-date close) — assumption
   to document.
3. Rights-issue adjustment method.
4. Source of IDX market-structure reference data (lot size, tick size,
   auto-rejection limits, sessions, settlement) — to be verified against IDX
   primary sources.
5. IHSG source (M10) — Twelve Data lists `JKSE` "Jakarta Composite Index" in its
   reference data (observed [21]); other providers ND.
6. Budget (F1).

**Per provider (to confirm in writing)**
* **IDX:** individual eligibility; EOD/historical and Data Reference licence
  terms (storage, derived, cloud, retention after termination); delisted
  coverage; corporate-action fields; delivery method; price.
* **EODHD:** post-termination retention (§11 contradiction); rented-server
  storage; exchange-origin vs aggregated JK prices; JK start date; JK delisted
  coverage; dividend record/payment-date coverage for JK; rights issues; plan
  needed for trading-hours/holiday API.
* **Twelve Data:** "permitted timeframes" for storage; delisted XIDX price
  history; XIDX depth; Pro variant prices; ISIN add-on cost; rights issues;
  rented-server storage.
* **FMP:** IDX coverage scope on Ultimate; `.JK` delisted and CA coverage;
  scope of the derivative-works clause.
* **Sectors / Invezgo / GoAPI / OHLC.dev:** raw OHLCV availability, licence
  terms, delisted coverage, history depth, whether they hold an IDX
  redistribution licence.
* **LSEG / Bloomberg / FactSet / S&P / ICE:** IDX coverage, delisted coverage,
  individual eligibility, price.

## 21. Research date

All findings: **2026-09-24**. Terms change; re-check each source's terms at
selection time and record the version read.

Retrieval notes (2026-09-24):
* idx.co.id and data.idx.co.id returned HTTP 403 to automated requests
  (including robots.txt); no attempt was made to bypass this.
* sectors.app returned HTTP 429.
* FactSet developer/marketplace pages returned no body text (client-rendered).
* Items marked **I** come from search-engine-indexed text that the search
  engine attributed to the cited URL; the page body itself was not read or did
  not contain the text. Treat **I** items as unverified until confirmed.

## 22. Source links

| # | Source | URL |
| --- | --- | --- |
| 1 | IDX Data Services (HTTP 403; I) | https://www.idx.co.id/en/products/idx-data-services/ |
| 2 | IDX Data Services Portal (HTTP 403) | https://data.idx.co.id/ |
| 3 | IDX Data Service Catalogue & Pricelist 2024 (HTTP 403) | https://www.idx.co.id/media/2qalvu4z/20240923_idx-data-catalogue-pricelist-2024.pdf |
| 4 | IDX Pricelist Oct 2022 (HTTP 403) | https://www.idx.co.id/media/20221218/20221026_pricelist-non-ab_updated-october-2022.pdf |
| 5 | ICE — Indonesia Stock Exchange (IDX) | https://developer.ice.com/fixed-income-data-services/catalog/indonesia-stock-exchange-idx |
| 6 | EODHD — JK exchange | https://eodhd.com/exchange/JK |
| 7 | EODHD — End-of-day API | https://eodhd.com/financial-apis/api-for-historical-data-and-volumes |
| 8 | EODHD — Delisted companies | https://eodhd.com/financial-apis/delisted-stock-companies-data-2 |
| 9 | EODHD — Splits & dividends | https://eodhd.com/financial-apis/api-splits-dividends |
| 10 | EODHD — Bulk API | https://eodhd.com/financial-apis/bulk-api-eod-splits-dividends |
| 11 | EODHD — Exchanges & ticker lists | https://eodhd.com/financial-apis/exchanges-api-list-of-tickers-and-trading-hours |
| 12 | EODHD — Pricing | https://eodhd.com/pricing |
| 13 | EODHD — Terms and Conditions (no version date) | https://eodhd.com/financial-apis/terms-conditions |
| 14 | EODHD — Commercial vs personal use | https://eodhd.com/financial-apis/commercial-vs-personal-license-use |
| 15 | Twelve Data — XIDX | https://twelvedata.com/exchanges/xidx |
| 16 | Twelve Data — Exchanges (plan per exchange) | https://twelvedata.com/exchanges |
| 17 | Twelve Data — Pricing | https://twelvedata.com/pricing |
| 18 | Twelve Data — Terms of Use (last updated 2026-01-01) | https://twelvedata.com/terms |
| 19 | Twelve Data — OpenAPI specification | https://api.twelvedata.com/doc/swagger/openapi.json |
| 20 | Twelve Data — `/stocks` reference (XIDX, delisted) | https://api.twelvedata.com/stocks?mic_code=XIDX&include_delisted=true&show_plan=true |
| 21 | Twelve Data — `/indices` reference (Indonesia) | https://api.twelvedata.com/indices?country=Indonesia |
| 22 | FMP — Pricing plans | https://site.financialmodelingprep.com/pricing-plans |
| 23 | FMP — Terms of Service (last updated 2023-08-01) | https://site.financialmodelingprep.com/terms-of-service |
| 24 | FMP — EOD / unadjusted price docs | https://site.financialmodelingprep.com/developer/docs/stable/historical-price-eod-full |
| 25 | FMP — example `.JK` page | https://site.financialmodelingprep.com/financial-summary/TKIM.JK |
| 26 | Yahoo — Terms of Service (last updated 2025-05-06) | https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html |
| 27 | yfinance documentation | https://ranaroussi.github.io/yfinance/ |
| 28 | Supertype — Sectors | https://supertype.ai/products/sectors |
| 29 | Sectors API v2 changelog | https://docs.sectors.app/api-references/v2/changelog |
| 30 | Sectors — Daily transaction (v1, retired 2026-05-11) | https://docs.sectors.app/api-references/transaction/daily-transaction |
| 31 | sectors.app / pricing (HTTP 429) | https://sectors.app/pricing |
| 32 | Invezgo — Indonesia stock API | https://invezgo.com/data-api-saham-indonesia |
| 33 | Invezgo — Terms | https://invezgo.com/terms |
| 34 | GoAPI — IDX stock API / terms | https://goapi.io/api-data-saham-indonesia/ · https://goapi.io/terms/ |
| 35 | OHLC.dev — IDX API | https://ohlc.dev/indonesia-stock-exchange-idx-api |
| 36 | LSEG — Exchange Traded Instruments | https://www.lseg.com/en/data-analytics/financial-data/pricing-and-market-data/exchange-traded-instruments-eti |
| 37 | LSEG — DataScope Select | https://www.lseg.com/en/data-analytics/products/datascope-select-data-delivery |
| 38 | Bloomberg — Data License | https://professional.bloomberg.com/products/data/data-license/ |
| 39 | Bloomberg — Reference data | https://professional.bloomberg.com/products/data/enterprise-catalog/reference/ |
| 40 | FactSet — Global Prices API (body not retrievable) | https://developer.factset.com/api-catalog/factset-global-prices-api |
| 41 | S&P Capital IQ Pro / Xpressfeed coverage | https://pages.marketintelligence.spglobal.com/SP-Capital-IQ-Pro-Data-Coverage.html |
