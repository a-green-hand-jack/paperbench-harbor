# PaperSmith In Docker

## Current Use

PaperSmith constructs paper-writing reconstruction tasks, not submitted papers
or a general scientific-quality score. Its natural-language entry points are
`papersmith-lifesci`, `papersmith-physics`, `papersmith-chemistry`, and
`papersmith-mathematics` in `.opencode/agent/`. They interpret a request and
invoke the same deterministic programs used by the CLI.

The supported evidence contracts are experimental LifeSci, Physics simulation,
Chemistry synthesis/characterization, and Mathematics theorem/proof
reconstruction. Defaults are one accepted task, serial execution, three build
attempts, 5400 seconds per stage, no upload, and no publication.
See [the workflow](papersmith-workflow.md) for the full request schema and gates.

The runner first validates a structured request. Without `--describe-request`,
it discovers and screens candidates. Two independent verifiers then approve
the exact candidate SHA. Only that approval permits construction, material
review, conversion, fidelity audit, and local staging. Accepted delivery also
needs a real writer trial. Candidate count is not accepted-task count.

## Build And Call

Run from this checkout on a machine with Docker:

```sh
sh scripts/papersmith-docker.sh build

# Actual PaperSmith CLI; explicitly offline, no credentials or model calls.
PAPERSMITH_NETWORK=none sh scripts/papersmith-docker.sh run \
  --domain physics --run-root /runs/physics-01 \
  --research-type simulation --target-count 1 --describe-request

sh scripts/papersmith-docker.sh shell
sh scripts/papersmith-docker.sh exec opencode run --help
```

`run` forwards remaining arguments to `scripts/run_paperrecon_domain.py`.
`exec` forwards a command and arguments without shell evaluation. The wrapper
preserves exit status and uses the caller's UID/GID, with a TTY only when
interactive. Run as your ordinary user, not sudo. `build` accepts Docker build
options, such as `build --build-arg OPENCODE_VERSION=1.18.29`.
`PAPERSMITH_IMAGE` overrides `paperbench-papersmith:dev`.

The image includes Python 3.12, project base/datasets/Harbor/sidecar dependencies,
uv, Ruff, Node 22, npm-installed OpenCode 1.18.29 and Codex 0.153.4, Git, compilers, Poppler,
latexmk, pdfLaTeX, XeLaTeX, LuaLaTeX, science packages, and Biber. The official
OpenCode npm package is `opencode-ai`, not `opencode`. Dependencies resolve at
build time; this is not a fully locked release environment. Paper-specific TeX
packages may require extending the Dockerfile. Optional `bohr` is not installed;
the existing discovery code records LKM failure and uses arXiv/Semantic Scholar.

## Live Source

The repository is mounted **read-only at its existing absolute host path**.
`PYTHONPATH` points to its live `src/` and root; no source is copied into the
image. Host edits are immediately visible to container reads, and the next
Python invocation uses edited code without rebuilding or reinstalling. Already
imported Python modules and running OpenCode agent definitions do not hot-reload:
restart that process. Rebuild only for dependency or Dockerfile changes.

The image's `/opt/venv` contains dependencies, not stale PaperSmith code.
`UV_NO_SYNC=1` and `UV_PROJECT_ENVIRONMENT=/opt/venv` make agent-issued `uv run`
reuse it without writing the checkout or host `.venv`. Build-context allowlisting
excludes source, Git history, caches, and credentials.

| Container path | Storage | Purpose |
| --- | --- | --- |
| `/runs` | `<prefix>-runs` volume | Corpus, downloads, scratch, reviews, evidence |
| `/state/home` | `<prefix>-state` volume | Container HOME, OpenCode/Codex state and sessions |
| `/cache` | `<prefix>-cache` volume | uv and tool caches |
| `/tmp` | Ephemeral tmpfs | Disposable intermediates |
| `/opt/venv` | Read-only image layer | Python dependencies |

The default prefix is `papersmith-<checkout-path-checksum>-<uid>`. Set
`PAPERSMITH_VOLUME_PREFIX` consistently to select a separate experiment, e.g.
`papersmith-physics-dev`. Volumes survive container exit and image rebuilds;
the wrapper never prunes them. Inspect retained files with `exec ls /runs` or
`shell`. Do not delete unique results without the research-asset retirement
procedure. Use different prefixes for concurrent or mutually untrusted runs:
a run can read/write other data in its own volumes.

The whole checkout, including ignored files, is readable. Keep credentials and
unrelated private data out of it. No host home or Docker socket is mounted.
The root filesystem is read-only; workloads have no Linux capabilities, no new
privileges, and a PID limit. A networkless initializer initializes only dedicated
volume directories before execution as the caller UID. No privileged mode,
host PID namespace, exposed port, or host network is enabled by default.

Networking defaults to `bridge`, allowing discovery/model traffic; it is
**not an egress allowlist**. Set `PAPERSMITH_NETWORK=none` to opt out. Only `none` and
`bridge` are accepted; host/container namespace modes and other values are
rejected before Docker operations or volume initialization. Image builds still
need network access to download dependencies. Containers share the
host kernel, not a VM boundary; use a separate execution host for stronger
isolation of adversarial material.

## Authentication

Host settings are not mounted by default, and credential environment variables
are not automatically forwarded. The build and wrapper never read, copy, or
print credential contents; authorized CLI/provider code can read mounted auth.

`PAPERSMITH_HOST_CONFIG=1` enables the supported host configuration mode:

- OpenCode `~/.config/opencode/opencode.jsonc`, package metadata, `node_modules`,
  `lck-provider/*.mjs`, and plugin files are mounted read-only at their host paths.
  The dependency and plugin directories are also mounted under `/state/home`.
- Codex `config.toml` and `auth.json` are mounted read-only from
  `PAPERSMITH_CODEX_HOME`, falling back to `CODEX_HOME`, then `~/.codex`.
  This mode requires both Codex files and the OpenCode config, even for a
  single-CLI invocation; the dependency/plugin directories must also exist.
- `HOME` uses the host path for absolute provider references, but its writable
  contents come from the dedicated state volume's `home` subdirectory, **not
  the host home**. Histories, databases, backups, and whole account directories
  are not imported by this mode.
- `PAPERSMITH_READONLY_PATHS` is a newline-separated allowlist of additional
  absolute files or dependency directories, mounted at the same paths. Add only
  the selected provider's auth file and required external modules/catalogs.
  Broad homes/config roots, ambiguous paths, and Docker sockets are rejected.

Mounting configuration grants access to settings and executable plugins; it does
not automatically supply every referenced account. Mounting auth additionally
grants container code access to that account, including network use on bridge.
Read-only prevents host-file writes, not credential use or disclosure. Review
paths and permissions without printing secrets; never run `opencode debug config`.
Host config edits are visible through bind mounts; restart the CLI to load them,
and use a new wrapper invocation after replacing a mounted file atomically.

Alternatively, without host-config mode, two individual mounts are supported
(mutually exclusive with `PAPERSMITH_HOST_CONFIG=1`):

- `PAPERSMITH_OPENCODE_CONFIG`: absolute path to an operator-reviewed,
  **secret-free** JSON/JSONC file; mounted read-only at `/opt/opencode.json`
  through the supported `OPENCODE_CONFIG` variable.
- `PAPERSMITH_OPENCODE_AUTH`: absolute path to a dedicated OpenCode auth file;
  mounted read-only at `/state/home/.local/share/opencode/auth.json`. It must be
  readable by the caller UID. This exposes the file to container code: use a
  least-privilege account, not a broad multi-account host auth store.

Do not put secret values in arguments, build args, requests, or logs. Config
references need their explicitly authorized dependencies; selecting a model ID
does not install a provider or grant auth access.

### Verified CLI Calls

The operator reported both real calls below successful in the current Ubuntu
session: `exit_code: 0`, `exact_response: true`, `diagnostic_categories: []`.
These are model/auth probes, not physics construction or acceptance evidence.
Re-running them makes real model requests; only paths, never secrets, appear here.

```sh
PAPERSMITH_HOST_CONFIG=1 sh scripts/papersmith-docker.sh exec python scripts/probe_papersmith_clis.py codex --model gpt-6-astra --timeout 60 --output /runs/cli-probes/codex.json

PAPERSMITH_HOST_CONFIG=1 PAPERSMITH_READONLY_PATHS="$HOME/.config/opencode/account-auth/gpt-evelyn.auth.json" sh scripts/papersmith-docker.sh exec python scripts/probe_papersmith_clis.py opencode --model openai-evelyn/gpt-6-astra --timeout 60 --output /runs/cli-probes/opencode.json
```

Read-only auth may not support providers that persist refreshed tokens. For
those flows, explicitly run
`PAPERSMITH_NETWORK=bridge sh scripts/papersmith-docker.sh exec opencode auth login`
interactively without host-config mode or any auth mount. Credentials then live in the private state
volume, never in the image or checkout. Do not archive that volume with run
evidence or use agent tools to read/print its auth file.

The runner defaults to `openai/gpt-5.6-terra` for construction and
`apex-claude/claude-sonnet-5` for material review. These do not inherit the outer
natural-language session's model. Pass `--model` and `--reviewer-model` explicitly
for your configured accounts, and configure the independent verifier's models
separately using its `--help`. Review independence still applies; missing
providers are blockers, not permission for self-review.

## Construction Boundary

After approving discovery cost, use the default bridge network, remove
`--describe-request`, and supply your configured `--model`. See the concrete
commands in [the Chinese development guide](../DEV.md). Follow the verifier and promotion commands in
[the workflow](papersmith-workflow.md), using `/runs/...` for all run, candidate,
and approval paths. In `shell`, `python scripts/...` and `uv run scripts/...`
both use current source. Local staging never uploads.

This isolates **PaperSmith construction**, not downstream Hello World. The
wrapper runs neither Hello World nor pytest. Repository-level `tests/` is
permanently retired; `scripts/test*.py` and generated Harbor task verifiers are
separate and remain intact.

Full runner acceptance still requires a downstream Harbor writer trial. That
trial cannot launch Docker containers here because no Docker daemon/socket is
exposed. Do not add a host socket or bypass trial gates to report success.
Construction/material checks can run here; accepted delivery needs a separately
authorized trial execution surface and actual evidence. Request display proves
CLI/dependency wiring only, not construction, authentication, material quality,
or release readiness.
