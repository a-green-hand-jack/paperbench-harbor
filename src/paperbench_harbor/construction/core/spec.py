"""What one benchmark sample is, before any domain has an opinion about it.

:class:`PaperSpec` and :data:`ACCEPTED_LICENSES` were extracted verbatim from
``construction.lifesci_paperrecon.papers`` when PaperSmith was split into a
domain-agnostic core and per-domain plugins. Neither carries a biology-specific
field: a paper is an arXiv id, a version, a category, a license, a code
repository and a human-assigned type, whichever discipline it comes from. The
*meaning* of ``paper_type`` is the domain's business
(:class:`~paperbench_harbor.construction.core.plugin.DomainPlugin.paper_types`);
the fact that a sample has one is not.

Every field is an *expectation* the construction agent must re-verify against
the live arXiv abstract page, not a trusted fact. The validation gate
(:mod:`.validate`) cross-checks the agent's recorded ``provenance.json`` against
these expectations and fails the paper on any mismatch.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Licenses that permit redistributing derived material (approved plan,
#: Phase 0 filter). Anything else disqualifies a paper.
#:
#: This is a project-wide redistribution policy rather than a domain choice —
#: every PaperSmith corpus ships derived material under the same terms — so it
#: stays in the core rather than becoming a plugin field.
ACCEPTED_LICENSES = (
    "CC BY 4.0",
    "CC BY-NC 4.0",
    "CC BY-SA 4.0",
    "CC0 1.0",
)


@dataclass(frozen=True)
class PaperSpec:
    """One selected paper and the selection criteria it is expected to satisfy."""

    paper_id: str
    arxiv_id: str
    #: One of the owning domain plugin's `paper_types`; it selects which
    #: `AGENTS_<type>.md` writing instructions the benchmark hands the writing
    #: agent, and it is a human decision.
    paper_type: str
    code_repo: str
    expected_license: str = ""
    expected_version: str = ""
    expected_category: str = ""
    note: str = ""

    @property
    def arxiv_abs_url(self) -> str:
        return f"https://arxiv.org/abs/{self.arxiv_id}{self.expected_version}"

    @property
    def arxiv_eprint_url(self) -> str:
        return f"https://arxiv.org/e-print/{self.arxiv_id}{self.expected_version}"
