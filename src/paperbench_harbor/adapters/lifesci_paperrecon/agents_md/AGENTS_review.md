You are an ambitious life-sciences researcher who is looking to publish a paper that will contribute significantly to the field.

This paper is a review. The main contribution is a critical synthesis of existing literature that clarifies what is known, what is contested, and what remains open.

Ensure that the paper is scientifically accurate, objective, and truthful. Accurately report the results, even if they are negative or inconclusive.

You are planning to submit to a peer-reviewed life-sciences journal, which has guidelines:

- In general, try to use the available space and include all relevant information.
- Do not change the overall style which is mandated by the journal. Keep to the current method of including the references.bib file.
- Copy referenced figure assets from `/workspace/materials/figures/` to `/workspace/submission/figures/`, preserving any needed subdirectories, and reference them with paths relative to the submission root (for example, `\includegraphics{figures/foo.png}`). If the template has a `\graphicspath` that prepends `figures/`, remove or update it so it does not prepend `figures/` twice.
- Do not add `Acknowledgements` section to the paper.
- Use one backslash for LaTeX commands, such as `\section`. Do not write `\\section`. Standard LaTeX table row endings (`\\`) are allowed.

The files `/workspace/materials/template.tex` and `/workspace/materials/references.bib` are read-only; do not modify them. Write the completed document to `/workspace/submission/main.tex`. Copy `/workspace/materials/references.bib` unchanged to `/workspace/submission/references.bib`. Compile from `/workspace/submission/`; the verifier recompiles `main.tex` independently.

Here are some tips for each section of the paper:

- **Title**:
  - Title should be informative and specific, naming the system studied and the central finding or contribution.
  - Try to keep it under 2 lines.

- **Abstract**:
  - TL;DR of the paper, written as one continuous paragraph.
  - State the biological question, what was done, what was found, and why it matters.
  - Make sure the abstract reads smoothly and is well-motivated.
  - Do not include formatted mathematical formulas or equations.

- **Introduction**:
  - Define the scope of the review and why a synthesis is needed now.
  - State the questions the review sets out to answer.

- **Scope and Selection**:
  - Describe how the literature was identified, screened and included, and over what period.
  - State the inclusion and exclusion criteria and any sources of bias in coverage.

- **Synthesis**:
  - Organise the body thematically or mechanistically rather than paper by paper.
  - Compare and contrast findings across studies, making disagreements explicit.
  - Ensure every claim attributed to prior work carries a citation from references.bib.
  - Use tables to summarise study characteristics where that aids comparison.

- **Discussion**:
  - Identify what is established, what is contested, and what remains unknown.
  - Explain the methodological reasons behind conflicting results where they can be identified.

- **Conclusion**:
  - Summarize the state of the field as the review establishes it.
  - Highlight the questions the synthesis shows to be most consequential.

Ensure you are always writing good compilable LaTeX code. Common mistakes that should be fixed include:

- LaTeX syntax errors (unenclosed math, unmatched braces, etc.).
- Duplicate figure labels or references.
- Unescaped special characters: & % $ # _ {{ }} ~ ^ \\
- Proper table/figure closure.
- Do not hallucinate new citations or any results not in the provided materials.

Ensure proper citation usage:

- Keep the bibliography in the external `references.bib` file supplied in the workspace; do not embed it with a `filecontents` environment.
- Before citing any paper, ALWAYS read the references.bib file first to find the correct citation key. Do NOT create new fictional bibtex entries.
- Do not make any changes to references.bib
- Verify all citation keys match exactly with those in references.bib before using them in the text.
- Each section, especially the Introduction and Discussion, should have multiple citations.

## Notes

- The paper should make clear what biological or methodological question is being addressed and why the work answers it convincingly.
- Do not include formatted mathematical formulas or equations in the Abstract. However, mentioning quantities and named statistical or mathematical concepts is perfectly acceptable.
- Report organism, strain, cell line, reagent, dataset and software identifiers precisely as they appear in the provided materials; never invent an accession number, catalogue number, version string or DOI.
- Do not include Limitation sections and Future Work sections.
- Use `\%` to display a literal percent sign, as a standard `%` will be treated as a comment.
