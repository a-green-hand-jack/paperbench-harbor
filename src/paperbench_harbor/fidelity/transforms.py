"""Machine-readable source-to-Harbor transform declarations.

This module captures, for each benchmark, how upstream source files map to the
generated Harbor task tree. Every Harbor file must be accounted for by exactly
one transform (copy / rename / move / generated / vendor), and every upstream
writer-visible file must have a declared target. The audit consumes these
declarations to verify SHA-256 equality for content-preserving transforms and
to reject any undeclared or semantically different mapping.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

TransformKind = Literal["copy", "rename", "move", "generated", "vendor"]

KIND_COPY = "copy"
KIND_RENAME = "rename"
KIND_MOVE = "move"
KIND_GENERATED = "generated"
KIND_VENDOR = "vendor"

# Generated / vendored files that legitimately live in a task but carry no
# upstream benchmark content. Matching is by exact relative path or subtree.
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
    "environment/paper_orchestra/",
    "environment/paper_orchestra_search/",
    "environment/materials/conference_template/",
    "tests/vendor/",
)
_VENDOR_SUFFIXES = (".sty", ".bst")


def classify_generated_vendor(rel_path: str) -> bool:
    """Return True when a task file is a known generated/vendor artifact.

    Such files carry no upstream benchmark content and are exempt from
    upstream byte-equality, but they must still be accounted for so that no
    undeclared writer-visible file can silently appear.
    """
    if rel_path in _GENERATED_EXACT:
        return True
    if any(rel_path.startswith(prefix) for prefix in _VENDOR_PREFIXES):
        return True
    return "/texmf/" in rel_path and rel_path.endswith(_VENDOR_SUFFIXES)


@dataclass(frozen=True)
class FileTransform:
    """Declares how one Harbor file was produced from upstream.

    `target` is the Harbor-relative path, `source` the upstream-relative path
    when the transform is content-preserving. `kind` classifies the transform;
    `generated` and `vendor` entries carry a `note` describing their origin.
    """

    kind: TransformKind
    target: str
    source: str | None = None
    note: str = ""

    def to_dict(self) -> dict[str, str | None]:
        return {
            "kind": self.kind,
            "target": self.target,
            "source": self.source,
            "note": self.note,
        }


@dataclass(frozen=True)
class VerifierEntry:
    """Maps one upstream verifier-only source to its Harbor private copies.

    `expected_in_writer` marks upstream files that are intentionally also part
    of the writer-visible surface (for example PWB figure/table summaries, which
    the writer receives and the evaluator also consumes). For those entries the
    private copy is still checked byte-for-byte, but they are exempt from the
    leakage assertion.
    """

    upstream: str  # upstream-relative path
    targets: tuple[str, ...]  # Harbor-relative paths
    note: str = ""
    expected_in_writer: bool = False


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative_files(root: Path) -> list[str]:
    """Return sorted relative POSIX paths of all files under `root`."""
    if not root.is_dir():
        return []
    return sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    )


def _copy_transform(
    upstream_root: Path, source: str, task_dir: Path, target: str
) -> FileTransform:
    """Build a content-preserving transform, verifying the source exists."""
    src = upstream_root / source
    if not src.is_file():
        raise FileNotFoundError(f"declared upstream source missing: {src}")
    return FileTransform(kind=KIND_COPY, target=target, source=source)


def _directory_copy_transforms(
    upstream_root: Path, source_dir: str, task_dir: Path, target_dir: str
) -> list[FileTransform]:
    """Declare copy transforms for every file under an upstream directory."""
    transforms: list[FileTransform] = []
    for rel in _relative_files(upstream_root / source_dir):
        target = f"{target_dir.rstrip('/')}/{rel}"
        transforms.append(_copy_transform(upstream_root, f"{source_dir}/{rel}", task_dir, target))
    return transforms


# --------------------------------------------------------------------------- #
# PaperWrite-Bench (short)
# --------------------------------------------------------------------------- #

_PWB_PUBLIC_RESOURCE_FILES = (
    "template.tex",
    "references.bib",
    "figure_summary.txt",
    "table_summary.txt",
)
_PWB_PUBLIC_RESOURCE_DIRS = ("figures", "tables", "code")
_PWB_OVERVIEW_FILENAMES = {
    "short": "research_overview_short.md",
    "long": "research_overview_long.md",
}
_PWB_PRIVATE_RESOURCE_FILES = ("eval_points.json",)


def pwb_writer_transforms(
    upstream_root: Path,
    paper_id: str,
    task_dir: Path,
    overview: str,
) -> list[FileTransform]:
    """Declare all writer-visible transforms for one PWB task."""
    paper_dir = upstream_root / paper_id
    resources = paper_dir / "resources"
    prefix = f"{paper_id}"
    transforms: list[FileTransform] = []

    overview_source = _PWB_OVERVIEW_FILENAMES[overview]
    transforms.append(
        FileTransform(
            kind=KIND_RENAME,
            target="environment/materials/research_overview.md",
            source=f"{prefix}/resources/{overview_source}",
            note="selected overview variant renamed to canonical name",
        )
    )
    for filename in _PWB_PUBLIC_RESOURCE_FILES:
        source = f"{prefix}/resources/{filename}"
        target = f"environment/materials/{filename}"
        if (resources / filename).is_file():
            transforms.append(_copy_transform(upstream_root, source, task_dir, target))
    for dirname in _PWB_PUBLIC_RESOURCE_DIRS:
        transforms.extend(
            _directory_copy_transforms(
                upstream_root,
                f"{prefix}/resources/{dirname}",
                task_dir,
                f"environment/materials/{dirname}",
            )
        )
    transforms.append(
        FileTransform(
            kind=KIND_GENERATED,
            target="environment/materials/AGENTS.md",
            note="rendered from adapters/paperwrite_bench/agents_md/AGENTS_<type>.md",
        )
    )
    return transforms


def pwb_verifier_entries(
    upstream_root: Path,
    paper_id: str,
    task_dir: Path,
    overview: str,
) -> list[VerifierEntry]:
    """Map PWB verifier-only upstream sources to their private Harbor copies."""
    paper_dir = upstream_root / paper_id
    original = paper_dir / "original"
    resources = paper_dir / "resources"
    prefix = f"{paper_id}"
    entries: list[VerifierEntry] = []

    for filename in ("main.tex", "main.pdf", "config.yaml"):
        if (original / filename).is_file():
            entries.append(
                VerifierEntry(
                    upstream=f"{prefix}/original/{filename}",
                    targets=(f"solution/private/{filename}",),
                    note="ground-truth source copy",
                )
            )
    for filename in _PWB_PRIVATE_RESOURCE_FILES:
        if (resources / filename).is_file():
            entries.append(
                VerifierEntry(
                    upstream=f"{prefix}/resources/{filename}",
                    targets=(f"solution/private/{filename}", f"tests/private/{filename}"),
                    note="private evaluation fixture",
                )
            )
    non_selected = _PWB_OVERVIEW_FILENAMES["long" if overview == "short" else "short"]
    if (resources / non_selected).is_file():
        entries.append(
            VerifierEntry(
                upstream=f"{prefix}/resources/{non_selected}",
                targets=(f"tests/private/{non_selected}",),
                note="non-selected overview variant kept verifier-only",
            )
        )
    if (original / "main.tex").is_file():
        entries.append(
            VerifierEntry(
                upstream=f"{prefix}/original/main.tex",
                targets=("tests/private/ground_truth.tex",),
                note="ground truth for evaluator",
            )
        )
    for filename in ("figure_summary.txt", "table_summary.txt"):
        if (resources / filename).is_file():
            entries.append(
                VerifierEntry(
                    upstream=f"{prefix}/resources/{filename}",
                    targets=(f"tests/private/{filename}",),
                    note="evaluator coverage summary",
                    # These files are also part of the writer-visible surface
                    # (PUBLIC_RESOURCE_FILES), so their presence in the writer
                    # environment is expected, not a leak.
                    expected_in_writer=True,
                )
            )
    return entries


# --------------------------------------------------------------------------- #
# LifeSci-PaperRecon (biology corpus, short/long overview)
# --------------------------------------------------------------------------- #

#: Benchmark name written into `task.toml`/`source_manifest.json` by the
#: converter for the biology corpus.
LSPR_BENCHMARK = "LifeSci-PaperRecon"

#: The biology corpus has no `eval_points.json`: the pilot ships the binary
#: Harbor smoke check only and the rubric evaluator is deferred. It does carry
#: an extra verifier-only `original/provenance.json` recording the arXiv id,
#: version, license and fetch date each sample was derived from.
_LSPR_PRIVATE_ORIGINAL_FILES = ("main.tex", "main.pdf", "config.yaml", "provenance.json")


def lspr_writer_transforms(
    upstream_root: Path,
    paper_id: str,
    task_dir: Path,
    overview: str,
) -> list[FileTransform]:
    """Declare all writer-visible transforms for one LifeSci-PaperRecon task.

    The writer surface is structurally identical to PaperWrite-Bench's because
    the biology corpus is built into the same generic layout and wrapped by the
    same converter; only the provenance of `AGENTS.md` differs (this repo's own
    biology instructions rather than PaperRecon's).
    """

    transforms = pwb_writer_transforms(upstream_root, paper_id, task_dir, overview)
    return [
        FileTransform(
            kind=KIND_GENERATED,
            target=transform.target,
            note=(
                "rendered from adapters/lifesci_paperrecon/agents_md/"
                "AGENTS_<type>.md"
            ),
        )
        if transform.target == "environment/materials/AGENTS.md"
        else transform
        for transform in transforms
    ]


def lspr_verifier_entries(
    upstream_root: Path,
    paper_id: str,
    task_dir: Path,
    overview: str,
) -> list[VerifierEntry]:
    """Map LifeSci-PaperRecon verifier-only sources to their private copies."""
    paper_dir = upstream_root / paper_id
    original = paper_dir / "original"
    resources = paper_dir / "resources"
    prefix = f"{paper_id}"
    entries: list[VerifierEntry] = []

    for filename in _LSPR_PRIVATE_ORIGINAL_FILES:
        if not (original / filename).is_file():
            continue
        if filename == "provenance.json":
            # Swept into the ground-truth tree by the converter's copytree of
            # original/, not into solution/private/.
            entries.append(
                VerifierEntry(
                    upstream=f"{prefix}/original/{filename}",
                    targets=(f"tests/private/ground_truth_sources/{filename}",),
                    note="construction provenance (arXiv id, version, license, fetch date)",
                )
            )
            continue
        entries.append(
            VerifierEntry(
                upstream=f"{prefix}/original/{filename}",
                targets=(f"solution/private/{filename}",),
                note="ground-truth source copy",
            )
        )

    non_selected = _PWB_OVERVIEW_FILENAMES["long" if overview == "short" else "short"]
    if (resources / non_selected).is_file():
        entries.append(
            VerifierEntry(
                upstream=f"{prefix}/resources/{non_selected}",
                targets=(f"tests/private/{non_selected}",),
                note="non-selected overview variant kept verifier-only",
            )
        )
    if (original / "main.tex").is_file():
        entries.append(
            VerifierEntry(
                upstream=f"{prefix}/original/main.tex",
                targets=("tests/private/ground_truth.tex",),
                note="ground truth for the oracle and any future evaluator",
            )
        )
    for filename in ("figure_summary.txt", "table_summary.txt"):
        if (resources / filename).is_file():
            entries.append(
                VerifierEntry(
                    upstream=f"{prefix}/resources/{filename}",
                    targets=(f"tests/private/{filename}",),
                    note="coverage summary",
                    expected_in_writer=True,
                )
            )
    return entries


# --------------------------------------------------------------------------- #
# PaperWritingBench (sparse-plotoff)
# --------------------------------------------------------------------------- #

_PWBW_PUBLIC_FILES = ("idea_sparse.md", "experimental_log.md")


def _pwbw_prefix(venue: str, paper_id: str) -> str:
    """Upstream-relative directory prefix for a PaperWritingBench paper."""
    return f"{venue}/papers/{paper_id}"


def pwbw_writer_transforms(
    upstream_root: Path,
    paper_id: str,
    task_dir: Path,
    venue: str,
) -> list[FileTransform]:
    """Declare all writer-visible transforms for one PWBW task."""
    paper_dir = upstream_root / venue / "papers" / paper_id
    raw = paper_dir / "raw_materials"
    prefix = _pwbw_prefix(venue, paper_id)
    transforms: list[FileTransform] = []

    for filename in _PWBW_PUBLIC_FILES:
        if (raw / filename).is_file():
            transforms.append(
                _copy_transform(
                    upstream_root,
                    f"{prefix}/raw_materials/{filename}",
                    task_dir,
                    f"environment/materials/{filename}",
                )
            )
    transforms.extend(
        _directory_copy_transforms(
            upstream_root,
            f"{prefix}/raw_materials/figures",
            task_dir,
            "environment/materials/figures",
        )
    )
    # Conference template files are bundled from this repo's packaging tree
    # (vendor), not from upstream paper data; classify_generated_vendor() covers
    # every file under environment/materials/conference_template/.
    return transforms


def pwbw_verifier_entries(
    upstream_root: Path,
    paper_id: str,
    task_dir: Path,
    venue: str,
) -> list[VerifierEntry]:
    """Map PWBW verifier-only upstream sources to their private Harbor copies."""
    paper_dir = upstream_root / venue / "papers" / paper_id
    raw = paper_dir / "raw_materials"
    prefix = _pwbw_prefix(venue, paper_id)
    entries: list[VerifierEntry] = []

    for pdf in sorted(paper_dir.glob("*.pdf")):
        rel = f"{prefix}/{pdf.name}"
        entries.append(
            VerifierEntry(
                upstream=rel,
                targets=(f"solution/private/{pdf.name}", f"tests/private/{pdf.name}"),
                note="original paper PDF",
            )
        )
    if (raw / "idea_dense.md").is_file():
        entries.append(
            VerifierEntry(
                upstream=f"{prefix}/raw_materials/idea_dense.md",
                targets=("solution/private/idea_dense.md", "tests/private/idea_dense.md"),
                note="dense variant kept verifier-only",
            )
        )
    for source in sorted(raw.glob("original_paper_gt_citations_*.json")):
        entries.append(
            VerifierEntry(
                upstream=f"{prefix}/raw_materials/{source.name}",
                targets=(f"solution/private/{source.name}", f"tests/private/{source.name}"),
                note="ground-truth citation cache",
            )
        )
    return entries
