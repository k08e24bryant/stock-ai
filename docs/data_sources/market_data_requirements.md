# Market-Data Source Requirements and Provider Research (Q2)

**Status:** Requirements finalized; provider research (round 1) and validation
(round 2) recorded. **No production provider has been selected.** Production
readiness: **BLOCKED** (§32). **$0 development mode** (2026-09-24): public
development data sources are recorded in §36; they do not satisfy production
requirements. Phase 2 implementation has **not** started.
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
   ingestion.** A proposed rule is documented in §21; it is not yet adopted.

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
  reinvested at the close of the ex-date (§24).
* The rights-issue methodology is proposed in §25; the out-of-the-money case
  and the backtest treatment are still open (§33).
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

Bracketed numbers refer to §35.

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

## 20. Validation round 2 — scope and method

Date: **2026-09-24** (same day as round 1). Sections 10–19 remain the round-1
record; where round 2 adds or corrects evidence, sections 21–33 take precedence.

Scope: resolve the project-level questions (precedence, dividend reinvestment,
rights issues, IDX trading rules, IHSG) and validate each candidate field by
field. Method: provider documentation and terms; official regulator/exchange
documents where reachable; published index-provider methodologies; two
documented reference endpoints queried with public demo keys. **No account was
opened, no paid data was retrieved, and no provider was contacted.** Anything
that needs a provider account or written confirmation remains open.

Additional status label used from here on:

* **UNCLEAR — requires written provider confirmation.** The terms are silent or
  ambiguous. Permission is **not** inferred.

---

## 21. Source-precedence rule (proposed)

This is a **documented proposal**, to be adopted (or amended) before ingestion.
It is deterministic and field-specific; it never ranks providers globally.

### 21.1 Evidence tiers (per field, per source)

| Tier | Definition | Examples |
| --- | --- | --- |
| T1 | Official primary record for that field | IDX official close; issuer/KSEI/IDX corporate-action terms; IDX regulations for trading rules; IDX listing, delisting, and suspension announcements |
| T2 | Licensed vendor data whose documentation states it is exchange-originated **for IDX** | none confirmed as of 2026-09-24 |
| T3 | Licensed vendor data that is aggregated or derived, or whose IDX provenance is undocumented | e.g. EODHD's terms describe VWAP aggregation from non-exchange sources [13] |
| X | Unlicensed, unofficial, or scraped where prohibited | never ingested |

A source's tier is assigned **per field** from recorded evidence (a vendor can
be T2 for closes and T3 for dividends), and stored with a reference to that
evidence.

### 21.2 Ordered rules

For a given security, field, and effective date:

1. **Raw beats derived.** A raw observation (e.g. unadjusted close, announced
   dividend amount) always outranks a vendor-derived value (adjusted close,
   split-adjusted dividend). Derived vendor values are used only to cross-check
   in-house calculations.
2. **Lower tier number wins** (T1 > T2 > T3).
3. **Corporate-action terms come from the announcement.** Ratio, exercise
   price, amount, and dates are taken from the issuer/KSEI/IDX announcement
   (T1) where available; a vendor's reconstructed ratio never overrides
   announced terms.
4. **Versioned beats unversioned; later correction from the same source
   supersedes its earlier version.** Both versions are kept; the earlier one is
   marked superseded, never deleted.
5. **Point-in-time rule for historical use.** For backtests and features, only
   observations whose availability time ≤ decision time are eligible. A better
   source arriving later does not rewrite what the system "knew" earlier; the
   resolution is computed as of each decision time (bitemporal: effective time
   and knowledge time).
6. **Fixed tie-break.** If sources remain tied, a pre-declared, versioned
   source order **per field** decides. The order is configuration, recorded in
   the repository, and changed only by an explicit, dated decision.
7. **Traceability.** Every resolved value references the winning observation
   and lists the losing observations.

### 21.3 Preconditions before the rule can be finalized

* Tier assignments need evidence per field and source (sections 28–30).
* Tie-break orders need the reconciliation sample (M13).
* Rule 5 needs availability timestamps; where a source provides none, the
  retrieval time is the conservative availability time (§22).

---

## 22. Provenance requirements (every ingested record)

Documentation only; no tables are defined here.

| Field | Mandatory | Meaning |
| --- | --- | --- |
| `source_id` | **Yes** | Provider/dataset identifier (e.g. provider + endpoint/dataset name) |
| `source_security_id` | **Yes** | The identifier the source used (ticker, vendor ID, FIGI, ISIN) exactly as received |
| `retrieved_at` | **Yes** | UTC timestamp when the record was fetched |
| `ingestion_run_id` | **Yes** | Identifier of the ingestion run that produced it |
| `raw_record_ref` | **Yes** | Pointer to the immutable raw payload (storage key/URI) plus a content checksum |
| `licence_ref` | **Yes** | Licence/terms version under which the record was obtained (URL + date read) |
| `parser_version` | **Yes** | Version of the code that parsed the raw payload |
| `revision_status` | **Yes** | `original` / `correction` / `superseded`, with a link to the prior version |
| `available_at` | **Yes** (with fallback) | When the information was public. If the source gives no timestamp, use `retrieved_at` and flag `available_at_is_fallback = true` |
| `source_timestamp` | Optional | Any as-of/last-modified time supplied by the source |
| `published_at` | Optional (mandatory for corporate actions **when obtainable**) | Announcement/publication time of the underlying event |
| `source_version` | Optional | Source-provided version, changelog entry, or API version |
| `request_params` | Optional | Parameters used for the request, for reproducibility |

Rationale: CLAUDE.md §15 (time semantics), §16 (survivorship), invariant 6
(raw vs derived), and the multi-source rules in §7.

**Superseded for daily prices by the
[Phase 2B Data Contract](phase_2b_data_contract.md) (2026-09-24):** the
`available_at` fallback to `retrieved_at` is not used — historical availability
is recorded as unknown unless an authoritative timestamp exists; `retrieved_at`
and licence/parser metadata live at snapshot level; rows reference a
deterministic snapshot, while `ingestion_run_id` identifies each loader
execution.

---

## 23. Disagreement handling

Documentation only.

**Procedure (for every field with more than one observation):**

1. **Detect**: compare observations for the same security, field, and
   effective date after unit normalization (currency, shares vs lots,
   split-adjusted vs raw). Tolerances are per field and must be defined before
   ingestion; until then the default is **exact equality** after normalization.
2. **Preserve**: keep every observation. Nothing is overwritten or deleted.
3. **Record provenance** for each observation (§22).
4. **Apply precedence** (§21) to produce the resolved value.
5. **Flag**: write a disagreement record (field, sources, values, rule applied,
   resolution) and surface it in validation reports.
6. **Never silently overwrite** the losing observation.

**Examples**

| Disagreement | Handling notes |
| --- | --- |
| OHLC differs | Check whether one source is adjusted and the other raw before flagging. Prefer the T1 official close; otherwise rules 2–6. |
| Volume differs | Normalize units (shares vs lots; IDX lot = 100 shares since 2014-01-06, §26) and market scope (regular vs negotiated) first. |
| Dividend amount differs | Compare gross vs net and split-adjusted vs unadjusted first. Announced gross amount (T1) wins. |
| Corporate-action date differs | Distinguish cum/ex/recording/payment dates before flagging. Announcement terms (T1) win; flag for manual review because a date error shifts the adjustment. |
| Ticker mapping differs | Never auto-resolve. Map through the stable identifier; flag for manual review with effective dates. |

---

## 24. Total-return and dividend-reinvestment convention

**Evidence from published index methodologies:**

* MSCI (Index Calculation Methodology, August 2025): "Daily Total Return (DTR)
  methodology reinvests regular cash distributions in indexes on the ex-date of
  such distributions." It also states that if a security does not trade on the
  ex-date, "the reinvestment is postponed to the day when the security resumes"
  trading (§2.2.1, "Timing of Reinvestment"). **C** [50]
* S&P Dow Jones Indices (Index Mathematics, April 2026): total return
  counterparts assume "dividends are reinvested in the index after the close on
  the ex-date". **I** — the PDF returned HTTP 403 [51].

**Project convention — a MODELLING ASSUMPTION, not provider-supplied data:**

* The gross cash dividend with ex-date *t* is reinvested at the **close of the
  ex-date**, i.e. the ex-date total return is
  `(P_t + D_t) / P_{t-1} − 1`, where `P` are raw closes put on a comparable
  basis for any capital change between *t−1* and *t*, and `D_t` is the gross
  dividend per share.
* This matches the MSCI convention [50] and, if confirmed, the S&P DJI
  convention [51].
* Reinvesting "at the ex-date adjusted price" is not a separate convention: a
  dividend-adjusted series built with the same ex-date factor produces the same
  return. The adjusted series is derived from this convention, not an
  alternative to it.
* If the security is suspended on the ex-date, reinvestment is postponed to the
  next trading day (following MSCI [50]). **Assumption.**
* Amounts are gross (F4). Withholding tax is not modelled. MSCI's net indexes
  use a withholding rate for Indonesia [50]; a net variant is out of scope.

---

## 25. Rights-issue methodology

**Evidence:**

* MSCI: "the adjustment for a rights issue is always theoretical (the intrinsic
  value of the right is the difference between the underlying stock price and
  the subscription price), even if the rights will list on an exchange"; its
  event table uses a "Theo-ex price taking into account the terms of the event".
  **C** [50]
* Indonesian rights issues (HMETD) are governed by POJK 32/POJK.04/2015 as
  amended by POJK 14/POJK.04/2019 [52][53] (identified on ojk.go.id; full text
  not reviewed in this round).
* KSEI announces HMETD schedules. Search-indexed text lists cum date, ex date,
  recording date, distribution date, and rights trading start and end.
  **I** — the KSEI pages returned HTTP 404/500 on 2026-09-24 [54][55].

**Proposed methodology (documentation only; nothing implemented):**

| Use | Treatment |
| --- | --- |
| Adjusted historical prices | Theoretical ex-rights price (TERP), consistent with MSCI [50]. With *M* old shares entitled to *N* new shares at subscription price *S* and cum-rights close *P*: `TERP = (M·P + N·S) / (M + N)`. Price-adjustment factor for pre-ex-date prices = `TERP / P`. |
| Total return | The same factor applied on the ex-date, so a holder's value is preserved at the theoretical value of the right. **Assumption.** |
| Backtesting | **Open decision:** (a) theoretical treatment (as indexes do), or (b) explicit HMETD handling: rights received, then exercised (requires cash) or sold at observed rights prices. (b) needs rights-security price history. |
| Valuation | Per-share fundamentals (EPS, BVPS, DPS) rescaled by the same factor so they align with the adjusted price history. |
| Event studies | Rights ex-dates inside an event window are flagged as confounding events; announcement time comes from the issuer/KSEI disclosure. |

**Open:** treatment when `S ≥ P` (rights out of the money). The MSCI text
reviewed does not address it (no match for "in the money"). Must be decided
before implementation.

**Data required per rights issue (primary sources: issuer prospectus/disclosure,
KSEI, IDX):** ratio (old : new), subscription price, cum date (regular and cash
market), ex date, recording date, rights distribution date, rights trading
period, exercise period, new-share listing date, rights ticker, announcement
date/time.

**Provider coverage:** no candidate vendor documents these fields (§29). Sectors
lists rights issues as covered but documents no fields [29].

---

## 26. IDX trading rules — sources and verification status

IDX regulation pages and PDFs returned HTTP 403 to automated requests; this was
not bypassed. Status labels: **VERIFIED-PRIMARY** (official document read),
**VERIFIED-COPY** (full text of an official document read from a third-party
copy), **SECONDARY** (reputable secondary text read), **I** (search-indexed
only).

| Rule | As documented | Effective | Source | Status |
| --- | --- | --- | --- | --- |
| Lot size | 1 round lot = **100** shares (previously 500) | 2014-01-06 | Kep-00071/BEI/11-2013, issued 2013-11-08 [43] | VERIFIED-COPY |
| Tick size (2014) | < Rp500: Rp1; Rp500–<Rp5,000: Rp5; ≥ Rp5,000: Rp25 | 2014-01-06 | Kep-00071/BEI/11-2013 [43] | VERIFIED-COPY. A search summary stated Rp10 for the middle band, which contradicts the document. |
| Tick size (2016) | < Rp200: Rp1; Rp200–500: Rp2; Rp500–2,000: Rp5; Rp2,000–5,000: Rp10; > Rp5,000: Rp25 | Effective date not verified | Cites Kep-00023/BEI/04-2016 [45] | SECONDARY |
| Price limits (2020–2023) | ARA 35% / 25% / 20% by price band (Rp50–200 / >200–5,000 / >5,000); ARB 7% | until 2023-05-31 | [46] | SECONDARY |
| Price limits (phase I) | ARB 15%, ARA unchanged | 2023-06-05 | [46] | SECONDARY |
| Price limits (phase II) | Symmetric: ARB = ARA per band (35% / 25% / 20%) | 2023-09-04 | [46]; Peraturan II-A Kep-00055/BEI/03-2023 identified [44] | SECONDARY; official PDF 403 |
| Price limits (2025) | ARB **15%** for all price ranges (Main, Development, New Economy boards; ETFs; REITs); IHSG trading-halt thresholds 8% and 15%, suspension at 20% | 2025-04-08 | Kep-00002/BEI/04-2025 and Kep-00003/BEI/04-2025 as reported by [47] | SECONDARY |
| Trading sessions | Conflicting: Mon–Thu 09:00–12:00 & 13:30–15:49, Fri 09:00–11:30 & 14:00–15:49 WIB [15]; other secondary text differs | varies by period | IDX page identified [48] | UNVERIFIED — conflicting |
| Closing price | Closing-auction price; auction results 16:00–16:05 JKT; closes available 16:15 | as of Aug 2025 | MSCI Appendix VII [50] | SECONDARY (verified text) |
| Trading calendar | 2026 calendar published as Peng-00171/BEI.POP/09-2025 | 2026 | IDX PDF identified [49] | I — 403. Calendars for 2015–2025 are needed. |
| Settlement | T+2: first T+2 trade date 2018-11-26 (last T+3 trade date 2018-11-23; first T+2 settlement 2018-11-28) | 2018-11-26 | OJK press release SP 80/DHMS/OJK/XI/2018 [42] | **VERIFIED-PRIMARY** |

Notes:

* Within the required window (2015-01-01 onward) the lot size is 100 shares.
  No later change was found in the sources checked; that is not proof that none
  exists.
* Price limits, tick sizes, and sessions changed several times inside the
  window. A time-versioned reference dataset built from the official decisions
  is required, and each row must be verified against the official text.

---

## 27. IHSG source analysis

| Candidate | Evidence IHSG exists | 2015+ history verified | Date semantics | Storable (licence) | Status |
| --- | --- | --- | --- | --- | --- |
| IDX (index owner) | "IDX Index License" product listed (I) [1] | S | S | S | UNVERIFIED |
| Twelve Data | `JKSE` "Jakarta Composite Index", IDR, XIDX in reference data (observed) [21] | **No** — `earliest_timestamp` with the demo key returned 401 [58] | Local exchange time per API schema [19] | Deletion within 30 days after termination (§16.2) [18] | NOT VERIFIED; permanent storage not permitted |
| EODHD | Index tickers use the `.INDX` suffix; `JKSE.INDX` is not in the EODHD docs checked | **No** — demo request returned "Forbidden" [59] | Trading day, local time (generic) [7] | UNCLEAR [13] | NOT VERIFIED |
| FMP | Generic index-history endpoints exist; `^JKSE` not documented | No | ND | Deletion on termination [23] | NOT VERIFIED |
| LSEG / Bloomberg / FactSet / S&P / ICE | Not documented publicly | S | S | S | UNVERIFIED |
| Yahoo | — | — | — | Automated collection prohibited [26] | EXCLUDED |

IHSG is an IDX index. Whether any vendor holds the licence needed to deliver
IHSG values for storage is **not documented** and must be confirmed.
**No candidate currently satisfies M10 with evidence.**

---

## 28. Per-provider validation

### 28.1 Licensing

Legend: **Yes (C)** confirmed by terms · **No (X)** prohibited by terms ·
**UNCLEAR** = UNCLEAR — requires written provider confirmation ·
**n/a** not applicable.

| Question | EODHD (personal) | Twelve Data (individual) | FMP (personal) | Yahoo | Invezgo | Sectors / GoAPI / OHLC.dev | IDX, ICE, LSEG, Bloomberg, FactSet, S&P |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Automated retrieval | Yes (C) — API plans [12] | Yes (C), within rate limits (§2.3(h)) [18] | Yes (C) — API plans [22] | **No (X)** §2.4(i) [26] | UNCLEAR — site terms: "Don't use bots" [33]; API product exists [32] | UNCLEAR | UNCLEAR |
| Permanent storage | UNCLEAR [13] | **No (X)** after termination (§16.2) [18] | **No (X)** after termination (§6.3) [23] | n/a | UNCLEAR | UNCLEAR | UNCLEAR |
| Storage after termination | UNCLEAR — indexed deletion clause vs current terms [13] | **No (X)** — delete within 30 days [18] | **No (X)** — delete incl. cached [23] | n/a | UNCLEAR | UNCLEAR | UNCLEAR |
| Derived data | UNCLEAR — "manipulate, and analyze" permitted; derived data not defined [13] | Yes (C) if not reverse-engineerable (§2.2(c)); retention after termination UNCLEAR [18] | UNCLEAR during subscription (§2.6.1(ii)); **No (X)** after termination (§6.2) [23] | n/a | UNCLEAR | UNCLEAR | UNCLEAR |
| Private use | Yes (C) [13] | Yes (C) — "personal, internal, and non-commercial" [17] | Yes (C) §2.2.1 [23] | n/a | Yes (C), website terms [33] | UNCLEAR | UNCLEAR |
| Cloud/VPS storage | UNCLEAR | UNCLEAR — "Authorized User" includes customer-authorized "computerized systems" [18] | UNCLEAR — must notify FMP of storage locations (§2.8) [23] | n/a | UNCLEAR | UNCLEAR | UNCLEAR |
| Multiple rented servers | UNCLEAR | UNCLEAR | UNCLEAR (§2.8) | n/a | UNCLEAR | UNCLEAR | UNCLEAR |
| Combination with another provider | UNCLEAR (not addressed) | UNCLEAR — prohibited only "to create competing products" (§2.3(k)) [18] | UNCLEAR | n/a | UNCLEAR | UNCLEAR | UNCLEAR |
| Redistribution | **No (X)** [13] | Only via tier/add-on/agreement (§2.2(b),(e)) [18] | **No (X)** §2.6.1(i) [23] | n/a | **No (X)** without permission [33] | UNCLEAR | UNCLEAR |
| Private dashboard display | UNCLEAR — "displaying" prohibited; display to oneself not addressed [13] | Yes (C) — display to Authorized Users (§2.2(b)) [18] | UNCLEAR — "publicly perform or display" prohibited [23] | n/a | UNCLEAR | UNCLEAR | UNCLEAR |

EODHD commercial plans (for reference): the "Internal Use" plan restricts use to
within the company, and "Displaying the data or sharing it with individuals
outside your company is not permissible". The "Custom Plan" lists "Negotiable
terms including data download to corporate servers" [57].

### 28.2 Historical coverage (IDX-specific)

| Check | EODHD | Twelve Data | FMP | Sectors | Invezgo | IDX / institutional |
| --- | --- | --- | --- | --- | --- | --- |
| Indonesian equities | C — 924 active JK tickers [6] | C — 944 active XIDX [20] | C — `.JK` pages [25] | C [28] | C — "900+" [32] | S |
| 2015 onward | ND for JK (plan "30+ years" is generic) [12] | ND (endpoint exists) [19] | ND | ND | C — "since 2009" (vendor claim) [32] | S |
| Delisted IDX equities | ND for JK (generic endpoint) [11] | 180 delisted identifiers listed (observed) [20]; history ND | ND | ND | ND | S |
| History through final trading day | Generic: "Delisted symbols retain their full history" [7]; JK ND | ND | ND | ND | ND | S |
| Ticker changes / renames | US only [11]; JK ND | ND | ND | ND | ND | S |
| Stable IDs | ISIN partial (generic) [11] | FIGI (observed) [20]; ISIN add-on [19] | ND | ND | ND | S |

### 28.3 Corporate-action fields

Legend: **documented** = field in official docs/schema · **ND** = not
documented · **absent** = the official API schema has no such field.

| Field | EODHD [9] | Twelve Data [19] | FMP | Sectors [29] | Invezgo | IDX Data Reference |
| --- | --- | --- | --- | --- | --- | --- |
| Cash dividend amount | documented (`value`, `unadjustedValue`) | documented (`amount`) | ND (IDX) | ND (covered, fields ND) | ND | S |
| Ex-date | documented (`date`) | documented (`ex_date`) | ND | ND | ND | S |
| Record date | documented, "varying coverage"; IDX ND | absent | ND | ND | ND | S |
| Payment date | documented, "varying coverage"; IDX ND | absent | ND | ND | ND | S |
| Splits | documented (ratio `new/old`) | documented (`ratio`, `from_factor`, `to_factor`) | ND | ND (covered) | ND | S |
| Reverse splits | documented (generic examples) | ND | ND | ND | ND | S |
| Bonus / stock dividends | documented as non-standard split ratios (generic) | ND | ND | ND | ND | S |
| Rights issues | ND | ND | ND | ND (covered, fields ND) | ND | S |
| Rights ratio | ND | ND | ND | ND | ND | S |
| Exercise price | ND | ND | ND | ND | ND | S |
| Rights dates | ND | ND | ND | ND | ND | S |

### 28.4 Market data

| Check | EODHD | Twelve Data | FMP | Sectors | Invezgo |
| --- | --- | --- | --- | --- | --- |
| Raw OHLCV | documented "raw" [7]; provenance contradiction [13][56] | `adjust=none` [19] | "Unadjusted" (split) endpoint [24]; IDX ND | ND (close/volume/market cap only, v1 retired) [30] | ND |
| Adjusted | `adjusted_close` only (splits + dividends) [7] | `adjust=splits/dividends/all` [19] | dividend-adjusted endpoint listed [22] | ND | "Full corporate action adjusted" [32] |
| Volume unit | "adjusted for splits only"; shares vs lots ND [7] | ND | ND | ND | ND |
| Currency | IDR [6] | IDR (observed listing) [20] | ND | IDR [30] | ND |
| Date semantics | trading day in local market time [7] | bar-open datetime at local exchange time [19] | ND | ND | ND |
| Regular vs negotiated | ND | ND | ND | ND | ND |
| Suspension handling | ND | ND | ND | ND | ND |

EODHD's data-sources page names direct exchange contracts for the US, Europe
(Cboe), Australia (ASX), and Canada, plus data "from CFDs and market makers";
**Indonesia is not named** [56].

### 28.5 Automation

| Check | EODHD | Twelve Data | FMP | Sectors | Invezgo |
| --- | --- | --- | --- | --- | --- |
| API / auth | REST, `api_token` parameter [7] | REST, `apikey` parameter [19] | REST [24]; auth details not reviewed | REST, credit-based [29]; auth details not reviewed | REST [32]; auth ND |
| Rate limits | 100k/day; 1,000/min (paid) [12] | credits/min by tier [17] | 300–3,000/min [22] | monthly credit limit; HTTP 429 [29][30] | 250–2,000/min; 30k–320k/month [32] |
| Historical endpoint | per ticker [7] | `time_series`, ≤ 5,000 points/request [19] | per ticker [24] | v2 `/close/` per date, paginated [29] | ND |
| Bulk endpoint | whole exchange per day, 100 calls, historical dates allowed [10] | batch requests (pricing page) [17] | bulk on Ultimate [22] | ND | ND |
| Pagination | not needed per ticker | `/stocks` paginated [19] | ND | yes [29] | ND |
| Backfill feasibility (≈1,300 securities × 10 yrs) | feasible within limits (by docs) | feasible if the tier allows (≈1 request per ticker) | feasible on Ultimate (by docs) | ≈2,700 date requests (by docs) | ND |
| Daily incremental | bulk per exchange-day [10] | per ticker or batch | bulk (Ultimate) | per date | ND |

Feasibility here is arithmetic from documented limits, **not tested** with IDX
data.

### 28.6 Cost (as displayed on 2026-09-24)

| Item | EODHD | Twelve Data | FMP | Invezgo | Others |
| --- | --- | --- | --- | --- | --- |
| Free tier | 20 calls/day, past year, EOD [12] | Basic: 8 credits/min, 800/day, 3 exchanges (no IDX) [17][16] | 250 calls/day [22] | 1-month trial [32] | GoAPI free limited quota [34]; others ND/S |
| Paid tiers & price | Personal: $19.99–$99.99/mo; Commercial Internal Use $399/mo; Enterprise $2,499/mo; Custom by request [12][57] | Grow $79/mo; Pro $229/mo (as displayed); Ultra $999/mo [17] | Starter $19, Premium $49, Ultimate $99 per month, billed annually [22] | IDR 499,900 – 4,000,000/mo [32] | S |
| Billing | monthly or yearly | monthly or annual | billed annually (displayed) | monthly | S |
| IDX access | All World and above [12]; JK page mentions All World Extended for the hours API [6] (U) | **Pro** (individual) / **Venture** (business) [16] | **Ultimate** ("Global Coverage") [22] | included | S |
| History | "30+ years" (plan) [12] | ND | Ultimate "Full Historical Access" [22] | "since 2009" [32] | S |
| Delisted | listed as included (All World) [12] | ND | endpoint listed [22] | ND | S |
| Corporate actions | splits/dividends included (All World) [12] | Grow+ [17] | endpoints listed [22] | adjusted prices only | S |
| Security IDs | ISIN where available [11] | FIGI (listing); ISIN paid add-on; FIGI parameter on Ultra [19] | ND | ND | S |
| Contact sales | Custom plan [57] | business plans | commercial pages | — | IDX, ICE, LSEG, Bloomberg, FactSet, S&P |

---

## 29. Source matrix

**Confidence** describes the evidence type, not the quality of the provider:
**High** = official documentation specific to IDX; **Medium** = official
documentation that is generic (not IDX-specific) or an observed API listing;
**Low** = vendor marketing, search-indexed text, or secondary sources.

| Required data | Provider | Coverage | License | Storage | Cloud | API | Cost | Confidence | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Daily OHLCV (raw) | EODHD | JK active tickers; depth ND | Personal; store/analyse permitted | UNCLEAR | UNCLEAR | Yes | $19.99+/mo | Medium | Provenance contradiction (VWAP/non-exchange) |
| Daily OHLCV (raw) | Twelve Data | XIDX; depth ND | Internal use | No (after termination) | UNCLEAR | Yes | Pro tier | Medium | `adjust=none` required |
| Daily OHLCV (raw) | FMP | `.JK` pages; depth ND | Personal | No (after termination) | UNCLEAR | Yes | Ultimate | Low | IDX coverage scope ND |
| Daily OHLCV | Invezgo | IDX; "since 2009" | UNCLEAR | UNCLEAR | UNCLEAR | Yes | IDR/mo | Low | Adjusted prices; raw ND |
| Daily OHLCV | IDX Data Services | IDX (official) | S | S | S | S | S | Low (I) | Official source; site 403 |
| Delisted history | EODHD | endpoint generic; JK ND | as above | UNCLEAR | UNCLEAR | Yes | All World | Medium | — |
| Delisted history | Twelve Data | 180 identifiers listed; history ND | as above | No | UNCLEAR | Yes | Pro | Medium | — |
| Cash dividends | EODHD | fields documented; JK ND | as above | UNCLEAR | UNCLEAR | Yes | All World | Medium | Record/payment dates "varying coverage" |
| Cash dividends | Twelve Data | ex-date + amount only | as above | No | UNCLEAR | Yes | Grow+/Pro | Medium | No record/payment date |
| Rights issues | Sectors | "covered"; fields ND | ND | ND | ND | Yes | ND | Low | — |
| Rights issues | Issuer / KSEI / IDX disclosures | primary terms | website terms not reviewed | UNCLEAR | UNCLEAR | No documented API | Free to read (not verified) | Low (pages 403/404/500) | T1 for terms |
| Splits / bonus | EODHD | ratio documented (generic) | as above | UNCLEAR | UNCLEAR | Yes | All World | Medium | — |
| Splits | Twelve Data | ratio/factors documented | as above | No | UNCLEAR | Yes | Grow+ | Medium | Bonus/stock dividend ND |
| Security IDs | Twelve Data | FIGI (observed); ISIN add-on | as above | No | UNCLEAR | Yes | Add-on / Ultra | Medium | — |
| Security IDs | EODHD | ISIN partial | as above | UNCLEAR | UNCLEAR | Yes | All World | Medium | — |
| Ticker history | none documented for IDX | — | — | — | — | — | — | — | Gap |
| Suspensions | none documented for IDX | — | — | — | — | — | — | — | Gap; IDX announcements (403) |
| IHSG | Twelve Data | `JKSE` listed; depth not verified | as above | No | UNCLEAR | Yes | Pro | Medium | §27 |
| IHSG | EODHD | not documented | as above | UNCLEAR | UNCLEAR | Yes | — | Low | §27 |
| Trading rules | IDX decisions / OJK | see §26 | public documents | n/a (reference facts) | n/a | none | free | Mixed (§26) | Manual curation |

## 30. Field-level matrix

`TBD` means **no evidence-based choice exists yet**.

| Field | Primary source | Fallback source | Required fields | Provenance required | Validation status |
| --- | --- | --- | --- | --- | --- |
| Daily OHLCV | TBD | TBD | OHLCV, date, currency, volume (unit) | Yes | NOT VALIDATED — no candidate with IDX-specific provenance and permitted permanent storage |
| Cash dividends | TBD | TBD | gross amount, ex-date (+ record/payment date) | Yes | NOT VALIDATED — IDX coverage of fields not documented |
| Rights | TBD | TBD | ratio, subscription price, cum/ex/recording/distribution dates, trading and exercise periods | Yes | NOT VALIDATED — no vendor documents fields; primary pages unreachable |
| Splits/bonus | TBD | TBD | ratio, effective (ex) date | Yes | NOT VALIDATED — generic docs only |
| Security ID | TBD | TBD | ISIN / vendor ID | Yes | NOT VALIDATED — ISIN partial or paid add-on |
| Ticker history | TBD | TBD | old/new ticker, effective date | Yes | NOT AVAILABLE from any candidate's documentation |
| Suspensions | TBD | TBD | status, start/end date | Yes | NOT AVAILABLE from any candidate's documentation |
| Delisting | TBD | TBD | listing/delisting date | Yes | NOT VALIDATED — delisting-date field not documented |
| IHSG | TBD | TBD | daily index history 2015+ | Yes | NOT VALIDATED (§27) |
| Trading rules | TBD | TBD | lot/tick/session/limits by effective date | Yes | PARTIAL — lot size (2014) and T+2 verified; others secondary or unverified (§26) |

---

## 31. One provider or multiple providers

**Evidence-based finding (not a selection):**

* **No single candidate documents all mandatory fields for IDX.** Fields
  documented by no vendor: rights-issue terms (ratio, subscription price,
  dates), IDX ticker-change history, suspension status/dates, delisting dates,
  and verified IHSG history. IDX trading rules come only from IDX/OJK
  documents.
* **Permanent storage (M1)** is prohibited after termination by Twelve Data and
  FMP, and unclear for EODHD. For those providers, a subscription-dependent
  store conflicts with the reproducibility requirement unless written terms
  say otherwise.
* **Therefore a multi-source architecture is necessary.** The minimum
  combination, by category:
  1. a licensed daily price + cash-dividend + split source for IDX;
  2. primary-source corporate-action terms (issuer/KSEI/IDX disclosures) for
     rights issues and verification of other actions;
  3. primary-source listing, delisting, ticker-change, and suspension records
     (IDX announcements);
  4. an IHSG source with verified history and storage rights;
  5. a curated, time-versioned IDX trading-rule reference dataset (§26).
  A single licensed source may turn out to cover several of these; that
  requires written confirmation (§33).

**Licensing issues created by combining sources:**

* Combination clauses (e.g. Twelve Data §2.3(k)) and derived-data clauses must
  be checked for every pair.
* Deletion-on-termination clauses make any combined or derived dataset that
  contains that provider's data subject to deletion (FMP §6.2 explicitly covers
  "derived" data).
* Terms of reuse for IDX/KSEI website announcements have not been reviewed.
* IHSG is IDX intellectual property; vendor rights to deliver it are
  undocumented.

---

## 32. Implementation readiness gate

Statuses: **READY** · **PARTIALLY READY** · **BLOCKED**. Readiness to *begin
implementation*, not to trade or publish.

| Item | Status | Missing evidence |
| --- | --- | --- |
| OHLCV | BLOCKED | A source with documented IDX raw OHLCV, verified 2015+ depth, documented volume unit, and permitted permanent storage; EODHD provenance contradiction resolved |
| Delisted history | BLOCKED | Written confirmation that delisted IDX securities have full history, plus delisting dates |
| Corporate actions | BLOCKED | IDX-specific field coverage (record/payment dates, bonus, reverse splits) from a selected source; primary-source verification path |
| Dividends | BLOCKED | IDX dividend coverage including delisted securities; gross vs net confirmation |
| Rights | BLOCKED | Any source of rights terms with fields; KSEI/IDX pages reachable or licensed; out-of-the-money treatment decided |
| Security IDs | BLOCKED | A stable ID for all IDX securities including delisted (ISIN coverage for JK/XIDX) |
| Ticker history | BLOCKED | Any documented source of IDX ticker changes with effective dates |
| Suspensions | BLOCKED | Any documented source of suspension status and dates |
| IHSG | BLOCKED | Verified 2015+ history and storage rights from any source |
| Licensing | BLOCKED | Written confirmations for the UNCLEAR cells in §28.1 |
| Permanent storage | BLOCKED | A source whose terms permit retention after termination |
| Cloud storage | BLOCKED | Written confirmation for rented-server storage (not needed for local-only work) |
| Automation | PARTIALLY READY | Limits and endpoints documented for EODHD, Twelve Data, and FMP; untested with IDX data; depends on selection |
| Provenance | READY (design) | Requirements defined (§22); schema design is an implementation task |
| Source disagreement handling | PARTIALLY READY | Procedure defined (§21, §23); per-field tolerances and tie-break orders need the reconciliation sample (M13) |
| Trading rules | PARTIALLY READY | Official texts for tick sizes (2016+), price limits, sessions, and calendars 2015–2025 |

**Overall: BLOCKED.** Phase 2 implementation should not start until at least
OHLCV, licensing, permanent storage, and security IDs move out of BLOCKED.

---

## 33. Open questions

**Project-level**
1. Adopt or amend the precedence rule (§21); define per-field tolerances and
   tie-break orders after the M13 sample.
2. Rights: out-of-the-money treatment; theoretical vs explicit HMETD handling
   in backtests (§25).
3. Build the time-versioned IDX trading-rule dataset from official texts (§26),
   including trading calendars 2015–2025.
4. IHSG source with verified history and storage rights (§27).
5. Budget (F1).

**Written confirmations to request**
* **IDX Data Services:** individual eligibility; EOD/historical, Data
  Reference (corporate actions), and Index licence terms (storage, derived,
  cloud, retention after termination); delisted coverage; suspension and
  ticker-change data; delivery method; price.
* **EODHD:** retention after termination; derived data; rented-server storage;
  private display; whether JK prices are exchange-originated (Indonesia is not
  named among direct contracts [56]); JK start date; delisted JK coverage and
  delisting dates; JK record/payment-date coverage; rights issues; JK ISIN
  coverage; `JKSE.INDX` availability and depth; which plan is needed for the
  trading-hours/holiday API.
* **Twelve Data:** retention of derived data after termination; the "permitted
  timeframes" referenced in §2.3(g); history for the 180 delisted XIDX
  identifiers; XIDX and JKSE depth; dividend record/payment dates; rights
  issues; ISIN add-on cost; rented-server storage.
* **FMP:** IDX coverage on Ultimate; `.JK` delisted and corporate-action
  coverage; `^JKSE`; scope of the derivative-works clause.
* **Sectors / Invezgo / GoAPI / OHLC.dev:** licence terms; raw OHLCV; delisted
  coverage; history depth; whether they hold IDX redistribution licences.
* **LSEG / Bloomberg / FactSet / S&P / ICE:** IDX coverage including delisted;
  individual eligibility; price.
* **KSEI / IDX websites:** terms for reuse of published corporate-action and
  announcement data.

## 34. Research dates

* Round 1 (sections 10–19): **2026-09-24**.
* Round 2 (sections 20–33): **2026-09-24**.

Re-check every source's terms at selection time and record the version read.

Retrieval notes:
* idx.co.id, data.idx.co.id, and IDX test domains returned HTTP 403 to
  automated requests; this was not bypassed.
* KSEI pages returned HTTP 404/500 on 2026-09-24; the OJK site was reachable.
* The S&P DJI methodology PDF returned HTTP 403.
* sectors.app returned HTTP 429; FactSet pages rendered no body text.
* Demo-key probes: Twelve Data `/stocks` and `/indices` returned data;
  `earliest_timestamp` returned 401; EODHD returned "Forbidden".
* Items marked **I** come from search-engine-indexed text that the search
  engine attributed to the cited URL; the page body itself was not read or did
  not contain the text. Treat **I** items as unverified until confirmed.

## 35. Source links

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
| 42 | OJK press release SP 80/DHMS/OJK/XI/2018 (T+2) | https://ojk.go.id/id/berita-dan-kegiatan/siaran-pers/Pages/Siaran-Pers-Penyelesaian-Transaksi-Bursa-Dua-Hari-T+2-Berjalan-Lancar.aspx |
| 43 | IDX Kep-00071/BEI/11-2013 (lot size, tick size) — third-party-hosted copy | https://svc.star.id/docs/forms/general/SK%20Peraturan%20Nomor%20II-A%20Perubahan%20Satuan%20Perdagangan%20dan%20Fraksi%20Harga.pdf |
| 44 | IDX Peraturan II-A, Kep-00055/BEI/03-2023 (HTTP 403) | https://www.idx.co.id/Media/y0vjxqur/signed_peraturan_ii_a_perdagangan_efek_bersifat_ekuitas.pdf |
| 45 | Stockbit Snips — tick size table citing Kep-00023/BEI/04-2016 (secondary, 2022-02-02) | https://snips.stockbit.com/investasi/pengertian-fraksi-harga-saham |
| 46 | Katadata Databoks — auto-rejection schedule 2023 (secondary, 2023-03-31) | https://databoks.katadata.co.id/datapublish/2023/03/31/ini-batas-auto-rejection-saham-terbaru-2023 |
| 47 | Kontan — ARB 15% from 2025-04-08 (secondary) | https://momsmoney.kontan.co.id/news/bei-tetapkan-auto-rejection-bawah-arb-hanya-15-dan-mengubah-batas-trading-halt-8 |
| 48 | IDX — Trading hours and mechanism (HTTP 403) | https://www.idx.co.id/en/products-services/trading-hours-and-mechanism/ |
| 49 | IDX — 2026 exchange holiday calendar, Peng-00171/BEI.POP/09-2025 (HTTP 403) | https://www.idx.co.id/StaticData/NewsAndAnnouncement/ANNOUNCEMENTSTOCK/Exchange/Peng-00171%20Libur%20Bursa%202026-No.%20Peng-00171BEI.POP09-2025.pdf |
| 50 | MSCI Index Calculation Methodology, August 2025 | https://www.msci.com/eqb/methodology/meth_docs/MSCI_Index_Calculation_Methodology_Aug2025.pdf |
| 51 | S&P DJI Index Mathematics Methodology, April 2026 (HTTP 403; I) | https://www.spglobal.com/spdji/en/documents/methodologies/methodology-index-math.pdf |
| 52 | POJK 32/POJK.04/2015 — HMETD (identified; not reviewed) | https://www.ojk.go.id/id/kanal/pasar-modal/regulasi/peraturan-ojk/Documents/Pages/pojk-32-penambahan-modal-pt-dengan-memberikan-hak-memesan-efek-terlebih-dahulu/SALINAN-POJK%20HMETD.pdf |
| 53 | POJK 14/POJK.04/2019 — amendment (identified; not reviewed) | https://www.ojk.go.id/id/regulasi/Pages/Perubahan-Atas-Peraturan-Otoritas-Jasa-Keuangan-Nomor-32-tentang-Penambahan-Modal-Perusahaan-Terbuka-dengan-Me.aspx |
| 54 | KSEI — example HMETD schedule announcement (HTTP 404 on 2026-09-24; I) | https://www.ksei.co.id/ksei_news/read/6857/Pengumuman-CA-Jadwal-Kegiatan-Penawaran-Umum-Terbatas-I-dalam-rangka-Penerbitan-Hak-Memesan-Efek-Terlebih-Dahulu-HMETD-PT-Broadband-Multimedia-Tbk-KBLV |
| 55 | KSEI — corporate action service (HTTP 500 on 2026-09-24) | https://web.ksei.co.id/services/types/corporate-action |
| 56 | EODHD — Our data sources and data partners | https://eodhd.com/financial-apis/our-data-sources-and-data-partners |
| 57 | EODHD — Commercial pricing | https://eodhd.com/commercial-pricing |
| 58 | Twelve Data — `earliest_timestamp` (JKSE) probe; demo key returned 401 | https://api.twelvedata.com/earliest_timestamp?symbol=JKSE&mic_code=XIDX&interval=1day |
| 59 | EODHD — `eod/JKSE.INDX` probe; demo key returned "Forbidden" | https://eodhd.com/api/eod/JKSE.INDX |

---

## 36. Development Data Sources ($0 development mode)

**These sources are development data sources and are not declared to satisfy
production licensing requirements.**

Decision (project owner, 2026-09-24): proceed in **$0 development mode**. Build
the pipeline, database, features, technical analysis, event studies, ML, and
backtesting framework on publicly accessible data now. The production
requirements in sections 1–35 are **unchanged**; production source selection
remains a later gate (§32). All development code must go through the
provider-neutral interface (§36.9) so that a production source can replace
development sources without changing downstream code.

Research and inspection date: **2026-09-24**. Downloads were stored outside the
repository (session scratch space); **no third-party data is committed**.

### 36.1 Production vs development requirements

| Requirement | Production (unchanged) | Development |
| --- | --- | --- |
| History | 2015-01-01 onward (MUST) | Enough history to build and test the pipeline; the actual range is documented |
| Delisted securities | MUST | Best effort; gaps documented |
| Ticker history, suspensions | MUST | Best effort; heuristics allowed if labelled |
| Corporate actions, rights, dividends | MUST | Best effort from public sources |
| IHSG | MUST | Required (available) |
| Licence: storage, cloud, derived data | MUST | Recorded per source; not a gate |
| Provenance | MUST | **MUST** — same provenance fields (§22) |

### 36.2 License classification used here

* **OPEN LICENSE**: an explicit licence is attached by the publisher (e.g. MIT,
  Apache-2.0, CC BY, CC0, ODbL). A NonCommercial licence (CC BY-NC) is recorded
  as explicit but **non-commercial**.
* **LICENSE UNCLEAR**: publicly downloadable; no licence, or the publisher's
  right to license the underlying data is unclear.
* **RESTRICTED — NOT USED FOR DEVELOPMENT**: needs an account, API key,
  subscription, or authentication. Access controls were not bypassed.

**Upstream-rights caveat (applies to every IDX-derived dataset below):** the
publishers state the data belongs to IDX. As quoted in the Dataset-Saham-IDX
README (IDX Terms of Use no. 6; the IDX site itself returned HTTP 403 and was
not read directly), IDX allows **non-commercial** use with full attribution and
access date, prohibits commercial use without written permission, and does
not permit web scraping/crawling [DS-1]. A repository licence cannot grant
more rights than its publisher holds. Yahoo-derived datasets carry the Yahoo
caveat recorded in §11.

### 36.3 Sources investigated

| # | Source | Type | Licence (as published) | Class | Inspected | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| DS-1 | wildangunawan/Dataset-Saham-IDX (GitHub) | IDX-format daily, per ticker | CC BY-NC 4.0 | OPEN (non-commercial); upstream rights UNCLEAR | **Yes** | Manual updates; states data taken from idx.co.id |
| DS-2 | KAnggara75/Dataset-Saham-IDX (fork of DS-1) | same format, extended | CC BY-NC 4.0 (inherited) | as DS-1 | **Yes** | Extension fetched from a local API (`localhost:3000`); upstream undocumented |
| DS-3 | KAnggara75/Dataset-Saham-IDX-SQL | SQL mirror of DS-1 | CC BY-NC 4.0 (NOASSERTION in API) | as DS-1 | Sample | Same range as DS-1 (2019-07-29 → 2025-02-21) |
| DS-4 | Pholenk/IDX-Dataset (GitHub; mirrored to Kaggle `pholenk/eod-data-indonesia-stock-exchange`) | IDX-format daily per ticker + 56 index files | Data: **ODbL v1.0**; code: AGPL-3.0 | OPEN; upstream rights UNCLEAR | **Yes** | "Derived from files published by IDX"; collection method not in repo |
| DS-5 | faisalburhanudin/idx (GitHub) | Yahoo-format daily per ticker | none | LICENSE UNCLEAR (Yahoo caveat) | **Yes** | Snapshot of 2019-04-08; release `07042019` |
| DS-6 | theonegareth/daily-IHSG (Hugging Face; mirrors fadil05/…, ggvalentino99/…) | IHSG daily | MIT (declared) | OPEN (declared); source Yahoo ^JKSE | **Yes** | Card: "Source is Yahoo Finance" |
| DS-7 | dimasirginsyh/indonesia-stock-dividends (GitHub) | cash dividends | none | LICENSE UNCLEAR | **Yes** | Upstream: mitbal/daguerreo-data (DS-8) |
| DS-8 | mitbal/daguerreo-data (GitHub) | dividends, profiles, income statements | none | LICENSE UNCLEAR | Metadata + sync script | Sync script calls idx.co.id internal endpoints using browser impersonation (`curl_cffi`) |
| DS-9 | nichsedge/idx-bei (GitHub; 51 forks incl. Alivanza/idx-bei) | IDX scraper toolkit + JSON snapshots (corporate actions, company profiles) | MIT (repository) | OPEN (code); data upstream rights UNCLEAR | **Yes** (`corporateActions.json`, `allCompanies.json`) | Scrapes IDX/KSEI |
| DS-10 | kjhq/Indonesia-Stock-Symbols-and-Metadata (Hugging Face) | ticker, name, market, sector | CC0 1.0 | OPEN | **Yes** | 863 rows |
| DS-11 | lensetek/idx-panel-data-descriptor (GitHub; Zenodo 10.5281/zenodo.21110404) | 95 large-cap tickers, yfinance | README: CC BY 4.0; **Zenodo: GPL-3.0-or-later** | Contradictory — UNCLEAR | **Yes** | Yahoo-sourced; 3.3% duplicate rows |
| DS-12 | qywok/indonesia_stocks (Hugging Face) | 183 tickers, yfinance-style adjusted | MIT (declared) | OPEN (declared); Yahoo caveat | Sample | Starts 2023-01-02 |
| DS-13 | nauraazalia/idx-prolonged-suspension-dataset (GitHub) | yearly alive/suspended label + ratios | CC BY 4.0 | OPEN | **Yes** | Not suspension dates |
| DS-14 | nofendian17/idx_dataset (GitHub) | daily all-stock snapshots | none | LICENSE UNCLEAR | Sample | Scraped from imq21.com |
| DS-15 | SeedFlora/idx-daily-data (GitHub) | few tickers, Yahoo | none | LICENSE UNCLEAR | README | Selected tickers only |
| DS-16 | Zenodo 20603320 — LQ45 components 2023–2025 | 45 tickers | CC BY 4.0 | OPEN | Metadata | Small subset |
| DS-17 | Zenodo 20739308 / 18276107 — bank stocks 2020–2025 | 4–5 tickers | CC BY 4.0 | OPEN | Metadata | Small subset |
| DS-18 | Zenodo 17626537 — Financial data IDX 2020–2023 | fundamentals (xlsx) | CC BY 4.0 | OPEN | Metadata | Relevant to Phase 3, not prices |
| DS-19 | Kaggle: eren2222 (2000–2024, 2020–2024), muamkh/ihsgstockdata, bestagi, garethharrison/daily-ihsg, pholenk mirror | various | per Kaggle page | **RESTRICTED — NOT USED FOR DEVELOPMENT** | No | Download requires an account (API returned 302) |
| DS-20 | Other GitHub scrapers/tools (NeaByteLab/IDX-API, basnugroho/indonesia-stocks-scraper, kubil-ismail/indonesia-stock-exchange, alukito/idx-data, others found by search) | code, not datasets | various | n/a | README only | Not data sources |

### 36.4 Measurements of inspected datasets

Checks: duplicates on (ticker, date); OHLC consistency `high ≥ max(open, close,
low)`, `low ≤ min(open, close, high)`, `high ≥ low`; `volume ≥ 0`. Rows with a
zero in any OHLC field are excluded from the consistency checks and counted
separately.

| Metric | DS-4 Pholenk | DS-1 wildangunawan | DS-2 KAnggara75 fork | DS-5 faisalburhanudin | DS-11 lensetek |
| --- | --- | --- | --- | --- | --- |
| Files | 983 CSV (245 MB) | 958 CSV (178 MB) | 958 CSV | 627 CSV | 1 CSV (20 MB) |
| Rows | 1,289,820 | 1,078,040 | 1,344,519 | 1,517,903 | 373,577 |
| Tickers | 983 | 958 | 958 | 627 | 95 |
| Date range | 2020-01-02 → 2026-05-29 | 2019-07-29 → 2025-02-21 | 2019-07-29 → 2026-05-08 | 2000-03-30 → 2019-04-08 | 2010-01-04 → 2026-07-01 |
| Duplicates | 0% | 0% | 0% | 0% | 3.255% |
| Missing OHLC fields | 0% | 0% | 0% | 0% | 0% |
| Rows with a zero OHLC field | 81.1% (mostly `Open`) | 92.9% (`open_price`) | 82.3% | 0.0004% | 0% |
| `Open` = 0 | 81.1% (2020–2024: 92–97%; 2025: 43%; 2026: 33%) | 92.9% | — | — | — |
| High = Low = Volume = 0 (no trade/suspended) | 156,317 rows (12.1%) | 131,839 rows (12.2%) | — | — | — |
| OHLC violations (checkable rows) | 0 | 0 | 0 | high 604, low 491, high<low 18 | high 28, low 55 |
| Negative volume | 0 | 0 | 0 | 0 | 0 |
| Price basis | **raw** (e.g. BBCA 33,450 on 2020-01-02, before its 2021 split) | raw | raw | split-adjusted (Yahoo `Close`) + `Adj Close` | adjusted (decimal prices) |
| Volume unit | shares | shares (documented) | shares | shares (Yahoo) | shares |
| Extra fields | previous close, value, frequency, bid/offer, listed & tradable shares, foreign buy/sell, non-regular volume/value/frequency, remarks | same as DS-4 plus `first_trade`, `delisting_date` (always empty) | as DS-1 | `Adj Close` | ticker |
| Tickers with data by 2015-01-31 | 0 | 0 | 0 | 455 | 88 |

**Index datasets**

| Metric | DS-4 `COMPOSITE.csv` (IHSG) | DS-6 daily-IHSG |
| --- | --- | --- |
| Rows / range | 1,540 / 2020-01-02 → 2026-05-29 | 7,716 / 1995-01-02 → 2026-09-23 |
| Rows 2015+ | 1,540 | 2,832 |
| Fields | previous, high, low, close, constituents, volume, value, frequency, capitalization | open, high, low, close, volume |
| Quality | — | 108 flat-OHLC rows and 132 zero-volume rows (early years); 0 OHLC violations |
| Cross-check | 1,539 overlapping days; max relative close difference 0.754%; only 1 day > 0.1% | — |

DS-4 also contains 55 other IDX index files (e.g. LQ45, IDX30, IDX80, sector indices).

**Supplemental datasets**

| Dataset | Measured |
| --- | --- |
| DS-7 dividends | 5,925 records; 602 tickers; ex-dates 2000-07-12 → 2026-08-20 (≈ 238–421 per year from 2015); 0 duplicates; fields `ex_date`, `dividend`, `payment_date`, `fiscal_year`, `dividend_type`; `payment_date` missing in 2,691 records (45%); no record date; gross vs net **not stated** |
| DS-9 corporate actions | 1,652 records in 15 categories: rights (HMETD) 241, non-pre-emptive issues 76, stock splits 199, reverse splits 5, bonus shares 141, stock dividends 40, IPO 438, warrants 234, mergers 10, capital reductions 22, conversions 53, company listings 149, partial delistings 35, buyback 1, private placement 8. Fields: ticker, listing/recording date (`TanggalPencatatan`), shares before/after. **No ex-date, ratio, or exercise price.** |
| DS-9 company list | 957 records (IDX company-profile JSON) |
| DS-1 `List Emiten/all.csv` | 951 rows: code, name, listing date, shares, listing board (no delisting date) |
| DS-10 metadata | 863 rows: name, ticker, market, sector |
| DS-13 suspension labels | 5,611 company-year rows; 936 companies; years 2014–2023; 5,403 `alive`, 208 `suspended` |

### 36.5 Cross-source validation findings

* **DS-4 vs DS-1 closes:** 1,002,669 overlapping (ticker, date) rows; 99.483%
  identical; **5,186 differ, all on 9 dates in 2024** (2024-02-01, 02-13,
  02-28, 06-26, 06-27, 06-28, 07-04, 07-31, 08-15; 543–618 tickers per date).
  Of those, 2,042 are exact one-trading-day shifts (DS-1 close = DS-4 next-day
  close). One source is misaligned on those dates; **which one is not
  determined**. DS-2 agrees with DS-1 on all 5,186, but DS-2 inherits DS-1's
  history, so this is not independent evidence. Handling: §23 (preserve both,
  flag, never overwrite).
* **DS-2 vs DS-4 closes:** 1,271,258 overlapping rows; 99.558% identical.
* **Open prices** are zero for most rows before 2025 in **both** IDX-format
  sources, so this reflects the upstream field, not one publisher's error.
  Development code must treat `open = 0` as **missing**, not as a price.
* **Missing trading days:** DS-4 has 10 gaps longer than 5 calendar days; all
  fall around holiday periods (e.g. 2024-04-05 → 2024-04-16, 2025-03-27 →
  2025-04-08). DS-4's README warns that some non-holiday dates may be missing.
  A verified IDX calendar is still required (§26).
* **Encoding:** DS-4 and DS-2 CSVs start with a UTF-8 byte-order mark.

### 36.6 Development source map

| Dataset | Type | License | Tickers | Start | End | OHLCV | Dividends | Corporate Actions | IHSG | Provenance | Status |
| ------- | ---- | ------: | ------: | ----: | --: | ----- | --------- | ----------------- | ---- | ---------- | ------ |
| DS-4 Pholenk/IDX-Dataset | IDX-format daily | ODbL v1.0 (upstream IDX) | 983 | 2020-01-02 | 2026-05-29 | Yes (open often 0) | No | No | Yes (`COMPOSITE`) | Commit `9bb3b26bd28ab46bc2f3e74a7c03805ce053301b`; archive SHA-256 `5165948e756e113577458769efd609040f7534d2ede0f4ba1967dba593566c91` | **Selected — core OHLCV + IHSG** |
| DS-1 wildangunawan | IDX-format daily | CC BY-NC 4.0 (upstream IDX) | 958 | 2019-07-29 | 2025-02-21 | Yes (open often 0) | No | No | No | Commit `bc0ac7712c` (2025-02-23); archive SHA-256 `e7c44464f232935c8797d91cf4def542ee18b79f041bef7fd6bfb71e89abbefe` | **Selected — cross-check** |
| DS-2 KAnggara75 fork | IDX-format daily | CC BY-NC 4.0 (inherited) | 958 | 2019-07-29 | 2026-05-08 | Yes | No | No | No | Commit `ad3fba81abb236966b944bffde67c6c5ced8395b`; archive SHA-256 `a3634b09b5aeba54eb8dad21c946751ae95988dc5847af5bc4bc5812df58f6bc`; extension upstream undocumented | Supplemental — cross-check only |
| DS-5 faisalburhanudin | Yahoo-format daily | none | 627 | 2000-03-30 | 2019-04-08 | Yes (split-adjusted) | No | No | No | Snapshot 2019-04-08 | **Selected — pre-2020 development history, flagged** |
| DS-6 daily-IHSG | index daily | MIT (declared; Yahoo source) | 1 index | 1995-01-02 | 2026-09-23 | Yes | n/a | n/a | Yes | HF dataset, refreshed daily | **Selected — IHSG pre-2020 and latest** |
| DS-7 indonesia-stock-dividends | dividends | none | 602 | 2000-07-12 | 2026-08-20 | No | Yes | No | No | Upstream DS-8 (IDX via automated collection) | **Selected — dividends** |
| DS-9 nichsedge/idx-bei | corporate actions + profiles | MIT (repo; upstream IDX) | 957 (profiles) | 1979 | 2026-08 | No | No | Partial (share counts, dates) | No | Scraped from IDX | **Selected — corporate-action events, metadata** |
| DS-10 kjhq metadata | security metadata | CC0 | 863 | — | — | No | No | No | No | HF dataset | Supplemental — sector names |
| DS-1 `List Emiten` | security metadata | CC BY-NC 4.0 | 951 | — | 2025-02 | No | No | No | No | as DS-1 | Supplemental — listing dates, boards |
| DS-11 lensetek | yfinance daily | contradictory | 95 | 2010-01-04 | 2026-07-01 | Yes (adjusted) | No | No | Yes | Zenodo DOI | Not selected (small, licence contradiction) |
| DS-12 qywok | yfinance daily | MIT (declared) | 183 | 2023-01-02 | 2026-06-11 | Yes (adjusted) | No | No | No | HF | Not selected (short) |
| DS-13 suspension labels | yearly status | CC BY 4.0 | 936 | 2014 | 2023 | No | No | No | No | research dataset | Supplemental — labels only |
| DS-19 Kaggle datasets | various | various | — | — | — | — | — | — | — | — | **RESTRICTED — NOT USED FOR DEVELOPMENT** |

### 36.7 Selected development sources

**Core development source — daily OHLCV:** DS-4 Pholenk/IDX-Dataset
(2020-01-02 → 2026-05-29, 983 tickers, raw IDX-format prices, ODbL). Selected
for development because it is the only full-universe, IDX-format source found
with an explicit open-data licence and the longest recent range. This is **not**
a production selection.

**Supplemental development sources**

| Need | Source | Scope / caveat |
| --- | --- | --- |
| Cross-check OHLCV | DS-1 (and DS-2 for 2025-02 → 2026-05) | Disagreement on 9 dates in 2024 (§36.5) |
| Pre-2020 history | DS-5 | 2000–2019-04, **split-adjusted Yahoo basis**, licence unclear. Gap 2019-04-09 → 2019-07-26 to DS-1 and a different price basis: **not to be stitched** onto raw IDX data without adjustment factors. |
| IHSG | DS-4 `COMPOSITE` (2020+); DS-6 (1995+, Yahoo) | Agree within 0.754% on overlap |
| Dividends | DS-7 | Gross/net not stated; payment date 45% missing; no record date |
| Corporate actions | DS-9 `corporateActions.json` | Share counts and listing dates; no ex-date or exercise price, so rights adjustments are not computable from it alone |
| Security metadata | DS-1 `List Emiten`, DS-10, DS-9 company profiles | No ISIN; no delisting dates |
| Ticker history | none found | Gap |
| Suspensions | Heuristic only: high = low = volume = 0 in DS-4/DS-1 (documented as the suspension marker in DS-1's column notes) | Not distinguishable from "no trades"; DS-13 gives yearly labels only |

### 36.8 Limitations and production gaps

* **History:** the full-universe raw IDX-format data starts **2019-07-29**
  (DS-1) or **2020-01-02** (DS-4). Production MUST (2015-01-01) is **not**
  met by raw data; 2015–2019 exists only as Yahoo split-adjusted data (DS-5).
* **Delisted securities:** DS-4 has 24 tickers whose last date is before
  2026-05-01 (e.g. APOL, BORN, CKRA, FINN, GREN, ITTG); whether each was
  delisted, suspended, or renamed is **not recorded**. DS-1's
  `delisting_date` column is empty for all rows.
* **Open prices** missing for most rows before 2025.
* **Ticker changes, ISINs, suspension dates, rights terms:** not available
  from any development source.
* **Dividends:** gross vs net unknown; payment dates incomplete.
* **Licensing:** IDX-derived data is subject to IDX's non-commercial,
  no-scraping terms (as quoted by DS-1); DS-1/DS-2 are NonCommercial; DS-4
  is ODbL (share-alike applies if a derived database is ever publicly used
  or distributed); DS-5, DS-7, DS-8 have no licence; DS-6, DS-11, DS-12 are
  Yahoo-derived. **None of these satisfy production requirements M1/M11.**
* **Provenance of collection:** DS-8's collector uses browser impersonation
  against IDX endpoints; DS-2's extension comes from an undocumented local
  API. These are recorded, not endorsed.
* **Reproducibility:** repositories change; development ingestion must pin
  the commit SHA and archive checksum (§36.6) and store the raw files with
  provenance (§22).

### 36.9 Provider-neutral interface

`data/ingestion/provider.py` defines the minimal contract
(`MarketDataProvider`: `list_securities`, `get_daily_prices`, `get_dividends`,
`get_corporate_actions`, `get_index_history`) and immutable record types that
each carry mandatory `Provenance` (§22). It fixes three semantics the
development data showed to be necessary: `open` is optional (missing opens);
`price_basis` distinguishes raw from adjusted; `trading_status` distinguishes
traded / no trades / suspended / unknown. **No provider is implemented.**

### 36.10 Development source links (checked 2026-09-24)

| # | URL |
| --- | --- |
| DS-1 | https://github.com/wildangunawan/Dataset-Saham-IDX |
| DS-2 | https://github.com/KAnggara75/Dataset-Saham-IDX |
| DS-3 | https://github.com/KAnggara75/Dataset-Saham-IDX-SQL |
| DS-4 | https://github.com/Pholenk/IDX-Dataset · mirror https://www.kaggle.com/datasets/pholenk/eod-data-indonesia-stock-exchange |
| DS-5 | https://github.com/faisalburhanudin/idx |
| DS-6 | https://huggingface.co/datasets/theonegareth/daily-IHSG |
| DS-7 | https://github.com/dimasirginsyh/indonesia-stock-dividends |
| DS-8 | https://github.com/mitbal/daguerreo-data |
| DS-9 | https://github.com/nichsedge/idx-bei |
| DS-10 | https://huggingface.co/datasets/kjhq/Indonesia-Stock-Symbols-and-Metadata |
| DS-11 | https://github.com/lensetek/idx-panel-data-descriptor · https://zenodo.org/records/21110404 |
| DS-12 | https://huggingface.co/datasets/qywok/indonesia_stocks |
| DS-13 | https://github.com/nauraazalia/idx-prolonged-suspension-dataset |
| DS-14 | https://github.com/nofendian17/idx_dataset |
| DS-15 | https://github.com/SeedFlora/idx-daily-data |
| DS-16 | https://zenodo.org/records/20603320 |
| DS-17 | https://zenodo.org/records/20739308 · https://zenodo.org/records/18276107 |
| DS-18 | https://zenodo.org/records/17626537 |
| DS-19 | https://www.kaggle.com/datasets/eren2222/complete-indonesia-stock-exchange-idx-2000-2024 · https://www.kaggle.com/datasets/eren2222/indonesia-stock-exchange-idx-historical-price · https://www.kaggle.com/datasets/muamkh/ihsgstockdata · https://www.kaggle.com/datasets/bestagi/indonesia-stock-marketidx-price-data · https://www.kaggle.com/datasets/garethharrison/daily-ihsg |
| DS-20 | https://github.com/NeaByteLab/IDX-API · https://github.com/basnugroho/indonesia-stocks-scraper · https://github.com/kubil-ismail/indonesia-stock-exchange · https://github.com/alukito/idx-data |

### 36.11 Phase 2A implementation findings (DS-4, revision `9bb3b26`, 2026-09-24)

Verified from the files themselves, before and during implementation of
`data/ingestion/pholenk.py`. These refine §36.4–§36.5; no earlier measurement
was contradicted (the provider's report reproduces 1,289,820 rows, 983
securities, 2020-01-02 → 2026-05-29, 0 duplicates, 1,045,981 missing opens,
156,317 zero-volume rows, 0 invalid OHLC, 0 negative volume).

* **Structure:** 983 files `dataset/stocks/csv/<KEY>.csv`, one identical
  26-column header, UTF-8 with BOM, rows **newest first**, dates always
  `YYYY-MM-DD`, prices as decimals, volume and value as integers. KEY is 4
  characters except `GOTOM`, `MAMIP`, `MYRXP`.
* **Exactly three row patterns:** traded with `Open = 0` (889,664); traded
  with open present (243,839); `Volume = 0`, `High = Low = Open = 0`, `Close =
  Previous` (156,317). No mixed patterns occur.
* **Close on zero-volume rows repeats the previous close.** It is a carried
  reference price, not a trade; `trading_status` marks these rows.
* **Source defect:** `TRUE.csv` has `Ticker = "True"` in all 1,188 rows (the
  ticker was coerced to a boolean string upstream). The provider uses the file
  key and logs the mismatch; any other ticker mismatch is rejected.
* **Name changes:** 78 files contain more than one company name; the newest
  row's name is used for `Security.name`.
* **`Remarks`** is a 30- or 8-character code string. Its encoding is not
  documented; it is kept in the raw layer and **not interpreted** (it was not
  found to separate suspension from no trading).
