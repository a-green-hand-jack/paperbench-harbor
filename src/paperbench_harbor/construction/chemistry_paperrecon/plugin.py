"""Chemistry construction contract for the shared PaperRecon pipeline."""

from __future__ import annotations

from paperbench_harbor.adapters.chemistry_paperrecon.harbor import AGENTS_MD_DIR
from paperbench_harbor.adapters.paperwrite_bench.converter import OVERVIEW_FILENAMES
from paperbench_harbor.construction.core.plugin import DomainPlugin

REQUIRED_OVERVIEW_HEADINGS: tuple[tuple[str, ...], ...] = (("title",), ("research question", "chemical question"), ("approach", "synthetic route", "computational method"), ("results", "key findings"), ("chemical significance", "significance"), ("takeaway", "outlook"))
OVERVIEW_SKELETON_HEADINGS = ("Title", "Chemical Question", "Approach", "Results", "Chemical Significance", "Takeaway")
OVERVIEW_BOUNDS = {OVERVIEW_FILENAMES["short"]: (700, 7000), OVERVIEW_FILENAMES["long"]: (2500, 30000)}
PAPER_TYPES = ("synthesis_characterization", "computational_chemistry", "cheminformatics_ml")

CHEMISTRY_PLUGIN = DomainPlugin(
    name="chemistry", domain_label="chemistry", paper_types=PAPER_TYPES, overview_headings=REQUIRED_OVERVIEW_HEADINGS,
    overview_skeleton_headings=OVERVIEW_SKELETON_HEADINGS, significance_heading="Chemical Significance", overview_bounds=OVERVIEW_BOUNDS,
    overview_length_targets="roughly 1,500-4,000 characters short and 6,000-15,000 long", agents_md_dir=AGENTS_MD_DIR,
    benchmark_intro=("You are building one sample of **Chemistry-PaperRecon**, a benchmark that asks a writing agent to reconstruct a chemistry paper from a research overview and public study materials."),
    stop_condition_examples=("A paper whose reconstruction does not require software may use the core `not_applicable` code status only with an approved, evidence-based reason; missing code is not a reason."),
    overview_skeleton_rationale=" - chemistry papers need the chemical question, route or method, and measured evidence",
    overview_content_guidance=("State compounds, conditions, characterization, computational settings and quantitative outcomes without reproducing manuscript prose."),
    caption_example="figures/fig2.png: Reaction scope with isolated yields and selectivity.",
    imagery_guidance="Expect reaction schemes, spectra, crystal structures, energy profiles and assay plots.", require_table_inventory=True,
)
