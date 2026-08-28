#!/usr/bin/env python3
"""Minimal deterministic verifier for the first Harbor smoke task."""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


def main() -> None:
    submission = Path(sys.argv[1] if len(sys.argv) > 1 else "/workspace/submission")
    main_tex = submission / "main.tex"
    bibliography = submission / "references.bib"
    if not main_tex.is_file():
        fail("main.tex is missing")
    if not bibliography.is_file():
        fail("references.bib is missing")
    if not re.search(r"\\documentclass\s*\{", main_tex.read_text(encoding="utf-8")):
        fail("main.tex is not a LaTeX document")
    if "\\end{document}" not in main_tex.read_text(encoding="utf-8"):
        fail("main.tex has no document terminator")
    with tempfile.TemporaryDirectory(prefix="harbor-compile-") as build_dir:
        build = Path(build_dir)
        (build / "main.tex").write_text(main_tex.read_text(encoding="utf-8"), encoding="utf-8")
        (build / "references.bib").write_text(bibliography.read_text(encoding="utf-8"), encoding="utf-8")
        commands = [
            ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "main.tex"],
            ["bibtex", "main"],
            ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "main.tex"],
            ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "main.tex"],
        ]
        for command in commands:
            result = subprocess.run(command, cwd=build, capture_output=True, text=True)
            if result.returncode:
                fail(f"command failed: {' '.join(command)}\n{result.stdout}\n{result.stderr}")
        pdf = build / "main.pdf"
        if not pdf.is_file() or pdf.stat().st_size == 0:
            fail("recompiled PDF is missing or empty")
    print("PASS: submission structure and restricted LaTeX compilation")


if __name__ == "__main__":
    main()
