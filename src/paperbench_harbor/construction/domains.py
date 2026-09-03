"""Registry of PaperRecon domains supported by the shared construction flow."""

from __future__ import annotations

from dataclasses import dataclass

from paperbench_harbor.construction.chemistry_paperrecon.papers import (
    APPROVED_PAPERS as CHEMISTRY_PAPERS,
)
from paperbench_harbor.construction.chemistry_paperrecon.plugin import CHEMISTRY_PLUGIN
from paperbench_harbor.construction.chemistry_paperrecon.screening import (
    CHEMISTRY_EXCLUDE_IDS,
    CHEMISTRY_SCREENING_POLICY,
    CHEMISTRY_SEED_CANDIDATES,
)
from paperbench_harbor.construction.core.plugin import DomainPlugin
from paperbench_harbor.construction.core.screen import ScreeningPolicy, SeedCandidate
from paperbench_harbor.construction.core.spec import PaperSpec
from paperbench_harbor.construction.lifesci_paperrecon.papers import (
    APPROVED_PAPERS as LIFESCI_PAPERS,
)
from paperbench_harbor.construction.lifesci_paperrecon.plugin import LIFESCI_PLUGIN
from paperbench_harbor.construction.lifesci_paperrecon.screening import (
    LIFESCI_EXCLUDE_IDS,
    LIFESCI_SCREENING_POLICY,
    LIFESCI_SEED_CANDIDATES,
)
from paperbench_harbor.construction.mathematics_paperrecon.papers import (
    APPROVED_PAPERS as MATHEMATICS_PAPERS,
)
from paperbench_harbor.construction.mathematics_paperrecon.plugin import MATHEMATICS_PLUGIN
from paperbench_harbor.construction.mathematics_paperrecon.screening import (
    MATHEMATICS_EXCLUDE_IDS,
    MATHEMATICS_SCREENING_POLICY,
    MATHEMATICS_SEED_CANDIDATES,
)
from paperbench_harbor.construction.physics_paperrecon.papers import (
    APPROVED_PAPERS as PHYSICS_PAPERS,
)
from paperbench_harbor.construction.physics_paperrecon.plugin import PHYSICS_PLUGIN
from paperbench_harbor.construction.physics_paperrecon.screening import (
    PHYSICS_EXCLUDE_IDS,
    PHYSICS_SCREENING_POLICY,
    PHYSICS_SEED_CANDIDATES,
)


@dataclass(frozen=True)
class PaperReconDomain:
    name: str
    plugin: DomainPlugin
    screening_policy: ScreeningPolicy
    seed_candidates: tuple[SeedCandidate, ...]
    exclude_ids: tuple[str, ...]
    approved_papers: tuple[PaperSpec, ...]
    benchmark_config: str


_DOMAINS = {
    "lifesci": PaperReconDomain(
        "lifesci", LIFESCI_PLUGIN, LIFESCI_SCREENING_POLICY, LIFESCI_SEED_CANDIDATES,
        LIFESCI_EXCLUDE_IDS, LIFESCI_PAPERS, "lifesci-paperrecon-short",
    ),
    "physics": PaperReconDomain(
        "physics", PHYSICS_PLUGIN, PHYSICS_SCREENING_POLICY, PHYSICS_SEED_CANDIDATES,
        PHYSICS_EXCLUDE_IDS, PHYSICS_PAPERS, "physics-paperrecon-short",
    ),
    "chemistry": PaperReconDomain(
        "chemistry", CHEMISTRY_PLUGIN, CHEMISTRY_SCREENING_POLICY, CHEMISTRY_SEED_CANDIDATES,
        CHEMISTRY_EXCLUDE_IDS, CHEMISTRY_PAPERS, "chemistry-paperrecon-short",
    ),
    "mathematics": PaperReconDomain(
        "mathematics", MATHEMATICS_PLUGIN, MATHEMATICS_SCREENING_POLICY,
        MATHEMATICS_SEED_CANDIDATES, MATHEMATICS_EXCLUDE_IDS, MATHEMATICS_PAPERS,
        "mathematics-paperrecon-short",
    ),
}


def domain_names() -> tuple[str, ...]:
    return tuple(_DOMAINS)


def get_domain(name: str) -> PaperReconDomain:
    try:
        return _DOMAINS[name]
    except KeyError as error:
        raise ValueError(f"unknown PaperRecon domain {name!r}; choose from {', '.join(domain_names())}") from error
