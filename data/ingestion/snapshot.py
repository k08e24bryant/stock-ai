"""Provider-agnostic snapshot identity and file inventory.

Purpose
    Build the file inventory of a local, immutable dataset snapshot and derive
    its deterministic identity, as specified in
    docs/data_sources/phase_2b_ingestion_design.md §1–§2.

Inputs
    A snapshot directory and a source-specific classifier (file roles).

Outputs
    `InventoryEntry` records, the snapshot `content_sha256`, and the
    deterministic `snapshot_id`.

Assumptions
    * Identity = source + revision + content hash. Retrieval time is **not**
      part of identity; the retrieval manifest (which contains it) is excluded
      from the inventory.
    * A file's SHA-256 is computed from the exact bytes read; callers parse
      from those same bytes.

Limitations
    Local files only; nothing is downloaded here.

Example
    >>> derive_snapshot_id("src", "rev1", "a" * 64)
    'src:rev1:aaaaaaaaaaaaaaaa'
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path

MANIFEST_NAME = "manifest.json"


class FileRole(StrEnum):
    """What a snapshot file is used for."""

    STOCK = "stock"
    INDEX = "index"
    PREVIEW = "preview"
    OTHER = "other"


class StructuralError(ValueError):
    """The snapshot's structure is not what the parser supports; loading stops."""


@dataclass(frozen=True, slots=True)
class SnapshotManifest:
    """Retrieval metadata recorded when the snapshot was downloaded."""

    source_id: str
    source_url: str
    revision: str
    archive_sha256: str | None
    retrieved_at: datetime
    licence_reference: str


@dataclass(frozen=True, slots=True)
class InventoryEntry:
    """One file of a snapshot, identified by its path and content hash."""

    relative_path: str
    sha256: str
    size_bytes: int
    role: FileRole
    row_count: int
    source_key: str | None


def read_bytes(path: Path) -> bytes:
    """Read a whole file. The single place file bytes are read (observable in tests)."""
    return path.read_bytes()


def sha256_hex(data: bytes) -> str:
    """SHA-256 of exactly these bytes."""
    return hashlib.sha256(data).hexdigest()


def list_snapshot_files(root: Path) -> list[str]:
    """All files under `root` (POSIX relative paths, sorted), excluding the manifest."""
    if not root.is_dir():
        raise StructuralError(f"snapshot directory {root} does not exist")
    paths = [
        p.relative_to(root).as_posix()
        for p in root.rglob("*")
        if p.is_file() and p.relative_to(root).as_posix() != MANIFEST_NAME
    ]
    return sorted(paths, key=lambda rel: rel.encode("utf-8"))


def content_sha256(entries: Iterable[InventoryEntry]) -> str:
    """Hash of the inventory listing: sorted ``path\\0sha256\\n`` lines, UTF-8."""
    digest = hashlib.sha256()
    for entry in sorted(entries, key=lambda e: e.relative_path.encode("utf-8")):
        digest.update(f"{entry.relative_path}\0{entry.sha256}\n".encode())
    return digest.hexdigest()


def derive_snapshot_id(source_id: str, revision: str, content_hash: str) -> str:
    """Deterministic snapshot identifier (matches the database CHECK constraint)."""
    return f"{source_id}:{revision}:{content_hash[:16]}"


__all__ = [
    "MANIFEST_NAME",
    "FileRole",
    "InventoryEntry",
    "SnapshotManifest",
    "StructuralError",
    "content_sha256",
    "derive_snapshot_id",
    "list_snapshot_files",
    "read_bytes",
    "sha256_hex",
]
