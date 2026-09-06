# PaperSmith Workflow

See [README](../README.md) for the current user interface and [DEV](../DEV.md)
for Docker acceptance. Issue #71 replaces the former domain-first workflow.

`proposal -> gate1 -> materials -> gate2 -> convert -> gate3 -> deliver`

One `papersmith create` invocation performs the full sequence. Separate review
sessions produce schema-validated verdicts tied to current artifacts. No manual
approval exchange, domain requirement, pre-existing oracle or downstream writer
evaluation is needed. Actual Harbor oracle=1 and nop=0 trials are mandatory at gate3,
followed by the independent scientific assessment. Count refers to admitted deliveries;
discovery replenishes rejected candidates, fixed `--paper` allowlists block rather
than replace. Start with count one, then explicitly resume to five after reviewing it.

The controller locks a full-manuscript objective unless the user deliberately selects
`--task-kind summary`. Every phase receives the same contract and candidate's original
count scope. Identifier policy is explicit and cannot waive asset attribution.
Relevant source items have include/substitute/exclude/unavailable dispositions with
reasons, not merely broad coverage assurances. Structured tables preserve exact cells,
anchors, units, caption, notes, missing-value and precision policies and original images
when available and lawful. Public starter TeX and bibliography compile independently;
that is not an accepted manuscript. The synthetic oracle uses only those public inputs.

`status` reads a quick checkpoint snapshot; `validate` authoritatively checks current
artifacts, canonical identity, read-scope receipts and acceptance evidence. Compile
failures retain the oracle response, whereas scientific repairs can regenerate it.
Historical outputs are never edited to acquire new approval. Delivery's artifact index
links original material, coverage, starter proof, three reviews and real oracle/nop proof.
