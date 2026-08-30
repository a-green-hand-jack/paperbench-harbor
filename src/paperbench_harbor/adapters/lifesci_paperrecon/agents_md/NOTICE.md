# Writing instructions (LifeSci-PaperRecon)

These files are **not** upstream material. Unlike
`adapters/paperwrite_bench/agents_md/`, which holds verbatim copies of
PaperRecon's `AGENTS_<type>.md`, the files here were written for this
repository's own biology benchmark and adapt the instruction surface to
life-sciences papers:

- the section guidance follows IMRaD (Abstract / Introduction / Materials and
  Methods / Results / Discussion / Conclusion) instead of the ML-shaped
  Introduction / Method / Experiments / Analysis ordering;
- the guidance names life-science reporting conventions (organisms, reagents,
  software versions, statistical tests, reproducibility statements) instead of
  baselines, ablations and benchmark leaderboards;
- the venue framing is a life-sciences journal rather than a top-tier ML
  conference.

Everything relating to the Harbor **submission contract** — read-only
`template.tex`/`references.bib`, writing to `/workspace/submission/main.tex`,
copying `references.bib` and figure assets, compiling from
`/workspace/submission/` — is kept phrase-for-phrase identical to the
PaperWrite-Bench instructions so both benchmarks impose one contract.

Paper types map to `type:` in each sample's `config.yaml`:

- `AGENTS_computational.md` — modelling, simulation, algorithm and tool papers
- `AGENTS_experimental.md` — empirical / data-driven studies
- `AGENTS_review.md` — reviews and syntheses
