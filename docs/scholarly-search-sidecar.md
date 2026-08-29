# Scholarly-search sidecar

`paperbench_harbor.common.scholarly_search` provides a dependency-free,
cutoff-aware sidecar over a JSONL index. Each line contains at least `title`
and may contain `abstract`, `year`, `url`, and `source`.

Start it with:

```bash
python scripts/scholarly_search_sidecar.py \
  --index path/to/scholarly_search.jsonl \
  --host 0.0.0.0 --port 8765
```

Query it with `/search?q=audio+visual&cutoff_year=2024&limit=10`. Results are
filtered before ranking, then sorted by token overlap, publication year, and
title. This makes a fixed index and cutoff reproducible. The sidecar does not
silently fetch the live web; refreshing the index is an explicit upstream-data
step and should be recorded as an artifact.

This is the controlled retrieval primitive. Full upstream parity additionally
requires populating a benchmark-approved index and wiring the agent container
to the sidecar endpoint; arbitrary live internet access is not equivalent to
that reproducible setup.
