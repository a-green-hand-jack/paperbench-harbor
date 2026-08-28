from __future__ import annotations

from pathlib import Path


class LeakageError(RuntimeError):
    """Raised when verifier-only material appears in the writer environment."""


def audit_forbidden_names(
    public_root: Path,
    forbidden_names: set[str],
    ignore_globs: tuple[str, ...] = (),
) -> None:
    """Fail conversion if a public task tree contains a forbidden filename.

    `ignore_globs` are pathlib-style patterns relative to `public_root` whose
    matches are exempt, e.g. ("materials/code/**",) for public source trees.
    """

    patterns: list[str] = []
    for glob in ignore_globs:
        if glob.endswith("/**"):
            base = glob[:-3]
            patterns.extend((base, f"{base}/*", f"{base}/**/*"))
        else:
            patterns.append(glob)
    ignored_paths = {
        path
        for pattern in patterns
        for path in public_root.glob(pattern)
    }
    leaked = [
        path
        for path in public_root.rglob("*")
        if path.is_file() and path not in ignored_paths and path.name in forbidden_names
    ]
    if leaked:
        rendered = "\n".join(f"- {path}" for path in leaked)
        raise LeakageError(f"Verifier-only files leaked into the public environment:\n{rendered}")
