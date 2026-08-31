"""The LifeSci-PaperRecon pilot paper set.

These three papers were selected by hand (approved plan, "Phase 0 results") to
give the pilot mixed paper-type coverage rather than three samples of the same
shape. That mix is a deliberate human decision, so the build **never
substitutes a paper**: if re-verification finds that a paper no longer
qualifies — the license changed, the submission is PDF-only, the linked
repository is gone — the build stops and reports, and a human re-decides.

Every field below is an *expectation* the construction agent must re-verify
against the live arXiv abstract page, not a trusted fact. The validation gate
(:mod:`paperbench_harbor.construction.core.validate`) cross-checks the agent's
recorded `provenance.json` against these expectations and fails the paper on any
mismatch.

:class:`PaperSpec` and :data:`ACCEPTED_LICENSES` are re-exported from
:mod:`paperbench_harbor.construction.core.spec`, where they moved when
PaperSmith was split into a core and per-domain plugins; neither ever carried a
biology-specific field.
"""

from __future__ import annotations

from paperbench_harbor.construction.core.spec import ACCEPTED_LICENSES, PaperSpec

__all__ = ["ACCEPTED_LICENSES", "PILOT_BY_ID", "PILOT_PAPERS", "PaperSpec"]

PILOT_PAPERS: tuple[PaperSpec, ...] = (
    PaperSpec(
        paper_id="paper_1",
        arxiv_id="2606.27607",
        paper_type="computational",
        code_repo="https://github.com/beagle-dev/beagle-lib",
        expected_license="CC BY 4.0",
        expected_version="v1",
        expected_category="q-bio.PE",
        note="BEAGLE 4.1 — phylogenetics library / tool paper.",
    ),
    PaperSpec(
        paper_id="paper_2",
        arxiv_id="2503.19375",
        paper_type="computational",
        code_repo=(
            "https://github.com/DominicDevlin/"
            "Stem-cell-differentiation-underpins-reproducible-morphogenesis"
        ),
        expected_license="CC BY 4.0",
        expected_version="v2",
        expected_category="q-bio.CB",
        note=(
            "Cell differentiation underpins reproducible morphogenesis — "
            "hypothesis-driven simulation study."
        ),
    ),
    PaperSpec(
        paper_id="paper_3",
        arxiv_id="2601.02265",
        paper_type="experimental",
        code_repo="https://github.com/mdsamad001/Drug_Release_Dynamics_Prediction",
        expected_license="CC BY-SA 4.0",
        expected_version="v1",
        expected_category="q-bio.BM",
        note="Explainable ML for drug-release prediction — applied empirical study.",
    ),
)

PILOT_BY_ID = {spec.paper_id: spec for spec in PILOT_PAPERS}
