# PaperOrchestra Sidecar

PaperWritingBench tasks ship the pinned complete PaperOrchestra pipeline in
`environment/paper_orchestra/` and the sidecar server as
`/workspace/paper_orchestra_sidecar.py`.

That file is a copy of `src/paperbench_harbor/sidecar/server.py`, which runs
standalone from its own `__main__` block. It is **not**
`scripts/paper_orchestra_sidecar.py`; that launcher imports
`paperbench_harbor.sidecar.server` and is host-only, so it would fail inside a
task container, where this project is never installed.

The generated Docker environment starts the sidecar automatically before the
Harbor agent command through `/workspace/entrypoint.sh`. No interactive
container operation is required.

The sidecar readiness endpoint is:

```text
GET /healthz
```

The environment entrypoint waits for this endpoint before executing the agent.

The upstream pipeline is copied from `google-research/paper-orchestra`; the
sidecar is only an HTTP adapter around its search components.

The sidecar exposes the two upstream search stages:

- `POST /v1/discover`: Gemini Google Search discovery, using the upstream
  `HybridLiteratureAgent` prompt and candidate schema. Requires the upstream
  Gemini credentials (`GEMINI_API_KEY` or Vertex AI settings).
- `POST /v1/enrich-title`: Semantic Scholar title search, fuzzy matching, and
  publication cutoff filtering from the upstream `scholar_utils.py`.

Example enrichment request:

```json
{"title": "An exact paper title", "year_hint": 2024,
 "cutoff_date": "2024-11"}
```

The sidecar does not print or persist API keys. The PaperOrchestra revision and
Apache-2.0 attribution are recorded in `vendor/NOTICE.md`. PaperWrite-Bench
does not receive this component because its upstream protocol has no scholarly
search stage.
