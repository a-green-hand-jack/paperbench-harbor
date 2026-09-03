"""Registry for PaperRecon Harbor conversion identities.

All PaperRecon domains use the same PaperWrite-Bench layout converter; the
registry keeps the public configuration id and domain-specific identity in one
place so CLI, fidelity and release tooling cannot drift apart.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from paperbench_harbor.adapters.paperwrite_bench.converter import PaperWriteBenchConversionConfig


@dataclass(frozen=True)
class PaperReconAdapter:
    domain: str
    config: str
    benchmark: str
    build_config: Callable[..., PaperWriteBenchConversionConfig]


def _adapters() -> dict[str, PaperReconAdapter]:
    from paperbench_harbor.adapters.chemistry_paperrecon.harbor import (
        BENCHMARK as chemistry_benchmark,
    )
    from paperbench_harbor.adapters.chemistry_paperrecon.harbor import (
        chemistry_paperrecon_conversion_config,
    )
    from paperbench_harbor.adapters.lifesci_paperrecon.harbor import (
        BENCHMARK as lifesci_benchmark,
    )
    from paperbench_harbor.adapters.lifesci_paperrecon.harbor import (
        lifesci_paperrecon_conversion_config,
    )
    from paperbench_harbor.adapters.mathematics_paperrecon.harbor import (
        BENCHMARK as mathematics_benchmark,
    )
    from paperbench_harbor.adapters.mathematics_paperrecon.harbor import (
        mathematics_paperrecon_conversion_config,
    )
    from paperbench_harbor.adapters.physics_paperrecon.harbor import (
        BENCHMARK as physics_benchmark,
    )
    from paperbench_harbor.adapters.physics_paperrecon.harbor import (
        physics_paperrecon_conversion_config,
    )

    return {
        "lifesci": PaperReconAdapter(
            "lifesci", "lifesci-paperrecon-short", lifesci_benchmark,
            lifesci_paperrecon_conversion_config,
        ),
        "physics": PaperReconAdapter(
            "physics", "physics-paperrecon-short", physics_benchmark,
            physics_paperrecon_conversion_config,
        ),
        "chemistry": PaperReconAdapter(
            "chemistry", "chemistry-paperrecon-short", chemistry_benchmark,
            chemistry_paperrecon_conversion_config,
        ),
        "mathematics": PaperReconAdapter(
            "mathematics", "mathematics-paperrecon-short", mathematics_benchmark,
            mathematics_paperrecon_conversion_config,
        ),
    }


def paperrecon_domains() -> tuple[str, ...]:
    return tuple(_adapters())


def get_paperrecon_adapter(domain: str) -> PaperReconAdapter:
    try:
        return _adapters()[domain]
    except KeyError as error:
        raise ValueError(
            f"unknown PaperRecon domain {domain!r}; choose from {', '.join(paperrecon_domains())}"
        ) from error


def paperrecon_conversion_config(
    domain: str,
    *,
    source: Path,
    output_dir: Path,
    upstream_revision: str | None,
    overview: str = "short",
    limit: int | None = None,
    overwrite: bool = False,
) -> PaperWriteBenchConversionConfig:
    return get_paperrecon_adapter(domain).build_config(
        source=source,
        output_dir=output_dir,
        upstream_revision=upstream_revision,
        overview=overview,
        limit=limit,
        overwrite=overwrite,
    )
