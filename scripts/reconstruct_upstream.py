#!/usr/bin/env python3
"""Reconstruct the PaperWrite-Bench local directory layout from Hugging Face.

Mirrors PaperRecon's `paper_recon/common/hf_download.py` so conversion can run
against a stable on-disk layout without depending on the upstream package.

Usage:
    uv run --extra datasets scripts/reconstruct_upstream.py --papers paper_1 paper_2
"""
from __future__ import annotations

import argparse
import io
import tarfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = REPO_ROOT / "upstream-data" / "PaperWrite-Bench"
DEFAULT_REPO_ID = "hal-utokyo/PaperWrite-Bench"


def _write_text(path: Path, content: str) -> None:
    if content:
        path.write_text(content, encoding="utf-8")


def reconstruct_paper(paper_dir: Path, sample: dict) -> None:
    original = paper_dir / "original"
    resources = paper_dir / "resources"
    original.mkdir(parents=True, exist_ok=True)
    resources.mkdir(parents=True, exist_ok=True)

    config_lines = [
        f"type: {sample['type']}",
        f"num_page: {sample['num_page']}",
        f"column: {sample['column']}",
        f"conference: {sample['conference']}",
    ]
    (original / "config.yaml").write_text("\n".join(config_lines) + "\n", encoding="utf-8")

    _write_text(original / "main.tex", sample["gt_tex"])
    if sample.get("gt_pdf"):
        (original / "main.pdf").write_bytes(sample["gt_pdf"])

    _write_text(resources / "template.tex", sample["template_tex"])
    _write_text(resources / "research_overview_short.md", sample["research_overview_short"])
    _write_text(resources / "research_overview_long.md", sample["research_overview_long"])
    _write_text(resources / "references.bib", sample["references_bib"])
    _write_text(resources / "figure_summary.txt", sample["figure_summary"])
    _write_text(resources / "table_summary.txt", sample["table_summary"])
    if sample.get("eval_points"):
        _write_text(resources / "eval_points.json", sample["eval_points"])

    figures_dir = resources / "figures"
    figures_dir.mkdir(exist_ok=True)
    for filename, image in zip(sample["figure_filenames"], sample["figure_images"]):
        ext = Path(filename).suffix.lower()
        fmt = "PNG" if ext == ".png" else "JPEG"
        image.save(figures_dir / filename, format=fmt)

    tables_dir = resources / "tables"
    tables_dir.mkdir(exist_ok=True)
    for filename, content in zip(sample["table_filenames"], sample["table_contents"]):
        _write_text(tables_dir / filename, content)

    if sample.get("has_code") and sample.get("code_tar_gz"):
        with tarfile.open(fileobj=io.BytesIO(sample["code_tar_gz"]), mode="r:gz") as tar:
            tar.extractall(path=str(resources), filter="data")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-id", default=DEFAULT_REPO_ID)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--papers", nargs="*", help="Only reconstruct these paper ids")
    args = parser.parse_args()

    from datasets import load_dataset

    dataset = load_dataset(args.repo_id, split="test")
    for sample in dataset:
        paper_id = sample["paper_id"]
        if args.papers and paper_id not in args.papers:
            continue
        paper_dir = args.output_dir / paper_id
        if paper_dir.exists() and (paper_dir / "resources" / "template.tex").exists():
            print(f"skip {paper_id}: already reconstructed")
            continue
        print(f"reconstructing {paper_id}")
        reconstruct_paper(paper_dir, sample)


if __name__ == "__main__":
    main()
