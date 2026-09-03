"""Where a task's bytes came from, discovered rather than declared.

The existing audit checks a hand-written transform table: "this task file comes
from that upstream file", hashed on both ends. Its whole value is that the
table was transcribed independently of the converter, so the two can be
compared. That is also its cost -- the table is a second hand-maintained copy
of every benchmark's layout, and onboarding a benchmark means writing it again.

Replacing the table with a `UpstreamLayoutSpec` would destroy the property, not
preserve it: an audit derived from the same spec the converter used checks the
spec against itself.

This module moves the independence somewhere it survives that. The
correspondence between a task file and its upstream origin is **recovered from
content**, not read from a declaration:

- every upstream file under the paper directory is indexed by SHA-256;
- every writer-visible task file is looked up in that index;
- a file whose bytes appear upstream is *shown* to be a faithful copy of it,
  whatever any table claims;
- a file whose bytes appear nowhere upstream is either declared generated or is
  a finding.

Nothing here consults a converter, a spec, or a transform table to decide what
a file's source is. A spec is then compared against what the bytes say -- the
two disagree loudly, which is exactly what a second opinion is for.

What this cannot do, and why the leakage checks stay
----------------------------------------------------
Content addressing answers "did these bytes come from upstream, unmodified". It
cannot answer "should the writer be able to see them" -- ground truth staged
into the writer environment is a perfect content match to its upstream source.
The verifier-only and forbidden-name checks in :mod:`.audit` remain the
authority there, and this module is deliberately additive.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from paperbench_harbor.fidelity.transforms import classify_generated_vendor, sha256


@dataclass(frozen=True)
class Origin:
    """One task file, and the upstream paths whose bytes match it."""

    target: str
    #: Every upstream path with these exact bytes. Usually one; more when the
    #: corpus itself contains duplicates (an empty `__init__.py`, a LICENSE
    #: vendored twice), which is a fact about the corpus, not an error.
    sources: tuple[str, ...]

    @property
    def is_upstream(self) -> bool:
        return bool(self.sources)


@dataclass
class OriginReport:
    """What the bytes say about one task's writer-visible surface."""

    #: Task files shown to be byte-identical to some upstream file.
    from_upstream: dict[str, Origin] = field(default_factory=dict)
    #: Task files whose bytes appear nowhere upstream, and which the shared
    #: generated/vendor classifier does not already account for.
    unexplained: list[str] = field(default_factory=list)
    #: Task files the classifier accounts for (rendered templates, vendored
    #: styles, the sidecar). Not checked against upstream by design.
    generated_or_vendor: list[str] = field(default_factory=list)

    @property
    def checked(self) -> int:
        return len(self.from_upstream) + len(self.unexplained) + len(self.generated_or_vendor)


def index_by_content(root: Path) -> dict[str, list[str]]:
    """SHA-256 -> every path under `root` with those bytes.

    Symlinks are followed rather than skipped. `is_file()` already returns
    False for a link whose target is gone -- the real hazard in upstream
    `code/` trees, which are verbatim third-party checkouts -- while a live
    link is a file the task genuinely contains. Skipping links outright would
    also make this blind to any Hugging Face cache checkout, where every file
    is a link into `blobs/`.
    """
    index: dict[str, list[str]] = {}
    if not root.is_dir():
        return index
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        index.setdefault(sha256(path), []).append(path.relative_to(root).as_posix())
    return index


def _writer_files(task_dir: Path) -> Iterable[tuple[str, Path]]:
    root = task_dir / "environment"
    if not root.is_dir():
        return []
    return sorted(
        (f"environment/{path.relative_to(root).as_posix()}", path)
        for path in root.rglob("*")
        if path.is_file()
    )


def _matches_generated(rel_path: str, generated: Iterable[str]) -> bool:
    """Whether a spec-declared generated target covers ``rel_path``.

    A trailing slash denotes a generated or vendored subtree. Keeping that
    convention here lets the global classifier stay genuinely cross-benchmark.
    """
    return any(
        rel_path == pattern or (pattern.endswith("/") and rel_path.startswith(pattern))
        for pattern in generated
    )


def derive_origins(
    task_dir: Path,
    paper_dir: Path,
    *,
    generated: Iterable[str] = (),
) -> OriginReport:
    """Recover each writer-visible file's upstream origin from its bytes.

    `generated` names the benchmark's own generated writer-visible files, on top
    of what `classify_generated_vendor` already covers for every benchmark.

    A file the classifier accounts for is settled before its content is looked
    up at all. Content addressing has one systematic false positive -- an empty
    file matches every other empty file -- and generated trees are full of them:
    `environment/texmf/.keep` is zero bytes, and so is many an upstream
    `__init__.py`, so asking where `.keep`'s bytes came from produced a
    confident wrong answer on 29 of the 51 published tasks. Where a file is
    known to be produced, its origin is not a question worth asking.
    """
    index = index_by_content(paper_dir)
    exempt = tuple(generated)
    report = OriginReport()
    for rel, path in _writer_files(task_dir):
        if classify_generated_vendor(rel) or _matches_generated(rel, exempt):
            report.generated_or_vendor.append(rel)
            continue
        sources = index.get(sha256(path))
        if sources:
            report.from_upstream[rel] = Origin(target=rel, sources=tuple(sources))
        else:
            report.unexplained.append(rel)
    return report


def compare_to_expectation(
    report: OriginReport,
    expected: dict[str, Path],
    paper_dir: Path,
    *,
    rewritable: Iterable[str] = (),
) -> list[str]:
    """Check a spec's predicted copies against what the bytes actually show.

    This is the second opinion, and it only means something because the two
    sides were produced differently: `expected` comes from a declaration, the
    report comes from hashing files. Three ways they can disagree, all findings:

    - the spec predicts a file the task does not have;
    - the spec names a source whose bytes are not the ones that landed;
    - a task file has upstream bytes the spec never claimed, which is
      undeclared upstream content reaching the writer.

    `rewritable` exempts targets a documented safeguard may have edited. The
    exemption is narrow on purpose: the file must still be present, it must
    still be one the spec predicted, and only its bytes are allowed to differ.
    """
    rewritable = set(rewritable)
    findings: list[str] = []
    for target, source in sorted(expected.items()):
        origin = report.from_upstream.get(target)
        if origin is None:
            if target in report.unexplained:
                if target in rewritable:
                    continue
                findings.append(f"content mismatch: {target} has no upstream byte match")
                continue
            if target in report.generated_or_vendor:
                findings.append(
                    f"spec predicts an upstream copy but the bytes are generated: {target}"
                )
            else:
                findings.append(f"spec predicts a file the task does not have: {target}")
            continue
        try:
            declared = source.resolve().relative_to(paper_dir.resolve()).as_posix()
        except ValueError:
            findings.append(f"spec names a source outside the paper directory: {source}")
            continue
        if declared not in origin.sources:
            findings.append(
                f"spec names {declared} but the bytes came from {', '.join(origin.sources)}: {target}"
            )
    for target in sorted(set(report.from_upstream) - set(expected)):
        findings.append(f"undeclared upstream content in the writer environment: {target}")
    return findings
