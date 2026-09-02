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
from paperbench_harbor.fidelity.dataset import (
    DatasetAuditError,
    audit_dataset,
    format_failures,
)

#: Shared help text, so the three commands describe the flag identically.
_AUDIT_HELP = (
    "Run the per-task fidelity audit against --source before reporting success. "
    "Conversion that silently drops or rewrites upstream content is the failure "
    "this catches, so it is on by default. Determinism is not checked here; that "
    "costs two more full conversions and stays in scripts/audit_fidelity.py."
)


def _audit_or_exit(*, benchmark: str, source: Path, output_dir: Path, protocol: str) -> None:
    """Audit a freshly converted dataset, and fail the command if it does not pass.

    A conversion command that exits 0 on a tree the audit would reject is the
    thing this prevents: the audit used to be a separate command an operator had
    to remember to run, so a broken conversion looked exactly like a good one.
    """
    try:
        reports = audit_dataset(
            benchmark=benchmark, source=source, dataset=output_dir, protocol=protocol
        )
    except DatasetAuditError as exc:
        typer.echo(f"fidelity audit could not run: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    failures = format_failures(reports)
    if failures:
        typer.echo(failures, err=True)
        raise typer.Exit(code=1)
    typer.echo(f"Fidelity audit passed for {len(reports)} task(s).")


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
    audit: Annotated[bool, typer.Option(help=_AUDIT_HELP)] = True,
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
    if audit:
        _audit_or_exit(
            benchmark="PaperWritingBench",
            source=source,
            output_dir=output_dir,
            protocol=protocol,
        )


@app.command("paperwrite-bench")
def paperwrite_bench_command(
    source: Annotated[Path, typer.Option(exists=True, file_okay=False, resolve_path=True)],
    output_dir: Annotated[Path, typer.Option(resolve_path=True)],
    upstream_revision: Annotated[str, typer.Option(help="Pinned upstream PaperWrite-Bench revision; required")],
    overview: Annotated[str, typer.Option()] = "short",
    limit: Annotated[int | None, typer.Option(min=1)] = None,
    overwrite: Annotated[bool, typer.Option()] = False,
    audit: Annotated[bool, typer.Option(help=_AUDIT_HELP)] = True,
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
    if audit:
        _audit_or_exit(
            benchmark="PaperWrite-Bench",
            source=source,
            output_dir=output_dir,
            protocol=overview,
        )


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
    audit: Annotated[bool, typer.Option(help=_AUDIT_HELP)] = True,
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
    if audit:
        from paperbench_harbor.adapters.lifesci_paperrecon.harbor import BENCHMARK

        _audit_or_exit(
            benchmark=BENCHMARK, source=source, output_dir=output_dir, protocol=overview
        )


if __name__ == "__main__":
    app()
