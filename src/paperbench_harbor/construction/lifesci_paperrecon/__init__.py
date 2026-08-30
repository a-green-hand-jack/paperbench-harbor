"""Opencode-agent-driven construction of the LifeSci-PaperRecon source corpus.

This package deliberately contains **no paper-transformation logic**. An
earlier iteration hand-wrote LaTeX/bibliography/figure transformations in
Python and was abandoned: every real paper carries different, unanticipated
pathologies (the first pilot paper alone needed a shell-escape-dependent
``standalone`` preamble rewritten, which Harbor forbids), and a growing
library of per-paper regex rules does not scale to 30-50 samples, let alone to
a second domain.

Instead the per-paper build is delegated to an ``opencode`` CLI agent session
(:mod:`.opencode_agent`) driven by a self-contained specification
(:mod:`.prompt`), and the result is admitted only if it passes a deterministic
contract check (:mod:`.validate`). The split is intentional:

* **Agent judgment** — fetching, license re-verification, LaTeX surgery,
  bibliography conversion, figure extraction, overview authoring. Anything
  where the right action depends on what this particular paper looks like.
* **Plain code** — "does the produced directory match the contract the Harbor
  converter needs, and does it compile under the verifier's own restricted
  flags". Contract checking is not paper-specific judgment, so it stays
  deterministic, reviewable and un-negotiable by the agent.

Entry point: ``scripts/build_lifesci_paperrecon_source.py``.
"""

from paperbench_harbor.construction.lifesci_paperrecon.papers import (
    PILOT_BY_ID,
    PILOT_PAPERS,
    PaperSpec,
)
from paperbench_harbor.construction.lifesci_paperrecon.validate import (
    ValidationIssue,
    ValidationReport,
    validate_paper,
)

__all__ = [
    "PILOT_BY_ID",
    "PILOT_PAPERS",
    "PaperSpec",
    "ValidationIssue",
    "ValidationReport",
    "validate_paper",
]
