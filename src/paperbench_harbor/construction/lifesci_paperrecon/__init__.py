"""LifeSci-PaperRecon's domain half of the opencode-agent-driven construction.

This package deliberately contains **no paper-transformation logic**. An
earlier iteration hand-wrote LaTeX/bibliography/figure transformations in
Python and was abandoned: every real paper carries different, unanticipated
pathologies (the first pilot paper alone needed a shell-escape-dependent
``standalone`` preamble rewritten, which Harbor forbids), and a growing
library of per-paper regex rules does not scale to 30-50 samples, let alone to
a second domain.

Instead the per-paper build is delegated to an ``opencode`` CLI agent session
(:mod:`paperbench_harbor.construction.core.opencode_agent`) driven by a
self-contained specification
(:mod:`paperbench_harbor.construction.core.prompt`), and the result is admitted
only if it passes a deterministic contract check
(:mod:`paperbench_harbor.construction.core.validate`). The split is intentional:

* **Agent judgment** — fetching, license re-verification, LaTeX surgery,
  bibliography conversion, figure extraction, overview authoring. Anything
  where the right action depends on what this particular paper looks like.
* **Plain code** — "does the produced directory match the contract the Harbor
  converter needs, and does it compile under the verifier's own restricted
  flags". Contract checking is not paper-specific judgment, so it stays
  deterministic, reviewable and un-negotiable by the agent.

Since the GeneralPaperSmith/DomainPaperSmith split, all of that machinery lives
in :mod:`paperbench_harbor.construction.core` and knows nothing about biology.
What is left here is the domain itself: the approved pilot papers
(:mod:`.papers`) and :data:`~.plugin.LIFESCI_PLUGIN`, which supplies the
biology paper-type taxonomy, the overview skeleton and its bounds, and the
prompt fragments that make the construction spec a life-sciences one. See
``docs/papersmith-architecture.md``.

Entry point: ``scripts/build_lifesci_paperrecon_source.py``.
"""

from paperbench_harbor.construction.core.spec import PaperSpec
from paperbench_harbor.construction.core.validate import (
    ValidationIssue,
    ValidationReport,
    validate_paper,
)
from paperbench_harbor.construction.lifesci_paperrecon.papers import (
    PILOT_BY_ID,
    PILOT_PAPERS,
)
from paperbench_harbor.construction.lifesci_paperrecon.plugin import LIFESCI_PLUGIN

__all__ = [
    "LIFESCI_PLUGIN",
    "PILOT_BY_ID",
    "PILOT_PAPERS",
    "PaperSpec",
    "ValidationIssue",
    "ValidationReport",
    "validate_paper",
]
