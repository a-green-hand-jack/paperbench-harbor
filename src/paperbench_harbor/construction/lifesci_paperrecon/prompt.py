"""The specification handed to the opencode construction agent.

This module is deliberately the largest thing in the package, because in this
design the prompt *is* the pipeline. The earlier fixed-script approach encoded
"how to build a paper" in Python and broke on the first paper whose LaTeX did
something unanticipated; here Python encodes only the **contract** and the
**failure signal**, and the agent decides how to satisfy them.

Two consequences shape everything below:

* **Say what, not how.** Failure modes are not pre-enumerated. Telling the
  agent "watch out for `\\standaloneconfig`" would just be the old regex library
  written in English, and would not help with the next paper's unrelated
  pathology. The prompt states the invariant ("it must compile with these
  exact flags") and lets the agent discover and fix whatever violates it.
* **Every fact is to be re-verified, not trusted.** The prompt carries the
  approved selection as *expectations to check against the live source*, and
  says explicitly that a mismatch means stop, never substitute. The validation
  gate enforces the same thing from the outside.
"""

from __future__ import annotations

from paperbench_harbor.adapters.paperwrite_bench.converter import OVERVIEW_FILENAMES
from paperbench_harbor.construction.lifesci_paperrecon.papers import (
    ACCEPTED_LICENSES,
    PaperSpec,
)
from paperbench_harbor.construction.lifesci_paperrecon.validate import ValidationReport

#: Flags reproduced verbatim from `common/templates/test_state.py.j2`. The
#: agent is given the literal command line rather than a description of it so
#: it can run exactly what the verifier will run.
VERIFIER_COMPILE_SEQUENCE = """\
pdflatex -interaction=nonstopmode -halt-on-error -no-shell-escape main.tex
pdflatex -interaction=nonstopmode -halt-on-error -no-shell-escape main.tex
bibtex main
pdflatex -interaction=nonstopmode -halt-on-error -no-shell-escape main.tex
pdflatex -interaction=nonstopmode -halt-on-error -no-shell-escape main.tex"""


def build_prompt(spec: PaperSpec, output_dir: str) -> str:
    """The full construction task for one paper."""

    short = OVERVIEW_FILENAMES["short"]
    long = OVERVIEW_FILENAMES["long"]
    licenses = ", ".join(f"`{name}`" for name in ACCEPTED_LICENSES)

    return f"""\
You are building one sample of **LifeSci-PaperRecon**, a benchmark that asks a
writing agent to reconstruct a life-sciences research paper from a research
overview plus the study's own figures, tables, bibliography and code. Your job
is to turn one published arXiv paper into that sample. You are not writing a
paper; you are preparing source material.

Work autonomously. Fetch what you need, inspect it, and fix whatever does not
fit. Nothing below tells you which LaTeX problems this paper has, because every
paper has different ones — find them yourself by compiling.

# The paper

- arXiv ID: `{spec.arxiv_id}` version `{spec.expected_version}`
- Abstract page: {spec.arxiv_abs_url}
- Source bundle (LaTeX): {spec.arxiv_eprint_url}
- Code repository: {spec.code_repo}
- Expected arXiv category: `{spec.expected_category}`
- Expected license: `{spec.expected_license}`
- Assigned paper type: `{spec.paper_type}`
- Note: {spec.note}

**Every expectation above is unverified.** Check each one against the live
arXiv abstract page and the live repository before you build anything.

# Stop conditions — do not work around these

If any of the following is true, **stop immediately**. Write your finding to
`{output_dir}/original/provenance.json` with a top-level `"blocked"` key
explaining what you found, build nothing else, and end your run.

1. The license on the live arXiv page is not one of: {licenses}.
   (This benchmark redistributes material derived from the paper, so a
   non-permissive license disqualifies it outright.)
2. The submission has no LaTeX source — an e-print bundle that is a PDF only.
3. The code repository is gone, private, or cannot be checked out.
4. The arXiv ID, version or category does not match the expectations above.

The code repository's *license* is **not** a stop condition. Record whatever
you find in `provenance.json`'s `code_license` — including `"none declared"`
when the repository has no license file and the GitHub API reports
`license: null` — and carry on building. Report it accurately; do not guess a
license, and do not infer one from the paper's own license.

Do **not** substitute a different paper, a different version, or a different
repository. The selection was a human decision; a blocked paper goes back to a
human, it does not get replaced by you.

# What to produce

Create exactly this tree under `{output_dir}` (absolute path; create it):

```
{output_dir}/
├── original/            <- GROUND TRUTH. Never shown to the writing agent.
│   ├── main.tex
│   ├── main.pdf
│   ├── config.yaml
│   └── provenance.json
└── resources/           <- PUBLIC. Copied verbatim into the writer's workspace.
    ├── template.tex
    ├── {short}
    ├── {long}
    ├── references.bib
    ├── figure_summary.txt
    ├── table_summary.txt
    ├── figures/
    ├── tables/          (omit if the paper has no tables as separate assets)
    └── code/
```

## The leakage rule

`resources/` is handed to the writing agent verbatim. `original/` is not. So
`resources/` must contain **no** file named `main.tex`, `main.pdf`,
`config.yaml`, `provenance.json`, `eval_points.json` or `source_manifest.json`
anywhere in its tree (the sole exception is inside `resources/code/`, which is
a verbatim third-party checkout). More importantly, nothing in `resources/`
outside the figures, tables, bibliography and overviews may contain the
paper's prose — that is the answer.

## `original/main.tex` and `original/main.pdf`

`main.tex` is the paper's ground-truth LaTeX. If the arXiv bundle splits the
body across `\\input`/`\\include` files, you may either keep those files
alongside it in `original/` or inline them — but the result must compile (see
below). `main.pdf` is the paper's compiled PDF; the arXiv PDF is fine.

## `original/config.yaml`

Plain `key: value` lines, no nesting:

```
type: {spec.paper_type}
num_page: <integer page count of the ground-truth PDF>
column: <1column or 2column, matching the paper's actual layout>
conference: arXiv {spec.expected_category}
```

`type` must be exactly `{spec.paper_type}` — it selects which writing
instructions the benchmark hands the writing agent, and it is a human
decision, not yours.

## `original/provenance.json`

A single JSON object recording what you actually observed, not what this
prompt claims:

```json
{{
  "title": "...",
  "arxiv_id": "{spec.arxiv_id}",
  "arxiv_version": "{spec.expected_version}",
  "arxiv_category": "{spec.expected_category}",
  "license_label": "...",
  "license_url": "...",
  "source_url": "{spec.arxiv_eprint_url}",
  "fetch_date": "<YYYY-MM-DD, the date you fetched it>",
  "code_repo": "{spec.code_repo}",
  "code_commit": "<the exact commit SHA you checked out>",
  "code_license": "...",
  "notes": "<anything a human reviewing this sample should know>"
}}
```

## `resources/template.tex`

The paper's section skeleton, and the writing agent's starting point. Take
`main.tex` and remove the body: keep the preamble, `\\begin{{document}}`, the
title/author block if the paper's class needs one, every
`\\section`/`\\subsection` heading in its original order, the
`\\bibliographystyle`/`\\bibliography` lines, and `\\end{{document}}`. Remove
all prose, all figures and tables, and all `\\cite` commands — a citation is
part of the answer.

**`template.tex` must compile on its own**, from a copy of `resources/` alone,
using exactly:

```
pdflatex -interaction=nonstopmode -halt-on-error -no-shell-escape template.tex
```

with no network access. Verify this yourself before you finish.

## `resources/{short}` and `resources/{long}`

Markdown, written by you from the paper, using this skeleton — the benchmark
is life-sciences, so it is deliberately not the ML-shaped
motivation/method/contributions one:

```
# Title

<the paper's actual title>

## Research Question or Hypothesis
## Approach
## Key Findings
## Biological Significance
## Takeaway
```

`Title` is a literal heading with the paper's real title underneath it, not a
placeholder to replace — this matches the overview format the writing agent is
already trained against in the sibling benchmarks. Every other heading is
literal too, spelled as shown.

This is the **only** description of the study the writing agent receives, so
it must be sufficient to reconstruct the paper's scientific content — and it
must not be the paper. Write the science, not the sentences: state what was
asked, what was done, what came out (with the actual quantitative results,
effect sizes, model parameters and organism/dataset identifiers a reader would
need), and why it matters biologically. Do not include LaTeX. Do not name
section headings from the paper. Do not include citations.

Aim for roughly 1,500-4,000 characters for the short variant and 6,000-15,000
for the long one; the long variant must carry strictly more detail, not the
same content restated.

## `resources/references.bib`

The paper's own bibliography, reused verbatim so the writing agent is doing
writing rather than literature retrieval. If the arXiv bundle ships a `.bib`,
use it as-is. If it ships only a `.bbl` or inline `\\bibitem`s, convert them
into real BibTeX entries, **preserving the original citation keys exactly** so
the ground truth's `\\cite` commands still resolve.

Every key cited anywhere in `original/main.tex` must be defined here. Never
invent an entry to satisfy a citation — if a key has no source, find the real
reference.

## `resources/figures/` and `resources/tables/`

Every figure asset the paper includes, in a format `pdflatex` accepts (`.pdf`,
`.png`, `.jpg`, `.eps`). Tables that exist as separate `\\input` files go in
`tables/`; tables written inline in `main.tex` do not need extracting.

## `resources/figure_summary.txt` and `resources/table_summary.txt`

One caption per asset, keyed by filename, e.g.:

```
figures/fig2a.png: Dose-response curves for ... The x-axis is ...
```

Write these by **looking at the images** and reading how the paper uses them,
not by copying the LaTeX caption verbatim — the writing agent has to be able to
decide where each asset belongs and what it shows. Describe what is actually
plotted or depicted: axes and units, conditions compared, what the panel
demonstrates. This is a life-sciences corpus, so expect micrographs, gels,
phylogenetic trees, pathway diagrams and dose-response curves rather than
training curves and architecture diagrams.

Every file in `figures/` must be mentioned by name in `figure_summary.txt`, and
likewise for tables. If the paper has no separate table assets, say so
explicitly in `table_summary.txt` rather than leaving it empty.

## `resources/code/`

A checkout of {spec.code_repo}. Record the exact commit in `provenance.json`.
Remove `.git/` and any large data artefacts that are not source; keep the
analysis/simulation code, its README, and its license file if it has one.
Record the repository's license in `provenance.json`'s `code_license` exactly
as you find it — `"none declared"` is a valid and expected answer, and is not
a reason to stop.

# The hard requirement: the oracle must compile

The benchmark's verifier recompiles the submission in a clean, network-free
copy with:

```
{VERIFIER_COMPILE_SEQUENCE}
```

and asserts every `\\cite` key resolves in `references.bib`. Separately, the
benchmark's *oracle* proves each task is solvable by taking
`original/main.tex`, rewriting `\\bibliography{{...}}` to
`\\bibliography{{references}}`, resolving every `\\includegraphics` and
`\\input` against the **public** `resources/` tree, and compiling the result
with those same flags.

Two things follow, and they are where real papers usually fail:

1. **No shell-escape, no network, no external tooling.** Anything in the
   preamble that needs `-shell-escape`, downloads something, or shells out
   will fail. Rewrite it so the document compiles without it.
2. **Every asset `main.tex` references must be findable in `resources/`** under
   a name the reference resolves to, and the reference path must still work
   when the file sits next to `main.tex` in a flat submission directory. If
   `main.tex` uses `\\graphicspath`, make sure it is consistent with the paths
   in its `\\includegraphics` calls and with `figures/` — a `\\graphicspath`
   that prepends `figures/` to a reference that already says `figures/` is a
   silent failure.

## The oracle rewrites your `main.tex` before compiling it

This is fixed, documented behaviour, not something to discover by trial. The
oracle applies these edits to a copy of `original/main.tex`:

- `\\bibliography{{anything}}` becomes `\\bibliography{{references}}`.
- Every `\\includegraphics`/`\\input` reference is resolved against the public
  materials; **an unresolvable reference is deleted from the document.** If a
  figure vanishes from the oracle's PDF, that is why.
- Citation keys are matched case-insensitively against `references.bib`, and
  any still-missing key is appended as a synthetic `@misc` stub.
- **If the document uses `\\citep`/`\\citet` and does not contain the exact
  literal string `\\usepackage{{natbib}}`, a bare `\\usepackage{{natbib}}` is
  injected immediately after `\\documentclass`.**

That last one bites when the paper's own class or style file already loads
natbib with options (many arXiv/journal styles do): the injected bare copy
plus the style's optioned copy is an "Option clash for package natbib" and the
build dies. The fix is to make `main.tex` contain the literal
`\\usepackage{{natbib}}` itself, placed *after* whatever style file loads
natbib, so the oracle sees it and injects nothing. Do not try to suppress the
style's own natbib with an option it does not define.

Note where the injection lands: **immediately after `\\documentclass`**, ahead
of everything else in your preamble. So `\\PassOptionsToPackage{{numbers}}{{natbib}}`
is *not* enough on its own — the oracle's bare `\\usepackage{{natbib}}` is
inserted above it, natbib loads in author-year mode before your options are
passed, and a numeric bibliography style such as `elsarticle-num` or
`unsrtnat` then fails with "Bibliography not compatible with author-year
citations". For a numerically-cited paper you need the literal
`\\usepackage{{natbib}}` present *and* numeric mode selected in a way that
survives — passing the option before that literal load, or
`\\setcitestyle{{numbers}}` after it.

Check both documents yourself: compile `template.tex` from a copy of
`resources/`, and compile `main.tex` from a directory containing only
`main.tex`, its `references.bib` and its referenced assets. Iterate until both
succeed. Do not report success on a paper you have not compiled.

# Working notes

- `pdflatex` and `bibtex` are available and run the same TeX Live the verifier
  uses. Use them; do not reason about whether something compiles.
- You have network access for fetching. The compiled documents must not need
  it.
- Work inside `{output_dir}` and its parent. Do not write anywhere else.
- When you are done, print a short summary: the license you verified, the
  commit you checked out, the page count, and confirmation that both documents
  compiled.
"""


def build_retry_prompt(spec: PaperSpec, report: ValidationReport, output_dir: str) -> str:
    """A follow-up turn driven by the validation gate's own findings.

    Feeding the machine-checked failure back is the designed response to a
    rejected build. Hand-patching the output instead would reintroduce exactly
    the per-paper rule library this design exists to avoid.
    """

    return f"""\
The sample you built for arXiv {spec.arxiv_id}{spec.expected_version} at
`{output_dir}` was rejected by the benchmark's automated contract check. The
findings below are machine-generated from the same code that gates the corpus,
so they are exact.

{report.agent_feedback()}

Fix the underlying cause in `{output_dir}` and re-verify. Specifically:

- Do not work around a compilation failure by deleting the content that fails;
  the ground truth has to stay faithful to the published paper.
- Do not satisfy a citation check by inventing a bibliography entry.
- Re-run the compilations yourself before finishing: `template.tex` from a copy
  of `resources/`, and `main.tex` from a directory holding only itself, its
  `references.bib` and its referenced assets, both with
  `pdflatex -interaction=nonstopmode -halt-on-error -no-shell-escape`.

If a finding is wrong or impossible to satisfy without misrepresenting the
paper, do not force it: say so clearly in your final message and leave the
sample as it is, so a human can decide.
"""
