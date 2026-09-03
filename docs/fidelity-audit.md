# Fidelity audit: Harbor conversion vs. upstream benchmarks

> **Maintenance note:** this document explains the audit contract. Any specific
> task count, revision, or audit total below is dated evidence, not a mutable
> release claim. Consult the [task dataset card](https://huggingface.co/datasets/Jack-Jieke-Wu/Paper-Writing-Exam)
> and its immutable revision for the current release.

This document records how the generated Harbor tasks were checked against the
upstream PaperWrite-Bench (PaperRecon) and PaperWritingBench
(PaperOrchestra) writing pipelines, which official evaluators are implemented,
and which differences remain intentional adaptations or parity gaps.

Verified against upstream revisions:

- `Agent4Science-UTokyo/PaperRecon` @ `main` (PaperWrite-Bench)
- `google-research/paper-orchestra` @ `ca1b3fa01c2970fc7cda32d16245db38d57b3f56`
  (PaperWritingBench)

## Reproducible task-fidelity audit

Since Issue #4, the per-task and dataset-level fidelity claims are produced by
an automated audit instead of manual inspection. The audit verifies, against a
fixed upstream source tree and revision, that every generated task preserves
upstream writer-visible content (SHA-256), keeps verifier-only material
byte-identical and out of the writer environment, respects the task contract,
and that repeated conversion of the same fixed input is deterministic.

```bash
uv run scripts/audit_fidelity.py paperwrite-bench \
    --source /path/to/PaperWrite-Bench \
    --dataset /path/to/paperwrite-bench-short \
    --upstream-revision <rev> \
    --overview short \
    --output reports/pwb
uv run scripts/audit_fidelity.py paperwritingbench \
    --source /path/to/PaperWritingBench \
    --dataset /path/to/paperwritingbench-sparse-plotoff \
    --upstream-revision <rev> \
    --protocol sparse-plotoff \
    --output reports/pwbw
```

The converter runs the per-task half of this audit itself. Every
`paperbench-harbor` conversion command audits the tree it just produced and
exits non-zero if it does not pass, so a conversion that silently drops or
rewrites upstream content can no longer look like a successful one. Pass
`--no-audit` to skip it.

The standalone command above remains the way to get written reports and the
dataset-level determinism check. Determinism is deliberately not part of the
conversion command: it is a property of the converter rather than of any task,
and establishing it costs two further full conversions.

The audit writes one `<task-id>.json` report per task, `summary.json`, and
`review-logs/` below the requested output directory. The latter is isolated per
audit run, so concurrent audits cannot overwrite each other's reviewer
evidence. The summary records overall totals, determinism, semantic-review
outcomes, and a version-pinned evidence block: upstream revision/tree digest,
dataset tree digest, converter revision, and reviewer selection. Retain that
generated report directory with the released dataset version; it is the audit
evidence, rather than a copied table of counts in this document.

Source-to-Harbor layout lives in each benchmark's
`src/paperbench_harbor/adapters/*/spec.py` and drives production staging. The
audit does not trust that declaration on its own: it independently recovers
writer origins from actual SHA-256 bytes, then compares the recovered evidence
to the spec. Every unexplained writer file, altered undeclared copy, private
content leak, or semantic-review rejection fails the audit.

The converter CLI now requires a non-empty `--upstream-revision`, which is
recorded both in each task's `source_manifest.json` and in the dataset-level
`dataset-manifest.jsonl`. Per-task `source_manifest.json` file hashes are keyed
by task-relative paths so the manifest is deterministic and portable across
machines.

## PaperWrite-Bench (short)

### Writer-visible input surface

Upstream (`perform_writeup_with_agent`) copies `resources/` into the agent's
working directory, excluding `eval_points*`, `research_overview_*`,
`overview_sufficiency_evaluation*`, `reproduction_judgment_*`, and `AGENTS_*`,
then adds:

- `research_overview_<type>.md` renamed to `research_overview.md` (short here)
- `CLAUDE.md` / `AGENTS.md` with the per-paper-type benchmark instructions
  (`AGENTS_<method|benchmark|both>.md`)
- `references.bib` (verbatim from resources)

Harbor task `environment/materials/` mirrors this exactly:

| Upstream | Harbor | Status |
| --- | --- | --- |
| `research_overview_short.md` -> `research_overview.md` | `materials/research_overview.md` | identical bytes |
| `template.tex`, `references.bib` | `materials/*` | identical bytes |
| `figure_summary.txt`, `table_summary.txt` | `materials/*` | identical bytes |
| `figures/`, `tables/`, `code/` | `materials/*` | identical bytes |
| `eval_points.json` (excluded upstream) | verifier-only (`tests/private/`) | matches |
| non-selected overview (excluded upstream) | verifier-only (`tests/private/`) | matches |
| `AGENTS_<type>.md` | embedded in `instruction.md` + `materials/AGENTS.md` | preserves the upstream instructions; an existing `Acknowledgements` heading may be retained but must receive no new content |

The one-shot writing prompt is reproduced in `instruction.md` (overview and
figure/table descriptions are referenced by file path instead of being
inlined; the information content is identical). `num_page` and
`column_type` (`single-column` / `double-column`) are rendered exactly as
upstream does.

### Intentional adaptations (not part of the writer input)

- Output contract: upstream agents edit `template.tex`; Harbor requires the
  submission contract `main.tex` + `references.bib` + optional `figures/`.
  Inputs are unchanged; only the output path is fixed.
- Network policy: Harbor tasks currently declare
  `[environment] network_mode = "public"`, like the upstream writer-facing
  surface. The verifier declares no phase policy of its own and therefore
  inherits that baseline; it is **not** network-isolated by Harbor. What
  isolates the recompilation is the compile itself -- a clean copy, no ground
  truth, no judge credentials, and `-no-shell-escape`. The verifier phase is
  left inheritable on purpose: the optional official metrics call an
  operator-supplied judge endpoint, and an explicit `[verifier] network_mode`
  could not be loosened at run time by `--allow-environment-host`. The repository provides a controlled,
  cutoff-aware scholarly-search sidecar, but populating and operating its
  versioned index is still a deployment concern; open-internet retrieval is
  therefore not automatically reproducible in every run.
- Harness post-processing (reflection loop, page-limit adjustment, chktex,
  "AI-Generated" watermark) is not part of the Harbor task; the agent has the
  full agent timeout to do equivalent self-correction.

## PaperWritingBench (sparse-plotoff)

### Writer-visible input surface

Upstream (`paper_writer.py` with `--use_plotting` off) provides the agent
pipeline with:

- `idea_sparse.md` (sparse protocol), `experimental_log.md`
- `figures/` including `info.json` (copied into the writeup directory)
- the conference LaTeX template directory (`template.tex`, `guidelines.md`,
  style and bibliography files, starter `references.bib`)

Harbor task `environment/materials/` mirrors this exactly:
`idea_sparse.md`, `experimental_log.md`, `figures/` (+ `info.json`),
`conference_template/` (verbatim copy of the bundled official template).

### Intentional adaptations

- Controlled scholarly-search sidecar: the repository now provides a
  dependency-free HTTP sidecar over a versioned JSONL index. It enforces the
  publication cutoff before deterministic ranking. Tasks retain internet access
  for compatibility, while a benchmark run can provide the sidecar endpoint
  and fixed index explicitly. Populating and operating that index is still a
  deployment concern, not part of conversion.
- Pipeline shape: upstream is multi-agent (outline -> literature -> sections
  -> refinement). Harbor measures a single writing agent end-to-end; the
  benchmark's evaluation target is the produced paper, not the pipeline.

## Evaluation layer (both benchmarks)

The verifier performs the Harbor smoke checks (submission contract, restricted
recompilation with `-no-shell-escape` and no network, and citation-vs-
bibliography validation) and invokes official evaluator code as a separate,
non-blocking metrics step. Results are written to
`/logs/verifier/evaluation.json`; they never determine the binary Harbor
reward.

### PaperWrite-Bench / PaperRecon

- Deterministic citation F1 always runs.
- With `JUDGE_API_KEY`, the vendored per-section rubric evaluator runs against
  `eval_points.json`, including figure/table coverage and context scoring.
- The upstream agentic hallucination-verification pass is not available in the
  verifier image because its coding-agent CLI is not bundled.

### PaperWritingBench / PaperOrchestra

- With `JUDGE_API_KEY`, the vendored AgentReview ensemble and
  literature-review quality autoraters run against the recompiled submission
  PDF.
- Citation F1 runs at stage 1: reference extraction and title matching. The
  upstream arXiv-ID fetch and P0/P1 classification stages are not run inside
  the verifier.
- Without `JUDGE_API_KEY`, the LLM autoraters are skipped and the evaluator
  records that status instead of blocking the Harbor reward.

The evaluator wiring is implemented, but upstream-versus-Harbor parity
experiments have not yet been run. Harbor evaluator outputs therefore must not
be presented as comparable with published upstream numbers; parity remains an
open validation step.

## Validation evidence

- 251/251 Harbor tasks: oracle reward 1.0, NOP reward 0.0 (harbor 0.20.0,
  Docker, dataset-level runs).
- Real-agent end-to-end runs (claude-code, claude-sonnet-5 via the Apex
  gateway): `pwb-0001` reward 1.0 (14-page paper), `pwbw-0001` reward 1.0
  (8-page CVPR paper).
- Bounded Codex API-key run: five `paperwrite-bench-short` tasks and five
  `paperwritingbench-sparse-plotoff` tasks completed in parallel; all 10
  received Harbor reward 1.0 with no trial errors. Nine official evaluator
  artifacts were written. The remaining PaperWritingBench evaluator call
  received empty judge responses during citation title extraction and failed
  before writing `evaluation.json`; this did not affect binary reward.
- Bounded judge-backed `pwbw-0001` run with three ensemble reviews: reward 1.0,
  citation F1 `0.8831`, literature-review score `16`; the evaluator wrote
  `/logs/verifier/evaluation.json` and no credential value appeared in logs or
  artifacts.

These results validate task conversion and Harbor's binary verifier contract.
They do not constitute upstream evaluator parity results or numeric evidence
that the official judge-backed metrics match upstream runs.

### Task-fidelity audit evidence

Do not copy task counts or pass/fail claims here. Each fixed dataset revision
must retain the actual `summary.json` and per-task reports produced by the
command above. Those artifacts include the input revision and hashes needed to
establish what was audited, and they make the report independently inspectable
without treating prose as an authority.
