"""Core helpers for the paper-run Harbor agent.

This module is intentionally free of any ``harbor`` import so it can be unit
tested on a machine without Harbor installed.  It builds the exact shell
command sequences that the ``PaperRun`` agent executes inside the task
environment, plus the brief file and the submission export mapping.

All facts about the ``paper-run`` CLI (commands, flags, output paths) are
derived from the pinned revision ``PAPER_RUN_COMMIT``.
"""

from __future__ import annotations

import json
from pathlib import Path

# Pinned paper-run release (issues #22 and #23).  Do not float this.
PAPER_RUN_VERSION = "0.2.0"
PAPER_RUN_INSTALL_URL = (
    f"https://raw.githubusercontent.com/a-green-hand-jack/paper-run/"
    f"v{PAPER_RUN_VERSION}/install.sh"
)
# Compatible OpenCode runtime verified against the pinned lockfile.
OPENCODE_VERSION = "1.18.25"
NODE_MAJOR = "20"
NVM_URL = "https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh"

# Paths inside the task environment (fixed by the environment template).
WORKSPACE = "/workspace"
MATERIALS_DIR = f"{WORKSPACE}/materials"
SUBMISSION_DIR = f"{WORKSPACE}/submission"
PROJECT_DIR = f"{WORKSPACE}/paper-run-project"
BRIEF_PATH = f"{WORKSPACE}/paper-run-brief.md"

# Exec budget for the single `paper-run start` invocation.  A full 13-stage
# autonomous paper-writing run can exceed two hours behind a slower gateway,
# so Harbor runs select this budget with ``--agent-timeout 14400``.
START_TIMEOUT_SEC = 14400
STAGE_TIMEOUT_MULTIPLIER = 2

# Required brief sections enforced by the harness validator
# (agent-writing-harness v0.3.0 .agents/tools/paper-brief.py).
REQUIRED_BRIEF_SECTIONS = (
    "Paper identity",
    "What readers should believe",
    "Operating mode",
    "Evidence and materials",
    "What must not change silently",
    "What may evolve",
    "Target and delivery",
    "Authors and identity",
    "Constraints",
    "First deliverable",
    "Template usage note",
)

# Publication artifacts produced under project/paper by the harness build.
PUBLICATION_PDFS = (
    "main.pdf",
    "main-anonymous.pdf",
    "main-camera-ready.pdf",
    "main-arxiv.pdf",
)


def _q(value: str) -> str:
    """Minimal POSIX single-quote shell escaping."""
    return "'" + value.replace("'", "'\\''") + "'"


def _nvm(cmd: str) -> str:
    """Wrap ``cmd`` so nvm is sourced first and the result status is propagated.

    ``{ export NVM_DIR=...; . ...; cmd; }`` — the group's exit status is the
    last command's, so failures propagate through ``set -e``/Harbor.
    """
    return (
        f'{{ export NVM_DIR="$HOME/.nvm"; . "$NVM_DIR/nvm.sh"; {cmd}; }}'
    )


# ---------------------------------------------------------------------------
# Brief construction
# ---------------------------------------------------------------------------


def _neutralize_embedded_instruction(instruction: str) -> str:
    """Adapt a benchmark instruction for the harness environment.

    - ``/workspace/materials`` absolute paths become in-repo ``materials/`` so
      the writer reads the staged copies (reading the repo-external path would
      hit OpenCode's ``external_directory`` permission, which defaults to ask
      and aborts headless runs).
    - The benchmark's output-location section (``/workspace/submission``) is
      replaced with harness semantics: the writer produces the canonical
      ``paper/`` tree, and the wrapper exports it to the submission contract
      afterwards.
    """
    text = instruction
    text = text.replace("/workspace/materials", "materials")
    lines = text.splitlines()
    out: list[str] = []
    in_submission = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## ") and "Submission contract" in stripped:
            in_submission = True
            out.append(line)
            out.append("")
            out.append("This Harbor task is run through the `paper-run` harness.")
            out.append("Produce the complete paper in the harness `paper/` tree and follow the")
            out.append("harness publication workflow; the harness exports it to the benchmark's")
            out.append("submission contract afterwards. The materials are in `materials/`.")
            continue
        if in_submission:
            if stripped.startswith("## ") and not stripped.startswith("## Submission"):
                in_submission = False
            else:
                continue
        out.append(line)
    text = "\n".join(out)
    # Indent every line so embedded ``## `` headings cannot be re-parsed by the
    # brief validator, while staying readable inside a code fence.
    return "\n".join(
        f"  {line}" if line.strip() else line
        for line in text.rstrip().splitlines()
    )


def build_brief(
    instruction: str,
    materials_dir: str = "materials",
    mode: str = "autonomous",
) -> str:
    """Render a valid harness brief from the Harbor task instruction.

    The instruction text is embedded verbatim under ``Constraints`` so the
    writer has the full task, while ``Evidence and materials`` points the
    writer at the public materials directory (already present in the
    container at an absolute path, so nothing needs copying into the repo).
    """
    if mode not in ("autonomous", "collaborative"):
        raise ValueError(f"unsupported operating mode: {mode!r}")
    lines = [
        "# Paper Brief",
        "",
        "## Paper identity",
        "",
        "- Working title: TODO (decide from the research overview)",
        "- Target venue: unresolved (verify current official rules before submission work)",
        "- Paper type: research paper",
        "- Intended readers: TODO (from the research overview)",
        "- One-sentence positioning: TODO (from the research overview)",
        "",
        "## What readers should believe",
        "",
        "### Central thesis",
        "",
        "TODO: state the single most important conclusion the paper wants readers to accept.",
        "",
        "### Contributions",
        "",
        "- TODO: one entry per defensible contribution (central / supporting / optional)",
        "",
        "## Operating mode",
        "",
        f"- Mode: {mode}",
        "- Approval boundary: the Agent drafts, self-reviews, polishes, and builds",
        "  checkpoints without step-by-step confirmation; it stops for Human review",
        "  before changing a locked item, approving a release, or final submission.",
        "",
        "## Evidence and materials",
        "",
        "The benchmark supplies the research materials on disk in the writing",
        "repository itself (staged from the benchmark environment):",
        "",
        f"- Materials directory: `{materials_dir}` (read the files there in full)",
        "- Follow the task instruction in the Constraints section below.",
        "",
        "## What must not change silently",
        "",
        "- TODO: locked claims, comparisons, limitations, or interface meaning",
        "",
        "## What may evolve",
        "",
        "- TODO: bounded areas where the Agent may work without re-asking",
        "",
        "## Target and delivery",
        "",
        "- Venue / year / track and deadline: unresolved",
        "- Publication variants needed: unresolved (default: draft, anonymous, camera-ready, arxiv)",
        "- Release authority: Human (approves each release instance and final submission)",
        "",
        "## Authors and identity",
        "",
        "- Author list: unresolved",
        "- Anonymity / disclosure constraints: unresolved",
        "",
        "## Constraints",
        "",
        "The benchmark task instruction is authoritative:",
        "",
        "```markdown",
        _neutralize_embedded_instruction(instruction),
        "```",
        "",
        "## Harness contract constraints (paper-run enforces these)",
        "",
        "- `PAPER.md` section `## What must not change silently` is a **locked",
        "  contract**: paper-run fails the run if its text changes. Do not modify",
        "  that section's heading or body at all.",
        "- `BRIEF.md` is the human's input contract; do not edit it.",
        "- If you believe something must be locked, record it under `PAPER.md",
        "  ## Unresolved` as a candidate instead of editing the locked section.",
        "- Do not modify `## Operating mode`'s `Mode:` value.",
        "- Do not run `git add`, `git commit`, `git push`, or repository release",
        "  scripts; the paper-run controller owns checkpoints and release records.",
        "- For the final candidate stage, inspect files with the read/list tools",
        "  and record the release record with the edit tool; do not invoke",
        "  arbitrary Python or shell one-liners.",
        "- Language and length limits: follow the task instruction",
        "- Compute / data limits: none",
        "- Style examples or Writing DNA corpus: none",
        "",
        "## First deliverable",
        "",
        "- Complete the full paper and place the final LaTeX source in the harness",
        "  `paper/` directory according to the harness publication workflow.",
        "",
        "## Template usage note",
        "",
        "Use the `agent-writing-harness` harness to write this paper. Draft under",
        "the declared operating mode, following AGENTS.md and the paper contracts.",
    ]
    return "\n".join(lines) + "\n"


def write_brief_command(brief_content: str, brief_path: str = BRIEF_PATH) -> str:
    """Write the generated brief into the container via a quoted heredoc."""
    marker = "PAPERRUN_BRIEF_EOF"
    parent = str(Path(brief_path).parent)
    return (
        f"mkdir -p {_q(parent)} && "
        f"cat > {_q(brief_path)} <<'{marker}'\n"
        f"{brief_content}"
        f"{marker}\n"
    )


# ---------------------------------------------------------------------------
# Installation commands
# ---------------------------------------------------------------------------


def node_install_commands() -> list[str]:
    """Install Node >= 20 via nvm (no sudo needed, user-local)."""
    return [
        (
            f'export NVM_DIR="$HOME/.nvm"; '
            f"curl -fsSL {NVM_URL} | bash && . \"$NVM_DIR/nvm.sh\" && "
            f"nvm install {NODE_MAJOR} && nvm alias default {NODE_MAJOR}"
        ),
    ]


def opencode_install_commands() -> list[str]:
    """Install the pinned OpenCode runtime through npm."""
    return [
        _nvm(f"npm install -g opencode-ai@{OPENCODE_VERSION} && opencode --version"),
    ]


def paper_run_install_commands() -> list[str]:
    """Install the pinned paper-run release with its official installer."""
    return [
        _nvm(
            f"curl -fsSL {_q(PAPER_RUN_INSTALL_URL)} | sh && "
            f"test \"$(paper-run --version)\" = {_q(PAPER_RUN_VERSION)}"
        ),
    ]


def version_check_command() -> str:
    """Print installed versions for the run record."""
    return (
        _nvm("node --version; opencode --version; paper-run --version")
    )


def opencode_user_config_command(base_url: str | None, model: str | None) -> str | None:
    """Write a user-level OpenCode config pointing provider openai at a gateway.

    Credentials are never written here; OpenCode reads ``OPENAI_API_KEY`` from
    the environment.  Only the provider base URL and an explicit model
    registration are declared, so a custom OpenAI-compatible endpoint (e.g. the
    Apex gateway) is reachable.

    Narrow bash permission rules are intentionally NOT set here: OpenCode
    merges config layers and "last matching rule wins", so the writing repo's
    project ``opencode.json`` (with its ``bash: {"*": "ask"}`` catch-all,
    installed after this layer) would override them. Project rules are patched
    into the initialized repository instead (see
    :func:`patch_opencode_project_command`) and committed with the materials
    checkpoint.
    """
    config: dict[str, object] = {}
    if model and "/" in model:
        provider, model_id = model.split("/", 1)
        provider_block: dict[str, object] = {"models": {model_id: {}}}
        if base_url:
            provider_block["options"] = {"baseURL": base_url}
        config["provider"] = {provider: provider_block}
    if not config:
        return None
    payload = json.dumps(config, indent=2)
    return (
        'mkdir -p "$HOME/.config/opencode" && '
        f"printf '%s\\n' {_q(payload)} > \"$HOME/.config/opencode/opencode.json\""
    )


# Narrow read-only bash rules the headless writer legitimately needs, layered
# into the project opencode.json so the run stays a single clean invocation.
# Everything else keeps the paper-run default ``"*": "ask"`` (fail-fast).
NARROW_BASH_ALLOW: dict[str, str] = {
    # Inspection / read-only (headless writers use these constantly).
    "pwd": "allow",
    "ls *": "allow",
    "find *": "allow",
    "cat *": "allow",
    "head *": "allow",
    "tail *": "allow",
    "wc *": "allow",
    "stat *": "allow",
    "file *": "allow",
    "which *": "allow",
    "echo *": "allow",
    "printf *": "allow",
    "env *": "allow",
    "grep *": "allow",
    "rg *": "allow",
    "sed *": "allow",
    "awk *": "allow",
    # Git inspection (read-only; no push/clone/remote mutation).
    "git status*": "allow",
    "git branch*": "allow",
    "git rev-parse*": "allow",
    "git remote -v": "allow",
    "git log*": "allow",
    "git show*": "allow",
    "git diff*": "allow",
    "git tag*": "allow",
    "git show-ref*": "allow",
    "git describe*": "allow",
    # Python for harness tooling and light file ops.
    "python3 *": "allow",
    "python3": "allow",
    "python *": "allow",
    "python": "allow",
    # Local file manipulation inside the isolated container.
    "mkdir *": "allow",
    "cp *": "allow",
    "mv *": "allow",
    "touch *": "allow",
    # Publication-variant build toolchain.
    "make *": "allow",
    "make": "allow",
    "pdflatex *": "allow",
    "pdflatex --version": "allow",
    "bibtex *": "allow",
    "bibtex --version": "allow",
    "latexmk *": "allow",
    "tectonic *": "allow",
    "pdfinfo *": "allow",
    "pdftotext * -": "allow",
    "python3 -m json.tool .paper-run/assessment.json": "allow",
    # Candidate/release inspection commands used around the final stage.
    "du *": "allow",
    "df *": "allow",
    "ls -la releases*": "allow",
    "ls -la releases/*": "allow",
}


def patch_opencode_project_command(project_dir: str = PROJECT_DIR) -> str:
    """Merge narrow bash allows into the initialized project config.

    The official release installer does not expose its package directory as a
    stable integration surface. Patching the generated config after
    ``paper-run init`` keeps the package immutable; the next manual checkpoint
    commits this change together with the public materials.
    """
    config_path = f"{project_dir}/opencode.json"
    script = (
        "import json, pathlib\n"
        f"p = pathlib.Path({json.dumps(config_path)})\n"
        "cfg = json.loads(p.read_text())\n"
        "bash = cfg.setdefault('permission', {}).setdefault('bash', {})\n"
        "bash.setdefault('*', 'ask')\n"
        + "".join(f"bash[{_q(k)}] = {_q(v)}\n" for k, v in NARROW_BASH_ALLOW.items())
        + "p.write_text(json.dumps(cfg, indent=2) + '\\n')\n"
    )
    marker = "PAPERRUN_PATCH_EOF"
    return f"python3 - <<'{marker}'\n{script}{marker}\n"


# ---------------------------------------------------------------------------
# Run commands
# ---------------------------------------------------------------------------


def init_command(
    brief_path: str = BRIEF_PATH,
    project_dir: str = PROJECT_DIR,
    mode: str = "autonomous",
    model: str | None = None,
) -> str:
    """Initialize a local writing repository (network template fetch)."""
    model_arg = f" --model {_q(model)}" if model else ""
    return _nvm(
        f"paper-run init {_q(project_dir)} "
        f"--brief {_q(brief_path)} --mode {mode} --local{model_arg}"
    )


def start_command(
    model: str | None,
    variant: str | None,
    project_dir: str = PROJECT_DIR,
    stage_timeout_multiplier: int = STAGE_TIMEOUT_MULTIPLIER,
) -> str:
    """Start the autonomous headless pipeline exactly once."""
    parts = ["paper-run", "start", "--headless", "--mode", "autonomous"]
    if model:
        parts += ["--model", _q(model)]
    if variant:
        parts += ["--variant", _q(variant)]
    parts += ["--stage-timeout-multiplier", str(stage_timeout_multiplier)]
    cmd = " ".join(parts)
    return f"cd {_q(project_dir)} && " + _nvm(cmd)


def status_command(project_dir: str = PROJECT_DIR) -> str:
    """Read pipeline status as JSON."""
    return f"cd {_q(project_dir)} && " + _nvm("paper-run status --json")


def stage_materials_command(
    materials_src: str = MATERIALS_DIR,
    project_dir: str = PROJECT_DIR,
) -> str:
    """Copy public benchmark materials into the writing repo and commit them.

    paper-run's material assessment only considers files inside the writing
    repo (``materials|evidence|data|figures`` directories plus the contracts),
    so materials must live at ``<project>/materials/`` for the verdict to be
    usable.  They are committed with a manual ``paper-run checkpoint`` so
    ``paper-run start``'s clean-tree/HEAD consistency checks pass and the run
    stays a single headless invocation.
    """
    return (
        f"mkdir -p {_q(f'{project_dir}/materials')} && "
        f"cp -r {_q(materials_src)}/. {_q(f'{project_dir}/materials')}/ && "
        f"cd {_q(project_dir)} && git add -A && "
        + _nvm("paper-run checkpoint")
    )


# ---------------------------------------------------------------------------
# Export commands
# ---------------------------------------------------------------------------


def export_commands(
    project_dir: str = PROJECT_DIR,
    submission_dir: str = SUBMISSION_DIR,
    logs_dir: str = "/logs/agent",
    materials_dir: str = MATERIALS_DIR,
) -> list[str]:
    """Copy the harness paper/ tree into the submission contract.

    ``main.tex`` is authoritative.  The whole ``paper/`` tree is copied so
    ``\\input``/``\\include`` dependencies, style files and figures resolve.
    PaperWrite-Bench supplies a read-only ``/workspace/materials/references.bib``;
    when it exists, preserve it as both bibliography names so paper-run's
    ``\\bibliography{refs}`` output and Harbor's ``references.bib`` contract
    resolve to the same file. PaperWritingBench has no root materials
    bibliography, so its literature-review output remains authoritative.
    """
    paper_dir = f"{project_dir}/paper"
    artifact_dir = f"{logs_dir}/paper-run"
    return [
        f"rm -rf {_q(submission_dir)} && mkdir -p {_q(submission_dir)}",
        (
            f"cp -r {_q(paper_dir)}/. {_q(submission_dir)}/ && "
            f"if [ -f {_q(f'{materials_dir}/references.bib')} ]; then "
            f"cp {_q(f'{materials_dir}/references.bib')} "
            f"{_q(submission_dir)}/references.bib && "
            f"cp {_q(f'{materials_dir}/references.bib')} "
            f"{_q(submission_dir)}/refs.bib; else "
            f"cp {_q(paper_dir)}/refs.bib {_q(submission_dir)}/references.bib; fi"
        ),
        (
            f"mkdir -p {_q(artifact_dir)} && "
            f"cp -r {_q(project_dir)}/.paper-run {_q(artifact_dir)}/ && "
            f"cp {_q(project_dir)}/.paper-run/run.log {_q(artifact_dir)}/run.log && "
            + " && ".join(
                f"cp {_q(paper_dir)}/{name} {_q(artifact_dir)}/ 2>/dev/null || true"
                for name in PUBLICATION_PDFS
            )
        ),
    ]


def submission_ready_command(
    submission_dir: str = SUBMISSION_DIR,
) -> str:
    """Fail loudly if the required submission files are missing."""
    return (
        f"test -f {_q(submission_dir)}/main.tex && "
        f"test -f {_q(submission_dir)}/references.bib && "
        f"grep -q '\\\\documentclass' {_q(submission_dir)}/main.tex"
    )
