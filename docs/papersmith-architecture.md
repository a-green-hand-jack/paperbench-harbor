# PaperSmith architecture: a domain-agnostic core and per-domain plugins

**Status (2026-08-31):** the split described here is implemented, with exactly
one domain plugin — `lifesci`. **Math, physics and chemistry are deferred, not
promised.** A second plugin gets written when Phase 4's scale-up produces a
concrete second-domain paper set to pressure-test this interface against real
friction; adding one speculatively would tune the seam to imagined
requirements. What exists today is an extraction with **zero behaviour change**
for biology: the prompt the construction agent receives is byte-identical to
the pre-split one, and the validation gate reaches the same verdicts.

PaperSmith is the `opencode`-driven construction agent that turns an arXiv
paper plus its code repository into a PaperRecon benchmark sample. It has two
halves:

- **GeneralPaperSmith** — `src/paperbench_harbor/construction/core/`. The
  construction specification, the deterministic gate, the restricted
  recompilation, the agent-session driver and the turn loop. Knows nothing
  about any discipline, and may not import a domain package.
- **DomainPaperSmith** — `src/paperbench_harbor/construction/lifesci_paperrecon/`.
  One `DomainPlugin` instance plus that domain's approved paper set. Contains
  no machinery.

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
    plugin.py                 DomainPlugin: the entire domain seam
    prompt.py                 build_prompt / build_retry_prompt (spec, output_dir, plugin)
    validate.py               validate_paper(paper_dir, spec, plugin, *, build_root, run_compile)
    latex.py                  restricted recompilation, verifier flags
    opencode_agent.py         one `opencode run` session per turn
    pipeline.py               build_paper() turn loop; build_corpus() worker pool
  lifesci_paperrecon/         LifeSci DomainPaperSmith
    papers.py                 PILOT_PAPERS — the approved selection
    plugin.py                 LIFESCI_PLUGIN
```

`scripts/build_lifesci_paperrecon_source.py` is now a thin CLI wrapper:
argument parsing, then `build_corpus(PILOT_PAPERS, LIFESCI_PLUGIN, ...)`. A
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

## Extension point left open, deliberately unbuilt

A **reconstructability review** — a second model reading the generated overview
back against the paper, to catch an overview that satisfies every structural
check while being unusable — belongs in `core/review.py` and would run in the
turn loop between a passing validation and admission to the corpus. It is
domain-agnostic (comparing a paper to its overview needs no biology), and it is
**not implemented**: no LLM-calling review code was written in this phase, per
the owner's earlier explicit choice. The pipeline's structure leaves the seam
obvious.

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

## Related documents

- `docs/lifesci-paperrecon-construction.md` — the construction recipe, the
  build host requirements, and the pathologies the pilot exposed.
- `docs/lifesci-paperrecon.md` — benchmark status and the two-layer
  verification architecture.
- `docs/naming-convention.md` — the PaperSmith name and the brand ↔ upstream
  mapping.
