"""Physics candidate-discovery policy."""

from paperbench_harbor.construction.core.screen import ScreeningPolicy, SeedCandidate
from paperbench_harbor.construction.physics_paperrecon.plugin import PHYSICS_PLUGIN

PHYSICS_SEED_CANDIDATES: tuple[SeedCandidate, ...] = ()
PHYSICS_EXCLUDE_IDS: tuple[str, ...] = ()
PHYSICS_SCREENING_POLICY = ScreeningPolicy(
    name="physics", paper_types=PHYSICS_PLUGIN.paper_types,
    search_scope=("arXiv physics, high-energy physics, condensed matter, astrophysics and quantitative experimental physics categories. Use Bohrium LKM for broad discovery, then independently verify every proposed record."),
    selection_criteria=("Select theory, simulation or experimental papers with redistributable arXiv source and figures. Code is required unless a human can approve a documented `not_applicable` reason for a reconstruction that does not depend on software."),
    prior_findings="No historical candidate list is treated as evidence; discovery starts from live sources.",
)
