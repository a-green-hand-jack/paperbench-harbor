"""Chemistry candidate-discovery policy."""

from paperbench_harbor.construction.chemistry_paperrecon.plugin import CHEMISTRY_PLUGIN
from paperbench_harbor.construction.core.screen import ScreeningPolicy, SeedCandidate

CHEMISTRY_SEED_CANDIDATES: tuple[SeedCandidate, ...] = ()
CHEMISTRY_EXCLUDE_IDS: tuple[str, ...] = ()
CHEMISTRY_SCREENING_POLICY = ScreeningPolicy(
    name="chemistry", paper_types=CHEMISTRY_PLUGIN.paper_types,
    search_scope=("arXiv chemistry-adjacent categories, ChemRxiv-linked public preprints and computational chemistry literature. Use Bohrium LKM for broad discovery, then independently verify every proposed record."),
    selection_criteria=("Select synthetic, computational or chemistry-ML papers with redistributable source, usable figures and a reproducible material package. Code is required unless a human approves a documented `not_applicable` reason."),
    prior_findings="No historical candidate list is treated as evidence; discovery starts from live sources.",
)
