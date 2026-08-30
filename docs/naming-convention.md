# Naming convention: project brand names vs. upstream benchmark names

This project keeps two separate names for each benchmark family, and they
serve different purposes. Don't conflate them.

## The distinction

- **Upstream name** — the official name the benchmark's original authors
  gave it (e.g. "PaperWrite-Bench" is `hal-utokyo`'s name for their
  benchmark; "PaperWritingBench" is `yiwen-song`/PaperOrchestra's name for
  theirs). This name is preserved verbatim wherever traceability to the
  official upstream benchmark matters: the `benchmark` field in
  `source_manifest.json`, `task.toml` metadata, dataset directory names
  (`paperwrite-bench-short/`, `paperwritingbench-sparse-plotoff/`), task ID
  prefixes (`pwb-####`, `pwbw-####`), and the already-published Hugging Face
  dataset structure (`Jack-Jieke-Wu/Paper-Writing-Exam`). **None of these
  code-level identifiers change** — renaming them would break the fidelity
  documentation's whole point (same name as upstream = easy to verify this
  is the same benchmark) and would be a breaking change to the published
  `v0.2.0` dataset revision.
- **Project brand name** — a paperbench-harbor-specific name used in
  narrative documentation (READMEs, plans, survey docs, presentations) to
  give each benchmark family a name that fits a consistent house style
  across all three families, since a from-scratch benchmark like
  LifeSci-PaperRecon has no upstream name to inherit in the first place.

## Current mapping (confirmed 2026-08-30)

| Project brand name | Upstream name (unchanged in code/metadata) | Domain | Recipe / methodology |
|---|---|---|---|
| **AI-PaperRecon** | PaperWrite-Bench | ML/AI | PaperRecon (single overview → reconstruction) |
| **AI-PaperOrchestra** | PaperWritingBench | ML/AI | PaperOrchestra (multi-agent idea/log → paper) |
| **LifeSci-PaperRecon** | *(none — project-original)* | Biology / life sciences | PaperRecon-style (cloned from AI-PaperRecon's recipe) |

Pattern: `<Domain>-<Methodology>`. The `AI-` pair shares a domain prefix but
stays distinguishable by methodology suffix (`PaperRecon` vs
`PaperOrchestra`); `LifeSci-PaperRecon` reuses the `PaperRecon` suffix
because it deliberately clones that recipe rather than PaperOrchestra's.

## Where to use which name

- Code, file paths, dataset directories, task IDs, `source_manifest.json`,
  `task.toml` `relevant_experience`/`tags` fields referencing the upstream
  benchmark, Hugging Face repo/config names: **upstream name** (or, for
  LifeSci-PaperRecon, its own name since there's no upstream one).
- README prose, plan documents, survey documents, issue write-ups, anything
  explaining "the three benchmark families in this project" to a reader who
  doesn't need the upstream paper citation in that sentence: **project
  brand name**, with the upstream name given in parentheses on first mention
  per section, e.g. "AI-PaperRecon (upstream: PaperWrite-Bench)".

## The construction agent: PaperSmith (confirmed 2026-08-30)

This is a separate naming axis from the benchmark-family table above — it
names a *role*, not a benchmark. **PaperSmith** is the project's name for the
`opencode`-driven construction agent that builds LifeSci-PaperRecon's corpus:
per paper, an `opencode` CLI session (see
`src/paperbench_harbor/construction/lifesci_paperrecon/`) that fetches the
source, performs LaTeX surgery, converts bibliographies, captions figures,
and authors the biology-adapted overview — the thing that replaced the
abandoned fixed-Python-script pipeline. Use "PaperSmith" in narrative prose
when referring to this agent/workflow generically (e.g. "PaperSmith
discovered the `standalone` shell-escape issue on its own"); the underlying
invocation (`opencode run --model ... --auto --dir ...`) and module names in
code are unaffected by this naming — it's a documentation convenience, not a
new code identifier to introduce everywhere.
