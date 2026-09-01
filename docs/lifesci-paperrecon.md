# LifeSci-PaperRecon: status and verification architecture

This document consolidates the current state of the project's third Harbor
benchmark — **LifeSci-PaperRecon**, a from-scratch, non-ML/AI (biology /
life-sciences) paper-writing benchmark — and clarifies a distinction that is
easy to blur when talking about "the scorer": Harbor's task-level pass/fail
is not the same thing as the LLM judge that evaluates a paper-writing agent's
performance. Tracks [issue #2](https://github.com/a-green-hand-jack/paperbench-harbor/issues/2).

## Two-layer verification: task correctness vs. agent performance

These are two different mechanisms answering two different questions, and
the project keeps them structurally separate.

### Layer 1 — Harbor task-level pass/fail (binary reward)

**Question it answers: "Is this task well-posed, and did the submission meet
the minimal technical contract?"** It does not ask "is this a good paper?"

Mechanism (deterministic, no LLM): the submission contract is present
(`main.tex`, `references.bib`), `main.tex` recompiles standalone in an
isolated sandbox (`-no-shell-escape`, no network), and every `\cite{}` key
used resolves to an entry in `references.bib`.

Two uses of the same mechanism:

- **At dataset-construction/QA time**: run the **oracle** (copies the
  ground-truth paper into `/workspace/submission/`) — must score reward
  `1.0`. Run a **NOP agent** (does nothing) — must score reward `0.0`. This
  is how the project confirms every generated task is actually solvable and
  not accidentally broken (bad citation graph, a template that fails to
  compile, a contract mismatch). `docs/fidelity-audit.md`'s "251/251 Harbor
  tasks: oracle reward 1.0, NOP reward 0.0" is task-design validation
  evidence — it says nothing about how well any real agent writes.
- **At real-agent-run time**: the same checks gate whatever the agent
  actually submits. An agent can produce a technically valid but
  scientifically empty or bad paper and still get reward `1.0` — this layer
  only certifies "minimally valid, compilable, non-fabricated citations,"
  not writing quality.

### Layer 2 — LLM judge verifier (official benchmark metrics)

**Question it answers: "How good is this agent's paper?"** This is the
actual performance-evaluation signal — the benchmark's real headline metric,
analogous to what the upstream PaperWrite-Bench / PaperWritingBench papers
report as their results.

Mechanism: optional, gated by `JUDGE_API_KEY`, runs *after* the binary reward
is already decided, writes to `/logs/verifier/evaluation.json`, and **never
affects the binary reward**. Currently implemented for the two existing
ML/AI benchmarks only, as vendored unmodified upstream code
(`vendor/NOTICE.md`):

**PaperWrite-Bench** (`grader_pwb.py.j2` → `vendor/paper_recon/evaluation/`):

| Sub-metric | Needs ground truth? | What it actually receives |
|---|---|---|
| Citation F1 (deterministic, no LLM) | Yes | Compares `\cite{}` key sets between GT `main.tex` and Pred `main.tex` directly |
| Rubric score (LLM judge) | Indirectly | Scores Pred section text against `eval_points.json` — a rubric *pre-extracted from GT at construction time* (by LLM + human review), not the raw GT text at judge time |
| Figure/table match (LLM judge) | Yes | Compares GT vs Pred figure/table captions side-by-side |
| Hallucination claim detection (LLM judge) | Yes, feeds full GT text into the prompt | Implemented upstream but **not currently wired into the Harbor verifier image** (needs a coding-agent CLI the verifier doesn't bundle) |

**PaperWritingBench** (`grader_pwbw.py.j2` → `vendor/paper_orchestra/autoraters/`):

| Sub-metric | Needs ground truth? | What it actually receives |
|---|---|---|
| AgentReview (LLM, 3-way ensemble + meta-review) | **No** | Reads *only* the submitted paper text; acts as an independent peer reviewer, scores Originality/Quality/Clarity/Soundness/Overall etc. in absolute terms — never sees the GT paper |
| Literature-review quality (LLM) | **No** | Reads *only* the submitted PDF plus a fixed "average citation count" baseline number; scores clarity/depth/connectivity/presentation 0–100 |
| Citation F1 (LLM-assisted extraction) | Yes | Extracts and title-matches references from *both* the GT PDF and the generated PDF |

The practical takeaway: some sub-metrics compare the submission against the
ground truth (directly, or via a rubric distilled from it beforehand);
others are absolute quality judgments that never see the ground truth at
all, functioning like a standalone peer reviewer.

## LifeSci-PaperRecon: current status (2026-09-01)

### What it is

A from-scratch, self-built, non-ML/AI paper-writing benchmark in the biology
/ life-sciences domain, cloning PaperWrite-Bench's simpler single-overview
reconstruction recipe (not PaperWritingBench's multi-agent one). Full design
rationale and phased plan: `/Users/jieke/.claude/plans/github-issue-2-reactive-hearth.md`.
Survey of why no existing public benchmark qualified: `docs/non-ml-benchmark-survey.md`.

### Why it exists

Issue #2 asked for non-ML/AI coverage. The two existing benchmarks
(PaperWrite-Bench, PaperWritingBench) are both ML/AI-only. A survey of 12+
candidate public benchmarks (SurveyEval, MLR-Bench, SurveyGen, SurveyLens,
HiSciBench, Denario, data-to-paper, Prompt-to-Paper, FinRpt, SurGE, and
others) found none that cleanly satisfied all scope criteria (fixed public
dataset, pure writing agent, pre-supplied materials, full-fidelity
wrappability) in a non-ML/AI domain — SurveyGen's Task 3 protocol came
closest but needs further corpus-scale verification. Per the issue's own
fallback plan, the project is building its own.

### Key decisions locked so far

1. **Domain**: biology / life sciences.
2. **Recipe**: PaperWrite-Bench-style (single overview + verbatim
   references.bib + optional code + section-skeleton template), reusing the
   existing domain-agnostic `paperwrite_bench/converter.py` rather than
   writing a parallel Harbor-format converter.
3. **Source pool**: arXiv `q-bio.*` categories (LaTeX source required,
   2025+, redistribution-permissive license — CC-BY/CC-BY-NC/CC-BY-SA/CC0,
   public code required).
4. **Scale**: 3-paper pilot first, then ~30–50 for the full dataset.
5. **Construction LLM**: `gpt-5.6-terra` via the existing Apex
   OpenAI-compatible gateway (`.env`).
6. **Hugging Face target**: merge into the existing
   `Jack-Jieke-Wu/Paper-Writing-Exam` repo as a new config/subset (not a
   separate repo).
7. **Pilot papers** (mixed type, deliberately not all the same shape):
   - BEAGLE 4.1 — arXiv 2606.27607v1, q-bio.PE, `computational` (tool/library paper)
   - Cell differentiation underpins reproducible morphogenesis — arXiv 2503.19375v2, q-bio.CB, `computational` (hypothesis-driven simulation study)
   - Drug release prediction (explainable ML) — arXiv 2601.02265v1, q-bio.BM, `experimental` (ML + chemistry empirical study)

### Naming

The benchmark's project brand name is **LifeSci-PaperRecon** — see
`docs/naming-convention.md` for the full brand-name ↔ upstream-name mapping
across all three benchmark families (the two existing ones are now branded
**AI-PaperRecon** = PaperWrite-Bench, and **AI-PaperOrchestra** =
PaperWritingBench; upstream code identifiers for those two are unchanged).
LifeSci-PaperRecon has no upstream name to preserve since it's
project-original. Dataset directory:
`datasets/lifesci-paperrecon-short/`. Task IDs: `lspr-0001`, `lspr-0002`,
`lspr-0003` for the pilot. Benchmark identifier recorded in
`source_manifest.json` / `task.toml`: `"LifeSci-PaperRecon"`.

### Phase status

- **Phase 0 (source discovery)**: done. 27 fully-qualifying candidates found
  across q-bio.BM/QM/GN/MN/CB/PE/NC/TO (q-bio.SC was a dead end — no
  code-linked papers found). Hardest filter in practice was license
  (arXiv-perpetual-only and CC-BY-NC-SA/ND combinations are common and
  disqualifying), not code availability.
- **Phase 1 (construction pipeline)**: built and run. The pipeline is
  **agent-driven, not a fixed script** — per paper, an `opencode` CLI session
  does the fetching, LaTeX surgery, bibliography conversion, figure captioning
  and overview authoring, and a deterministic gate in plain code decides
  whether the result is admitted. Full recipe, rationale and how to re-run:
  `docs/lifesci-paperrecon-construction.md`. **All 3 pilot papers built,
  validated, wrapped and smoke-checked** — see "Phase 1 pilot results" below.
  The pipeline has since been split into a domain-agnostic core
  (`construction/core/`) plus a `LIFESCI_PLUGIN`, with zero behaviour change
  for biology and no second domain yet: `docs/papersmith-architecture.md`.
- **Phase 2 (Harbor wrap, converter parameterization)**: done.
  `paperwrite_bench/converter.py`'s previously-hardcoded benchmark
  name/tags/category/agents-md/grader settings are now parameters, with
  defaults that reproduce PaperWrite-Bench byte-for-byte;
  `adapters/lifesci_paperrecon/harbor.py` supplies the biology values and
  `paperbench-harbor lifesci-paperrecon` drives it. No second Harbor converter
  exists. `tests/test_lifesci_paperrecon_converter.py` pins both the biology
  output and the unchanged PaperWrite-Bench defaults.
- **Phase 3 (LLM judge verifier / official benchmark metrics)**:
  **explicitly deferred, and NOT going to be built from scratch.** Per
  2026-08-30 decision, the plan to hand-build a bespoke
  rubric/`eval_points.json`-extraction pipeline (mirroring PaperWrite-Bench)
  or an AgentReview-style standalone reviewer (mirroring PaperWritingBench)
  is dropped. Instead, an **already-tuned external paper-review agent will
  be integrated later** as LifeSci-PaperRecon's Layer-2 judge, once
  available. Until then, LifeSci-PaperRecon tasks carry **Layer 1 (binary
  smoke check) only** — same as the existing benchmarks' minimum bar, just
  without an official-metrics companion yet. Whatever integration point is
  built later should follow the `grader_pwb.py.j2`/`grader_pwbw.py.j2`
  pattern (`/logs/verifier/evaluation.json`, `JUDGE_API_KEY`-gated,
  non-blocking to the binary reward) for consistency with the rest of the
  project, but the actual judge model/prompts are out of this project's
  hands to design — they'll arrive as a black-box "paper review agent" to
  wire in.
- **Phase 4 (scale to ~30–50)**: **partially complete (22/30–50 target).**
  35 new candidates were screened, promoted, and fed through the full
  PaperSmith pipeline (screen → construct → review). Of 38 total approved
  papers (3 pilots + 35 scale-up), 22 are now in the corpus. 11 were blocked
  by category mismatches (10 primary-outside-`q-bio.*` plus 1 q-bio
  subcategory mismatch; this is a **still-open scope question** — the
  coordinator must decide which cross-listed/non-q-bio-primary papers to
  accept or decline, and that decision has not been made). 5
  genuinely failed after exhausting retries (unrelated to the two generic bugs
  fixed in this phase). See “Phase 4 execution results” below. The
  one-command entry point that drives screen → verify → promote → build →
  wrap → audit from a single free-form request is
  `.opencode/agent/papersmith-lifesci.md`; both of its steps are now wired
  end-to-end (unit-verified; the live end-to-end smoke test is still a
  separate open item) — see `docs/papersmith-architecture.md`
  ("One-command entry point").
- **Phase 5 (Hugging Face publish)**: complete. The 22-task
  `lifesci-paperrecon-short` configuration was added to
  `Jack-Jieke-Wu/Paper-Writing-Exam` at tag `v0.3.1` and immutable revision
  `bfe2471c41f416d877e74bfa73cf0f29165c7567`. The existing `v0.3.0` release was
  preserved rather than retagged. A full download of the tagged LifeSci tree
  matched the local release tree for all 7,169 files by SHA-256; `lspr-0001`
  produced oracle reward 1.0 and NOP reward 0.0 from the tagged download. The
  repository verification suite passed with `193 passed`, and `ruff check .`
  passed with no findings. A real-agent Harbor 0.20.0 run then exercised
  `lspr-0001` and `lspr-0002` from the byte-matched release tree using Codex
  0.151.0, `openai/gpt-5.6-terra`, and Harbor agent kwarg
  `reasoning_effort=medium`, which invoked Codex with
  `-c model_reasoning_effort=medium`. Both trials completed without exceptions
  and earned reward 1.0. For each generated submission, the independent
  verifier passed all three checks: submission structure, recompilation
  without shell escape, and citation definitions.

### Open follow-ups

- **Cross-listed-paper scope decision (Phase 4, explicitly pending human
  decision).** 11 of the 35 scale-up candidates were blocked by the
  provenance-mismatch check: 10 have a primary arXiv category outside
  `q-bio.*` (`cs.LG` × 7 — papers 5, 9, 12, 14, 22, 27, 36 — plus `cs.CE`
  (16), `cs.CV` (37), `stat.ME` (25)), and 1 (`paper_4`) is a
  q-bio-subcategory mismatch (`q-bio.QM` primary where `q-bio.BM` was
  originally recorded). They carry q-bio cross-lists and are legitimate
  life-sciences work, but the decision of which cross-listed /
  non-q-bio-primary papers to accept versus decline is a **human scope
  decision that has not been made**, and `papers.py` has been left recording
  the true primary categories pending it. Note the pipeline itself already
  handles cross-listed papers correctly when the category is recorded
  accurately: three non-q-bio-primary papers built successfully
  (`paper_21` `stat.AP`, `paper_26` `cs.AI`, `paper_38` `stat.ME`).
- When the external paper-review agent is ready, define its exact input
  contract against this document’s Layer 2 table (does it need the raw GT
  paper directly, a pre-extracted rubric, or nothing at all — this
  determines what verifier-only material needs to be prepared and
  byte-preserved for it ahead of time).


## Phase 1 pilot results (2026-08-31)

### All three tasks built end-to-end

`lspr-0001`, `lspr-0002` and `lspr-0003` were constructed, validated, wrapped
and smoke-checked: **oracle reward 1.0 and NOP reward 0.0 for all three**
(harbor 0.20.0), fidelity/leakage audit `3/3 passed, determinism_ok: true`, 73
unit tests passing.

| Task | Paper | arXiv | Type | Paper license | Code repo license |
|---|---|---|---|---|---|
| `lspr-0001` | BEAGLE 4.1 | 2606.27607v1 | computational | CC BY 4.0 | MIT |
| `lspr-0002` | Cell differentiation / morphogenesis | 2503.19375v2 | computational | CC BY 4.0 | none declared |
| `lspr-0003` | Drug release prediction | 2601.02265v1 | experimental | CC BY-SA 4.0 | none declared |

The agent-driven design proved itself on real pathologies no rule in this
repository anticipates: it removed BEAGLE 4.1's `standalone` build
configuration (which needs `-shell-escape`, forbidden by Harbor), caught a
`daub2015cell`/`daub2014cell` citation-key mismatch in paper 2, and resolved a
natbib/`elsarticle-num` mode conflict in paper 3. Details and the two prompt
bugs the pilot exposed: `docs/lifesci-paperrecon-construction.md`.

### Code-repository licensing: policy changed mid-pilot

Papers 2 and 3 initially stopped at the construction agent's code-repository
license stop-condition. Independently re-verified against the GitHub API:

| Pilot paper | Paper license (arXiv) | Code repo | Repo license |
|---|---|---|---|
| 1. BEAGLE 4.1 | CC BY 4.0 ✅ | `beagle-dev/beagle-lib` | MIT |
| 2. Cell differentiation / morphogenesis | CC BY 4.0 ✅ | `DominicDevlin/Stem-cell-...-morphogenesis` | none declared |
| 3. Drug release prediction | CC BY-SA 4.0 ✅ | `mdsamad001/Drug_Release_Dynamics_Prediction` | none declared |

All three *papers* are correctly licensed; it was the *code repositories* that
tripped the check. Both are public but carry no license file, and
`GET /repos/{owner}/{repo}` reports `license: null`.

**Resolved 2026-08-31 by owner decision: an unlicensed code repository no
longer blocks construction.** Papers 2 and 3 were rebuilt with their code
included. The requirement is now *record, don't block* — `code_license` is a
required field in `provenance.json` (it may say `"none declared"`, it may not
be absent), so the fact survives into Phase 5's dataset card rather than being
lost. See `docs/lifesci-paperrecon-construction.md`, "Licensing", for the
reasoning and for what Phase 5 must surface.

Note for **Phase 4**: Phase 0's screening checked that a linked repository
existed, not that it was licensed. Under the current policy that is no longer
disqualifying, so the re-screen does not need a licensed repo as a hard
filter — but it should still read and carry each candidate's `license` field
into the table, so the pool's licensing mix is a deliberate choice rather than
an unexamined one.

## Phase 4 execution results (2026-08-31)

### Scale-up: 22 of 38 approved papers built

A batch of 35 new candidate papers was screened via `core/screen.py` +
`lifesci_paperrecon/screening.py`, promoted into `papers.py`’s
`APPROVED_PAPERS` (now 38 entries), and built via
`scripts/build_lifesci_paperrecon_source.py --concurrency 3`.

| Outcome | Count | Papers |
|---|---|---|
| Built (corpus) | 22 | paper_1–3 (pilots), paper_6, 8, 11, 15, 17–21, 23–24, 26, 28–30, 32–33, 35, 38 |
| Blocked (category mismatch) | 11 | paper_4, 5, 9, 12, 14, 16, 22, 25, 27, 36, 37 |
| Failed (exhausted retries) | 5 | paper_7, 10, 13, 31, 34 |

Harbor-wrapped: **22 tasks** in `datasets/lifesci-paperrecon-short/` (`lspr-0001`
through `lspr-0022`). Fidelity/leakage audit: **22/22 passed,
determinism_ok: true**. Oracle reward 1.0 and NOP reward 0.0 confirmed on the
two retried papers (`lspr-0007`/paper_15, `lspr-0012`/paper_21).

### Category/license mix of the built corpus

All 22 papers carry `CC BY 4.0` except `lspr-0003` (paper_3, `CC BY-SA 4.0`).
Primary categories: `q-bio.QM` (7), `q-bio.BM` (5), `q-bio.GN` (5),
`q-bio.PE` (1), `q-bio.CB` (1), `stat.AP` (1), `cs.AI` (1), `stat.ME` (1).
Paper types: computational (15), experimental (7).

### Two generic bugs found and fixed

1. **Missing bundled LaTeX style files.** Papers using ICML 2026 or COLM 2026
   style files failed to compile under the no-network sandbox because those
   styles are not in `texlive-full`. Fixed by adding
   `packaging/conference-styles/{icml2026.sty,icml2026.bst,colm2026_conference.sty,colm2026_conference.bst}`.

2. **`shutil.copytree()` crashing on dead symlinks.** Third-party code
   checkouts can contain symlinks with targets outside the tree (an author’s
   own machine). Fixed by adding `symlinks=True` to every `copytree` call
   that handles a paper’s `code/` directory: `core/latex.py`
   (`compile_restricted`), `core/pipeline.py` (corpus admission),
   `adapters/paperwrite_bench/converter.py` (`_copy_public_materials` and
   the two `ground_truth_sources` copies).

### Paper_15 and paper_21 retries

Both papers were affected by the two bugs above and required a fresh
construction retry after the fixes landed.

- **paper_15** (ProtDiS, arXiv 2605.23960v1): originally failed on all 3
  turns due to missing `icml2026.sty`. After the style-file fix, it compiled
  clean but the reconstructability review caught SCOP task-level mislabeling
  in `research_overview_long.md` (invented “SCOP-clan” level, swapped
  fold/class labels). Passed on turn 2 after the agent corrected the labels.

- **paper_21** (fetal growth representation, arXiv 2608.07590v1): originally
  errored on `shutil.copytree` due to dead symlinks in its code checkout.
  After the symlinks fix, it compiled clean but had two issues: (a) a
  provenance-mismatch (`q-bio.QM` recorded instead of the true primary
  `stat.AP`), resolved by the agent on turn 1; (b) an arithmetic error in the
  overview (AGA count 729 instead of 731), caught by the reconstructability
  review and fixed on turn 2.

### What’s blocked (not this phase’s job to resolve)

The 11 category-blocked papers and the cross-listed-paper scope question
remain explicitly open and unresolved, pending a human decision from the
coordinator. See “Open follow-ups” above.

### Genuinely failed papers (not retried)

| Paper | Failure mode |
|---|---|
| paper_7 | `template.tex` compile failure (unrelated to style files) |
| paper_10 | Template leaks citations; unresolved citation key “numbers” |
| paper_13 | Agent produced no output (all required files missing) |
| paper_31 | Reconstructability review: content accuracy issues |
| paper_34 | Reconstructability review: content accuracy issues |
