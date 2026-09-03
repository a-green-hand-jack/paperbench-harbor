"""Human-approved Physics-PaperRecon papers.

The registry intentionally starts empty. Screening output is only a proposal;
the scale-up file may be populated only by the SHA-bound human approval gate.
"""

from __future__ import annotations

import json
from pathlib import Path

from paperbench_harbor.construction.core.spec import ACCEPTED_LICENSES, PaperSpec

__all__ = ["ACCEPTED_LICENSES", "APPROVED_BY_ID", "APPROVED_PAPERS", "PaperSpec"]

APPROVED_SCALEUP_PATH = Path(__file__).resolve().parent / "approved_scaleup.jsonl"
_SCALEUP_FIELDS = (
    "paper_id",
    "arxiv_id",
    "paper_type",
    "code_repo",
    "expected_license",
    "expected_version",
    "expected_category",
    "note",
    "code_status",
    "code_not_applicable_reason",
)


def _load_scaleup_promotions(path: Path) -> tuple[PaperSpec, ...]:
    """Load SHA-approved records; malformed approvals must stop the build."""

    if not path.is_file():
        return ()
    specs: list[PaperSpec] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"{path.name}:{number} is not valid JSON: {error}") from error
        if not isinstance(record, dict):
            raise TypeError(f"{path.name}:{number} is not a JSON object")
        missing = [field for field in _SCALEUP_FIELDS if field not in record]
        if missing:
            raise ValueError(f"{path.name}:{number} is missing {missing}")
        specs.append(PaperSpec(**{field: record[field] for field in _SCALEUP_FIELDS}))
    return tuple(specs)


APPROVED_PAPERS = _load_scaleup_promotions(APPROVED_SCALEUP_PATH)
APPROVED_BY_ID = {spec.paper_id: spec for spec in APPROVED_PAPERS}
