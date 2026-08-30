"""Driving one `opencode` CLI session per paper.

The interesting decisions here are about containment, not about the agent.
`--auto` auto-approves every tool call, which the CLI itself labels dangerous:
the agent gets unsupervised shell and file-write access for the length of the
run. Two rules follow, and :func:`run_construction` enforces both rather than
documenting them:

* the working directory is an isolated scratch tree that is **not inside any
  git working tree** — a `--auto` run pointed at the repository could rewrite
  the code that is supposed to be judging it;
* nothing the agent produces enters the corpus until
  :mod:`.validate` has passed it.

Retries continue the same opencode session (``--continue``) instead of starting
fresh, so the agent still has the context of what it built and why, and is
correcting its own work rather than rebuilding blind from a diff.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_MODEL = "openai/gpt-5.6-terra"

#: Long enough for a full fetch/build/compile-iterate cycle on a 50-page paper
#: with a large figure set; short enough that a wedged run does not hold the
#: pilot open indefinitely.
DEFAULT_TIMEOUT_SECONDS = 5400


class ScratchLocationError(RuntimeError):
    """Raised when a `--auto` run would be pointed somewhere unsafe."""


@dataclass(frozen=True)
class AgentRun:
    """One completed `opencode run` invocation."""

    paper_id: str
    turn: int
    command: tuple[str, ...]
    returncode: int
    log_path: Path
    started_at: str
    finished_at: str
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out


def _enclosing_git_root(path: Path) -> Path | None:
    """Return the git working tree containing `path`, if any.

    Checked by walking for a `.git` entry rather than by shelling out to git,
    so the answer does not depend on git being installed or on the agent's own
    environment.
    """

    for candidate in [path, *path.parents]:
        if (candidate / ".git").exists():
            return candidate
    return None


def prepare_scratch(scratch_root: Path, paper_id: str, *, fresh: bool = False) -> Path:
    """Create (and vet) the isolated workspace for one paper's agent session."""

    workspace = (scratch_root / paper_id).resolve()
    git_root = _enclosing_git_root(workspace if workspace.exists() else scratch_root.resolve())
    if git_root is not None:
        raise ScratchLocationError(
            f"refusing to run an --auto agent in {workspace}: it is inside the git "
            f"working tree at {git_root}. The scratch workspace must live outside "
            "any repository; validated output is copied into the corpus afterwards."
        )
    if fresh and workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


def run_construction(
    *,
    paper_id: str,
    prompt: str,
    workspace: Path,
    log_dir: Path,
    model: str = DEFAULT_MODEL,
    turn: int = 1,
    continue_session: bool = False,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    dry_run: bool = False,
) -> AgentRun:
    """Invoke `opencode run` for one construction turn and record it.

    The prompt is passed as an argument rather than piped so that the exact
    command is reproducible from the log: a human re-running the build should
    be able to copy the recorded command line verbatim.
    """

    if _enclosing_git_root(workspace) is not None:
        raise ScratchLocationError(f"{workspace} is inside a git working tree")

    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{paper_id}.turn{turn}.log"

    command: tuple[str, ...] = (
        "opencode",
        "run",
        "--model",
        model,
        "--auto",
        "--dir",
        str(workspace),
        *(("--continue",) if continue_session else ()),
        prompt,
    )

    started_at = datetime.now(UTC).isoformat(timespec="seconds")
    if dry_run:
        log_path.write_text(
            "DRY RUN - not executed\n\n" + "\n".join(command) + "\n", encoding="utf-8"
        )
        return AgentRun(
            paper_id=paper_id,
            turn=turn,
            command=command,
            returncode=0,
            log_path=log_path,
            started_at=started_at,
            finished_at=started_at,
        )

    environment = dict(os.environ)
    # opencode writes its own session state under the user's home; keep it out
    # of the scratch tree so `--continue` survives a `--fresh` rebuild.
    environment.setdefault("OPENCODE_DISABLE_AUTOUPDATE", "1")

    timed_out = False
    with log_path.open("w", encoding="utf-8") as log:
        log.write(f"# {started_at}\n# command: {command!r}\n\n")
        log.flush()
        try:
            completed = subprocess.run(
                command,
                cwd=str(workspace),
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                check=False,
            )
            returncode = completed.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            returncode = 124
            log.write(f"\n\n# TIMED OUT after {timeout}s\n")
        except FileNotFoundError:
            raise RuntimeError(
                "`opencode` is not on PATH. This build must run on a host with "
                "the opencode CLI installed and its providers configured."
            ) from None

    return AgentRun(
        paper_id=paper_id,
        turn=turn,
        command=command,
        returncode=returncode,
        log_path=log_path,
        started_at=started_at,
        finished_at=datetime.now(UTC).isoformat(timespec="seconds"),
        timed_out=timed_out,
    )


def tail_log(run: AgentRun, lines: int = 40) -> str:
    """The end of an agent log, for reporting a failure without dumping it."""

    if not run.log_path.is_file():
        return ""
    content = run.log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(content[-lines:])


def check_opencode_available(model: str = DEFAULT_MODEL) -> None:
    """Fail early and clearly if the CLI or the configured model is missing."""

    if shutil.which("opencode") is None:
        raise RuntimeError("`opencode` is not on PATH")
    result = subprocess.run(
        ("opencode", "models"),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"`opencode models` failed:\n{result.stderr[-2000:]}")
    if model not in result.stdout.split():
        print(
            f"warning: model {model!r} was not listed by `opencode models`; "
            "the run may fail",
            file=sys.stderr,
        )
