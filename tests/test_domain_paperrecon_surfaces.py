"""Contracts shared by the three new PaperRecon domain surfaces."""

from __future__ import annotations

import json

import pytest

from paperbench_harbor.adapters.chemistry_paperrecon.harbor import (
    IDENTITY as CHEMISTRY_IDENTITY,
)
from paperbench_harbor.adapters.mathematics_paperrecon.harbor import (
    IDENTITY as MATHEMATICS_IDENTITY,
)
from paperbench_harbor.adapters.physics_paperrecon.harbor import IDENTITY as PHYSICS_IDENTITY
from paperbench_harbor.construction.chemistry_paperrecon.papers import (
    APPROVED_PAPERS as CHEMISTRY_APPROVED,
)
from paperbench_harbor.construction.chemistry_paperrecon.plugin import CHEMISTRY_PLUGIN
from paperbench_harbor.construction.chemistry_paperrecon.screening import (
    CHEMISTRY_SCREENING_POLICY,
)
from paperbench_harbor.construction.mathematics_paperrecon.papers import (
    APPROVED_PAPERS as MATHEMATICS_APPROVED,
)
from paperbench_harbor.construction.mathematics_paperrecon.plugin import MATHEMATICS_PLUGIN
from paperbench_harbor.construction.mathematics_paperrecon.screening import (
    MATHEMATICS_SCREENING_POLICY,
)
from paperbench_harbor.construction.physics_paperrecon.papers import (
    APPROVED_PAPERS as PHYSICS_APPROVED,
)
from paperbench_harbor.construction.physics_paperrecon.papers import (
    _load_scaleup_promotions,
)
from paperbench_harbor.construction.physics_paperrecon.plugin import PHYSICS_PLUGIN
from paperbench_harbor.construction.physics_paperrecon.screening import (
    PHYSICS_SCREENING_POLICY,
)


@pytest.mark.parametrize(
    ("plugin", "policy", "identity", "prefix", "expected_types"),
    (
        (PHYSICS_PLUGIN, PHYSICS_SCREENING_POLICY, PHYSICS_IDENTITY, "phys", ("theory", "simulation", "experimental")),
        (CHEMISTRY_PLUGIN, CHEMISTRY_SCREENING_POLICY, CHEMISTRY_IDENTITY, "chem", ("synthesis_characterization", "computational_chemistry", "cheminformatics_ml")),
        (MATHEMATICS_PLUGIN, MATHEMATICS_SCREENING_POLICY, MATHEMATICS_IDENTITY, "math", ("theorem_proof", "numerical", "formalized_computer_assisted")),
    ),
)
def test_domain_contracts_are_explicit(plugin, policy, identity, prefix, expected_types) -> None:
    assert plugin.paper_types == expected_types
    assert policy.paper_types == expected_types
    assert identity.task_id_prefix == prefix
    assert plugin.significance_heading in plugin.overview_skeleton_headings
    assert "LKM" in policy.search_scope


def test_new_domains_start_without_machine_approved_papers() -> None:
    assert PHYSICS_APPROVED == ()
    assert CHEMISTRY_APPROVED == ()
    assert MATHEMATICS_APPROVED == ()


def test_scaleup_loader_preserves_the_no_code_approval_contract(tmp_path) -> None:
    approved = tmp_path / "approved_scaleup.jsonl"
    approved.write_text(
        "\n".join(
            json.dumps(record)
            for record in (
                {"paper_id": "phys_1", "arxiv_id": "2601.00001", "paper_type": "theory", "code_repo": "", "expected_license": "CC BY 4.0", "expected_version": "v1", "expected_category": "hep-th", "note": "proof-only", "code_status": "not_applicable", "code_not_applicable_reason": "The approved source establishes a proof without software inputs."},
                {"paper_id": "phys_2", "arxiv_id": "2601.00002", "paper_type": "simulation", "code_repo": "https://github.com/example/sim", "expected_license": "CC BY 4.0", "expected_version": "v1", "expected_category": "physics.comp-ph", "note": "simulation", "code_status": "available", "code_not_applicable_reason": ""},
            )
        ),
        encoding="utf-8",
    )

    specs = _load_scaleup_promotions(approved)

    assert [spec.paper_id for spec in specs] == ["phys_1", "phys_2"]
    assert not specs[0].requires_code
    assert specs[0].code_not_applicable_reason
    assert specs[1].requires_code


def test_scaleup_loader_rejects_an_incomplete_approval(tmp_path) -> None:
    approved = tmp_path / "approved_scaleup.jsonl"
    approved.write_text('{"paper_id":"phys_1"}\n', encoding="utf-8")

    with pytest.raises(ValueError, match="missing"):
        _load_scaleup_promotions(approved)
