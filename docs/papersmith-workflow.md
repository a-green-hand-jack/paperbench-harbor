# PaperSmith Workflow

See [README](../README.md) for the current user interface and [DEV](../DEV.md)
for Docker acceptance. Issue #71 replaces the former domain-first workflow.

`proposal -> gate1 -> materials -> gate2 -> convert -> gate3 -> deliver`

One `papersmith create` invocation performs the full sequence. Separate review
sessions produce schema-validated verdicts tied to current artifacts. No manual
approval exchange, domain requirement, pre-existing oracle or downstream writer
trial is needed. Count refers to admitted deliveries and rejected candidates are
replenished. `status`, `resume` and `validate` operate on durable checkpoints.
