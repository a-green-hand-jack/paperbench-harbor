"""Upstream layout as data, so a converter can be driven by it rather than encode it.

Today each benchmark's layout is written down three times: imperatively in its
converter, declaratively in `fidelity/transforms.py`, and in prose in `docs/`.
All three are hand-maintained and must agree. Onboarding a fourth benchmark
means writing all three again -- measured at 550-800 hand-written lines when the
corpus can be pre-shaped into the PaperWrite-Bench layout, and 1500-2200 when it
cannot.

This module is the first step out of that: one declarative description of where
a benchmark's material lives and where it goes. Nothing consumes it as the
source of truth yet. A spec is currently *checked against* its converter -- see
`tests/test_adapter_specs.py`, which converts a fixture and asserts the spec
predicts exactly the copied files that came out. That is deliberate. The value
of the exercise is evidence that the layouts really are expressible as data
before any converter is rewritten to depend on it.

What is intentionally **not** here
----------------------------------
Not every difference between benchmarks is layout. Two things resist being data
and should stay as hooks hanging off a spec rather than fields inside one:

- PaperWrite-Bench's `_read_config()`, a bespoke parser for an upstream file
  that is not quite YAML, including a fix for merged lines like
  `column: 2columnconference: CVPR25`.
- PaperWritingBench's `_UPSTREAM_DATA_WARNINGS`, 17 human observations about
  specific upstream samples. There is nothing to derive them from.

A spec that tried to absorb those would be a worse converter, not a better
description.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

#: Placeholder in a rule's `source`, replaced by the selected protocol's file.
#: PaperWrite-Bench's `short` / `long` overviews are the only current use: the
#: same target is fed by a different upstream file per protocol.
VARIANT = "{variant}"


@dataclass(frozen=True)
class CopyRule:
    """One upstream path and where the conversion puts it.

    `source` is relative to a paper directory; `target` and `extra_targets` are
    relative to the generated task directory. A rule with `kind="tree"` copies a
    directory, and predicts every file under it.
    """

    source: str
    target: str
    kind: str = "file"
    #: Conversion fails if the source is absent. Most upstream material is
    #: optional -- a paper with no tables ships no `tables/`.
    required: bool = False
    #: Further copies of the same source. PaperWrite-Bench puts
    #: `eval_points.json` in both `solution/private/` and `tests/private/`,
    #: because the oracle and the evaluator each need it.
    extra_targets: tuple[str, ...] = ()
    #: Names never copied out of a `kind="tree"` source, matched per path
    #: segment. Build-environment residue in a verbatim third-party checkout --
    #: a `.git` directory, a bytecode cache -- describes the machine that
    #: fetched the corpus, not the paper, and the converters drop it.
    tree_excludes: tuple[str, ...] = (".git", "__pycache__")
    #: The conversion may legitimately rewrite this file, so its bytes need not
    #: match upstream. Only `template.tex`, whose `\includegraphics` of an
    #: asset the corpus does not ship is stripped rather than left to fail the
    #: oracle compile -- 4 of the 51 published PaperWrite-Bench tasks. A task
    #: where it fired also ships `upstream_data_warnings.md` saying so.
    may_be_rewritten: bool = False

    def targets(self) -> tuple[str, ...]:
        return (self.target, *self.extra_targets)


@dataclass(frozen=True)
class UpstreamLayoutSpec:
    """Where one benchmark's material lives upstream, and where it lands."""

    benchmark: str
    task_id_prefix: str
    #: Glob, relative to the source root, that enumerates candidate paper dirs.
    paper_glob: str
    #: A candidate is a paper iff this relative path exists inside it. This is
    #: the whole of "discovery" -- both converters do exactly this, and the
    #: marker is the file the conversion cannot proceed without anyway.
    discovery_marker: str
    #: Protocol name -> the upstream file that protocol selects. Empty for a
    #: benchmark with a single protocol.
    variant_sources: Mapping[str, str] = field(default_factory=dict)
    public: tuple[CopyRule, ...] = ()
    private: tuple[CopyRule, ...] = ()
    #: Names that must never appear in the writer environment. A second,
    #: independent layer over the copy rules: a rule that accidentally staged
    #: ground truth would still be caught here.
    forbidden_public_names: frozenset[str] = frozenset()
    #: Writer-visible paths the conversion *generates* rather than copies.
    #: `fidelity/transforms.classify_generated_vendor` already covers what is
    #: generated for every benchmark; these are the per-benchmark additions it
    #: does not, so a spec can account for a whole environment tree.
    generated_public: tuple[str, ...] = ()
    #: Verifier-only paths the conversion generates. `source_manifest.json` is
    #: the whole of it today: a record of upstream hashes, produced here rather
    #: than copied from anywhere.
    generated_private: tuple[str, ...] = ()

    def protocols(self) -> tuple[str, ...]:
        return tuple(self.variant_sources) or ("",)

    def resolve(self, rule: CopyRule, protocol: str) -> str:
        """A rule's source with the protocol's variant file substituted in."""
        if VARIANT not in rule.source:
            return rule.source
        try:
            return rule.source.replace(VARIANT, self.variant_sources[protocol])
        except KeyError as exc:
            raise ValueError(
                f"{self.benchmark}: unknown protocol {protocol!r}; "
                f"expected one of {sorted(self.variant_sources)}"
            ) from exc

    def unselected_variants(self, protocol: str) -> tuple[str, ...]:
        """The variant files this protocol does *not* select.

        They are verifier-only rather than merely unused: shipping the long
        overview beside the short one would hand the writer a second, richer
        description of the paper it is meant to reconstruct.
        """
        return tuple(
            source for name, source in self.variant_sources.items() if name != protocol
        )


def find_paper_dirs(spec: UpstreamLayoutSpec, source: Path) -> list[Path]:
    """Every directory under `source` that the spec recognises as a paper."""
    return sorted(
        path
        for path in source.glob(spec.paper_glob)
        if path.is_dir() and (path / spec.discovery_marker).exists()
    )


def _expand(paper_dir: Path, source: str) -> Iterable[Path]:
    """Resolve one rule source, which may be a glob.

    Globs exist because PaperWritingBench's citation caches are named after the
    paper (`original_paper_gt_citations_*.json`) and its PDF is named after the
    sample, so neither can be spelled literally.
    """
    if any(ch in source for ch in "*?["):
        return sorted(paper_dir.glob(source))
    candidate = paper_dir / source
    return [candidate] if candidate.exists() else []


def rewritable_targets(spec: UpstreamLayoutSpec) -> frozenset[str]:
    """Targets a documented conversion safeguard is allowed to have rewritten.

    Content-addressed auditing must not treat these as missing when their bytes
    do not match upstream -- that is the safeguard working, not a defect.
    """
    return frozenset(
        target
        for rule in (*spec.public, *spec.private)
        if rule.may_be_rewritten
        for target in rule.targets()
    )


def predict_copies(
    spec: UpstreamLayoutSpec,
    paper_dir: Path,
    protocol: str = "",
    *,
    private: bool = False,
) -> dict[str, Path]:
    """Task-relative path -> the upstream file the spec says it comes from.

    Only copies. Generated and vendored files are not predicted here; the audit
    already classifies those, and duplicating that classification is how the
    two descriptions drift apart.
    """
    rules = spec.private if private else spec.public
    predicted: dict[str, Path] = {}
    for rule in rules:
        resolved = spec.resolve(rule, protocol)
        matches = list(_expand(paper_dir, resolved))
        if not matches and rule.required:
            raise FileNotFoundError(f"{spec.benchmark}: required source missing: {resolved}")
        for match in matches:
            for target in rule.targets():
                if rule.kind == "tree":
                    if not match.is_dir() or not any(match.iterdir()):
                        continue
                    for item in sorted(match.rglob("*")):
                        if not item.is_file():
                            continue
                        parts = item.relative_to(match).parts
                        if any(part in rule.tree_excludes for part in parts):
                            continue
                        if item.suffix == ".pyc":
                            continue
                        predicted[f"{target}/{'/'.join(parts)}"] = item
                elif match.is_file():
                    name = match.name if target.endswith("/") else None
                    predicted[f"{target}{name}" if name else target] = match
    return predicted
