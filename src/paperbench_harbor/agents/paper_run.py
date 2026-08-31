"""Harbor installed agent wrapping the pinned ``paper-run`` harness.

Registering
-----------
Run a task with the custom import path::

    harbor run --path <task> \
        --agent paperbench_harbor.agents.paper_run:PaperRun \
        --model openai/gpt-5.6-sol \
        --agent-kwarg variant=high

The agent installs Node, the pinned OpenCode runtime, and the pinned
``paper-run`` release into the task container, initializes a local writing
repository from the task's public materials, runs the autonomous headless
pipeline exactly once, and exports the resulting ``paper/`` tree into the
shared submission contract
(``/workspace/submission/{main.tex,references.bib,figures/}``).

Credentials are never baked into files or logs.  Provider credentials
(``OPENAI_API_KEY``, and optionally ``OPENAI_BASE_URL`` for a custom
OpenAI-compatible endpoint) flow from Harbor's ``--agent-env`` into the exec
environment; only the non-secret base URL is written into OpenCode's user
config so a gateway endpoint is reachable.
"""

from __future__ import annotations

import json
import os
from typing import ClassVar

from harbor.agents.installed.base import BaseInstalledAgent, CliFlag
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext

from paperbench_harbor.agents import paper_run_core as core


class PaperRun(BaseInstalledAgent):
    """Run the pinned ``paper-run`` paper-writing harness in the container."""

    SUPPORTS_ATIF: bool = False
    SUPPORTS_RESUME: bool = False

    CLI_FLAGS: ClassVar[list[CliFlag]] = [
        CliFlag("variant", cli="--variant", type="str"),
    ]

    @staticmethod
    def name() -> str:
        return "paper-run"

    def version(self) -> str | None:
        return core.PAPER_RUN_VERSION

    # -- install ----------------------------------------------------------

    def _agent_env_value(self, key: str) -> str | None:
        """Resolve a value from extra_env first, then the host environment."""
        if key in self.extra_env:
            return self.extra_env[key]
        return os.environ.get(key)

    async def install(self, environment: BaseEnvironment) -> None:
        """Install Node, OpenCode, and paper-run into the task container."""
        # A neutral git identity is required because paper-run init commits.
        await self.exec_as_agent(
            environment,
            command=(
                'git config --global user.email "paper-run@localhost" && '
                'git config --global user.name "paper-run"'
            ),
        )
        for command in core.node_install_commands():
            await self.exec_as_agent(environment, command=command, timeout_sec=900)
        for command in core.opencode_install_commands():
            await self.exec_as_agent(environment, command=command, timeout_sec=900)
        for command in core.paper_run_install_commands():
            await self.exec_as_agent(environment, command=command, timeout_sec=1800)
        await self.exec_as_agent(environment, command=core.version_check_command())

    # -- run --------------------------------------------------------------

    @property
    def _model(self) -> str | None:
        return self.model_name or self._agent_env_value("PAPER_RUN_MODEL")

    @property
    def _variant(self) -> str | None:
        # Resolve the declared CLI_FLAGS kwarg without depending on Harbor
        # internals; fall back to the constructor kwargs, then an env var.
        flags = getattr(self, "_resolved_flags", None) or {}
        variant = flags.get("variant")
        if variant is None:
            variant = getattr(self, "_flag_kwargs", {}).get("variant")
        return variant or self._agent_env_value("PAPER_RUN_VARIANT")

    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        """Build the brief, initialize, run the pipeline once, then export."""
        brief = core.build_brief(instruction)
        await self.exec_as_agent(
            environment,
            command=core.write_brief_command(brief),
            timeout_sec=120,
        )

        base_url = self._agent_env_value("OPENAI_BASE_URL")
        config_command = core.opencode_user_config_command(base_url, self._model)
        if config_command:
            await self.exec_as_agent(environment, command=config_command, timeout_sec=120)

        # Initialize (network template fetch). Model is fixed into the
        # project opencode.json so paper-run start's availability check works.
        await self.exec_as_agent(
            environment,
            command=core.init_command(model=self._model),
            timeout_sec=1200,
        )

        # Add the writer's narrowly scoped headless bash permissions to the
        # generated project config. The materials checkpoint below commits it.
        await self.exec_as_agent(
            environment,
            command=core.patch_opencode_project_command(),
            timeout_sec=60,
        )

        # Stage the public benchmark materials into the repo so the material
        # assessment can see them, and commit with a manual checkpoint.
        await self.exec_as_agent(
            environment,
            command=core.stage_materials_command(),
            timeout_sec=300,
        )

        # Exactly one autonomous headless pipeline start. The stage multiplier
        # is a supported paper-run option, not a source patch workaround.
        await self.exec_as_agent(
            environment,
            command=core.start_command(self._model, self._variant),
            timeout_sec=core.START_TIMEOUT_SEC,
        )

        # Export into the shared submission contract + trial artifacts.
        for command in core.export_commands():
            await self.exec_as_agent(environment, command=command, timeout_sec=300)
        await self.exec_as_agent(
            environment,
            command=core.submission_ready_command(),
            timeout_sec=60,
        )

        # Surface a compact run record on the context.
        status = await self.exec_as_agent(
            environment,
            command=core.status_command(),
            timeout_sec=60,
        )
        self._record_run(context, status.stdout or "")

    # -- post-run ---------------------------------------------------------

    @staticmethod
    def _record_run(context: AgentContext, status_output: str) -> None:
        """Best-effort: annotate the context with the paper-run status JSON."""
        try:
            data = json.loads(status_output)
        except json.JSONDecodeError:
            data = {"raw": status_output.strip()}
        metadata = dict(getattr(context, "metadata", {}) or {})
        metadata["paper_run"] = data
        context.metadata = metadata
