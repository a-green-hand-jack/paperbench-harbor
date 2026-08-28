from __future__ import annotations

from pathlib import Path


class LeakageError(RuntimeError):
    """Raised when verifier-only material appears in the writer environment."""


def audit_forbidden_names(public_root: Path, forbidden_names: set[str]) -> None:
    """Fail conversion if a public task tree contains a forbidden filename."""

    leaked = [
        path
        for path in public_root.rglob("*")
        if path.is_file() and path.name in forbidden_names
    ]
    if leaked:
        rendered = "\n".join(f"- {path}" for path in leaked)
        raise LeakageError(f"Verifier-only files leaked into the public environment:\n{rendered}")
