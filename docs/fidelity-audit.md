# Fidelity audit: Harbor conversion vs. upstream benchmarks

This document records how the generated Harbor tasks were checked against the
upstream PaperWrite-Bench (PaperRecon) and PaperWritingBench
(PaperOrchestra) writing pipelines, and which differences are intentional
adaptations.

Verified against upstream revisions:

- `Agent4Science-UTokyo/PaperRecon` @ `main` (PaperWrite-Bench)
- `google-research/paper-orchestra` @ `ca1b3fa01c2970fc7cda32d16245db38d57b3f56`
  (PaperWritingBench)

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
| `AGENTS_<type>.md` | embedded in `instruction.md` + `materials/AGENTS.md` | identical text |

The one-shot writing prompt is reproduced in `instruction.md` (overview and
figure/table descriptions are referenced by file path instead of being
inlined; the information content is identical). `num_page` and
`column_type` (`single-column` / `double-column`) are rendered exactly as
upstream does.

### Intentional adaptations (not part of the writer input)

- Output contract: upstream agents edit `template.tex`; Harbor requires the
  submission contract `main.tex` + `references.bib` + `figures/` +
  `final.pdf`. Inputs are unchanged; only the output path is fixed.
- Network policy: Harbor tasks run with `allow_internet=false`. Upstream does
  not sandbox the writer's network. Materials are self-contained (all
  citations come from `references.bib`), but this is a deliberate hardening
  that must be accounted for in parity experiments.
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

- No scholarly-search interface yet: upstream's literature agent performs a
  web search with a research cutoff. The controlled-search sidecar is planned
  (implementation step 6); until then tasks run without network and the
  writer must construct the bibliography from the materials alone. This is a
  known protocol gap, documented in `docs/implementation-plan.md`.
- Pipeline shape: upstream is multi-agent (outline -> literature -> sections
  -> refinement). Harbor measures a single writing agent end-to-end; the
  benchmark's evaluation target is the produced paper, not the pipeline.

## Evaluation layer (both benchmarks)

The Harbor verifier is currently smoke-level: submission contract, restricted
recompilation (`-no-shell-escape`, no network), and a deterministic
citation-vs-bibliography check. The upstream scoring (per-section rubric vs
`eval_points.json`, hallucination analysis, citation F1 for PaperWrite-Bench;
rubric + P0/P1 citation verification + side-by-side comparison for
PaperWritingBench) is NOT yet integrated. Harbor scores are therefore not yet
comparable with published upstream numbers; parity experiments remain
(implementation step 8).

## Validation evidence

- 251/251 Harbor tasks: oracle reward 1.0, NOP reward 0.0 (harbor 0.20.0,
  Docker, dataset-level runs).
- Real-agent end-to-end runs (claude-code, claude-sonnet-5 via the Apex
  gateway): `pwb-0001` reward 1.0 (14-page paper), `pwbw-0001` reward 1.0
  (8-page CVPR paper).
