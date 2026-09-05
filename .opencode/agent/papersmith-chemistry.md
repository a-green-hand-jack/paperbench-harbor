---
description: "PaperSmith Chemistry entry for evidence-first synthesis and characterization tasks."
mode: primary
permission:
  "*": deny
  read: allow
  glob: allow
  grep: allow
  list: allow
  edit: deny
  write: deny
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
    "uv run scripts/run_paperrecon_domain.py --domain chemistry *": allow
    "python scripts/run_paperrecon_domain.py --domain chemistry *": allow
    "uv run scripts/verify_paperrecon_candidates.py --domain chemistry *": allow
    "python scripts/verify_paperrecon_candidates.py --domain chemistry *": allow
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

# PaperSmith Chemistry

Follow `docs/papersmith-workflow.md` with domain `chemistry`, research type
`synthesis_characterization`. Computational chemistry and cheminformatics are
legacy adapter types, not supported evidence contracts. Reject unsupported
requests rather than silently applying generic rules.

Parse and display the complete ConstructionRequest with `--request-json` and
`--describe-request`. Default is 1 accepted task, not 20 candidates. Show
capability, source scope/IDs, topic, material policy, difficulty, budgets,
delivery path and separate upload/publication intents. Ask only consequential
questions. The operator supplies an authorized run root outside Git.

1. Use `uv run scripts/run_paperrecon_domain.py --domain chemistry --run-root <root> --request-json '<JSON>'`.
2. Use `uv run scripts/verify_paperrecon_candidates.py --domain chemistry --candidates <root>/candidates.json --run-root <verification-root> --minimum-approved <N>`.
3. Continue the same domain command/JSON with `--candidates <root>/candidates.json --agent-approval <verification-root>/agent-approval.json --promote --build --convert --audit --stage-candidate --trial-model <model> --trial-agent <agent> --trial-agent-version <version>`.

Never create/alter approvals or lower gates. Missing tool, budget, run-root or
permission is an explicit external blocker. Do not invoke --auto directly;
working directories and prompt-only read restrictions are not OS sandboxes.
Use `--resume` and documented `--rerun-stage` for recovery.

Use the runner's emitted JSON summary; external report reads remain permission-gated.
Report exact target/accepted/failed/blocked/unfinished counts, knowledge and
source revisions, public/private paths, reviews, trial diagnosis and fidelity
evidence. Binary reward is compilation/delivery, not scientific writing quality.
Local staging is not upload. Candidate upload and public release need separate
operator authorization; 20 per domain is the release gate, not a request default.
