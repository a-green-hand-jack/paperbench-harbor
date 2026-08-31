"""GeneralPaperSmith: the domain-agnostic half of the PaperSmith construction agent.

This package holds everything about building a PaperRecon-shaped benchmark
sample that does not depend on which discipline the paper comes from: the
construction specification handed to the opencode agent (:mod:`.prompt`), the
deterministic gate that decides whether the result may enter a corpus
(:mod:`.validate`), the restricted recompilation that reproduces the Harbor
verifier (:mod:`.latex`), the agent session driver (:mod:`.opencode_agent`),
and the turn loop and worker pool that tie them together (:mod:`.pipeline`).

A discipline plugs in one :class:`~.plugin.DomainPlugin` — its paper-type
taxonomy, overview skeleton and length bounds, and the prose fragments its
prompt needs — and gets the whole machine. See ``docs/papersmith-architecture.md``
for the contract and the reasoning behind it, and
``construction.lifesci_paperrecon`` for the one plugin that exists today.

Nothing in this package may import a domain package.
"""

from paperbench_harbor.construction.core.plugin import DomainPlugin
from paperbench_harbor.construction.core.spec import ACCEPTED_LICENSES, PaperSpec
from paperbench_harbor.construction.core.validate import (
    ValidationIssue,
    ValidationReport,
    validate_paper,
)

__all__ = [
    "ACCEPTED_LICENSES",
    "DomainPlugin",
    "PaperSpec",
    "ValidationIssue",
    "ValidationReport",
    "validate_paper",
]
