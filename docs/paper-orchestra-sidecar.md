# PaperOrchestra Sidecar

PaperWritingBench tasks ship the pinned PaperOrchestra literature-search
components in `environment/paper_orchestra_search/` and the sidecar launcher as
`/workspace/paper_orchestra_sidecar.py`.

Start the sidecar in the writer environment:

```bash
python3 /workspace/paper_orchestra_sidecar.py --host 127.0.0.1 --port 8765 &
```

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
