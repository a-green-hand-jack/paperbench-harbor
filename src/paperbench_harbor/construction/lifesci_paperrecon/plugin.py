"""LifeSci DomainPaperSmith: what makes a life-sciences PaperRecon sample.

Every biology-specific decision PaperSmith makes is in this one object. The
machinery that acts on it — the construction prompt, the validation gate, the
turn loop — lives in :mod:`paperbench_harbor.construction.core` and has no idea
what a phylogeny is.

The values below were extracted verbatim from the pre-split
``lifesci_paperrecon`` prompt and validator, so the generated prompt and the
enforced contract are byte-for-byte what built the pilot corpus.
"""

from __future__ import annotations

from paperbench_harbor.adapters.lifesci_paperrecon.harbor import AGENTS_MD_DIR
from paperbench_harbor.adapters.paperwrite_bench.converter import OVERVIEW_FILENAMES
from paperbench_harbor.construction.core.plugin import DomainPlugin

#: The biology-adapted overview skeleton (approved plan, Phase 1 step 4),
#: replacing PaperWrite-Bench's Motivation/Proposed Method/Contributions shape.
#: Each entry is a set of acceptable spellings for one required heading.
REQUIRED_OVERVIEW_HEADINGS: tuple[tuple[str, ...], ...] = (
    ("title",),
    ("research question", "hypothesis"),
    ("approach", "experimental approach", "computational approach"),
    ("key findings", "findings"),
    ("biological significance", "significance"),
    ("takeaway",),
)

#: The same skeleton as the prompt prints it, in order.
OVERVIEW_SKELETON_HEADINGS: tuple[str, ...] = (
    "Title",
    "Research Question or Hypothesis",
    "Approach",
    "Key Findings",
    "Biological Significance",
    "Takeaway",
)

#: Sanity bounds, not style rules. The floor catches an agent that emitted a
#: heading skeleton with no content; the ceiling catches one that pasted the
#: paper in, which would hand the writing agent the answer.
OVERVIEW_BOUNDS = {
    OVERVIEW_FILENAMES["short"]: (700, 7000),
    OVERVIEW_FILENAMES["long"]: (2500, 30000),
}

#: The biology-adapted replacement for PaperWrite-Bench's method/benchmark/both
#: taxonomy. Must match an `AGENTS_<type>.md` in the LifeSci-PaperRecon adapter.
PAPER_TYPES = ("computational", "experimental", "review")

LIFESCI_PLUGIN = DomainPlugin(
    name="lifesci",
    domain_label="biology",
    paper_types=PAPER_TYPES,
    overview_headings=REQUIRED_OVERVIEW_HEADINGS,
    overview_skeleton_headings=OVERVIEW_SKELETON_HEADINGS,
    significance_heading="Biological Significance",
    overview_bounds=OVERVIEW_BOUNDS,
    overview_length_targets=(
        "roughly 1,500-4,000 characters for the short variant and 6,000-15,000\n"
        "for the long one"
    ),
    agents_md_dir=AGENTS_MD_DIR,
    benchmark_intro=(
        "You are building one sample of **LifeSci-PaperRecon**, a benchmark that asks a\n"
        "writing agent to reconstruct a life-sciences research paper from a research\n"
        "overview plus the study's own figures, tables, bibliography and code."
    ),
    # Owner decision, 2026-08-31: the *paper's* license still gates selection,
    # but the code repository's does not. That carve-out is this benchmark's
    # policy rather than a core invariant, so it rides on the plugin.
    stop_condition_examples=(
        "The code repository's *license* is **not** a stop condition. Record whatever\n"
        "you find in `provenance.json`'s `code_license` — including `\"none declared\"`\n"
        "when the repository has no license file and the GitHub API reports\n"
        "`license: null` — and carry on building. Report it accurately; do not guess a\n"
        "license, and do not infer one from the paper's own license."
    ),
    overview_skeleton_rationale=(
        " — the benchmark\n"
        "is life-sciences, so it is deliberately not the ML-shaped\n"
        "motivation/method/contributions one"
    ),
    overview_content_guidance=(
        "Write the science, not the sentences: state what was\n"
        "asked, what was done, what came out (with the actual quantitative results,\n"
        "effect sizes, model parameters and organism/dataset identifiers a reader would\n"
        "need), and why it matters biologically."
    ),
    caption_example="figures/fig2a.png: Dose-response curves for ... The x-axis is ...",
    imagery_guidance=(
        "This is a life-sciences corpus, so expect micrographs, gels,\n"
        "phylogenetic trees, pathway diagrams and dose-response curves rather than\n"
        "training curves and architecture diagrams."
    ),
)
