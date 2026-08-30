# Survey: Paper-Writing-Agent Benchmarks (Non-ML/AI Coverage)

Tracks [issue #2](https://github.com/a-green-hand-jack/paperbench-harbor/issues/2) — "Survey & Harbor-wrap public paper-writing benchmarks (add non-ML/AI coverage)". Covers deliverables 1 and 2: a catalog of candidate benchmarks with an in-scope/out-of-scope classification, and a shortlist assessment. Research conducted 2026-08-30.

## Scope recap

A qualifying benchmark must be:

- A public, downloadable, **fixed** dataset (not a live agent framework that generates its own tasks).
- Graded solely on the produced **manuscript**, by a **pure writing agent** — no code execution, no experiment running, no hypothesis derivation as part of the graded task.
- Driven by **pre-existing research materials** supplied to the agent (idea, experimental log, figures, overview, references) — not materials the agent must derive itself (including via its own literature retrieval).
- Wrappable in Harbor with **full fidelity** to the official benchmark: same samples, same input protocol, same ground truth, same evaluator.

The project already has ML/AI-only coverage (`PaperWrite-Bench`, `PaperWritingBench`). This survey looks for benchmarks that extend coverage into non-ML/AI domains, and separately verified two carried-over candidates from the original issue triage (SurveyEval, MLR-Bench).

## Catalog

| Name | Link | License | Domain(s) | Samples | Input protocol | Evaluator | Data availability | Verdict |
|---|---|---|---|---|---|---|---|---|
| **SurveyEval** | [arXiv:2512.02763](https://arxiv.org/abs/2512.02763) | Unstated (no artifact found) | 7 nominal subjects (CS + Astronomy/Biology/Chemistry/Geography/Aerospace/Physics), but 20/38 topics are CS/LLM topics reused from SurveyX | 38 topics (20 CS + 18 STEM, 3 per non-CS subject) | Topic-title only; every system performs its own web retrieval | LLM-as-judge (Overall/Outline/Reference tracks), narratively described, no released code/prompts | **No public dataset or code found anywhere** (arXiv, GitHub, HF, Papers-with-Code all checked) | ❌ Out of scope |
| **MLR-Bench** | [arXiv:2505.19955](https://arxiv.org/abs/2505.19955) · [GitHub](https://github.com/chchenhui/mlrbench) · [HF](https://huggingface.co/datasets/chchenhui/mlrbench-tasks) | MIT | ML/AI only (ICLR/ICML/NeurIPS workshops) | 201 tasks (idea/proposal); 10-task subset for writing/experimentation | Writing stage's official input is always an **agent-generated** experiment report sampled from a prior pipeline run — no fixed/ground-truth input exists | MLR-Judge, LLM rubric per stage, code released (MIT) | Task list on HF; no released ground-truth experiment logs | ❌ Out of scope — no fixed writing-stage ground truth to preserve; also ML/AI-only |
| **SurveyGen** | [arXiv:2508.17647](https://arxiv.org/abs/2508.17647) · [GitHub](https://github.com/tongbao96/SurveyGen) | Data: CC BY-NC 4.0; Code: Apache-2.0 | Mixed corpus incl. **Medicine, Biology, Psychology** + CS | 4,205 surveys (full corpus); 120-survey subset (30/domain) in the paper's main experiments | 3 task variants: (1) topic-only, (2) topic+RAG, (3) **human-guided — fixed gold outline + pre-selected references supplied, no retrieval** | Automatic (semantic similarity, ROUGE-L, Key-Point-Recall, structural/citation metrics) + human eval on a CS subset | Code + dataset released via GitHub → Google Drive | ⚠️ **Conditionally in scope** — best candidate found. Task 3 alone matches the required form; needs verification that the full 4,205-survey corpus (not just the 120-sample subset) has non-CS outline/reference annotations at scale |
| **SurveyLens** | [arXiv:2602.11238](https://arxiv.org/abs/2602.11238) · [GitHub](https://github.com/TechnicolorGUO/SurveyLens) | Data: non-commercial academic use only; code license unspecified | 10 disciplines incl. **Medicine, Biology, Sociology, Physics, Psychology**, Environmental Science, Education, Engineering, Business + CS | 1,000 human surveys (100/discipline) | Topic-string only; every system (incl. Deep Research agents) must self-retrieve literature; no oracle-materials condition | Dual rubric: discipline-aware LLM-judge + reference-alignment | Dataset via Google Drive; MIT code | ❌ Out of scope — widest domain breadth found, but no supplied-materials task variant exists |
| **HiSciBench** | [arXiv:2512.22899](https://arxiv.org/abs/2512.22899) | Not yet released | Math, Physics, Chemistry, Biology, Geography, Astronomy | 8,735 instances across 5 hierarchical levels | Level 4 ("Literature Review Generation") is embedded in a QA/parsing/discovery battery, not a standalone manuscript task | LLM/automatic scoring per level | Not yet released, no repo link | ❌ Out of scope — not a dedicated writing benchmark; unreleased |
| **Denario** | [arXiv:2510.26887](https://arxiv.org/abs/2510.26887) | N/A (system) | Astrophysics, Biology, Biophysics, Chemistry, Materials Science, Medicine, Neuroscience, Planetary Science | N/A — case studies | Full pipeline: idea → lit check → **writes and executes code** → plots → draft | Human expert review | Not a static benchmark | ❌ Out of scope — live pipeline, same failure mode as AI Scientist |
| **data-to-paper** | [arXiv:2404.17605](https://arxiv.org/abs/2404.17605) | N/A (framework) | Domain-agnostic demo | N/A | Agent raises hypotheses, **writes/runs code**, then writes paper | Traceability-based, not ground-truth comparison | No fixed dataset | ❌ Out of scope — live pipeline, requires code execution |
| **Prompt-to-Paper** (bioinformatics) | [arXiv:2607.05456](https://arxiv.org/abs/2607.05456) | Not confirmed | Bioinformatics | Not a fixed benchmark | Autonomous coding agent **executes real computational biology experiments** | Not confirmed | Not confirmed | ❌ Out of scope — runs experiments as part of the task |
| **FinRpt** (equity research reports) | [arXiv:2511.07322](https://arxiv.org/abs/2511.07322) (AAAI 2026) | Not confirmed | Finance/Economics | Not stated in abstract | Built from 7 types of financial filings; multi-agent generator trained via SFT+RL | 11 automatic metrics | Claimed public, not confirmed | ⚠️ **Unresolved** — genuine non-ML/AI domain, but unclear from the abstract whether report writing requires deriving/computing figures from raw filings (would fail the "pre-existing materials" criterion) or works from already-extracted structured facts. Needs a full-paper read before ruling in or out |
| **SurGE** | [arXiv:2508.15658](https://arxiv.org/abs/2508.15658) | Not confirmed | CS only | Not stated (1M+ paper corpus) | Topic description input | Not confirmed | Not confirmed | ❌ Out of scope — wrong domain |
| SurveyEval-adjacent CS-only sets: DeepSurvey-Bench, SGSimEval, STRUCTSURVEY, TaxoAlign/CS-TaxoBench, Survey-Arena, DAS-Bench | Various arXiv | — | CS/general, domain unspecified or CS-confirmed | — | — | — | — | ❌ Out of scope — CS-focused |
| PaperBench, AI Scientist v1/v2, PRBench, ReplicatorBench, ScienceAgentBench, ResearchBench, SciAgentArena, MedAgentBench, ChemBench, SciAssess | (original issue triage) | — | Various | — | Require experiment execution / code / hypothesis discovery | — | — | ❌ Out of scope — research-agent benchmarks, documented in the original issue |

## Shortlist assessment

No candidate is a clean, ready-to-wrap match. Two are worth further diligence before falling back to a from-scratch build:

1. **SurveyGen — Task 3 (human-guided) protocol.** The only found benchmark with a task variant that hands the agent a fixed outline + pre-selected reference set (no retrieval) and grades only the produced prose, with genuine non-CS coverage (Medicine, Biology, Psychology). Before shortlisting for a Harbor smoke conversion:
   - Confirm the full 4,205-survey corpus (not just the 120-survey / 30-per-domain subset used in the paper's experiments) has outline + reference annotations for enough non-CS samples to be worth a dedicated Harbor protocol.
   - Confirm the CC BY-NC 4.0 data license is compatible with the project's redistribution needs (non-commercial only — check how this interacts with the project's existing licensing posture, since PaperWrite-Bench explicitly filters out non-redistributable sources).
   - Confirm the released evaluator code/rubric prompts can be reused verbatim, per project fidelity requirements.

2. **FinRpt.** Genuine non-ML/AI domain (finance), fixed dataset claimed, but the abstract doesn't resolve whether the graded task requires deriving figures from raw filings (disqualifying) versus writing from pre-extracted structured facts (qualifying). Needs a full-paper read.

## Known gap

**No public benchmark currently satisfies all four scope criteria in a non-ML/AI domain.** The closest near-miss (SurveyGen Task 3) requires isolating one protocol variant out of a multi-task paper and verifying corpus scale before it can be trusted as a faithful, full-fidelity wrap. Per the issue's fallback plan, the project is proceeding to design a **from-scratch non-ML/AI benchmark**, following the construction recipe extracted from PaperWrite-Bench and PaperWritingBench (see below), while SurveyGen/FinRpt remain open follow-up items rather than closed leads.

## Construction recipe extracted from PaperWrite-Bench and PaperWritingBench

Full detail from primary sources (papers + repos) is in the research notes; summarized here for reuse.

### PaperWrite-Bench (source: arXiv:2604.01128, `Agent4Science-UTokyo/PaperRecon`, `hal-utokyo/PaperWrite-Bench`)

1. **Source selection**: 51 papers manually curated by the authors, all published after 2025 (ACL/EMNLP/CVPR/ICCV/ICLR/NeurIPS/ACMMM), chosen to postdate benchmarks built on ~2024 papers and reduce memorization risk. Only exclusion rule: drop repos whose license explicitly prohibits redistribution.
2. **Input derivation**: LLM-generated (GPT-5) `research_overview` in short (~463 words) and long (~1,492 words) variants, from a fixed prompt template with a defined section skeleton and character budget — human-reviewed for reconstructability. Figures/tables kept as originals with simplified captions. **References reused verbatim from the original paper** (not reconstructed), to isolate writing skill from retrieval skill. Section-heading-only LaTeX template extracted from the arXiv source. Optional original codebase included (readme's abstract/intro stripped).
3. **Ground truth & scoring**: per-paper rubric (`eval_points.json`, LLM-drafted + human-reviewed) scored 1–5 by an LLM judge per matched section (7-category taxonomy: Abstract/Intro/Related Work/Method/Benchmark Construction/Experiment/Conclusion); two-stage hallucination detection (LLM claim extraction + coding-agent re-verification against GT code/LaTeX); citation precision/recall/F1. Human validation: Kendall τb = 0.578 against expert judgment. Judge prompts and evaluation code are public.
4. **Licensing**: no blanket redistribution license claimed; defers to each source paper's own license, with an explicit exclusion policy for non-redistributable sources.

### PaperWritingBench (source: arXiv:2604.05018, `google-research/paper-orchestra`, `yiwen-song/PaperWritingBench`)

1. **Source selection**: 200 papers, 100 CVPR 2025 + 100 ICLR 2025, randomly sampled from OpenReview/CVF for topic diversity; only quality filter is discarding mis-parsed samples.
2. **Input derivation**: PDFs parsed via MinerU + PDFFigures 2.0; an LLM (Gemini) reverse-engineers a fully anonymized (no authors/titles/citations/figure-refs) **Idea Summary** (Sparse vs Dense variants) and **Experimental Log**, paired with the venue's official LaTeX template and guidelines. Figures are optional writer input — "PlotOff" (GT figures supplied) vs "PlotOn" (agent's own Plotting Agent generates visuals) is an *evaluation-stage* ablation, not an input-stage one.
3. **Ground truth & scoring**: four separate LLM-as-judge evaluators (citation F1 against P0/P1-partitioned references, literature-review-quality rubric, overall/technical quality via reused reviewer frameworks — AI Scientist-v2 Reviewer and ScholarPeer, and pairwise side-by-side comparison). Human validation: 11 researchers, 180 paired evaluations, Pearson r = 0.6458 vs. GPT-5 autorater.
4. **Licensing**: Apache-2.0 for code and dataset; notably **no stated policy** on copyright/redistribution of the underlying CVPR/ICLR paper content (a gap relative to PaperWrite-Bench).

### What breaks when porting this recipe to a non-ML/AI domain

1. **Section taxonomy is CS/ML-shaped** — the fixed 7-category classifier (with "Benchmark Construction" as a first-class category) assumes ML-conference structure; a biology (Materials & Methods / Results / Discussion) or physics (Theory / Derivation / Numerical Results) paper needs a different ontology and matching rules.
2. **LaTeX-template dependency is CS-conference-specific** — both benchmarks extract an official LaTeX template as a required input; many non-CS venues publish in Word/journal-typeset form with no standardized author-supplied class file.
3. **Figure/table semantics assume ML visual conventions** — training curves, architecture diagrams, bar charts. Biology (micrographs, gels, phylogenies), physics (apparatus schematics, phase diagrams), and social-science (survey instruments, maps) figures need different captioning and rubric anchors.
4. **Code-as-ground-truth doesn't generalize** — PaperWrite-Bench uses the original codebase both as writer input and as the grounding corpus for hallucination-stage verification by a coding agent. Most non-CS empirical fields have no comparable code artifact.
5. **Citation infrastructure assumes Semantic Scholar coverage** — strong for CS/ML, materially weaker elsewhere; may need OpenAlex/CrossRef instead, with different metadata fields.
6. **Anti-leakage recency thresholds need per-field recalibration** — "published after 2025" / CVPR-ICLR-deadline cutoffs were chosen to counter memorization of *famous ML papers*; a different field's memorization risk profile may not follow the same rule.
7. **Rubric-generation prompts are written for ML papers** — templates like "Proposed Method" / "Experimental Results" / "Benchmark Design" need domain-specific rewrites (e.g., "Hypothesis" / "Experimental Design" / "Statistical Analysis" / "Biological Significance"), each requiring its own human-correlation validation — the published τb = 0.578 correlation was measured only on ML papers.

Not publicly documented and not inferred: PaperWrite-Bench's full annotator qualification process beyond "reviewers with top-tier conference reviewing experience"; PaperWritingBench's exact Gemini extraction prompts (referenced as living in an appendix not fully captured during this research pass).

## Next steps

- [ ] Deep-dive SurveyGen's full corpus (Google Drive) to confirm non-CS Task-3 scale, and re-check its CC BY-NC 4.0 license against project redistribution needs.
- [ ] Read the full FinRpt paper to resolve whether report generation requires deriving figures from raw filings.
- [ ] Design and scope a from-scratch non-ML/AI benchmark, adapting the PaperWrite-Bench/PaperWritingBench recipe with the domain-specific adjustments listed above (domain choice TBD).
