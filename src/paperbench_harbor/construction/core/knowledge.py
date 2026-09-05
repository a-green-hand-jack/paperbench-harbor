"""Versioned research-type contracts, shared by extraction, validation and review.

These rules are repository policy, not model-generated standards. Changes require
source citations, code review, version bumps and positive/negative test examples.
Legacy adapter taxonomies are deliberately not reinterpreted as research types.
"""

import json
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class KnowledgePackage:
    domain: str
    research_type: str
    version: str
    required_facts: tuple[str, ...]
    checks: tuple[str, ...]
    sources: tuple[str, ...]
    positive_example: str
    negative_example: str
    selection_policy: str = "Versioned, redistributable source; sufficient public reconstruction evidence"
    evidence_schema: str = "research-evidence-v1"
    material_contract: str = "Every required fact and claim has a located source and public support"
    tools: tuple[str, ...] = ("validate_research_evidence", "independent_material_review")

    def as_dict(self) -> dict:
        return json.loads(json.dumps(asdict(self)))


PACKAGES = (
    KnowledgePackage(
        "lifesci", "experimental", "1.0.0",
        ("samples", "groups", "controls", "replicates", "statistics", "effect_size", "uncertainty"),
        ("causal_claim_requires_intervention", "distinguish_biological_and_technical_replicates"),
        ("https://arriveguidelines.org/arrive-guidelines",),
        "Report independent biological n separately from repeated measurements and give uncertainty.",
        "Treat three measurements of one animal as three independent animals.",
    ),
    KnowledgePackage(
        "physics", "simulation", "1.0.0",
        ("system", "equations", "units", "boundary_conditions", "parameters", "approximations", "convergence", "error"),
        ("positive_convergence_tolerance", "nonnegative_error_bound"),
        ("https://doi.org/10.1115/1.2960953",),
        "Compare grid refinements at fixed boundary conditions and report error and tolerance.",
        "Claim convergence from a single grid without an error estimate.",
    ),
    KnowledgePackage(
        "chemistry", "synthesis_characterization", "1.0.0",
        ("molecular_identity", "reaction_conditions", "yield", "purity", "characterization", "methods"),
        ("yield_and_purity_in_percent_range", "characterization_identity_matches_product"),
        ("https://pubs.acs.org/page/joceah/submission/authors.html",),
        "Bind the product identity to spectra, isolated yield, purity and reaction conditions.",
        "Use a spectrum for a different product as evidence of the claimed structure.",
    ),
    KnowledgePackage(
        "mathematics", "theorem_proof", "1.0.0",
        ("definitions", "hypotheses", "quantifiers", "lemma_dependencies", "proof_outline", "boundary_cases"),
        ("acyclic_lemma_dependencies", "all_dependencies_defined", "no_unrequested_proof_discovery"),
        ("https://www.ams.org/education/undergraduate/kimball",),
        "Supply hypotheses, quantifiers and an acyclic lemma outline for writing reconstruction.",
        "Omit a compactness assumption or use the theorem itself to prove its prerequisite lemma.",
    ),
)


def get_knowledge_package(domain: str, research_type: str) -> KnowledgePackage:
    for package in PACKAGES:
        if (package.domain, package.research_type) == (domain, research_type):
            return package
    raise ValueError(f"unsupported research type: {domain}/{research_type}; explicit selection required")
