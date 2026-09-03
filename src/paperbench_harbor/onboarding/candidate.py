"""Strict data contracts for a proposed Harbor benchmark.

The onboarding agent may discover and describe a benchmark, but that description
is only a claim. These types make the hand-off explicit: deterministic scripts
can verify immutable source facts, and a human has to bind an approved layout
proposal to the exact candidate bytes before implementation may begin.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlparse


class OnboardingError(RuntimeError):
    """A benchmark candidate or approval record is invalid or untrusted."""


@dataclass(frozen=True)
class BenchmarkCandidate:
    """A candidate selected under the paper-writing scope from issue #2."""

    benchmark_id: str
    source_repository: str
    source_revision: str
    source_license: str
    dataset_manifest_url: str
    dataset_manifest_sha256: str
    benchmark_license: str
    sample_count: int
    writer_deliverable: bool
    requires_experiments: bool
    requires_code: bool
    input_protocol: str
    evaluator: str
    selection_record_url: str
    rationale: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class LayoutApproval:
    """A human review that binds a candidate and its proposed layout bytes."""

    candidate_sha256: str
    layout_spec_sha256: str
    reviewer: str


_FIELDS = tuple(BenchmarkCandidate.__dataclass_fields__)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require_string(record: dict[str, object], field: str, *, where: str) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value.strip():
        raise OnboardingError(f"{where} {field!r} must be a non-empty string")
    return value.strip()


def _is_pinned_hex(value: str) -> bool:
    return len(value) in {40, 64} and all(char in "0123456789abcdef" for char in value.lower())


def _immutable_manifest_url(value: str) -> bool:
    """Accept only public manifest URLs whose bytes are tied to a fixed revision."""
    parsed = urlparse(value)
    if parsed.scheme != "https":
        return False
    parts = [part for part in parsed.path.split("/") if part]
    if parsed.netloc == "raw.githubusercontent.com" and len(parts) >= 4:
        return _is_pinned_hex(parts[2])
    if parsed.netloc == "huggingface.co" and "resolve" in parts:
        index = parts.index("resolve")
        return len(parts) > index + 1 and _is_pinned_hex(parts[index + 1])
    return False


def parse_candidate(path: Path) -> BenchmarkCandidate:
    """Read one canonical candidate proposal, rejecting extra or missing claims."""

    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise OnboardingError(f"candidate proposal does not exist: {path}") from error
    except (OSError, json.JSONDecodeError) as error:
        raise OnboardingError(f"cannot parse candidate proposal {path}: {error}") from error
    if not isinstance(record, dict):
        raise OnboardingError(f"candidate proposal {path} must be a JSON object")
    unexpected = sorted(set(record) - set(_FIELDS))
    missing = sorted(set(_FIELDS) - set(record))
    if missing or unexpected:
        detail = []
        if missing:
            detail.append("missing " + ", ".join(missing))
        if unexpected:
            detail.append("unexpected " + ", ".join(unexpected))
        raise OnboardingError(f"candidate proposal {path}: " + "; ".join(detail))

    strings = {
        field: _require_string(record, field, where=str(path))
        for field in _FIELDS
        if field
        not in {"sample_count", "writer_deliverable", "requires_experiments", "requires_code"}
    }
    sample_count = record["sample_count"]
    if not isinstance(sample_count, int) or isinstance(sample_count, bool) or sample_count < 1:
        raise OnboardingError(f"{path} 'sample_count' must be an integer >= 1")
    flags: dict[str, bool] = {}
    for field in ("writer_deliverable", "requires_experiments", "requires_code"):
        value = record[field]
        if not isinstance(value, bool):
            raise OnboardingError(f"{path} {field!r} must be boolean")
        flags[field] = value

    if not flags["writer_deliverable"]:
        raise OnboardingError("candidate is not a manuscript-writing benchmark")
    if flags["requires_experiments"] or flags["requires_code"]:
        raise OnboardingError(
            "candidate evaluates a research agent, not a pure paper-writing agent"
        )
    digest = strings["dataset_manifest_sha256"]
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest.lower()):
        raise OnboardingError(f"{path} dataset_manifest_sha256 must be a SHA-256 hex digest")
    if not strings["selection_record_url"].startswith("https://"):
        raise OnboardingError(f"{path} selection_record_url must be an HTTPS record")
    if not _immutable_manifest_url(strings["dataset_manifest_url"]):
        raise OnboardingError(
            f"{path} dataset_manifest_url must name an immutable GitHub or Hugging Face revision"
        )
    revision = strings["source_revision"]
    if len(revision) != 40 or any(char not in "0123456789abcdef" for char in revision.lower()):
        raise OnboardingError(f"{path} source_revision must be a full Git SHA-1")

    return BenchmarkCandidate(
        benchmark_id=strings["benchmark_id"],
        source_repository=strings["source_repository"],
        source_revision=strings["source_revision"],
        source_license=strings["source_license"],
        dataset_manifest_url=strings["dataset_manifest_url"],
        dataset_manifest_sha256=digest.lower(),
        benchmark_license=strings["benchmark_license"],
        sample_count=sample_count,
        writer_deliverable=flags["writer_deliverable"],
        requires_experiments=flags["requires_experiments"],
        requires_code=flags["requires_code"],
        input_protocol=strings["input_protocol"],
        evaluator=strings["evaluator"],
        selection_record_url=strings["selection_record_url"],
        rationale=strings["rationale"],
    )


def write_candidate(path: Path, candidate: BenchmarkCandidate) -> None:
    """Write the canonical proposal that later approvals digest."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(candidate.as_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def read_layout_approval(
    path: Path, *, candidate_path: Path, layout_spec_path: Path
) -> LayoutApproval:
    """Validate an explicit human approval against immutable proposal bytes."""

    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise OnboardingError(f"human approval is required: {path} does not exist") from error
    except (OSError, json.JSONDecodeError) as error:
        raise OnboardingError(f"cannot read human approval {path}: {error}") from error
    if not isinstance(record, dict) or record.get("schema_version") != 1:
        raise OnboardingError(f"human approval {path} must be a schema_version 1 object")
    expected = {"schema_version", "candidate_sha256", "layout_spec_sha256", "reviewer"}
    if set(record) != expected:
        raise OnboardingError(f"human approval {path} must contain exactly {sorted(expected)}")
    candidate_sha = _require_string(record, "candidate_sha256", where=str(path))
    layout_sha = _require_string(record, "layout_spec_sha256", where=str(path))
    reviewer = _require_string(record, "reviewer", where=str(path))
    if candidate_sha != sha256_file(candidate_path):
        raise OnboardingError("human approval does not match the exact candidate proposal")
    if layout_sha != sha256_file(layout_spec_path):
        raise OnboardingError("human approval does not match the exact layout spec proposal")
    return LayoutApproval(
        candidate_sha256=candidate_sha,
        layout_spec_sha256=layout_sha,
        reviewer=reviewer,
    )
