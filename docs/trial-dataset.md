# Trial Exporter Maintenance

The normative user documentation for released trajectories is the
[Paper-Writing-Exam-Trials dataset card](https://huggingface.co/datasets/Jack-Jieke-Wu/Paper-Writing-Exam-Trials).
It explains retrieval, formats, legitimate analyses, and the relationship to
the task and source-archive datasets. This document is only for maintainers
exporting a new trial.

## Export boundary

The exporter accepts one completed Harbor trial and the task's verifier-only
`source_manifest.json`. It produces a sanitized archive, summary records, and
an immutable provenance link. It must reject credentials, task solutions,
private verifier fixtures, ground-truth papers, and unrelated host files.

Use the `paperbench-trial-export` plugin where available, or the manual
fallback:

```bash
python3 scripts/export_trial.py \
  --trial-dir <harbor-trial-dir> \
  --output-dir <trial-dataset-staging-dir> \
  --private-manifest <task>/tests/private/source_manifest.json \
  --task-id <task-id> \
  --benchmark <benchmark-name> \
  --protocol <protocol> \
  --benchmark-hf-revision <immutable-task-revision> \
  --harbor-repo-commit <paperbench-harbor-revision> \
  --agent-name <agent> \
  --agent-version <version> \
  --integration-commit <integration-revision> \
  --model <provider/model> \
  --provider <provider> \
  --agent-config-file <non-secret-config.json>
```

Review the generated `data/`, `manifests/`, and `artifacts/` files before a
separate Hugging Face upload. Record the returned immutable trial-dataset
revision in the release evidence. A trial archive never changes the benchmark
task revision it references.

## Checks

Before upload, run the exporter tests and inspect the archive allowlist. The
task's source manifest is used to verify provenance but is never copied into
the public trial dataset. See [the task dataset card](https://huggingface.co/datasets/Jack-Jieke-Wu/Paper-Writing-Exam)
for task identity and [the source archive card](https://huggingface.co/datasets/Jack-Jieke-Wu/Paper-Writing-Exam-Source-Archive)
for source-input provenance.
