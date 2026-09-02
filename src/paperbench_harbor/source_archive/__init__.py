"""Immutable source-archive registry construction and verification."""

from paperbench_harbor.source_archive.registry import (
    SourceArchiveError,
    build_source_archive,
    validate_source_archive,
)
from paperbench_harbor.source_archive.release_gate import validate_release_provenance

__all__ = [
    "SourceArchiveError",
    "build_source_archive",
    "validate_release_provenance",
    "validate_source_archive",
]
