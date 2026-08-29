# Vendored upstream code

`vendor/paper_recon/` contains evaluation and support modules copied
unmodified from `Agent4Science-UTokyo/PaperRecon` (Apache-2.0). They are used
by the Harbor verifier to reproduce the official PaperWrite-Bench scoring:

- `evaluation/evaluate_per_section.py` — section classification, per-section
  rubric vs `eval_points.json`, hallucination analysis
- `evaluation/evaluate_citation.py` — citation key F1
- `evaluation/evaluate_figure.py`, `evaluation/evaluate_table.py` —
  figure/table coverage and context
- `common/llm.py` — litellm-based judge calls
- `common/config.py`, `common/log.py`, `common/coding_agent.py` — support

No modifications were made except that the code runs against a user-supplied
OpenAI-compatible judge endpoint via the standard `OPENAI_API_KEY` /
`OPENAI_API_BASE` environment variables (or the upstream `AZURE_GPT54_*`
variables), and the agentic hallucination-verification pass requires a coding
agent CLI that the verifier image does not bundle (rubric and citation modes
are fully supported).

For PaperWritingBench the same approach is used with the PaperOrchestra
autoraters under `vendor/paper_orchestra/`.

The `vendor/paper_orchestra/upstream_search/` subtree additionally contains
the upstream PaperOrchestra literature-search agent and Semantic Scholar
utility (Google LLC, Apache-2.0), pinned from the upstream repository. The
Harbor sidecar wraps the upstream Semantic Scholar enrichment contract without
printing or persisting API keys.
