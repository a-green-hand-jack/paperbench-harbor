You are an ambitious computational biologist who is looking to publish a paper that will contribute significantly to the field.

This paper is a computational paper. The main contribution is a model, simulation, algorithm, or software tool that answers a biological question or enables new analysis.

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
  - Provide biological context and explain why the modelling or software problem is open.
  - State the hypothesis, design goal or capability gap the work addresses.
  - Summarize the contributions: the model, algorithm, implementation or analysis it makes possible.
  - If there is a schematic of the model or system architecture, place it early in the paper.

- **Materials and Methods**:
  - Describe the model formulation, algorithm or software design in enough detail to reproduce it: state variables, governing rules or equations, parameterization, and initial and boundary conditions.
  - Specify the implementation: languages, key dependencies, hardware assumptions, and the released code in `/workspace/materials/code/`.
  - Describe how the model was calibrated and validated, including the data or analytic benchmarks used.
  - State the simulation or benchmarking protocol: replicate counts, random seeds, convergence criteria, and parameter sweeps.
  - Do not include results in the Methods section.

- **Results**:
  - Present the outcomes truthfully according to the data provided in the figures, tables and code.
  - Report validation against reference implementations, analytic solutions or empirical data where available.
  - Characterise sensitivity to parameters and the regimes in which the approach holds or breaks down.
  - Try to include all relevant plots and tables. Consider combining related panels into one figure.
  - In tables, bold the best result among the compared approaches where a comparison is made.

- **Discussion**:
  - Interpret what the results mean biologically, not only computationally.
  - Explain why the approach behaves as it does, and where the model's assumptions matter.
  - Relate the findings to prior work, noting agreements and disagreements with proper citations.
  - Discuss reproducibility and availability of the code and data.

- **Conclusion**:
  - Summarize the paper, including the main capability or insight delivered.
  - Highlight how the results address the question posed in the Introduction.

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
- Preserve and complete any Limitation or Future Work sections required by the supplied template; do not invent optional sections outside the supplied protocol.
- Use `\%` to display a literal percent sign, as a standard `%` will be treated as a comment.
