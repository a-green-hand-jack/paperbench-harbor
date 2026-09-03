"""Mathematics construction contract for the shared PaperRecon pipeline."""

from __future__ import annotations

from paperbench_harbor.adapters.mathematics_paperrecon.harbor import AGENTS_MD_DIR
from paperbench_harbor.adapters.paperwrite_bench.converter import OVERVIEW_FILENAMES
from paperbench_harbor.construction.core.plugin import DomainPlugin

REQUIRED_OVERVIEW_HEADINGS: tuple[tuple[str, ...], ...] = (("title",), ("problem", "research question"), ("definitions and setup", "setup", "formalism"), ("main results", "results"), ("mathematical significance", "significance"), ("outlook", "takeaway"))
OVERVIEW_SKELETON_HEADINGS = ("Title", "Problem", "Definitions and Setup", "Main Results", "Mathematical Significance", "Outlook")
OVERVIEW_BOUNDS = {OVERVIEW_FILENAMES["short"]: (700, 7000), OVERVIEW_FILENAMES["long"]: (2500, 30000)}
PAPER_TYPES = ("theorem_proof", "numerical", "formalized_computer_assisted")

MATHEMATICS_PLUGIN = DomainPlugin(
    name="mathematics", domain_label="mathematics", paper_types=PAPER_TYPES, overview_headings=REQUIRED_OVERVIEW_HEADINGS,
    overview_skeleton_headings=OVERVIEW_SKELETON_HEADINGS, significance_heading="Mathematical Significance", overview_bounds=OVERVIEW_BOUNDS,
    overview_length_targets="roughly 1,500-4,000 characters short and 6,000-15,000 long", agents_md_dir=AGENTS_MD_DIR,
    benchmark_intro=("You are building one sample of **Mathematics-PaperRecon**, a benchmark that asks a writing agent to reconstruct a mathematics paper from a research overview and public study materials."),
    stop_condition_examples=("A proof-only paper may use the core `not_applicable` code status only with an approved, evidence-based reason; absent or unavailable code is not a reason."),
    overview_skeleton_rationale=" - mathematics papers need the problem, definitions and precise claims before exposition",
    overview_content_guidance=("State definitions, assumptions, theorem claims, proof strategy and any numerical or formal verification evidence without copying the paper."),
    caption_example="figures/convergence.pdf: Error bound versus discretization level.",
    imagery_guidance="Expect commutative diagrams, geometric constructions, convergence plots and proof dependency diagrams.", require_table_inventory=True,
)
