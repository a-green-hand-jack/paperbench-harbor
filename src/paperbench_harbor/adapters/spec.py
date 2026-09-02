"""Upstream layout as data, so a converter can be driven by it rather than encode it.

Today each benchmark's layout is written down three times: imperatively in its
converter, declaratively in `fidelity/transforms.py`, and in prose in `docs/`.
All three are hand-maintained and must agree. Onboarding a fourth benchmark
means writing all three again -- measured at 550-800 hand-written lines when the
corpus can be pre-shaped into the PaperWrite-Bench layout, and 1500-2200 when it
cannot.

The shared staging helper below now consumes one declarative description as the
production source of truth. Fidelity does not simply re-read that declaration:
it recovers origins from task and upstream bytes, then compares the recovered
evidence against the spec. That preserves an independent check even though the
converter has stopped maintaining a second layout table.

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

import shutil
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

    #: Restrict a rule to selected protocols. This makes the non-selected
    #: PaperWrite-Bench overview explicit verifier-only material without
    #: pretending that both variants are copied in one conversion.
    protocols: tuple[str, ...] = ()

    def targets(self) -> tuple[str, ...]:
        return (self.target, *self.extra_targets)

    def applies_to(self, protocol: str) -> bool:
        return not self.protocols or protocol in self.protocols


@dataclass(frozen=True)
class BenchmarkIdentity:
    """Task identity that must travel with an upstream layout.

    A new adapter should not need a second table for its task-id prefix, tags,
    writing-instruction directory, or public benchmark name. These are all
    stable facts about the benchmark, so the layout spec owns them alongside
    the source mapping.
    """

    benchmark: str
    task_id_prefix: str
    tags: tuple[str, ...]
    relevant_experience: str
    agents_md_dir: str = ""
    agents_md_fallback: str = ""


@dataclass(frozen=True)
class RenderDefaults:
    """Stable template defaults supplied by an adapter's declarative spec."""

    category: str = "research-writing"
    num_page: str = ""
    column: str = ""
    grader_module: str = ""


@dataclass(frozen=True)
class MaterialCompletenessContract:
    """A source inventory that must map to writer-visible evidence.

    This is deliberately schema-neutral. A domain owns how it derives and
    checks the inventory (for example, LifeSci inventories inline LaTeX tables),
    while conversion and onboarding retain the stable paths that make the
    contract visible and auditable rather than an undocumented prompt rule.
    """

    source_inventory: str
    public_inventory: str
    public_material_root: str


@dataclass(frozen=True)
class ProvenanceRequirements:
    """Fields a future release registry/source archive must fix before publish."""

    registry_fields: tuple[str, ...] = (
        "task_id",
        "dataset_revision",
        "converter_revision",
        "upstream_revision",
        "source_archive_locator",
        "source_archive_sha256",
        "evaluator_revision",
    )


@dataclass(frozen=True)
class UpstreamLayoutSpec:
    """Where one benchmark's material lives upstream, and where it lands."""

    identity: BenchmarkIdentity
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
    #: Paths relative to ``environment/`` that may contain names otherwise
    #: forbidden to the writer. A vendored code checkout is source material,
    #: not ground truth, so its upstream filenames are not leak evidence.
    forbidden_public_ignore_globs: tuple[str, ...] = ()
    #: Writer-visible paths the conversion *generates* rather than copies.
    #: `fidelity/transforms.classify_generated_vendor` already covers what is
    #: generated for every benchmark; these are the per-benchmark additions it
    #: does not, so a spec can account for a whole environment tree.
    generated_public: tuple[str, ...] = ()
    #: Verifier-only paths the conversion generates. `source_manifest.json` is
    #: the whole of it today: a record of upstream hashes, produced here rather
    #: than copied from anywhere.
    generated_private: tuple[str, ...] = ()
    #: How this adapter locates its LaTex support files. The implementation is
    #: deliberately a hook, but its mode is data so onboarding cannot silently
    #: pick a different resolver from the one fidelity/regression evidence used.
    style_resolution: str = "none"
    #: Defaults supplied to the shared Harbor templates. Per-paper metadata may
    #: override a value (for example PaperWrite-Bench reads the actual column
    #: from its template), but the common baseline lives in the spec.
    render: RenderDefaults = field(default_factory=RenderDefaults)
    #: Optional exact material-inventory contract supplied by a domain-specific
    #: deterministic checker. The generic converter stages the declared public
    #: inventory like every other source material; it never asks an LLM to guess
    #: whether evidence was omitted.
    material_completeness: MaterialCompletenessContract | None = None
    #: The data model #40 requires from future onboarding. Archive publication
    #: is a separate product, but an adapter cannot claim its fields are
    #: unknowable or defer them until after a task release has been cut.
    provenance_requirements: ProvenanceRequirements = field(
        default_factory=ProvenanceRequirements
    )

    @property
    def benchmark(self) -> str:
        return self.identity.benchmark

    @property
    def task_id_prefix(self) -> str:
        return self.identity.task_id_prefix

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
        if not rule.applies_to(protocol):
            continue
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


def stage_declared_copies(
    spec: UpstreamLayoutSpec,
    paper_dir: Path,
    task_dir: Path,
    protocol: str = "",
    *,
    private: bool = False,
) -> tuple[list[Path], dict[Path, tuple[str, Path]]]:
    """Copy one spec surface into a task and record its upstream provenance.

    This is the converter-side counterpart to :func:`predict_copies`: the
    latter is read-only evidence for the audit, while this function is the
    production implementation of a layout rule.  It deliberately keeps only
    filesystem mechanics here.  Benchmark-specific normalization, rendering,
    and vendor staging remain explicit converter hooks.

    Tree copies preserve symlinks and drop repository/cache residue exactly as
    the original benchmark converters did.  ``dirs_exist_ok`` supports the
    PaperWrite-Bench verifier tree, where the ``original`` and ``resources``
    subtrees are intentionally combined under one evaluator root.
    """
    rules = spec.private if private else spec.public
    copied: list[Path] = []
    provenance: dict[Path, tuple[str, Path]] = {}

    for rule in rules:
        if not rule.applies_to(protocol):
            continue
        resolved = spec.resolve(rule, protocol)
        matches = list(_expand(paper_dir, resolved))
        if not matches and rule.required:
            raise FileNotFoundError(f"{spec.benchmark}: required source missing: {resolved}")
        for source in matches:
            for target in rule.targets():
                destination = task_dir / target
                if rule.kind == "tree":
                    if not source.is_dir() or not any(source.iterdir()):
                        continue
                    shutil.copytree(
                        source,
                        destination,
                        symlinks=True,
                        ignore=shutil.ignore_patterns(*rule.tree_excludes, "*.pyc"),
                        dirs_exist_ok=destination.exists(),
                    )
                    for upstream_file in sorted(source.rglob("*")):
                        if not upstream_file.is_file():
                            continue
                        relative = upstream_file.relative_to(source)
                        if any(part in rule.tree_excludes for part in relative.parts):
                            continue
                        if upstream_file.suffix == ".pyc":
                            continue
                        copied_file = destination / relative
                        copied.append(copied_file)
                        provenance[copied_file] = ("upstream", upstream_file)
                    continue
                if not source.is_file():
                    continue
                copied_file = destination / source.name if target.endswith("/") else destination
                copied_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, copied_file)
                copied.append(copied_file)
                provenance[copied_file] = ("upstream", source)

    return copied, provenance
