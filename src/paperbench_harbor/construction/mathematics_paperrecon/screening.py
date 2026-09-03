"""Mathematics candidate-discovery policy."""

from paperbench_harbor.construction.core.screen import ScreeningPolicy, SeedCandidate
from paperbench_harbor.construction.mathematics_paperrecon.plugin import MATHEMATICS_PLUGIN

MATHEMATICS_SEED_CANDIDATES: tuple[SeedCandidate, ...] = ()
MATHEMATICS_EXCLUDE_IDS: tuple[str, ...] = ()
MATHEMATICS_SCREENING_POLICY = ScreeningPolicy(
    name="mathematics", paper_types=MATHEMATICS_PLUGIN.paper_types,
    search_scope=("arXiv mathematics and formal methods categories, emphasizing public-source manuscripts with reconstructable theorem, numerical or formalized results. Use Bohrium LKM for broad discovery, then independently verify every proposed record."),
    selection_criteria=("Select theorem-proof, numerical, or formalized/computer-assisted papers with redistributable source and sufficient figures or structured results. Code is required unless a human approves a documented proof-only `not_applicable` reason."),
    prior_findings="No historical candidate list is treated as evidence; discovery starts from live sources.",
)
