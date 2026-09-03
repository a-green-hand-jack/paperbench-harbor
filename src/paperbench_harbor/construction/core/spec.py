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
from typing import Literal

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

CodeStatus = Literal["available", "not_applicable"]
CODE_STATUSES: tuple[CodeStatus, ...] = ("available", "not_applicable")


@dataclass(frozen=True)
class PaperSpec:
    """One selected paper and the selection criteria it is expected to satisfy."""

    paper_id: str
    arxiv_id: str
    #: One of the owning domain plugin's `paper_types`; it selects which
    #: `AGENTS_<type>.md` writing instructions the benchmark hands the writing
    #: agent, and it is a human decision.
    paper_type: str
    #: The repository is mandatory only when :attr:`code_status` is
    #: ``"available"``.  A theoretical or proof-only paper may be selected
    #: with ``"not_applicable"`` only when a reviewer recorded why code is not
    #: a reconstruction input.
    code_repo: str = ""
    expected_license: str = ""
    expected_version: str = ""
    expected_category: str = ""
    note: str = ""
    code_status: CodeStatus = "available"
    code_not_applicable_reason: str = ""

    def __post_init__(self) -> None:
        if self.code_status not in CODE_STATUSES:
            raise ValueError(
                f"code_status must be one of {CODE_STATUSES}, got {self.code_status!r}"
            )
        if self.code_status == "available":
            if not self.code_repo.strip():
                raise ValueError("code_repo is required when code_status='available'")
            if self.code_not_applicable_reason.strip():
                raise ValueError(
                    "code_not_applicable_reason must be empty when code_status='available'"
                )
        else:
            if self.code_repo.strip():
                raise ValueError(
                    "code_repo must be empty when code_status='not_applicable'"
                )
            if not self.code_not_applicable_reason.strip():
                raise ValueError(
                    "code_not_applicable_reason is required when "
                    "code_status='not_applicable'"
                )

    @property
    def requires_code(self) -> bool:
        return self.code_status == "available"

    @property
    def arxiv_abs_url(self) -> str:
        return f"https://arxiv.org/abs/{self.arxiv_id}{self.expected_version}"

    @property
    def arxiv_eprint_url(self) -> str:
        return f"https://arxiv.org/e-print/{self.arxiv_id}{self.expected_version}"
