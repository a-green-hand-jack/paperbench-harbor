# Hello World Smoke Test

The Hello World task is the short end-to-end gate for a PaperBench Harbor
benchmark change. It validates the actual Harbor pathway, not a mocked client:

1. Harbor loads a normal task directory and starts its writer environment.
2. The Codex agent receives the task instruction and the mounted brief.
3. Codex writes `/workspace/submission/main.tex` and `references.bib`.
4. The isolated verifier applies the shared submission contract, recompiles
   the paper and returns its binary reward.
5. A task-specific verifier assertion confirms that the submission contains
   the brief's required signal, title, sections and citation.

It deliberately does **not** establish the semantic validity or protocol
coverage of every real benchmark task. Keep the contract, fidelity and
deterministic-regeneration checks, plus representative real-agent trials, as
separate release gates.

## Generate and run

Run from a checkout of this repository after configuring the host's Codex
provider credentials. If the host uses the Codex CLI's ChatGPT OAuth login,
set `CODEX_FORCE_AUTH_JSON=1` for this process only. Harbor injects the
existing `~/.codex/auth.json` into the ephemeral agent container at runtime;
it must never be copied into the task or repository. If the host instead uses
an API key, omit that prefix and export `OPENAI_API_KEY` in the job shell.

```bash
SMOKE_ROOT=/tmp/paperbench-harbor-smoke
JOB_ROOT=/path/to/harbor-jobs

uv run paperbench-harbor hello-world --output-dir "$SMOKE_ROOT"
CODEX_FORCE_AUTH_JSON=1 uv run --extra harbor harbor run \
  --jobs-dir "$JOB_ROOT" \
  --path "$SMOKE_ROOT/hello-world/hello-world-0001" \
  --agent codex \
  --model openai/gpt-5.6-terra \
  --ak reasoning_effort=medium \
  --yes --n-concurrent 1 \
  --job-name paperbench-hello-world-terra-medium
```

The expected result is a completed Harbor job with binary reward `1`. Retain
the job directory and report:

- the Git commit that generated the task;
- Harbor and Codex versions;
- `openai/gpt-5.6-terra` and `reasoning_effort=medium`;
- wall-clock duration, with cold image/data setup distinguished from the
  warm-cache task run;
- the binary reward and paths to the agent and verifier logs.

The target for a warm-cache run is five minutes or less. A run that exceeds
the target remains useful evidence, but should be reported as a performance
failure rather than silently treated as a passing smoke gate.

## Release

`paperbench-harbor hello-world --output-dir <release-root>` places the task at
`hello-world/hello-world-0001`. Include that directory in the next
`Paper-Writing-Exam` Hugging Face dataset release, record its immutable commit
and tag, and then run the same command from that immutable release. The
published task must not diverge from the generator output used for the local
gate.
