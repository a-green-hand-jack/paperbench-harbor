# Contributing

## Principles

1. Preserve benchmark semantics before optimizing convenience.
2. Treat every generated LaTeX project as untrusted input.
3. Keep writer-visible and verifier-only files separated by explicit allowlists.
4. Pin upstream revisions and record file hashes for every generated task.
5. Add smoke fixtures before converting the complete datasets.

## Local checks

```bash
make install
make lint
make test
```

Do not commit generated benchmark datasets, source papers, API keys, evaluator outputs, or model credentials.
