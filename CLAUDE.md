# CLAUDE.md

## Project: Stock Intelligence & Quantitative Decision-Support System

## 1. Project Overview

This project is a quantitative stock intelligence and decision-support system focused primarily on Indonesian equities.

The system is NOT intended to be a simple "stock price predictor" or an automated system that blindly outputs BUY/SELL recommendations.

Its purpose is to combine:

* Fundamental analysis
* Valuation analysis
* Technical analysis
* News analysis
* NLP
* Government and policy events
* Social and political sentiment
* Sector relationships
* Historical event studies
* Machine learning
* Risk management
* Backtesting

The final system should explain WHY a stock may be interesting, WHAT could affect it, HOW the current valuation compares with reasonable estimates, and WHAT risks could invalidate the thesis.

The system should prioritize evidence, reproducibility, explainability, and prevention of data leakage.

---

# 2. Core Philosophy

Follow these principles throughout the entire project.

### 2.1 Do not build a black-box stock predictor

Avoid designs such as:

```text
News → Neural Network → BUY
```

Prefer:

```text
Raw Data
    ↓
Feature Engineering
    ↓
Fundamental / Valuation / Technical / Event Analysis
    ↓
Statistical Evidence
    ↓
Machine Learning
    ↓
Risk Analysis
    ↓
Explainable Output
```

Machine learning is one component of the system, not the entire system.

---

### 2.2 Separate different questions

The system must distinguish between:

1. Business quality
2. Valuation
3. Market timing
4. Event impact
5. Expected return
6. Risk

Do not collapse all of these into one arbitrary score without preserving the underlying components.

For example:

```text
Business Quality: STRONG
Valuation: UNDERVALUED
Technical: BEARISH
News: POSITIVE
Event Impact: POSITIVE
Risk: HIGH
```

This is more useful than:

```text
BUY = 87%
```

---

### 2.3 Cheap does not automatically mean attractive

A stock with a low PER or PBV is not automatically undervalued.

Consider:

* Earnings quality
* Earnings growth
* ROE
* Debt
* Cash flow
* Industry conditions
* Cyclicality
* Future growth
* Business quality

---

### 2.4 Expensive does not automatically mean unattractive

A high valuation can sometimes reflect:

* High expected growth
* Strong profitability
* Competitive advantages
* Strong balance sheet
* High-quality recurring cash flow

The system must evaluate valuation in context.

---

### 2.5 Never predict the exact future price as the primary objective

Prefer probabilistic and scenario-based outputs.

Examples:

```text
Probability of positive 5-day return
Expected 5-day return
Expected drawdown
Risk/reward
Fair value range
Bear/Base/Bull scenarios
```

Avoid presenting a single future price as if it were certain.

---

# 3. Main System Architecture

The conceptual architecture is:

```text
                    STOCK INTELLIGENCE SYSTEM
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
        ▼                     ▼                     ▼
   FUNDAMENTAL           VALUATION              MARKET
    ANALYSIS              ENGINE                ANALYSIS
        │                     │                     │
 Revenue Growth          Historical PER       Price
 Profit Growth            Historical PBV       Volume
 EPS Growth               Peer Valuation       Momentum
 ROE                      DCF                  Volatility
 Debt                     FCF Yield            Technical
 Cash Flow                Earnings Multiple
        │                     │                     │
        └─────────────────────┼─────────────────────┘
                              │
                              ▼
                     EVENT INTELLIGENCE
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
            NEWS          GOVERNMENT        MACRO
          SENTIMENT         POLICY          EVENTS
              │               │               │
              └───────────────┼───────────────┘
                              ▼
                       ENTITY / SECTOR
                          EXPOSURE
                              │
                              ▼
                       HISTORICAL EVENT
                            STUDY
                              │
                              ▼
                     MACHINE LEARNING
                              │
                              ▼
                        RISK ENGINE
                              │
                              ▼
                      SIGNAL / REPORT
                              │
                ┌─────────────┴─────────────┐
                ▼                           ▼
            DASHBOARD                    ALERTS
```

---

# 4. Fundamental Analysis

The fundamental engine should evaluate company quality.

Potential features include:

### Profitability

* ROE
* ROA
* Net profit margin
* Operating margin
* Gross margin
* EBITDA margin

### Growth

* Revenue growth
* Net income growth
* EPS growth
* FCF growth
* Historical CAGR

### Financial Health

* Debt-to-equity
* Net debt
* Interest coverage
* Current ratio
* Cash balance

### Cash Flow

* Operating cash flow
* Free cash flow
* FCF margin
* FCF conversion

### Dividend

* Dividend yield
* Dividend payout ratio
* Dividend growth
* Dividend consistency

The system must preserve raw financial data and calculated features separately.

---

# 5. Valuation Engine

The valuation engine is a core component of the project.

It must answer:

> "Is the current market price reasonable relative to the company's fundamentals and expected future cash generation?"

Do NOT rely on a single valuation method.

Use multiple approaches where appropriate.

## 5.1 Historical Valuation

Examples:

* Historical PER
* Historical PBV
* Historical EV/EBITDA
* Historical FCF yield

Compare current valuation with historical distributions.

Example:

```text
Historical PER
P25
Median
P75

Current PER
```

---

## 5.2 Peer Valuation

Compare companies within relevant industries.

Potential metrics:

* PER
* PBV
* EV/EBITDA
* EV/EBIT
* P/FCF
* ROE
* Revenue growth
* Earnings growth
* Net margin

Do not conclude that a lower multiple automatically means cheaper in an economically meaningful sense.

---

## 5.3 DCF

For suitable companies, implement Discounted Cash Flow valuation.

Support:

* Revenue assumptions
* Margin assumptions
* Tax assumptions
* Capex
* Working capital
* Free cash flow
* WACC / discount rate
* Terminal growth

Output scenarios:

```text
Bear Case
Base Case
Bull Case
```

---

## 5.4 Earnings-Based Valuation

For appropriate companies:

```text
Expected EPS × Reasonable Multiple
```

The reasonable multiple should be based on historical valuation, peers, growth, profitability, and business characteristics.

---

## 5.5 Fair Value Range

Do not output only:

```text
Fair Value = Rp1,823
```

Prefer:

```text
Current Price: Rp1,500

Bear Case: Rp1,250
Base Case: Rp1,850
Bull Case: Rp2,300
```

The system must store the assumptions behind each scenario.

---

# 6. Technical Analysis

Technical analysis is used primarily for market timing and confirmation.

Potential features:

* SMA20
* SMA50
* SMA200
* EMA
* RSI
* MACD
* ATR
* Bollinger Bands
* Momentum
* Volatility
* Volume ratio
* Breakout detection
* Support/resistance distance
* Gap
* Relative strength versus sector
* Relative strength versus market index

Do not allow technical indicators to override fundamental or event analysis without explicit logic.

---

# 7. News Intelligence

The system should collect legally accessible news data through appropriate APIs, feeds, RSS sources, or permitted public sources.

Respect:

* Terms of service
* Robots.txt
* Copyright
* Rate limits
* Data licensing

Do not build a scraper that violates website restrictions.

Every news item must preserve its original publication timestamp.

Critical rule:

## Publication time matters.

The system must know whether information was available:

* Before market open
* During market hours
* After market close

Never use information that was not available at the time of a historical trading decision.

---

# 8. NLP Engine

The NLP pipeline should eventually support:

### Sentiment Analysis

Classify sentiment such as:

```text
Positive
Neutral
Negative
```

But sentiment alone is insufficient.

---

### Named Entity Recognition

Identify:

* Companies
* Government institutions
* Politicians/public officials when relevant to the event
* Industries
* Commodities
* Countries
* Products
* Locations

---

### Event Classification

Potential event categories:

```text
Government Policy
Tax
Subsidy
Export Regulation
Import Regulation
Interest Rate
Monetary Policy
Fiscal Policy
Commodity Policy
Corporate Earnings
Dividend
Acquisition
Merger
Contract
Legal Issue
Regulatory Action
Geopolitical Event
Supply Disruption
Demand Shock
Management Change
```

---

# 9. Event Intelligence

This is one of the most important parts of the project.

The system should transform:

```text
News
↓
Event
↓
Economic mechanism
↓
Affected sector
↓
Affected companies
↓
Expected direction
↓
Historical reaction
```

Example:

```text
Government increases biodiesel mandate
        ↓
Domestic CPO demand potentially increases
        ↓
Palm oil sector
        ↓
Relevant plantation companies
        ↓
Historical event analysis
        ↓
Current valuation
        ↓
Current technical condition
```

Do not assume that a positive event automatically means every related stock rises.

The system must consider:

* Exposure
* Magnitude
* Existing expectations
* Current valuation
* Commodity prices
* Margins
* Policy implementation
* Company-specific exposure
* Market regime

---

# 10. Event Knowledge Graph

The system should eventually represent relationships such as:

```text
Government
    ↓
Policy
    ↓
Economic Mechanism
    ↓
Commodity / Industry
    ↓
Sector
    ↓
Company
    ↓
Stock
```

Example:

```text
Government
   ↓
Biodiesel Mandate
   ↓
CPO Domestic Demand
   ↓
Palm Oil Industry
   ↓
AALI / LSIP / TAPG
```

The relationships must be stored in a structured and explainable form.

Do not hardcode relationships directly inside business logic when they should exist as data.

---

# 11. Event Study

Historical event studies are required before claiming that an event has predictive value.

For similar historical events, calculate:

* 1-day return
* 3-day return
* 5-day return
* 10-day return
* Maximum drawdown
* Maximum favorable excursion
* Abnormal return
* Sector-relative return
* Market-relative return

Compare against:

* IHSG / relevant market benchmark
* Relevant sector index
* Matched non-event periods when appropriate

The system should answer:

```text
How did similar events historically affect this sector/company?
```

Not:

```text
This event guarantees the stock will rise.
```

---

# 12. Market Regime

Detect broader market conditions.

Potential regimes:

```text
BULL
BEAR
SIDEWAYS
HIGH_VOLATILITY
LOW_VOLATILITY
```

Potential inputs:

* Market index trend
* Volatility
* Breadth
* Sector performance
* Market momentum
* Volume
* Correlations

Signals should be interpreted differently depending on regime.

---

# 13. Machine Learning

Machine learning should be introduced only after reliable non-ML baselines exist.

Start with:

1. Logistic Regression
2. Random Forest
3. XGBoost
4. LightGBM

Deep learning should only be introduced when there is a clear reason.

Potential targets:

```text
P(return > 0 over 1D)
P(return > 0 over 5D)
Expected 5D return
Expected drawdown
```

Potential features:

```text
Fundamental
Valuation
Technical
News sentiment
Event impact
Sector performance
Market regime
Volatility
Volume
Momentum
```

---

# 14. Time-Series Validation

NEVER randomly shuffle financial time-series data for normal train/test evaluation.

Use:

* Time-based train/test split
* Walk-forward validation
* Expanding window
* Rolling window where appropriate

Example:

```text
Train: 2018-2022
Validation: 2023
Test: 2024

Then walk forward.
```

Historical data must only use information that would actually have been available at that point in time.

---

# 15. Data Leakage Prevention

This is a critical project requirement.

Never allow future information into historical features.

Examples of leakage:

```text
Using annual financial statements
before their publication date

Using revised data that was unavailable at the time

Using future stock prices in feature engineering

Using news published after the trading decision

Using today's company universe to test historical performance
```

All time-sensitive data should have appropriate timestamps.

Prefer:

```text
event_time
publication_time
available_at
effective_date
```

where applicable.

---

# 16. Survivorship Bias

Historical backtesting should account for companies that:

* Were delisted
* Were suspended
* Merged
* Changed ticker
* Were acquired
* Had corporate actions

Do not construct a historical universe using only today's surviving companies if that creates survivorship bias.

---

# 17. Corporate Actions

Historical price data must correctly handle:

* Stock splits
* Reverse splits
* Rights issues
* Dividends where relevant
* Bonus shares
* Corporate actions

Do not blindly mix adjusted and unadjusted prices.

Document which price series is used for:

* Return calculation
* Trading simulation
* Chart display

---

# 18. Signal Engine

The final signal engine should combine evidence from multiple modules.

Conceptually:

```text
Fundamental
+
Valuation
+
Technical
+
News
+
Event
+
Sector
+
Market Regime
+
ML
+
Risk
```

Output should remain explainable.

Example:

```text
STOCK ANALYSIS

Business Quality: STRONG
Valuation: UNDERVALUED
Technical: NEUTRAL
News: POSITIVE
Event Impact: POSITIVE
Market Regime: BULLISH
Risk: MEDIUM

Fair Value:
Bear: Rp1,250
Base: Rp1,850
Bull: Rp2,300

Current Price:
Rp1,500

Model:
Probability of positive 5D return: 64%

Key Drivers:
- Positive policy event
- Strong earnings growth
- Valuation below historical median

Key Risks:
- Commodity price decline
- Margin compression
- Policy implementation uncertainty
```

Do not create arbitrary confidence scores.

If probabilities are displayed, they must come from a properly defined and preferably calibrated model.

---

# 19. Risk Engine

Risk management is mandatory.

Potential calculations:

* Position sizing
* Stop distance
* ATR-based risk
* Maximum portfolio exposure
* Sector exposure
* Correlation
* Liquidity
* Maximum drawdown
* Risk/reward
* Expected loss

Never assume that a high expected return automatically justifies a large position.

---

# 20. Backtesting

Every strategy must be backtested before paper trading.

Include:

* Transaction fees
* Taxes where applicable
* Slippage
* Spread
* Liquidity constraints
* Position size
* Entry timing
* Exit timing
* Corporate actions
* Suspensions where relevant

Metrics:

```text
Total Return
CAGR
Maximum Drawdown
Sharpe Ratio
Sortino Ratio
Win Rate
Profit Factor
Turnover
Average Trade
Expected Value
Volatility
```

Always compare against relevant benchmarks.

---

# 21. Paper Trading

Before any real-money automation:

```text
Backtest
   ↓
Walk-forward validation
   ↓
Paper trading
   ↓
Monitor
   ↓
Review
```

Do not implement autonomous real-money trading as an early milestone.

---

# 22. Database

PostgreSQL should be the primary relational database.

Potential tables:

```text
companies
prices
financials
financial_publications
corporate_actions
news
news_entities
news_sentiment
events
event_company_exposure
event_studies
technical_features
valuation_metrics
valuation_scenarios
market_regimes
ml_predictions
signals
backtest_runs
portfolio_positions
```

Database design should prioritize:

* Referential integrity
* Timestamps
* Reproducibility
* Historical versioning where needed
* Query performance
* Clear relationships

---

# 23. Technology Stack

Preferred stack:

### Backend

* Python
* FastAPI
* Pydantic
* SQLAlchemy

### Database

* PostgreSQL
* Redis

### Data / Analytics

* pandas
* NumPy
* SciPy
* scikit-learn

### Machine Learning

* XGBoost
* LightGBM
* PyTorch
* Hugging Face Transformers

### NLP

* Transformer-based models
* Indonesian-language models where appropriate

### Task Processing

* Celery or another appropriate task queue

### Frontend

* Next.js
* TypeScript

### Infrastructure

* Docker
* Docker Compose

Do not add technologies without a clear reason.

---

# 24. Development Environment

The primary development environment is Windows.

The project should be designed to run locally first.

Use Docker for services such as:

```text
PostgreSQL
Redis
```

Do not require every component to run continuously.

The local machine is primarily:

```text
Development
Testing
Backtesting
Model experimentation
Research
```

24/7 automation can be deployed to cloud infrastructure later.

---

# 25. Project Structure

Prefer a structure similar to:

```text
stock-ai/
│
├── CLAUDE.md
├── CONTEXT.md
├── PROJECT_PLAN.md
├── README.md
├── pyproject.toml
├── .env.example
├── docker-compose.yml
│
├── backend/
│   ├── api/
│   ├── models/
│   ├── schemas/
│   └── services/
│
├── data/
│   ├── ingestion/
│   ├── cleaning/
│   ├── validation/
│   └── features/
│
├── ml/
│   ├── sentiment/
│   ├── classification/
│   ├── prediction/
│   └── training/
│
├── valuation/
│
├── event_engine/
│
├── backtesting/
│   ├── engine/
│   ├── strategies/
│   └── metrics/
│
├── database/
│   ├── migrations/
│   └── schemas/
│
├── workers/
│
├── dashboard/
│
└── tests/
```

The exact structure may evolve.

Do not reorganize the entire project without a clear reason.

---

# 26. Development Roadmap

Build incrementally.

## Phase 1 — Environment

Set up:

* Python
* Virtual environment
* Git
* Docker
* PostgreSQL
* Redis
* Basic project structure

Do not build ML yet.

---

## Phase 2 — Market Data

Implement:

* Historical OHLCV
* Company metadata
* Data validation
* PostgreSQL storage

---

## Phase 3 — Fundamental Data

Implement:

* Financial statements
* Publication timestamps
* Fundamental metrics
* Fundamental analysis

---

## Phase 4 — Valuation Engine

Implement:

* Historical multiples
* Peer valuation
* Earnings valuation
* DCF
* Bear/Base/Bull scenarios
* Fair value ranges

---

## Phase 5 — Technical Analysis

Implement:

* Indicators
* Trend
* Momentum
* Volatility
* Volume
* Relative strength

---

## Phase 6 — News Intelligence

Implement:

* News ingestion
* Deduplication
* Publication timestamps
* Entity extraction
* Sentiment
* Event classification

---

## Phase 7 — Event Intelligence

Implement:

* Event taxonomy
* Company exposure
* Sector exposure
* Economic mechanism
* Event knowledge graph

---

## Phase 8 — Historical Event Study

Implement:

* Event windows
* Abnormal returns
* Sector comparison
* Market comparison
* Historical event statistics

---

## Phase 9 — Machine Learning

Implement:

* Baseline models
* Feature dataset
* Time-series validation
* Walk-forward validation
* Calibration
* Model evaluation

---

## Phase 10 — Risk Engine

Implement:

* Position sizing
* Stop logic
* Risk/reward
* Portfolio exposure
* Liquidity constraints

---

## Phase 11 — Backtesting

Integrate all components and perform realistic backtests.

---

## Phase 12 — Dashboard

Create a dashboard showing:

* Market regime
* Top events
* Valuation
* Fundamental quality
* Technical condition
* News sentiment
* Event impact
* ML predictions
* Risk
* Historical evidence

---

## Phase 13 — Paper Trading

Only after the system has passed sufficient validation.

---

# 27. Claude Code Working Rules

You are acting as a senior software engineer and quantitative research assistant.

Follow these rules:

### Rule 1

Do not implement the entire project at once.

Work milestone by milestone.

### Rule 2

Before changing the architecture, inspect the current repository.

### Rule 3

Before implementing a new feature, explain:

```text
What
Why
Where
How
```

Keep the explanation concise.

### Rule 4

After implementation:

1. Run tests.
2. Run lint/type checks where configured.
3. Verify imports.
4. Verify database migrations if applicable.
5. Report what changed.
6. Report any remaining issues.

### Rule 5

Do not silently modify unrelated files.

### Rule 6

Do not delete existing functionality without explaining why.

### Rule 7

Do not invent financial data.

If a required data source is unavailable, clearly state it.

### Rule 8

Do not assume a data source is legally or technically suitable.

Check documentation, licensing, API limitations, and terms when relevant.

### Rule 9

Prefer simple, testable implementations before sophisticated implementations.

### Rule 10

Do not introduce machine learning when a deterministic/statistical baseline has not been implemented.

### Rule 11

Every model feature must have a clear definition and timestamp semantics.

### Rule 12

Every backtest must explicitly document assumptions.

### Rule 13

Never use future information in historical analysis.

### Rule 14

Never claim a model is profitable merely because one backtest looks good.

### Rule 15

Do not produce fake precision.

Avoid arbitrary outputs such as:

```text
BUY confidence = 93.72%
```

unless the number has a defensible statistical interpretation.

---

# 28. Code Quality

Prefer:

* Type hints
* Small functions
* Clear module boundaries
* Pydantic models
* Configuration through environment variables
* Unit tests
* Integration tests
* Logging
* Structured errors
* Reproducible experiments

Avoid:

* Giant functions
* Hardcoded secrets
* Hardcoded API keys
* Hidden global state
* Unexplained magic numbers
* Duplicate business logic

---

# 29. Secrets

Never commit:

```text
API keys
Passwords
Database credentials
Tokens
Private credentials
```

Use:

```text
.env
```

and provide:

```text
.env.example
```

The `.env` file must be in `.gitignore`.

---

# 30. Documentation

Every major module should have documentation explaining:

* Purpose
* Inputs
* Outputs
* Assumptions
* Data sources
* Limitations
* Example usage

Important financial assumptions must be documented.

---

# 31. Research Standards

When researching financial or economic concepts:

* Prefer primary sources
* Verify important claims
* Record data source
* Record retrieval/publication date where relevant
* Distinguish facts from assumptions
* Distinguish model output from factual information

Do not present model predictions as facts.

---

# 32. Final Product Philosophy

The final product should behave like an analytical research assistant.

A user should be able to select a stock and see:

```text
1. What is this company?
2. How strong is the business?
3. Is the current valuation relatively high or low?
4. What is the estimated fair-value range?
5. What assumptions drive that valuation?
6. What is happening technically?
7. What recent events matter?
8. Which sectors/companies are affected?
9. How did similar events affect the market historically?
10. What does the ML model estimate?
11. What are the key risks?
12. What evidence supports the analysis?
```

The system should prioritize transparency over flashy predictions.

The goal is not to create an oracle.

The goal is to create a reproducible, explainable, evidence-driven quantitative stock intelligence system.

---

# 33. First Task

When starting work in this repository:

1. Inspect the repository.
2. Identify the current state of the project.
3. Do not immediately implement the complete system.
4. Create or update:

   * `CONTEXT.md`
   * `PROJECT_PLAN.md`
   * `README.md`
5. Propose the initial architecture.
6. Identify missing decisions, especially data sources.
7. Set up the minimal development environment.
8. Run basic validation.
9. Report what was created and why.
10. Stop before implementing advanced functionality.

Do not start with ML, trading automation, or a dashboard.

Start with a clean and reproducible foundation.
