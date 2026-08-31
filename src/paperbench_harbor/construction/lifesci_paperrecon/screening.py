"""LifeSci-PaperRecon's screening policy, and what survived from Phase 0.

Phase 0 screened arXiv's `q-bio.*` categories and reported **27 fully-qualifying
candidates**, of which three were selected and built. The individual arXiv IDs
of the other 24 were never written to a machine-readable file, and no such file
exists anywhere in this repository, under `datasets/`, or under `.cache/` — the
only surviving record is the narrative summary in `docs/lifesci-paperrecon.md`.

:data:`LIFESCI_SEED_CANDIDATES` is therefore **empty**, and that is the honest
answer rather than a gap to be filled. Reconstructing 24 plausible-looking arXiv
IDs from a category breakdown would produce a list that looks like recovered
data and is not, and every fabricated entry would cost a screening run a live
verification to disprove — the exact failure the "verify, don't trust" rule
exists to prevent.

What *is* recoverable is worth more than a stale ID list anyway, and is seeded
into the policy instead: the category set that was searched, which category was
a dead end, which filter actually bound hardest, and the three IDs to exclude.
The screening agent re-derives the pool live against current policy, which it
would have had to do to the stale list regardless — the code-repository-license
filter that produced the original 27 is no longer the policy (owner decision,
2026-08-31), so a recovered Phase 0 list would have needed re-screening in full.
"""

from __future__ import annotations

from paperbench_harbor.construction.core.screen import ScreeningPolicy, SeedCandidate
from paperbench_harbor.construction.lifesci_paperrecon.papers import APPROVED_PAPERS
from paperbench_harbor.construction.lifesci_paperrecon.plugin import LIFESCI_PLUGIN

#: Nothing to re-verify: see this module's docstring. An empty seed list is a
#: supported case — :func:`~..core.screen.build_screening_prompt` tells the
#: agent it is searching from scratch rather than confirming a prior pass.
LIFESCI_SEED_CANDIDATES: tuple[SeedCandidate, ...] = ()

#: Papers already built into the corpus. Derived from the approved set rather
#: than restated, so a promoted candidate is excluded from the next pass by
#: construction rather than by anyone remembering to update a list.
LIFESCI_EXCLUDE_IDS: tuple[str, ...] = tuple(
    spec.arxiv_id for spec in APPROVED_PAPERS
)

LIFESCI_SCREENING_POLICY = ScreeningPolicy(
    name="lifesci",
    paper_types=LIFESCI_PLUGIN.paper_types,
    search_scope="""\
arXiv's quantitative biology categories. Phase 0 searched, and found qualifying
papers in, all of these:

  `q-bio.BM` (biomolecules), `q-bio.QM` (quantitative methods),
  `q-bio.GN` (genomics), `q-bio.MN` (molecular networks),
  `q-bio.CB` (cell behavior), `q-bio.PE` (populations and evolution),
  `q-bio.NC` (neurons and cognition), `q-bio.TO` (tissues and organs)

Use the arXiv API (`http://export.arxiv.org/api/query`) rather than scraping the
listing pages — it paginates properly and returns the categories, versions and
abstracts you need to filter on. Cross-listed papers whose primary category is
outside `q-bio.*` are fine as long as the science is life-sciences.""",
    selection_criteria="""\
The paper must be a life-sciences research paper reporting its own study —
computational, experimental, or a review of a defined literature. Prefer recent
work (the last two to three years) so the linked code is still checkable out and
the dependencies still resolve.

Aim for a mix of paper types and of subject areas rather than fifteen variations
on one method, and prefer papers whose figures are self-contained enough that a
writer given only the figures and a research overview could place them: a paper
whose results live entirely in a supplementary spreadsheet makes a poor sample.

The linked repository should be the code *for this paper* — the analysis or
simulation code the study ran — not a general-purpose library the paper merely
cites, and not a personal dotfiles-grade repository with one script in it.""",
    prior_findings="""\
From the Phase 0 pass, worth not rediscovering at full cost:

- **The license filter bound hardest by a wide margin** — much harder than code
  availability. arXiv-perpetual-only submissions and the `CC BY-NC-SA` /
  `CC BY-ND` combinations are common in this literature and all disqualifying.
  Check the license before spending any time on the e-print bundle or the
  repository.
- **`q-bio.SC` (subcellular processes) was a dead end** — no code-linked
  qualifying papers were found there. Deprioritize it; do not skip it entirely,
  since that finding is from a single pass over an earlier time window.
- Phase 0 checked only that a linked repository *existed*, never its license.
  Under current policy an unlicensed repository is acceptable, so a paper Phase 0
  would have kept is still keepable — but the `license` field must now be read
  and recorded for every candidate, which Phase 0 did not do.""",
)
