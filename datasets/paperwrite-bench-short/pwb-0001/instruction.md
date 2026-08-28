# Paper reconstruction task

Write a complete scientific paper from the research materials in `/workspace/materials`.

## Available material

- `research_overview.md` describes the research question, method, evaluation, and findings.
- `paper_template.tex` provides the required LaTeX document structure.
- `references.bib` contains the bibliography entries available for citation.

## Requirements

1. Use the supplied template as the basis for the paper.
2. Write an abstract, introduction, method, experiment, results, related work, and conclusion.
3. State only claims supported by the provided research overview.
4. Preserve BibTeX citation keys from the provided bibliography.
5. Do not use the network or introduce external source material.
6. Compile the paper successfully with `pdflatex` and `bibtex`.

## Submission contract

Place your final artifacts in `/workspace/submission`:

```text
/workspace/submission/
├── main.tex
├── references.bib
└── final.pdf
```

`main.tex` is authoritative. The verifier recompiles it in a separate sandbox; a submitted PDF does not replace successful recompilation.
