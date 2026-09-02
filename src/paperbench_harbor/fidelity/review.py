"""Independent semantic review for a converted Harbor task."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from paperbench_harbor.construction.core.opencode_agent import (
    DEFAULT_TIMEOUT_SECONDS,
    run_agent_session,
)
from paperbench_harbor.construction.core.review import ReviewVerdict, parse_verdict

DEFAULT_CONVERSION_REVIEWER_MODEL = "apex-claude/claude-sonnet-5"
VERDICT_FILENAME = "verdict.json"


def _review_scratch_root() -> Path:
    """Return a disposable review root that cannot inherit a repository's Git state.

    Some controlled workers mount `/tmp` inside a repository-shaped sandbox.
    `run_agent_session()` rightly rejects `--auto` there, but a semantic audit
    must still be runnable. Keep the staged evidence under a dedicated cache
    directory instead, or use an explicitly supplied, non-Git location.
    """
    configured = os.environ.get("PAPERBENCH_REVIEW_TMP", "").strip()
    root = (
        Path(configured) if configured else Path.home() / ".cache" / "paperbench-harbor" / "reviews"
    )
    root.mkdir(parents=True, exist_ok=True)
    resolved = root.resolve()
    for candidate in (resolved, *resolved.parents):
        if (candidate / ".git").exists():
            raise RuntimeError(
                f"semantic review scratch root {resolved} is inside a Git working tree; "
                "set PAPERBENCH_REVIEW_TMP to an isolated directory"
            )
    return resolved


def default_conversion_reviewer_model() -> str:
    """Resolve the reviewer separately from the converter model."""
    return (
        os.environ.get("CONVERSION_REVIEWER_MODEL", "").strip() or DEFAULT_CONVERSION_REVIEWER_MODEL
    )


def _copytree(source: Path, destination: Path) -> None:
    shutil.copytree(
        source,
        destination,
        symlinks=True,
        ignore=shutil.ignore_patterns(".git", "__pycache__", ".opencode"),
    )


def prepare_conversion_review_dir(
    paper_dir: Path,
    task_dir: Path,
    review_dir: Path,
) -> Path:
    """Stage only the evidence an independent conversion reviewer may inspect."""
    if review_dir.exists():
        shutil.rmtree(review_dir)
    review_dir.mkdir(parents=True)

    _copytree(paper_dir, review_dir / "upstream")
    task_evidence = review_dir / "task"
    task_evidence.mkdir()
    for filename in ("instruction.md", "task.toml"):
        source = task_dir / filename
        if not source.is_file():
            raise FileNotFoundError(f"conversion review input missing: {source}")
        shutil.copy2(source, task_evidence / filename)

    environment = task_dir / "environment"
    if not environment.is_dir():
        raise FileNotFoundError(f"conversion review input missing: {environment}")
    _copytree(environment, task_evidence / "environment")
    return review_dir


def build_conversion_review_prompt(review_dir: Path, benchmark: str) -> str:
    """Ask a reviewer to judge fidelity without revealing implementation claims."""
    return f"""\
You are independently reviewing one Harbor conversion for {benchmark}. You did
not build it. Do not repair it. Read the actual upstream sample and the task
evidence staged below, then write exactly one JSON verdict.

# Evidence

- `{review_dir}/upstream/` is the complete upstream sample used for conversion.
- `{review_dir}/task/instruction.md` and `task.toml` are the generated task contract.
- `{review_dir}/task/environment/` is everything writer-visible in the Harbor task,
  including the material directory and the isolated LaTeX support files.

You were intentionally not given a layout spec, converter code, transform
declarations, `solution/`, or `tests/`. Do not infer facts from files you do not
have.

# Decide

Pass only when the generated instruction faithfully expresses the upstream
writing protocol, the writer-visible materials correspond to the upstream
public inputs, and the task does not hand over private ground truth or omit
material that the protocol requires. Name concrete source and task paths for
every concern. A clean structural audit is not evidence of semantic fidelity.

# Output

Write `{review_dir}/{VERDICT_FILENAME}` as one JSON object and nothing else:

```json
{{
  "ok": true,
  "reasoning": "specific evidence reviewed",
  "concerns": []
}}
```

`ok` must be a JSON boolean. `reasoning` must be non-empty. If `ok` is false,
`concerns` must be a non-empty list of actionable strings. Do not modify any
evidence file; the directory is disposable, but the verdict is the only output.
"""


def run_conversion_review(
    *,
    benchmark: str,
    paper_id: str,
    paper_dir: Path,
    task_dir: Path,
    model: str | None = None,
    log_dir: Path,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    dry_run: bool = False,
) -> ReviewVerdict:
    """Run one isolated reviewer and return a strictly parsed verdict."""
    with tempfile.TemporaryDirectory(
        prefix="paperbench-conversion-review-", dir=_review_scratch_root()
    ) as temporary:
        review_dir = prepare_conversion_review_dir(paper_dir, task_dir, Path(temporary))
        prompt = build_conversion_review_prompt(review_dir, benchmark)
        try:
            run = run_agent_session(
                paper_id=paper_id,
                prompt=prompt,
                workspace=review_dir,
                log_dir=log_dir,
                model=model or default_conversion_reviewer_model(),
                timeout=timeout,
                dry_run=dry_run,
            )
        except Exception as error:  # noqa: BLE001 - review failures must fail the audit.
            return ReviewVerdict(ok=False, reasoning=str(error), concerns=[str(error)])
        if not run.ok:
            reason = f"semantic reviewer exited {run.returncode} (timed_out={run.timed_out})"
            return ReviewVerdict(ok=False, reasoning=reason, concerns=[reason])
        try:
            return parse_verdict(review_dir / VERDICT_FILENAME)
        except Exception as error:  # noqa: BLE001 - hostile reviewer output is a failed review.
            return ReviewVerdict(ok=False, reasoning=str(error), concerns=[str(error)])
