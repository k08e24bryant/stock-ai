"""Phase 2C-2: event/dividend loaders, adjustment factors, adjusted series.

Pure tests need no database. Database tests (``integration``) run in the
throwaway ``migrated_database``; the development database is never touched.

The price fixture has 70 filler securities, so that a single corporate
action stays below the 5% market-wide threshold, as in the real market, plus
these special cases (D1 = 2024-01-02, D2 = 2024-01-03, D3 = 2024-01-04):

| Key | Case |
| --- | --- |
| SPLT | 1:5 split on D2 (DS-9 ``stockSplit`` on D2) → factor 0.2, ``split`` |
| RGHT | reference 400 vs close 500 on D2; DS-9 ``hmetd`` on D2+17 → ``rights`` |
| UNCL | factor 0.5 on D2; the only DS-9 event is 40 days later → ``unclassified`` |
| SPAN | split on D3, a market-wide anomaly date; same-day DS-9 split → applied |
| DIVD | cash dividend 10 with ex-date D2 (traded) |
| DIVS | cash dividend 4 with ex-date D2, not traded on D2 → reinvested on D3 |
| F00–F05 | reference ≠ previous close on D3 → D3 is an anomaly date (8.1%) |
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session
from test_ingestion_loader import TABLES, build_snapshot, load, no_trade, row

from backend.models import (
    AdjustmentBuild,
    CashDividend,
    CorporateActionEvent,
    DataQualityIncident,
    IngestionRun,
    PriceAdjustmentFactor,
    ReferencePriceAnomalyDate,
)
from data.features import adjustment_factors
from data.features.adjusted_prices import adjust, load_adjusted_series
from data.features.adjustment_factors import compare_with_stored, derive, write_build
from data.ingestion import load_snapshot, records
from data.ingestion.idx_bei_actions import IdxBeiActionsSource, parse_actions
from data.ingestion.idx_dividends import IdxDividendsSource, parse_dividends
from data.ingestion.loader import LoadFailedError, LoadNotConfirmedError
from data.ingestion.records import (
    RecordLoader,
    dry_run_records,
    prepare_record_snapshot,
)
from data.ingestion.snapshot import StructuralError

D1, D2, D3 = "2024-01-02", "2024-01-03", "2024-01-04"
DS9_REV, DS7_REV = "9" * 40, "7" * 40
PRICE_SOURCE = "pholenk-idx-dataset"
Rows = list[dict[str, str]]

# --------------------------------------------------------------------------
# Fixtures: prices
# --------------------------------------------------------------------------


def bar(day: str, key: str, close: int, reference: int) -> dict[str, str]:
    c, r = f"{close}.0", f"{reference}.0"
    return row(
        Date=day, Ticker=key, Name=f"{key} Tbk.", Previous=r, Open="0.0", High=c, Low=c, Close=c
    )


def halt(day: str, key: str, close: int) -> dict[str, str]:
    c = f"{close}.0"
    return no_trade(Date=day, Ticker=key, Name=f"{key} Tbk.", Close=c, Previous=c)


def price_universe() -> dict[str, Rows]:
    stocks: dict[str, Rows] = {}
    for i in range(70):
        key = f"F{i:02d}"
        d3_reference = 90 if i < 6 else 100  # F00-F05 disagree on D3
        stocks[key] = [
            bar(D3, key, 100, d3_reference),
            bar(D2, key, 100, 100),
            bar(D1, key, 100, 100),
        ]
    stocks["SPLT"] = [
        bar(D3, "SPLT", 205, 210),
        bar(D2, "SPLT", 210, 200),
        bar(D1, "SPLT", 1000, 1000),
    ]
    stocks["RGHT"] = [
        bar(D3, "RGHT", 420, 420),
        bar(D2, "RGHT", 420, 400),
        bar(D1, "RGHT", 500, 500),
    ]
    stocks["UNCL"] = [
        bar(D3, "UNCL", 160, 160),
        bar(D2, "UNCL", 160, 150),
        bar(D1, "UNCL", 300, 300),
    ]
    stocks["SPAN"] = [
        bar(D3, "SPAN", 410, 400),
        bar(D2, "SPAN", 800, 800),
        bar(D1, "SPAN", 800, 800),
    ]
    stocks["DIVD"] = [
        bar(D3, "DIVD", 995, 990),
        bar(D2, "DIVD", 990, 1000),
        bar(D1, "DIVD", 1000, 1000),
    ]
    stocks["DIVS"] = [bar(D3, "DIVS", 198, 200), halt(D2, "DIVS", 200), bar(D1, "DIVS", 200, 200)]
    return stocks


# --------------------------------------------------------------------------
# Fixtures: DS-9 events and DS-7 dividends
# --------------------------------------------------------------------------


def event(record_id: int, key: str, day: str, label: str) -> dict[str, Any]:
    return {
        "id": record_id,
        "KodeEmiten": key,
        "TanggalPencatatan": f"{day}T00:00:00",
        "JenisTindakan": label,
        "JumlahSaham": 1000.0,
        "JumlahSahamSetelahTindakan": 5000.0,
    }


def ds9_categories() -> dict[str, list[dict[str, Any]]]:
    return {
        "stockSplit": [
            event(1, "SPLT", D2, "stockSplit"),
            event(2, " span", D3, "stockSplit"),  # whitespace and case as in the real ' PPRE'
        ],
        "hmetd": [
            event(3, "RGHT", "2024-01-20", "hmetd"),
            event(4, "UNCL", "2024-02-12", "hmetd"),  # 40 days after: outside the window
            event(5, "ZZZZ", D2, "hmetd"),  # not in the price universe
        ],
    }


def write_ds9(root: Path, categories: dict[str, list[dict[str, Any]]], rev: str = DS9_REV) -> Path:
    (root / "data").mkdir(parents=True, exist_ok=True)
    doc = {
        "totalRecordsAllTypes": sum(len(v) for v in categories.values()),
        "categories": {k: {"count": len(v), "data": v} for k, v in categories.items()},
    }
    (root / "data" / "corporateActions.json").write_text(json.dumps(doc), encoding="utf-8")
    (root / "LICENSE").write_text("MIT License\n", encoding="utf-8")
    _manifest(root, "nichsedge-idx-bei", rev)
    return root


def div(ex: str, amount: str, payment: str | None = "2024-02-01") -> dict[str, Any]:
    return {
        "dividend": amount,
        "dividend_type": "final",
        "ex_date": ex,
        "fiscal_year": "2023",
        "payment_date": payment,
    }


def ds7_records() -> dict[str, list[dict[str, Any]]]:
    return {
        "DIVD.JK": [div(D2, "10"), div("2023-06-01", "8")],  # the second predates the data
        "DIVS.JK": [div(D2, "4.0", payment="2024-02-1")],  # malformed optional payment_date
        "ZZZZ.JK": [div(D2, "5")],
    }


def write_ds7(root: Path, dividends: dict[str, list[dict[str, Any]]], rev: str = DS7_REV) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "all_dividends.json").write_text(json.dumps(dividends), encoding="utf-8")
    (root / "README.md").write_text("# dividends\n", encoding="utf-8")
    _manifest(root, "dimasirginsyh-idx-dividends", rev)
    return root


def _manifest(
    root: Path, source_id: str, rev: str, retrieved: str = "2026-09-25T08:49:07Z"
) -> None:
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "source_id": source_id,
                "source_url": "https://example.invalid",
                "revision": rev,
                "archive_sha256": "0" * 64,
                "retrieved_at": retrieved,
                "licence": "test fixture",
            }
        ),
        encoding="utf-8",
    )


# --------------------------------------------------------------------------
# Parsers and dry runs (no database)
# --------------------------------------------------------------------------


def test_actions_parser_keeps_source_values_and_normalizes_only_the_match_key() -> None:
    records = [event(7, " pPre", D2, "stockSplit")]
    doc = {"totalRecordsAllTypes": 1, "categories": {"stockSplit": {"count": 1, "data": records}}}
    [record] = parse_actions(json.dumps(doc).encode())
    assert record.match_key == "PPRE"
    assert record.values is not None and record.values["source_ticker"] == " pPre"
    assert record.values["registration_date"] == date(2024, 1, 3)
    assert record.values["shares_after"] == Decimal("5000.0")
    assert record.record_ref == "categories.stockSplit.data[0]"


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda d: d["categories"]["hmetd"].__setitem__("count", 99), "count 99"),
        (lambda d: d.__setitem__("totalRecordsAllTypes", 99), "totalRecordsAllTypes"),
        (lambda d: d.pop("categories"), "categories"),
    ],
)
def test_actions_parser_structural_errors(
    mutate: Callable[[dict[str, Any]], object], message: str
) -> None:
    categories = ds9_categories()
    doc: dict[str, Any] = {
        "totalRecordsAllTypes": 5,
        "categories": {k: {"count": len(v), "data": v} for k, v in categories.items()},
    }
    mutate(doc)
    with pytest.raises(StructuralError, match=message):
        parse_actions(json.dumps(doc).encode())


def test_actions_parser_quarantines_a_bad_record() -> None:
    bad = event(8, "SPLT", D2, "stockSplit") | {"TanggalPencatatan": "2024-01-03T09:00:00"}
    doc = {"totalRecordsAllTypes": 1, "categories": {"stockSplit": {"count": 1, "data": [bad]}}}
    [record] = parse_actions(json.dumps(doc).encode())
    assert record.values is None and "unexpected date" in record.reasons[0]


def test_dividend_parser_keeps_malformed_optional_field_as_null() -> None:
    results = {r.record_ref: r for r in parse_dividends(json.dumps(ds7_records()).encode())}
    divs = results["DIVS.JK[0]"]
    assert divs.values is not None and divs.values["payment_date"] is None
    assert divs.issues == (
        {"field": "payment_date", "raw": "2024-02-1", "reason": divs.issues[0]["reason"]},
    )
    divd = results["DIVD.JK[0]"]
    assert divd.values is not None
    assert (divd.values["amount"], divd.values["amount_basis"], divd.match_key) == (
        Decimal("10"),
        "unstated",
        "DIVD",
    )
    bad = parse_dividends(json.dumps({"X.JK": [div(D2, "-1")]}).encode())
    assert bad[0].values is None and "not a positive amount" in bad[0].reasons[0]


def test_record_snapshot_identity_ignores_retrieval_time(tmp_path: Path) -> None:
    a = prepare_record_snapshot(IdxDividendsSource(), write_ds7(tmp_path / "a", ds7_records()))
    b_root = write_ds7(tmp_path / "b", ds7_records())
    _manifest(b_root, "dimasirginsyh-idx-dividends", DS7_REV, retrieved="2030-01-01T00:00:00Z")
    b = prepare_record_snapshot(IdxDividendsSource(), b_root)
    assert a.snapshot_id == b.snapshot_id
    assert [e.row_count for e in a.entries if e.relative_path == "all_dividends.json"] == [4]
    (b_root / "all_dividends.json").unlink()
    with pytest.raises(StructuralError, match="data files missing"):
        prepare_record_snapshot(IdxDividendsSource(), b_root)


def test_record_dry_run_is_deterministic_and_database_free(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = write_ds9(tmp_path / "ds9", ds9_categories())
    prepared = prepare_record_snapshot(IdxBeiActionsSource(), root)
    assert json.dumps(dry_run_records(prepared), sort_keys=True, default=str) == json.dumps(
        dry_run_records(prepared), sort_keys=True, default=str
    )

    def forbidden() -> None:
        raise AssertionError("the database must not be touched")

    monkeypatch.setattr("backend.database.get_engine", forbidden)
    assert load_snapshot.main(["idx-bei-actions", str(root)]) == 0
    assert json.loads(capsys.readouterr().out)["counters"]["records_accepted"] == 5
    assert load_snapshot.main(["idx-bei-actions", str(root), "--execute"]) == 2
    assert load_snapshot.main(["idx-bei-actions", str(root), "--expect-stock-files", "3"]) == 2


# --------------------------------------------------------------------------
# Adjusted series (pure)
# --------------------------------------------------------------------------


def test_adjust_split_dividend_and_reliability() -> None:
    rows = [
        (date(2024, 1, 2), Decimal("1000"), Decimal("1000")),
        (date(2024, 1, 3), Decimal("210"), Decimal("200")),  # 1:5 split
        (date(2024, 1, 4), Decimal("220"), Decimal("210")),  # dividend 11 reinvested
    ]
    bars = adjust(
        rows,
        price_factors={date(2024, 1, 3): Decimal("0.2")},
        dividends={date(2024, 1, 4): (Decimal("220") / Decimal("231"), Decimal("11"))},
        anomaly_dates={date(2024, 1, 3)},
    )
    assert [b.adj_close for b in bars] == [Decimal("200.0"), Decimal("210"), Decimal("220")]
    assert bars[1].price_return == Decimal("0.05")  # never the raw -79%
    assert bars[2].total_return == (Decimal("231") / Decimal("210") - 1)
    tr = [b.tr_adj_close for b in bars]
    assert abs(tr[2] / tr[1] - 1 - bars[2].total_return) < Decimal("1e-30")  # §24 identity
    assert [b.reliable for b in bars] == [True, False, True]
    assert bars[-1].adj_close == bars[-1].close == bars[-1].tr_adj_close


# --------------------------------------------------------------------------
# Database: loaders, factors, series
# --------------------------------------------------------------------------


@pytest.fixture
def engine(migrated_database: Engine) -> Engine:
    with migrated_database.begin() as conn:
        conn.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY"))
    return migrated_database


def count(engine: Engine, model: Any, **where: Any) -> int:
    with Session(engine) as s:
        return int(s.scalar(select(func.count()).select_from(model).filter_by(**where)) or 0)


def load_records(engine: Engine, source: Any, root: Path, rev: str) -> Any:
    prepared = prepare_record_snapshot(source, root)
    return RecordLoader(engine, price_source_id=PRICE_SOURCE).load(prepared, confirm_revision=rev)


@pytest.fixture
def loaded(tmp_path: Path, engine: Engine) -> dict[str, Path]:
    """Prices, events, and dividends of the fixture universe, loaded."""
    roots = {
        "prices": build_snapshot(tmp_path / "prices", price_universe()),
        "ds9": write_ds9(tmp_path / "ds9", ds9_categories()),
        "ds7": write_ds7(tmp_path / "ds7", ds7_records()),
    }
    load(engine, roots["prices"])
    load_records(engine, IdxBeiActionsSource(), roots["ds9"], DS9_REV)
    load_records(engine, IdxDividendsSource(), roots["ds7"], DS7_REV)
    return roots


def security(engine: Engine, key: str) -> int:
    with engine.connect() as conn:
        return int(
            conn.execute(
                text("SELECT security_id FROM security_source_keys WHERE source_key = :k"),
                {"k": key},
            ).scalar_one()
        )


@pytest.mark.integration
def test_record_loads_link_securities_and_keep_provenance(
    loaded: dict[str, Path], engine: Engine
) -> None:
    with Session(engine) as s:
        events = {e.source_record_id: e for e in s.scalars(select(CorporateActionEvent))}
        dividends = {(d.source_ticker, d.ex_date): d for d in s.scalars(select(CashDividend))}
    assert len(events) == 5 and len(dividends) == 4
    assert (events["2"].source_ticker, events["2"].security_id) == (
        " span",
        security(engine, "SPAN"),
    )
    assert (events["5"].security_match, events["5"].security_id) == ("unmatched", None)
    assert events["1"].security_match == "ticker_text_match" and events["1"].file_id is not None
    divs = dividends[("DIVS.JK", date(2024, 1, 3))]
    assert (divs.payment_date, divs.amount, divs.amount_basis) == (None, Decimal("4"), "unstated")
    assert divs.record_ref == "DIVS.JK[0]"
    with Session(engine) as s:
        [warning] = s.scalars(
            select(DataQualityIncident).filter_by(incident_type="malformed_optional_field")
        ).all()
    assert (warning.severity, warning.details["raw"], warning.details["stored_as"]) == (
        "warning",
        "2024-02-1",
        None,
    )
    assert count(engine, IngestionRun, status="succeeded") == 3


@pytest.mark.integration
def test_record_rerun_is_idempotent_and_conflicts_are_not_overwritten(
    loaded: dict[str, Path], engine: Engine, tmp_path: Path
) -> None:
    again = load_records(engine, IdxDividendsSource(), loaded["ds7"], DS7_REV)
    c = again.counters
    assert (c.rows_inserted, c.rows_unchanged, c.rows_conflicted, c.incidents_created) == (
        0,
        4,
        0,
        0,
    )
    changed = ds7_records()
    changed["DIVD.JK"][0]["dividend"] = "12"
    rev2 = "8" * 40
    v2 = load_records(engine, IdxDividendsSource(), write_ds7(tmp_path / "v2", changed, rev2), rev2)
    assert (v2.counters.rows_conflicted, v2.counters.rows_inserted) == (1, 0)
    with Session(engine) as s:
        stored = s.scalars(
            select(CashDividend).filter_by(source_ticker="DIVD.JK", ex_date=date(2024, 1, 3))
        ).one()
        [conflict] = s.scalars(
            select(DataQualityIncident).filter_by(incident_type="conflicting_observation")
        ).all()
    assert stored.amount == Decimal("10")
    assert (conflict.details["stored"]["amount"], conflict.details["incoming"]["amount"]) == (
        "10.0000000000000000",
        "12",
    )


@pytest.mark.integration
def test_record_conflicting_duplicate_is_rejected(tmp_path: Path, engine: Engine) -> None:
    load(engine, build_snapshot(tmp_path / "prices", price_universe()))
    categories = ds9_categories()
    categories["stockSplit"].append(event(1, "RGHT", D2, "stockSplit"))  # same id, other content
    result = load_records(
        engine, IdxBeiActionsSource(), write_ds9(tmp_path / "ds9", categories), DS9_REV
    )
    assert (result.counters.rows_rejected, result.counters.rows_inserted) == (2, 4)
    assert (
        count(engine, DataQualityIncident, incident_type="conflicting_duplicate_in_snapshot") == 1
    )


@pytest.mark.integration
def test_record_load_needs_confirmation_and_is_atomic(
    tmp_path: Path, engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    load(engine, build_snapshot(tmp_path / "prices", price_universe()))
    prepared = prepare_record_snapshot(
        IdxDividendsSource(), write_ds7(tmp_path / "ds7", ds7_records())
    )
    loader = RecordLoader(engine, price_source_id=PRICE_SOURCE)
    with pytest.raises(LoadNotConfirmedError):
        loader.load(prepared, confirm_revision=DS7_REV[:7])

    def boom(*args: object, **kwargs: object) -> int:
        raise RuntimeError("injected after inserts")

    monkeypatch.setattr(records, "insert_incident_drafts", boom)
    with pytest.raises(LoadFailedError, match="injected"):
        loader.load(prepared, confirm_revision=DS7_REV)
    assert count(engine, CashDividend) == 0
    assert count(engine, IngestionRun, status="failed") == 1


@pytest.mark.integration
def test_factor_derivation(loaded: dict[str, Path], engine: Engine) -> None:
    with engine.connect() as conn:
        conn.execute(text("SET TRANSACTION READ ONLY"))  # derivation only reads
        build = derive(conn)
        conn.rollback()
    assert [a["trading_date"] for a in build.anomalies] == [date(2024, 1, 4)]
    [anomaly] = build.anomalies
    assert (anomaly["mismatched_securities"], anomaly["compared_securities"]) == (7, 76)
    ids = {
        key: security(engine, key)
        for key in ("SPLT", "RGHT", "UNCL", "SPAN", "DIVD", "DIVS", "F00")
    }
    got = {(f["security_id"], f["effective_date"], f["factor_kind"]): f for f in build.factors}

    def factor(key: str, day: str, kind: str = "price") -> dict[str, Any]:
        return got[(ids[key], date.fromisoformat(day), kind)]

    assert (factor("SPLT", D2)["classification"], factor("SPLT", D2)["factor"]) == (
        "split",
        Decimal("0.2"),
    )
    assert factor("RGHT", D2)["classification"] == "rights"
    assert factor("RGHT", D2)["corporate_action_event_id"] is not None
    assert (factor("UNCL", D2)["classification"], factor("UNCL", D2)["status"]) == (
        "unclassified",
        "applied",
    )
    assert (factor("SPAN", D3)["classification"], factor("SPAN", D3)["status"]) == (
        "split",
        "applied",
    )
    assert (factor("F00", D3)["classification"], factor("F00", D3)["status"]) == (
        "unclassified",
        "excluded_market_wide_anomaly",
    )
    divd = factor("DIVD", D2, "cash_dividend")
    assert (divd["factor"], divd["dividend_amount"], divd["source_ex_date"]) == (
        Decimal("0.99"),
        Decimal("10"),
        date(2024, 1, 3),
    )
    divs = factor("DIVS", D3, "cash_dividend")  # postponed: not traded on the ex-date
    assert divs["source_ex_date"] == date(2024, 1, 3)
    assert abs(divs["factor"] - Decimal(198) / Decimal(202)) < Decimal("1e-26")
    assert (ids["DIVD"], date(2024, 1, 3), "price") not in got  # IDX does not adjust for cash
    counts = build.summary["counts"]
    assert counts["dividend.skipped_before_first_row"] == 1
    assert counts["dividend.postponed_to_next_traded_day"] == 1
    assert build.report()["factors_sha256"] == derive_report_digest(engine)


def derive_report_digest(engine: Engine) -> str:
    with engine.connect() as conn:
        digest = str(derive(conn).report()["factors_sha256"])
        conn.rollback()
    return digest


@pytest.mark.integration
def test_write_verify_and_rebuild(loaded: dict[str, Path], engine: Engine) -> None:
    with engine.begin() as conn:
        build = derive(conn)
        write_build(conn, build)
    stored = count(engine, PriceAdjustmentFactor)
    assert stored == len(build.factors) and count(engine, ReferencePriceAnomalyDate) == 1
    with engine.connect() as conn:
        assert compare_with_stored(conn, derive(conn)) == {
            "factors_missing": 0,
            "factors_extra": 0,
            "factors_differing": 0,
            "anomaly_dates_differing": 0,
        }
        conn.rollback()
    with engine.begin() as conn:  # rebuild replaces, never duplicates
        write_build(conn, derive(conn))
    assert count(engine, PriceAdjustmentFactor) == stored
    assert count(engine, AdjustmentBuild) == 2
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE price_adjustment_factors SET factor = factor * 2 "
                "WHERE factor_kind = 'price' AND classification = 'split'"
            )
        )
    with engine.connect() as conn:
        assert compare_with_stored(conn, derive(conn))["factors_differing"] == 2
        conn.rollback()


@pytest.mark.integration
def test_adjusted_series_from_the_database(loaded: dict[str, Path], engine: Engine) -> None:
    with engine.begin() as conn:
        write_build(conn, derive(conn))
    with engine.connect() as conn:
        split = load_adjusted_series(conn, security(engine, "SPLT"))
        dividend = load_adjusted_series(conn, security(engine, "DIVD"))
        anomaly = load_adjusted_series(conn, security(engine, "F00"))
    assert [b.adj_close for b in split] == [
        Decimal("200.0000"),
        Decimal("210.0000"),
        Decimal("205.0000"),
    ]
    assert split[1].price_return == Decimal("0.05")
    assert dividend[1].total_return == 0 and dividend[1].price_return == Decimal("-0.01")
    assert dividend[1].dividend == Decimal("10")
    assert [b.reliable for b in anomaly] == [True, True, False]
    assert anomaly[0].adj_close == Decimal("100.0000")  # excluded factor is not applied


@pytest.mark.integration
def test_factor_cli_modes(
    loaded: dict[str, Path], engine: Engine, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("backend.database.get_engine", lambda: engine)
    assert adjustment_factors.main([]) == 0  # dry run
    assert count(engine, PriceAdjustmentFactor) == 0
    assert adjustment_factors.main(["--verify"]) == 1  # nothing stored yet
    assert adjustment_factors.main(["--execute"]) == 0
    report = tmp_path / "verify.json"
    assert adjustment_factors.main(["--verify", "--report", str(report)]) == 0
    assert json.loads(report.read_text(encoding="utf-8"))["differences"]["factors_missing"] == 0


@pytest.mark.integration
def test_record_verification_passes_then_detects_tampering(
    loaded: dict[str, Path], engine: Engine
) -> None:
    from data.validation.verify_load import verify_records

    for source, root in ((IdxBeiActionsSource(), "ds9"), (IdxDividendsSource(), "ds7")):
        report = verify_records(engine, prepare_record_snapshot(source, loaded[root]), deep=True)
        assert report.ok, [(c.group, c.name, c.expected, c.actual) for c in report.failures]
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE cash_dividends SET amount = amount + 1 "
                "WHERE source_ticker = 'DIVD.JK' AND ex_date = '2024-01-03'"
            )
        )
    prepared = prepare_record_snapshot(IdxDividendsSource(), loaded["ds7"])
    failures = {
        f"{c.group}.{c.name}": c.actual
        for c in verify_records(engine, prepared, deep=True).failures
    }
    assert failures == {"rows.observation_differs": 1}
