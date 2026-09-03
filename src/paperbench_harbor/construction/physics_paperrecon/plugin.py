"""Physics construction contract for the shared PaperRecon pipeline."""

from __future__ import annotations

from paperbench_harbor.adapters.paperwrite_bench.converter import OVERVIEW_FILENAMES
from paperbench_harbor.adapters.physics_paperrecon.harbor import AGENTS_MD_DIR
from paperbench_harbor.construction.core.plugin import DomainPlugin

REQUIRED_OVERVIEW_HEADINGS: tuple[tuple[str, ...], ...] = (("title",), ("open problem", "research question"), ("formalism", "derivation", "experimental setup"), ("results", "findings"), ("physical significance", "significance"), ("outlook", "takeaway"))
OVERVIEW_SKELETON_HEADINGS = ("Title", "Open Problem", "Formalism or Experimental Setup", "Results", "Physical Significance", "Outlook")
OVERVIEW_BOUNDS = {OVERVIEW_FILENAMES["short"]: (700, 7000), OVERVIEW_FILENAMES["long"]: (2500, 30000)}
PAPER_TYPES = ("theory", "simulation", "experimental")

PHYSICS_PLUGIN = DomainPlugin(
    name="physics", domain_label="physics", paper_types=PAPER_TYPES, overview_headings=REQUIRED_OVERVIEW_HEADINGS,
    overview_skeleton_headings=OVERVIEW_SKELETON_HEADINGS, significance_heading="Physical Significance", overview_bounds=OVERVIEW_BOUNDS,
    overview_length_targets="roughly 1,500-4,000 characters short and 6,000-15,000 long", agents_md_dir=AGENTS_MD_DIR,
    benchmark_intro=("You are building one sample of **Physics-PaperRecon**, a benchmark that asks a writing agent to reconstruct a physics paper from a research overview and public study materials."),
    stop_condition_examples=("A paper whose reconstruction does not require software may use the core `not_applicable` code status only with an approved, evidence-based reason; missing code is not a reason."),
    overview_skeleton_rationale=" - physics papers foreground the problem, formalism and regime",
    overview_content_guidance=("State the observable, assumptions, parameter regime, uncertainty and quantitative result without reproducing prose."),
    caption_example="figures/spectrum.pdf: Energy spectrum versus field, with one-sigma bands.",
    imagery_guidance="Expect spectra, phase diagrams, detector schematics and Feynman diagrams.", require_table_inventory=True,
)
