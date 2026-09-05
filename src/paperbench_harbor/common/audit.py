from __future__ import annotations

from pathlib import Path


class LeakageError(RuntimeError):
    """Raised when verifier-only material appears in the writer environment."""


def audit_public_materials(public_root: Path, *, code_prefix: str, code_approved: bool) -> None:
    from paperbench_harbor.adapters.paperwrite_bench.spec import SPEC

    if public_root.is_symlink() or any(p.is_symlink() for p in public_root.rglob("*")):
        raise ValueError("public symlink material")
    code = public_root / code_prefix
    if code.exists() and not code_approved:
        raise ValueError("public code lacks pinned approved provenance")
    try:
        audit_forbidden_names(
            public_root, set(SPEC.forbidden_public_names) | {"provenance.json"},
            ignore_globs=(f"{code_prefix}/**",) if code_approved else (),
        )
    except LeakageError as error:
        raise ValueError(str(error)) from error


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
