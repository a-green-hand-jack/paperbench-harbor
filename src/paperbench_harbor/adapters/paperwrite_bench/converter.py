from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


SUPPORTED_OVERVIEWS = {"short", "long"}


@dataclass(frozen=True)
class PaperWriteBenchConversionConfig:
    source: Path
    output_dir: Path
    overview: str = "short"
    limit: int | None = None
    overwrite: bool = False
    upstream_revision: str | None = None


def convert_paperwrite_bench(config: PaperWriteBenchConversionConfig) -> int:
    """Convert PaperWrite-Bench samples into Harbor tasks.

    The first implementation target is the official local directory layout reconstructed
    by PaperRecon's Hugging Face download helper.
    """

    if config.overview not in SUPPORTED_OVERVIEWS:
        allowed = ", ".join(sorted(SUPPORTED_OVERVIEWS))
        raise ValueError(f"Unsupported overview {config.overview!r}; expected one of: {allowed}")

    raise NotImplementedError(
        "PaperWrite-Bench conversion is not implemented yet. "
        "See docs/implementation-plan.md for the staged implementation sequence."
    )
