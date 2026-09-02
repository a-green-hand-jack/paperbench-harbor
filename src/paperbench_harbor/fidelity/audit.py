"""Fidelity audit: verify Harbor tasks against a fixed upstream source tree.

The audit checks, per task:

1. writer-visible files match their declared upstream sources byte-for-byte
   (SHA-256) for content-preserving transforms;
2. every writer-visible file is either a declared content-preserving copy or a
   declared generated/vendor artifact (no undeclared content);
3. verifier-only private copies are byte-identical to their upstream sources
   and none of that content appears in the writer environment;
4. task contract fields (network policy, venue, protocol, compile entrypoint)
   match the current specification.

Dataset-level determinism (repeated conversion produces an identical tree,
manifest, and hashes) is handled by the CLI, which converts the full fixed
input twice into scratch directories and compares digests.
"""

from __future__ import annotations

import tempfile
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from paperbench_harbor.adapters.spec import (
    UpstreamLayoutSpec,
    find_paper_dirs,
    predict_copies,
    rewritable_targets,
)
from paperbench_harbor.common.audit import audit_forbidden_names
from paperbench_harbor.fidelity.origin import compare_to_expectation, derive_origins
from paperbench_harbor.fidelity.review import run_conversion_review
from paperbench_harbor.fidelity.transforms import classify_generated_vendor, sha256

LSPR_BENCHMARK = "LifeSci-PaperRecon"


class FidelityError(RuntimeError):
    """Raised when a fidelity check fails."""


@dataclass
class TaskReport:
    benchmark: str
    task_id: str
    upstream_paper_id: str
    ok: bool
    errors: list[str] = field(default_factory=list)
    writer_files_checked: int = 0
    writer_hashes_matched: int = 0
    verifier_entries_checked: int = 0
    contract_checks: int = 0
    notes: list[str] = field(default_factory=list)
    semantic_reviewed: bool = False
    semantic_verdict: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "benchmark": self.benchmark,
            "task_id": self.task_id,
            "upstream_paper_id": self.upstream_paper_id,
            "ok": self.ok,
            "errors": self.errors,
            "writer_files_checked": self.writer_files_checked,
            "writer_hashes_matched": self.writer_hashes_matched,
            "verifier_entries_checked": self.verifier_entries_checked,
            "contract_checks": self.contract_checks,
            "notes": self.notes,
            "semantic_reviewed": self.semantic_reviewed,
            "semantic_verdict": self.semantic_verdict,
        }


def _writer_visible_files(task_dir: Path) -> list[str]:
    root = task_dir / "environment"
    if not root.is_dir():
        return []
    return sorted(
        f"environment/{path.relative_to(root).as_posix()}"
        for path in root.rglob("*")
        if path.is_file()
    )


def _layout_spec(benchmark: str) -> UpstreamLayoutSpec:
    if benchmark == "PaperWrite-Bench":
        from paperbench_harbor.adapters.paperwrite_bench.spec import SPEC

        return SPEC
    if benchmark == LSPR_BENCHMARK:
        from paperbench_harbor.adapters.lifesci_paperrecon.harbor import SPEC

        return SPEC
    if benchmark == "PaperWritingBench":
        from paperbench_harbor.adapters.paperwritingbench.spec import SPEC

        return SPEC
    raise FidelityError(f"unsupported benchmark for fidelity audit: {benchmark}")


def _paper_dir(spec: UpstreamLayoutSpec, upstream_root: Path, paper_id: str) -> Path:
    matches = [path for path in find_paper_dirs(spec, upstream_root) if path.name == paper_id]
    if len(matches) != 1:
        raise FidelityError(
            f"{spec.benchmark}: expected one source directory for {paper_id!r}, found {len(matches)}"
        )
    return matches[0]


def _private_files(task_dir: Path) -> dict[str, Path]:
    files: dict[str, Path] = {}
    for root in (task_dir / "solution" / "private", task_dir / "tests" / "private"):
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if path.is_file():
                files[path.relative_to(task_dir).as_posix()] = path
    return files


def _matches_generated(rel_path: str, generated: tuple[str, ...]) -> bool:
    return any(
        rel_path == pattern or (pattern.endswith("/") and rel_path.startswith(pattern))
        for pattern in generated
    )


def _audit_writer_surface(
    task_dir: Path,
    paper_dir: Path,
    spec: UpstreamLayoutSpec,
    protocol: str,
    report: TaskReport,
) -> None:
    """Recover writer origins from bytes, then compare that evidence to the spec."""
    origins = derive_origins(task_dir, paper_dir, generated=spec.generated_public)
    rewritable = rewritable_targets(spec)
    report.writer_files_checked += origins.checked
    report.writer_hashes_matched += len(origins.from_upstream)
    report.notes.extend(f"generated/vendor: {rel}" for rel in origins.generated_or_vendor)
    expected = predict_copies(spec, paper_dir, protocol)
    report.errors.extend(
        f"undeclared writer-visible file: {rel} has no upstream origin or generated declaration"
        for rel in origins.unexplained
        if rel not in rewritable and rel not in expected
    )
    report.errors.extend(
        compare_to_expectation(
            origins,
            expected,
            paper_dir,
            rewritable=rewritable,
        )
    )


def _audit_verifier(
    task_dir: Path,
    paper_dir: Path,
    spec: UpstreamLayoutSpec,
    protocol: str,
    report: TaskReport,
) -> None:
    """Verify the entire private surface against actual upstream bytes and rules."""
    expected = predict_copies(spec, paper_dir, protocol, private=True)
    actual = _private_files(task_dir)
    for target, source in sorted(expected.items()):
        report.verifier_entries_checked += 1
        target_path = actual.get(target)
        if target_path is None:
            report.errors.append(f"verifier target missing: {target}")
        elif sha256(source) != sha256(target_path):
            report.errors.append(f"verifier content mismatch: {source} -> {target}")

    for target in sorted(actual):
        if target not in expected and not _matches_generated(target, spec.generated_private):
            report.errors.append(f"undeclared verifier-only file: {target}")
    for target in spec.generated_private:
        if not target.endswith("/") and target not in actual:
            report.errors.append(f"generated verifier file missing: {target}")

    public_hashes = {
        sha256(source) for source in predict_copies(spec, paper_dir, protocol).values()
    }
    writer_hashes = {
        sha256(task_dir / rel)
        for rel in _writer_visible_files(task_dir)
        if not classify_generated_vendor(rel) and not _matches_generated(rel, spec.generated_public)
    }
    for source in sorted(set(expected.values())):
        if sha256(source) in public_hashes:
            continue
        if sha256(source) in writer_hashes:
            report.errors.append(
                f"verifier-only content leaked into writer environment: {source.relative_to(paper_dir)}"
            )

    try:
        audit_forbidden_names(
            task_dir / "environment",
            set(spec.forbidden_public_names),
            ignore_globs=spec.forbidden_public_ignore_globs,
        )
    except RuntimeError as exc:
        report.errors.append(str(exc))


#: Harbor's network policy vocabulary (`harbor.models.task.config.NetworkMode`).
NETWORK_MODES = frozenset({"no-network", "public", "allowlist"})

#: What an `[environment]` baseline means when it declares nothing. Harbor's
#: `BaselineNetworkPolicyConfig.network_mode` defaults to `public`.
DEFAULT_NETWORK_MODE = "public"

#: The policy the current task specification expects, per execution phase.
#: These are the values the audit enforces; changing the generated templates
#: means changing these in the same commit.
EXPECTED_NETWORK_MODES = {
    "agent": "public",
    "verifier": "public",
}


def _table(config: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    section = config.get(key)
    return section if isinstance(section, Mapping) else {}


def _declared_baseline(section: Mapping[str, Any]) -> str | None:
    """Resolve one `[environment]`-shaped section's declared network baseline.

    Returns `None` when the section declares no policy at all, which is what
    makes the caller fall through to the next level of Harbor's inheritance.
    An explicit `network_mode` wins over the deprecated `allow_internet`,
    matching Harbor's `_apply_legacy_allow_internet`, which only migrates the
    legacy field when `network_mode` was not set.
    """
    declared = section.get("network_mode")
    if declared is not None:
        return str(declared)
    legacy = section.get("allow_internet")
    if legacy is None:
        return None
    return "public" if legacy else "no-network"


def effective_network_mode(config: Mapping[str, Any], phase: str) -> str:
    """The network policy Harbor will actually apply to one execution phase.

    Replicates Harbor 0.22.0's resolution order so the audit checks the policy
    that takes effect rather than the policy a file appears to declare:

    1. `[<phase>].network_mode`, an explicit phase override;
    2. `[<phase>.environment]`'s own baseline, where the phase runs in a
       separate environment that declares one;
    3. the top-level `[environment]` baseline;
    4. `public`, Harbor's default when nothing declares anything.

    A task that sets `environment_mode = "separate"` but no verifier policy
    therefore inherits the writer environment's baseline -- it does not become
    isolated by virtue of being separate.
    """
    phase_section = _table(config, phase)
    declared = phase_section.get("network_mode")
    if declared is not None:
        return str(declared)
    nested = phase_section.get("environment")
    if isinstance(nested, Mapping):
        baseline = _declared_baseline(nested)
        if baseline is not None:
            return baseline
    baseline = _declared_baseline(_table(config, "environment"))
    return baseline if baseline is not None else DEFAULT_NETWORK_MODE


def _audit_contract(
    task_dir: Path,
    report: TaskReport,
) -> None:
    """Verify task contract fields against the current specification.

    The `protocol` / `venue` mapping is recorded in the dataset-level manifest,
    not in task.toml, so that mapping is checked by the CLI's mapping stage
    rather than here. Here we verify the fields task.toml and instruction.md
    actually declare.

    task.toml is parsed, not searched. A substring check cannot distinguish a
    declared policy from an inherited one, and it pins one spelling of a field
    that Harbor may deprecate underneath it.
    """
    task_toml = task_dir / "task.toml"
    if not task_toml.is_file():
        report.errors.append("task.toml missing")
        return
    text = task_toml.read_text(encoding="utf-8", errors="replace")
    try:
        config = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        report.contract_checks += 1
        report.errors.append(f"contract check failed: task.toml is not valid TOML ({exc})")
        return

    checks: list[tuple[str, bool]] = [
        (
            'verifier environment_mode = "separate"',
            _table(config, "verifier").get("environment_mode") == "separate",
        ),
    ]
    for phase, expected in EXPECTED_NETWORK_MODES.items():
        actual = effective_network_mode(config, phase)
        checks.append(
            (
                f"{phase} network policy is {expected!r} (declared or inherited), got {actual!r}",
                actual == expected,
            )
        )
        checks.append(
            (
                f"{phase} network policy {actual!r} is a Harbor network mode",
                actual in NETWORK_MODES,
            )
        )
    for name, passed in checks:
        report.contract_checks += 1
        if not passed:
            report.errors.append(f"contract check failed: {name}")

    instruction = task_dir / "instruction.md"
    if instruction.is_file():
        itext = instruction.read_text(encoding="utf-8", errors="replace")
        entry_checks = [
            ("main.tex entry", "main.tex" in itext),
            ("references.bib entry", "references.bib" in itext),
        ]
        for name, passed in entry_checks:
            report.contract_checks += 1
            if not passed:
                report.errors.append(f"instruction contract failed: {name}")


def run_fidelity_audit(
    *,
    benchmark: str,
    task_id: str,
    upstream_paper_id: str,
    upstream_root: Path,
    task_dir: Path,
    protocol: str,
    venue: str | None,
    semantic_review: bool = False,
    reviewer_model: str | None = None,
    review_log_dir: Path | None = None,
) -> TaskReport:
    """Run the full fidelity audit for a single task."""
    report = TaskReport(
        benchmark=benchmark,
        task_id=task_id,
        upstream_paper_id=upstream_paper_id,
        ok=True,
    )

    del venue  # Layout specs identify the source paper without a benchmark dispatch chain.
    spec = _layout_spec(benchmark)
    paper_dir = _paper_dir(spec, upstream_root, upstream_paper_id)
    _audit_writer_surface(task_dir, paper_dir, spec, protocol, report)
    _audit_verifier(task_dir, paper_dir, spec, protocol, report)
    _audit_contract(task_dir, report)
    if semantic_review:
        report.semantic_reviewed = True
        verdict = run_conversion_review(
            benchmark=benchmark,
            paper_id=upstream_paper_id,
            paper_dir=paper_dir,
            task_dir=task_dir,
            protocol=protocol,
            model=reviewer_model,
            log_dir=review_log_dir
            or Path(tempfile.gettempdir()) / "paperbench-harbor-fidelity-review-logs",
        )
        report.semantic_verdict = verdict.as_dict()
        if not verdict.ok:
            report.errors.append(f"semantic review failed: {verdict.reasoning}")
            report.errors.extend(f"semantic concern: {concern}" for concern in verdict.concerns)

    report.ok = not report.errors
    return report


def summarize(reports: list[TaskReport]) -> dict[str, Any]:
    """Build an overall summary across tasks."""
    total = len(reports)
    passed = sum(1 for report in reports if report.ok)
    return {
        "total_tasks": total,
        "passed_tasks": passed,
        "failed_tasks": total - passed,
        "writer_files_checked": sum(r.writer_files_checked for r in reports),
        "writer_hashes_matched": sum(r.writer_hashes_matched for r in reports),
        "verifier_entries_checked": sum(r.verifier_entries_checked for r in reports),
        "contract_checks": sum(r.contract_checks for r in reports),
        "semantic_reviews": sum(r.semantic_reviewed for r in reports),
        "semantic_review_failures": sum(
            r.semantic_reviewed and not (r.semantic_verdict or {}).get("ok", False) for r in reports
        ),
        "failed_tasks_detail": [
            {"task_id": r.task_id, "errors": r.errors} for r in reports if not r.ok
        ],
    }
