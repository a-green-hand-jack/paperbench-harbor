"""Human-approved, declarative source layout for a new Harbor benchmark.

The onboarding agent writes this JSON outside the repository.  It is data, not
an adapter implementation: after an independent candidate check and a
SHA-256-bound human approval, the generic converter consumes it directly.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from paperbench_harbor.adapters.spec import (
    BenchmarkIdentity,
    CopyRule,
    RenderDefaults,
    UpstreamLayoutSpec,
)
from paperbench_harbor.onboarding.candidate import (
    BenchmarkCandidate,
    OnboardingError,
    read_layout_approval,
)


@dataclass(frozen=True)
class ApprovedLayout:
    """The one spec shape the generic onboarding converter accepts."""

    candidate_id: str
    layout: UpstreamLayoutSpec
    writer_instructions: str
    candidate_sha256: str | None = None
    layout_spec_sha256: str | None = None
    reviewer: str | None = None


_TOP_LEVEL = {
    "schema_version",
    "candidate_id",
    "identity",
    "paper_glob",
    "discovery_marker",
    "public",
    "private",
    "forbidden_public_names",
    "writer_instructions",
    "render",
}
_IDENTITY = {"benchmark", "task_id_prefix", "tags", "relevant_experience"}
_RENDER = {"category", "num_page", "column"}
_RULE = {
    "source",
    "target",
    "kind",
    "required",
    "extra_targets",
    "tree_excludes",
    "tree_exclude_globs",
    "may_be_rewritten",
    "protocols",
}
_REQUIRED_PUBLIC = {
    "environment/materials/research_overview.md",
    "environment/materials/template.tex",
    "environment/materials/references.bib",
}
_REQUIRED_PRIVATE = {"solution/private/main.tex"}


def _object(value: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise OnboardingError(f"{label} must be a JSON object")
    return value


def _exact_keys(value: dict[str, Any], expected: set[str], *, label: str) -> None:
    missing = sorted(expected - set(value))
    unexpected = sorted(set(value) - expected)
    if missing or unexpected:
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if unexpected:
            details.append("unexpected " + ", ".join(unexpected))
        raise OnboardingError(f"{label}: " + "; ".join(details))


def _string(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OnboardingError(f"{label} must be a non-empty string")
    return value.strip()


def _strings(value: Any, *, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise OnboardingError(f"{label} must be a list of non-empty strings")
    return tuple(item.strip() for item in value)


def _rule(value: Any, *, label: str) -> CopyRule:
    record = _object(value, label=label)
    _exact_keys(record, _RULE, label=label)
    kind = _string(record["kind"], label=f"{label} kind")
    if kind not in {"file", "tree"}:
        raise OnboardingError(f"{label} kind must be file or tree")
    for field in ("required", "may_be_rewritten"):
        if not isinstance(record[field], bool):
            raise OnboardingError(f"{label} {field} must be boolean")
    return CopyRule(
        source=_string(record["source"], label=f"{label} source"),
        target=_string(record["target"], label=f"{label} target"),
        kind=kind,
        required=record["required"],
        extra_targets=_strings(record["extra_targets"], label=f"{label} extra_targets"),
        tree_excludes=_strings(record["tree_excludes"], label=f"{label} tree_excludes"),
        tree_exclude_globs=_strings(
            record["tree_exclude_globs"], label=f"{label} tree_exclude_globs"
        ),
        may_be_rewritten=record["may_be_rewritten"],
        protocols=_strings(record["protocols"], label=f"{label} protocols"),
    )


def parse_layout_spec(path: Path, *, candidate: BenchmarkCandidate) -> ApprovedLayout:
    """Parse a strict, portable proposal without trusting an adapter module."""

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise OnboardingError(f"layout spec does not exist: {path}") from error
    except (OSError, json.JSONDecodeError) as error:
        raise OnboardingError(f"cannot parse layout spec {path}: {error}") from error
    record = _object(value, label="layout spec")
    _exact_keys(record, _TOP_LEVEL, label="layout spec")
    if record["schema_version"] != 1:
        raise OnboardingError("layout spec schema_version must be 1")
    candidate_id = _string(record["candidate_id"], label="layout spec candidate_id")
    if candidate_id != candidate.benchmark_id:
        raise OnboardingError("layout spec candidate_id does not match the approved candidate")

    identity = _object(record["identity"], label="layout spec identity")
    _exact_keys(identity, _IDENTITY, label="layout spec identity")
    render = _object(record["render"], label="layout spec render")
    _exact_keys(render, _RENDER, label="layout spec render")
    column = _string(render["column"], label="layout spec render column")
    if column not in {"single-column", "double-column"}:
        raise OnboardingError("layout spec render column must be single-column or double-column")

    if not isinstance(record["public"], list) or not isinstance(record["private"], list):
        raise OnboardingError("layout spec public and private must be lists")
    public = tuple(
        _rule(item, label=f"layout spec public[{index}]")
        for index, item in enumerate(record["public"])
    )
    private = tuple(
        _rule(item, label=f"layout spec private[{index}]")
        for index, item in enumerate(record["private"])
    )
    public_targets = {target for rule in public for target in rule.targets()}
    private_targets = {target for rule in private for target in rule.targets()}
    missing_public = sorted(_REQUIRED_PUBLIC - public_targets)
    missing_private = sorted(_REQUIRED_PRIVATE - private_targets)
    if missing_public or missing_private:
        details = []
        if missing_public:
            details.append("required public targets missing: " + ", ".join(missing_public))
        if missing_private:
            details.append("required private targets missing: " + ", ".join(missing_private))
        raise OnboardingError("layout spec " + "; ".join(details))

    forbidden = _strings(record["forbidden_public_names"], label="layout spec forbidden_public_names")
    layout = UpstreamLayoutSpec(
        identity=BenchmarkIdentity(
            benchmark=_string(identity["benchmark"], label="layout spec identity benchmark"),
            task_id_prefix=_string(
                identity["task_id_prefix"], label="layout spec identity task_id_prefix"
            ),
            tags=_strings(identity["tags"], label="layout spec identity tags"),
            relevant_experience=_string(
                identity["relevant_experience"],
                label="layout spec identity relevant_experience",
            ),
        ),
        paper_glob=_string(record["paper_glob"], label="layout spec paper_glob"),
        discovery_marker=_string(
            record["discovery_marker"], label="layout spec discovery_marker"
        ),
        public=public,
        private=private,
        forbidden_public_names=frozenset(forbidden),
        generated_public=("environment/materials/AGENTS.md",),
        generated_private=("tests/private/source_manifest.json",),
        render=RenderDefaults(
            category=_string(render["category"], label="layout spec render category"),
            num_page=_string(render["num_page"], label="layout spec render num_page"),
            column=column,
        ),
    )
    return ApprovedLayout(
        candidate_id=candidate_id,
        layout=layout,
        writer_instructions=_string(
            record["writer_instructions"], label="layout spec writer_instructions"
        ),
    )


def load_approved_layout(
    path: Path, *, candidate_path: Path, approval_path: Path, candidate: BenchmarkCandidate
) -> ApprovedLayout:
    """Require a human approval before parsing the layout into executable data."""

    approval = read_layout_approval(
        approval_path,
        candidate_path=candidate_path,
        layout_spec_path=path,
    )
    return replace(
        parse_layout_spec(path, candidate=candidate),
        candidate_sha256=approval.candidate_sha256,
        layout_spec_sha256=approval.layout_spec_sha256,
        reviewer=approval.reviewer,
    )
