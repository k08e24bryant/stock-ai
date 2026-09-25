"""Command-line entry point for snapshot dry runs and (explicit) database loads.

Purpose
    The only command path that can write a snapshot into PostgreSQL.

Usage
    Dry run (default; no database access at all)::

        python -m data.ingestion.load_snapshot pholenk data/raw/pholenk/IDX-Dataset-9bb3b26

    Record sources (``idx-bei-actions``, ``idx-dividends``) use the same flags
    and safety rules; their records are linked to the price source's
    securities by ticker text (a development heuristic, recorded per row).

    Real load (both flags required; the revision must equal the manifest's)::

        python -m data.ingestion.load_snapshot pholenk data/raw/pholenk/IDX-Dataset-9bb3b26 \\
            --expect-stock-files 983 --execute \\
            --confirm-revision 9bb3b26bd28ab46bc2f3e74a7c03805ce053301b

Safety
    * Without ``--execute`` nothing connects to the database.
    * ``--execute`` without a ``--confirm-revision`` exactly equal to the
      snapshot's full ``manifest.json`` ``revision`` (the 40-hex git SHA, not
      the short SHA in the directory name and not the ``snapshot_id``) exits
      with status 2 before any database connection.
    * `SnapshotLoader.load` independently refuses a mismatched revision.

Outputs
    A deterministic JSON report on stdout (or ``--report PATH``). Exit status 0
    on success, 1 on a failed load, 2 on refused/invalid invocation.

Example
    >>> sorted(SOURCES)
    ['pholenk']
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from data.ingestion.idx_bei_actions import IdxBeiActionsSource
from data.ingestion.idx_dividends import IdxDividendsSource
from data.ingestion.loader import (
    LoadFailedError,
    SnapshotLoader,
    SnapshotSource,
    dry_run,
    prepare_snapshot,
    report_json,
)
from data.ingestion.pholenk import SOURCE_ID as PHOLENK_SOURCE_ID
from data.ingestion.pholenk_snapshot import PholenkSnapshotSource
from data.ingestion.records import (
    PreparedRecordSnapshot,
    RecordLoader,
    RecordSource,
    dry_run_records,
    prepare_record_snapshot,
)
from data.ingestion.snapshot import StructuralError

# Daily-price sources (loaded by `SnapshotLoader`).
SOURCES: dict[str, Callable[[], SnapshotSource]] = {"pholenk": PholenkSnapshotSource}
# Record sources (loaded by `RecordLoader`, linked to a price source's keys).
RECORD_SOURCES: dict[str, Callable[[], RecordSource]] = {
    "idx-bei-actions": IdxBeiActionsSource,
    "idx-dividends": IdxDividendsSource,
}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Dry-run or load a data snapshot.")
    parser.add_argument("source", choices=sorted({*SOURCES, *RECORD_SOURCES}))
    parser.add_argument("root", type=Path, help="snapshot directory containing manifest.json")
    parser.add_argument(
        "--expect-stock-files",
        type=int,
        default=None,
        metavar="N",
        help="fail before any write unless exactly N stock files are found (Pholenk: 983)",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="write to the database (default: offline dry run, no database connection)",
    )
    parser.add_argument(
        "--confirm-revision",
        default=None,
        metavar="FULL_REVISION",
        help=(
            "required with --execute: the snapshot's full manifest.json 'revision' "
            "(e.g. the 40-hex git SHA 9bb3b26bd28ab46bc2f3e74a7c03805ce053301b), "
            "matched exactly; a short SHA such as 9bb3b26 or the snapshot_id is refused"
        ),
    )
    parser.add_argument(
        "--link-price-source",
        default=PHOLENK_SOURCE_ID,
        metavar="SOURCE_ID",
        help=(
            "record sources only: price source whose keys link records to securities "
            f"(ticker-text match, development heuristic; default {PHOLENK_SOURCE_ID})"
        ),
    )
    parser.add_argument("--report", type=Path, default=None, help="write the JSON report here")
    args = parser.parse_args(argv)

    if args.source in RECORD_SOURCES:
        return _record_main(args)

    source = SOURCES[args.source]()
    try:
        prepared = prepare_snapshot(source, args.root, expect_stock_files=args.expect_stock_files)
    except StructuralError as exc:
        print(f"structural error, nothing written: {exc}", file=sys.stderr)
        return 2

    if not args.execute:
        return _emit(dry_run(prepared), args.report)

    if args.confirm_revision != prepared.manifest.revision:
        print(
            "refusing to load: --confirm-revision must equal the snapshot revision "
            f"{prepared.manifest.revision!r}; nothing written",
            file=sys.stderr,
        )
        return 2

    from backend.database import get_engine

    try:
        result = SnapshotLoader(get_engine()).load(prepared, confirm_revision=args.confirm_revision)
    except LoadFailedError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    report = {"run_id": str(result.run_id), **result.validation_summary}
    return _emit(report, args.report)


def _record_main(args: argparse.Namespace) -> int:
    if args.expect_stock_files is not None:
        print("--expect-stock-files applies to price sources only", file=sys.stderr)
        return 2
    try:
        prepared: PreparedRecordSnapshot = prepare_record_snapshot(
            RECORD_SOURCES[args.source](), args.root
        )
    except StructuralError as exc:
        print(f"structural error, nothing written: {exc}", file=sys.stderr)
        return 2
    if not args.execute:
        return _emit(dry_run_records(prepared), args.report)
    if args.confirm_revision != prepared.manifest.revision:
        print(
            "refusing to load: --confirm-revision must equal the snapshot revision "
            f"{prepared.manifest.revision!r}; nothing written",
            file=sys.stderr,
        )
        return 2

    from backend.database import get_engine

    loader = RecordLoader(get_engine(), price_source_id=args.link_price_source)
    try:
        result = loader.load(prepared, confirm_revision=args.confirm_revision)
    except LoadFailedError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return _emit({"run_id": str(result.run_id), **result.validation_summary}, args.report)


def _emit(report: dict[str, object], path: Path | None) -> int:
    rendered = report_json(report)
    if path is None:
        print(rendered)
    else:
        path.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
