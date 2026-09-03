"""The seam between GeneralPaperSmith and a DomainPaperSmith.

Everything PaperSmith does that depends on *which discipline the paper comes
from* is reachable through one frozen object. The core prompt, validator and
pipeline take a :class:`DomainPlugin` and never import a domain package; a
domain package supplies one plugin instance and never re-implements a check.

The shape follows HELM's shared-harness-plus-scenario precedent: an in-process
plugin object handed to a fixed harness, rather than SWE-bench's practice of
forking the whole pipeline per language. See ``docs/papersmith-architecture.md``
for why.

Two kinds of field live here, and they are deliberately not mixed:

* **Contract fields** the validator enforces (`paper_types`,
  `overview_headings`, `overview_bounds`, `agents_md_dir`). Getting these wrong
  fails a build.
* **Prompt fragments** the construction spec splices in (`benchmark_intro`,
  `imagery_guidance`, `caption_example`, `overview_content_guidance`,
  `overview_skeleton_rationale`, `stop_condition_examples`). These are prose
  the agent reads; the *invariants* around them — the compile sequence, the
  leakage rule, the output tree, the provenance fields — stay in the core
  prompt where no domain can weaken them.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DomainPlugin:
    """One discipline's answers to the questions the core cannot answer itself."""

    #: Short machine name, e.g. ``"lifesci"``. Used in logs and reports.
    name: str

    #: The adjective this domain uses for itself in validator feedback, e.g.
    #: ``"biology"`` -> "Use the biology overview skeleton: ...".
    domain_label: str

    #: The domain's replacement for PaperWrite-Bench's method/benchmark/both
    #: taxonomy. Each entry must have a matching ``AGENTS_<type>.md`` in
    #: :attr:`agents_md_dir`; the validator checks that, because the converter
    #: silently falls back to a default type and would otherwise hand a paper
    #: the wrong writing instructions.
    paper_types: tuple[str, ...]

    #: Required overview sections, as accepted *spellings*: each entry is a
    #: tuple of lowercase variants, any one of which satisfies that heading.
    #: Drives ``validate._check_overviews``.
    overview_headings: tuple[tuple[str, ...], ...]

    #: The same skeleton in display form, ordered, as the construction prompt
    #: shows it. The first entry is rendered as the ``#`` title heading and the
    #: rest as ``##`` sections.
    overview_skeleton_headings: tuple[str, ...]

    #: Which skeleton heading carries "why this result matters to the field"
    #: — the one section whose framing is genuinely domain-specific (biology's
    #: "Biological Significance"; a physics domain would name its own). Must
    #: appear in :attr:`overview_skeleton_headings` and be covered by
    #: :attr:`overview_headings`.
    significance_heading: str

    #: Per-overview-file ``(floor, ceiling)`` character bounds. Sanity bounds,
    #: not style rules: the floor catches a heading skeleton with no content,
    #: the ceiling catches an agent that pasted the paper in.
    overview_bounds: dict[str, tuple[int, int]]

    #: The length *targets* the construction prompt asks for, as a phrase
    #: ("roughly 1,500-4,000 characters for the short variant and ..."). Kept
    #: beside :attr:`overview_bounds` on purpose: the prompt target and the
    #: enforced bound are two views of one decision, and a domain that widens
    #: one without the other would be telling the agent to miss its own gate.
    overview_length_targets: str

    #: Directory holding this domain's ``AGENTS_<paper_type>.md`` writing
    #: instructions, i.e. its Harbor adapter's ``AGENTS_MD_DIR``.
    agents_md_dir: Path

    # --- prompt fragments ------------------------------------------------- #

    #: Opening sentences naming the benchmark and what a sample of it is.
    benchmark_intro: str

    #: Domain clarifications appended to the core stop-condition list — what
    #: does *not* stop a build, and any domain-specific reason that does.
    #: May be empty.
    stop_condition_examples: str

    #: Trailing clause explaining why this domain's overview skeleton has the
    #: shape it does. Spliced directly after "using this skeleton", so it
    #: should begin with its own separator (e.g. " — ..."). May be empty.
    overview_skeleton_rationale: str

    #: What the overview must actually say, in this domain's terms — the
    #: quantities, identifiers and significance a reader of *this* literature
    #: needs.
    overview_content_guidance: str

    #: One example caption line for ``figure_summary.txt``, in this domain's
    #: idiom.
    caption_example: str

    #: What this domain's figures typically are, so the agent describes what is
    #: actually plotted instead of defaulting to ML-paper vocabulary.
    imagery_guidance: str

    #: Whether every source-table environment must be represented by an
    #: immutable public table fragment and an inventory. This stays opt-in so
    #: an existing domain can adopt the stricter source-material contract on
    #: its own release cadence.
    require_table_inventory: bool = False

    def __post_init__(self) -> None:
        if self.significance_heading not in self.overview_skeleton_headings:
            raise ValueError(
                f"significance_heading {self.significance_heading!r} is not one of "
                f"overview_skeleton_headings {self.overview_skeleton_headings!r}"
            )
        lowered = self.significance_heading.lower()
        if not any(lowered in variants for variants in self.overview_headings):
            raise ValueError(
                f"significance_heading {self.significance_heading!r} is not accepted by "
                "overview_headings; the validator would reject an overview that follows "
                "this plugin's own skeleton"
            )

    def overview_skeleton(self) -> str:
        """The skeleton as the construction prompt prints it."""

        title, *sections = self.overview_skeleton_headings
        body = "\n".join(f"## {heading}" for heading in sections)
        return f"# {title}\n\n<the paper's actual title>\n\n{body}"

    def overview_skeleton_remedy(self) -> str:
        """The one-line "use this skeleton" remedy attached to a failed check."""

        headings = ", ".join(self.overview_skeleton_headings)
        return f"Use the {self.domain_label} overview skeleton: {headings}."
