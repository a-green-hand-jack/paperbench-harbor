# Submission Contract

Every benchmark task in this project, across all three protocols, grades the
same thing: a complete LaTeX source tree at a fixed location inside the task
container.

```text
/workspace/submission/
├── main.tex
├── references.bib
└── figures/ (optional)
```

`main.tex` must compile on its own from this directory. `references.bib` must
define every key cited by `main.tex`. Figures referenced by
`\includegraphics` must resolve inside the submission tree.

This contract is agent-neutral. Tasks and verifier templates make no
assumption about which agent produced the tree, what internal workspace it
used, or how it got there.

## What the verifier checks

The binary Harbor reward comes from three checks in `tests/test_state.py`:

1. **Structure** — `main.tex` and `references.bib` exist at the contract paths.
2. **Safe recompilation** — the submission is copied into a clean directory and
   rebuilt with `pdflatex -interaction=nonstopmode -halt-on-error
   -no-shell-escape`, `bibtex`, then two more `pdflatex` passes.
3. **Citation resolution** — every `\cite` key in `main.tex` is defined in
   `references.bib`.

Optional official evaluator metrics run separately and are diagnostic only.
They never change the binary reward.

## Writing an agent against it

Any Harbor agent works. The two Harbor-native agents (`codex`, `claude-code`)
need no adaptation — point them at a task and they write into
`/workspace/submission/` directly:

```bash
harbor run \
  --repo "https://huggingface.co/datasets/Jack-Jieke-Wu/Paper-Writing-Exam/tree/<revision>/paperwrite-bench-short" \
  --include-task-name pwb-0001 \
  --agent codex \
  --model <provider>/<model> \
  --yes --n-concurrent 1
```

An external writing harness that uses its own workspace layout needs a thin
Harbor agent wrapper that exports its output tree into the contract above.
That wrapper belongs to whoever runs the harness, not to this repository —
the benchmark ships no agent adapters, and running a published task never
requires installing this project.

If you write one, the things worth getting right are:

| Concern | What to do |
|---|---|
| Inputs | Read only `/workspace/materials/`. `solution/`, `tests/private/`, and evaluator metadata are verifier-only and must never be staged into the writer environment. |
| Credentials | Take them from the environment Harbor provides. Never write them into task files, Docker layers, command arguments, logs, or generated config. |
| Export | Emit the complete tree needed to compile `main.tex`, and fail loudly when a required file is missing rather than submitting a partial tree. |
| Artifacts | Keep agent logs and diagnostics under the trial artifact root, and never copy the task's private verifier files there. |

## Task layout

For reference, a published task directory looks like this:

```text
<task-id>/
├── task.toml
├── instruction.md
├── environment/     # writer-visible materials and the agent image
├── solution/        # oracle, verifier-only
└── tests/           # verifier, private material, evaluator
```

The writer sees only the public material allowlist. Ground-truth papers,
rubrics, citation labels, and evaluator metadata remain verifier-only.
