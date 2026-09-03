# PaperSmith architecture: a domain-agnostic core and per-domain plugins

**Status (2026-08-31):** the split described here is implemented, with exactly
one domain plugin — `lifesci`. All three pipeline stages — screen, construct,
review — now exist; see "The three stages" below. **Math, physics and chemistry are deferred, not
promised.** A second plugin gets written when Phase 4's scale-up produces a
concrete second-domain paper set to pressure-test this interface against real
friction; adding one speculatively would tune the seam to imagined
requirements. What exists today is an extraction with **zero behaviour change**
for biology: the prompt the construction agent receives is byte-identical to
the pre-split one, and the validation gate reaches the same verdicts.

PaperSmith is the `opencode`-driven pipeline that turns arXiv papers into
PaperRecon benchmark samples. It has two halves:

- **GeneralPaperSmith** — `src/paperbench_harbor/construction/core/`. The
  candidate screener, the construction specification, the deterministic gate,
  the reconstructability reviewer, the restricted recompilation, the
  agent-session driver and the turn loop. Knows nothing about any discipline,
  and may not import a domain package.
- **DomainPaperSmith** — `src/paperbench_harbor/construction/lifesci_paperrecon/`.
  One `DomainPlugin` instance, one `ScreeningPolicy`, and that domain's approved
  paper set. Contains no machinery.

## The three stages

The deliverable is a pipeline, not a script. A paper travels through three
stages, and each one is agent-driven for the same reason: its criteria are
checkable but not enumerable, so a fixed script over the arXiv API or a regex
over LaTeX would encode only the cases someone anticipated.

| Stage | Module | Agent asks | Output | Gate |
|---|---|---|---|---|
| 1. Screen | `core/screen.py` | Which papers *could* become samples? | `candidates.json` — a proposal | A human promotes entries into the domain's approved set |
| 2. Construct | `core/prompt.py` + `core/validate.py` | Turn this paper into a sample | The `original/` + `resources/` tree | ~28 deterministic checks, plus an oracle-equivalent compile |
| 3. Review | `core/review.py` | Is the overview faithful and sufficient? | `ReviewVerdict` | A failing verdict becomes a `ValidationIssue` and drives a retry turn |

Stage 2's gate is the one that admits a paper to the corpus. Stages 1 and 3 sit
on either side of it and answer the two questions it structurally cannot: which
paper to build, and whether what got built actually means anything.

### Stage 1 — screening (`core/screen.py`)

`ScreeningPolicy` is deliberately **not** part of `DomainPlugin`. Screening and
construction are different jobs, and almost nothing a `DomainPlugin` carries —
overview skeletons, caption idiom, significance headings — bears on where to
look for a paper. The one field they must agree on is `paper_types`, because a
proposed candidate's type has to be one the construction gate will accept; a
domain builds its policy from its plugin's tuple rather than restating it.

| Field | Meaning |
|---|---|
| `name` | Short machine name, matching the domain's plugin. |
| `search_scope` | Prompt fragment: which arXiv categories and listings to search. |
| `selection_criteria` | Prompt fragment: what qualifies, in the domain's terms. The core appends the invariants no domain may relax. |
| `paper_types` | The domain's construction taxonomy, so a proposal is typed acceptably. Must equal the plugin's. |
| `prior_findings` | What a previous pass actually learned — dead-end categories, which filter bound hardest. Free text, may be empty. |

**The output is a proposal, not a decision.** `run_screening()` writes
`candidates.json` and stops; nothing appends to a domain's approved-papers
module. That invariant is load-bearing rather than procedural: `validate.py`'s
`provenance-mismatch` check works by comparing what the construction agent found
against what a human approved, and it stops meaning anything the moment the
approved list is itself machine-generated. A screening agent that could promote
its own candidates would close that loop and remove the only check against a
silently substituted paper.

The paper's own license remains a hard filter (`ACCEPTED_LICENSES`); the code
repository's license is **recorded but never filters** (owner decision,
2026-08-31), so `code_license` is a required non-empty field on every proposed
candidate rather than an optional note — a blank one would make an unlicensed
repository indistinguishable from a licensed one by the time the dataset card is
written.

**Seed data, honestly.** Phase 0 reported 27 qualifying candidates but wrote no
machine-readable table; only a narrative summary survives, and the individual
IDs of the 24 non-pilot candidates are unrecoverable. `LIFESCI_SEED_CANDIDATES`
is therefore empty, and a test pins it that way. Reconstructing plausible arXiv
IDs from the category breakdown would produce a list that looks like recovered
data and is not. What *is* recoverable is seeded into `prior_findings` instead —
the category set, the `q-bio.SC` dead end, the fact that the license filter
bound hardest — and the agent re-derives the pool live. It would have had to
anyway: the code-repo-license filter that produced the original 27 is no longer
the policy, so a recovered list would have needed full re-screening regardless.

### Stage 3 — reconstructability review (`core/review.py`)

`validate.py`'s ~28 checks are all structural — headings present, lengths in
range, no literal leakage, the oracle compiles. None can tell whether the
overview is *true about this paper* or says enough to reconstruct it. A
generated overview can satisfy the entire gate while being a fluent description
of nothing in particular, and the only thing that has ever caught that is a
human reading the overview against the paper, which does not scale to 30-50
samples.

So a second model reads `original/main.tex` beside the generated overviews and
returns a `ReviewVerdict`:

| Field | Type | Meaning |
|---|---|---|
| `ok` | `bool` | Whether the sample passes all three tests (faithful, sufficient, no literal leakage). |
| `reasoning` | `str` | The judgment, citing specific content. Read by a human auditing the corpus. |
| `concerns` | `list[str]` | Specific, actionable problems. Fed verbatim to the next construction turn, so a failing verdict with no concerns is itself rejected — the retry would have nothing to act on. |

**The reviewer must be a different model family from the constructor.**
Same-model self-grading is a known failure mode of generator-plus-judge loops: a
model reviewing its own output ratifies its own misreadings, because the
misreading and the review come from the same prior. The default reviewer is
`apex-claude/claude-sonnet-5` against a `openai/gpt-5.6-terra` constructor — a
deliberately different vendor and architecture, capable enough for a
faithfulness judgment without being the most expensive tier, which matters for a
check that runs on every paper of every turn. Overridable by `--reviewer-model`,
then `$REVIEWER_MODEL`, then the default.

**The reviewer runs against a throwaway copy, never the live workspace.** It
runs under the same `opencode run --auto` mode as construction, which grants
unsupervised filesystem writes to whatever `--dir` points at. A reviewer that
can edit the sample it is grading is not a reviewer — and worse, it could
silently repair an otherwise-failing corpus candidate into passing. So
`run_review()` copies exactly three files — `original/main.tex` and the two
`resources/research_overview_*.md` — into a fresh `<build_root>/<paper_id>/review/`
and points the agent there. Not `provenance.json` (which would tell it what the
constructor claims), not `template.tex`, not the figures. The directory is
rebuilt from scratch every call, because a stale copy would let the reviewer
grade the previous turn's overview.

**The verdict is parsed, never trusted.** `verdict.json` gets the same treatment
as `provenance.json`: malformed JSON, a missing key, a wrong type (`"ok": 1` and
`"ok": "true"` both rejected), an empty `reasoning`, or a rejection with no
concerns are all hard failures. A reviewer that cannot produce a well-formed
verdict has not reviewed anything, and coercing one into shape would mean a
paper admitted on a verdict nobody read.

**Integration reuses the existing vehicle.** A failing verdict becomes
`report.fail("reconstructability-review", ...)` on the *same*
`ValidationReport` the structural gate produced. `report.ok` is a property over
`.issues`, so it recomputes to `False` automatically, and `build_retry_prompt()`
needed zero changes — `report.agent_feedback()` already renders every issue into
the next opencode turn exactly like a compile failure. No second report type, no
second retry loop.

**Audit trail.** On a paper that ultimately passes, the last verdict is written
to `original/reconstructability_review.json` before the corpus copy, so what the
independent reviewer actually said travels with the sample. Under `original/`,
never `resources/`: `resources/` is copied verbatim into the writing agent's
environment, and a reviewer's account of what the overview does and does not
contain is a description of the answer.

**Cost control.** `--skip-review` turns stage 3 off for cheap structural
iteration. Note one thing the plan assumed that the code does not do: review was
to run only when `run_compile=True`, but `run_compile` is not a parameter of
`build_paper()` — `validate_paper()` is always called with its default `True`,
and `--validate-only` skips the *agent*, not the compile. So the guard reduces
to `--skip-review` alone, which is the flag that actually controls the cost.

**First live result (2026-08-31).** Run against the already-built, already-passing
`paper_1`, the reviewer returned **`ok: false`** — and was right. It confirmed
roughly twenty quantitative claims against `main.tex` as exact, then found that
`research_overview_long.md` asserts the CUDA-vs-OpenCL speedup is "near
1.35-fold at 8,192" patterns in the same sentence that says it was "always more
than 1.5-fold", against `main.tex`'s "over 1.5-fold ... across all pattern
counts". A second concern (a two-GPU value of 1.8-fold against the paper's
stated 1.1-1.7-fold incremental bound) is equally checkable. Both are real
defects that all ~28 structural checks pass over, which is precisely the gap
this stage was built to close.

That run also exposed a prompt bug worth recording: the reviewer initially
flagged several figure-derived numbers as "invented" because it is shown
`main.tex` but not the figures, while the construction prompt explicitly tells
the constructor to read values off the plots. The review prompt now states that
asymmetry — a value absent from the prose is not by itself unfaithful; a value
that *violates a bound the prose states* is, whichever figure it came from. The
correction removed the false positives and left both real findings standing.

## One-command entry point

**Status (2026-08-31): step 2 of 2 shipped.** Both additive touches deferred
during step 1 — the `approved_scaleup.jsonl` loader in `papers.py` and
`--extra-guidance` on the screening CLI — landed once the Phase 4 scale-up run
that was actively editing those same files settled and merged. See "What was
wired in step 2" below for what changed and how it was verified.

The three stages above are capabilities, not a workflow. Growing the corpus still
meant a human running four programs in order and hand-carrying candidate ids
between them. `.opencode/agent/papersmith-lifesci.md` is the entry point that
removes the hand-carrying: a `mode: primary` custom opencode agent, invoked as

```
opencode run --agent papersmith-lifesci "give me 10 more life-sciences papers about genomics with public code"
```

from the repository root on the build host. The deliverable is an opencode agent
rather than a Python CLI because the entry point has to accept a free-form
request, and a fixed `argparse` surface cannot take "about genomics with public
code" as an argument. The free text steers the parameters; the procedure itself
is fixed and runs identically every time.

### The seven steps

| # | Step | Program |
|---|---|---|
| 1 | Parse the request for a target count, topical steering, and any explicit arXiv IDs | the agent itself |
| 2 | Screen for candidates | `scripts/screen_lifesci_paperrecon_candidates.py` |
| 3 | Verify every claim against live sources | `scripts/promote_lifesci_paperrecon_candidates.py --limit N` |
| 4 | Human approves a byte-bound candidate subset, then promote | `scripts/promote_lifesci_paperrecon_candidates.py --human-approval <file> --promote --limit N` |
| 5 | Build — construction plus reconstructability review | `scripts/build_lifesci_paperrecon_source.py --concurrency 3` |
| 6 | Harbor-wrap the corpus | `paperbench-harbor lifesci-paperrecon --overwrite` |
| 7 | Audit task fidelity and semantic material allocation | `scripts/audit_fidelity.py lifesci-paperrecon` |
| 8 | Report candidates → human-approved/promoted → built → blocked → task count → audit result | the agent itself |

Only steps 1 and 7 are the agent's own judgment, and both are about reading a
sentence and relaying output. Every step that decides anything is a program.

### Why promotion is a separate deterministic program

"One command starts the whole thing" appears to contradict the invariant stage 1
rests on. Screening's output is *a proposal, not a decision* precisely because
`validate.py`'s `provenance-mismatch` check works by comparing what the
construction agent found against what a human approved — and it stops meaning
anything the moment the approved list is itself machine-generated. A pipeline
that auto-promotes has closed that loop.

The resolution is not to trust the screening agent more, and not to let the
orchestrating agent write the approved list. It is to put an **independent,
deterministic verification stage between screening and promotion**:

- `promote_lifesci_paperrecon_candidates.py` re-derives every claim in
  `candidates.json` from the live arXiv and GitHub APIs. There is no model call
  anywhere in the file. What the screening agent said is treated as an assertion
  to be checked, never as a fact to be copied.
- A candidate whose *claimed* field disagrees with the live source is **rejected
  outright, even if the claim would have been policy-compliant had it been
  true**. This is deliberately stricter than "policy-compliant", and the extra
  strictness is the entire point: the failure mode being defended against is not
  "an inadmissible paper slipped through", it is "the agent copied the answer key
  instead of checking" — which is exactly what `provenance-mismatch` catches one
  stage later, at the cost of a full construction run. Two real screening
  candidates this session reported a primary category from the model's prior
  rather than from the API, which is what motivated building this at all.
- The default invocation is a **dry-run report**. Writing requires an explicit
  `--promote` plus a human-created approval JSON record that names the reviewer,
  selects candidate arXiv ids, and carries the SHA-256 of the exact candidate
  proposal. A stale approval cannot be replayed against edited candidate bytes;
  an eligible candidate not selected by the reviewer remains unpromoted.
  `--limit N` still caps one invocation.
- Promotion writes **data, not code**: accepted candidates are appended to
  `src/paperbench_harbor/construction/lifesci_paperrecon/approved_scaleup.jsonl`,
  one `PaperSpec`-shaped JSON object per line. It never text-surgeries
  `papers.py`, whose hand-curated tuple stays a hand-edited Python artifact.
- Idempotency is keyed on `arxiv_id`, never `paper_id`. The `paper_id` is
  assigned at promotion time and would differ between two runs over the same
  candidate, so a `paper_id` comparison would duplicate every entry on the second
  run. New ids continue past the highest `paper_N` in both the tuple and the
  JSONL, so two promotion runs cannot collide.
- The orchestrating agent has **no `edit` and no `write` access at all**, and its
  `bash` permission is deny-by-default with an allowlist of the five specific
  program invocations this pipeline needs plus `cat`/`ls`/`git rev-parse HEAD`.
  It also never runs anything with `--auto`: the scripts it calls start their own
  `--auto` sessions inside their own scratch workspaces, and the orchestrator
  sits one level above that. So the agent's role is strictly "call these known
  programs with sensible arguments and relay what they printed", enforced
  structurally rather than by instruction.
- The audit command defaults to isolated semantic review and the PaperSmith
  permission policy explicitly denies `--no-semantic-review`. Its version-pinned
  report records the upstream revision and tree digest, dataset tree digest,
  converter revision, reviewer selection, and semantic-review outcome so a
  release can retain actual evidence instead of a prose claim.

One implementation note worth recording, because it is not what the plan assumed:
**the arXiv Atom API does not expose a license.** An `id_list` query returns
`arxiv:primary_category` and the version (in the entry's `<id>`), and the string
"license" appears nowhere in the response — verified against the live API,
2026-08-31. The license is only on the abstract *page*, in a
`<div class="abs-license">` anchor whose `href` is the canonical Creative Commons
URL. So promotion reads two arXiv endpoints, and derives the license name
structurally from that URL's path (`/licenses/by-sa/4.0/` → `CC BY-SA 4.0`)
rather than through a lookup table, which makes it spell every variant the same
way `ACCEPTED_LICENSES` does with nothing to keep in sync. A missing license
block is a hard failure, not a pass: if arXiv changes the page layout, the script
must say it verified nothing.

### What this is not

**This is not the paper-writing-agent evaluator, and the agent's prose forbids it
from talking as though it were.** The pipeline stops at "produced a correctly
built Harbor task". The oracle=1.0/NOP=0.0 smoke check and the fidelity audit are
task-*design* correctness checks (the two-layer distinction in
`docs/lifesci-paperrecon.md`): they establish that a task is well-formed and that
its verifier discriminates, and they say nothing about how well any agent writes.
The Layer-2 LLM judge is Phase 3, still deferred, and no part of this entry point
touches or implies it. The agent reports counts, pass/fail and failure reasons —
never a score, never "quality", never how a writing agent would fare.

Publishing is also out of scope: it stays the separate, explicitly human-triggered
Hugging Face workflow in `docs/dataset-versioning.md`. Nothing here auto-publishes.

A second domain's entry point will be a second file,
`.opencode/agent/papersmith-<domain>.md`, with the same seven-step shape pointed
at that domain's scripts — not a multi-domain dispatcher built before a second
domain exists, the same YAGNI stance as the plugin split.

### What was wired in step 2

Both touches deferred in step 1 intersected files the in-flight Phase 4
scale-up run was actively editing (`papers.py`, `screen_lifesci_paperrecon_candidates.py`).
Once that run merged (`APPROVED_PAPERS` grew from 3 hand-curated pilots to 38),
both landed on top of it:

1. **`papers.py` now reads `approved_scaleup.jsonl`.** `_load_scaleup_promotions()`
   parses the file (one `PaperSpec`-shaped JSON object per line) if it exists, and
   `APPROVED_PAPERS` becomes the hand-curated tuple plus whatever it contains.
   A missing file — the ordinary case for a checkout that has never run
   promotion — yields the empty tuple, so this is byte-for-byte a no-op change
   for every existing caller: confirmed by re-running the full suite immediately
   after landing the loader, before touching anything else, and by a dedicated
   test (`tests/test_lifesci_paperrecon_papers_loader.py`) that asserts
   `APPROVED_PAPERS` equals the hand-curated tuple when the file is absent. A
   malformed line (bad JSON, a JSON array instead of an object, a missing
   field) raises by name rather than silently dropping a promoted paper — the
   same "don't trust, verify" discipline `provenance.json` parsing uses
   elsewhere in this package.
2. **`screen_lifesci_paperrecon_candidates.py` now has `--extra-guidance`.**
   `build_screening_prompt()` and `run_screening()` both gained a keyword-only
   `extra_guidance: str = ""` parameter, rendered as its own prompt section
   ("This run's topical steering") appended alongside `prior_findings` rather
   than woven into the invariants — it can narrow which *qualifying* papers get
   proposed, and the prompt says explicitly that it never relaxes what
   qualifies. Verified with a dry-run render (`--dry-run` prints the rendered
   prompt without spending a model call) confirming the steering text and the
   non-relaxation sentence both appear.

Steps 1-4 of the seven-step procedure now form an unbroken chain: a paper
promoted in step 3 is immediately visible to step 4's `--papers` argument via
`APPROVED_BY_ID`, with no manual edit in between. The live end-to-end smoke
test (`opencode run --agent papersmith-lifesci "<a request for exactly 1 new
paper>"`, producing one new validated Harbor task with no manual step) is
still a separate verification step and is not claimed by the unit-level
evidence above — see the open item below.


## Why in-process plugins, and not a forked pipeline

Two pieces of prior art decided this, in opposite directions.

**HELM is the precedent we followed.** It splits into a fixed harness plus
"scenario" plugin objects, one per task or domain; IBM's Enterprise-HELM adds
finance, legal and climate scenarios without touching the core. Terminal-Bench
and Bench360 use the same shape under a `BaseTask`/adapter interface. The
lesson is that a shared harness parameterized by in-process objects survives
domain addition, and keeps one copy of the logic that must not drift — here,
the oracle-equivalent compile and the leakage rule.

**SWE-bench is the cautionary alternative we avoided.** Its cross-language
adaptation is done by *forking the whole pipeline per language* — SWE-bench-C,
SWE-Next — rather than by a shared core with a language plugin. That is a real
warning that a plugin interface can fail to hold up across genuinely different
domains, and it is exactly why this phase adds **one** plugin (extracted from
working code) rather than three (invented from guesses). If the interface turns
out to strain against a second real domain, the friction shows up as new
plugin fields or a widened seam — a cheaper failure than discovering it after
three speculative domains have been built against it.

A third consideration is about verifiers, not structure: a deterministic gate
only catches what it was built to check. Adding a domain does not shrink the
semantic-quality gap, it multiplies it, unless each domain's verifier extension
is deliberate. That is why `DomainPlugin` separates *contract* fields the
validator enforces from *prompt fragments* the agent merely reads: a domain can
say what its overview must contain, but it cannot weaken the compile, leakage
or provenance checks.

## Layout

```
src/paperbench_harbor/construction/
  core/                       GeneralPaperSmith
    spec.py                   PaperSpec, ACCEPTED_LICENSES — no domain fields
    plugin.py                 DomainPlugin: the construction domain seam
    screen.py                 stage 1: ScreeningPolicy, Candidate, run_screening
    prompt.py                 build_prompt / build_retry_prompt (spec, output_dir, plugin)
    validate.py               validate_paper(paper_dir, spec, plugin, *, build_root, run_compile)
    review.py                 stage 3: ReviewVerdict, run_review
    latex.py                  restricted recompilation, verifier flags
    opencode_agent.py         run_agent_session(): one `opencode run` session
    pipeline.py               build_paper() turn loop; build_corpus() worker pool
  lifesci_paperrecon/         LifeSci DomainPaperSmith
    papers.py                 APPROVED_PAPERS — the approved selection
    screening.py              LIFESCI_SCREENING_POLICY, seeds and exclusions
    plugin.py                 LIFESCI_PLUGIN
    approved_scaleup.jsonl    promoted candidates, one PaperSpec-shaped record
                              per line — data, written only by the promotion
                              script, read back into APPROVED_PAPERS by
                              papers.py's additive loader

.opencode/agent/
  papersmith-lifesci.md       the one-command entry point
```

`scripts/build_lifesci_paperrecon_source.py` is now a thin CLI wrapper:
argument parsing, then `build_corpus(APPROVED_PAPERS, LIFESCI_PLUGIN, ...)`. A
future domain's build script is that file with two imports changed.

## The `DomainPlugin` contract

Every field is required; the dataclass is frozen. Fields divide into what the
validator **enforces** and what the prompt **prints**.

### Contract fields — the validator acts on these

| Field | Type | Meaning and use |
|---|---|---|
| `name` | `str` | Short machine name (`"lifesci"`). Logs and reports only. |
| `domain_label` | `str` | The adjective the domain uses for itself in validator feedback (`"biology"` → "Use the biology overview skeleton: ..."). |
| `paper_types` | `tuple[str, ...]` | The domain's replacement for PaperWrite-Bench's method/benchmark/both taxonomy. `_check_config` rejects a `config.yaml` whose `type` is not in this tuple, and separately rejects one that disagrees with the human-approved `PaperSpec.paper_type`. |
| `overview_headings` | `tuple[tuple[str, ...], ...]` | Required overview sections as accepted *spellings*: each inner tuple is lowercase variants, any one of which satisfies that heading. Drives `_check_overviews`; a missing heading is an `overview-skeleton` failure. |
| `overview_bounds` | `dict[str, tuple[int, int]]` | Per-overview-file `(floor, ceiling)` character bounds. Sanity bounds, not style rules: the floor catches a heading skeleton with no content, the ceiling catches an agent that pasted the paper in. |
| `agents_md_dir` | `Path` | Where the domain's `AGENTS_<paper_type>.md` writing instructions live — its Harbor adapter's `AGENTS_MD_DIR`. `_check_config` verifies the file exists, because the converter silently falls back to a default type and would otherwise hand a paper the wrong writing instructions. |

### Prompt fragments — the agent reads these

| Field | Type | Meaning and use |
|---|---|---|
| `benchmark_intro` | `str` | Opening sentences naming the benchmark and what a sample of it is. The core appends "Your job is to turn one published arXiv paper into that sample...". |
| `overview_skeleton_headings` | `tuple[str, ...]` | The skeleton in display form, ordered. The first entry renders as the `#` title heading, the rest as `##` sections. `overview_skeleton()` builds the block the prompt prints; `overview_skeleton_remedy()` builds the one-line remedy the validator attaches to a failed check. |
| `significance_heading` | `str` | Which skeleton heading carries "why this result matters to the field" — the one section whose framing is genuinely domain-specific (`"Biological Significance"`; a physics domain would name its own). |
| `overview_length_targets` | `str` | The length targets the prompt asks for, as a phrase. Deliberately beside `overview_bounds`: the prompt target and the enforced bound are two views of one decision, and a domain that widened one without the other would be telling the agent to miss its own gate. |
| `overview_skeleton_rationale` | `str` | Trailing clause explaining why the skeleton has this shape. Spliced after "using this skeleton", so it carries its own separator. May be empty. |
| `overview_content_guidance` | `str` | What the overview must actually say in this domain's terms — which quantities, identifiers and significance a reader of *this* literature needs. |
| `caption_example` | `str` | One example caption line for `figure_summary.txt`, in the domain's idiom. |
| `imagery_guidance` | `str` | What this domain's figures typically are, so the agent describes what is actually plotted instead of defaulting to ML-paper vocabulary. |
| `stop_condition_examples` | `str` | Domain clarifications appended to the core stop-condition list — what does *not* stop a build, and any domain-specific reason that does. May be empty; lifesci uses it for the code-repository-license carve-out (owner decision, 2026-08-31), which is this benchmark's policy rather than a core invariant. |

`__post_init__` rejects a self-contradictory plugin: `significance_heading`
must appear in `overview_skeleton_headings` and be accepted by
`overview_headings`, so a domain cannot ship a skeleton its own validator would
reject.

### What stays in the core, and is not a plugin's to change

The verifier compile sequence; the oracle's `main.tex` rewrite behaviour and
the natbib injection documentation; the `original/` + `resources/` output tree;
the leakage rule; the `config.yaml` and `provenance.json` field specifications;
the `references.bib` and `code/` rules; `ACCEPTED_LICENSES`; the retry-prompt
mechanics; and every check in `validate.py` other than the three that consult
the plugin (paper type, overview skeleton, overview bounds).

## Concurrency

`core.pipeline.build_corpus(specs, plugin, *, concurrency=1, ...)` runs
`build_paper()` per spec in a `ThreadPoolExecutor`. Threads rather than
processes because every expensive step waits on something else — the agent's
API calls, `pdflatex`, a git checkout — and each paper already owns a separate
scratch workspace (`<scratch_root>/<paper_id>/`), a separate compile build root
and a separate agent session, so workers share no mutable state. Outcomes come
back in `specs` order regardless of completion order, and a worker that raises
is recorded as that paper's outcome rather than sinking the run.

`concurrency=1` is the default and `--concurrency N` exposes it. The real
ceiling is the model gateway's rate limit, which is a property of the
deployment rather than of this code.

## Shared agent-session plumbing

`opencode_agent.run_agent_session()` drives every `--auto` session in this
package — construction turns, screening passes and review calls alike. It was
named `run_construction` when construction was its only caller; nothing about it
was ever construction-specific (`paper_id` is a log label, and
`continue_session=False` was already the single-shot case), so it was renamed
rather than copied when stages 1 and 3 arrived.

Its two containment rules apply to all three stages: the working directory must
be outside any git working tree, and nothing an agent produces enters the corpus
until the gate has passed it.

## Evidence the split is real

- `tests/test_lifesci_paperrecon_validate.py` — unchanged assertions, updated
  imports and call signature only. Proves zero behaviour change for biology.
- `tests/test_construction_core_generic.py` — defines a second, deliberately
  unbiological in-test `DomainPlugin` and asserts the same core code enforces
  *its* contract: the same bytes on disk pass under one plugin and fail under
  the other, bounds and paper types follow the plugin, no biology leaks into
  another domain's prompt, and the core invariants survive any plugin.
- The pilot corpus at `.cache/lifesci-paperrecon/corpus/{paper_1,paper_2,paper_3}`
  re-validates to PASS through the new `core.validate` path, including the
  oracle-equivalent compile.
- `tests/test_construction_core_review.py` — verdict shape validation, the
  containment property (a reviewer that writes to its `--dir` cannot reach the
  live sample), model-selection precedence, and the `ValidationReport`
  integration.
- `tests/test_construction_core_screen.py` — prompt building from a second,
  deliberately non-biological `ScreeningPolicy`, `candidates.json` shape and
  policy validation, and the honestly-empty lifesci seed list.
- `tests/test_promote_lifesci_paperrecon_candidates.py` — the verify-before-promote
  stage, against arXiv and GitHub payloads copied from real responses so the
  parsers are exercised rather than bypassed: a claim matching the live source is
  accepted, a mismatch on any one of license, category or code license is rejected
  with that field named, a dry run leaves the approved file untouched, `--limit`
  caps eligible promotions, a human approval is required and byte-bound, and a
  second run over the same candidates is a no-op.

## Related documents

- `docs/lifesci-paperrecon-construction.md` — the construction recipe, the
  build host requirements, and the pathologies the pilot exposed.
- `docs/lifesci-paperrecon.md` — benchmark status and the two-layer
  verification architecture.
- `docs/naming-convention.md` — the PaperSmith name and the brand ↔ upstream
  mapping.
