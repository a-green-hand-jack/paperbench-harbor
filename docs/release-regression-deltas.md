# v0.3.1 Regeneration Deltas

This document is the GitHub-side explanation of the intentional differences
between the immutable `v0.3.1` task release and the PR #42 converter output.
The corresponding command logs, per-task audit reports, and release-bound
hashes belong with the released Hugging Face dataset card; this repository
records the rule and rationale, not a second mutable copy of the evidence.

## Baseline

The comparison uses the immutable Paper-Writing-Exam revision
`bfe2471c41f416d877e74bfa73cf0f29165c7567`. The three configurations are
regenerated from their pinned input revision and compared byte-for-byte. The
standard exclusions are deliberately visible in the command invocation:

- `tests/private/source_manifest.json`: generated provenance with the current
  source/tree digest and converter revision;
- `task.toml` and `instruction.md`: generated task contract text;
- `__pycache__/`: non-portable interpreter residue accidentally present in the
  historical release;
- `environment/materials/upstream_data_warnings.md`: explicit data-quality
  safeguard generated only when it is needed.

No exclusion is an unreviewed content change: `scripts/regress_release.py`
reports zero missing, added, and changed files after the named exclusions, and
the configuration-specific entries below identify any material correction that
needs a separate fidelity audit.

## PaperWrite-Bench

The allowed comparison covers 23,668 files, all identical. Eleven generated
`AGENTS.md` files are additionally named, rather than hidden by a broad glob:
`pwb-0003`, `0004`, `0007`, `0013`, `0014`, `0017`, `0021`, `0029`, `0034`,
`0038`, and `0040`.

Seven preserve an acknowledgement heading already required by the supplied
template. Four preserve a supplied Limitation or Future Work heading. In each
case, the converter changes only the generated instruction from a blanket
prohibition to a requirement to respect the template's existing protocol; it
does not add an optional paper section or alter an upstream input.

Four further, explicitly named templates are corrected:
`pwb-0027`, `pwb-0037`, `pwb-0044`, and `pwb-0048` under
`environment/materials/template.tex`. The historical converter commented out
the entire active line while trying to omit an unavailable graphic. The
corrected converter removes only that graphic command and leaves the surrounding
template structure active. For `pwb-0044`, that preserves the required
`\\title{...}` line. This is a task-material correctness repair verified by the
independent semantic audit, not an unreviewed exclusion.

## PaperWritingBench

The allowed comparison keeps every path outside three reviewed fidelity repairs
byte-identical to `v0.3.1`. The three additional named comparison exclusions are
`environment/materials/experimental_log.md` and
`environment/paper_orchestra/`, plus `environment/paper_orchestra_sidecar.py`,
for all 200 tasks:

- The historical converter rewrote experimental logs by escaping mathematical
  pipes, adding synthetic table headers, and padding cells with invented `NA`
  values. The corrected converter copies each log byte-for-byte from the pinned
  upstream source. The full independent material and semantic audit verifies
  that every excluded log now has the declared upstream origin rather than
  treating this exclusion as a content waiver.
- The historical writer environment shipped the complete PaperOrchestra source
  tree. It included a front-end example with a direct ground-truth-paper URL,
  evaluator code, and sample pipeline commands. The corrected environment
  ships only the sidecar's declared runtime closure: `LICENSE`, the literature
  review agent and prompt, and the Gemini, prompt, and Semantic Scholar helper
  modules. The converter regression test asserts that no CLI, evaluator, or
  front-end subtree remains writer-visible.
- The companion sidecar now imports only the credential-free Semantic Scholar
  helper at startup and defers the Gemini-backed literature agent until valid
  Gemini or Vertex credentials are deliberately supplied. This preserves the
  credential-free discovery fallback and prevents writer-visible support code
  from eagerly loading a credential-dependent integration.

The generated instruction now faithfully states the upstream PlotOff contract:
provided figures are supplied rather than newly generated, and every figure in
`info.json` must be used separately. The full isolated semantic audit is the
release gate for these content corrections.

## LifeSci-PaperRecon

The allowed comparison covers 7,068 files, all identical after the standard
generated-file exclusions plus the following reviewed corrections:

- the dataset manifest records the new pinned source snapshot;
- fifteen explicitly listed generated `AGENTS.md` files preserve headings
  required by their supplied paper templates, following the same narrow rule
  as PaperWrite-Bench;
- 19 manuscript `.tex` files embedded inside linked code checkouts are removed
  from the writer surface. They are paper source, not implementation evidence,
  and would disclose the answer; PDFs in those code checkouts remain available
  where the code uses them as evidence;
- twelve task-local `.cls` or `.bst` files are staged in `environment/texmf`
  and `tests/texmf` for `lspr-0008`, `lspr-0009`, `lspr-0016`, and `lspr-0017`.
  These files are required by the supplied template or bibliography and make
  the writer and oracle compile contracts agree.

The generic contract and instruction files change because this PR adds the
release-blocking material and format checks. They are not treated as evidence
of task-content parity; the full structural, isolation, material-completeness,
determinism, and semantic audits are the authority for that claim.

## Evidence Ownership

GitHub keeps this rationale, the converter code, and the release procedure.
The immutable Hugging Face release keeps the actual audit directory:
`summary.json`, per-task reports, semantic-review logs, source/input hashes,
and the selected reviewer model. A future release must link both immutable
revisions and must not replace the historical `v0.3.1` tree.
