from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

SUPPORTED_PROTOCOLS = {"sparse-plotoff", "sparse-ploton", "dense-plotoff"}


@dataclass(frozen=True)
class PaperWritingBenchConversionConfig:
    source: Path
    output_dir: Path
    protocol: str = "sparse-plotoff"
    limit: int | None = None
    overwrite: bool = False
    upstream_revision: str | None = None


def convert_paperwritingbench(config: PaperWritingBenchConversionConfig) -> int:
    """Convert PaperWritingBench samples into Harbor tasks.

    The implementation intentionally starts as a guarded stub. The first development
    milestone is to bind the exact upstream release schema and test public/private
    material selection on a small smoke subset.
    """

    if config.protocol not in SUPPORTED_PROTOCOLS:
        allowed = ", ".join(sorted(SUPPORTED_PROTOCOLS))
        raise ValueError(f"Unsupported protocol {config.protocol!r}; expected one of: {allowed}")

    raise NotImplementedError(
        "PaperWritingBench conversion is not implemented yet. "
        "See docs/implementation-plan.md for the staged implementation sequence."
    )
