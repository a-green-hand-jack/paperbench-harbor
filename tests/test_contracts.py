from pathlib import Path

from paperbench_harbor.common.contracts import SubmissionContract


def test_submission_contract_is_stable() -> None:
    contract = SubmissionContract()
    assert contract.root == Path("/workspace/submission")
    assert contract.required_relative_paths == ("main.tex", "references.bib")
