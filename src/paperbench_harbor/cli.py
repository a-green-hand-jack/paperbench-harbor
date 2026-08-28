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
    protocol: Annotated[str, typer.Option()] = "sparse-plotoff",
    limit: Annotated[int | None, typer.Option(min=1)] = None,
    overwrite: Annotated[bool, typer.Option()] = False,
) -> None:
    """Convert PaperWritingBench samples into Harbor tasks."""
    config = PaperWritingBenchConversionConfig(
        source=source,
        output_dir=output_dir,
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
    overview: Annotated[str, typer.Option()] = "short",
    limit: Annotated[int | None, typer.Option(min=1)] = None,
    overwrite: Annotated[bool, typer.Option()] = False,
) -> None:
    """Convert PaperWrite-Bench samples into Harbor tasks."""
    config = PaperWriteBenchConversionConfig(
        source=source,
        output_dir=output_dir,
        overview=overview,
        limit=limit,
        overwrite=overwrite,
    )
    converted = convert_paperwrite_bench(config)
    typer.echo(f"Converted {converted} PaperWrite-Bench task(s).")


if __name__ == "__main__":
    app()
