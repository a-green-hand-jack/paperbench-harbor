# LifeSci-PaperRecon: construction recipe

How the biology paper-writing benchmark is built. Unlike
`paperwrite-bench-short` and `paperwritingbench-sparse-plotoff`, which adapt
published third-party benchmarks, **this benchmark is built in-repo** from
public arXiv `q-bio` papers. There is no upstream dataset or evaluator to
preserve fidelity to, so the quality bar is different: provenance
traceability, reproducibility from a pinned snapshot, and a documented
construction procedure.

Status and phase breakdown: `docs/lifesci-paperrecon.md`. Brand-name vs.
upstream-name rules: `docs/naming-convention.md`.

## The design decision that shapes everything else

An earlier iteration of this pipeline hand-wrote the paper transformations in
Python — `arxiv.py` to fetch, `latex.py` to strip `main.tex` into a template,
`figures.py` to extract assets, and so on. It was abandoned mid-flight.

The reason is worth recording, because the obvious response to a broken build
is to fix the script. The first pilot paper's preamble contained
`\standaloneconfig{mode=buildnew}`, which requires `-shell-escape`; the Harbor
verifier forbids `-shell-escape`, so the paper could not compile. The fix at
the time was a hand-written regex. The next paper would have had a different
pathology needing a different regex, and the one after that another. At 3
samples that is annoying; at the planned 30–50, across a domain nobody has
built a corpus for before, it is a rule library that only ever grows and that
encodes no reusable understanding.

So the pipeline was inverted. **Per-paper judgment is delegated to an agent;
only the contract is code.**

| Delegated to the agent (varies per paper) | Kept as plain code (never varies) |
|---|---|
| Fetching the source bundle and PDF | What files must exist, and under which names |
| Re-verifying license, version, category | What must *not* exist (leakage) |
| LaTeX surgery to make it compile restricted | Whether it compiles under the verifier's flags |
| Converting `.bbl`/`\bibitem` into BibTeX | Whether every cited key resolves |
| Extracting and captioning figures | Whether every asset is captioned |
| Writing the research overviews | Whether the overview skeleton is present |
| Checking out and pruning the code repo | Whether provenance matches the approved selection |

The right-hand column is contract checking, not paper-specific judgment, which
is why it stays deterministic and reviewable. The agent cannot negotiate with
it: a sample that fails the gate does not enter the corpus, and the designed
response to a failure is *another agent turn fed the gate's own findings*, not
a patch to the gate.

## Module layout

Since the GeneralPaperSmith/DomainPaperSmith split, the machinery below is
domain-agnostic and lives under `construction/core/`, parameterized by a
`DomainPlugin`; only the paper set and the plugin are biology-specific. See
`docs/papersmith-architecture.md` for the contract.

| Path | Responsibility |
|---|---|
| `src/paperbench_harbor/construction/lifesci_paperrecon/papers.py` | The approved pilot set. Every field is an *expectation to re-verify*, never a trusted fact. |
| `.../lifesci_paperrecon/plugin.py` | `LIFESCI_PLUGIN`: the biology paper-type taxonomy, overview skeleton and bounds, and the prompt fragments that make the spec a life-sciences one. |
| `src/paperbench_harbor/construction/core/prompt.py` | The construction specification handed to the agent, and the retry prompt built from a failed validation report. |
| `.../core/opencode_agent.py` | Invokes `opencode run`, and refuses to do so anywhere inside a git working tree. |
| `.../core/latex.py` | Recompilation under the verifier's exact restricted flags. |
| `.../core/validate.py` | The deterministic gate. Layout, provenance, leakage, citations, and an oracle-equivalent compile. |
| `.../core/spec.py` | `PaperSpec` and the redistribution-permissive license policy. |
| `.../core/pipeline.py` | The per-paper agent/validate/retry loop, the corpus admission step, and the `--concurrency` worker pool. |
| `scripts/build_lifesci_paperrecon_source.py` | Thin CLI wrapper: pilot papers + `LIFESCI_PLUGIN` into `build_corpus()`. |
| `src/paperbench_harbor/adapters/lifesci_paperrecon/harbor.py` | Phase 2 identity metadata for the shared converter. No second Harbor converter exists. |
| `src/paperbench_harbor/adapters/lifesci_paperrecon/agents_md/` | Biology writing instructions (`AGENTS_computational.md`, `_experimental.md`, `_review.md`) handed to the *writing* agent at benchmark time. |

## The output contract

Each paper is built into the generic layout the PaperWrite-Bench converter
already consumes, which is why Phase 2 needs no new converter:

```
<paper_id>/
├── original/            GROUND TRUTH — verifier-only, never shown to the writer
│   ├── main.tex
│   ├── main.pdf
│   ├── config.yaml      type / num_page / column / conference
│   └── provenance.json  arXiv id+version+category, license, fetch date, code commit
└── resources/           PUBLIC — copied verbatim into the writer's workspace
    ├── template.tex             section skeleton, must compile standalone
    ├── research_overview_short.md
    ├── research_overview_long.md
    ├── references.bib           the paper's own bibliography, verbatim
    ├── figure_summary.txt
    ├── table_summary.txt
    ├── figures/
    ├── tables/                  (omitted when the paper has no separate table assets)
    └── code/                    the study's public analysis repository
```

`provenance.json` is this benchmark's addition to the upstream layout. The
converter sweeps it into `tests/private/ground_truth_sources/` along with the
rest of `original/`, so it stays verifier-only; `fidelity/transforms.py`
declares it explicitly (`_LSPR_PRIVATE_ORIGINAL_FILES`) so the leakage audit
knows where it is supposed to end up.

### The biology overview skeleton

PaperWrite-Bench's overview is shaped for ML method papers
(Motivation / Proposed Method / Contributions). This corpus replaces it:

```
# Title
## Research Question or Hypothesis
## Approach
## Key Findings
## Biological Significance
## Takeaway
```

The overview is the *only* description of the study the writing agent
receives, so it has to be sufficient to reconstruct the science — actual
quantitative results, effect sizes, model parameters, organism and dataset
identifiers — while not being the paper. `validate.py` enforces the headings,
length bounds, and the absence of LaTeX structure; whether the content is
genuinely reconstructable is a human review question and is listed under
"What a human still has to check" below.

## The validation gate

`validate_paper()` runs seven groups of checks. The first six are structural;
the seventh is the expensive and important one.

1. **Layout** — every contract file present. `figures/` and `code/` must be
   non-empty: a public, redistribution-permissive code repository is a
   *selection criterion* for this benchmark, so an empty `code/` means the
   paper should not have been chosen.
2. **Config** — `type` is one of `computational`/`experimental`/`review`,
   matches the human-assigned type, and has a corresponding `AGENTS_<type>.md`.
   That last check exists because the converter *silently falls back* to
   `AGENTS_computational.md` for an unknown type, which would hand a paper the
   wrong writing instructions with no error anywhere.
3. **Provenance** — required fields present, and arXiv id, version, category,
   license and code repo all match the approved selection. A mismatch is a
   hard failure, never a warning: silently substituting a paper is worse than
   failing the build.
4. **Template** — a complete document, at least three sectioning commands, no
   `\cite` commands, and no more than 25% of the ground truth's body prose
   surviving. A template that carries the text leaves nothing to reconstruct.
5. **Overviews** — skeleton headings present, within length bounds, not LaTeX,
   and the long variant strictly longer than the short one.
6. **Summaries** — every file in `figures/`/`tables/` is named in the
   corresponding summary. An asset the writer cannot identify is unusable.
7. **Citations and compilation** — see below.

### Why the compile check reproduces the oracle instead of approximating it

The check that matters is "will the oracle score reward `1.0`", because that is
what proves the generated task is solvable at all. Getting that right means not
re-implementing what the oracle does. So `_check_compiles`:

- builds a real `materials/` tree using the converter's **own**
  `_copy_public_materials`;
- renders the **shipped** `normalize.py.j2` template and runs it, exactly as
  `solve.sh` does — including its bibliography renaming and its resolution of
  every `\includegraphics`/`\input` against the public materials;
- compiles the result with `compile_restricted`, which reproduces
  `test_state.py.j2`'s command sequence
  (`pdflatex ×2`, `bibtex`, `pdflatex ×2`, all with
  `-interaction=nonstopmode -halt-on-error -no-shell-escape`) from a clean copy.

Copying `resources/` and `original/` into one directory and compiling that
would be easier and would be wrong: it would pass papers whose figure paths
only resolve because the ground-truth tree happens to be laid out
conveniently, and would miss `\graphicspath` double-prefixing entirely.

`template.tex` is compiled separately from a copy of `resources/` alone,
because it is what the writing agent starts from — a task whose skeleton does
not compile before the agent writes a word is broken.

Citation coverage uses `test_state.py.j2`'s regexes and its `\input`-expanding
reader, copied deliberately rather than approximated, so a paper that splits
its body across `\input` files cannot pass here and fail in the verifier.

## Running a build

Both the agent and the compile checks need a host with network access, the
`opencode` CLI, and a TeX Live matching the verifier's. See
"Build host" below.

```bash
scripts/build_lifesci_paperrecon_source.py \
    --scratch-root /home/user/lifesci-paperrecon-scratch \
    --corpus-root  .cache/lifesci-paperrecon/corpus \
    --papers paper_1 \
    --max-turns 3 \
    --report .cache/lifesci-paperrecon/report-paper_1.json
```

Per paper the loop is:

1. `opencode run --model openai/gpt-5.6-terra --auto --dir <scratch>/<paper_id> "<prompt>"`
2. run the gate against the scratch workspace;
3. on failure, `opencode run ... --continue "<retry prompt built from the gate's findings>"`
   — the same session, so the agent is correcting its own work with the context
   of why it built it that way, not rebuilding blind;
4. on success, copy the workspace into the corpus (minus `.git`);
5. after `--max-turns`, report the failure. Never patch it here.

`--validate-only` re-runs the gate against existing workspaces without
invoking the agent; `--dry-run` prints the exact command and prompt without
running anything, which is the cheapest way to review a prompt change.

### Scratch isolation is enforced, not documented

`--auto` auto-approves every tool permission — the CLI itself calls it
dangerous — so the agent has unsupervised shell and file-write access for the
length of the run. `prepare_scratch()` and `run_agent_session()` both walk the
path's ancestors and **refuse to start** if the workspace is inside a git
working tree. Nothing enters the repository until the gate has passed it.

### Stop conditions

The prompt gives the agent four conditions under which it must refuse to build:
a non-permissive **paper** license, a PDF-only submission with no LaTeX source,
a code repository that is gone/private/uncheckoutable, or an arXiv
id/version/category that does not match the approved selection. The agent
records the reason in `original/provenance.json` under a top-level `"blocked"`
key and stops.

The code repository's *license* is deliberately **not** among them — see
"Licensing" below.

The harness surfaces a block as a distinct `blocked` status rather than a
generic validation failure, because the two need different human responses: a
blocked paper is a re-selection decision, a failed one is a retry.

## Build host

The construction build does not run on a typical developer laptop. It needs:

- **`opencode`** (v1.18.25 at time of writing) with a provider configured for
  `openai/gpt-5.6-terra`;
- **network access** for arXiv and GitHub;
- **`pdflatex`/`bibtex` matching the verifier's TeX Live**;
- tens of GB of disk for source bundles, PDFs and code checkouts.

On the TeX requirement: the verifier compiles inside `ubuntu:24.04` +
`texlive-full` (`common/templates/tests.Dockerfile.j2`). Installing *a* TeX
Live on the build host is not equivalent — a version difference shows up as a
construction check and a verifier disagreeing about a paper that is fine, or
worse, agreeing about one that is not. The build host therefore runs the same
image, exposed through thin shims so that `pdflatex` on `PATH` is the
verifier's `pdflatex`:

```sh
docker build -t lspr-tex:24.04 -f <the TeX layer of tests.Dockerfile.j2> .
# ~/bin/lspr-tex-tool, symlinked to as pdflatex, bibtex, kpsewhich, pdfinfo, ...
exec docker run --rm --network none -u "$(id -u):$(id -g)" \
    -v /home/user:/home/user -v /tmp:/tmp -w "$PWD" -e HOME=/tmp \
    -e TEXINPUTS -e BSTINPUTS -e BIBINPUTS \
    lspr-tex:24.04 "$(basename "$0")" "$@"
```

`--network none` mirrors the verifier's sandbox, so a document that quietly
needs to download something fails during construction rather than at
evaluation time. The shims serve both the Python gate and the agent's own
compile attempts, which is the point: the agent iterates against the same
compiler that will judge the result.

## Harbor wrapping (Phase 2)

Unchanged from the plan, and deliberately boring:

```bash
paperbench-harbor lifesci-paperrecon \
    --source .cache/lifesci-paperrecon/corpus \
    --output-dir datasets/lifesci-paperrecon-short \
    --upstream-revision <construction-pipeline git revision> \
    --overview short
```

This calls `convert_paperwrite_bench` with a config from
`adapters/lifesci_paperrecon/harbor.py`. The converter itself has **no**
biology-specific logic; the only thing that changed to support a second corpus
was turning previously-hardcoded identity metadata into parameters
(`benchmark`, `task_id_prefix`, `category`, `tags`, `relevant_experience`,
`agents_md_dir`, `include_official_grader`), with defaults that reproduce
PaperWrite-Bench byte-for-byte. `tests/test_lifesci_paperrecon_converter.py`
pins both halves of that: the biology output *and* the unchanged defaults.

`include_official_grader=False`: the pilot ships the Layer-1 binary smoke check
only. There is no upstream evaluator to reproduce here, and fabricating an
`eval_points.json` rubric would be worse than shipping none — see
`docs/lifesci-paperrecon.md` for the two-layer verification architecture and
why Phase 3 is deferred to an external review agent.

## Licensing

Two separate licenses per sample. They are **not** treated the same way, and
the asymmetry is deliberate.

- **The paper — enforced, blocking.** Derived material (overviews, template,
  extracted figures) is redistributed, so only `CC BY 4.0`, `CC BY-NC 4.0`,
  `CC BY-SA 4.0` and `CC0 1.0` qualify. arXiv's default perpetual
  non-exclusive license does not. A paper failing this stops the build.
- **The code repository — recorded, advisory.** `resources/code/` is
  redistributed verbatim inside every Harbor task's build context. Since
  2026-08-31, a repository with no license file does **not** block
  construction (owner decision): the agent records what it finds in
  `provenance.json`'s `code_license` — `"none declared"` is a valid answer —
  and carries on.

Because nothing blocks on the code license any more, the only remaining
guarantee is that the finding is *written down*. `code_license` is therefore a
**required** provenance field, enforced by `validate.py`: it may say anything,
but it may not be absent. A silently-missing field would make an unlicensed
repository indistinguishable from a licensed one by the time Phase 5 writes
the dataset card.

What that means in practice, so it is not a surprise later: an unlicensed
public GitHub repository is not automatically redistributable — absent a
license, default copyright applies, and GitHub's ToS grants viewing and
forking on GitHub rather than redistribution elsewhere. Two of the three pilot
samples ship code in that state, with the owner's explicit sign-off. **Phase 5
must surface each sample's `code_license` verbatim in the dataset card** so
downstream users can make their own call per sample.

Phase 5 requires the dataset card to list each sample's arXiv ID, version and
license, plus its code repository and that repository's recorded license.

### Consequence for Phase 4 screening

Phase 0's original screening checked that a linked repository *existed* and
was described as permissive; it did not verify the repository's license, and
two of three pilot papers turned out to have none. Under the current policy
that is no longer disqualifying, so **Phase 4's re-screen does not need to
hard-require a licensed code repository** — but it should still *read*
`GET /repos/{owner}/{repo}`'s `license` field and carry it into the candidate
table, so the eventual dataset card is accurate and the pool's licensing mix
is a visible, deliberate choice rather than an unexamined one.

## Validation evidence (2026-08-31)

All three pilot papers built end-to-end on the Ubuntu build host.

- Unit tests: **73 passed** (51 pre-existing, 22 covering the gate).
- Gate: **`paper_1`, `paper_2`, `paper_3` all PASS** — `template.tex`
  compiled, the oracle-normalized `main.tex` compiled, provenance matched the
  approved selection, no leakage, all citation keys resolved.
- Fidelity/leakage audit: `{"total_tasks": 3, "passed_tasks": 3,
  "failed_tasks": 0, "determinism_ok": true}`.
- **Harbor: `lspr-0001`, `lspr-0002`, `lspr-0003` each oracle reward `1.0`,
  NOP reward `0.0`** (harbor 0.20.0, Docker).

| Task | Paper | Type | Turns | Notes |
|---|---|---|---|---|
| `lspr-0001` | BEAGLE 4.1 (2606.27607v1) | computational | 2 | agent removed a `standalone` config needing `-shell-escape` |
| `lspr-0002` | Cell differentiation / morphogenesis (2503.19375v2) | computational | 1 | agent caught a `daub2015cell`/`daub2014cell` citation-key mismatch |
| `lspr-0003` | Drug release prediction (2601.02265v1) | experimental | 1 (after a prompt fix; 3 before) | natbib/`elsarticle-num` interaction, see below |

The pipeline earned its design twice over. BEAGLE 4.1's submitted source
carries a `standalone` build configuration requiring `-shell-escape`, which
Harbor forbids; the agent found and removed it unaided. No rule in this
repository anticipates that pathology — which is the entire argument for not
writing one.

### Two prompt bugs the pilot exposed

Both were *under-specifications of a fixed contract*, not missing per-paper
rules, and both were fixed in `prompt.py` rather than by patching output:

1. **`# Title` read as a placeholder.** The gate rejected `paper_1`'s
   overview for a missing Title section; the agent had written the paper's
   title with no heading. Checking upstream's own `research_overview.md`
   showed the literal heading *is* the convention, so the check was right and
   the prompt was ambiguous. Cost: one turn.
2. **The oracle's natbib injection was undocumented.** `paper_3`
   (`\PassOptionsToPackage{numbers}{natbib}` + `\usepackage{arxiv}` +
   `\bibliographystyle{elsarticle-num}`) burned all three turns on an option
   clash, then a "Bibliography not compatible with author-year citations"
   error. Root cause: `normalize.py` injects a bare `\usepackage{natbib}`
   *immediately after `\documentclass`* — above the paper's
   `\PassOptionsToPackage` line — so natbib loaded in author-year mode against
   a numeric bibliography style. The prompt now documents every rewrite the
   oracle performs, including where the injection lands. On re-run with that
   disclosure the agent fixed it on turn 1, unaided, exactly as intended
   (literal `\usepackage{natbib}` after the options pass).

The second is worth remembering for the scale-up: numerically-cited papers
using a `*-num` bibliography style are common, so that interaction would have
recurred across the 30–50 corpus. Documenting the oracle's behaviour fixed it
once for every future paper; a regex would have fixed it for one.

## What a human still has to check

The gate proves a sample is *well-formed and solvable*. It cannot prove it is
*good*. Before this corpus is trusted:

1. **Read a generated `research_overview_short.md` against the real paper.**
   Is it sufficient to reconstruct the paper's science, and does it avoid
   handing over the paper's own sentences? This is the single highest-value
   spot check and nothing automated substitutes for it.
2. **Spot-check `figure_summary.txt` against the actual images.** The captions
   are supposed to come from looking at the figures, not from copying the
   LaTeX caption.
3. **Diff `template.tex` against `original/main.tex`.** The section skeleton
   should match the paper's real structure in order.
4. **Confirm `resources/code/` carries its license file** and contains source
   rather than bulk data.
