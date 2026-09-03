# Hugging Face Card Maintenance

The release-facing dataset cards are versioned with this repository under
`packaging/huggingface/` and are published to their corresponding Hugging Face
dataset repositories:

| Card source | Published dataset | Owns |
|---|---|---|
| `paper-writing-exam/README.md` | `Paper-Writing-Exam` | Dataset relationship, task collection/selection, task use, and material boundary |
| `paper-writing-exam-trials/README.md` | `Paper-Writing-Exam-Trials` | Trajectory retrieval, schema, use, and limitations |
| `paper-writing-exam-source-archive/README.md` | `Paper-Writing-Exam-Source-Archive` | Task-paper registry, original-input archive, and license/provenance boundary |

Published cards: [Paper-Writing-Exam](https://huggingface.co/datasets/Jack-Jieke-Wu/Paper-Writing-Exam),
[Paper-Writing-Exam-Trials](https://huggingface.co/datasets/Jack-Jieke-Wu/Paper-Writing-Exam-Trials),
and [Paper-Writing-Exam-Source-Archive](https://huggingface.co/datasets/Jack-Jieke-Wu/Paper-Writing-Exam-Source-Archive).

Before a documentation-only upload, check all task counts, immutable revisions,
tags, and source-archive links against the actual release manifest. The cards
are the only detailed user-facing manuals. GitHub documentation should link to
them and describe construction, validation, publishing, and maintenance.
