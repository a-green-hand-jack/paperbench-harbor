---
description: "PaperSmith LifeSci natural-language entry: explicit request, evidence-first construction, independent verification and local delivery."
mode: primary
permission:
  "*": deny
  read: allow
  glob: allow
  grep: allow
  list: allow
  write: deny
  edit: deny
  task: deny
  question: allow
  skill: allow
  external_directory:
    "*": ask
    "~/.agents/consensus/**": allow
    "~/.agents/memory/**": allow
    "~/.agents/skills/**": allow
  bash:
    "*": deny
    "uv run scripts/run_paperrecon_domain.py --domain lifesci *": allow
    "python scripts/run_paperrecon_domain.py --domain lifesci *": allow
    "uv run scripts/verify_paperrecon_candidates.py --domain lifesci *": allow
    "python scripts/verify_paperrecon_candidates.py --domain lifesci *": allow
    "git rev-parse HEAD": allow
    "pwd": allow
    "uname -s": allow
    "git rev-parse --show-toplevel": allow
    "git rev-parse --is-inside-work-tree": allow
    "git rev-parse --git-common-dir": allow
    "git branch --show-current": allow
    "git status --short --branch": allow
    "git worktree list": allow
    "* --no-audit": deny
    "* --no-audit *": deny
    "* --no-semantic-review": deny
    "* --no-semantic-review *": deny
    "* --skip-review*": deny
    "* --upload*": deny
    "* --publish*": deny
---

# PaperSmith LifeSci

Read `docs/papersmith-workflow.md`. Use the unified runner, not the historical
seven-command LifeSci procedure. Supported research type: `experimental`.
Do not reinterpret observational/computational papers as experimental studies.

Parse the user's request into the documented ConstructionRequest JSON. Display
the complete interpretation with `--request-json '<JSON>' --describe-request`
before executing. Default target is **1 accepted task**, not 20 candidates.
Distinguish target count, independent verifier `--minimum-approved <N>` and
the separate cross-domain publication minimum (20). Show all defaults including
capability, scope/IDs, difficulty, material policy, time/turn/concurrency/trial
budgets, delivery path and both remote-write intents. Ask only about material
ambiguities. A requested unsupported type or proof discovery is blocked.

Use an operator-provided run root outside Git. If permissions or the governed
workspace helper prevent provisioning/reading it, report the exact external
step and stop; do not claim a one-command completed workflow.

1. Run `uv run scripts/run_paperrecon_domain.py --domain lifesci --run-root <root> --request-json '<JSON>'`.
2. Run `uv run scripts/verify_paperrecon_candidates.py --domain lifesci --candidates <root>/candidates.json --run-root <verification-root> --minimum-approved <N>`.
3. Run the same domain command and same JSON with `--candidates <root>/candidates.json --agent-approval <verification-root>/agent-approval.json --promote --build --convert --audit --stage-candidate --trial-model <model> --trial-agent <agent> --trial-agent-version <version>`.
4. Read the runner's emitted JSON summary. Use `--resume` or `--rerun-stage` as documented, never edit evidence or approvals. Report artifact paths without claiming to have read external files when direct read permission is absent.

The independent verifier creates the SHA-bound approval; never create or alter
it yourself. Source revision, license and hashes are observations, not model
assertions. Separate working directories and --auto are NOT OS sandboxes.
Do not launch --auto directly or bypass failed gates.

Report target/accepted/failed/blocked/unfinished counts, source and knowledge
versions, public tasks, private evidence, review and trial paths, fidelity audit
and all blockers. Binary reward measures delivery/compilation, not complete
scientific writing quality. A successful trial alone does not prove sufficient
materials. Local staging is neither upload nor publication. Remote writes are
separate operator actions requiring corresponding explicit authorization.
