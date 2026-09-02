# Paper-Writing Agent Integrations

GitHub is the source of truth for the adapters that connect paper-writing
agents to this benchmark. Agent outputs and run histories belong in the
public trial dataset, not in this repository.

## Common contract

Every integration must document and test these fields:

| Field | Requirement |
|---|---|
| Registration | Harbor agent class and import path |
| Version | Immutable release, tag, or commit |
| Runtime | Required CLI, language runtime, and package versions |
| Inputs | Explicit list of writer-visible files and directories |
| Credentials | Environment variables passed by Harbor; never written to files |
| Model settings | Model, provider, variant, and non-secret configuration |
| Output | Mapping into `/workspace/submission/main.tex`, `references.bib`, and optional `figures/` |
| Artifacts | Agent logs, checkpoints, trajectory, publication files, and diagnostics |
| Failure behavior | Timeout, missing input, denied permission, and malformed output behavior |
| Verification | Unit/contract tests plus a bounded Harbor smoke run |

The benchmark submission contract is:

```text
/workspace/submission/
├── main.tex
├── references.bib
└── figures/ (optional)
```

An agent may use a different internal workspace, but the adapter must export
the complete LaTeX source tree needed to compile `main.tex` into this contract.
The adapter owns the export; benchmark tasks and verifier templates remain
agent-neutral.

## Supported integrations

| Agent | Adapter | Version policy | Status |
|---|---|---|---|
| Harbor Codex | Native Harbor agent | Harbor-managed | Supported baseline |
| Claude Code | Native Harbor agent | Harbor-managed | Supported baseline |
| `paper-run` | `paperbench_harbor.agents.paper_run:PaperRun` | Pinned release and runtime in `paper_run_core.py` | Experimental integration |

The `paper-run` adapter is the reference implementation for an external
paper-writing harness. It installs its pinned runtime inside the task
container, stages only public materials, executes the harness, exports the
paper tree, and copies run diagnostics to the agent artifact directory.

## Adding an agent

1. Add a thin wrapper under `src/paperbench_harbor/agents/`.
2. Pin every external release and runtime dependency in the wrapper or a
   companion core module.
3. Pass credentials through Harbor's agent environment only. Do not put keys
   in task files, Docker layers, command arguments, logs, or generated config.
4. Make the writer-visible input allowlist explicit. The agent must not read
   `solution/`, `tests/private/`, evaluator metadata, or host paths.
5. Export a complete submission and fail if required files are missing.
6. Preserve useful agent artifacts below the trial artifact root without
   copying the task's private verifier files.
7. Add tests for command construction, version pinning, output mapping,
   permission behavior, and secret non-persistence.
8. Run a bounded Harbor smoke test and record the task revision, repository
   commit, model settings, and artifact paths.

Agent adapters should not vendor a complete external repository into this
project unless the benchmark verifier or task environment genuinely requires
it. Prefer a version-pinned installer or package and keep any required
third-party provenance in `src/paperbench_harbor/vendor/NOTICE.md`.

## Trial records

Each completed Harbor trial may be exported by the opt-in
`paperbench-trial-export` Harbor JobPlugin, which calls the same exporter
implementation as `scripts/export_trial.py`. The plugin publishes only final
retry results and can target a user-selected dataset repository. A trial record
references the public benchmark by immutable Hugging Face revision and task
checksum; it does not duplicate the benchmark task tree.

The exporter accepts only known Harbor result and artifact locations and
rejects API keys, bearer tokens, credential files, host credentials, and
verifier-private task material. Review the generated manifest before uploading
it to Hugging Face.

## Reproducibility record

Reports and pull requests that add or update an agent must include:

- the GitHub integration commit;
- the public benchmark Hugging Face repository and immutable revision;
- task ID and task checksum;
- agent release and runtime versions;
- model/provider and non-secret settings;
- Harbor command or config shape;
- Harbor reward and official evaluator output status;
- public trial dataset artifact ID after upload.
