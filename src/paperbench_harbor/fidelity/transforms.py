"""Shared generated-file classification and content hashing for fidelity checks.

Benchmark layout no longer lives here.  Converters stage declared copies from
``adapters.spec`` and fidelity compares that declaration to origins recovered
from actual bytes.  Keeping only cross-benchmark Harbor artifacts in this
module prevents a second, hand-maintained benchmark path table from drifting
back into the implementation.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

# Harbor template files that do not encode source-benchmark material.  A
# benchmark's own generated output belongs in ``UpstreamLayoutSpec`` instead.
_GENERATED_EXACT = frozenset(
    {
        "task.toml",
        "instruction.md",
        "environment/Dockerfile",
        "environment/texmf/.keep",
        "environment/entrypoint.sh",
        "environment/paper_orchestra_sidecar.py",
        "solution/solve.sh",
        "solution/normalize.py",
        "solution/oracle_pwbw.py",
        "tests/Dockerfile",
        "tests/test.sh",
        "tests/test_state.py",
        "tests/grader_pwb.py",
        "tests/grader_pwbw.py",
        "tests/private/source_manifest.json",
    }
)
_VENDOR_PREFIXES = (
    "environment/texmf/",
    "environment/materials/conference_template/",
    "tests/vendor/",
)
_VENDOR_SUFFIXES = (".sty", ".bst")


def classify_generated_vendor(rel_path: str) -> bool:
    """Return whether a task file is a shared Harbor-generated artifact."""
    if rel_path in _GENERATED_EXACT:
        return True
    if any(rel_path.startswith(prefix) for prefix in _VENDOR_PREFIXES):
        return True
    return "/texmf/" in rel_path and rel_path.endswith(_VENDOR_SUFFIXES)


def sha256(path: Path) -> str:
    """Return a file's SHA-256 without loading large sources into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
