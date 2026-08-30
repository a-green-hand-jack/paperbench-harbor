from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from paperbench_harbor.adapters.paperwrite_bench.converter import (
    PaperWriteBenchConversionConfig,
    convert_paperwrite_bench,
)
from paperbench_harbor.adapters.paperwritingbench.converter import (
    PaperWritingBenchConversionConfig,
    convert_paperwritingbench,
)

app = typer.Typer(
    no_args_is_help=True,
    help="Convert scientific-paper writing benchmarks into Harbor task datasets.",
)


@app.command("paperwritingbench")
def paperwritingbench_command(
    source: Annotated[Path, typer.Option(exists=True, file_okay=False, resolve_path=True)],
    output_dir: Annotated[Path, typer.Option(resolve_path=True)],
    upstream_revision: Annotated[str, typer.Option(help="Pinned upstream PaperWritingBench revision; required")],
    protocol: Annotated[str, typer.Option()] = "sparse-plotoff",
    limit: Annotated[int | None, typer.Option(min=1)] = None,
    overwrite: Annotated[bool, typer.Option()] = False,
) -> None:
    """Convert PaperWritingBench samples into Harbor tasks."""
    if not upstream_revision.strip():
        raise typer.BadParameter("--upstream-revision must be a non-empty revision")
    config = PaperWritingBenchConversionConfig(
        source=source,
        output_dir=output_dir,
        upstream_revision=upstream_revision.strip(),
        protocol=protocol,
        limit=limit,
        overwrite=overwrite,
    )
    converted = convert_paperwritingbench(config)
    typer.echo(f"Converted {converted} PaperWritingBench task(s).")


@app.command("paperwrite-bench")
def paperwrite_bench_command(
    source: Annotated[Path, typer.Option(exists=True, file_okay=False, resolve_path=True)],
    output_dir: Annotated[Path, typer.Option(resolve_path=True)],
    upstream_revision: Annotated[str, typer.Option(help="Pinned upstream PaperWrite-Bench revision; required")],
    overview: Annotated[str, typer.Option()] = "short",
    limit: Annotated[int | None, typer.Option(min=1)] = None,
    overwrite: Annotated[bool, typer.Option()] = False,
) -> None:
    """Convert PaperWrite-Bench samples into Harbor tasks."""
    if not upstream_revision.strip():
        raise typer.BadParameter("--upstream-revision must be a non-empty revision")
    config = PaperWriteBenchConversionConfig(
        source=source,
        output_dir=output_dir,
        upstream_revision=upstream_revision.strip(),
        overview=overview,
        limit=limit,
        overwrite=overwrite,
    )
    converted = convert_paperwrite_bench(config)
    typer.echo(f"Converted {converted} PaperWrite-Bench task(s).")


@app.command("lifesci-paperrecon")
def lifesci_paperrecon_command(
    source: Annotated[Path, typer.Option(exists=True, file_okay=False, resolve_path=True)],
    output_dir: Annotated[Path, typer.Option(resolve_path=True)],
    upstream_revision: Annotated[
        str, typer.Option(help="Pinned construction-pipeline revision; required")
    ],
    overview: Annotated[str, typer.Option()] = "short",
    limit: Annotated[int | None, typer.Option(min=1)] = None,
    overwrite: Annotated[bool, typer.Option()] = False,
) -> None:
    """Convert a LifeSci-PaperRecon source corpus into Harbor tasks.

    The corpus is produced by `scripts/build_lifesci_paperrecon_source.py`; this
    command reuses the PaperWrite-Bench converter with biology identity
    metadata and without the vendored official-metrics grader.
    """
    from paperbench_harbor.adapters.lifesci_paperrecon.harbor import (
        lifesci_paperrecon_conversion_config,
    )

    if not upstream_revision.strip():
        raise typer.BadParameter("--upstream-revision must be a non-empty revision")
    config = lifesci_paperrecon_conversion_config(
        source=source,
        output_dir=output_dir,
        upstream_revision=upstream_revision.strip(),
        overview=overview,
        limit=limit,
        overwrite=overwrite,
    )
    converted = convert_paperwrite_bench(config)
    typer.echo(f"Converted {converted} LifeSci-PaperRecon task(s).")


if __name__ == "__main__":
    app()
