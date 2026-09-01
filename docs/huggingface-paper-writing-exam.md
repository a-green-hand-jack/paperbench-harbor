# Hugging Face Paper-Writing Exam Card

The public dataset card is maintained in the Hugging Face repository:

<https://huggingface.co/datasets/Jack-Jieke-Wu/Paper-Writing-Exam>

## Viewer behavior

The card sets:

```yaml
viewer: false
```

`Paper-Writing-Exam` contains executable Harbor task trees, including nested
environment, solution, and verifier files. It is not a conventional tabular
dataset with compatible `train`, `validation`, and `test` splits, so the Dataset
Viewer is intentionally disabled. This does not change task downloads or
Harbor evaluation.

## Direct task fetch

Install the Hugging Face CLI and Harbor, then use an include pattern to fetch
only one task. Pass the resulting local task directory to Harbor; the full
dataset does not need to be downloaded first:

```bash
hf download Jack-Jieke-Wu/Paper-Writing-Exam \
  --repo-type dataset \
  --revision bfe2471c41f416d877e74bfa73cf0f29165c7567 \
  --include 'lifesci-paperrecon-short/lspr-0001/**' \
  --local-dir ./paper-writing-exam

harbor run \
  --path ./paper-writing-exam/lifesci-paperrecon-short/lspr-0001 \
  --agent codex \
  --model <provider>/<model> \
  --yes --n-concurrent 1
```

Replace the configuration subdirectory and task ID in both the `--include`
glob and the Harbor `--path` for another configuration:

| Configuration | Tree subdirectory | Example task |
|---|---|---|
| PaperWrite-Bench | `paperwrite-bench-short` | `pwb-0001` |
| PaperWritingBench | `paperwritingbench-sparse-plotoff` | `pwbw-0001` |
| LifeSci-PaperRecon | `lifesci-paperrecon-short` | `lspr-0001` |

The release commit is
`bfe2471c41f416d877e74bfa73cf0f29165c7567`; use it for reproducibility, or
verify that `v0.3.1` still resolves to that commit.
